from __future__ import annotations

import unittest
from unittest.mock import patch

from src.query_catalog import generate_company_queries, load_web_query_catalog
from src.db import WebDocument
from src.searcher import evaluate_search_result
from src.storage import StorageManager
from src.tavily_client import TavilySearchClient


class WebQueryCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = load_web_query_catalog()
        self.company = {
            "company_id": "co_001",
            "company_name": "Example Components",
            "company_aliases": ["Example Co"],
            "location": "Sample City, Sample County",
            "county": "Sample County",
            "address": "123 Industrial Way, Sample City, GA 30000",
            "product_service": "thermal module",
            "ev_supply_chain_role": "battery thermal management",
            "facility_type": "Manufacturing Plant",
            "industry_group": "Automotive Components",
            "primary_oems": "Example OEM",
            "supplier_affiliation_type": "Tier supplier",
            "ev_relevant": "Yes",
        }

    def test_generates_catalog_queries_from_dynamic_fields(self) -> None:
        generated, skipped = generate_company_queries(self.company, self.catalog)
        query_text = "\n".join(query.query_text for query in generated)
        self.assertIn("Example Components", query_text)
        self.assertIn("Example OEM", query_text)
        self.assertLessEqual(len(generated), self.catalog["query_budgets"]["yes"]["default"])
        self.assertTrue(any(item.reason.startswith("budget_exceeded") for item in skipped))

    def test_missing_fields_skip_required_templates(self) -> None:
        company = {"company_name": "Sparse Company", "ev_relevant": "No"}
        generated, skipped = generate_company_queries(company, self.catalog)
        self.assertTrue(generated)
        self.assertTrue(any("missing:" in item.reason for item in skipped))
        self.assertFalse(any("  " in query.query_text for query in generated))

    def test_no_fixed_oem_from_catalog_when_primary_oems_missing(self) -> None:
        company = dict(self.company)
        company["primary_oems"] = ""
        generated, _ = generate_company_queries(company, self.catalog)
        self.assertFalse(any("Example OEM" in query.query_text for query in generated))
        self.assertFalse(any(query.family == "oem_relationship" for query in generated))

    def test_url_filter_requires_company_and_geography_for_facility(self) -> None:
        query = {"family": "facility_location", "query_text": "Example Components Sample City facility"}
        accepted = evaluate_search_result(
            "https://state.example/news",
            "Example Components opens Sample City facility",
            "Example Components facility in Sample County Georgia manufactures thermal module parts.",
            self.company,
            query,
            0.1,
        )
        rejected = evaluate_search_result(
            "https://state.example/news",
            "Another company opens facility",
            "A facility opened in another state.",
            self.company,
            query,
            0.1,
        )
        self.assertTrue(accepted["accepted"])
        self.assertFalse(rejected["accepted"])
        self.assertIn("company_entity_not_matched", rejected["rejection_reason"])

    def test_b2_object_key_uses_stable_identifiers_and_hash(self) -> None:
        manager = StorageManager(
            {
                "object_key_pattern": "{cloud_prefix}/{file_type}/{company_id}/{doc_id}_{domain_slug}_{content_hash12}.{ext}",
                "cloud_prefix": "georgia_ev/raw",
                "storage_backend": "backblaze_b2",
            }
        )
        key = manager.build_object_key(
            "DOC_001",
            "Example Components",
            "https://example.com/file.pdf",
            "pdf",
            company_id="co_001",
            content_hash="abcdef1234567890",
        )
        self.assertEqual(key, "georgia_ev/raw/pdf/co_001/DOC_001_example_com_abcdef123456.pdf")

    def test_web_document_metadata_model_contains_required_fields(self) -> None:
        fields = set(WebDocument.__table__.columns.keys())
        for field in {
            "source_id",
            "source_url",
            "final_url",
            "canonical_url",
            "query_used",
            "query_family",
            "query_stage",
            "source_type",
            "source_priority",
            "retrieved_at",
            "published_date",
            "content_hash",
            "b2_bucket",
            "b2_object_key",
            "b2_uri",
            "processing_status",
            "relevance_score",
            "confidence_score",
            "rejection_reason",
        }:
            self.assertIn(field, fields)

    def test_tavily_client_loads_multiple_keys_from_env(self) -> None:
        with patch.dict("os.environ", {"TAVILY_API_KEYS": "tvly-a, tvly-b\n,tvly-c", "TAVILY_API_KEY": "tvly-a"}):
            client = TavilySearchClient({"tavily_api_keys_env": "TAVILY_API_KEYS", "tavily_api_key_env": "TAVILY_API_KEY"})
        self.assertEqual([state.key for state in client.keys], ["tvly-a", "tvly-b", "tvly-c"])

    def test_tavily_client_reports_unavailable_without_keys(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            client = TavilySearchClient({"tavily_api_keys_env": "TAVILY_API_KEYS", "tavily_api_key_env": "TAVILY_API_KEY"})
        self.assertFalse(client.available())


if __name__ == "__main__":
    unittest.main()
