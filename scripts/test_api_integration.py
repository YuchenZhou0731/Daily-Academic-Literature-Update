"""Credential transport and Scopus collection checks, using isolated synthetic data."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import credentials
import digest
from test_digest import PROFILE, TODAY, FakeClient, paper


def scopus_item(number, date=None, display=None):
    return {"dc:title": f"Soil microwave remote sensing study {number}", "prism:doi": f"10.1234/paper.{number}",
            "prism:coverDate": date or TODAY.isoformat(), "prism:coverDisplayDate": display or "",
            "prism:aggregationType": "Journal", "subtype": "ar", "dc:creator": "First Author", "eid": f"2-s2.0-{number}"}


def scopus_response(items, total):
    return {"search-results": {"entry": items, "opensearch:totalResults": str(total)}}


class ApiTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parent.parent / ".test-tmp"
        parent.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=parent)
        self.root = Path(self.temporary.name)
        (self.root / ".credentials").mkdir()
        (self.root / ".credentials" / "test.dpapi").write_bytes(b"encrypted-fixture")
        self.config = {source: {"file": ".credentials/test.dpapi"} for source in ("openalex", "scopus")}
        self.profile = copy.deepcopy(PROFILE)
        self.profile["sources"] = ["scopus"]
        digest.write_json(self.root / "profile.json", self.profile)

    def tearDown(self):
        self.temporary.cleanup()

    def access(self):
        return credentials.Credentials(self.root, self.config)

    def collect(self, client):
        with contextlib.redirect_stdout(io.StringIO()):
            return digest.collect(self.root, self.profile, client=client, today=TODAY)

    def test_credentials_only_reach_exact_https_provider_host(self):
        access = self.access()
        with patch.object(credentials, "decrypt", return_value=json.dumps({"api_key": "test-secret", "label": "fixture"})) as decrypt:
            for url in ("http://api.openalex.org/works", "https://api.openalex.org.evil.example/works",
                        "https://api.openalex.org:444/works", "https://user@api.openalex.org/works"):
                with self.assertRaises(ValueError):
                    access.headers("openalex", url)
            decrypt.assert_not_called()
            self.assertEqual(access.headers("openalex", "https://api.openalex.org/works"), {"Authorization": "Bearer test-secret"})
            self.assertEqual(access.headers("scopus", "https://api.elsevier.com/content/search/scopus"), {"X-ELS-APIKey": "test-secret"})

    def test_failed_decryption_does_not_make_an_anonymous_request(self):
        client = digest.HttpClient(PROFILE["collection"], self.root / "raw", self.access())
        with patch.object(credentials, "decrypt", side_effect=OSError("test")), patch.object(client.opener, "open") as request:
            with self.assertRaisesRegex(RuntimeError, "owning Windows user"):
                client.get("https://api.openalex.org/works", "openalex", "test", 1)
            request.assert_not_called()
        with self.assertRaises(RuntimeError):
            credentials.Credentials(self.root).headers("scopus", "https://api.elsevier.com/content/search/scopus")

    def test_authenticated_redirect_is_blocked_before_forwarding(self):
        guard = credentials.AuthRedirectGuard()
        for header in ({"Authorization": "Bearer test"}, {"X-ELS-APIKey": "test"}):
            request = urllib.request.Request("https://api.openalex.org/works", headers=header)
            with self.assertRaisesRegex(RuntimeError, "redirect refused"):
                guard.redirect_request(request, None, 302, "Found", {}, "https://other.example/")

    def test_requests_are_signed_and_secrets_are_redacted_before_cache_and_parsing(self):
        client = digest.HttpClient(PROFILE["collection"], self.root / "raw", self.access())
        secret = "fixture/secret+123"
        calls = []
        def respond(request, **_):
            calls.append(request)
            if request.full_url.endswith("rate-limit"):
                data = {"api_key": secret, "rate_limit": {"daily_remaining_usd": 1, "daily_budget_usd": 1,
                        "endpoint_costs_usd": {"search": 0.01}, "resets_in_seconds": 3600}}
            else:
                data = {"results": [], "echo": secret, "encoded": urllib.parse.quote(secret, safe="")}
            return io.BytesIO(json.dumps(data).encode())
        with patch.object(credentials, "decrypt", return_value=json.dumps({"api_key": secret})), patch.object(client.opener, "open", side_effect=respond), patch.object(digest.time, "sleep"):
            result, _ = client.get("https://api.openalex.org/works?search=soil", "openalex", "fixture", 1)
            client.get("https://api.elsevier.com/content/search/scopus", "scopus", "fixture", 1)
        self.assertEqual(len(calls), 3)
        self.assertEqual(dict(calls[1].header_items())["Authorization"], "Bearer " + secret)
        self.assertEqual(dict(calls[2].header_items())["X-els-apikey"], secret)
        self.assertEqual(result["echo"], "[REDACTED]")
        for path in (self.root / "raw").rglob("*.json"):
            self.assertNotIn(secret, path.read_text())
            self.assertNotIn(urllib.parse.quote(secret, safe=""), path.read_text())

    def test_prepaid_balance_does_not_allow_spending_beyond_free_daily_allowance(self):
        client = digest.HttpClient(PROFILE["collection"], self.root / "raw", self.access())
        data = {"rate_limit": {"daily_remaining_usd": 0, "daily_budget_usd": 1, "prepaid_remaining_usd": 100,
                              "endpoint_costs_usd": {"search": 0.01}, "resets_in_seconds": 3600}}
        with patch.object(credentials, "decrypt", return_value=json.dumps({"api_key": "fixture"})), patch.object(client.opener, "open", return_value=io.BytesIO(json.dumps(data).encode())) as request:
            with self.assertRaises(digest.RateLimitError):
                client.get("https://api.openalex.org/works", "openalex", "test", 1)
            self.assertEqual(request.call_count, 1)

    def test_retry_reserves_a_second_search_cost(self):
        client = digest.HttpClient({**PROFILE["collection"], "retries": 1}, self.root / "raw", self.access())
        client.openalex_budget = {"remaining": digest.Decimal("0.01"), "cost": digest.Decimal("0.01"), "reset": 3600}
        error = urllib.error.HTTPError("https://api.openalex.org/works", 503, "Unavailable", {}, None)
        with patch.object(credentials, "decrypt", return_value=json.dumps({"api_key": "fixture"})), patch.object(client.opener, "open", side_effect=error) as request, patch.object(digest.time, "sleep"):
            with self.assertRaises(digest.RateLimitError):
                client.get("https://api.openalex.org/works", "openalex", "test", 1)
            self.assertEqual(request.call_count, 1)

    def test_scopus_date_precision_and_title_only_evidence(self):
        record = digest.scopus_paper(scopus_item(1, "2026-11-01", "November 2026"))
        self.assertEqual(record["published"], "2026-11")
        self.assertEqual(record["date_precision"], "month")
        self.assertEqual(record["abstract"], "")
        self.assertEqual(record["publication_type"], "journal-article")
        self.assertIn("not first-online", record["publication_source"])
        self.assertEqual(digest.scopus_paper(scopus_item(1, "2026-01-01", "2026"))["published"], "2026")

    def test_scopus_does_not_overwrite_existing_publication_date_or_authors(self):
        store = digest.Store(self.root)
        try:
            with store.db:
                original = paper(publication_source="Crossref published-online", published="2026-10-20", date_precision="day", authors=["A", "B"])
                key = store.upsert(original)
                store.upsert(digest.scopus_paper(scopus_item(1, "2026-11-01", "November 2026")))
            merged = store.get(key)
            self.assertEqual(merged["published"], "2026-10-20")
            self.assertEqual(merged["authors"], ["A", "B"])
            self.assertNotEqual(merged.get("authors_scope"), "first-author")
            self.assertEqual(merged["abstract"], original["abstract"])
        finally:
            store.close()

    def test_zero_results_and_api_errors_are_distinct(self):
        good = self.collect(FakeClient({("scopus", 1): scopus_response([{"error": "Result set was empty"}], 0)}))
        self.assertTrue(good["coverage_complete"])
        for response in ({"service-error": {"status": "invalid"}}, scopus_response([{"error": "Invalid API Key"}], 0), scopus_response([], 5)):
            bad = self.collect(FakeClient({("scopus", 1): response}))
            self.assertFalse(bad["coverage_complete"])
            self.assertEqual(bad["queries"][0]["status"], "failed")

    def test_scopus_capped_run_resumes_offset_with_frozen_window(self):
        self.profile["collection"]["max_pages"] = 1
        first = self.collect(FakeClient({("scopus", 1): scopus_response([scopus_item(1), scopus_item(2)], 3)}))
        self.assertEqual(first["queries"][0]["status"], "capped")
        client = FakeClient({("scopus", 2): scopus_response([scopus_item(3)], 3)})
        second = self.collect(client)
        self.assertTrue(second["coverage_complete"])
        self.assertEqual(second["stored_papers"], 3)
        self.assertIn("start=2", client.calls[0][2])
        self.assertEqual(second["queries"][0]["from"], first["queries"][0]["from"])

    def test_scopus_uses_year_search_then_filters_outside_daily_window(self):
        client = FakeClient({("scopus", 1): scopus_response([scopus_item(1, "2027-01-01"), scopus_item(2, "2026-11-15")], 2)})
        pages = list(digest.pages("scopus", "soil microwave", "2026-11-10", "2026-11-23", self.profile["collection"], client))
        self.assertEqual([p["doi"] for p in pages[0][0]], ["10.1234/paper.2"])
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(client.calls[0][2]).query)
        self.assertEqual(query["date"], ["2026"])
        self.assertEqual(query["view"], ["STANDARD"])
        list(digest.pages("scopus", "soil microwave", "2025-12-10", "2026-11-23", self.profile["collection"], client))
        self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlsplit(client.calls[-1][2]).query)["date"], ["2025-2026"])

    def test_scopus_offset_ceiling_does_not_claim_complete(self):
        client = FakeClient({})
        with self.assertRaisesRegex(ValueError, "offset limit"):
            list(digest.pages("scopus", "soil", "2026-01-01", "2026-11-23", self.profile["collection"], client, {"next_page": 2501}))
        self.assertEqual(client.calls, [])

    def test_scopus_page_size_does_not_reset_other_sources(self):
        original = {**self.profile["collection"], "page_size": 100}
        changed = {**original, "scopus_page_size": 5}
        self.assertEqual(digest.source_page_size("scopus", original), 10)
        self.assertEqual(digest.source_page_size("crossref", original), 100)
        for source in ("crossref", "openalex", "arxiv"):
            self.assertEqual(digest.query_key(source, "soil", original), digest.query_key(source, "soil", changed))
        self.assertNotEqual(digest.query_key("scopus", "soil", original), digest.query_key("scopus", "soil", changed))
        client = FakeClient({("scopus", 2): scopus_response([scopus_item(1)], 11)})
        list(digest.pages("scopus", "soil", "2026-01-01", "2026-11-25", original, client, {"next_page": 2}))
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(client.calls[0][2]).query)
        self.assertEqual(params["start"], ["10"])
        self.assertEqual(params["count"], ["10"])


if __name__ == "__main__":
    unittest.main()
