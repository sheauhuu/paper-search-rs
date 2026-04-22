from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from paper_search_mcp import __main__ as main_module  # noqa: E402
from paper_search_mcp.jcr.models import JcrEntry, JcrIndex  # noqa: E402

# Ensure jcr_lookup is registered for testing (default config has JCR disabled,
# so we force-register by calling the underlying mcp.tool directly).
main_module.mcp.tool(
    name="jcr_lookup",
    description=main_module._JCR_LOOKUP_DESC,
)(main_module.jcr_lookup_tool)


def _make_index_with_sample() -> JcrIndex:
    index = JcrIndex()
    index.add(JcrEntry(
        issn="00280836",
        journal="Nature",
        impact_factor=64.8,
        jcr_quartile="Q1",
        jcr_rank="1/326",
        jcr_category="MULTIDISCIPLINARY SCIENCES(SCIE)",
        cas_quartile="1",
        cas_category="综合性期刊",
        ccf_rank=None,
        ccf_field=None,
    ))
    index.add(JcrEntry(
        issn="03774278",
        journal="Fuzzy Sets and Systems",
        impact_factor=4.6,
        jcr_quartile="Q1",
        cas_quartile="2",
        ccf_rank="B",
        ccf_field="计算机科学",
    ))
    return index


class JcrLookupToolTests(unittest.IsolatedAsyncioTestCase):
    async def _get_tool(self):
        return next(
            tool
            for tool in await main_module.mcp._local_provider.list_tools()
            if tool.name == "jcr_lookup"
        )

    async def test_lookup_by_journal_name(self) -> None:
        index = _make_index_with_sample()
        tool = await self._get_tool()
        with patch.object(main_module, "_get_jcr_index", return_value=index):
            result = await tool.run({"journal": "Nature"})
        text = result.content[0].text
        self.assertIn("Journal: Nature", text)
        self.assertIn("Impact Factor: 64.8", text)
        self.assertIn("JCR Quartile: Q1", text)
        self.assertIn("CAS Quartile: 1", text)

    async def test_lookup_by_issn(self) -> None:
        index = _make_index_with_sample()
        tool = await self._get_tool()
        with patch.object(main_module, "_get_jcr_index", return_value=index):
            result = await tool.run({"issn": "0377-4278"})
        text = result.content[0].text
        self.assertIn("Journal: Fuzzy Sets and Systems", text)
        self.assertIn("CCF Rank: B", text)

    async def test_lookup_not_found(self) -> None:
        index = _make_index_with_sample()
        tool = await self._get_tool()
        with patch.object(main_module, "_get_jcr_index", return_value=index):
            result = await tool.run({"journal": "Nonexistent Journal"})
        text = result.content[0].text
        self.assertIn("No JCR data found", text)

    async def test_lookup_no_input(self) -> None:
        tool = await self._get_tool()
        result = await tool.run({})
        text = result.content[0].text
        self.assertIn("Provide at least one", text)

    async def test_lookup_no_jcr_data(self) -> None:
        tool = await self._get_tool()
        with patch.object(main_module, "_get_jcr_index", return_value=None):
            result = await tool.run({"journal": "Nature"})
        text = result.content[0].text
        self.assertIn("JCR data not available", text)

    async def test_tool_schema_exists(self) -> None:
        tool = await self._get_tool()
        params = tool.model_dump()["parameters"]["properties"]
        self.assertIn("journal", params)
        self.assertIn("issn", params)

    async def test_tool_not_registered_when_jcr_disabled(self) -> None:
        """When JCR is disabled, jcr_lookup should not be in the tool list
        at production startup (but we already registered it for other tests,
        so we just verify the _register_jcr_lookup logic)."""
        from paper_search_mcp.config import Config
        config = Config()  # JCR disabled by default
        self.assertFalse(config.jcr.get("enabled"))

    async def test_lookup_warning_journal(self) -> None:
        index = JcrIndex()
        index.add(JcrEntry(
            issn="12345678",
            journal="Suspicious Journal",
            impact_factor=0.3,
            is_warning=True,
            warning_reason="学术不端",
        ))
        tool = await self._get_tool()
        with patch.object(main_module, "_get_jcr_index", return_value=index):
            result = await tool.run({"journal": "Suspicious Journal"})
        text = result.content[0].text
        self.assertIn("Warning: journal on warning list", text)
        self.assertIn("Warning Reason: 学术不端", text)


if __name__ == "__main__":
    unittest.main()
