from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from paper_search_mcp import __main__ as main_module
from paper_search_mcp import config as config_module
from paper_search_mcp.config import Config
from paper_search_mcp.models import Paper, WosSearchOptions
from paper_search_mcp.search.biorxiv import BioRxivSearcher
from paper_search_mcp.search.crossref import CrossRefSearcher
from paper_search_mcp.search.webofscience import WebOfScienceSearcher
from paper_search_mcp.tools.paper_search import (
    _build_search_kwargs,
    _sort_papers,
    _validate_platform_specific_options,
)


class PaperSearchContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_schema_exposes_nested_wos_options(self) -> None:
        tool = next(
            tool
            for tool in await main_module.mcp._local_provider.list_tools()
            if tool.name == "paper_search"
        )

        parameters = tool.model_dump()["parameters"]
        self.assertIn("wos_options", parameters["properties"])
        self.assertIn("WosSearchOptions", parameters["$defs"])

        wos_schema = parameters["$defs"]["WosSearchOptions"]["properties"]
        self.assertIn("doi", wos_schema)
        self.assertIn("issn", wos_schema)
        self.assertIn("document_type", wos_schema)
        self.assertIn("page", wos_schema)

    def test_wos_options_require_webofscience(self) -> None:
        with self.assertRaisesRegex(ValueError, "webofscience"):
            _validate_platform_specific_options(
                ["arxiv", "crossref"],
                WosSearchOptions(doi="10.1000/example"),
            )

    def test_wos_options_only_forward_to_webofscience(self) -> None:
        wos_options = WosSearchOptions(
            doi="10.1000/example",
            issn="1234-5678",
            document_type="Article",
            page=2,
        )

        wos_kwargs = _build_search_kwargs(
            "webofscience",
            max_results=5,
            sort_by="date",
            year_from=2021,
            year_to=2024,
            author="smith",
            journal="Nature",
            wos_options=wos_options,
        )
        self.assertEqual(wos_kwargs["doi"], "10.1000/example")
        self.assertEqual(wos_kwargs["issn"], "1234-5678")
        self.assertEqual(wos_kwargs["document_type"], "Article")
        self.assertEqual(wos_kwargs["page"], 2)

        crossref_kwargs = _build_search_kwargs(
            "crossref",
            max_results=5,
            sort_by="date",
            wos_options=wos_options,
        )
        self.assertNotIn("doi", crossref_kwargs)
        self.assertNotIn("issn", crossref_kwargs)
        self.assertNotIn("document_type", crossref_kwargs)
        self.assertNotIn("page", crossref_kwargs)

    def test_sort_by_date_handles_mixed_datetime_and_year(self) -> None:
        papers = [
            Paper(
                paper_id="dated",
                title="Dated paper",
                authors=[],
                abstract="",
                published_date=datetime(2024, 5, 1),
                url="https://example.test/dated",
                source="crossref",
                year=2024,
            ),
            Paper(
                paper_id="year-only",
                title="Year only paper",
                authors=[],
                abstract="",
                url="https://example.test/year",
                source="google_scholar",
                year=2025,
            ),
        ]

        sorted_papers = _sort_papers(papers, "date")

        self.assertEqual([paper.paper_id for paper in sorted_papers], ["year-only", "dated"])

    def test_crossref_sort_mapping_matches_api_tokens(self) -> None:
        self.assertEqual(CrossRefSearcher._map_sort("relevance"), "score")
        self.assertEqual(CrossRefSearcher._map_sort("date"), "published")
        self.assertEqual(CrossRefSearcher._map_sort("citations"), "is-referenced-by-count")

    def test_env_config_defines_medrxiv_platform(self) -> None:
        with patch.object(config_module, "_find_legacy_config_files", return_value=[]):
            config = Config()
        self.assertIn("medrxiv", config.platforms)
        self.assertFalse(config.is_platform_enabled("medrxiv"))

    def test_env_overrides_apply_without_config_files(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PAPER_SEARCH_DEFAULT_PLATFORMS": "crossref,medrxiv",
                "PAPER_SEARCH_PLATFORM_MEDRXIV_ENABLED": "true",
                "PAPER_SEARCH_MAX_CONCURRENT_SEARCHES": "9",
                "PAPER_SEARCH_PLATFORM_CROSSREF_RATE_LIMIT_RPS": "4.5",
                "CROSSREF_MAILTO": "bot@example.com",
            },
            clear=True,
        ):
            with patch.object(config_module, "_find_legacy_config_files", return_value=[]):
                config = Config()

        self.assertEqual(config.default_platforms, ["crossref", "medrxiv"])
        self.assertTrue(config.is_platform_enabled("medrxiv"))
        self.assertEqual(config.max_concurrent_searches, 9)
        self.assertEqual(config.platform_config("crossref")["rate_limit_rps"], 4.5)
        self.assertEqual(config.platform_config("crossref")["mailto"], "bot@example.com")

    def test_config_path_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "File-based configuration is no longer supported"):
            Config("ignored.yaml")

    def test_legacy_config_yaml_in_cwd_is_rejected(self) -> None:
        with TemporaryDirectory() as temp_dir:
            legacy_path = Path(temp_dir) / "config.yaml"
            legacy_path.write_text("platforms:\\n  crossref:\\n    enabled: true\\n", encoding="utf-8")
            with patch.object(Path, "cwd", return_value=Path(temp_dir)):
                with self.assertRaisesRegex(ValueError, "Legacy config.yaml file detected"):
                    Config()

    def test_env_default_platforms_allow_empty_list(self) -> None:
        with patch.dict(
            os.environ,
            {"PAPER_SEARCH_DEFAULT_PLATFORMS": "  "},
            clear=True,
        ):
            with patch.object(config_module, "_find_legacy_config_files", return_value=[]):
                config = Config()

        self.assertEqual(config.default_platforms, [])

    def test_debug_env_enables_diagnostics(self) -> None:
        with patch.dict(
            os.environ,
            {"PAPER_SEARCH_DEBUG": "true"},
            clear=True,
        ):
            with patch.object(config_module, "_find_legacy_config_files", return_value=[]):
                config = Config()

        self.assertTrue(config.debug_enabled)

    def test_paper_to_text_formats_extra_labels(self) -> None:
        paper = Paper(
            paper_id="demo",
            title="Demo Paper",
            authors=[],
            abstract="",
            url="https://example.test/demo",
            source="crossref",
            extra={
                "page": "10-20",
                "publisher": "ACM",
                "raw_meta": {"count": 13},
            },
        )

        text = paper.to_text()

        self.assertIn("Page: 10-20", text)
        self.assertIn("Publisher: ACM", text)
        self.assertIn("Raw Meta: 13", text)

    def test_webofscience_record_omits_duplicate_uid_and_doctype(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PAPER_SEARCH_PLATFORM_WEBOFSCIENCE_ENABLED": "true",
                "WOS_API_KEY": "fake-key",
            },
            clear=True,
        ):
            with patch.object(config_module, "_find_legacy_config_files", return_value=[]):
                searcher = WebOfScienceSearcher(Config())

        paper = searcher._parse_record(
            {
                "uid": "WOS:123",
                "title": "Cleaner WoS output",
                "source": {
                    "sourceTitle": "Safety Science",
                    "publishYear": 2024,
                    "volume": "145",
                    "issue": "1",
                    "pages": {"range": "945-953", "count": 9},
                },
                "identifiers": {"doi": "10.1000/example"},
                "types": ["Article"],
            }
        )

        self.assertIsNotNone(paper)
        assert paper is not None
        self.assertEqual(paper.extra["pages"], "945-953")
        self.assertNotIn("uid", paper.extra)
        self.assertNotIn("doctype", paper.extra)

        text = paper.to_text()
        self.assertIn("Categories: Article", text)
        self.assertIn("Pages: 945-953", text)
        self.assertNotIn("uid:", text)
        self.assertNotIn("doctype:", text)

    async def test_webofscience_diagnostics_keep_fallback_request_url(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PAPER_SEARCH_PLATFORM_WEBOFSCIENCE_ENABLED": "true",
                "WOS_API_KEY": "fake-key",
            },
            clear=True,
        ):
            with patch.object(config_module, "_find_legacy_config_files", return_value=[]):
                searcher = WebOfScienceSearcher(Config())

        async def fake_request_with_fallback(url: str, **kwargs: object) -> dict:
            searcher._api_version = "v1"
            searcher._fallback_attempted = True
            searcher.update_diagnostics(request_url=f"{searcher._api_url}/documents")
            return {"hits": [], "metadata": {"total": 0}}

        searcher._request_with_fallback = fake_request_with_fallback  # type: ignore[method-assign]
        papers = await searcher.search("construction safety")

        self.assertEqual(papers, [])
        self.assertEqual(searcher._api_version, "v2")
        self.assertEqual(
            searcher.diagnostics_snapshot()["request_url"],
            "https://api.clarivate.com/apis/wos-starter/v1/documents",
        )


class BioRxivSearcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_filters_recent_records_by_free_text_query(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PAPER_SEARCH_DEFAULT_PLATFORMS": "biorxiv",
                "PAPER_SEARCH_PLATFORM_BIORXIV_ENABLED": "true",
                "PAPER_SEARCH_PLATFORM_BIORXIV_RATE_LIMIT_RPS": "1.0",
            },
            clear=True,
        ):
            with patch.object(config_module, "_find_legacy_config_files", return_value=[]):
                searcher = BioRxivSearcher(Config())

            async def fake_get_json(url: str):
                self.assertNotIn("?category=", url)
                return {
                    "collection": [
                        {
                            "title": "Diffusion models for protein design",
                            "authors": "Alice Smith; Bob Chen",
                            "abstract": "A diffusion model for proteins.",
                            "category": "bioinformatics",
                            "date": "2026-04-01",
                            "doi": "10.1101/2026.04.01.000001",
                            "version": "1",
                        },
                        {
                            "title": "Single-cell atlas of mouse brain",
                            "authors": "Carol Lee",
                            "abstract": "Transcriptomics study.",
                            "category": "neuroscience",
                            "date": "2026-04-02",
                            "doi": "10.1101/2026.04.02.000002",
                            "version": "1",
                        },
                    ]
                }

            searcher._get_json = fake_get_json  # type: ignore[method-assign]
            papers = await searcher.search("diffusion model", max_results=5)

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].doi, "10.1101/2026.04.01.000001")


class ReadmeContractTests(unittest.TestCase):
    def test_readme_mentions_nested_wos_options(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("wos_options", readme)
        self.assertIn("document_type", readme)
        self.assertIn("mcpServers", readme)
        self.assertIn("\"env\":", readme)


if __name__ == "__main__":
    unittest.main()
