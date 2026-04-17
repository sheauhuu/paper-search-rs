"""CrossRef searcher — ported from academic-mcp, converted to async httpx."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from ..models import Paper
from .base import BaseSearcher


class CrossRefSearcher(BaseSearcher):
    platform_name = "crossref"
    base_url = "https://api.crossref.org"
    _SORT_MAP = {
        "relevance": "score",
        "date": "published",
        "citations": "is-referenced-by-count",
    }

    async def search(
        self,
        query: str,
        max_results: Optional[int] = None,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        sort_by: str = "relevance",
        **kwargs: Any,
    ) -> List[Paper]:
        max_results = max_results or self.max_results
        params: Dict[str, Any] = {
            "query": query,
            "rows": min(max_results, 1000),
            "sort": self._map_sort(sort_by),
            "order": "desc",
        }

        # Polite pool
        mailto = self.config.platform_config("crossref").get("mailto", "")
        if mailto:
            params["mailto"] = mailto

        # Year filtering
        filters = []
        if year_from:
            filters.append(f"from-pub-date:{year_from}")
        if year_to:
            filters.append(f"until-pub-date:{year_to}")
        if filters:
            params["filter"] = ",".join(filters)

        headers = {"Accept": "application/json"}

        try:
            url = f"{self.base_url}/works"
            data = await self._get_json(url, params=params, headers=headers)
            items = data.get("message", {}).get("items", [])

            papers: List[Paper] = []
            for item in items:
                paper = self._parse_item(item)
                if paper:
                    papers.append(paper)

            return papers

        except Exception as e:
            logger.error(f"[crossref] Search failed: {e}")
            return []

    @classmethod
    def _map_sort(cls, sort_by: str) -> str:
        return cls._SORT_MAP.get(sort_by, "score")

    def _parse_item(self, item: dict) -> Optional[Paper]:
        try:
            doi = item.get("DOI", "")
            title = self._extract_title(item)
            authors = self._extract_authors(item)
            abstract = item.get("abstract", "")

            # Publication date
            published_date = (
                self._extract_date(item, "published")
                or self._extract_date(item, "issued")
                or self._extract_date(item, "created")
            )

            url = item.get("URL", f"https://doi.org/{doi}" if doi else "")
            pdf_url = self._extract_pdf_url(item)

            # Subjects / keywords
            subjects = item.get("subject", [])
            keywords = subjects if isinstance(subjects, list) else []

            container_title = self._extract_container_title(item)

            return Paper(
                paper_id=doi,
                title=title,
                authors=authors,
                abstract=abstract,
                doi=doi or None,
                published_date=published_date,
                pdf_url=pdf_url or None,
                url=url,
                source="crossref",
                categories=[item.get("type", "")],
                keywords=keywords,
                citations=int(item.get("is-referenced-by-count") or 0),
                journal=container_title or None,
                year=published_date.year if published_date else None,
                extra={
                    "publisher": item.get("publisher", ""),
                    "volume": item.get("volume", ""),
                    "issue": item.get("issue", ""),
                    "page": item.get("page", ""),
                },
            )
        except Exception as e:
            logger.warning(f"[crossref] Parse error: {e}")
            return None

    # --- Helper methods ---

    @staticmethod
    def _extract_title(item: dict) -> str:
        titles = item.get("title", [])
        if isinstance(titles, list) and titles:
            return titles[0]
        return str(titles) if titles else ""

    @staticmethod
    def _extract_authors(item: dict) -> List[str]:
        authors: List[str] = []
        for a in item.get("author", []):
            if isinstance(a, dict):
                given = a.get("given", "")
                family = a.get("family", "")
                if given and family:
                    authors.append(f"{given} {family}")
                elif family:
                    authors.append(family)
                elif given:
                    authors.append(given)
        return authors

    @staticmethod
    def _extract_date(item: dict, field: str) -> Optional[datetime]:
        date_info = item.get(field, {})
        if not date_info:
            return None
        parts_list = date_info.get("date-parts", [])
        if not parts_list or not parts_list[0]:
            return None
        parts = parts_list[0]
        try:
            year = parts[0] if len(parts) > 0 and parts[0] is not None else None
            month = parts[1] if len(parts) > 1 and parts[1] is not None else 1
            day = parts[2] if len(parts) > 2 and parts[2] is not None else 1
            if year is None:
                return None
            return datetime(year, month, day)
        except (ValueError, IndexError, TypeError):
            return None

    @staticmethod
    def _extract_container_title(item: dict) -> str:
        titles = item.get("container-title", [])
        if isinstance(titles, list) and titles:
            return titles[0]
        return str(titles) if titles else ""

    @staticmethod
    def _extract_pdf_url(item: dict) -> str:
        # Check resource primary
        resource = item.get("resource", {})
        if resource:
            primary = resource.get("primary", {})
            if primary and primary.get("URL", "").endswith(".pdf"):
                return primary["URL"]
        # Check links
        for link in item.get("link", []):
            if isinstance(link, dict) and "pdf" in link.get("content-type", "").lower():
                return link.get("URL", "")
        return ""
