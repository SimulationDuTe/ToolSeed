# ToolSeed native DSH panel

Local, unpublished plugin for **DeepSeek Harness Desktop 0.2.1-rc.2 / rc.3**. Uses the
official `settings.section` slot and `connection.fetch.register`
owner-admitted transport (HTTP on Web, IPC on Desktop). No DSH source changes,
browser launch, model calls, extra MCP tool or listening service. The recall
hook invokes the existing search tool through the scoped host tool runtime.

## Proactive capability recall

`recall: true` (default) searches before a normal model step using the current
task, a new tool error, or newly observed tool names. Up to two matching cards
are supplied without requiring the model to initiate search. The model decides
whether to read and apply a complete method. No extra model call, automatic
capability execution, forced continuation or first-call interception occurs.

Search passes the Agent scope, host permission pipeline and cancellation signal.
There are at most three searches per turn, a 1.5-second timeout, query and version
deduplication, and no injected message for empty/weak matches. A failed/timed-out
search disables further automatic recall for that turn. Optional `recallNamespace`
adds the named workspace scope to the global library; it is not a data directory.
See [proactive recall](../../docs/PROACTIVE-RECALL.md) for matching and limitations.

## Experience learning

`learning: true` (default) adds a bounded cue in an already admitted Agent step
after a failure followed by a normal tool return, six returns across three tools,
or a user follow-up after tool activity. The host model decides whether to skip,
reuse, revise or save a method, failure lesson or tool recipe using `toolbox_learn`.
The hook never calls a model/tool itself and does not claim success or infer a
root cause. It retains only bounded activity metadata, not arguments/results/user
text. After guidance delivery and subsequent activity, it can prompt the model
to append invocation-bound observations or propose an amendment on that same
capability through `toolbox_learn`. One general learning hint and one reuse-update
hint per turn; no forced task-end continuation or persistent backlog. See
[reuse updates](../../docs/REUSE-UPDATES.md) for binding and revision behavior.

Restart the ToolSeed MCP process to discover the new tool, reload this plugin,
and sync the packaged ToolSeed Skill through the existing installer. Set
`learning: false` to disable this hook. Set `opportunities: false`,
`learning: false`, `recall: false` and `revisionValidation: false` to retain only the panel. See
[experience learning](../../docs/EXPERIENCE-LEARNING.md) for the API and boundaries.

## P1-A opportunity hints

The optional Agent adapter is enabled by default (`opportunities: true`). It uses
this version's public `tools/result`, `agent/pre-step`, `session/event` and
`agent/disposed` events. The settings UI and its five read-only routes are unchanged.
No extra server, database, Core mutation or MCP tool is registered by the adapter.

In one live Agent turn, three distinct executions failing with the same tool name
and structured `error.info.code` produce a possible-reuse signal. Free-text errors,
ordinary successes, cancellation, the outer PTC transport and ToolSeed's own calls
do not feed this rule. The next normally admitted step can receive **one L1 hint**;
the adapter never wakes an idle Agent, steers an extra turn or calls a model/tool.
An already observed post-signal search suppresses another hint. Exact execution
tokens deduplicate notifications. State is limited to 256 executions/16 error
groups per Agent turn and cleared on the next turn or disposal; no historical
signals are reconstructed after restart. This deliberately narrow rule can miss
costly work without structured failures and can flag unrelated failures sharing
one tool/code. It is a hint to assess, not proof of applicability or reuse value.

The configured MCP server must already expose ToolSeed's existing tools to that
Agent. `mcpServer` defaults to `toolseed`, meaning
`mcp__toolseed__toolbox_search` etc.; set it to your actual clean server name
(1–32 letters, digits, underscores or hyphens). Keep the MCP server's `--data-dir`
identical to the panel's `dataDir`. The plugin does not start or configure that
MCP server, load Skills on the Agent's behalf, or install a model provider. If the
tool is hidden/absent, a signal is logged as `prompt_unavailable`, not a search.
If Agent/tools services are absent, optional Cordis injection stays inactive and
the existing read-only panel works. Set `opportunities: false` in the plugin's
official profile config to disable the repeated-failure hint. Restart DSH after code/config
updates; the existing installer need not be rerun for a local package link.

The hint asks the Agent to actually load applicable Skills, search with an object
`context`, check fit/permissions/verification, continue the original task on no
match or failure, and save only a validated, worthwhile method using the current
contract. It allows no save. L2 abstraction remains the Agent's cost/risk decision;
this rule never automatically escalates to L2 or creates/promotes a capability.

Look for `toolseed/opportunity` in the host logs. Metadata distinguishes
`signal_detected`, `opportunity_proposed`, `opportunity_prompted` (the host committed
the identified context message), actual search results, saves/duplicates/failures
and guidance delivery. It stores no tool arguments, prompt/error text, procedure
bodies or hidden reasoning. Correlation is explicitly **same Agent turn**, not
proven causal attribution. Actual adoption and task outcome remain `unknown`.
The host Session retains the admitted fixed hint through its normal message log;
Core evidence/maintenance tables receive no opportunity events. These adapter
records are not new GUI activity or historical capability evidence. Log durability
and retention follow DSH configuration. A turn ending is not a confirmed task result;
no `agent/turn-stopping` assessment/continuation is installed.

Verified with the installed 0.2.1-rc.2 runtime, real AgentLoop/ToolRuntime and a
real ToolSeed MCP stdio process in a unique test database, using a deterministic
scripted driver with **zero model/network calls**. This verifies the event and
transport mechanism, not a real model's autonomous search/save/adoption behaviour.
See [P1-A delivery and limitations](../../docs/P1-A.md) for commands and evidence.

### Optional trigger diagnostics (off by default)

Set `opportunityDiagnostics: true` explicitly in the existing plugin config and
reload/restart DSH. It requires the existing opportunities adapter and Agent/tools
services; it does not enable those services or change the three-failure rule.
Filter the existing host logger for `toolseed/opportunity-diagnostics` and first
confirm `observer_started`. Set the flag to `false` and reload to stop the capture.
No frontend rebuild is required. The observer is included in the plugin package.

The old logs omit most skipped events and intermediate counts. This bounded mode
adds final-result flags/code presence, actual safe code values, duplicate decisions,
counts, skipped reasons, admitted/rejected steps, checked search-tool visibility,
proposal and committed-context stages. Agent, Session, turn and Symbol identities
become capture-local opaque labels. While enabled, existing opportunity logs also
use this projection; budget exhaustion never falls back to raw identifiers.
No error text, command output, result body, arguments, prompts, paths or reasoning
are collected. Metadata lookup reads only the installed host's version metadata;
failure is `unknown`, not the package's declared supported version.

Limits per plugin load: **256 logger records, 128 KiB total, 2 KiB per record**,
including a reserved stop record. Host formatter overhead/exporter copies are
outside that payload budget. The capture stops at its limit; disabling/reloading
discards its in-memory identity maps. Logger retention/exporters belong to DSH:
there is no new file, database or server and no promised Desktop log pathname.
Stop the mode first, then remove only a diagnostic extract you created yourself;
clear shared logs using the host's retention policy. Restarting clears the process
logger's memory buffer, not its exporter files. Do not delete historical test logs.
See [fields, collection steps, cleanup and synthetic checks](../../docs/P1-A-DIAGNOSTICS.md).

## Install from this checkout

Install ToolSeed in the Python environment used by your existing MCP server
(`python -m pip install -e .` from the repository). Fully quit DSH Desktop. Run:

```powershell
node integrations/dsh/build.mjs
./integrations/dsh/install.ps1 `
  -Python F:/ToolSeed/.venv311/Scripts/python.exe `
  -DataDir F:/ToolSeed/.toolseed `
  -DshCommand 'F:/DeepSeek Harness/resources/runtime/cli/bin/dsh.cmd'
```

Use your MCP server's **same absolute data directory**. The script uses the
official `dsh plugin --profile desktop add <local-package>` command, then writes
only a marked `toolseed-panel` override in the desktop profile's patch file,
backing up an existing patch. It preserves other entries and the MCP configuration.
Dependencies/lockfile are managed by DSH/pnpm. The plugin is not published.

Open DSH normally, then select **Settings → ToolSeed** in the settings sidebar.
There is no ToolSeed entry in the main sidebar. The two views, **已入库能力**
(saved capabilities) and **活动** (activity), reuse the cards, details and read-only
query helpers in `toolseed/ui_assets/app.js`. Evidence, history and optional raw
identifiers live in details. Titles use existing descriptions for technical names;
test fixtures are marked as tests, never presented as business achievements.
The plugin invokes the fixed
Python executable's **read-only management commands** on demand, with hidden
subprocess windows, timeouts and bounded concurrency. No persistent Python server
is started. The page reports query errors; it does not probe or
assert that MCP is running. First setup requires Python with this checkout installed.

The host bundle's fallback config uses `python` and ToolSeed's normal environment /
user directory resolution. Set explicit `python` and `dataDir` to avoid host PATH
or working-directory ambiguity. Changing `dataDir` in a query is forbidden.

## Shared UI and security

`build.mjs` reuses the canonical GUI's escaping presentation helpers in the
documented DSH lazy-CJS format. Rebuild after shared-view edits and restart DSH
(reinstall if using a copied package instead of a local link).
The page renders in the host document, with DSH's public `Button`, `Input`,
`SegmentedTabs` and `Modal` components. Scoped layout CSS
consumes the host's `--dsw-*`, `--dsh-content-font-size`, `--dsh-code-font-size`
and `--ds-font-family-code` tokens. It defines no palette, font stack, theme state,
theme selector or theme overrides. Transparent content surfaces preserve the host
settings background; colors, fonts, controls and light/dark/system changes inherit
the live host cascade without copying styles or observing internal host elements.
There is no iframe, shadow document, postMessage bridge or independent webpage shell.
All stored data passes through the shared HTML escapers (names and Procedure text
remain untrusted). The standalone HTTP GUI and its `frame-ancestors 'none'` policy
are unchanged. The page uses public `connection.rpc.call`; Connection admits owners before
the registered Fetch handler. Only five predefined management query routes exist.
All are reads. Unknown fields, arbitrary Python commands and data-directory changes
are rejected. Error responses do not return subprocess stderr.

The settings UI performs no Store initialization, database migration, capability execution or management
mutation. Lifecycle restrictions on procedure content match the existing Inspector.
Evidence gaps remain unknown; a delivery or failed tool invocation is not a task
success/failure. The current Core schema is v7. Empty/missing/old/corrupt databases are explained
without automatically creating or repairing them.

## Verify

The optional `revisionValidation` feature (default `true`) registers the native
`toolseed_validate_revision` tool. It inspects a candidate, runs model-selected
new/regression cases through the scoped host tool runtime, and activates only
after all assertions pass against the unchanged base. Failed cases are retained
and the current version remains available. This tool uses fixed local management
bridge operations with the configured `python` and MCP-matching `dataDir`; the
settings UI remains read-only. See [revision activation](../../docs/REVISION-ACTIVATION.md).
The five public MCP tools remain unchanged; the native validator is DSH-specific.

```powershell
node integrations/dsh/build.mjs
node --test integrations/dsh/test/backend.test.mjs
node --test integrations/shared/test/*.test.mjs
python -X utf8 -m unittest tests.test_management tests.test_cli tests.test_ui -q
```

`TOOLSEED_TEST_PYTHON` may select the Python used by Node integration tests.
Fixtures use disposable `tests/.data/dsh-*` databases, never the user's library.

## Public contract references

The installed 0.2.1-rc.2 packages' READMEs and exports are the version-specific
authority: `dsh-client-ui-settings`, `dsh-client-ui-settings-general`,
`dsh-client-ui-theme`, `dsh-client-modules`, `dsh-client-connection`,
`dsh-connection`, `dsh-app-boot`, `dsh-plugin-manager`. The public primitives
module is part of the shipped Web frontend baseline. Installed ordinary plugins
such as `dsh-codex-subscription` and `dsh-plugin-wallpaper-engine` use this same
`settings.section` registration; their source was read only as an integration reference.
Current documentation: [plugin creation](https://deepseek-harness.github.io/deepseek-harness/en/develop/basic/),
[client modules](https://deepseek-harness.github.io/deepseek-harness/en/reference/subsystems/client-modules).
The rc.3 installed AgentLoop, ToolRuntime and MCP have also passed the isolated
learning, reuse feedback, revision activation and proactive recall probes with
zero real model calls. The compatibility declaration names only these two
verified prereleases; later DSH versions require re-verification.

The simplified panel was tested in an isolated official DSH Web profile
with the same 0.2.1-rc.2 client and components, not in the user's live Desktop session:
11 Node tests, 26 Python GUI/management tests and 4 documentation contract tests.
Browser checks cover settings-only navigation, both views, description/scenario
search, details, optional raw fields, narrow cards and cross-tab
light/dark/system/font synchronization. Screenshots read the existing library
without writing it; the only saved capability there is explicitly marked as an
integration self-test. No user appearance preferences or database were changed.
Restart DSH to load the new client. See the [delivery record and actual screenshots](../../docs/PANEL-SIMPLIFICATION.md).
