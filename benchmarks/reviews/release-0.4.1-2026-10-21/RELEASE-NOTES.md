# ToolSeed v0.4.1

Patch release over `v0.4.0`. Git install is the supported distribution path for this release;
PyPI is **not** published (see "Distribution" below).

## What changed

- **Fix — evidence and maintenance lifecycle hardening** (`0f1648c`): evidence validity,
  maintenance decisions, capability observations, version promotion and rollback paths are
  tightened so a failed write cannot be mistaken for an applied decision, and old decisions
  without a record-order marker are rejected instead of being guessed.
- **Fix — atomic decision resolution** (`c0cac12`): applying a maintenance decision now
  resolves and records it atomically; a commit failure rolls back instead of leaving a
  half-applied decision behind.
- **Docs — Alpha usage path and delivery boundary** (`277f38f`): a new *Alpha quickstart* in
  the README (install, MCP stdio configuration, confirming the four public tools, setting and
  verifying the persistence directory, search/save/deliver, and reading Invocation/Evidence/
  `unknown`), plus a new `docs/ALPHA-STATUS.md` that states what is verified, what reuse was
  observed in real agent work, what net benefit is **not** proven, and the unsupported surface
  and known limits. The stale "MCP not implemented" note is gone.
- **Skill — save guidance** (`277f38f`): the packaged Skill now states every enforced manifest
  limit, requires a pre-submit check, and defines a minimal correction from the actual error
  message instead of blind retries. Saving stays optional per task. **No Core contract was
  relaxed.**
- **Test — contract guard** (`277f38f`): a new test pins the documented limits to the Core
  constants and keeps the usage documents free of stale claims.

## Compatibility

- No database schema migration: the schema is identical to `v0.4.0`.
- No change to the four public tools (`toolbox_search`, `toolbox_save`, `toolbox_run`,
  `toolbox_stats`) and no change to the candidate contract.
- Python >= 3.11; the only runtime dependency is `mcp>=2.3,<3`.

## Install (Git)

```bash
python -m venv .venv-toolseed
.venv-toolseed/Scripts/pip install "git+https://github.com/SimulationDuTe/ToolSeed@v0.4.1"
# or: .venv-toolseed/bin/pip install "git+https://github.com/SimulationDuTe/ToolSeed@v0.4.1"
```

Then register the MCP server (Claude Code / Cursor style):

```json
{
  "mcpServers": {
    "toolseed": {
      "command": "<venv>/Scripts/toolseed-mcp.exe",
      "args": ["--data-dir", "<abs-path>/.toolseed"]
    }
  }
}
```

Codex style (`~/.codex/config.toml`):

```toml
[mcp_servers.toolseed]
command = "<venv>/Scripts/toolseed-mcp.exe"
args = ["--data-dir", "<abs-path>/.toolseed"]
```

Verify the install: the server must list exactly the four tools above, `toolbox_stats` must
return structured data, and the data directory must contain `toolseed.sqlite3`.

## Distribution

- **GitHub Release**: pushing the `v0.4.1` tag runs the release workflow, which builds the
  sdist and wheel, runs `twine check`, writes `SHA256SUMS` and attaches the artifacts to a
  GitHub Release for this tag.
- **PyPI**: not published, and this release does not publish there. The Git install path above
  is the supported route; a PyPI upload would be a separate, separately authorised step.

## Known limits

- Net benefit is **not** proven: reuse was observed in real agent work, but the measured cost
  of the method-library path was not lower. See `docs/ALPHA-STATUS.md`.
- Procedures are untrusted text; nothing is executed, and there is no sandbox.
- Single-user, local storage; provider token and billing figures are not observable here.
- Documentation lives in the repository, not inside the wheel or sdist.
