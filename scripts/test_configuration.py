"""Behavioral checks for reusable onboarding, preferences and credential backends."""
import argparse
import contextlib
import copy
import datetime as dt
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import configuration
import credentials
import digest
import workspace


TOPIC = {"id": "battery-recycling", "label": "电池回收", "queries": ["lithium battery recycling"],
         "require_all": [["battery", "batteries"], ["recycling", "recovery"]], "boost_terms": ["life cycle"]}


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parent.parent / ".test-tmp"
        parent.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=parent)
        self.root = Path(self.temporary.name) / "private-library"
        workspace.initialize(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def ready(self, **changes):
        workspace.configure(self.root, {"topics": [copy.deepcopy(TOPIC)], **changes}, confirm=True)
        return digest.profile_for(self.root)

    def paper(self, number=1, **changes):
        return digest.base_paper("Fixture", f"Battery recycling method {number}", "Battery recycling and material recovery.",
                                 publication_type="journal-article", published=dt.datetime.now(dt.timezone.utc).date().isoformat(),
                                 journal="Example Research", doi=f"10.1234/battery.{number}", **changes)

    def test_init_is_a_private_unconfirmed_draft_without_a_schedule(self):
        profile = digest.load_json(self.root / "profile.json")
        self.assertFalse(profile["preferences_confirmed"])
        self.assertEqual(profile["topics"], [])
        self.assertEqual(profile["previously_delivered_dois"], [])
        self.assertFalse(profile["schedule"]["enabled"])
        self.assertEqual(profile["credentials"], {})
        self.assertFalse(workspace.doctor(self.root)["configuration_ready"])
        with self.assertRaises(ValueError):
            workspace.initialize(self.root)

    def test_all_presets_are_optional_valid_drafts(self):
        for name in ("remote-sensing", "machine-learning"):
            root = self.root.parent / name
            workspace.initialize(root, name)
            profile = digest.load_json(root / "profile.json")
            configuration.validate_profile(profile)
            self.assertFalse(profile["preferences_confirmed"])
            self.assertFalse(profile["schedule"]["enabled"])
            with self.assertRaises(ValueError):
                digest.execute(argparse.Namespace(command="collect"), root, profile)

    def test_custom_field_and_count_change_actual_selection(self):
        profile = self.ready(digest={"max_papers": 5}, selection_guidance=["Prefer reusable experimental methods."])
        store = digest.Store(self.root)
        with store.db:
            for number in range(7):
                store.upsert(self.paper(number))
        store.close()
        with contextlib.redirect_stdout(io.StringIO()):
            packet = digest.load_json(digest.prepare(self.root, profile))
        self.assertEqual(len(packet["papers"]), 5)
        self.assertEqual(packet["selection_guidance"], ["Prefer reusable experimental methods."])

    def test_topic_edits_preserve_papers_and_configuration_history(self):
        self.ready()
        store = digest.Store(self.root)
        with store.db:
            key = store.upsert(self.paper())
        store.close()
        second = {"id": "catalysis", "label": "催化", "queries": ["catalysis recycling"], "require_all": [["catalysis"]]}
        workspace.edit_topic(self.root, "add", second)
        workspace.edit_topic(self.root, "update", {"label": "电池材料回收"}, TOPIC["id"])
        workspace.edit_topic(self.root, "remove", identifier="catalysis")
        profile = digest.profile_for(self.root)
        self.assertEqual(profile["topics"][0]["label"], "电池材料回收")
        store = digest.Store(self.root)
        self.assertIsNotNone(store.get(key))
        store.close()
        self.assertGreaterEqual(len(list((self.root / "config-history").glob("*.json"))), 4)

    def test_invalid_updates_do_not_replace_profile(self):
        self.ready()
        before = (self.root / "profile.json").read_bytes()
        for change in ({"digest": 5}, {"digest": {"max_papers": 0}}, {"digest": {"max_papers": True}},
                       {"schedule": {"frequency": "daily", "time": "25:00"}},
                       {"timezone": "Not/A_Timezone"}, {"journals": {"mode": "only", "names": []}},
                       {"previously_delivered_dois": []}):
            with self.assertRaises(ValueError):
                workspace.configure(self.root, change)
            self.assertEqual((self.root / "profile.json").read_bytes(), before)

    def test_weekly_schedule_is_intent_not_scheduler_registration(self):
        self.ready(timezone="Europe/Paris", schedule={"enabled": True, "frequency": "weekly", "time": "09:15", "weekdays": ["TU", "FR"]})
        result = workspace.doctor(self.root)
        self.assertEqual(result["schedule_intent"]["weekdays"], ["TU", "FR"])
        self.assertIn("not checked", result["scheduler_registration"])
        self.assertFalse((self.root / "automation.json").exists())
        with self.assertRaises(ValueError):
            workspace.configure(self.root, {"schedule": {"weekdays": ["Tuesday"]}})

    def test_timezone_uses_daylight_saving_and_local_calendar_date(self):
        profile = self.ready(timezone="America/New_York")
        winter = configuration.local_now(profile, dt.datetime(2026, 1, 1, 1, tzinfo=dt.timezone.utc))
        summer = configuration.local_now(profile, dt.datetime(2026, 7, 1, 12, tzinfo=dt.timezone.utc))
        self.assertEqual(winter.date().isoformat(), "2025-12-31")
        self.assertEqual(winter.utcoffset(), dt.timedelta(hours=-5))
        self.assertEqual(summer.utcoffset(), dt.timedelta(hours=-4))

    def test_journal_preference_and_whitelist_are_different(self):
        profile = self.ready(journals={"mode": "prefer", "names": ["Preferred Journal"]})
        ordinary = digest.assess(self.paper(), profile)
        self.assertIsNotNone(ordinary)
        preferred = self.paper()
        preferred["journal"] = "Preferred Journal"
        self.assertGreater(digest.assess(preferred, profile)["score"], ordinary["score"])
        profile["journals"]["mode"] = "only"
        self.assertIsNone(digest.assess(self.paper(), profile))
        self.assertIsNotNone(digest.assess(preferred, profile))
        profile["journals"]["exclude"] = ["Preferred Journal"]
        self.assertIsNone(digest.assess(preferred, profile))

    def test_preprints_are_an_explicit_separate_choice(self):
        self.ready(journals={"mode": "only", "names": ["Preferred Journal"]})
        workspace.configure(self.root, {"digest": {"include_preprints": True}})
        profile = digest.profile_for(self.root)
        preprint = self.paper(preprint=True)
        preprint["publication_type"] = "preprint"
        self.assertIsNotNone(digest.assess(preprint, profile))
        workspace.configure(self.root, {"digest": {"include_preprints": False}})
        self.assertIsNone(digest.assess(preprint, digest.profile_for(self.root)))

    def test_public_sources_can_be_configured_without_keys(self):
        self.ready()
        workspace.configure(self.root, {"sources": ["crossref", "arxiv"]})
        result = workspace.doctor(self.root)
        self.assertTrue(result["configuration_ready"])
        self.assertTrue(all(not source["key_required"] for source in result["sources"]))

    def test_english_analysis_is_archived_without_chinese_title_requirement(self):
        profile = self.ready(language="en")
        store = digest.Store(self.root)
        with store.db:
            key = store.upsert(self.paper())
        store.close()
        with contextlib.redirect_stdout(io.StringIO()):
            packet = digest.prepare(self.root, profile)
        analysis = self.root / "analysis.json"
        digest.write_json(analysis, {"papers": [{"key": key, "title_local": "Battery recycling", "relevance": "Relevant to material recovery."}]})
        path = digest.archive(self.root, profile, packet, analysis)
        content = path.read_text(encoding="utf-8")
        self.assertIn("Literature digest", content)
        self.assertIn("full text not read", content)
        self.assertIn("Relevant to material recovery.", content)
        self.assertIn('lang="en"', path.with_suffix(".html").read_text(encoding="utf-8"))

    def test_profile_rejects_plaintext_key_fields(self):
        profile = self.ready()
        profile["credentials"] = {"openalex": {"api_key": "fixture-not-a-real-key"}}
        with self.assertRaises(ValueError):
            configuration.validate_profile(profile)

    def test_system_keyring_access_is_scoped_to_workspace_and_provider(self):
        keyring = Mock()
        keyring.get_password.return_value = "fixture-protected-key"
        access = credentials.Credentials(self.root, {"openalex": {"backend": "keyring"}})
        with patch.object(credentials, "system_keyring", return_value=keyring):
            headers = access.headers("openalex", "https://api.openalex.org/works")
        self.assertEqual(headers["Authorization"], "Bearer fixture-protected-key")
        keyring.get_password.assert_called_once_with(credentials.keyring_service(self.root), "openalex")
        self.assertNotEqual(credentials.keyring_service(self.root), credentials.keyring_service(self.root.parent))
        self.assertEqual(access.redact("fixture-protected-key"), "[REDACTED]")

    def test_missing_key_does_not_fall_back_to_plaintext_or_anonymous_access(self):
        with self.assertRaises(RuntimeError):
            credentials.Credentials(self.root).headers("openalex", "https://api.openalex.org/works")
        access = credentials.Credentials(self.root, {"scopus": {"backend": "keyring"}})
        keyring = Mock()
        keyring.get_password.return_value = None
        with patch.object(credentials, "system_keyring", return_value=keyring), self.assertRaises(RuntimeError):
            access.headers("scopus", "https://api.elsevier.com/content/search/scopus")

    def test_noninteractive_key_import_is_refused(self):
        with patch.object(workspace.sys.stdin, "isatty", return_value=False), patch.object(workspace.getpass, "getpass") as prompt:
            with self.assertRaises(ValueError):
                workspace.import_key(self.root, "openalex")
            prompt.assert_not_called()


if __name__ == "__main__":
    unittest.main()
