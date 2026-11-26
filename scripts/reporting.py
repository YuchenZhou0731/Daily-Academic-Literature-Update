"""English digest presentation; evidence stays identical to the source records."""


def english_report(report):
    from digest import safe_url
    coverage = report["coverage"]
    gaps = sum(row.get("status") != "complete" or not row.get("caught_up", True) for row in coverage.get("queries", []))
    if not coverage.get("queries"):
        coverage_text = "No online collection was recorded for this run. Coverage is unverified."
    elif gaps or coverage.get("partial_run"):
        coverage_text = f"Incomplete coverage: {gaps} queries failed, reached their page budget, or have not caught up. Progress is retained."
    else:
        coverage_text = "Configured queries were traversed; database coverage, indexing delays and query wording still limit discovery."
    lines = [f"# Literature digest · {report['date']}", "", f"Selected {len(report['papers'])}; {report['pending_after']} relevant candidates remain for review.", "", coverage_text, ""]
    if report.get("selection_note"):
        lines += ["Selection note: " + report["selection_note"], ""]
    if not report["papers"]:
        lines += ["No papers were selected for this digest.", ""]
    for index, paper in enumerate(report["papers"], 1):
        analysis = paper.get("analysis", {})
        title = analysis.get("title_local") or analysis.get("title_zh") or paper["title"]
        evidence = "Database abstract read; full text not read" if paper.get("abstract") else "Title and metadata only; abstract and full text not read"
        lines += [f"## {index}. {title}", "", paper["title"], "",
                  "- Topics: " + "; ".join(topic["label"] for topic in paper["topics"]),
                  "- Sources: " + ", ".join(paper["sources"]),
                  "- Journal: " + (paper.get("journal") or "Not provided"),
                  "- Publication date: " + (paper.get("published") or "Not provided"),
                  "- Date basis: " + (paper.get("publication_source") or "Unspecified") + "; precision: " + paper.get("date_precision", "unknown") + "; first-online date not independently verified",
                  "- Type: " + ("Preprint; journal peer review not confirmed" if paper.get("preprint") else "Database publication record"),
                  "- Authors: " + ("; ".join(paper.get("authors", [])) or "Not provided") + (" (first author only)" if paper.get("authors_scope") == "first-author" else ""),
                  "- DOI: " + (paper.get("doi") or "Not provided"),
                  "- Link: " + (safe_url(paper.get("url")) or "Not provided"), "- Evidence: " + evidence, ""]
        for field, label in (("relevance", "Research relevance"), ("goal", "Objective"), ("method", "Method"), ("result", "Abstract-reported findings"), ("limitation", "Evidence boundary")):
            if analysis.get(field):
                lines += [f"**{label}:** {analysis[field]}", ""]
        if not analysis:
            lines += ["No agent analysis has been added. The following text is supplied by the metadata source.", ""]
        if paper.get("abstract"):
            lines += ["**Source abstract:** " + paper["abstract"], ""]
    return "\n".join(lines)
