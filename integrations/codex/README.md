# ToolSeed Codex Agent Adapter

Local, unpublished adapter for **Codex CLI / Codex App** that adds ToolSeed's
Agent workflow on top of the existing MCP server. It does not replace MCP,
change Core/Schema or register a fifth public tool.

Verified against:

- Codex CLI `0.163.0-alpha.11` (Windows x64) — actual hook, Skill, AGENTS and
  `exec` verification
- Codex App `26.1016.6573.0` — installed-version/shared-interface inspection
  only; the adapter was not exercised in the App UI

Other Codex versions must be re-verified. Only this installed version is
claimed.

## What it adds

The existing MCP path lets Codex call the four ToolSeed tools. This adapter adds:

| Layer | Mechanism |
|---|---|
| Runtime opportunity hint | `PostToolUse` hook + `hookSpecificOutput.additionalContext` |
| Reusable method knowledge | ToolSeed `SKILL.md` installed in `$CODEX_HOME/skills/toolseed/` |
| Always-on guidance | A marked block in `$CODEX_HOME/AGENTS.md` |
| Installation / self-check | `src/install.mjs`, `src/verify.mjs` |
| Trust | Codex app-server `config/batchWrite`, the same method the Codex TUI uses |

The hint is generated only by the local hook. It does not call a model, call a
tool, save a capability or wake an idle Agent. The adapter otherwise exits 0
and never blocks the user's task.

## Install

Prerequisites:

- Codex is installed and the ToolSeed MCP server is configured with the
  **same absolute data directory** you use elsewhere. See
  [`mcp.toml.example`](mcp.toml.example).
- Node.js 22+ for the installer/verifier (`WebSocket` is used to query the
  Codex app-server). The runtime hook itself only needs a normal Node runtime.
- The current ToolSeed checkout is importable by the Python used by the MCP
  server.

Dry run first (default):

```powershell
node integrations/codex/src/install.mjs `
  --codex-home "$env:USERPROFILE\.codex" `
  --data-dir "F:/ToolSeed/.toolseed" `
  --codex "C:/path/to/codex.exe"
```

Apply:

```powershell
node integrations/codex/src/install.mjs --apply `
  --codex-home "$env:USERPROFILE\.codex" `
  --data-dir "F:/ToolSeed/.toolseed" `
  --codex "C:/path/to/codex.exe"
```

Useful options:

- `--json` — machine-readable plan/result.
- `--no-trust` — write the hook but leave approval to Codex.
- `--no-agents-md` — do not modify `$CODEX_HOME/AGENTS.md`.
- `--skill-source <path>` — use a different `SKILL.md`.
- `--mcp-server <name>` — default `toolseed`; must match `mcp_servers.<name>`.
- `--node <path>` — Node executable used in the hook command; defaults to the
  Node running the installer.

The installer:

1. copies `toolseed/skill/SKILL.md` to `$CODEX_HOME/skills/toolseed/SKILL.md`;
2. merges one `PostToolUse` handler into `$CODEX_HOME/hooks.json` while
   preserving existing hooks;
3. appends/replaces a marked block in `$CODEX_HOME/AGENTS.md`;
4. asks the Codex app-server for the effective hook key and hash, then writes
   the trust value through `config/batchWrite`;
5. re-queries `hooks/list` and `skills/list` to verify the result.

Starting the app-server may let Codex initialize its normal per-user state
(system skills, SQLite files) in that `CODEX_HOME`; the adapter does not run a
model or a tool. Codex may also normalize `config.toml` when it writes hook
trust. The installer never edits MCP configuration or DSH configuration.

If trust cannot be written, start Codex and approve the hook through its normal
hook trust UI, or use `--no-trust`. Do not use
`--dangerously-bypass-hook-trust` as a permanent setup.

## Verify

```powershell
node integrations/codex/src/verify.mjs `
  --codex-home "$env:USERPROFILE\.codex" `
  --data-dir "F:/ToolSeed/.toolseed" `
  --codex "C:/path/to/codex.exe"
```

Expected core checks: `hook_listed`, `hook_trusted`, `skill_active`,
`agents_md`, `mcp_server_config`. `toolseed_database` is created by the MCP
server on first use; it is a warning until then.

Unit tests (local checkout; not committed):

```powershell
node integrations/codex/test/opportunities.test.mjs
node integrations/codex/test/install.test.mjs
```

`node --test integrations/codex/test/*.test.mjs` also works in a normal
environment. This repository's DSH sandbox forbids the test runner's
child-process pipes, so the two files are run directly during local checks.

## Runtime behavior

The adapter installs one `PostToolUse` hook. On every completed tool call it
looks for `structurally identified failures` only:

- explicit error code at `error.info.code` / `error.code`;
- MCP `structuredContent` or a single bounded JSON text block with
  `error.code` / `error.info.code`;
- non-zero structured `exitCode` / `exit_code` when the host exposes it.

Free-text errors, shell output, prompts, arguments and procedure bodies are
never parsed or logged.

When the same **tool name + structured code** appears in **3 distinct
executions in one turn**, the adapter emits one L1 hint through
`hookSpecificOutput.additionalContext`. The hint asks the Agent to actually
load the `toolseed` skill, make one short `toolbox_search` call, assess
applicability/permissions/evidence, continue the original task on no match,
and save only after actual validation.

State is scoped by `session_id` + `turn_id`, capped at 256 executions and 16
error groups per turn, and pruned after 24 hours. ToolSeed's own calls
(`mcp__<server>__toolbox_*`) are observed for stages but excluded from the
blocker count. One hint per turn; a later search is recorded but does not
rewrite the signal.

Adapter-local records:

- `$CODEX_HOME/.toolseed-codex/state/*.json` — bounded counters and opaque IDs;
- `$CODEX_HOME/.toolseed-codex/events.jsonl` — stage records
  (`signal_detected`, `hint_emitted`, `search_completed`, `capability_saved`,
  `guidance_delivered`, `save_failed`, …), rotated at 1 MiB.

No tool arguments, output text, prompts, error messages, procedure bodies or
hidden reasoning are stored. These are adapter records, not Core evidence and
not a task-success signal.

## Verification status

| Layer | Status |
|---|---|
| Four MCP tools / capability library | Verified (search and save executed against the real ToolSeed MCP server) |
| Skill loading | Verified: `skills/list` shows `toolseed` scope `user`, enabled; `codex debug prompt-input` lists `r0/toolseed/SKILL.md` |
| AGENTS.md context injection | Verified in `codex debug prompt-input` (`agents_md.instructions`) |
| Hook loading/trust | Verified with `hooks/list` (`trustStatus=trusted`) and `config/batchWrite` |
| Opportunity identification | Verified end-to-end: 3 `PROBE_FAIL` calls → `signal_detected` |
| Prompt injection | Verified with a local mock Responses API: the next model request contained the hint (`hint_found=true`) |
| Capability save | Verified: `toolbox_save` returned `status=accepted` with capability/version IDs |
| Cross-task real-model reuse | **Not verified.** The end-to-end turn uses a scripted mock model, not a real model or a real Codex session. |

The isolated end-to-end run used
`--dangerously-bypass-approvals-and-sandbox` only so the mock MCP server could
write its temporary database and the hook could write its test state. It is not
an install or production recommendation.

## Known limits

- **Bash failures have no structured code in this Codex version.** The
  `PostToolUse` payload for `tool_name=Bash` is a string (observed: empty output
  for `cmd /c exit 1`). The adapter deliberately does not parse that text, so
  shell-only blockers do not trigger the runtime hint. The Skill and AGENTS.md
  guidance still apply.
- **Transport-level MCP failures may not emit `PostToolUse`.** A failed MCP
  call (`status: failed`, e.g. `isError: true`) was not observed through the
  hook; a *completed* MCP call whose payload contains a structured error does
  emit it. The ToolSeed Core error shape (`structuredContent.error.code`) does
  trigger.
- Hook output acceptance is not separately acknowledged by Codex. The log
  records `host_receipt: unknown`; the mock verification observed the hint in
  the next model request, but the adapter does not claim a receipt in normal
  use.
- No per-Agent tool-visibility query is exposed to hooks. The hint says that if
  the MCP tool is unavailable, the Agent must continue without retries.
- `Stop`/turn completion is not a task-success signal. Adoption and task
  outcome remain `unknown`.
- Codex has no verified native settings-panel contract for ToolSeed. Use MCP,
  the management CLI or the optional Web GUI for the library UI.
- Codex App and CLI surfaces may differ; only CLI `0.163.0-alpha.11` was
  exercised end-to-end. The installed App `26.1016.6573.0` was inspected for
  version/shared interface only.

## Files

| File | Purpose |
|---|---|
| `src/toolseed-hook.mjs` | Hook entry point; reads the event JSON from stdin and writes one JSON result |
| `src/opportunities.mjs` | Structured failure rule, hint, dedupe and ToolSeed-call observation |
| `src/state.mjs` | Per-turn state, atomic writes, file lock and cleanup |
| `src/logging.mjs` | Bounded JSONL stage log, safe IDs and short hashes |
| `src/paths.mjs` | `CODEX_HOME` / data-dir defaults |
| `src/install.mjs` | Skill, hooks, AGENTS.md, native trust and verification |
| `src/verify.mjs` | Read-only host check |
| `src/app-server-client.mjs` | Loopback WebSocket JSON-RPC client for `hooks/list`, `skills/list`, `config/batchWrite` |
| `src/host-capabilities.mjs` | Declarative, honest capability map |
| `mcp.toml.example` | MCP configuration example |

`TOOLSEED_CODEX_TRACE=<file>` is an opt-in diagnostic escape hatch for local
debugging. It records argv, stdin byte count, event/tool name, response type and
top-level response keys; it does not record tool input/output values. Leave it
unset in normal use.
