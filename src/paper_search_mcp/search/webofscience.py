"""Web of Science searcher — Clarivate WoS Starter API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from loguru import logger

from ..models import Paper
from .base import BaseSearcher

# WoS field tags for query building
_WOS_FIELD_TAGS = frozenset({
    "TS=", "TI=", "AU=", "SO=", "PY=", "DO=", "IS=", "VL=",
    "PG=", "CS=", "DT=", "PMID=", "FPY=", "DOP=", "AI=",
    "UT=", "OG=", "SUR=",
})


class WebOfScienceSearcher(BaseSearcher):
    """Searcher for Web of Science via Clarivate Starter API.

    Supports v1/v2 API with automatic fallback on server errors.
    Requires an API key (X-ApiKey header).
    """

    platform_name = "webofscience"
    base_url = "https://api.clarivate.com/apis/wos-starter"

    def __init__(self, config: Any) -> None:
        super().__init__(config)
        self._preferred_version: str = "v2"
        self._api_version: str = self._preferred_version
        self._fallback_attempted: bool = False

    @property
    def _api_url(self) -> str:
        return f"{self.base_url}/{self._api_version}"

    def _switch_to_fallback(self) -> bool:
        """Switch API version on failure. Returns False if already tried."""
        if self._fallback_attempted:
            return False
        self._api_version = "v1" if self._api_version == "v2" else "v2"
        self._fallback_attempted = True
        logger.warning(f"[webofscience] Switching to API {self._api_version}")
        return True

    def _reset_fallback(self) -> None:
        """Reset to preferred version after a successful request."""
        if self._fallback_attempted and self._api_version != self._preferred_version:
            self._fallback_attempted = False
            self._api_version = self._preferred_version

    async def search(
        self,
        query: str,
        max_results: Optional[int] = None,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        author: Optional[str] = None,
        journal: Optional[str] = None,
        **kwargs: Any,
    ) -> List[Paper]:
        self.reset_diagnostics(
            query=query,
            request_url=f"{self._api_url}/documents",
        )
        if not self.api_key:
            message = "Web of Science request failed: WOS_API_KEY is not configured."
            self.update_diagnostics(error=message)
            logger.error(f"[webofscience] {message}")
            return []

        max_results = max_results or self.max_results
        wos_query = self._build_query(
            query,
            year_from=year_from,
            year_to=year_to,
            author=author,
            journal=journal,
            doi=kwargs.get("doi"),
            issn=kwargs.get("issn"),
            document_type=kwargs.get("document_type"),
        )
        self.update_diagnostics(query=wos_query)

        params: dict[str, Any] = {
            "q": wos_query,
            "db": kwargs.get("db", "WOS"),
            "limit": max(1, min(max_results, 50)),
            "page": max(1, int(kwargs.get("page", 1))),
            "sortField": self._map_sort_field(kwargs.get("sort_by", "relevance")),
        }

        if kwargs.get("edition"):
            params["edition"] = kwargs["edition"]
        if kwargs.get("detail"):
            params["detail"] = kwargs["detail"]
        if kwargs.get("publish_time_span"):
            params["publishTimeSpan"] = kwargs["publish_time_span"]
        if kwargs.get("modified_time_span"):
            params["modifiedTimeSpan"] = kwargs["modified_time_span"]
        if kwargs.get("tc_modified_time_span"):
            params["tcModifiedTimeSpan"] = kwargs["tc_modified_time_span"]

        headers = {
            "X-ApiKey": self.api_key,
            "Accept": "application/json",
        }

        try:
            data = await self._request_with_fallback(
                f"{self._api_url}/documents", params=params, headers=headers,
            )
            self._reset_fallback()
            papers = self._parse_response(data)
            self.update_diagnostics(
                request_url=f"{self._api_url}/documents",
                status_code=200,
                result_count=len(papers),
                error=None,
            )
            return papers

        except Exception as e:
            status_code = getattr(getattr(e, "response", None), "status_code", None)
            message = self._format_search_error(status_code, e)
            self.update_diagnostics(
                request_url=f"{self._api_url}/documents",
                status_code=status_code,
                error=message,
                exception_type=type(e).__name__,
            )
            logger.error(f"[webofscience] {message}")
            return []

    async def _request_with_fallback(self, url: str, **kwargs: Any) -> Any:
        """Make request with automatic v1/v2 fallback on server errors."""
        try:
            return await self._get_json(url, **kwargs)
        except Exception as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            should_fallback = (
                not status  # network error
                or status == 404
                or status >= 500
            )
            if should_fallback and self._switch_to_fallback():
                # Retry with new version URL
                new_url = f"{self._api_url}/documents"
                self.update_diagnostics(request_url=new_url)
                return await self._get_json(new_url, **kwargs)
            raise

    @staticmethod
    def _format_search_error(status_code: Optional[int], exc: Exception) -> str:
        if status_code == 401:
            return (
                "Web of Science request failed: 401 Unauthorized. "
                "Check WOS_API_KEY and WoS Starter API entitlement."
            )
        if status_code == 403:
            return (
                "Web of Science request failed: 403 Forbidden. "
                "Check WoS Starter API entitlement and account permissions."
            )
        if status_code == 404:
            return "Web of Science request failed: 404 Not Found."
        if status_code is not None:
            return f"Web of Science request failed: HTTP {status_code}."
        return f"Web of Science request failed: {exc}"

    def _build_query(
        self,
        query: str,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        author: Optional[str] = None,
        journal: Optional[str] = None,
        doi: Optional[str] = None,
        issn: Optional[str] = None,
        document_type: Optional[str] = None,
    ) -> str:
        """Build a WoS field-tag query string."""
        parts: list[str] = []

        # Main topic query
        if query and query.strip():
            has_tag = any(
                query.upper().startswith(tag) or f" {tag}" in query.upper()
                for tag in _WOS_FIELD_TAGS
            )
            if has_tag:
                parts.append(query)
            else:
                parts.append(f"TS=({query})")

        # Year range
        if year_from or year_to:
            start = year_from or 1900
            end = year_to or 2099
            parts.append(f"PY=({start}-{end})")

        # Author
        if author:
            parts.append(f"AU=({author})")

        # Journal / Source
        if journal:
            parts.append(f"SO=({journal})")

        if doi:
            parts.append(f'DO="{doi}"')

        if issn:
            parts.append(f"IS={issn}")

        if document_type:
            doc_types = [item.strip() for item in document_type.split(",") if item.strip()]
            if doc_types:
                joined = " OR ".join(f'"{item}"' for item in doc_types)
                parts.append(f"DT=({joined})")

        return " AND ".join(parts)

    def _map_sort_field(self, sort_by: str) -> str:
        mapping = {
            "relevance": "RS+D",
            "date": "PY+D",
            "citations": "TC+D",
        }
        return mapping.get(sort_by, "RS+D")

    def _parse_response(self, data: dict) -> List[Paper]:
        hits = data.get("hits", [])
        if not isinstance(hits, list):
            return []

        total = data.get("metadata", {}).get("total", 0)
        logger.debug(f"[webofscience] {len(hits)} hits / {total} total")

        papers: List[Paper] = []
        for record in hits:
            paper = self._parse_record(record)
            if paper:
                papers.append(paper)
        return papers

    @staticmethod
    def _format_pages(pages: Any) -> Optional[str]:
        """Normalize WoS page metadata for user-facing output."""
        if isinstance(pages, str):
            return pages or None
        if isinstance(pages, dict):
            if pages.get("range"):
                return str(pages["range"])
            begin = pages.get("begin")
            end = pages.get("end")
            if begin and end:
                return f"{begin}-{end}"
            if pages.get("count"):
                return str(pages["count"])
        return None

    def _parse_record(self, record: dict) -> Optional[Paper]:
        try:
            uid = record.get("uid", "")
            title = record.get("title", "") or "No title"

            # Authors
            authors: list[str] = []
            names = record.get("names", {})
            if isinstance(names, dict):
                author_list = names.get("authors", [])
                authors = [a.get("displayName", "") for a in author_list if a.get("displayName")]

            # Abstract
            abstract = record.get("abstract", "") or ""

            # Source / publication info
            source = record.get("source", {}) or {}
            journal = source.get("sourceTitle", "") or None
            year = source.get("publishYear")
            volume = source.get("volume") or None
            issue = source.get("issue") or None
            pages = source.get("pages") or None

            # DOI
            identifiers = record.get("identifiers", {}) or {}
            doi = identifiers.get("doi") or None

            # Citations
            citation_count = 0
            citations = record.get("citations", [])
            if citations and isinstance(citations, list):
                first = citations[0] if citations else {}
                citation_count = (
                    first.get("citingArticlesCount")
                    or first.get("count")
                    or 0
                )

            # Keywords
            keywords_data = record.get("keywords", {}) or {}
            keywords = keywords_data.get("authorKeywords", []) or []

            # Document types
            types = record.get("types", []) or []

            # URL
            wos_url = f"https://www.webofscience.com/wos/woscc/full-record/{uid}" if uid else ""

            published_date = None
            if isinstance(year, int):
                published_date = datetime(year, 1, 1)

            return Paper(
                paper_id=uid,
                title=title.strip(),
                authors=authors,
                abstract=abstract.strip(),
                doi=doi,
                published_date=published_date,
                url=wos_url,
                source="webofscience",
                categories=types,
                keywords=keywords,
                citations=int(citation_count),
                journal=journal,
                year=year,
                extra={
                    "volume": volume,
                    "issue": issue,
                    "pages": self._format_pages(pages),
                },
            )
        except Exception as e:
            logger.warning(f"[webofscience] Parse error: {e}")
            return None
