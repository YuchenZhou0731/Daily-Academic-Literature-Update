# Full-text reading

This workflow starts only for papers the user selects. Adding a queue item does not authorize publisher login or unattended downloads. Use a user-provided local PDF/text or an explicitly authorized accessible source. Check title and DOI against the stored paper before attaching it. Keep canonical source URLs without login/session parameters. Never save passwords or cookies.

All commands use `python -I -B scripts/digest.py --workspace "xxx"` followed by:

- `reading add --key "xxx" --reason "xxx"`: record reading intent; idempotent.
- `reading attach --key "xxx" --file "xxx" --source-url "xxx"`: copy a source into the workspace by its SHA-256; status becomes full-text ready. It does not read or validate the scientific content.
- `reading show --key "xxx"`: obtain the managed source path and exact hash.
- `reading review --key "xxx" --card "xxx"`: validate and save a versioned full-text card after the actual reading.
- `reading tag --key "xxx" --topic "xxx" --subtopics "xxx"`: correct library organization without modifying archived digests.

Use suitable PDF reading tools for PDFs. If the source is scanned, incomplete, a preview, or inaccessible, preserve the ready/queued state and explain the remaining evidence gap. Do not mark it read based on file size, filename, an abstract, or existence alone.

The card format is:

```json
{
  "paper_key": "xxx",
  "source_sha256": "xxx",
  "reading_scope": "fulltext",
  "summary": "xxx",
  "objective": "xxx",
  "method": "xxx",
  "result": "xxx",
  "limitations": "xxx",
  "relevance": "xxx",
  "next_action": "xxx",
  "model_assumptions": "xxx",
  "data_validation": "xxx",
  "reproducibility": "xxx",
  "evidence": [
    {"field": "method", "locator": "xxx", "support": "xxx"},
    {"field": "result", "locator": "xxx", "support": "xxx"}
  ]
}
```

Replace `xxx` with verified record identifiers, source hashes and evidence-grounded content. The `reading_scope` and evidence `field` values above are schema constants. Do not invent data, equations, parameter values, performance gains or page numbers. An absent detail is not proof that the full study is deficient.

The script checks file identity, required sections and method/result locations. TXT/Markdown excerpts must occur in the attached text; only Unicode canonical form and whitespace are normalized, preserving signs, units and punctuation. PDF excerpts are recorded but are not automatically checked against extracted PDF text; the reader must verify them. These integrity checks do not establish scientific correctness. Cards and sources are versioned; attaching a new source resets readiness while retaining the old card. Missing/changed managed files are flagged for review.

The daily newsletter continues to use abstract-level evidence and separate delivery state. Full-text cards supplement the library; they do not retroactively rewrite previously delivered reports.
