"""User-selected full-text reading queue and evidence-linked cards."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import unicodedata

from digest import Store, assess, fingerprint, load_json, normalized, now, render_library, safe_url, write_json


FIELDS = ("summary", "objective", "method", "result", "limitations", "relevance", "next_action")
LABELS = {"summary": "概述", "objective": "研究目标", "method": "方法", "result": "结果", "limitations": "局限与适用条件", "relevance": "研究关联", "next_action": "下一步", "model_assumptions": "模型假设", "data_validation": "数据与验证", "reproducibility": "复现信息"}


def excerpt_text(value):
    return " ".join(unicodedata.normalize("NFC", value).split())


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def queue_entry(store, key):
    row = store.db.execute("SELECT * FROM reading_queue WHERE paper_key=?", (key,)).fetchone()
    return {"status": row["status"], **json.loads(row["payload"])} if row else None


def save_entry(store, key, entry):
    status = entry["status"]
    payload = {name: value for name, value in entry.items() if name != "status"}
    with store.db:
        store.db.execute("INSERT OR REPLACE INTO reading_queue VALUES (?,?,?,?)", (key, status, json.dumps(payload, ensure_ascii=False), now()))


def add(store, identifier, reason=""):
    key = store.resolve_key(identifier)
    entry = queue_entry(store, key) or {"status": "queued", "requested_at": now(), "source": None, "card_id": None}
    entry["reason"] = reason or entry.get("reason") or "用户选定待精读"
    save_entry(store, key, entry)
    return key


def attach(store, identifier, source_path, source_url=""):
    key = store.resolve_key(identifier)
    source = Path(source_path).resolve()
    if not source.is_file() or not source.stat().st_size:
        raise ValueError("A non-empty local full-text file is required")
    suffix = source.suffix.lower()
    if suffix not in {".pdf", ".txt", ".md"}:
        raise ValueError("Attach a PDF or extracted UTF-8 TXT/Markdown full text")
    if suffix == ".pdf":
        with source.open("rb") as stream:
            if not stream.read(5).startswith(b"%PDF-"):
                raise ValueError("The selected file does not have a PDF header")
    else:
        source.read_text(encoding="utf-8-sig")
    if source_url and not safe_url(source_url):
        raise ValueError("Source URL must use HTTP or HTTPS")
    digest = file_hash(source)
    target = store.root / "reading" / "sources" / key / (digest + suffix)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if file_hash(target) != digest:
            raise ValueError("Stored source file is corrupt; it was not overwritten")
    else:
        shutil.copyfile(source, target)
        if file_hash(target) != digest:
            raise ValueError("The copied source does not match the original")
    entry = queue_entry(store, key) or {"requested_at": now(), "reason": "用户指定全文", "card_id": None}
    if (entry.get("source") or {}).get("sha256") != digest:
        entry["card_id"] = None
        entry["status"] = "fulltext-ready"
    else:
        entry.setdefault("status", "fulltext-ready")
    entry["source"] = {"path": str(target.relative_to(store.root)), "sha256": digest, "url": source_url or (entry.get("source") or {}).get("url", ""), "attached_at": now()}
    save_entry(store, key, entry)
    return key


def verified_source(store, entry):
    source = (entry or {}).get("source")
    if not source:
        raise ValueError("No full-text file is attached")
    path = (store.root / source["path"]).resolve()
    if not path.is_relative_to(store.root / "reading" / "sources"):
        raise ValueError("Attached source path is outside the managed reading directory")
    if not path.is_file() or file_hash(path) != source["sha256"]:
        raise ValueError("Attached full text is missing or changed; attach and review the correct version")
    return path


def review(store, identifier, input_path):
    key = store.resolve_key(identifier)
    entry = queue_entry(store, key)
    source_path = verified_source(store, entry)
    card = load_json(input_path)
    if card.get("paper_key") != key or card.get("source_sha256") != entry["source"]["sha256"]:
        raise ValueError("The reading card must identify this paper and the attached source hash")
    if card.get("reading_scope") != "fulltext":
        raise ValueError("Only an explicitly completed full-text reading can advance this status")
    if any(not isinstance(card.get(field), str) or not card[field].strip() for field in FIELDS):
        raise ValueError("The reading card is missing a required non-empty section")
    if any(field in card and not isinstance(card[field], str) for field in LABELS):
        raise ValueError("Reading-card sections must be text")
    evidence = card.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("Reading cards require source evidence with page/section locations")
    covered = set()
    source_text = excerpt_text(source_path.read_text(encoding="utf-8-sig")) if source_path.suffix.lower() in {".txt", ".md"} else None
    for item in evidence:
        if not isinstance(item, dict) or item.get("field") not in LABELS:
            raise ValueError("An evidence item refers to an unknown section")
        if not isinstance(item.get("locator"), str) or not item["locator"].strip():
            raise ValueError("Every evidence item requires a page or section locator")
        if not isinstance(item.get("support"), str) or not item["support"].strip():
            raise ValueError("Every evidence item requires a short supporting source excerpt")
        if source_text is not None and excerpt_text(item["support"]) not in source_text:
            raise ValueError("A supporting excerpt was not found in the attached text")
        covered.add(item["field"])
    if not {"method", "result"}.issubset(covered):
        raise ValueError("Method and result each need a source location and supporting excerpt")
    card = {**card, "title": store.get(key)["title"], "reviewed_at": now(), "source_path": entry["source"]["path"],
            "excerpt_check": "matched-attached-text" if source_text is not None else "PDF-locations-recorded; not automatically text-verified"}
    card_id = fingerprint({name: value for name, value in card.items() if name != "reviewed_at"})[:24]
    old = store.db.execute("SELECT path,payload FROM reading_cards WHERE id=?", (card_id,)).fetchone()
    if old:
        path = Path(old[0])
        card["reviewed_at"] = json.loads(old[1])["reviewed_at"]
    else:
        directory = store.root / "reading" / "cards" / key
        path = directory / (card_id + ".md")
        directory.mkdir(parents=True, exist_ok=True)
        lines = ["# " + card["title"], "", "阅读级别：已完成所附版本的全文阅读。", "", "源文件：" + card["source_path"], ""]
        for field, label in LABELS.items():
            if card.get(field):
                lines.extend(["## " + label, "", card[field], ""])
        lines.extend(["## 证据定位", ""])
        for item in evidence:
            lines.extend([f"- {LABELS[item['field']]}：{item['locator']}", "  - 来源摘录：" + item["support"]])
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        write_json(directory / (card_id + ".json"), card)
        with store.db:
            store.db.execute("INSERT INTO reading_cards VALUES (?,?,?,?,?)", (card_id, key, card["reviewed_at"], json.dumps(card, ensure_ascii=False), str(path)))
    entry.update({"status": "fulltext-read", "card_id": card_id, "reviewed_at": card["reviewed_at"]})
    save_entry(store, key, entry)
    return path


def tag(store, profile, identifier, primary_topic, subtopics):
    key = store.resolve_key(identifier)
    if primary_topic not in {topic["id"] for topic in profile["topics"]}:
        raise ValueError("Select one configured primary research topic")
    labels = list(dict.fromkeys(label.strip() for label in subtopics if label.strip()))
    payload = {"primary_topic": primary_topic, "subtopics": labels, "updated": now(), "basis": "explicit"}
    with store.db:
        store.db.execute("INSERT OR REPLACE INTO paper_tags VALUES (?,?)", (key, json.dumps(payload, ensure_ascii=False)))
    return key


def taxonomy(store, profile, paper):
    row = store.db.execute("SELECT payload FROM paper_tags WHERE paper_key=?", (paper["key"],)).fetchone()
    if row:
        return json.loads(row[0])
    primary = next((item["id"] for item in paper.get("topics", [])), "unclassified")
    topic = next((item for item in profile["topics"] if item["id"] == primary), {})
    haystack = normalized(paper.get("title", "") + " " + paper.get("abstract", ""))
    labels = [rule["label"] for rule in topic.get("subtopic_rules", []) if any(" " + normalized(term) + " " in " " + haystack + " " for term in rule["terms"])]
    return {"primary_topic": primary, "subtopics": labels, "basis": "metadata-match"}


def reading_info(store, key):
    entry = queue_entry(store, key)
    if not entry:
        return {"status": "not-queued"}
    result = dict(entry)
    if entry.get("source"):
        try:
            source = verified_source(store, entry)
            result["source_path"] = str(source)
            result["source_integrity"] = "matches"
        except (ValueError, OSError):
            result["status"] = "needs-review"
            result["source_integrity"] = "missing-or-changed"
    if entry.get("card_id"):
        card = store.db.execute("SELECT payload,path FROM reading_cards WHERE id=?", (entry["card_id"],)).fetchone()
        if card:
            result["card"] = json.loads(card[0])
            result["card_path"] = str(Path(card[1]).relative_to(store.root))
    return result


def decorate_library(store, profile, papers):
    items = {paper["key"]: paper for paper in papers}
    for row in store.db.execute("SELECT paper_key FROM reading_queue UNION SELECT paper_key FROM paper_tags"):
        key = row[0]
        if key not in items:
            paper = store.get(key)
            assessment = assess(paper, profile, eligible_only=False) or {"score": 0, "topics": [], "evidence": "abstract" if paper.get("abstract") else "title-only"}
            items[key] = {**paper, **assessment, "analysis": {}, "digest_date": ""}
    for key, paper in items.items():
        paper["taxonomy"] = taxonomy(store, profile, paper)
        paper["reading"] = reading_info(store, key)
    return list(items.values())


def register_parser(commands):
    parser = commands.add_parser("reading", help="Manage user-selected full-text reading")
    sub = parser.add_subparsers(dest="reading_action", required=True)
    entry = sub.add_parser("add")
    entry.add_argument("--key", required=True)
    entry.add_argument("--reason", default="")
    attachment = sub.add_parser("attach")
    attachment.add_argument("--key", required=True)
    attachment.add_argument("--file", required=True)
    attachment.add_argument("--source-url", default="")
    review_parser = sub.add_parser("review")
    review_parser.add_argument("--key", required=True)
    review_parser.add_argument("--card", required=True)
    tagging = sub.add_parser("tag")
    tagging.add_argument("--key", required=True)
    tagging.add_argument("--topic", required=True)
    tagging.add_argument("--subtopics", nargs="*", default=[])
    sub.add_parser("list")
    showing = sub.add_parser("show")
    showing.add_argument("--key", required=True)


def execute(args, workspace, profile):
    store = Store(workspace)
    try:
        action = args.reading_action
        if action == "add":
            result = {"paper_key": add(store, args.key, args.reason)}
        elif action == "attach":
            key = attach(store, args.key, args.file, args.source_url)
            result = {"paper_key": key, **reading_info(store, key)}
        elif action == "review":
            result = {"card_path": str(review(store, args.key, args.card))}
        elif action == "tag":
            result = {"paper_key": tag(store, profile, args.key, args.topic, args.subtopics)}
        elif action == "show":
            key = store.resolve_key(args.key)
            result = {"paper_key": key, "title": store.get(key)["title"], **reading_info(store, key)}
        else:
            result = []
            for row in store.db.execute("SELECT paper_key FROM reading_queue ORDER BY updated DESC"):
                info = reading_info(store, row[0])
                result.append({"paper_key": row[0], "title": store.get(row[0])["title"], "status": info["status"], "source_path": info.get("source_path", ""), "source_sha256": (info.get("source") or {}).get("sha256", ""), "card_path": info.get("card_path", "")})
        if action not in {"list", "show"}:
            render_library(store, profile)
        return result
    finally:
        store.close()
