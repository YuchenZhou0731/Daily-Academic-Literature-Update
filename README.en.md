# Configurable Academic Literature Digest Skill

[中文说明](README.md)

A user-configured paper discovery workflow, searchable local library and selected-paper reading queue, primarily for Codex. Python handles retrieval, deduplication, evidence storage and archival. The assistant reviews actual titles/abstracts and writes the digest. Scheduling and notifications require the host's supported tools.

## Personalize it in conversation

Configure arbitrary topics, keywords and exclusions; paper limits; manual/daily/selected-weekday runs; local time and IANA timezone; journal preferences or a strict whitelist; document types and preprints; Chinese/English analysis; and an available delivery destination.

All user-fillable example and configuration values are `xxx`. No research field, journal list or schedule preference is supplied. Replace placeholders with actual values of the required JSON type; clear unused optional values with an empty string or array. Unresolved placeholders prevent confirmation and collection. Schema keys, supported option names and runtime requirements remain literal.

Example request:

> Use $literature-digest-skill. Topics: xxx; maximum papers: xxx; frequency: xxx; time: xxx; timezone: xxx; journal policy: xxx; document types: xxx; preprint preference: xxx; analysis language: xxx; delivery: xxx; additional requirements: xxx.

The assistant asks only for missing information, creates a private workspace and tests the workflow. Later changes such as adding a topic or adjusting the schedule preserve paper and delivery history.

## Install

Ask Codex's skill installer to install the repository root as `literature-digest-skill`:

```text
https://github.com/YuchenZhou0731/Daily-Academic-Literature-Update
```

Alternatively, place the complete repository in the host's user Skill directory under that name. Preserve `SKILL.md`, `scripts`, `assets` and `references`. Use the actual Skill directory supported by your client; installation alone does not register a schedule.

Python 3.10+ is required:

```text
python -m pip install -r requirements.txt
```

Copy and fill the [configuration template](examples/preferences.template.json) privately. In these commands, replace `xxx` with the appropriate workspace or file path; keep the same workspace throughout:

```text
python -I -B scripts/workspace.py --workspace "xxx" init
python -I -B scripts/workspace.py --workspace "xxx" configure --patch "xxx" --confirm
python -I -B scripts/workspace.py --workspace "xxx" doctor
python -I -B scripts/digest.py --workspace "xxx" collect
python -I -B scripts/digest.py --workspace "xxx" prepare
```

The initial profile is an unconfirmed placeholder draft, not an executable preference preset. `doctor` lists unresolved fields. `prepare` creates a review packet after configuration; the assistant must curate it and write evidence-grounded analysis before archival. Python alone does not generate an AI assessment or send notifications.

## Sources and keys

- Crossref is an available public metadata source; an abstract may be unavailable.
- arXiv is an optional public preprint source.
- OpenAlex requires your own key; the collector checks its reported daily allowance and a per-run cap.
- Scopus requires your own Elsevier key and appropriate search entitlement; STANDARD records may contain only the title and first author.

No separate model API key, browser registration helper or paper-search MCP service is required or bundled. The collector never purchases credits. Registration does not establish actual API access.

Optional keys are imported by the user in a local interactive terminal:

```text
python -I -B scripts/workspace.py --workspace "xxx" credential xxx
python -I -B scripts/workspace.py --workspace "xxx" doctor --credentials
```

Windows uses CurrentUser DPAPI. macOS/Linux desktop users can install `requirements-keyring.txt` for the system Keychain/Secret Service backend. Headless systems without an unlocked supported keyring cannot use that backend; keyless sources remain available. Never put keys in chat, command arguments, plaintext profiles or this repository. The implementation does not read environment-variable values or silently fall back to anonymous access.

## Scheduling is a separate acceptance step

Use the assistant host's scheduling tool after a manual test. Reuse an existing task when appropriate. A JSON time field is only intent; it does not create a timer. Local execution requires the machine and host runtime to be available.

When protected keys require normal-user execution, authorize only the fixed collector command through the host's supported mechanism. Verify that exact invocation without repeated approval, then verify the first actual scheduled run and notification. This repository does not rewrite global approval settings or install an OS scheduled task.

## Evidence and limits

The workflow distinguishes title-only metadata, abstracts and actually read full text. Preprints remain labeled; issue/index dates are not presented as verified first-online dates. Failed/capped queries retain coverage state. A source failure is not proof of no new papers. Lexical ranking is not scientific-quality assessment.

Reports, raw metadata, SQLite state, delivery receipts and reading materials stay in the private workspace. Full-text reading is opt-in; attaching a document does not mark it read. The static library UI and reading-card labels currently use Chinese; digest reports and assistant-written analysis support English.

## Development

```text
python -I -B -X utf8 scripts/run_tests.py
```

Offline tests use synthetic data and no credentials. GitHub Actions runs them on Windows, Linux and macOS. Passing tests does not verify a user's live account entitlement, network or notification setup.

See [onboarding](references/onboarding.md), [configuration](references/configuration.md), [sources](references/sources.md), [scheduling](references/scheduling.md) and [selected-paper reading](references/reading.md). The [Chinese publishing guide](docs/github-publishing.md) explains the repository's files and maintenance workflow.

Design references are credited in the Chinese README. This is an independent implementation; it does not bundle the referenced projects' scripts or services.

## License

[MIT License](LICENSE).
