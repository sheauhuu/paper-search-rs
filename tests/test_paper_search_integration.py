from __future__ import annotations

import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from paper_search_mcp import __main__ as main_module
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


def _make_config(
    temp_dir: str,
    *,
    default_platforms: list[str],
    enabled_platforms: dict[str, bool],
) -> Config:
    def _yaml_list(values: list[str]) -> str:
        return "".join(f"    - {value}\n" for value in values)

    def _yaml_enabled(value: bool) -> str:
        return "true" if value else "false"

    config_path = Path(temp_dir) / "config.yaml"
    config_path.write_text(
        (
            "search:\n"
            "  default_platforms:\n"
            f"{_yaml_list(default_platforms)}"
            "  max_results_per_platform: 10\n"
            "  max_concurrent_searches: 5\n"
            "  timeout_seconds: 30\n"
            "platforms:\n"
            "  arxiv:\n"
            "    enabled: false\n"
            "  google_scholar:\n"
            "    enabled: false\n"
            "  semantic_scholar:\n"
            "    enabled: false\n"
            "  webofscience:\n"
            f"    enabled: {_yaml_enabled(enabled_platforms.get('webofscience', False))}\n"
            "    api_key: fake-key\n"
            "    max_results: 10\n"
            "  crossref:\n"
            f"    enabled: {_yaml_enabled(enabled_platforms.get('crossref', False))}\n"
            "    max_results: 10\n"
            "jcr:\n"
            "  enabled: false\n"
        ),
        encoding="utf-8",
    )
    return Config(str(config_path))


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

        with TemporaryDirectory() as temp_dir:
            config = _make_config(
                temp_dir,
                default_platforms=["webofscience", "crossref"],
                enabled_platforms={"webofscience": True, "crossref": True},
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

        with TemporaryDirectory() as temp_dir:
            config = _make_config(
                temp_dir,
                default_platforms=["webofscience"],
                enabled_platforms={"webofscience": True, "crossref": False},
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
        with TemporaryDirectory() as temp_dir:
            config = _make_config(
                temp_dir,
                default_platforms=["crossref"],
                enabled_platforms={"webofscience": False, "crossref": True},
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


if __name__ == "__main__":
    unittest.main()
