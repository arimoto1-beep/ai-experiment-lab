// Task-specific MCP endpoint. Installed into the official task container by Harbor.
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { spawnSync } from "node:child_process";

const APP = "/app";
const SOCKET = "/ipc/mcp.sock";
const AUDIT = "/tmp/rlfm-operations.jsonl";
const REVIEW = process.env.RLFM_REVIEW_MODE === "1";
const REVIEW_REPORT = "/tmp/rlfm-review-report.json";
const REVIEW_ACK = "/ipc/rlfm-review-ack";
let phase = REVIEW ? "review" : "fix";
const MAX_FILE = 256_000;
const MAX_OUTPUT = 100_000;
const commands = {
  "npm test": ["test"],
  "npm run build": ["run", "build"],
  "npm run submit": ["run", "submit"],
};
const tools = [
  { name: "list_files", description: "List app source and output files.", inputSchema: { type: "object", properties: {}, additionalProperties: false } },
  { name: "read_file", description: "Read an allowed app file.", inputSchema: { type: "object", properties: { path: { type: "string" } }, required: ["path"], additionalProperties: false } },
  { name: "write_file", description: "Replace or create a TypeScript source file. Specs, input data, tests and configuration are read-only.", inputSchema: { type: "object", properties: { path: { type: "string" }, content: { type: "string" } }, required: ["path", "content"], additionalProperties: false } },
  { name: "run_command", description: "Run one fixed npm command: npm test, npm run build, or npm run submit.", inputSchema: { type: "object", properties: { command: { type: "string", enum: Object.keys(commands) } }, required: ["command"], additionalProperties: false } },
];
if (REVIEW) tools.push({ name: "submit_review", description: "Save your complete specification review before any edits. This ends the read-only phase; after host confirmation, fixes become available in this same session.", inputSchema: { type: "object", properties: { report: { type: "string" } }, required: ["report"], additionalProperties: false } });

function checkedPath(value, write = false) {
  if (typeof value !== "string" || !value || value.includes("\\") || value.includes("\0") || value.startsWith("/")) throw Error("invalid path");
  const parts = value.split("/");
  if (parts.some((p) => !p || p === "." || p === "..")) throw Error("invalid path");
  const relative = parts.join("/");
  const readable = relative.startsWith("src/") || relative.startsWith("output/") || ["package.json", "tsconfig.json", "vite.config.ts", "index.html"].includes(relative);
  const writable = relative.startsWith("src/") && !relative.startsWith("src/spec/") && !relative.startsWith("src/data/") && /\.(ts|tsx)$/.test(relative);
  if (!(write ? writable : readable)) throw Error("forbidden path");
  const target = path.join(APP, ...parts);
  const parent = path.dirname(target);
  if (!fs.existsSync(parent) || fs.realpathSync(parent) !== parent) throw Error("invalid path");
  if (fs.existsSync(target) && (fs.lstatSync(target).isSymbolicLink() || fs.realpathSync(target) !== target)) throw Error("invalid path");
  return target;
}

function listFiles(directory, prefix, found) {
  if (!fs.existsSync(directory)) return;
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    if (entry.isSymbolicLink()) continue;
    const relative = `${prefix}/${entry.name}`;
    if (entry.isDirectory()) listFiles(path.join(directory, entry.name), relative, found);
    else if (entry.isFile()) found.push(relative);
  }
}

function reply(text, isError = false) {
  return { content: [{ type: "text", text: String(text).slice(0, MAX_OUTPUT) }], isError };
}

function call(name, args) {
  let status = "ok";
  let detail = "";
  let commandOutput = "";
  try {
    if (!args || typeof args !== "object" || Array.isArray(args)) throw Error("invalid arguments");
    if (name === "list_files" && Object.keys(args).length === 0) {
      const files = [];
      listFiles(path.join(APP, "src"), "src", files);
      listFiles(path.join(APP, "output"), "output", files);
      return reply([...files, "package.json", "tsconfig.json", "vite.config.ts", "index.html"].sort().join("\n"));
    }
    if (name === "read_file" && Object.keys(args).join() === "path") {
      const target = checkedPath(args.path);
      if (!fs.existsSync(target) || !fs.statSync(target).isFile() || fs.statSync(target).size > MAX_FILE) throw Error("file unavailable");
      return reply(fs.readFileSync(target, "utf8"));
    }
    if (name === "write_file" && Object.keys(args).sort().join() === "content,path") {
      if (phase !== "fix") throw Error("review phase is read-only");
      const target = checkedPath(args.path, true);
      if (typeof args.content !== "string" || Buffer.byteLength(args.content) > MAX_FILE) throw Error("invalid content");
      fs.writeFileSync(target, args.content, { encoding: "utf8", flag: "w" });
      detail = args.path;
      return reply("written");
    }
    if (name === "run_command" && Object.keys(args).join() === "command") {
      if (phase !== "fix") throw Error("review phase is read-only");
      const argv = commands[args.command];
      if (!argv) throw Error("unsupported command");
      const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !/(ANTHROPIC|CLAUDE|API_KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|DOCKER)/i.test(key)));
      env.HOME = "/tmp/rlfm-home";
      fs.mkdirSync(env.HOME, { recursive: true });
      const result = spawnSync("npm", argv, { cwd: APP, encoding: "utf8", timeout: 180_000, maxBuffer: 4_000_000, env });
      detail = `${args.command}:exit=${result.status ?? 124}`;
      commandOutput = `exit_code=${result.status ?? 124}\n${result.stdout || ""}${result.stderr || ""}`;
      return reply(commandOutput);
    }
    if (REVIEW && name === "submit_review" && Object.keys(args).join() === "report") {
      if (phase !== "review" || fs.existsSync(REVIEW_REPORT)) throw Error("review already submitted");
      if (typeof args.report !== "string" || !args.report.trim() || Buffer.byteLength(args.report) > MAX_FILE) throw Error("invalid content");
      fs.writeFileSync(REVIEW_REPORT, JSON.stringify({ submittedAt: new Date().toISOString(), report: args.report }) + "\n", { flag: "wx" });
      detail = "review saved; awaiting host confirmation";
      const until = Date.now() + 120_000;
      const sleeper = new Int32Array(new SharedArrayBuffer(4));
      while (!fs.existsSync(REVIEW_ACK) && Date.now() < until) Atomics.wait(sleeper, 0, 0, 200);
      if (!fs.existsSync(REVIEW_ACK)) throw Error("review host acknowledgement timed out");
      phase = "fix";
      return reply("Your read-only review has been saved on the host. Continue in this same session: fix the problems you identified, using the available source-file and development-command tools. Do not request or infer private verifier results.");
    }
    throw Error("unsupported operation");
  } catch (error) {
    status = "denied";
    detail = error instanceof Error && ["invalid arguments", "invalid path", "forbidden path", "file unavailable", "invalid content", "unsupported command", "unsupported operation"].includes(error.message) ? error.message : "operation failed";
    return reply(detail, true);
  } finally {
    fs.appendFileSync(AUDIT, JSON.stringify({ at: new Date().toISOString(), tool: name, status, detail, ...(commandOutput ? { output: commandOutput.slice(0, MAX_OUTPUT) } : {}) }) + "\n");
  }
}

function dispatch(request) {
  if (!Object.hasOwn(request, "id")) return null;
  if (request.method === "initialize") return { jsonrpc: "2.0", id: request.id, result: { protocolVersion: request.params?.protocolVersion || "2025-03-26", capabilities: { tools: {} }, serverInfo: { name: "react-lead-form", version: "1" } } };
  if (request.method === "ping") return { jsonrpc: "2.0", id: request.id, result: {} };
  if (request.method === "tools/list") return { jsonrpc: "2.0", id: request.id, result: { tools } };
  if (request.method === "tools/call") return { jsonrpc: "2.0", id: request.id, result: call(request.params?.name, request.params?.arguments) };
  return { jsonrpc: "2.0", id: request.id, error: { code: -32601, message: "method unavailable" } };
}

fs.rmSync(SOCKET, { force: true });
const server = net.createServer((connection) => {
  let pending = "";
  connection.on("data", (chunk) => {
    pending += chunk.toString("utf8");
    while (pending.includes("\n")) {
      const end = pending.indexOf("\n");
      const line = pending.slice(0, end);
      pending = pending.slice(end + 1);
      try {
        const response = dispatch(JSON.parse(line));
        if (response) connection.write(JSON.stringify(response) + "\n");
      } catch {
        connection.write(JSON.stringify({ jsonrpc: "2.0", id: null, error: { code: -32600, message: "invalid request" } }) + "\n");
      }
    }
  });
  connection.on("end", () => connection.end());
});
server.listen(SOCKET, () => { fs.chmodSync(SOCKET, 0o666); });
