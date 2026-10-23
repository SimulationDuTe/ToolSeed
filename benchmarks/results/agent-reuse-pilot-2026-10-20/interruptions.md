# Infrastructure interruptions and continuation

The first six primary workers finished and independently passed. All six phase-1 workers
were then reported failed by the Harness before producing agent_report.json or completion.json.
Inspection found only the originally supplied problem files, task instructions and start markers;
no phase-1 task has been scored as completed or successful.

The parent session changed displayed model from openai-codex/gpt-6.1-sol to
claudex/gpt-6-astra and later back to openai-codex/gpt-6.1-sol. The precise termination
reason and child-provider configuration are unknown; coincidence is not proof of causation.
This is an observed experiment-operations interruption, not a task-solver outcome.

Continuation policy: send a continue message to each ORIGINAL phase-1 worker/context,
without changing fixtures, instructions, expected results, library, or started.json.
Retain the failed-attempt notices and original measurement boundaries. No adverse sample is
replaced and no new task is selected. Record one infrastructure interruption per phase-1 case.
Any later completion is acceptance of the continued original case, not a first-attempt success.
Original launch-to-completion intervals include the long interruption and must not be used
for latency or net-benefit claims. Exact active time and retry token cost remain unknown.

The same fixed phase-2 tasks started only after all phase-1 completion records existed.
At a later session continuation, env2/debug2 A/B had completion records but data2-A and
data2-B were inactive without reports or completion markers. Both original data2 contexts
were resumed under the same policy, preserving their partial converter files and original
start markers. Their exact interruption cause is unknown. This adds two interrupted cases:
eight primary cases in total have one recorded infrastructure continuation each.
No task was replaced, and none was counted complete before independent acceptance.
