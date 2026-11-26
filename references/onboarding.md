# Onboarding and changes

Prefer a short conversation over a long form. Reuse explicit preferences already provided. Research topics and display labels can be in any language; offer database-oriented English queries and synonyms when useful, then verify their scientific scope with the user.

Ask in small groups:

1. What topics, keywords or research problems should be followed? Any exclusions? Where should the private library live?
2. Maximum papers per run; manual/daily/selected weekdays; local time and IANA timezone.
3. All journals, preferred journals or a strict named list; article/review/conference/preprint choices; Chinese or English analysis; local/in-chat/authorized connector delivery.

If the user does not specify a setting, propose it visibly rather than presenting a preset as their confirmed preference. Do not require every topic to receive a paper every day. A single topic can have several queries and multiple synonym groups.

## Initial setup

1. Locate Python 3.10+ and install `requirements.txt` in the user's chosen Python environment when needed.
2. Choose a private workspace separate from the installed Skill; its path is shown as `xxx` in command templates. Initialization refuses to overwrite an existing profile and writes a workspace `.gitignore` that excludes its contents.
3. Run `python -I -B scripts/workspace.py --workspace "xxx" init` after replacing the path placeholder.
4. Read the draft `profile.json`. All user-fillable values are `xxx`; fill them from the conversation, propose technical settings when needed, and clear unused optional values. Keep required JSON types: numeric and boolean values must not remain quoted placeholders. Run `configure --patch "xxx" --confirm` with the completed patch file only after every placeholder is resolved. At least one actual topic is required.
5. Run `doctor` and inspect `unresolved_fields`. Add API sources only when selected and accessible. Crossref and arXiv are available without keys; neither is a supplied research preference.
6. Collect with conservative page/runtime budgets, review a small candidate pool and archive a local digest. Record network, evidence and coverage limitations honestly.
7. If the user requested recurring delivery, register/update a scheduler through the host and follow the separate unattended acceptance steps in `scheduling.md`.

## Incremental changes

Use `configure --patch "xxx"` for scalar/nested preferences. Objects merge; arrays replace. Existing SQLite history and archived reports are preserved, and the previous profile is copied into private `config-history/`.

For topics, avoid replacing the whole array when the user asks to add one:

```text
python -I -B scripts/workspace.py --workspace "xxx" topic add --file "xxx"
python -I -B scripts/workspace.py --workspace "xxx" topic update --id "xxx" --file "xxx"
python -I -B scripts/workspace.py --workspace "xxx" topic remove --id "xxx"
```

Keep a topic's ID stable when changing its display label or queries. Removal changes future matching; it does not erase papers or reading cards. After time/frequency/timezone changes, update the actual scheduled task as well as the profile. Never delete delivery history to implement a preference change.

When the user requests a currently unsupported behavior, explain the boundary. Store a qualitative preference in `selection_guidance` only when the reviewing assistant can actually apply it. Do not invent a provider integration, connector, journal metric or full-text capability.
