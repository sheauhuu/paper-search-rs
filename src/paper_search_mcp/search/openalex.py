"""OpenAlex searcher."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, List, Optional

from loguru import logger

from ..models import Paper
from .base import BaseSearcher


class OpenAlexSearcher(BaseSearcher):
    platform_name = "openalex"
    base_url = "https://api.openalex.org/works"

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
        params: dict[str, Any] = {
            "per-page": max(1, min(max_results, 200)),
        }

        doi = self._extract_doi(query)
        if doi:
            params["filter"] = f"doi:https://doi.org/{doi}"
        else:
            params["search"] = query
            filters = self._build_filters(year_from, year_to)
            if filters:
                params["filter"] = ",".join(filters)
            sort = self._map_sort(sort_by)
            if sort:
                params["sort"] = sort

        mailto = self.config.platform_config("openalex").get("mailto", "")
        if mailto:
            params["mailto"] = mailto
        if self.api_key:
            params["api_key"] = self.api_key

        try:
            data = await self._get_json(self.base_url, params=params)
            results = data.get("results", [])

            papers: List[Paper] = []
            for item in results:
                paper = self._parse_work(item)
                if paper:
                    papers.append(paper)

            return papers[:max_results]

        except Exception as e:
            logger.error(f"[openalex] Search failed: {e}")
            return []

    @staticmethod
    def _build_filters(year_from: Optional[int], year_to: Optional[int]) -> list[str]:
        filters: list[str] = []
        if year_from:
            filters.append(f"from_publication_date:{year_from}-01-01")
        if year_to:
            filters.append(f"to_publication_date:{year_to}-12-31")
        return filters

    @staticmethod
    def _map_sort(sort_by: str) -> str:
        if sort_by == "date":
            return "publication_date:desc"
        if sort_by == "citations":
            return "cited_by_count:desc"
        return ""

    @staticmethod
    def _extract_doi(query: str) -> Optional[str]:
        match = re.search(r"10\.\d{4,9}/[^\s\"<>]+", query, flags=re.IGNORECASE)
        if not match:
            return None
        return match.group(0).strip().rstrip(".,;)")

    @staticmethod
    def _strip_doi_url(value: str | None) -> Optional[str]:
        if not value:
            return None
        doi = value.strip()
        doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
        return doi or None

    @staticmethod
    def _abstract_from_inverted_index(index: Any) -> str:
        """Reconstruct OpenAlex abstract text from abstract_inverted_index."""
        if not isinstance(index, dict):
            return ""

        by_position: dict[int, str] = {}
        for word, positions in index.items():
            if not isinstance(word, str) or not isinstance(positions, list):
                continue
            for position in positions:
                if isinstance(position, int) and position >= 0:
                    by_position.setdefault(position, word)

        if not by_position:
            return ""
        return " ".join(word for _, word in sorted(by_position.items()))

    @staticmethod
    def _extract_authors(item: dict) -> List[str]:
        authors: List[str] = []
        for authorship in item.get("authorships", []):
            if not isinstance(authorship, dict):
                continue
            author = authorship.get("author") or {}
            if isinstance(author, dict) and author.get("display_name"):
                authors.append(author["display_name"])
        return authors

    @staticmethod
    def _extract_source(item: dict) -> Optional[str]:
        location = item.get("primary_location") or {}
        if not isinstance(location, dict):
            return None
        source = location.get("source") or {}
        if isinstance(source, dict):
            return source.get("display_name") or None
        return None

    @staticmethod
    def _extract_pdf_url(item: dict) -> Optional[str]:
        for location_key in ("best_oa_location", "primary_location"):
            location = item.get(location_key) or {}
            if isinstance(location, dict) and location.get("pdf_url"):
                return location["pdf_url"]
        return None

    @staticmethod
    def _parse_date(value: str | None) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d")
        except ValueError:
            return None

    def _parse_work(self, item: dict) -> Optional[Paper]:
        try:
            doi = self._strip_doi_url(item.get("doi"))
            abstract = self._abstract_from_inverted_index(item.get("abstract_inverted_index"))
            published_date = self._parse_date(item.get("publication_date"))
            source = self._extract_source(item)
            categories = [item.get("type", "")]
            primary_topic = item.get("primary_topic") or {}
            if isinstance(primary_topic, dict) and primary_topic.get("display_name"):
                categories.append(primary_topic["display_name"])

            return Paper(
                paper_id=item.get("id", ""),
                title=item.get("display_name", ""),
                authors=self._extract_authors(item),
                abstract=abstract,
                doi=doi,
                published_date=published_date,
                pdf_url=self._extract_pdf_url(item),
                url=item.get("id", ""),
                source="openalex",
                categories=[category for category in categories if category],
                citations=int(item.get("cited_by_count") or 0),
                journal=source,
                year=item.get("publication_year"),
                extra={
                    "openalex_id": item.get("id", ""),
                    "oa_status": (item.get("open_access") or {}).get("oa_status", ""),
                },
            )
        except Exception as e:
            logger.warning(f"[openalex] Parse error: {e}")
            return None
