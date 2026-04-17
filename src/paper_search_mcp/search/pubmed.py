"""PubMed searcher — ported from academic-mcp, converted to async httpx."""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional
from xml.etree import ElementTree as ET

from loguru import logger

from ..models import Paper
from .base import BaseSearcher


class PubMedSearcher(BaseSearcher):
    platform_name = "pubmed"
    search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    fetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

    async def search(
        self,
        query: str,
        max_results: Optional[int] = None,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        **kwargs: Any,
    ) -> List[Paper]:
        max_results = max_results or self.max_results

        # Build query with year filter
        full_query = query
        if year_from or year_to:
            date_filter = f"{year_from or ''}:{year_to or ''}[pdat]"
            full_query = f"{query} AND {date_filter}"

        search_params = {
            "db": "pubmed",
            "term": full_query,
            "retmax": max_results,
            "retmode": "xml",
        }
        if self.api_key:
            search_params["api_key"] = self.api_key

        try:
            # Step 1: Search for IDs
            search_text = await self._get_text(self.search_url, params=search_params)
            root = ET.fromstring(search_text)
            ids = [id_elem.text for id_elem in root.findall(".//Id") if id_elem.text]

            if not ids:
                return []

            # Step 2: Fetch details
            fetch_params = {
                "db": "pubmed",
                "id": ",".join(ids),
                "retmode": "xml",
            }
            if self.api_key:
                fetch_params["api_key"] = self.api_key

            fetch_text = await self._get_text(self.fetch_url, params=fetch_params)
            fetch_root = ET.fromstring(fetch_text)

            papers: List[Paper] = []
            for article in fetch_root.findall(".//PubmedArticle"):
                paper = self._parse_article(article)
                if paper:
                    papers.append(paper)

            return papers[:max_results]

        except Exception as e:
            logger.error(f"[pubmed] Search failed: {e}")
            return []

    def _parse_article(self, article: ET.Element) -> Optional[Paper]:
        try:
            pmid_elem = article.find(".//PMID")
            pmid = pmid_elem.text if pmid_elem is not None else ""

            title_elem = article.find(".//ArticleTitle")
            title = title_elem.text if title_elem is not None else ""

            # Authors
            authors: List[str] = []
            for author in article.findall(".//Author"):
                last = author.find("LastName")
                initials = author.find("Initials")
                if last is not None and initials is not None:
                    authors.append(f"{last.text} {initials.text}")

            # Abstract
            abstract_elem = article.find(".//AbstractText")
            abstract = abstract_elem.text if abstract_elem is not None else ""

            # Date
            year_elem = article.find(".//PubDate/Year")
            published_date = None
            year = None
            if year_elem is not None and year_elem.text:
                year = int(year_elem.text)
                published_date = datetime(year, 1, 1)

            # DOI
            doi_elem = article.find('.//ELocationID[@EIdType="doi"]')
            doi = doi_elem.text if doi_elem is not None else None

            return Paper(
                paper_id=pmid,
                title=title,
                authors=authors,
                abstract=abstract or "",
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                source="pubmed",
                doi=doi,
                published_date=published_date,
                year=year,
            )
        except Exception as e:
            logger.warning(f"[pubmed] Parse error: {e}")
            return None
