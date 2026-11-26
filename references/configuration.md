# Configuration

The private workspace's `profile.json` is editable. Use `workspace.py configure` to validate changes and retain a backup. `assets/profile.default.json` is a neutral, unconfirmed draft; presets are partial overlays.

| Field | Meaning |
|---|---|
| `topics` | Arbitrary research topics with stable IDs, labels, queries and keyword groups |
| `digest.max_papers` | Maximum selected papers per digest, 1–100; no minimum |
| `digest.publication_types` | Allowed source-reported types, such as `journal-article`, `review`, `proceedings-article`, `preprint` |
| `digest.include_preprints` | Permit preprints; separate labels remain mandatory |
| `digest.include_title_only` | Permit candidates without an abstract; only tentative relevance is allowed |
| `language` | `zh-CN` or `en` for analysis and digest presentation |
| `timezone` | IANA name, e.g. `Asia/Shanghai`, `Europe/Paris`, `America/New_York`; accounts for daylight saving |
| `schedule` | Intent: enabled, manual/daily/weekly, HH:MM, and weekday codes; does not register a task |
| `delivery.channel` | `local`, `codex`, or `connector`; external delivery needs a real authorized connector |
| `journals` | `mode`: any/prefer/only; `names`: named preferences or whitelist; `exclude`: exclusions |
| `journal_watch` | Optional Crossref journal discovery using verified journal names and ISSNs |
| `sources` | crossref/arxiv/openalex/scopus; authenticated sources need the user's keys |
| `selection_guidance` | Freeform scientific preferences applied by the reviewing assistant |
| `excluded_terms` | Whole normalized terms excluded from eligible candidates |
| `collection.publication_age_days` | Recent-publication eligibility window; imprecise dates retain their precision |
| `collection.initial_days` / `overlap_days` | Discovery lookback and overlap; not guaranteed database completeness |
| `collection.page_size` / `scopus_page_size` | Independent page sizes; start Scopus conservatively at 10 |
| `collection.max_pages` / `max_runtime_seconds` | Per-query page and collection runtime budgets |
| `collection.contact_email` | Optional contact for metadata requests; keep it in the private workspace |

## Topic example

```json
{
  "id": "battery-recycling",
  "label": "电池回收",
  "queries": ["lithium battery recycling", "battery material recovery"],
  "require_all": [["battery", "batteries"], ["recycling", "recovery"]],
  "boost_terms": ["life cycle", "reproducibility"],
  "exclude_title_terms": ["opinion"],
  "subtopic_rules": [{"label": "材料回收", "terms": ["material recovery", "lithium recovery"]}]
}
```

Each `require_all` group must match at least one alternative in the actual title or abstract. Groups combine with AND. Boost terms only affect candidate ordering. Missing terms can cause false negatives; broad terms can cause false positives, so the assistant reviews the returned pool.

## Preference patch example

```json
{
  "timezone": "Asia/Shanghai",
  "schedule": {"enabled": true, "frequency": "weekly", "time": "09:00", "weekdays": ["TU", "FR"]},
  "digest": {"max_papers": 5, "include_preprints": true},
  "sources": ["crossref", "arxiv"],
  "journals": {"mode": "prefer", "names": ["Example Journal"], "exclude": []},
  "selection_guidance": ["优先提供可复用的方法与明确的实验验证；不为了达到篇数而放宽关联性。"]
}
```

Replace `Example Journal` with actual verified names. `prefer` changes ranking; `only` excludes nonmatching journal records. A permitted preprint is evaluated separately from a journal whitelist. Explicit journal exclusions still apply. The helper synchronizes the `preprint` publication type when changing `include_preprints` without an explicit type list. Enabling preprints does not enable an additional source by itself.

The skill does not supply or verify JCR/CAS ranks, impact factors or institutional journal lists. If those matter, use a user-provided, dated list of journal names or ISSNs. Different providers classify document types differently; an unknown type is not silently called a journal article.

`preferences_confirmed`, `previously_delivered_dois` and stored deliveries serve different purposes. The first records onboarding completion; the latter two prevent duplicate notifications. Configuration edits must not clear delivery history. Keys live in protected storage; `credentials` contains references only.

The static library UI and reading-card labels currently use Chinese. English digest reports and agent-written analysis are supported. The configured timezone controls report dates; API discovery windows retain their documented source-date semantics.
