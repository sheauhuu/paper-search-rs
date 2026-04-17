from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from paper_search_mcp import __main__ as main_module
from paper_search_mcp.config import Config
from paper_search_mcp.models import Paper, WosSearchOptions
from paper_search_mcp.search.biorxiv import BioRxivSearcher
from paper_search_mcp.search.crossref import CrossRefSearcher
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

    def test_example_config_defines_medrxiv_platform(self) -> None:
        config = Config(str(ROOT / "config.example.yaml"))
        self.assertIn("medrxiv", config.platforms)
        self.assertFalse(config.is_platform_enabled("medrxiv"))


class BioRxivSearcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_filters_recent_records_by_free_text_query(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                (
                    "search:\n"
                    "  default_platforms:\n"
                    "    - biorxiv\n"
                    "platforms:\n"
                    "  biorxiv:\n"
                    "    enabled: true\n"
                    "    rate_limit_rps: 1.0\n"
                ),
                encoding="utf-8",
            )

            searcher = BioRxivSearcher(Config(str(config_path)))

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


if __name__ == "__main__":
    unittest.main()
