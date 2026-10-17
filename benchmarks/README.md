# P0 value experiment

This directory holds the repeatable comparison required by `P0-SLIM.md` §11.2.
There are two layers:

- `value_experiment.py`: deterministic reference-agent mechanism check;
- `live_experiment.py`: real-agent A/B harness with programmatic verifiers,
  JSONL records and paired statistics.

## 1. Deterministic mechanism check

```bash
python -m benchmarks.value_experiment --repetitions 3
```

It compares a scripted reference executor solving fixed tasks from scratch (A)
with saving each procedure once and reusing it (B). It verifies accounting and
reuse mechanics; it is **not** evidence of real LLM productivity or net benefit.

## 2. Live A/B harness

```bash
python -m benchmarks.live_experiment --mode scripted --seeds 1
python -m benchmarks.live_experiment --mode command \
  --agent-command "your-agent-command" --seeds 3 \
  --out .toolseed/live-experiment/records.jsonl
```

`--mode scripted` uses an oracle runner to validate the harness (not value
evidence). `--mode command` runs an external agent for each instance and
condition.

The command receives:

- `LIVE_PROMPT_FILE` and `LIVE_PROMPT`;
- `LIVE_OUTPUT` — write the answer JSON object here;
- `LIVE_INSTANCE_ID`, `LIVE_FAMILY`, `LIVE_CONDITION`;
- `LIVE_TOOLBOX_DIR` — empty for A; a seeded ToolSeed data directory for B.

For condition B the harness seeds the ToolSeed procedures once per run, then
counts `search_performed` and `procedure_delivered` events from the data
directory. A command that never calls ToolSeed will show `adoption_rate` 0.

The harness records one JSONL row per run, including condition, instance, seed,
success, elapsed_ms, searches, deliveries, adoption, tokens (currently
`unknown`), answer and error.

### What is measured

- task success with a programmatic verifier;
- paired success difference (McNemar) and bootstrap confidence interval;
- paired time saved, with bootstrap confidence interval;
- adoption rate;
- ToolSeed search/delivery counts;
- missing token cost as `unknown`.

## Pilot log (not evidence)

2026-10-17 manual pilot, 2 instances (`api_timeout_network`,
`port_conflict_old_app`), A/B with one run each using external subagents:

- A: 2/2 correct; no ToolSeed;
- B: 2/2 correct; 2/2 adopted ToolSeed (one search and one delivery each);
- task outcomes recorded with source `test_runner`;
- token cost unknown; per-run wall time not captured;
- success delta 0.

This confirms the adoption and evidence path, but the tasks are too easy and
the sample is far too small for a value claim. It is a pilot only.

## What this is not

The verifiers cover only the fixed synthetic task set. A real value claim still
requires a real AgentRunner, independent verification, pre-registered sample
size and thresholds, and token/cost accounting where available. Scripted mode
must never be reported as value evidence.

