// Narrow MCP worker for experiment #12. The source tree is mounted read-only.
import fs from 'node:fs'
import net from 'node:net'
import path from 'node:path'
import { spawnSync } from 'node:child_process'

const SOURCE = '/source'
const WORK = '/work'
const SOCKET = '/ipc/mcp.sock'
const TESTS = path.join(WORK, 'tests')
const APP_COPY = '/tmp/test-app'
const MAX_FILE = 256_000
const MAX_OUTPUT = 100_000
const tools = [
  { name: 'list_files', description: 'List source, specification, and saved test file names.', inputSchema: { type: 'object', properties: {}, additionalProperties: false } },
  { name: 'read_file', description: 'Read a source, specification, or saved test file.', inputSchema: { type: 'object', properties: { path: { type: 'string' } }, required: ['path'], additionalProperties: false } },
  { name: 'write_test', description: 'Save a TypeScript node:test file in the separate tests directory. Target program files cannot be edited.', inputSchema: { type: 'object', properties: { name: { type: 'string' }, content: { type: 'string' } }, required: ['name', 'content'], additionalProperties: false } },
  { name: 'run_tests', description: 'Run all saved *.test.ts files against a fresh disposable copy of the program using tsx --test. Returns exit code and TAP output.', inputSchema: { type: 'object', properties: {}, additionalProperties: false } },
]

function reply(value, isError = false) {
  return { content: [{ type: 'text', text: String(value).slice(0, MAX_OUTPUT) }], isError }
}

function testName(name) {
  if (typeof name !== 'string' || !/^[A-Za-z0-9_-]+\.test\.ts$/.test(name)) throw Error('invalid test name')
  return name
}

function sourceName(name) {
  if (typeof name !== 'string' || name.includes('\\') || name.includes('\0') || name.startsWith('/')) throw Error('invalid path')
  const parts = name.split('/')
  if (parts.some(part => !part || part === '.' || part === '..')) throw Error('invalid path')
  if (!(name.startsWith('src/') || ['package.json', 'tsconfig.json', 'vite.config.ts', 'index.html'].includes(name))) throw Error('forbidden path')
  return path.join(SOURCE, ...parts)
}

function list(directory, prefix, found) {
  if (!fs.existsSync(directory)) return
  for (const item of fs.readdirSync(directory, { withFileTypes: true })) {
    if (item.isSymbolicLink()) continue
    const relative = `${prefix}/${item.name}`
    if (item.isDirectory()) list(path.join(directory, item.name), relative, found)
    else if (item.isFile()) found.push(relative)
  }
}

function runTests() {
  const names = fs.readdirSync(TESTS).filter(name => /^[A-Za-z0-9_-]+\.test\.ts$/.test(name)).sort()
  if (!names.length) throw Error('no tests saved')
  fs.rmSync(APP_COPY, { recursive: true, force: true })
  fs.cpSync(SOURCE, APP_COPY, { recursive: true, dereference: false })
  fs.symlinkSync('/app/node_modules', path.join(APP_COPY, 'node_modules'), 'dir')
  const env = Object.fromEntries(Object.entries(process.env).filter(([name]) => !/(ANTHROPIC|CLAUDE|API_KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|DOCKER)/i.test(name)))
  env.HOME = '/tmp/test-home'
  fs.mkdirSync(env.HOME, { recursive: true })
  const result = spawnSync('/app/node_modules/.bin/tsx', ['--test', ...names.map(name => path.join(TESTS, name))], {
    cwd: APP_COPY, env, encoding: 'utf8', timeout: 90_000, maxBuffer: 4_000_000,
  })
  const exit = result.status ?? 124
  return `exit_code=${exit}\n${result.stdout || ''}${result.stderr || ''}${result.error ? `\nenvironment_error=${result.error.message}` : ''}`
}

function call(name, args) {
  let status = 'ok'
  let detail = ''
  try {
    if (!args || typeof args !== 'object' || Array.isArray(args)) throw Error('invalid arguments')
    if (name === 'list_files' && Object.keys(args).length === 0) {
      const found = []
      list(path.join(SOURCE, 'src'), 'src', found)
      list(TESTS, 'tests', found)
      return reply([...found, 'package.json', 'tsconfig.json', 'vite.config.ts', 'index.html'].sort().join('\n'))
    }
    if (name === 'read_file' && Object.keys(args).join() === 'path') {
      let target
      if (args.path.startsWith('tests/')) target = path.join(TESTS, testName(args.path.slice(6)))
      else target = sourceName(args.path)
      if (!fs.existsSync(target) || !fs.statSync(target).isFile() || fs.lstatSync(target).isSymbolicLink() || fs.statSync(target).size > MAX_FILE) throw Error('file unavailable')
      return reply(fs.readFileSync(target, 'utf8'))
    }
    if (name === 'write_test' && Object.keys(args).sort().join() === 'content,name') {
      const file = testName(args.name)
      if (typeof args.content !== 'string' || Buffer.byteLength(args.content) > MAX_FILE) throw Error('invalid content')
      const target = path.join(TESTS, file)
      if (fs.existsSync(target) && fs.lstatSync(target).isSymbolicLink()) throw Error('invalid path')
      fs.writeFileSync(target, args.content, 'utf8')
      detail = file
      return reply(`saved tests/${file}`)
    }
    if (name === 'run_tests' && Object.keys(args).length === 0) {
      const output = runTests()
      detail = output.slice(0, MAX_OUTPUT)
      return reply(output)
    }
    throw Error('unsupported operation')
  } catch (error) {
    status = 'error'
    detail = error instanceof Error ? error.message : String(error)
    return reply(detail, true)
  } finally {
    fs.appendFileSync(path.join(WORK, 'operations.jsonl'), JSON.stringify({ at: new Date().toISOString(), tool: name, status, detail }) + '\n')
  }
}

function dispatch(request) {
  if (!Object.hasOwn(request, 'id')) return null
  if (request.method === 'initialize') return { jsonrpc: '2.0', id: request.id, result: { protocolVersion: request.params?.protocolVersion || '2025-03-26', capabilities: { tools: {} }, serverInfo: { name: 'ai-lab-12-tests', version: '1' } } }
  if (request.method === 'ping') return { jsonrpc: '2.0', id: request.id, result: {} }
  if (request.method === 'tools/list') return { jsonrpc: '2.0', id: request.id, result: { tools } }
  if (request.method === 'tools/call') return { jsonrpc: '2.0', id: request.id, result: call(request.params?.name, request.params?.arguments) }
  return { jsonrpc: '2.0', id: request.id, error: { code: -32601, message: 'method unavailable' } }
}

fs.rmSync(SOCKET, { force: true })
const server = net.createServer(connection => {
  let pending = ''
  connection.on('data', chunk => {
    pending += chunk.toString('utf8')
    while (pending.includes('\n')) {
      const end = pending.indexOf('\n')
      const line = pending.slice(0, end)
      pending = pending.slice(end + 1)
      try {
        const response = dispatch(JSON.parse(line))
        if (response) connection.write(JSON.stringify(response) + '\n')
      } catch {
        connection.write(JSON.stringify({ jsonrpc: '2.0', id: null, error: { code: -32600, message: 'invalid request' } }) + '\n')
      }
    }
  })
})
server.listen(SOCKET, () => fs.chmodSync(SOCKET, 0o666))
