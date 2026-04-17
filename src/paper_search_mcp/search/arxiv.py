"""arXiv searcher — ported from academic-mcp, converted to async httpx."""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

import feedparser
from loguru import logger

from ..models import Paper
from .base import BaseSearcher


class ArxivSearcher(BaseSearcher):
    platform_name = "arxiv"
    base_url = "https://export.arxiv.org/api/query"

    _SORT_MAP = {
        "relevance": "relevance",
        "date": "submittedDate",
        "citations": "relevance",  # arXiv has no citation sort
    }

    async def search(
        self,
        query: str,
        max_results: Optional[int] = None,
        sort_by: str = "relevance",
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        **kwargs: Any,
    ) -> List[Paper]:
        max_results = max_results or self.max_results
        arxiv_sort = self._SORT_MAP.get(sort_by, "relevance")
        params = {
            "search_query": query,
            "max_results": max_results,
            "sortBy": arxiv_sort,
            "sortOrder": "descending",
        }

        try:
            text = await self._get_text(self.base_url, params=params)
            feed = feedparser.parse(text)
            papers: List[Paper] = []

            for entry in feed.entries:
                try:
                    authors = [a.name for a in entry.authors]
                    published = datetime.strptime(entry.published, "%Y-%m-%dT%H:%M:%SZ")
                    pdf_url = next(
                        (link.href for link in entry.links if link.type == "application/pdf"),
                        None,
                    )
                    paper_id = entry.id.split("/")[-1]
                    year = published.year

                    # Year filtering
                    if year_from and year < year_from:
                        continue
                    if year_to and year > year_to:
                        continue

                    papers.append(
                        Paper(
                            paper_id=paper_id,
                            title=entry.title,
                            authors=authors,
                            abstract=entry.summary,
                            url=entry.id,
                            pdf_url=pdf_url,
                            published_date=published,
                            source="arxiv",
                            categories=[tag.term for tag in entry.tags],
                            doi=entry.get("doi") or None,
                            year=year,
                        )
                    )
                except Exception as e:
                    logger.warning(f"[arxiv] Error parsing entry: {e}")
                    continue

            return papers

        except Exception as e:
            logger.error(f"[arxiv] Search failed: {e}")
            return []
