# Onboarding and changes

Prefer a short conversation over a long form. Reuse explicit preferences already provided. Research topics and display labels can be in any language; offer database-oriented English queries and synonyms when useful, then verify their scientific scope with the user.

Ask in small groups:

1. What topics, keywords or research problems should be followed? Any exclusions? Where should the private library live?
2. Maximum papers per run; manual/daily/selected weekdays; local time and IANA timezone.
3. All journals, preferred journals or a strict named list; article/review/conference/preprint choices; Chinese or English analysis; local/in-chat/authorized connector delivery.

If the user does not specify a setting, propose it visibly rather than presenting a preset as their confirmed preference. Do not require every topic to receive a paper every day. A single topic can have several queries and multiple synonym groups.

## Initial setup

1. Locate Python 3.10+ and install `requirements.txt` in the user's chosen Python environment when needed.
2. Choose a private workspace separate from the installed Skill. For example, from the repository use `../literature-workspace`; never use the Skill directory itself. Initialization refuses to overwrite an existing profile and writes a workspace `.gitignore` that excludes its contents.
3. Run `python -I -B scripts/workspace.py --workspace <workspace> init --preset <custom|remote-sensing|machine-learning>`.
4. Read the draft `profile.json`; write a patch matching the conversation, and run `configure --patch <patch.json> --confirm` using the same script/workspace. The presets are unconfirmed examples. A custom setup needs at least one actual topic.
5. Run `doctor`. Add optional API sources only when the user chooses them and has access. Baseline Crossref collection needs no key; adding arXiv is a separate source choice.
6. Collect with conservative page/runtime budgets, review a small candidate pool and archive a local digest. Record network, evidence and coverage limitations honestly.
7. If the user requested recurring delivery, register/update a scheduler through the host and follow the separate unattended acceptance steps in `scheduling.md`.

## Incremental changes

Use `configure --patch <patch.json>` for scalar/nested preferences. Objects merge; arrays replace. Existing SQLite history and archived reports are preserved, and the previous profile is copied into private `config-history/`.

For topics, avoid replacing the whole array when the user asks to add one:

```text
python -I -B scripts/workspace.py --workspace <workspace> topic add --file <topic.json>
python -I -B scripts/workspace.py --workspace <workspace> topic update --id <topic-id> --file <topic-patch.json>
python -I -B scripts/workspace.py --workspace <workspace> topic remove --id <topic-id>
```

Keep a topic's ID stable when changing its display label or queries. Removal changes future matching; it does not erase papers or reading cards. After time/frequency/timezone changes, update the actual scheduled task as well as the profile. Never delete delivery history to implement a preference change.

When the user requests a currently unsupported behavior, explain the boundary. Store a qualitative preference in `selection_guidance` only when the reviewing assistant can actually apply it. Do not invent a provider integration, connector, journal metric or full-text capability.
