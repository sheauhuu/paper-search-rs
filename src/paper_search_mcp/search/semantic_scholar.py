"""Semantic Scholar searcher — ported from academic-mcp, converted to async httpx."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, List, Optional

from loguru import logger

from ..models import Paper
from .base import BaseSearcher


class SemanticScholarSearcher(BaseSearcher):
    platform_name = "semantic_scholar"
    base_url = "https://api.semanticscholar.org/graph/v1"

    FIELDS = "title,abstract,year,citationCount,authors,url,publicationDate,externalIds,fieldsOfStudy,openAccessPdf"

    async def search(
        self,
        query: str,
        max_results: Optional[int] = None,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        **kwargs: Any,
    ) -> List[Paper]:
        max_results = max_results or self.max_results
        params = {
            "query": query,
            "limit": max_results,
            "fields": self.FIELDS,
        }

        # Build year filter
        year_filter = self._build_year_filter(year_from, year_to)
        if year_filter:
            params["year"] = year_filter

        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        try:
            url = f"{self.base_url}/paper/search"
            data = await self._get_json(url, params=params, headers=headers)
            results = data.get("data", [])

            papers: List[Paper] = []
            for item in results:
                paper = self._parse_paper(item)
                if paper:
                    papers.append(paper)

            return papers[:max_results]

        except Exception as e:
            logger.error(f"[semantic_scholar] Search failed: {e}")
            return []

    def _build_year_filter(self, year_from: Optional[int], year_to: Optional[int]) -> str:
        if year_from and year_to:
            return f"{year_from}-{year_to}"
        if year_from:
            return f"{year_from}-"
        if year_to:
            return f"-{year_to}"
        return ""

    def _parse_paper(self, item: dict) -> Optional[Paper]:
        try:
            authors = [a.get("name", "") for a in item.get("authors", []) if a.get("name")]

            # Parse publication date
            pub_date_str = item.get("publicationDate", "")
            published_date = None
            if pub_date_str:
                try:
                    published_date = datetime.strptime(pub_date_str.strip(), "%Y-%m-%d")
                except ValueError:
                    pass

            # PDF URL
            pdf_url = None
            oap = item.get("openAccessPdf")
            if oap and isinstance(oap, dict):
                pdf_url = oap.get("url")
                if not pdf_url and oap.get("disclaimer"):
                    pdf_url = self._extract_url_from_disclaimer(oap["disclaimer"])

            # DOI
            doi = None
            ext_ids = item.get("externalIds")
            if ext_ids:
                doi = ext_ids.get("DOI")

            # Categories / fields of study
            categories = item.get("fieldsOfStudy") or []

            return Paper(
                paper_id=item.get("paperId", ""),
                title=item.get("title", ""),
                authors=authors,
                abstract=item.get("abstract") or "",
                url=item.get("url", ""),
                pdf_url=pdf_url,
                published_date=published_date,
                source="semantic_scholar",
                categories=categories if isinstance(categories, list) else [categories],
                doi=doi,
                citations=item.get("citationCount", 0),
                year=item.get("year"),
            )
        except Exception as e:
            logger.warning(f"[semantic_scholar] Parse error: {e}")
            return None

    @staticmethod
    def _extract_url_from_disclaimer(disclaimer: str) -> str:
        patterns = [
            r"https?://doi\.org/[^\s,)]+",
            r"https?://arxiv\.org/[^\s,)]+",
            r"https?://[^\s,)]*\.pdf",
            r"https?://[^\s,)]+",
        ]
        for pattern in patterns:
            matches = re.findall(pattern, disclaimer)
            if matches:
                url = matches[0]
                if "arxiv.org/abs/" in url:
                    url = url.replace("/abs/", "/pdf/")
                return url
        return ""
