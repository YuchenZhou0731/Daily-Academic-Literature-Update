"""Isolated behavioral tests. No external services or environment variables."""
import contextlib
import copy
import datetime as dt
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import digest
import reading


TODAY = dt.datetime.now(digest.UTC).date()
PROFILE = {
    "schema_version": 1, "language": "zh-CN", "timezone": "UTC",
    "delivery": {"channel": "codex", "notify_empty": False},
    "collection": {"initial_days": 14, "overlap_days": 14, "publication_age_days": 180, "page_size": 2, "max_pages": 3, "timeout_seconds": 5},
    "digest": {"max_papers": 3, "include_preprints": True, "include_title_only": True},
    "sources": ["crossref"], "preferred_journals": [], "excluded_terms": [],
    "topics": [{"id": "delta", "label": "测试主题甲", "queries": ["delta zeta"],
                "require_all": [["gamma", "alpha beta", "zeta"], ["delta", "epsilon"]], "boost_terms": []}]
}


def paper(number=1, abstract="A alpha beta model estimates delta output.", title=None, **changes):
    return {"title": title or f"Delta zeta gamma study {number}", "doi": f"10.1234/paper.{number}",
            "published": TODAY.isoformat(), "journal": "Example Research", "authors": ["A. Researcher"],
            "abstract": abstract, "abstract_source": "Crossref" if abstract else "", "sources": ["Crossref"],
            "preprint": False, "url": f"https://doi.org/10.1234/paper.{number}", "identifiers": [], "raw_files": [], **changes}


def crossref_item(number):
    return {"DOI": f"10.1234/paper.{number}", "title": [f"Delta zeta study {number}"],
            "published": {"date-parts": [[TODAY.year, TODAY.month, TODAY.day]]}, "abstract": "Delta alpha beta."}


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, source, query_id, page, as_xml=False):
        self.calls.append((source, page, url))
        response = self.responses[(source, page)]
        if isinstance(response, Exception):
            raise response
        return copy.deepcopy(response), ""


class DigestTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parent.parent / ".test-tmp"
        parent.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.root = Path(self.temp.name)
        self.profile = copy.deepcopy(PROFILE)
        digest.write_json(self.root / "profile.json", self.profile)

    def tearDown(self):
        self.temp.cleanup()

    def put(self, *records):
        store = digest.Store(self.root)
        try:
            with store.db:
                keys = [store.upsert(record) for record in records]
            return keys
        finally:
            store.close()

    def prepare(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return digest.prepare(self.root, self.profile)

    def run_collect(self, client):
        with contextlib.redirect_stdout(io.StringIO()):
            return digest.collect(self.root, self.profile, client=client, today=TODAY)

    def test_general_terms_is_not_excluded(self):
        self.assertIsNotNone(digest.assess(paper(title="Synthetic zeta gamma of delta attribute"), self.profile))
        self.assertIsNotNone(digest.assess(paper(title="Synthetic epsilon alpha beta", abstract=""), self.profile))

    def test_topic_requires_all_groups_but_accepts_synonyms(self):
        self.assertIsNone(digest.assess(paper(title="Delta bacteria", abstract="Microbiology of delta"), self.profile))
        self.assertIsNotNone(digest.assess(paper(title="Epsilon alpha-beta modelling", abstract=""), self.profile))

    def test_word_boundaries_avoid_short_term_substrings(self):
        self.assertFalse(digest.contains("progress in examples", "PROS"))
        self.assertTrue(digest.contains("X-token delta output", "x token"))

    def test_two_crossref_pages_are_stored_before_selection(self):
        client = FakeClient({("crossref", 1): {"message": {"items": [crossref_item(1), crossref_item(2)], "next-cursor": "second", "total-results": 3}},
                             ("crossref", 2): {"message": {"items": [crossref_item(3)], "total-results": 3}}})
        self.profile["digest"]["max_papers"] = 1
        result = self.run_collect(client)
        self.assertTrue(result["coverage_complete"])
        self.assertEqual(result["stored_papers"], 3)
        packet = digest.load_json(self.prepare())
        self.assertEqual(packet["pending_count"], 3)
        self.assertEqual(len(packet["papers"]), 1)
        self.assertIn("cursor=second", client.calls[1][2])

    def test_failed_query_retains_window_and_successful_source_progresses(self):
        self.profile["sources"] = ["crossref", "openalex"]
        client = FakeClient({("crossref", 1): RuntimeError("offline"), ("openalex", 1): {"results": [], "meta": {"count": 0}}})
        result = self.run_collect(client)
        self.assertFalse(result["coverage_complete"])
        store = digest.Store(self.root)
        try:
            rows = {row["source"]: row for row in store.db.execute("SELECT * FROM checkpoints")}
            self.assertIsNone(rows["crossref"]["watermark"])
            self.assertEqual(rows["openalex"]["watermark"], TODAY.isoformat())
            _, later_start = store.window("crossref", "delta zeta", self.profile["collection"], TODAY + dt.timedelta(days=25))
            self.assertEqual(later_start, (TODAY - dt.timedelta(days=14)).isoformat())
        finally:
            store.close()

    def test_partial_pages_survive_failure_and_retry_deduplicates(self):
        first = {"message": {"items": [crossref_item(1), crossref_item(2)], "next-cursor": "next", "total-results": 3}}
        self.run_collect(FakeClient({("crossref", 1): first, ("crossref", 2): RuntimeError("interrupted")}))
        self.assertEqual(digest.status_report(self.root)["stored_papers"], 2)
        result = self.run_collect(FakeClient({("crossref", 1): first, ("crossref", 2): {"message": {"items": [crossref_item(3)]}}}))
        self.assertEqual(result["stored_papers"], 3)
        self.assertTrue(result["coverage_complete"])
        self.assertEqual(digest.status_report(self.root)["incomplete_queries"], [])

    def test_page_cap_is_visible_and_does_not_advance(self):
        self.profile["collection"]["max_pages"] = 1
        client = FakeClient({("crossref", 1): {"message": {"items": [crossref_item(1), crossref_item(2)], "total-results": 10, "next-cursor": "next"}}})
        report = self.run_collect(client)
        self.assertEqual(report["queries"][0]["status"], "capped")
        self.assertEqual(report["stored_papers"], 2)
        self.assertTrue(digest.status_report(self.root)["incomplete_queries"])

    def test_invalid_api_response_is_a_failure_not_empty_success(self):
        result = self.run_collect(FakeClient({("crossref", 1): {"error": "rate limit"}}))
        self.assertEqual(result["queries"][0]["status"], "failed")

    def test_doi_normalization_and_abstract_enrichment(self):
        keys = self.put(paper(doi="HTTPS://DOI.ORG/10.1234/PAPER.1", abstract=""), paper(sources=["OpenAlex"], abstract_source="OpenAlex"))
        self.assertEqual(keys[0], keys[1])
        store = digest.Store(self.root)
        try:
            merged = store.get(keys[0])
            self.assertTrue(merged["abstract"])
            self.assertEqual(set(merged["sources"]), {"Crossref", "OpenAlex"})
        finally:
            store.close()

    def test_published_metadata_is_not_replaced_by_arxiv_version(self):
        key = self.put(paper(publication_type="journal-article", journal="Verified Journal"))[0]
        self.put(paper(publication_type="preprint", preprint=True, journal="arXiv", sources=["arXiv"], identifiers=["arxiv:2611.12345"]))
        store = digest.Store(self.root)
        try:
            result = store.get(key)
            self.assertEqual(result["journal"], "Verified Journal")
            self.assertFalse(result["preprint"])
            self.assertEqual(result["publication_type"], "journal-article")
        finally:
            store.close()

    def test_distinct_dois_with_identical_titles_are_not_merged(self):
        first, second = self.put(paper(1, title="Delta zeta"), paper(2, title="Delta zeta"))
        self.assertNotEqual(first, second)

    def test_title_only_record_can_gain_a_doi(self):
        keys = self.put(paper(doi=""), paper())
        self.assertEqual(keys[0], keys[1])

    def test_arxiv_version_ids_are_normalized(self):
        xml = f'<entry xmlns="http://www.w3.org/2005/Atom"><id>https://arxiv.org/abs/2611.12345v2</id><title>Epsilon alpha beta</title><summary>A model.</summary><published>{TODAY}T00:00:00Z</published></entry>'
        result = digest.arxiv_paper(digest.ET.fromstring(xml))
        self.assertEqual(result["identifiers"], ["arxiv:2611.12345"])
        self.assertTrue(result["preprint"])

    def test_draft_archive_and_delivery_are_separate_states(self):
        self.put(paper())
        packet_path = self.prepare()
        path = digest.archive(self.root, self.profile, packet_path)
        self.assertTrue(path.exists())
        state = digest.status_report(self.root)
        self.assertEqual(state["pending_deliveries"][0]["status"], "pending")
        digest_id = state["pending_deliveries"][0]["digest_id"]
        digest.delivery(self.root, digest_id, "failed", error="connector offline")
        self.assertEqual(digest.load_json(self.prepare())["papers"], [])
        with self.assertRaises(ValueError):
            digest.delivery(self.root, digest_id, "sent")
        digest.delivery(self.root, digest_id, "sent", receipt="synthetic-receipt")
        self.assertEqual(digest.status_report(self.root)["pending_deliveries"], [])

    def test_archive_is_idempotent(self):
        self.put(paper())
        packet = self.prepare()
        first = digest.archive(self.root, self.profile, packet)
        second = digest.archive(self.root, self.profile, packet)
        self.assertEqual(first, second)
        self.assertEqual(digest.status_report(self.root)["archived_digests"], 1)

    def test_title_only_analysis_cannot_invent_results(self):
        self.put(paper(abstract=""))
        packet = digest.load_json(self.prepare())
        key = packet["papers"][0]["key"]
        with self.assertRaisesRegex(ValueError, "Title-only"):
            digest.validate_analysis(packet, {"papers": [{"key": key, "title_zh": "测试标题", "relevance": "标题候选。", "result": "Improves accuracy by 15%."}]})
        self.assertTrue(digest.validate_analysis(packet, {"papers": [{"key": key, "title_zh": "测试标题", "relevance": "仅由标题判断可能相关。"}]}))

    def test_unknown_or_missing_analysis_keys_are_rejected(self):
        self.put(paper())
        packet = digest.load_json(self.prepare())
        with self.assertRaises(ValueError):
            digest.validate_analysis(packet, {"papers": []})
        with self.assertRaises(ValueError):
            digest.validate_analysis(packet, {"papers": [{"key": "unknown"}]})
        with self.assertRaisesRegex(ValueError, "relevance"):
            digest.validate_analysis(packet, {"papers": [{"key": packet["papers"][0]["key"]}]})

    def test_profile_change_invalidates_prepared_selection(self):
        self.put(paper())
        packet = self.prepare()
        self.profile["digest"]["max_papers"] = 1
        with self.assertRaisesRegex(ValueError, "Profile changed"):
            digest.archive(self.root, self.profile, packet)

    def test_failed_file_write_does_not_mark_candidates_archived(self):
        self.put(paper())
        packet = self.prepare()
        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                digest.archive(self.root, self.profile, packet)
        self.assertEqual(digest.status_report(self.root)["archived_digests"], 0)
        self.assertEqual(len(digest.load_json(self.prepare())["papers"]), 1)

    def test_future_and_old_publications_do_not_enter_digest(self):
        future = paper(published=(TODAY + dt.timedelta(days=2)).isoformat())
        old = paper(published=(TODAY - dt.timedelta(days=181)).isoformat())
        self.assertIsNone(digest.assess(future, self.profile))
        self.assertIsNone(digest.assess(old, self.profile))

    def test_partial_publication_dates_are_not_invented(self):
        self.assertEqual(digest.publication([2026]), "2026")
        self.assertEqual(digest.publication([2026, 11]), "2026-11")
        record = digest.crossref_paper({"DOI": "10.1/test", "title": ["Delta zeta"], "created": {"date-time": "2026-11-20T00:00:00Z"}})
        self.assertEqual(record["published"], "")
        self.assertEqual(record["created_at"], "2026-11-20T00:00:00Z")
        record = paper(published=f"{TODAY.year}-{TODAY.month:02d}")
        self.assertIsNotNone(digest.assess(record, self.profile))

    def test_legacy_delivered_dois_are_suppressed(self):
        self.profile["previously_delivered_dois"] = ["https://doi.org/10.1234/PAPER.1"]
        self.assertIsNone(digest.assess(paper(), self.profile))

    def test_publication_type_filter_keeps_preprints_separate(self):
        self.profile["digest"]["publication_types"] = ["journal-article", "review", "preprint"]
        self.assertIsNone(digest.assess(paper(publication_type="proceedings-article"), self.profile))
        self.assertIsNotNone(digest.assess(paper(publication_type="journal-article"), self.profile))
        self.assertIsNotNone(digest.assess(paper(publication_type="preprint", preprint=True), self.profile))

    def test_empty_digest_is_not_queued_as_a_paper_notification(self):
        packet = self.prepare()
        path = digest.archive(self.root, self.profile, packet)
        self.assertTrue(path.exists())
        self.assertEqual(digest.status_report(self.root)["pending_deliveries"], [])

    def test_html_data_cannot_close_script_and_unsafe_urls_are_omitted(self):
        self.put(paper(title="Delta zeta </script><script>alert(1)</script>", url="javascript:alert(1)"))
        path = digest.archive(self.root, self.profile, self.prepare())
        self.assertNotIn("javascript:", path.read_text(encoding="utf-8"))
        page = (self.root / "library" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("</script><script>alert(1)", page)
        self.assertIn("\\u003c/script>", page)

    def test_chinese_profile_and_results_round_trip(self):
        digest.write_json(self.root / "profile.json", self.profile)
        self.assertEqual(digest.profile_for(self.root)["topics"][0]["label"], "测试主题甲")

    def test_human_or_agent_can_select_fewer_papers_without_losing_queue(self):
        keys = self.put(paper(1), paper(2), paper(3), paper(4))
        with contextlib.redirect_stdout(io.StringIO()):
            packet = digest.prepare(self.root, self.profile, selected_keys=[keys[-1]], selection_note="Only this record meets the review criteria.")
        data = digest.load_json(packet)
        self.assertEqual(len(data["papers"]), 1)
        self.assertEqual(data["pending_count"], 4)
        self.assertEqual(len(data["review_pool"]), 4)
        digest.archive(self.root, self.profile, packet)
        self.assertEqual(digest.load_json(self.prepare())["pending_count"], 3)

    def test_invalid_manual_selection_is_rejected(self):
        self.put(paper())
        with self.assertRaises(ValueError):
            digest.prepare(self.root, self.profile, selected_keys=["unknown"])

    def test_rate_limit_defers_remaining_queries_without_more_requests(self):
        self.profile["topics"][0]["queries"].append("epsilon model")
        client = FakeClient({("crossref", 1): digest.RateLimitError("quota exceeded")})
        result = self.run_collect(client)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(len(result["queries"]), 2)
        self.assertTrue(all(record["status"] == "failed" for record in result["queries"]))

    def test_workspace_lock_prevents_overlap_and_releases(self):
        with digest.WorkspaceLock(self.root):
            with self.assertRaises(RuntimeError):
                with digest.WorkspaceLock(self.root):
                    pass
        self.assertFalse((self.root / "operation.lock").exists())

    def test_library_keeps_archived_snapshot_after_profile_or_age_changes(self):
        key = self.put(paper())[0]
        digest.archive(self.root, self.profile, self.prepare())
        changed = copy.deepcopy(self.profile)
        changed["topics"][0]["require_all"] = [["unrelated topic"]]
        self.put(paper(abstract="A different updated abstract."))
        store = digest.Store(self.root)
        try:
            digest.render_library(store, changed)
        finally:
            store.close()
        saved = digest.load_json(self.root / "library" / "library.json")
        self.assertEqual(len(saved["papers"]), 1)
        self.assertEqual(saved["papers"][0]["key"], key)
        self.assertEqual(saved["papers"][0]["abstract"], paper()["abstract"])

    def test_crossref_continues_saved_page_in_frozen_window(self):
        self.profile["collection"]["max_pages"] = 1
        first = FakeClient({("crossref", 1): {"message": {"items": [crossref_item(1), crossref_item(2)], "next-cursor": "continue", "total-results": 3}}})
        self.run_collect(first)
        second = FakeClient({("crossref", 2): {"message": {"items": [crossref_item(3)], "total-results": 3}}})
        with contextlib.redirect_stdout(io.StringIO()):
            result = digest.collect(self.root, self.profile, client=second, today=TODAY + dt.timedelta(days=1))
        self.assertEqual([call[1] for call in second.calls], [2])
        self.assertIn("cursor=continue", second.calls[0][2])
        self.assertEqual(result["queries"][0]["until"], TODAY.isoformat())
        self.assertFalse(result["queries"][0]["caught_up"])
        self.assertFalse(result["coverage_complete"])
        self.assertEqual(result["stored_papers"], 3)
        self.assertEqual(digest.status_report(self.root)["resumable_queries"], [])

    def test_cooldown_survives_a_new_process_run(self):
        self.run_collect(FakeClient({("crossref", 1): digest.RateLimitError("quota", 600)}))
        second = FakeClient({})
        result = self.run_collect(second)
        self.assertEqual(second.calls, [])
        self.assertEqual(result["queries"][0]["status"], "failed")
        self.assertIn("retry_at", result["queries"][0])

    def test_journal_watch_is_prioritized_and_does_not_filter_by_issue_date(self):
        self.profile["journal_watch"] = [{"name": "Example Journal", "issn": "1234-567X"}]
        client = FakeClient({("crossref", 1): {"message": {"items": []}}})
        self.run_collect(client)
        self.assertIn("/journals/1234-567X/works", client.calls[0][2])
        self.assertIn("from-created-date", client.calls[0][2])
        self.assertNotIn("from-pub-date", client.calls[0][2])

    def test_invalid_cursor_cannot_fake_forward_progress(self):
        result = self.run_collect(FakeClient({("crossref", 1): {"message": {"items": [crossref_item(1), crossref_item(2)], "next-cursor": "*", "total-results": 8}}}))
        self.assertEqual(result["queries"][0]["status"], "failed")
        self.assertEqual(digest.status_report(self.root)["resumable_queries"], [])

    def test_reading_state_requires_explicit_fulltext_review(self):
        key = self.put(paper())[0]
        source, card_path = self.make_reading_fixture(key)
        store = digest.Store(self.root)
        try:
            reading.add(store, key, "Read the model assumptions")
            self.assertEqual(reading.queue_entry(store, key)["status"], "queued")
            reading.attach(store, key, source)
            self.assertEqual(reading.queue_entry(store, key)["status"], "fulltext-ready")
            self.fill_source_hash(store, key, card_path)
            path = reading.review(store, key, card_path)
            self.assertTrue(path.exists())
            self.assertEqual(reading.queue_entry(store, key)["status"], "fulltext-read")
            reading.add(store, key)
            self.assertEqual(reading.queue_entry(store, key)["status"], "fulltext-read")
            self.assertEqual(reading.review(store, key, card_path), path)
            self.assertEqual(store.db.execute("SELECT COUNT(*) FROM reading_cards").fetchone()[0], 1)
        finally:
            store.close()

    def make_reading_fixture(self, key):
        source = self.root / "synthetic-fulltext.txt"
        source.write_text("SYNTHETIC ARTICLE\nMethods: We solve a three-dimensional alpha beta equation.\nResults: The model reproduces the synthetic reference curve.\n", encoding="utf-8")
        card_path = self.root / "reading-card-input.json"
        card = {"paper_key": key, "reading_scope": "fulltext", "source_sha256": "",
                **{field: "Synthetic test note; not a scientific result." for field in reading.FIELDS},
                "evidence": [{"field": "method", "locator": "Methods section", "support": "We solve a three-dimensional alpha beta equation."},
                             {"field": "result", "locator": "Results section", "support": "The model reproduces the synthetic reference curve."}]}
        digest.write_json(card_path, card)
        return source, card_path

    def fill_source_hash(self, store, key, card_path):
        card = digest.load_json(card_path)
        card["source_sha256"] = reading.queue_entry(store, key)["source"]["sha256"]
        digest.write_json(card_path, card)

    def test_file_presence_does_not_allow_missing_evidence_or_preview_scope(self):
        key = self.put(paper())[0]
        source, card_path = self.make_reading_fixture(key)
        store = digest.Store(self.root)
        try:
            reading.attach(store, key, source)
            self.fill_source_hash(store, key, card_path)
            valid = digest.load_json(card_path)
            for change in ({"reading_scope": "preview"}, {"evidence": []}, {"source_sha256": "wrong"}, {"method": ""}):
                digest.write_json(card_path, {**valid, **change})
                with self.assertRaises(ValueError):
                    reading.review(store, key, card_path)
            self.assertEqual(reading.queue_entry(store, key)["status"], "fulltext-ready")
        finally:
            store.close()

    def test_invented_text_excerpt_is_rejected(self):
        key = self.put(paper())[0]
        source, card_path = self.make_reading_fixture(key)
        store = digest.Store(self.root)
        try:
            reading.attach(store, key, source)
            self.fill_source_hash(store, key, card_path)
            card = digest.load_json(card_path)
            card["evidence"][1]["support"] = "Accuracy increased by 99 percent."
            digest.write_json(card_path, card)
            with self.assertRaisesRegex(ValueError, "excerpt"):
                reading.review(store, key, card_path)
        finally:
            store.close()

    def test_evidence_comparison_preserves_signs_case_and_units(self):
        self.assertNotEqual(reading.excerpt_text("bias -5 K"), reading.excerpt_text("bias +5 K"))
        self.assertNotEqual(reading.excerpt_text("5 mW"), reading.excerpt_text("5 MW"))
        self.assertNotEqual(reading.excerpt_text("5 m²"), reading.excerpt_text("5 m2"))
        self.assertEqual(reading.excerpt_text("bias\n -5   K"), reading.excerpt_text("bias -5 K"))

    def test_changed_fulltext_is_flagged_without_rewriting_old_notes(self):
        key = self.put(paper())[0]
        source, card_path = self.make_reading_fixture(key)
        store = digest.Store(self.root)
        try:
            reading.attach(store, key, source)
            self.fill_source_hash(store, key, card_path)
            note = reading.review(store, key, card_path)
            old_note = note.read_bytes()
            managed = store.root / reading.queue_entry(store, key)["source"]["path"]
            managed.write_text("Changed document", encoding="utf-8")
            self.assertEqual(reading.reading_info(store, key)["status"], "needs-review")
            status = digest.status_report(self.root)
            self.assertEqual(status["reading_queue"], [{"status": "needs-review", "count": 1}])
            self.assertEqual(status["reading_issues"][0]["paper_key"], key)
            with self.assertRaises(ValueError):
                reading.review(store, key, card_path)
            self.assertEqual(note.read_bytes(), old_note)
        finally:
            store.close()

    def test_new_source_version_preserves_old_card(self):
        key = self.put(paper())[0]
        source, card_path = self.make_reading_fixture(key)
        store = digest.Store(self.root)
        try:
            reading.attach(store, key, source)
            self.fill_source_hash(store, key, card_path)
            old_card = reading.review(store, key, card_path)
            source.write_text(source.read_text(encoding="utf-8") + "A revised appendix.\n", encoding="utf-8")
            reading.attach(store, key, source)
            self.assertEqual(reading.queue_entry(store, key)["status"], "fulltext-ready")
            self.assertTrue(old_card.exists())
            self.fill_source_hash(store, key, card_path)
            self.assertNotEqual(reading.review(store, key, card_path), old_card)
            self.assertEqual(store.db.execute("SELECT COUNT(*) FROM reading_cards").fetchone()[0], 2)
        finally:
            store.close()

    def test_old_queued_paper_and_manual_tags_remain_searchable(self):
        key = self.put(paper(published=(TODAY - dt.timedelta(days=200)).isoformat()))[0]
        store = digest.Store(self.root)
        try:
            reading.add(store, key)
            reading.tag(store, self.profile, key, "delta", ["模型假设", "误差传播"])
            digest.render_library(store, self.profile)
        finally:
            store.close()
        library = digest.load_json(self.root / "library/library.json")
        self.assertEqual(len(library["papers"]), 1)
        self.assertEqual(library["papers"][0]["taxonomy"]["subtopics"], ["模型假设", "误差传播"])
        self.assertEqual(library["papers"][0]["reading"]["status"], "queued")

    def test_invalid_pdf_attachment_is_rejected(self):
        key = self.put(paper())[0]
        path = self.root / "not-a-real-pdf.pdf"
        path.write_text("Not a PDF", encoding="utf-8")
        store = digest.Store(self.root)
        try:
            with self.assertRaisesRegex(ValueError, "PDF header"):
                reading.attach(store, key, path)
        finally:
            store.close()

    def test_topic_specific_title_exclusions_do_not_disable_other_topics(self):
        self.profile["topics"][0]["exclude_title_terms"] = ["image text retrieval"]
        self.assertIsNone(digest.assess(paper(title="Delta gamma image-text retrieval"), self.profile))
        self.assertIsNotNone(digest.assess(paper(title="Delta gamma physical parameter retrieval"), self.profile))


if __name__ == "__main__":
    unittest.main(verbosity=2)
