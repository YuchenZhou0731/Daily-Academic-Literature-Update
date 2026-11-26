"""Initialize and customize a private literature workspace."""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import getpass
import json
from pathlib import Path
import shutil
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from configuration import validate_profile
from digest import WorkspaceLock, load_json, write_json


SKILL = Path(__file__).resolve().parent.parent
CONFIGURABLE = {"language", "timezone", "schedule", "delivery", "collection", "digest", "journals", "sources",
                "topics", "excluded_terms", "journal_watch", "selection_guidance", "preferences_confirmed"}


def merge(existing, update):
    result = copy.deepcopy(existing)
    for key, value in update.items():
        result[key] = merge(result[key], value) if isinstance(result.get(key), dict) and isinstance(value, dict) else copy.deepcopy(value)
    return result


def initialize(workspace, preset="custom"):
    root = Path(workspace).resolve()
    if root == SKILL or (root / "profile.json").exists():
        raise ValueError("Choose a separate workspace without an existing profile; initialization never overwrites")
    profile = load_json(SKILL / "assets/profile.default.json")
    if preset != "custom":
        profile = merge(profile, load_json(SKILL / "assets/presets" / (preset + ".json")))
    profile["preferences_confirmed"] = False
    validate_profile(profile, allow_draft=True)
    root.mkdir(parents=True, exist_ok=True)
    with WorkspaceLock(root):
        write_json(root / "profile.json", profile)
        if not (root / ".gitignore").exists():
            (root / ".gitignore").write_text("*\n!.gitignore\n", encoding="utf-8")
    return root / "profile.json"


def commit_profile(root, profile):
    validate_profile(profile, allow_draft=not profile.get("preferences_confirmed", True))
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    history = root / "config-history" / (stamp + ".json")
    history.parent.mkdir(exist_ok=True)
    shutil.copy2(root / "profile.json", history)
    write_json(root / "profile.json", profile)
    return root / "profile.json"


def configure(workspace, update, confirm=False):
    root = Path(workspace).resolve()
    if not isinstance(update, dict) or set(update) - CONFIGURABLE:
        raise ValueError("Configuration patch contains unsupported fields; credentials and history use their own workflows")
    with WorkspaceLock(root):
        profile = merge(load_json(root / "profile.json"), update)
        digest_update = update.get("digest", {})
        if isinstance(digest_update, dict) and "include_preprints" in digest_update and "publication_types" not in digest_update and "publication_types" in profile["digest"]:
            types = profile["digest"].get("publication_types", [])
            if digest_update["include_preprints"] and "preprint" not in types:
                types.append("preprint")
            elif not digest_update["include_preprints"]:
                types = [kind for kind in types if kind != "preprint"]
            profile["digest"]["publication_types"] = types
        if confirm:
            profile["preferences_confirmed"] = True
        return commit_profile(root, profile)


def edit_topic(workspace, action, topic=None, identifier=None):
    root = Path(workspace).resolve()
    with WorkspaceLock(root):
        profile = load_json(root / "profile.json")
        topics = profile["topics"]
        if action == "add":
            if not isinstance(topic, dict) or topic.get("id") in {item["id"] for item in topics}:
                raise ValueError("A new topic needs a unique ID")
            topics.append(topic)
        else:
            existing = next((item for item in topics if item["id"] == identifier), None)
            if existing is None:
                raise ValueError("Topic ID not found")
            if action == "remove":
                topics.remove(existing)
            else:
                if not isinstance(topic, dict) or topic.get("id", identifier) != identifier:
                    raise ValueError("Keep the topic ID when updating its settings")
                topics[topics.index(existing)] = merge(existing, topic)
        return commit_profile(root, profile)


def doctor(workspace, check_credentials=False):
    from credentials import Credentials, HOSTS
    root = Path(workspace).resolve()
    profile = load_json(root / "profile.json")
    validate_profile(profile, allow_draft=True)
    sources = []
    access = Credentials(root, profile.get("credentials"))
    for source in profile["sources"]:
        item = {"source": source, "key_required": source in HOSTS, "key_configured": access.configured(source)}
        if check_credentials and source in HOSTS:
            try:
                access.headers(source, "https://" + HOSTS[source] + "/")
                item["key_readable"] = True
            except (RuntimeError, ValueError):
                item["key_readable"] = False
        sources.append(item)
    configured = bool(profile.get("topics")) and profile.get("preferences_confirmed", False)
    configured = configured and all(not item["key_required"] or item["key_configured"] for item in sources)
    return {"configuration_ready": configured, "workspace": str(root), "sources": sources,
            "schedule_intent": profile["schedule"], "timezone": profile["timezone"],
            "scheduler_registration": "not checked; profile settings do not register a task",
            "network_and_delivery": "not tested",
            "collector_argv": [sys.executable, "-I", "-B", str(SKILL / "scripts/digest.py"), "--workspace", str(root), "collect"]}


def import_key(workspace, source):
    from credentials import save_key
    if not sys.stdin.isatty():
        raise ValueError("Run credential import yourself in an interactive terminal; do not send a key in chat or command arguments")
    root = Path(workspace).resolve()
    with WorkspaceLock(root):
        profile = load_json(root / "profile.json")
        validate_profile(profile, allow_draft=True)
        value = getpass.getpass(source + " API key (hidden): ").strip()
        reference = save_key(root, source, value)
        profile.setdefault("credentials", {})[source] = reference
        if source not in profile["sources"]:
            profile["sources"].append(source)
        commit_profile(root, profile)
    return {"provider": source, "protected_storage": reference["backend"], "stored": True, "api_authentication_tested": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    initial = commands.add_parser("init")
    initial.add_argument("--preset", choices=["custom", "remote-sensing", "machine-learning"], default="custom")
    update = commands.add_parser("configure")
    update.add_argument("--patch", required=True)
    update.add_argument("--confirm", action="store_true")
    topics = commands.add_parser("topic").add_subparsers(dest="action", required=True)
    addition = topics.add_parser("add")
    addition.add_argument("--file", required=True)
    modification = topics.add_parser("update")
    modification.add_argument("--id", required=True)
    modification.add_argument("--file", required=True)
    removal = topics.add_parser("remove")
    removal.add_argument("--id", required=True)
    diagnosis = commands.add_parser("doctor")
    diagnosis.add_argument("--credentials", action="store_true")
    credential = commands.add_parser("credential")
    credential.add_argument("provider", choices=["openalex", "scopus"])
    args = parser.parse_args()
    if args.command == "init":
        result = str(initialize(args.workspace, args.preset))
    elif args.command == "configure":
        result = str(configure(args.workspace, load_json(args.patch), args.confirm))
    elif args.command == "topic":
        result = str(edit_topic(args.workspace, args.action, load_json(args.file) if hasattr(args, "file") else None, getattr(args, "id", None)))
    elif args.command == "doctor":
        result = doctor(args.workspace, args.credentials)
    else:
        result = import_key(args.workspace, args.provider)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1)
