from __future__ import annotations

import os
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from paper_search_mcp import __main__ as main_module
from paper_search_mcp import config as config_module
from paper_search_mcp.config import Config
from paper_search_mcp.models import Paper
from paper_search_mcp.tools import paper_search as paper_search_module


class _RecordingSearcher:
    calls: list[dict] = []
    results: list[Paper] = []

    def __init__(self, config: Config) -> None:
        self.config = config

    async def search(self, query: str, **kwargs: object) -> list[Paper]:
        type(self).calls.append({"query": query, "kwargs": kwargs})
        return [paper.model_copy(deep=True) for paper in type(self).results]


class FakeWosSearcher(_RecordingSearcher):
    calls: list[dict] = []
    results: list[Paper] = []


class FakeCrossrefSearcher(_RecordingSearcher):
    calls: list[dict] = []
    results: list[Paper] = []


class FakeFailingWosSearcher(_RecordingSearcher):
    calls: list[dict] = []
    results: list[Paper] = []

    async def search(self, query: str, **kwargs: object) -> list[Paper]:
        type(self).calls.append({"query": query, "kwargs": kwargs})
        self.last_diagnostics = {
            "platform": "webofscience",
            "enabled": True,
            "api_key_present": True,
            "query": query,
            "request_url": "https://api.clarivate.com/apis/wos-starter/v2/documents",
            "status_code": 401,
            "error": (
                "Web of Science request failed: 401 Unauthorized. "
                "Check WOS_API_KEY and WoS Starter API entitlement."
            ),
            "exception_type": "HTTPStatusError",
        }
        return []


def _make_config(
    *,
    default_platforms: list[str],
    debug_enabled: bool = False,
) -> Config:
    env = {
        "PAPER_SEARCH_DEFAULT_PLATFORMS": ",".join(default_platforms),
        "PAPER_SEARCH_PLATFORM_CROSSREF_MAX_RESULTS": "10",
        "PAPER_SEARCH_PLATFORM_WEBOFSCIENCE_MAX_RESULTS": "10",
        "WOS_API_KEY": "fake-key",
        "PAPER_SEARCH_JCR_ENABLED": "false",
        "PAPER_SEARCH_DEBUG": str(debug_enabled).lower(),
    }
    with patch.dict(os.environ, env, clear=True):
        with patch.object(config_module, "_find_legacy_config_files", return_value=[]):
            return Config()


async def _get_paper_search_tool():
    return next(
        tool
        for tool in await main_module.mcp._local_provider.list_tools()
        if tool.name == "paper_search"
    )


class PaperSearchIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        FakeWosSearcher.calls = []
        FakeWosSearcher.results = []
        FakeCrossrefSearcher.calls = []
        FakeCrossrefSearcher.results = []
        FakeFailingWosSearcher.calls = []
        FakeFailingWosSearcher.results = []

    async def test_tool_run_merges_duplicate_results_and_formats_output(self) -> None:
        FakeWosSearcher.results = [
            Paper(
                paper_id="WOS:1",
                title="Integrated Testing Paper",
                authors=["Alice Smith"],
                abstract="Web of Science record",
                doi="10.1000/integration",
                url="https://example.test/wos/1",
                source="webofscience",
                journal="Nature Methods",
                citations=3,
                year=2024,
            )
        ]
        FakeCrossrefSearcher.results = [
            Paper(
                paper_id="10.1000/integration",
                title="Integrated Testing Paper",
                authors=["Alice Smith"],
                abstract="Crossref record",
                doi="10.1000/integration",
                url="https://example.test/crossref/1",
                source="crossref",
                journal="Nature Methods",
                citations=10,
                year=2024,
            )
        ]

        config = _make_config(
            default_platforms=["webofscience", "crossref"],
        )
        tool = await _get_paper_search_tool()

        with ExitStack() as stack:
            stack.enter_context(patch.object(main_module, "_config", config))
            stack.enter_context(
                patch.object(
                    paper_search_module,
                    "SEARCHER_REGISTRY",
                    {
                        "webofscience": FakeWosSearcher,
                        "crossref": FakeCrossrefSearcher,
                    },
                )
            )
            stack.enter_context(
                patch.object(paper_search_module, "_get_jcr_index", return_value=None)
            )

            result = await tool.run(
                {
                    "query": "machine learning",
                    "platforms": ["webofscience", "crossref"],
                    "author": "Alice",
                    "journal": "nature",
                    "min_citations": 5,
                    "wos_options": {
                        "doi": "10.1000/integration",
                        "page": 2,
                    },
                }
            )

        text_blocks = [block.text for block in result.content if getattr(block, "type", None) == "text"]
        self.assertEqual(len(text_blocks), 1)
        self.assertIn("Source: webofscience", text_blocks[0])
        self.assertIn("DOI: 10.1000/integration", text_blocks[0])
        self.assertIn("Citations: 10", text_blocks[0])
        self.assertNotIn("Source: crossref", text_blocks[0])

        self.assertEqual(len(FakeWosSearcher.calls), 1)
        self.assertEqual(FakeWosSearcher.calls[0]["kwargs"]["doi"], "10.1000/integration")
        self.assertEqual(FakeWosSearcher.calls[0]["kwargs"]["page"], 2)
        self.assertNotIn("doi", FakeCrossrefSearcher.calls[0]["kwargs"])
        self.assertNotIn("page", FakeCrossrefSearcher.calls[0]["kwargs"])

    async def test_tool_run_uses_default_platforms_for_wos_options(self) -> None:
        FakeWosSearcher.results = [
            Paper(
                paper_id="WOS:2",
                title="Default Platform Paper",
                authors=["Bob Chen"],
                abstract="Only WoS is enabled by default",
                doi="10.1000/default",
                url="https://example.test/wos/2",
                source="webofscience",
                journal="Science",
                citations=8,
                year=2023,
            )
        ]

        config = _make_config(
            default_platforms=["webofscience"],
        )
        tool = await _get_paper_search_tool()

        with ExitStack() as stack:
            stack.enter_context(patch.object(main_module, "_config", config))
            stack.enter_context(
                patch.object(
                    paper_search_module,
                    "SEARCHER_REGISTRY",
                    {"webofscience": FakeWosSearcher},
                )
            )
            stack.enter_context(
                patch.object(paper_search_module, "_get_jcr_index", return_value=None)
            )

            result = await tool.run(
                {
                    "query": "transformer",
                    "wos_options": {
                        "document_type": "Review",
                        "page": 3,
                    },
                }
            )

        text_blocks = [block.text for block in result.content if getattr(block, "type", None) == "text"]
        self.assertEqual(len(text_blocks), 1)
        self.assertIn("Title: Default Platform Paper", text_blocks[0])
        self.assertEqual(len(FakeWosSearcher.calls), 1)
        self.assertEqual(FakeWosSearcher.calls[0]["kwargs"]["document_type"], "Review")
        self.assertEqual(FakeWosSearcher.calls[0]["kwargs"]["page"], 3)

    async def test_tool_run_rejects_wos_options_when_webofscience_not_targeted(self) -> None:
        config = _make_config(
            default_platforms=["crossref"],
        )
        tool = await _get_paper_search_tool()

        with patch.object(main_module, "_config", config):
            with self.assertRaisesRegex(ValueError, "webofscience"):
                await tool.run(
                    {
                        "query": "graph neural networks",
                        "platforms": ["crossref"],
                        "wos_options": {"doi": "10.1000/blocked"},
                    }
                )

    async def test_tool_run_surfaces_wos_auth_failures(self) -> None:
        config = _make_config(
            default_platforms=["webofscience"],
        )
        tool = await _get_paper_search_tool()

        with ExitStack() as stack:
            stack.enter_context(patch.object(main_module, "_config", config))
            stack.enter_context(
                patch.object(
                    paper_search_module,
                    "SEARCHER_REGISTRY",
                    {"webofscience": FakeFailingWosSearcher},
                )
            )
            stack.enter_context(
                patch.object(paper_search_module, "_get_jcr_index", return_value=None)
            )

            result = await tool.run(
                {
                    "query": "TS=(construction AND safety) AND PY=(2020-2025)",
                    "platforms": ["webofscience"],
                }
            )

        text_blocks = [block.text for block in result.content if getattr(block, "type", None) == "text"]
        self.assertEqual(len(text_blocks), 1)
        self.assertIn("401 Unauthorized", text_blocks[0])
        self.assertNotIn("No papers found.", text_blocks[0])

    async def test_tool_run_appends_debug_section_when_enabled(self) -> None:
        config = _make_config(
            default_platforms=["webofscience"],
            debug_enabled=True,
        )
        tool = await _get_paper_search_tool()

        with ExitStack() as stack:
            stack.enter_context(patch.object(main_module, "_config", config))
            stack.enter_context(
                patch.object(
                    paper_search_module,
                    "SEARCHER_REGISTRY",
                    {"webofscience": FakeFailingWosSearcher},
                )
            )
            stack.enter_context(
                patch.object(paper_search_module, "_get_jcr_index", return_value=None)
            )

            result = await tool.run(
                {
                    "query": "TS=(construction AND safety) AND PY=(2020-2025)",
                    "platforms": ["webofscience"],
                }
            )

        text_blocks = [block.text for block in result.content if getattr(block, "type", None) == "text"]
        self.assertEqual(len(text_blocks), 1)
        self.assertIn("[debug]", text_blocks[0])
        self.assertIn("platform=webofscience", text_blocks[0])
        self.assertIn("status=401", text_blocks[0])


if __name__ == "__main__":
    unittest.main()
