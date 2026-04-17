"""bioRxiv / medRxiv searcher — ported from academic-mcp, converted to async httpx."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, List, Optional

from loguru import logger

from ..models import Paper
from .base import BaseSearcher


class BioRxivSearcher(BaseSearcher):
    """Searches both bioRxiv and medRxiv (configurable via platform_name)."""

    platform_name = "biorxiv"
    # Subclasses set their own base_url
    biorxiv_url = "https://api.biorxiv.org/details/biorxiv"
    medrxiv_url = "https://api.biorxiv.org/details/medrxiv"

    async def search(
        self,
        query: str,
        max_results: Optional[int] = None,
        days: int = 30,
        **kwargs: Any,
    ) -> List[Paper]:
        max_results = max_results or self.max_results
        base_url = self.biorxiv_url if self.platform_name == "biorxiv" else self.medrxiv_url
        source_name = self.platform_name
        site_url = "biorxiv.org" if source_name == "biorxiv" else "medrxiv.org"

        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        normalized_query = " ".join(query.lower().split())
        query_terms = re.findall(r"\w+", normalized_query)

        papers: List[Paper] = []
        cursor = 0

        while len(papers) < max_results:
            url = f"{base_url}/{start_date}/{end_date}/{cursor}"

            try:
                data = await self._get_json(url)
                collection = data.get("collection", [])

                for item in collection:
                    try:
                        date = datetime.strptime(item["date"], "%Y-%m-%d")
                        doi = item["doi"]
                        version = item.get("version", "1")

                        paper = Paper(
                            paper_id=doi,
                            title=item["title"],
                            authors=item["authors"].split("; "),
                            abstract=item["abstract"],
                            url=f"https://www.{site_url}/content/{doi}v{version}",
                            pdf_url=f"https://www.{site_url}/content/{doi}v{version}.full.pdf",
                            published_date=date,
                            source=source_name,
                            categories=[item["category"]],
                            doi=doi,
                            year=date.year,
                        )
                        if self._matches_query(paper, normalized_query, query_terms):
                            papers.append(paper)
                    except Exception as e:
                        logger.warning(f"[{source_name}] Parse error: {e}")
                        continue

                if len(collection) < 100:
                    break
                cursor += 100

            except Exception as e:
                logger.error(f"[{source_name}] Search failed: {e}")
                break

        return papers[:max_results]

    @staticmethod
    def _matches_query(paper: Paper, normalized_query: str, query_terms: List[str]) -> bool:
        if not normalized_query:
            return True

        haystack = " ".join(
            [
                paper.title,
                paper.abstract,
                " ".join(paper.authors),
                " ".join(paper.categories),
            ]
        ).lower()

        if normalized_query in haystack:
            return True
        return all(term in haystack for term in query_terms)


class MedRxivSearcher(BioRxivSearcher):
    """medRxiv searcher — reuses bioRxiv logic with different endpoint."""

    platform_name = "medrxiv"
