"""Scopus searcher — ported from academic-mcp, converted to async httpx."""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from loguru import logger

from ..models import Paper
from .base import BaseSearcher


class ScopusSearcher(BaseSearcher):
    platform_name = "scopus"
    base_url = "https://api.elsevier.com/content/search/scopus"

    async def search(
        self,
        query: str,
        max_results: Optional[int] = None,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        **kwargs: Any,
    ) -> List[Paper]:
        if not self.api_key:
            logger.error("[scopus] API key required")
            return []

        max_results = max_results or self.max_results
        headers = {
            "X-ELS-APIKey": self.api_key,
            "Accept": "application/json",
        }

        # Build query with year filter
        full_query = query
        if year_from or year_to:
            full_query += f" AND PUBYEAR AFT {year_from or 1900} AND PUBYEAR BEF {year_to or 2099}"

        params = {
            "query": full_query,
            "count": max_results,
            "sort": "relevance",
        }

        try:
            data = await self._get_json(self.base_url, params=params, headers=headers)
            entries = data.get("search-results", {}).get("entry", [])

            papers: List[Paper] = []
            for entry in entries:
                paper = self._parse_entry(entry)
                if paper:
                    papers.append(paper)

            return papers

        except Exception as e:
            logger.error(f"[scopus] Search failed: {e}")
            return []

    def _parse_entry(self, entry: dict) -> Optional[Paper]:
        try:
            authors: List[str] = []
            author_name = entry.get("dc:creator", "")
            if author_name:
                authors.append(author_name)

            # Date
            pub_date_str = entry.get("prism:coverDate", "")
            published_date = None
            if pub_date_str:
                try:
                    published_date = datetime.strptime(pub_date_str, "%Y-%m-%d")
                except ValueError:
                    pass

            doi = entry.get("prism:doi", "") or None
            url = entry.get("prism:url", "") or (f"https://doi.org/{doi}" if doi else "")
            scopus_id = entry.get("dc:identifier", "").replace("SCOPUS_ID:", "")

            return Paper(
                paper_id=scopus_id,
                title=entry.get("dc:title", ""),
                authors=authors,
                abstract=entry.get("dc:description", "") or "",
                doi=doi,
                published_date=published_date,
                url=url,
                source="scopus",
                categories=[entry.get("prism:aggregationType", "")],
                citations=int(entry.get("citedby-count", 0)),
                journal=entry.get("prism:publicationName", "") or None,
                year=published_date.year if published_date else None,
                extra={
                    "volume": entry.get("prism:volume", ""),
                    "issue": entry.get("prism:issueIdentifier", ""),
                    "pages": entry.get("prism:pageRange", ""),
                },
            )
        except Exception as e:
            logger.warning(f"[scopus] Parse error: {e}")
            return None
