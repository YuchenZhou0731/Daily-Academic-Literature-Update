"""Collect, review and archive a personal literature digest using public metadata."""
from __future__ import annotations

import argparse
import datetime as dt
from decimal import Decimal, InvalidOperation
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


UTC = dt.timezone.utc
SOURCES = ("crossref", "openalex", "arxiv", "scopus")


class RateLimitError(RuntimeError):
    def __init__(self, message, retry_after=3600):
        super().__init__(message)
        self.retry_after = retry_after


class WorkspaceLock:
    def __init__(self, workspace):
        self.path = Path(workspace) / "operation.lock"

    def __enter__(self):
        try:
            handle = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as error:
            raise RuntimeError("Another operation holds operation.lock. Check the recorded process before removing a stale lock.") from error
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid(), "started": now()}, stream)
        return self

    def __exit__(self, *_):
        self.path.unlink(missing_ok=True)


def now():
    return dt.datetime.now(UTC).isoformat()


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def text(value):
    if isinstance(value, list):
        value = " ".join(str(part) for part in value if part)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", html.unescape(str(value or "")))).strip()


def normalized(value):
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", text(value)).casefold()))


def contains(haystack, term):
    return bool(normalized(term)) and f" {normalized(term)} " in f" {normalized(haystack)} "


def doi(value):
    return re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", str(value or "").strip(), flags=re.I).lower()


def safe_url(value):
    value = str(value or "").strip()
    return value if urllib.parse.urlsplit(value).scheme in {"http", "https"} else ""


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def source_page_size(source, settings):
    return int(settings.get("scopus_page_size", min(10, settings["page_size"]))) if source == "scopus" else int(settings["page_size"])


def query_key(source, query, settings):
    return fingerprint(["v2", source, query, source_page_size(source, settings),
                        settings.get("crossref_query_field", "query.title"), settings.get("crossref_date_mode", "created-date")])


def query_plans(profile):
    queries = list(dict.fromkeys(query for topic in profile["topics"] for query in topic["queries"]))
    plans = []
    if "crossref" in profile["sources"]:
        for journal in profile.get("journal_watch", []):
            plans.append({"source": "crossref", "query": "journal:" + journal["issn"], "label": journal["name"], "kind": "journal"})
    for source in profile["sources"]:
        for query in queries:
            plans.append({"source": source, "query": query, "label": query, "kind": "topic"})
    order = {"arxiv": 1, "openalex": 2, "scopus": 3, "crossref": 4}
    return sorted(plans, key=lambda plan: 0 if plan["kind"] == "journal" else order[plan["source"]])


def profile_for(workspace):
    from configuration import validate_profile
    return validate_profile(load_json(Path(workspace) / "profile.json"))


def assess(paper, profile, today=None, eligible_only=True):
    from configuration import local_now
    today = today or local_now(profile).date()
    content = paper.get("title", "") + " " + paper.get("abstract", "")
    if eligible_only and any(contains(content, term) for term in profile.get("excluded_terms", [])):
        return None
    if eligible_only and doi(paper.get("doi")) in {doi(value) for value in profile.get("previously_delivered_dois", [])}:
        return None
    if eligible_only and paper.get("preprint") and not profile["digest"].get("include_preprints", True):
        return None
    journals = profile.get("journals", {"mode": "prefer", "names": profile.get("preferred_journals", [])})
    journal = normalized(paper.get("journal"))
    preferred = {normalized(name) for name in journals.get("names", [])}
    if eligible_only and journal in {normalized(name) for name in journals.get("exclude", [])}:
        return None
    if eligible_only and not paper.get("preprint") and journals.get("mode") == "only" and journal not in preferred:
        return None
    allowed_types = profile["digest"].get("publication_types")
    publication_type = "preprint" if paper.get("preprint") else paper.get("publication_type", "unknown")
    if eligible_only and allowed_types and publication_type not in allowed_types:
        return None
    if eligible_only and not paper.get("abstract") and not profile["digest"].get("include_title_only", True):
        return None
    published = paper.get("published", "")
    if eligible_only and published:
        first, last = publication_bounds(published)
        if first > today or (today - last).days > profile["collection"]["publication_age_days"]:
            return None
    matches = []
    scores = []
    for topic in profile["topics"]:
        if any(contains(paper.get("title", ""), term) for term in topic.get("exclude_title_terms", [])):
            continue
        if all(any(contains(content, term) for term in group) for group in topic["require_all"]):
            matched = [term for group in topic["require_all"] for term in group if contains(content, term)]
            boosts = [term for term in topic.get("boost_terms", []) if contains(content, term)]
            matches.append({"id": topic["id"], "label": topic["label"], "terms": matched, "boosts": boosts})
            scores.append(10 * len(topic["require_all"]) + 3 * sum(contains(paper["title"], term) for term in matched) + min(12, len(boosts) * 2))
    if not matches:
        return None
    score = max(scores) + (4 if paper.get("abstract") else 0)
    if journals.get("mode") in {"prefer", "only"} and journal in preferred:
        score += 2
    return {"score": score, "topics": matches, "evidence": "abstract" if paper.get("abstract") else "title-only"}


class Store:
    def __init__(self, workspace):
        self.root = Path(workspace).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "state.sqlite3", timeout=20)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS papers (key TEXT PRIMARY KEY, payload TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS aliases (alias TEXT PRIMARY KEY, paper_key TEXT NOT NULL REFERENCES papers(key));
          CREATE TABLE IF NOT EXISTS checkpoints (key TEXT PRIMARY KEY, source TEXT NOT NULL, query TEXT NOT NULL, watermark TEXT, pending_from TEXT, status TEXT, error TEXT);
          CREATE TABLE IF NOT EXISTS digests (id TEXT PRIMARY KEY, created TEXT NOT NULL, path TEXT NOT NULL, payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS digest_items (digest_id TEXT REFERENCES digests(id), paper_key TEXT REFERENCES papers(key), PRIMARY KEY(digest_id,paper_key));
          CREATE TABLE IF NOT EXISTS deliveries (digest_id TEXT REFERENCES digests(id), channel TEXT, status TEXT, receipt TEXT, error TEXT, updated TEXT, PRIMARY KEY(digest_id,channel));
          CREATE TABLE IF NOT EXISTS query_progress (key TEXT PRIMARY KEY, payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS source_cooldowns (source TEXT PRIMARY KEY, retry_at TEXT NOT NULL, error TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS reading_queue (paper_key TEXT PRIMARY KEY REFERENCES papers(key), status TEXT NOT NULL, payload TEXT NOT NULL, updated TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS reading_cards (id TEXT PRIMARY KEY, paper_key TEXT NOT NULL REFERENCES papers(key), created TEXT NOT NULL, payload TEXT NOT NULL, path TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS paper_tags (paper_key TEXT PRIMARY KEY REFERENCES papers(key), payload TEXT NOT NULL);
        """)

    def close(self):
        self.db.close()

    def get(self, key):
        row = self.db.execute("SELECT payload FROM papers WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def resolve_key(self, identifier):
        if self.get(identifier):
            return identifier
        row = self.db.execute("SELECT paper_key FROM aliases WHERE alias=?", ("doi:" + doi(identifier),)).fetchone()
        if not row:
            raise ValueError("Paper not found in this workspace; use a stored key or DOI")
        return row[0]

    def upsert(self, paper):
        paper = dict(paper)
        paper["doi"] = doi(paper.get("doi"))
        identities = ["doi:" + paper["doi"]] if paper["doi"] else []
        identities += paper.get("identifiers", [])
        title_alias = "title:" + fingerprint([normalized(paper.get("title")), paper.get("published", "")[:4]])
        for alias in identities + [title_alias]:
            found = self.db.execute("SELECT paper_key FROM aliases WHERE alias=?", (alias,)).fetchone()
            if not found:
                continue
            old = self.get(found[0])
            if alias == title_alias and old.get("doi") and paper["doi"] and old["doi"] != paper["doi"]:
                continue
            key = found[0]
            break
        else:
            key = fingerprint(identities[0] if identities else title_alias)[:24]
            old = None
        if old:
            merged = dict(old)
            published_types = {"journal-article", "review"}
            keep_published_metadata = old.get("publication_type") in published_types and paper.get("preprint")
            for field, value in paper.items():
                if (field in {"published", "publication_source", "date_precision"} and old.get("published")
                        and paper.get("publication_source", "").startswith("Scopus")
                        and not old.get("publication_source", "").startswith("Scopus") and not old.get("preprint")):
                    continue
                if field in {"authors", "authors_scope"} and paper.get("authors_scope") == "first-author" and len(old.get("authors", [])) > 1:
                    continue
                if keep_published_metadata and field in {"title", "journal", "authors", "url", "published", "publication_source", "date_precision", "publication_type"}:
                    continue
                if field in {"publication_source", "date_precision"} and not paper.get("published"):
                    continue
                if value and field not in {"abstract", "abstract_source", "sources", "identifiers", "raw_files", "preprint"}:
                    merged[field] = value
            if len(paper.get("abstract", "")) > len(old.get("abstract", "")):
                merged["abstract"] = paper["abstract"]
                merged["abstract_source"] = paper.get("abstract_source", "")
            if paper.get("authors") and not paper.get("authors_scope"):
                merged.pop("authors_scope", None)
            for field in ("sources", "identifiers", "raw_files"):
                merged[field] = sorted(set(old.get(field, []) + paper.get(field, [])))
            merged["preprint"] = False if merged.get("publication_type") in published_types else bool(old.get("preprint") or paper.get("preprint"))
            paper = merged
        paper["key"] = key
        stamp = now()
        self.db.execute("INSERT INTO papers VALUES (?,?,?,?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload,last_seen=excluded.last_seen", (key, json.dumps(paper, ensure_ascii=False), stamp, stamp))
        for alias in identities + [title_alias]:
            self.db.execute("INSERT OR IGNORE INTO aliases VALUES (?,?)", (alias, key))
        return key

    def window(self, source, query, settings, today):
        key = query_key(source, query, settings)
        progress = self.db.execute("SELECT payload FROM query_progress WHERE key=?", (key,)).fetchone()
        if progress:
            return key, json.loads(progress[0])["window_from"]
        row = self.db.execute("SELECT * FROM checkpoints WHERE key=?", (key,)).fetchone()
        anchor = dt.date.fromisoformat(row["watermark"]) if row and row["watermark"] else today
        days = settings.get("crossref_overlap_days", settings["overlap_days"]) if source == "crossref" and row and row["watermark"] else settings["overlap_days"] if row and row["watermark"] else settings["initial_days"]
        start = anchor - dt.timedelta(days=days)
        if row and row["pending_from"]:
            start = min(start, dt.date.fromisoformat(row["pending_from"]))
        return key, start.isoformat()

    def checkpoint(self, key, source, query, start, end, status, error=""):
        existing = self.db.execute("SELECT watermark,pending_from FROM checkpoints WHERE key=?", (key,)).fetchone()
        watermark = end if status == "complete" else (existing["watermark"] if existing else None)
        pending = None if status == "complete" else min(start, (existing["pending_from"] or start) if existing else start)
        self.db.execute("INSERT OR REPLACE INTO checkpoints VALUES (?,?,?,?,?,?,?)", (key, source, query, watermark, pending, status, error))

    def candidates(self, profile, include_archived=False):
        query = "SELECT * FROM papers"
        if not include_archived:
            query += " WHERE key NOT IN (SELECT paper_key FROM digest_items)"
        results = []
        for row in self.db.execute(query):
            paper = json.loads(row["payload"])
            assessment = assess(paper, profile)
            if assessment:
                results.append({**paper, **assessment, "first_seen": row["first_seen"]})
        return sorted(results, key=lambda paper: (-paper["score"], paper["first_seen"], paper["key"]))


class HttpClient:
    def __init__(self, settings, raw_dir, credentials=None):
        from credentials import AuthRedirectGuard, Credentials
        self.settings = settings
        self.raw_dir = Path(raw_dir)
        self.credentials = credentials or Credentials(self.raw_dir.parent.parent)
        self.last_request = {}
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), AuthRedirectGuard())
        self.openalex_budget = None

    def reserve_openalex(self):
        if self.openalex_budget is None:
            data, _ = self.get("https://api.openalex.org/rate-limit", "openalex", "free-budget", 0)
            try:
                limits = data["rate_limit"]
                values = [Decimal(str(limits[key])) for key in ("daily_remaining_usd", "daily_budget_usd")]
                cost = Decimal(str(limits["endpoint_costs_usd"]["search"]))
                cap = Decimal(str(self.settings.get("openalex_max_run_usd", "0.10")))
                if any(not value.is_finite() or value < 0 for value in [*values, cost, cap]):
                    raise ValueError("Invalid budget")
                self.openalex_budget = {"remaining": min(*values, cap), "cost": cost,
                                        "reset": max(60, min(86400, float(limits["resets_in_seconds"])))}
            except (KeyError, TypeError, ValueError, InvalidOperation):
                raise RuntimeError("OpenAlex free daily allowance could not be verified; search deferred") from None
        budget = self.openalex_budget
        if budget["remaining"] < budget["cost"]:
            raise RateLimitError("OpenAlex free allowance or configured run budget exhausted", budget["reset"])
        budget["remaining"] -= budget["cost"]

    def get(self, url, source, query_id, page, as_xml=False):
        interval = 3.1 if source == "arxiv" else 0.3
        headers = {"User-Agent": "LiteratureDigestSkill/0.1", "Accept": "application/atom+xml" if as_xml else "application/json"}
        if self.settings.get("contact_email"):
            headers["User-Agent"] += " (mailto:" + self.settings["contact_email"] + ")"
        headers.update(self.credentials.headers(source, url))
        for attempt in range(self.settings.get("retries", 2) + 1):
            if (source == "openalex" and self.credentials.configured(source)
                    and urllib.parse.urlsplit(url).path == "/works"):
                self.reserve_openalex()
            time.sleep(max(0, interval - (time.monotonic() - self.last_request.get(source, 0))))
            self.last_request[source] = time.monotonic()
            try:
                request = urllib.request.Request(url, headers=headers)
                deadline = time.monotonic() + self.settings["timeout_seconds"]
                with self.opener.open(request, timeout=self.settings["timeout_seconds"]) as response:
                    chunks = []
                    length = 0
                    while True:
                        if time.monotonic() > deadline:
                            raise TimeoutError("Response exceeded the total request time budget")
                        chunk = response.read1(65536)
                        if not chunk:
                            break
                        chunks.append(chunk)
                        length += len(chunk)
                        if length > 8_000_000:
                            raise ValueError("Metadata response exceeded 8 MB; reduce page_size")
                    body = self.credentials.redact(b"".join(chunks).decode("utf-8"))
                data = ET.fromstring(body) if as_xml else json.loads(body)
                path = self.raw_dir / source / f"{query_id[:16]}-{page}.{'xml' if as_xml else 'json'}"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(body, encoding="utf-8")
                return data, str(path.resolve())
            except urllib.error.HTTPError as error:
                error_body = self.credentials.redact(error.read(16384).decode("utf-8", errors="replace"))
                error_path = self.raw_dir / source / f"{query_id[:16]}-{page}-error-{attempt}.txt"
                error_path.parent.mkdir(parents=True, exist_ok=True)
                error_path.write_text(error_body, encoding="utf-8")
                if error.code not in {429, 500, 502, 503, 504} or attempt == self.settings.get("retries", 2):
                    if error.code == 429:
                        raw_delay = error.headers.get("Retry-After", "")
                        raise RateLimitError(f"HTTP 429: {source}", float(raw_delay) if raw_delay.isdigit() else 3600) from error
                    raise RuntimeError(f"HTTP {error.code}: {source}") from error
                retry_after = error.headers.get("Retry-After", "")
                delay = float(retry_after) if retry_after.isdigit() else 2 ** (attempt + 1)
                if delay > self.settings.get("max_retry_wait_seconds", 30):
                    raise RateLimitError(f"{source} rate limit; retry deferred", delay) from error
                time.sleep(delay)
            except (urllib.error.URLError, TimeoutError) as error:
                if attempt == self.settings.get("retries", 2):
                    raise RuntimeError(f"{source} request failed: {type(error).__name__}") from None
                time.sleep(2 ** (attempt + 1))


def publication(parts):
    if not parts or not isinstance(parts, list):
        return ""
    try:
        value = dt.date(int(parts[0]), int(parts[1]) if len(parts) > 1 else 1, int(parts[2]) if len(parts) > 2 else 1).isoformat()
        return value[:4] if len(parts) == 1 else value[:7] if len(parts) == 2 else value
    except (ValueError, TypeError, IndexError):
        return ""


def publication_bounds(value):
    parts = [int(part) for part in value.split("-")]
    first = dt.date(parts[0], parts[1] if len(parts) > 1 else 1, parts[2] if len(parts) > 2 else 1)
    if len(parts) == 1:
        return first, dt.date(parts[0], 12, 31)
    if len(parts) == 2:
        following = dt.date(parts[0] + (parts[1] == 12), 1 if parts[1] == 12 else parts[1] + 1, 1)
        return first, following - dt.timedelta(days=1)
    return first, first


def base_paper(source, title, abstract="", **fields):
    cleaned = text(abstract)
    return {"title": text(title), "doi": "", "published": "", "journal": "", "authors": [], "url": "", "preprint": False, "identifiers": [], "raw_files": [], "abstract": cleaned, "abstract_source": source if cleaned else "", "sources": [source], **fields}


def crossref_paper(item):
    published = ""
    date_source = "unknown"
    for field in ("published-online", "published", "published-print", "issued"):
        block = item.get(field, {})
        parts = block.get("date-parts", [[]])[0]
        published = publication(parts)
        if published:
            date_source = field
            break
    identifier = doi(item.get("DOI"))
    return base_paper("Crossref", item.get("title", []), item.get("abstract", ""), doi=identifier,
                      publication_type="preprint" if item.get("type") == "posted-content" else item.get("type", "unknown"),
                      published=published, publication_source="Crossref " + date_source,
                      date_precision={4: "year", 7: "month", 10: "day"}.get(len(published), "unknown"),
                      created_at=(item.get("created") or {}).get("date-time", ""), journal=text(item.get("container-title", [])),
                      authors=[text(" ".join([author.get("given", ""), author.get("family", "")])) for author in item.get("author", [])],
                      url="https://doi.org/" + identifier if identifier else safe_url(item.get("URL")),
                      preprint=item.get("type") == "posted-content")


def openalex_paper(item):
    index = item.get("abstract_inverted_index") or {}
    words = sorted((position, word) for word, positions in index.items() for position in positions)
    location = item.get("primary_location") or {}
    identifier = doi(item.get("doi"))
    return base_paper("OpenAlex", item.get("title"), " ".join(word for _, word in words), doi=identifier,
                      publication_type="journal-article" if item.get("type") == "article" and (location.get("source") or {}).get("type") == "journal" else item.get("type", "unknown"),
                      published=(item.get("publication_date") or "")[:10], publication_source="OpenAlex publication_date", date_precision="day" if item.get("publication_date") else "unknown",
                      journal=(location.get("source") or {}).get("display_name", ""),
                      authors=[text((author.get("author") or {}).get("display_name")) for author in item.get("authorships", [])],
                      identifiers=["openalex:" + item["id"].rsplit("/", 1)[-1]] if item.get("id") else [],
                      url="https://doi.org/" + identifier if identifier else safe_url(location.get("landing_page_url")),
                      preprint=item.get("type") == "preprint")


def scopus_paper(item):
    raw_date = str(item.get("prism:coverDate") or "")
    try:
        published = publication([int(part) for part in raw_date.split("-")])
    except ValueError:
        published = ""
    display = text(item.get("prism:coverDisplayDate"))
    if re.fullmatch(r"\d{4}", display):
        published = publication([int(display)])
    elif re.fullmatch(r"[A-Za-z]+ \d{4}", display):
        for pattern in ("%B %Y", "%b %Y"):
            try:
                parsed = dt.datetime.strptime(display, pattern)
                published = publication([parsed.year, parsed.month])
                break
            except ValueError:
                pass
        else:
            published = published[:4]
    elif re.fullmatch(r"\d{4}-\d{2}", display):
        published = publication([int(part) for part in display.split("-")])
    identifier = doi(item.get("prism:doi"))
    subtype = item.get("subtype")
    journal_article = item.get("prism:aggregationType") == "Journal"
    publication_type = "review" if journal_article and subtype == "re" else "journal-article" if journal_article and subtype == "ar" else "unknown"
    return base_paper("Scopus", item.get("dc:title"), item.get("dc:description", ""), doi=identifier,
                      publication_type=publication_type, published=published,
                      publication_source="Scopus cover/issue date (not first-online)",
                      date_precision={4: "year", 7: "month", 10: "day"}.get(len(published), "unknown"),
                      journal=text(item.get("prism:publicationName")), authors=[text(item["dc:creator"])] if item.get("dc:creator") else [],
                      authors_scope="first-author", identifiers=["scopus:" + item["eid"]] if item.get("eid") else [],
                      url="https://doi.org/" + identifier if identifier else next((safe_url(link.get("@href")) for link in item.get("link", []) if link.get("@ref") == "scopus"), ""))


ATOM = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom", "o": "http://a9.com/-/spec/opensearch/1.1/"}


def arxiv_paper(entry):
    field = lambda name: entry.findtext(name, default="", namespaces=ATOM)
    identifier = re.sub(r"v\d+$", "", field("a:id").split("/abs/")[-1])
    return base_paper("arXiv", field("a:title"), field("a:summary"), doi=doi(field("x:doi")),
                      publication_type="preprint",
                      published=field("a:published")[:10], publication_source="arXiv submitted", date_precision="day", journal="arXiv", preprint=True,
                      authors=[text(author.findtext("a:name", default="", namespaces=ATOM)) for author in entry.findall("a:author", ATOM)],
                      identifiers=["arxiv:" + identifier], url=safe_url(field("a:id")))


def pages(source, query, start, end, settings, client, resume=None, progress=None):
    size = source_page_size(source, settings)
    resume = resume or {}
    progress = progress if progress is not None else {}
    cursor = resume.get("next_cursor", "*")
    query_id = fingerprint([source, query])
    first_page = resume.get("next_page", 1)
    for page in range(first_page, first_page + settings["max_pages"]):
        if source == "crossref":
            mode = settings.get("crossref_date_mode", "created-date")
            params = {"filter": f"from-{mode}:{start},until-{mode}:{end}", "rows": size, "cursor": cursor,
                      "select": "DOI,title,abstract,author,published-online,published,published-print,issued,created,container-title,type,URL"}
            endpoint = "https://api.crossref.org/works"
            if query.startswith("journal:"):
                endpoint = "https://api.crossref.org/journals/" + query.split(":", 1)[1] + "/works"
            else:
                params[settings.get("crossref_query_field", "query.title")] = query
            if settings.get("contact_email"):
                params["mailto"] = settings["contact_email"]
            data, raw = client.get(endpoint + "?" + urllib.parse.urlencode(params), source, query_id, page)
            if not isinstance(data.get("message", {}).get("items"), list):
                raise ValueError("Crossref response is missing items")
            message = data["message"]
            items = message["items"]
            converted = [crossref_paper(item) for item in items]
            next_cursor = message.get("next-cursor")
            exhausted = not items or len(items) < size or page * size >= message.get("total-results", float("inf"))
            stalled = not exhausted and (not next_cursor or next_cursor == cursor)
            if stalled:
                raise ValueError("Pagination cursor did not advance; progress was not committed")
            cursor = next_cursor
            progress.update({"window_from": start, "window_until": end, "next_cursor": next_cursor, "next_page": page + 1, "total": message.get("total-results")})
        elif source == "openalex":
            params = {"search": query, "filter": f"from_publication_date:{start},to_publication_date:{end}", "per-page": size, "page": page, "sort": "publication_date:desc"}
            data, raw = client.get("https://api.openalex.org/works?" + urllib.parse.urlencode(params), source, query_id, page)
            if not isinstance(data.get("results"), list):
                raise ValueError("OpenAlex response is missing results")
            items = data["results"]
            converted = [openalex_paper(item) for item in items]
            exhausted = not items or len(items) < size or page * size >= data.get("meta", {}).get("count", float("inf"))
            stalled = False
        elif source == "scopus":
            offset = (page - 1) * size
            if offset >= 5000:
                raise ValueError("Scopus offset limit reached; this window needs a narrower query")
            count = min(size, 5000 - offset)
            terms = re.findall(r"[\w-]+", query)
            params = {"query": "TITLE-ABS-KEY(" + " AND ".join('"' + term + '"' for term in terms) + ")",
                      "date": start[:4] if start[:4] == end[:4] else start[:4] + "-" + end[:4], "sort": "-coverDate", "view": "STANDARD",
                      "start": offset, "count": count}
            data, raw = client.get("https://api.elsevier.com/content/search/scopus?" + urllib.parse.urlencode(params), source, query_id, page)
            result = data.get("search-results")
            if not isinstance(result, dict) or not str(result.get("opensearch:totalResults", "")).isdigit():
                raise ValueError("Scopus response is missing valid search results")
            total = int(result["opensearch:totalResults"])
            items = result.get("entry", [])
            if not isinstance(items, list):
                raise ValueError("Scopus response has invalid entries")
            errors = [item for item in items if "error" in item]
            if errors and not (total == 0 and len(items) == 1 and items[0].get("error") == "Result set was empty"):
                raise ValueError("Scopus returned an API error entry")
            if total == 0:
                if items and not errors:
                    raise ValueError("Scopus zero total contradicts returned records")
                items = []
            elif not items or any(not item.get("dc:title") for item in items):
                raise ValueError("Scopus nonempty result set contains missing records")
            parsed = [scopus_paper(item) for item in items]
            start_date, end_date = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
            converted = [paper for paper in parsed if not paper["published"] or
                         (publication_bounds(paper["published"])[0] <= end_date and publication_bounds(paper["published"])[1] >= start_date)]
            past_window = bool(parsed) and all(paper["published"] and publication_bounds(paper["published"])[1] < start_date for paper in parsed)
            exhausted = total == 0 or offset + len(items) >= total or past_window
            if not exhausted and len(items) != count:
                raise ValueError("Scopus returned a short nonterminal page; offset was not advanced")
            progress.update({"window_from": start, "window_until": end, "next_page": page + 1, "total": total})
            stalled = False
        else:
            terms = re.findall(r"[\w-]+", query)
            search = " AND ".join('all:"' + term + '"' for term in terms)
            search += f" AND submittedDate:[{start.replace('-', '')}0000 TO {end.replace('-', '')}2359]"
            params = {"search_query": search, "start": (page - 1) * size, "max_results": size, "sortBy": "submittedDate", "sortOrder": "descending"}
            data, raw = client.get("https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params), source, query_id, page, as_xml=True)
            entries = data.findall("a:entry", ATOM)
            if any("api/errors" in entry.findtext("a:id", default="", namespaces=ATOM) for entry in entries):
                raise ValueError("arXiv returned an API error feed")
            converted = [arxiv_paper(entry) for entry in entries]
            total = data.findtext("o:totalResults", default="", namespaces=ATOM)
            exhausted = not entries or len(entries) < size or (bool(total) and page * size >= int(total))
            stalled = False
        for paper in converted:
            paper["raw_files"] = [raw] if raw else []
        yield [paper for paper in converted if paper["title"]], exhausted
        if exhausted:
            return
        if stalled:
            raise ValueError("Pagination cursor did not advance; coverage is incomplete")


def collect(workspace, profile, client=None, today=None, only_source=None):
    workspace = Path(workspace).resolve()
    today = today or dt.datetime.now(UTC).date()
    stamp = dt.datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    settings = profile["collection"]
    started = time.monotonic()
    run_budget = settings.get("max_runtime_seconds", 600)
    if client is None:
        from credentials import Credentials
        client = HttpClient(settings, workspace / "raw" / stamp, Credentials(workspace, profile.get("credentials")))
    store = Store(workspace)
    report = {"id": stamp, "created": now(), "queries": [], "configured_sources": profile["sources"], "partial_run": bool(only_source), "protocol_version": 2}
    try:
        for plan in query_plans(profile):
            source, query = plan["source"], plan["query"]
            if only_source and source != only_source:
                continue
            end_date = today - dt.timedelta(days=settings.get("crossref_lag_days", 0) if source == "crossref" else 0)
            key, start = store.window(source, query, settings, end_date)
            saved = store.db.execute("SELECT payload FROM query_progress WHERE key=?", (key,)).fetchone()
            resume = json.loads(saved[0]) if saved else {}
            end = resume.get("window_until", end_date.isoformat())
            record = {**plan, "from": start, "until": end, "target_until": end_date.isoformat(), "caught_up": end >= end_date.isoformat(), "status": "capped", "received": 0, "pages": 0, "resumed_page": resume.get("next_page", 1), "error": ""}
            current_settings = dict(settings)
            if source == "crossref" and plan["kind"] == "topic":
                current_settings["max_pages"] = settings.get("crossref_discovery_max_pages", settings["max_pages"])
            progress = dict(resume)
            try:
                if time.monotonic() - started >= run_budget:
                    raise RuntimeError("Run time budget reached; this query remains pending")
                cooldown = store.db.execute("SELECT * FROM source_cooldowns WHERE source=?", (source,)).fetchone()
                if cooldown and dt.datetime.fromisoformat(cooldown["retry_at"]) > dt.datetime.now(UTC):
                    record["retry_at"] = cooldown["retry_at"]
                    raise RuntimeError("Source is waiting for its recorded retry time: " + cooldown["error"])
                for items, exhausted in pages(source, query, start, end, current_settings, client, resume, progress):
                    with store.db:
                        for paper in items:
                            store.upsert(paper)
                        if source in {"crossref", "scopus"}:
                            if exhausted:
                                store.db.execute("DELETE FROM query_progress WHERE key=?", (key,))
                            else:
                                store.db.execute("INSERT OR REPLACE INTO query_progress VALUES (?,?)", (key, json.dumps(progress)))
                    record["received"] += len(items)
                    record["pages"] += 1
                    if exhausted:
                        record["status"] = "complete"
                    elif time.monotonic() - started >= run_budget:
                        record["error"] = "Run time budget reached; progress retained"
                        break
                if record["status"] != "complete" and not record["error"]:
                    record["error"] = "Page budget reached; saved cursor/offset will resume this same window." if source in {"crossref", "scopus"} else "Page budget reached; checkpoint not advanced."
            except Exception as error:
                record["status"] = "failed"
                record["error"] = f"{type(error).__name__}: {error}"
                if isinstance(error, RateLimitError):
                    retry_at = (dt.datetime.now(UTC) + dt.timedelta(seconds=error.retry_after)).isoformat()
                    with store.db:
                        store.db.execute("INSERT OR REPLACE INTO source_cooldowns VALUES (?,?,?)", (source, retry_at, str(error)))
                    record["retry_at"] = retry_at
                elif source == "crossref" and resume and any(code in str(error) for code in ("HTTP 400", "HTTP 404", "HTTP 410")):
                    with store.db:
                        store.db.execute("DELETE FROM query_progress WHERE key=?", (key,))
                    record["error"] += "; cursor rejected, original window retained for restart"
            with store.db:
                store.checkpoint(key, source, query, start, end, record["status"], record["error"])
            report["queries"].append(record)
            write_json(workspace / "collection.json", report)
            print(json.dumps(record, ensure_ascii=False), flush=True)
        report["coverage_complete"] = not only_source and all(record["status"] == "complete" and record["caught_up"] for record in report["queries"])
        report["stored_papers"] = store.db.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        report["relevant_pending"] = len(store.candidates(profile))
        write_json(workspace / "collection.json", report)
        return report
    finally:
        store.close()


def diverse_selection(candidates, limit):
    remaining = list(candidates)
    selected = []
    topic_counts = {}
    while remaining and len(selected) < limit:
        def adjusted(paper):
            penalty = min(topic_counts.get(topic["id"], 0) for topic in paper["topics"]) * 8
            return paper["score"] - penalty
        winner = max(remaining, key=adjusted)
        selected.append(winner)
        remaining.remove(winner)
        for topic in winner["topics"]:
            topic_counts[topic["id"]] = topic_counts.get(topic["id"], 0) + 1
    return selected


def prepare(workspace, profile, include_archived=False, selected_keys=None, selection_note=""):
    store = Store(workspace)
    try:
        candidates = store.candidates(profile, include_archived)
        if selected_keys is None:
            selected = diverse_selection(candidates, profile["digest"]["max_papers"])
        else:
            lookup = {paper["key"]: paper for paper in candidates}
            if len(selected_keys) > profile["digest"]["max_papers"] or len(set(selected_keys)) != len(selected_keys) or any(key not in lookup for key in selected_keys):
                raise ValueError("Selected keys must be unique, eligible and within the digest limit")
            selected = [lookup[key] for key in selected_keys]
        coverage_path = Path(workspace) / "collection.json"
        coverage = load_json(coverage_path) if coverage_path.exists() else {"coverage_complete": False, "queries": []}
        packet = {"created": now(), "profile_hash": fingerprint(profile), "rereview": include_archived,
                  "language": profile.get("language", "zh-CN"), "selection_guidance": profile.get("selection_guidance", []),
                  "pending_count": len(candidates), "limit": profile["digest"]["max_papers"], "coverage": coverage,
                  "selection_note": selection_note, "review_pool": candidates[:max(12, profile["digest"]["max_papers"] * 4)], "papers": selected}
        path = Path(workspace) / "packets" / (fingerprint(packet)[:20] + ".json")
        write_json(path, packet)
        print(str(path.resolve()))
        return path
    finally:
        store.close()


def validate_analysis(packet, analysis):
    known = {paper["key"]: paper for paper in packet["papers"]}
    entries = analysis.get("papers", [])
    result = {}
    for entry in entries:
        key = entry.get("key")
        if key not in known or key in result:
            raise ValueError("Analysis contains an unknown or repeated paper key")
        if any(not isinstance(value, str) for field, value in entry.items() if field != "key"):
            raise ValueError("Analysis fields must be strings")
        if not (entry.get("title_local") or entry.get("title_zh", "")).strip() or not entry.get("relevance", "").strip():
            raise ValueError("Analysis needs a non-empty title_local and relevance")
        if entry.get("title_local") and entry.get("title_zh") and entry["title_local"] != entry["title_zh"]:
            raise ValueError("Conflicting localized titles")
        if not known[key].get("abstract") and any(entry.get(field, "").strip() for field in ("goal", "method", "result", "limitation")):
            raise ValueError("Title-only candidates cannot carry inferred goals, methods, results or limitations")
        result[key] = {field: entry[field].strip() for field in ("title_local", "title_zh", "relevance", "goal", "method", "result", "limitation") if entry.get(field, "").strip()}
    if set(result) != set(known):
        raise ValueError("Provide exactly one analysis entry for each selected paper")
    return result


def coverage_note(coverage):
    failures = [record for record in coverage.get("queries", []) if record.get("status") != "complete" or not record.get("caught_up", True)]
    if not coverage.get("queries"):
        return "本次没有已记录的在线检索，文献覆盖尚未验证。"
    if failures or coverage.get("partial_run"):
        sources = ", ".join(sorted({record["source"] for record in failures}))
        return f"检索覆盖不完整：{len(failures)} 个查询失败、达到分页上限或尚未追赶到当前窗口（{sources or '本次仅执行部分来源'}）；已保留进度供后续补抓。"
    return "本次已遍历所配置来源与检索式的返回页；仍受数据库收录、索引延迟及检索词覆盖限制。"


def markdown_report(report):
    if report.get("language") == "en":
        from reporting import english_report
        return english_report(report)
    lines = [f"# 个人文献日报 · {report['date']}", "", f"精选 {len(report['papers'])} 篇；{report['pending_after']} 篇相关候选仍待筛选。", "", coverage_note(report["coverage"]), ""]
    if not report["papers"]:
        lines += ["本次没有入选推送的文献。", ""]
    if report.get("selection_note"):
        lines += ["筛选说明：" + report["selection_note"], ""]
    for index, paper in enumerate(report["papers"], 1):
        analysis = paper.get("analysis", {})
        lines += [f"## {index}. {analysis.get('title_local') or analysis.get('title_zh') or paper['title']}", "", paper["title"], "",
                  f"- 主题：{'；'.join(topic['label'] for topic in paper['topics'])}",
                  f"- 来源：{', '.join(paper['sources'])}；{paper.get('journal') or '期刊未提供'}；{paper.get('published') or '日期未提供'}",
                  f"- 类型：{'预印本（未经期刊同行评审确认）' if paper.get('preprint') else '数据库所记录的发表文献'}",
                  f"- 作者：{'; '.join(paper.get('authors', [])) or '未提供'}{'（该来源仅提供首位作者）' if paper.get('authors_scope') == 'first-author' else ''}",
                  f"- DOI：{paper.get('doi') or '未提供'}",
                  f"- 日期依据：{paper.get('publication_source') or ', '.join(paper['sources'])}；{'仅提供年份，近期发表尚不能确认' if paper.get('date_precision') == 'year' else '仅提供月份，具体日未提供' if paper.get('date_precision') == 'month' else '数据库所记日期，未另行确认首次在线发表时间'}",
                  f"- 原文入口：{safe_url(paper.get('url')) or '未提供'}",
                  f"- 证据：{'已读取数据库摘要；未读取全文' if paper.get('abstract') else '仅标题与元数据；未读取摘要和全文'}", ""]
        if analysis:
            for field, label in (("relevance", "与研究的关联"), ("goal", "研究目标"), ("method", "方法"), ("result", "摘要报告的结果"), ("limitation", "摘要层面的边界")):
                if analysis.get(field):
                    lines += [f"**{label}：**{analysis[field]}", ""]
        else:
            lines += ["尚未添加 AI 解读，以下为数据库提供的摘要。", ""]
        if paper.get("abstract"):
            lines += ["**来源摘要：** " + paper["abstract"], ""]
    return "\n".join(lines)


def render_library(store, profile):
    from reading import decorate_library
    archived = {}
    for row in store.db.execute("SELECT payload FROM digests ORDER BY created"):
        report = json.loads(row[0])
        for paper in report["papers"]:
            archived[paper["key"]] = {**paper, "analysis": paper.get("analysis", {}), "digest_date": report["date"]}
    pending = [{**paper, "analysis": {}, "digest_date": ""} for paper in store.candidates(profile)]
    items = decorate_library(store, profile, list(archived.values()) + pending)
    items.sort(key=lambda paper: (paper.get("digest_date", ""), paper.get("published", "")), reverse=True)
    topics = {topic["id"]: {"id": topic["id"], "label": topic["label"]} for topic in profile["topics"]}
    for paper in items:
        for topic in paper["topics"]:
            topics.setdefault(topic["id"], {"id": topic["id"], "label": topic["label"]})
        if paper["taxonomy"]["primary_topic"] not in topics:
            topics[paper["taxonomy"]["primary_topic"]] = {"id": paper["taxonomy"]["primary_topic"], "label": "待分类"}
    data = {"updated": now(), "workspace": str(store.root), "topics": list(topics.values()), "schedule": profile.get("schedule", {}), "timezone": profile.get("timezone", "UTC"), "language": profile.get("language", "zh-CN"), "max_papers": profile["digest"]["max_papers"], "papers": items}
    directory = store.root / "library"
    write_json(directory / "library.json", data)
    template = (Path(__file__).resolve().parent.parent / "assets" / "library.html").read_text(encoding="utf-8")
    encoded = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace("&", "\\u0026")
    (directory / "index.html").write_text(template.replace("__LIBRARY_DATA__", encoded), encoding="utf-8")
    return directory / "index.html"


def archive(workspace, profile, packet_path, analysis_path=None):
    packet = load_json(packet_path)
    if packet["profile_hash"] != fingerprint(profile):
        raise ValueError("Profile changed since preparation; prepare again before archiving")
    if len(packet["papers"]) > profile["digest"]["max_papers"]:
        raise ValueError("Packet exceeds the configured digest limit")
    analyses = validate_analysis(packet, load_json(analysis_path)) if analysis_path else {}
    digest_id = fingerprint([packet, analyses])[:20]
    store = Store(workspace)
    try:
        existing = store.db.execute("SELECT path FROM digests WHERE id=?", (digest_id,)).fetchone()
        if existing:
            render_library(store, profile)
            return Path(existing[0])
        if not packet.get("rereview"):
            for paper in packet["papers"]:
                if store.db.execute("SELECT 1 FROM digest_items WHERE paper_key=?", (paper["key"],)).fetchone():
                    raise ValueError("A selected paper was already archived; prepare a fresh packet")
        from configuration import local_now
        date = local_now(profile).date().isoformat()
        directory = Path(workspace).resolve() / "reports" / f"{date}-{digest_id[:8]}"
        directory.mkdir(parents=True, exist_ok=True)
        report = {"id": digest_id, "date": date, "created": now(), "language": profile.get("language", "zh-CN"), "coverage": packet["coverage"],
                  "selection_note": packet.get("selection_note", ""),
                  "pending_after": max(0, packet["pending_count"] - len(packet["papers"])),
                  "papers": [{**paper, "analysis": analyses.get(paper["key"], {})} for paper in packet["papers"]]}
        report_path = directory / "digest.md"
        report_path.write_text(markdown_report(report), encoding="utf-8")
        write_json(directory / "digest.json", report)
        body = html.escape(report_path.read_text(encoding="utf-8"))
        language = "en" if profile.get("language") == "en" else "zh-CN"
        (directory / "digest.html").write_text('<!doctype html><html lang="' + language + '"><meta charset="utf-8"><title>Literature Digest</title><style>body{max-width:960px;margin:40px auto;padding:0 24px;color:#213547;font:17px/1.8 system-ui}pre{white-space:pre-wrap;font:inherit}</style><pre>' + body + '</pre></html>', encoding="utf-8")
        channel = profile["delivery"]["channel"]
        status = "archived" if channel == "local" or (not report["papers"] and not profile["delivery"].get("notify_empty")) else "pending"
        with store.db:
            store.db.execute("INSERT INTO digests VALUES (?,?,?,?)", (digest_id, report["created"], str(report_path), json.dumps(report, ensure_ascii=False)))
            for paper in packet["papers"]:
                if not store.get(paper["key"]):
                    raise ValueError("Packet references a paper absent from this workspace")
                store.db.execute("INSERT INTO digest_items VALUES (?,?)", (digest_id, paper["key"]))
            store.db.execute("INSERT INTO deliveries VALUES (?,?,?,?,?,?)", (digest_id, channel, status, "", "", now()))
        render_library(store, profile)
        return report_path
    finally:
        store.close()


def delivery(workspace, digest_id, status, receipt="", error=""):
    if status == "sent" and not receipt.strip():
        raise ValueError("A sent delivery needs a connector receipt or notification reference")
    store = Store(workspace)
    try:
        rows = store.db.execute("SELECT * FROM deliveries WHERE digest_id=?", (digest_id,)).fetchall()
        if len(rows) != 1:
            raise ValueError("Unknown or ambiguous digest delivery")
        if rows[0]["status"] == "sent" and status != "sent":
            raise ValueError("A successful delivery cannot be silently reset")
        with store.db:
            store.db.execute("UPDATE deliveries SET status=?,receipt=?,error=?,updated=? WHERE digest_id=?", (status, receipt, error, now(), digest_id))
    finally:
        store.close()


def status_report(workspace):
    from reading import reading_info
    store = Store(workspace)
    try:
        profile = profile_for(workspace)
        active = {query_key(plan["source"], plan["query"], profile["collection"]) for plan in query_plans(profile)}
        rows = [dict(row) for row in store.db.execute("SELECT key,source,query,pending_from,status,error FROM checkpoints")]
        incomplete = [row for row in rows if row["key"] in active and row["status"] != "complete"]
        reading_counts = {}
        reading_issues = []
        for row in store.db.execute("SELECT paper_key FROM reading_queue"):
            state = reading_info(store, row[0])["status"]
            reading_counts[state] = reading_counts.get(state, 0) + 1
            if state == "needs-review":
                reading_issues.append({"paper_key": row[0], "status": state})
        return {"stored_papers": store.db.execute("SELECT COUNT(*) FROM papers").fetchone()[0],
                "archived_digests": store.db.execute("SELECT COUNT(*) FROM digests").fetchone()[0],
                "pending_deliveries": [dict(row) for row in store.db.execute("SELECT * FROM deliveries WHERE status IN ('pending','failed','uncertain')")],
                "incomplete_queries": incomplete,
                "unqueried_plan_count": len(active - {row["key"] for row in rows}),
                "retired_checkpoint_count": sum(row["key"] not in active for row in rows),
                "resumable_queries": [json.loads(row["payload"]) for row in store.db.execute("SELECT * FROM query_progress") if row["key"] in active],
                "reading_queue": [{"status": state, "count": count} for state, count in reading_counts.items()],
                "reading_issues": reading_issues,
                "health_fingerprint": fingerprint(sorted([(item["source"], item["query"], item["status"], item["error"]) for item in incomplete] + [("reading", item["paper_key"], item["status"], "source missing or changed") for item in reading_issues]))}
    finally:
        store.close()


def execute(args, workspace, profile):
    if args.command in {"collect", "prepare", "archive"} and profile.get("preferences_confirmed") is False:
        raise ValueError("Complete the onboarding preferences with workspace.py configure --confirm before collecting")
    if args.command == "collect":
        result = collect(workspace, profile, only_source=args.source)
        print(json.dumps({"coverage_complete": result["coverage_complete"], "stored_papers": result["stored_papers"], "relevant_pending": result["relevant_pending"]}))
        return 0 if result["coverage_complete"] else 2
    if args.command == "prepare":
        prepare(workspace, profile, args.include_archived, [] if args.no_selection else args.keys, args.selection_note)
    elif args.command == "archive":
        print(archive(workspace, profile, args.packet, args.analysis))
    elif args.command == "delivery":
        delivery(workspace, args.digest, args.status, args.receipt, args.error)
    elif args.command == "status":
        print(json.dumps(status_report(workspace), ensure_ascii=False, indent=2))
    elif args.command == "reading":
        from reading import execute as reading_execute
        print(json.dumps(reading_execute(args, workspace, profile), ensure_ascii=False, indent=2))
    elif args.command == "library":
        store = Store(workspace)
        try:
            print(render_library(store, profile))
        finally:
            store.close()
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    collection = commands.add_parser("collect")
    collection.add_argument("--source", choices=SOURCES)
    preparation = commands.add_parser("prepare")
    preparation.add_argument("--include-archived", action="store_true")
    selection = preparation.add_mutually_exclusive_group()
    selection.add_argument("--keys", nargs="+")
    selection.add_argument("--no-selection", action="store_true")
    preparation.add_argument("--selection-note", default="")
    archiving = commands.add_parser("archive")
    archiving.add_argument("--packet", required=True)
    archiving.add_argument("--analysis")
    sending = commands.add_parser("delivery")
    sending.add_argument("--digest", required=True)
    sending.add_argument("--status", required=True, choices=["sent", "failed", "uncertain"])
    sending.add_argument("--receipt", default="")
    sending.add_argument("--error", default="")
    commands.add_parser("status")
    commands.add_parser("library")
    from reading import register_parser
    register_parser(commands)
    args = parser.parse_args()
    workspace = Path(args.workspace).resolve()
    profile = profile_for(workspace)
    if args.command == "status":
        return execute(args, workspace, profile)
    with WorkspaceLock(workspace):
        return execute(args, workspace, profile)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.modules.setdefault("digest", sys.modules[__name__])
    try:
        raise SystemExit(main())
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1)
