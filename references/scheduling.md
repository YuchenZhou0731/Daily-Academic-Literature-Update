# Scheduling and unattended verification

`schedule` in `profile.json` describes intent. Registration requires the assistant host's scheduling capability; installing this Skill or changing JSON does not create a task.

For Codex, discover and use the current `automation_update` tool. Prefer updating the existing task attached to the chosen chat. Preserve its target, notification preferences and history. Do not create a duplicate monitor or substitute an OS task. For another client, use its supported scheduler or explain that only manual runs are available. Never claim cross-client scheduling compatibility from the presence of `SKILL.md` alone.

## Durable task instructions

Build the prompt from the confirmed profile and actual machine:

- Exact interpreter, installed Skill script and private workspace.
- User's timezone, frequency, time and selected weekdays; report maximum and preprint/journal policy.
- Read profile and status before collection; reconcile uncertain delivery and keep deduplication history.
- Collect, inspect partial-coverage evidence, curate the actual abstract/title pool, analyze in the chosen language, archive, deliver, then record a real receipt.
- Treat exit code 2 as incomplete coverage; continue with retrieved candidates. Never turn source failure into “no new papers.”
- Keep quiet when no papers qualify and no new actionable problem exists, unless empty digests were requested.
- Do not change global permissions, register accounts, reopen browser helpers or download every paper during recurring runs.

## Permission acceptance

A successful manually approved request does not prove unattended execution. Protected-key access may require the owning user's process rather than a sandbox. Use the host's supported persistent authorization for the narrow, fixed collector invocation when the user authorizes it. Do not grant a generic interpreter/shell exception or bundle someone else's rules.

Validate the exact command the scheduler will execute, including its shell wrapper and path spelling. On a host with an approved command rule, ordinary/default execution may apply that rule; verify the behavior instead of assuming it. Avoid unconditional per-run escalation requests when the fixed command is already authorized. If rules are loaded only at startup, reload the host/session and repeat the test.

Record these separately in the private workspace:

1. Configuration valid.
2. Actual API retrieval and protected-key access passed.
3. Fixed invocation runs without repeated human approval.
4. Scheduler registered with the intended time and target.
5. First actual scheduled invocation and notification verified.

Keep the scheduler's returned identity and the tested command in private `automation.json`. Never copy them into the public repository. Schedule/timezone changes need both a profile update and a scheduler update. Local execution needs the machine and host runtime to be available.

The static library's copy buttons and a `pending` delivery row are not notification receipts. A user-visible report in the intended chat or the connector's returned message reference establishes delivery. Retry an existing report after failure; reconcile an uncertain send before retrying.
