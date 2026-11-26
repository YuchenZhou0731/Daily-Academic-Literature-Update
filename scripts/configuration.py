"""Validate user preferences independently of collection and delivery."""
from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


SOURCES = {"crossref", "arxiv", "openalex", "scopus"}
WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


def timezone_for(profile):
    name = profile.get("timezone", "UTC")
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        raise ValueError("Unknown timezone or missing timezone data; install requirements.txt and use an IANA name") from None


def local_now(profile, instant=None):
    instant = instant or dt.datetime.now(dt.timezone.utc)
    if instant.tzinfo is None:
        raise ValueError("A timezone-aware instant is required")
    return instant.astimezone(timezone_for(profile))


def strings(value, label, allow_empty=True):
    if not isinstance(value, list) or (not value and not allow_empty) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{label} must be a list of nonempty strings")


def integer(value, label, low=1, high=100000):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{label} must be an integer between {low} and {high}")


def validate_profile(profile, allow_draft=False):
    if not isinstance(profile, dict):
        raise ValueError("A profile must be a JSON object")
    for field in ("digest", "collection", "delivery"):
        if not isinstance(profile.get(field), dict):
            raise ValueError(f"{field} must be a JSON object")
    for field in ("schedule", "journals", "credentials"):
        if field in profile and not isinstance(profile[field], dict):
            raise ValueError(f"{field} must be a JSON object")
    if not isinstance(profile.get("topics"), list):
        raise ValueError("topics must be a list")
    if any(not isinstance(topic, dict) for topic in profile["topics"]):
        raise ValueError("Each topic must be a JSON object")
    if not isinstance(profile.get("journal_watch", []), list):
        raise ValueError("journal_watch must be a list")
    if profile.get("schema_version") != 1:
        raise ValueError("Unsupported profile schema")
    if profile.get("language", "zh-CN") not in {"zh-CN", "en"}:
        raise ValueError("language must be zh-CN or en")
    timezone_for(profile)
    if not profile.get("topics") and not allow_draft:
        raise ValueError("Configure at least one research topic before collecting")
    seen = set()
    for topic in profile.get("topics", []):
        key = topic.get("id", "")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", key) or key in seen:
            raise ValueError("Topic IDs must be unique lowercase slugs")
        seen.add(key)
        if not isinstance(topic.get("label"), str) or not topic["label"].strip():
            raise ValueError("Each topic needs a display label")
        strings(topic.get("queries"), "Topic queries", False)
        groups = topic.get("require_all")
        if not isinstance(groups, list) or not groups:
            raise ValueError("Each topic needs require_all keyword groups")
        for group in groups:
            strings(group, "Keyword alternatives", False)
        for field in ("boost_terms", "exclude_title_terms"):
            strings(topic.get(field, []), field)
        for rule in topic.get("subtopic_rules", []):
            if not isinstance(rule.get("label"), str) or not rule["label"].strip():
                raise ValueError("A subtopic rule needs a label")
            strings(rule.get("terms"), "Subtopic terms", False)
    sources = profile.get("sources")
    strings(sources, "sources", False)
    if len(sources) != len(set(sources)) or not set(sources).issubset(SOURCES):
        raise ValueError("Use unique sources: crossref, arxiv, openalex, scopus")
    if profile.get("delivery", {}).get("channel") not in {"local", "codex", "connector", "gmail"}:
        raise ValueError("Delivery must be local, codex or connector")
    integer(profile["digest"]["max_papers"], "max_papers", 1, 100)
    for field in ("include_preprints", "include_title_only"):
        if field in profile["digest"] and not isinstance(profile["digest"][field], bool):
            raise ValueError(f"{field} must be boolean")
    strings(profile["digest"].get("publication_types", []), "publication_types")
    settings = profile["collection"]
    for field in ("initial_days", "overlap_days", "publication_age_days", "page_size", "max_pages", "timeout_seconds"):
        integer(settings[field], field)
    integer(settings["page_size"], "page_size", 1, 200)
    integer(settings.get("scopus_page_size", 10), "scopus_page_size", 1, 200)
    for field in ("max_runtime_seconds", "crossref_discovery_max_pages"):
        if field in settings:
            integer(settings[field], field)
    integer(settings.get("retries", 2), "retries", 0, 5)
    if settings.get("crossref_query_field", "query.title") not in {"query.title", "query.bibliographic"}:
        raise ValueError("Unsupported Crossref query field")
    if settings.get("crossref_date_mode", "created-date") not in {"created-date", "index-date"}:
        raise ValueError("Unsupported Crossref date mode")
    journals = profile.get("journals", {"mode": "prefer", "names": profile.get("preferred_journals", [])})
    if journals.get("mode") not in {"any", "prefer", "only"}:
        raise ValueError("journals.mode must be any, prefer or only")
    strings(journals.get("names", []), "Journal names", journals.get("mode") != "only")
    strings(journals.get("exclude", []), "Excluded journal names")
    for journal in profile.get("journal_watch", []):
        if not isinstance(journal, dict) or not re.fullmatch(r"\d{4}-\d{3}[\dX]", journal.get("issn", "")) or not journal.get("name"):
            raise ValueError("Journal watches need a name and valid ISSN")
    for field in ("excluded_terms", "previously_delivered_dois", "selection_guidance"):
        strings(profile.get(field, []), field)
    schedule = profile.get("schedule", {"enabled": False, "frequency": "manual"})
    if not isinstance(schedule.get("enabled", False), bool):
        raise ValueError("schedule.enabled must be boolean")
    if schedule.get("frequency") not in {"manual", "daily", "weekly"}:
        raise ValueError("Frequency must be manual, daily or weekly")
    if schedule.get("frequency") != "manual":
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", schedule.get("time", "")):
            raise ValueError("Use a 24-hour schedule time such as 08:00")
        if schedule["frequency"] == "weekly":
            days = schedule.get("weekdays", [])
            strings(days, "Scheduled weekdays", False)
            if len(days) != len(set(days)) or not set(days).issubset(WEEKDAYS):
                raise ValueError("Use unique weekday codes: MO TU WE TH FR SA SU")
    elif schedule.get("enabled"):
        raise ValueError("A manual schedule cannot be enabled")
    for source, config in profile.get("credentials", {}).items():
        if source not in {"openalex", "scopus"} or not isinstance(config, dict):
            raise ValueError("Credential configuration must name a supported provider")
        if set(config) - {"backend", "file"}:
            raise ValueError("Credential configuration stores references, never plaintext keys")
        if config.get("backend", "dpapi") not in {"dpapi", "keyring"}:
            raise ValueError("Use the dpapi or system keyring credential backend")
        if config.get("backend", "dpapi") == "dpapi" and not isinstance(config.get("file"), str):
            raise ValueError("A DPAPI credential needs a file reference")
    return profile
