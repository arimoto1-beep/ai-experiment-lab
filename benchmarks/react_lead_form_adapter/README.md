# Terminal-Bench v4.0.0 react-lead-form adapter

This adapter is limited to the single official `react-lead-form` task at commit
`452bf305c6daa62fc59061d22133a7cbc7c1572e` and Harbor 0.25.0. It checks
all 40 tracked task files against Git blob bytes before a run. It never edits
the task, solution, `test.sh`, or `test_outputs.mjs`.

## Source and dependencies

The official task is obtained from the [Terminal-Bench repository at the pinned
commit](https://github.com/harbor-framework/terminal-bench/tree/452bf305c6daa62fc59061d22133a7cbc7c1572e/tasks/react-lead-form).
Its checkout is intentionally not duplicated in this repository. On Windows,
keep shell scripts in LF so the verifier can execute them:

```powershell
git clone --filter=blob:none --sparse https://github.com/harbor-framework/terminal-bench.git analysis/terminal-bench-v4.0.0
git -C analysis/terminal-bench-v4.0.0 config core.autocrlf false
git -C analysis/terminal-bench-v4.0.0 sparse-checkout set tasks/react-lead-form
git -C analysis/terminal-bench-v4.0.0 checkout 452bf305c6daa62fc59061d22133a7cbc7c1572e
python -m venv .harbor-react-lead-form-venv
.\.harbor-react-lead-form-venv\Scripts\python.exe -m pip install harbor==0.25.0
```

Docker Desktop must expose a Linux engine. The CLI image `ai-lab-agent:1`
comes from the existing [#6 Docker experiment](../agentic_dev/README.md);
this adapter pins the locally verified image ID. A rebuild may have a different
ID and requires revalidation of the auth separation before changing the pin.
Harbor builds the unchanged official task and separate verifier images from the
pinned checkout. Image IDs and nop/oracle controls are in the
[validation record](../../analysis/react-lead-form-validation-20261029/README.md).

## Isolation

- Harbor's host-side custom agent owns Docker operations. Its task container
  receives no Claude auth volume, no Docker socket, and no host workspace.
- The #6 CLI image is pinned to image ID
  `sha256:02ddedacf8dc79f1402df822f09699fc3be6d18bd93e0140b4d18b39fa57806b`.
  Only this container receives the auth volume and trial IPC volume. It has no
  task source mount or Docker socket. The existing #6 `mcp_bridge.py` runs there.
- The task container receives the trial IPC volume and read-only mounts of
  official task specs, input data, and root configuration. Its runtime network
  is `none`. The task-specific Node MCP worker runs inside that container.
- MCP permits source listing/reading, TypeScript source writing under `src/`
  outside `src/spec/` and `src/data/`, and exactly `npm test`, `npm run build`,
  `npm run submit`. Direct writes to tests, data, specs, configuration, absolute
  paths, symlinks, and parent traversal are refused. Code executed by npm also
  cannot write the protected bind mounts.
- The separate verifier container is disconnected from Docker networks before
  the unmodified official verifier runs. This is a runtime wrapper around
  Harbor's `Verifier`, not a change to the task's reward calculation.

The extra mounts and network restrictions differ from an unmodified official
Claude Code run. Both compared models would use exactly the same adapter.

## Running without a model

In Windows PowerShell, with Docker Desktop running and a shell that can access
its engine:

```powershell
$env:RLFM_DOCKER = (Get-Command docker -ErrorAction Stop).Source
$env:PYTHONUTF8 = '1'
.\.harbor-react-lead-form-venv\Scripts\python.exe -m ai_lab.react_lead_form_harbor --mode dummy
```

The dummy uses a new volume containing a random fake credential marker, then
checks allowed and rejected MCP operations. It does not invoke Claude. The
runner removes the dummy auth and IPC volumes after Harbor finishes.

## Outputs and partial completion

Each run is stored under `results/react_lead_form_harbor/<run_id>/`. Harbor's
job and trial directories carry the same run ID. Within a trial:

- `agent/cli-stdout.jsonl`, `cli-stderr.txt`: dummy result or future Claude
  stream, and CLI stderr.
- `agent/history.json` on model runs: tool events extracted on the host from
  the Claude stream using #6's event parser. This is the primary operation
  record because submitted code can alter files inside the task container.
- `agent/worker-operations.jsonl`: permitted and rejected operations, command
  exit codes and command output. Treat this task-side log as supporting evidence.
- `agent/security-probe.json`, `verifier/security-probe.json`: credential,
  socket, protected-write, and network checks as applicable.
- `agent/changes.patch`, `partial-analysis.json`: official initial source
  compared with Harbor's recovered artifact, Vitest case outcomes, and
  conservative feature-group outcomes.
- `verifier/reward.txt`, `test-stdout.txt`: official reward and verifier log.

The analyzer marks a Vitest case successful only if the complete case count is
present and the case has no `FAIL` line, or the official reward is 1. Feature
groups with explicit failures are failures. On reward 0, groups without enough
positive evidence remain **undetermined**; an unlisted official assertion is
never silently counted as passed. The official reward is untouched.
The generated feature groups are keyword-based supporting evidence, not the
causal defect count. The committed analyzer tightens whole-term matching to
avoid counting `malformed` as a form failure; saved run results were not
overwritten. The manual causal classification in the replication report is
authoritative for the six historical trials.

`results/` is ignored by Git. The committed [six-trial summary](../../analysis/react-lead-form-replication-20261031/summary.json)
and [source patches](../../analysis/react-lead-form-replication-20261031/patches/)
retain the reviewable evidence without raw CLI streams or container snapshots.
For each run ID, apply its patch to a fresh copy of the official
`tasks/react-lead-form/environment/app` with
`git -c core.autocrlf=false apply -p1 <patch-path>`. All six patches were
checked against the saved final source files byte-for-byte.

## Model-run conditions

The authorized 2026-10-30 pilot used a CLI-only auth volume validated by #6
and ran these two conditions one at a time:

```powershell
.\.harbor-react-lead-form-venv\Scripts\python.exe -m ai_lab.react_lead_form_harbor --mode claude --model claude-haiku-4-5 --effort default --auth-volume ai-lab-claude-auth --enable-model
.\.harbor-react-lead-form-venv\Scripts\python.exe -m ai_lab.react_lead_form_harbor --mode claude --model claude-haiku-5-5 --effort medium --auth-volume ai-lab-claude-auth --enable-model
```

The adapter keeps the official 28,800-second agent and 900-second verifier
timeouts, one attempt per run, one concurrent trial, the same task digest,
same four MCP tools, same CLI image ID, and 100 maximum Claude turns. The
model and Effort are paired conditions; their independent effects cannot be
inferred from one run each. See
[`analysis/react_lead_form_pilot_20261030.md`](../../analysis/react_lead_form_pilot_20261030.md)
for the preflight, safety checks, exact run IDs, official scores, partial
outcomes, usage, and interpretation limits. The commands above launch new
model trials and must not be used to interpret the two saved trials as reruns.

## Model-free validation on 2026-10-29

- Final dummy run `rlfm-5a2a29b121cc`: Harbor completed with no exceptions; official
  reward 0. The task probe found no credential-like environment variables,
  auth marker, or Docker socket; outbound TCP was blocked; protected files
  could not be opened writable. The dummy made one allowed source edit,
  rejected six forbidden operations, ran all three allowed npm commands, and
  Harbor recovered the edit. The separate verifier probe also found no auth,
  socket, or network access.
- The derived report found 5 passed and 6 failed Vitest cases of 11, despite
  the final reward of 0. It recorded the changed file and patch.
- Isolated oracle control: the same official verifier returned reward 1 with
  no exceptions after network disconnection.
