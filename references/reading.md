# Full-text reading

This workflow starts only for papers the user selects. Adding a queue item does not authorize publisher login or unattended downloads. Use a user-provided local PDF/text or an explicitly authorized accessible source. Check title and DOI against the stored paper before attaching it. Keep canonical source URLs without login/session parameters. Never save passwords or cookies.

All commands use `python -I -B scripts/digest.py --workspace <workspace>` followed by:

- `reading add --key <key-or-doi> --reason <why>`: record reading intent; idempotent.
- `reading attach --key <key-or-doi> --file <local.pdf-or-text> --source-url <canonical-url>`: copy a source into the workspace by its SHA-256; status becomes full-text ready. It does not read or validate the scientific content.
- `reading show --key <key-or-doi>`: obtain the managed source path and exact hash.
- `reading review --key <key-or-doi> --card <card.json>`: validate and save a versioned full-text card after the actual reading.
- `reading tag --key <key-or-doi> --topic <configured-topic-id> --subtopics <labels>`: correct library organization without modifying archived digests.

Use suitable PDF reading tools for PDFs. If the source is scanned, incomplete, a preview, or inaccessible, preserve the ready/queued state and explain the remaining evidence gap. Do not mark it read based on file size, filename, an abstract, or existence alone.

The card format is:

```json
{
  "paper_key": "the-stored-record-key",
  "source_sha256": "the-attached-source-hash",
  "reading_scope": "fulltext",
  "summary": "Concise synthesis in the configured analysis language",
  "objective": "Research question",
  "method": "Models, algorithms and experimental design",
  "result": "Findings supported by the source",
  "limitations": "Separate author-stated limits, reader inference and missing information",
  "relevance": "Connection to the user's research",
  "next_action": "A concrete reading, comparison or reproduction task",
  "model_assumptions": "Optional: assumptions, boundaries, scales and units",
  "data_validation": "Optional: data, comparators and validation limits",
  "reproducibility": "Optional: code/data availability and missing parameters",
  "evidence": [
    {"field": "method", "locator": "Section 2.1, page 3", "support": "A short exact source excerpt supporting the method."},
    {"field": "result", "locator": "Section 3, Figure 4", "support": "A short exact source excerpt supporting the finding."}
  ]
}
```

Do not invent data, equations, parameter values, performance gains or page numbers. An absent detail is not proof that the full study is deficient. For radiative-transfer papers, distinguish model assumptions from validated behavior and active from passive observables when relevant.

The script checks file identity, required sections and method/result locations. TXT/Markdown excerpts must occur in the attached text; only Unicode canonical form and whitespace are normalized, preserving signs, units and punctuation. PDF excerpts are recorded but are not automatically checked against extracted PDF text; the reader must verify them. These integrity checks do not establish scientific correctness. Cards and sources are versioned; attaching a new source resets readiness while retaining the old card. Missing/changed managed files are flagged for review.

The daily newsletter continues to use abstract-level evidence and separate delivery state. Full-text cards supplement the library; they do not retroactively rewrite previously delivered reports.
