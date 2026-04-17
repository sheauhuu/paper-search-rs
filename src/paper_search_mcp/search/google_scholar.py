"""Google Scholar searcher — ported from academic-mcp, converted to async httpx."""

from __future__ import annotations

import random
from datetime import datetime
from typing import Any, List, Optional

from bs4 import BeautifulSoup
from loguru import logger

from ..models import Paper
from .base import BaseSearcher


class GoogleScholarSearcher(BaseSearcher):
    platform_name = "google_scholar"
    base_url = "https://scholar.google.com/scholar"

    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    ]

    async def search(
        self,
        query: str,
        max_results: Optional[int] = None,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        **kwargs: Any,
    ) -> List[Paper]:
        max_results = max_results or self.max_results
        headers = {
            "User-Agent": random.choice(self.USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        }

        papers: List[Paper] = []
        start = 0
        per_page = min(10, max_results)

        while len(papers) < max_results:
            params: dict[str, Any] = {
                "q": query,
                "start": start,
                "hl": "en",
                "as_sdt": "0,5",
            }
            if year_from:
                params["as_ylo"] = year_from
            if year_to:
                params["as_yhi"] = year_to

            try:
                text = await self._get_text(self.base_url, params=params, headers=headers)
                soup = BeautifulSoup(text, "html.parser")
                results = soup.find_all("div", class_="gs_ri")

                if not results:
                    break

                for item in results:
                    if len(papers) >= max_results:
                        break
                    paper = self._parse_paper(item)
                    if paper:
                        papers.append(paper)

                start += per_page

            except Exception as e:
                logger.error(f"[google_scholar] Search failed: {e}")
                break

        return papers[:max_results]

    def _parse_paper(self, item) -> Optional[Paper]:
        try:
            title_elem = item.find("h3", class_="gs_rt")
            info_elem = item.find("div", class_="gs_a")
            abstract_elem = item.find("div", class_="gs_rs")

            if not title_elem or not info_elem:
                return None

            # Title and URL
            title = title_elem.get_text(strip=True).replace("[PDF]", "").replace("[HTML]", "")
            link = title_elem.find("a", href=True)
            url = link["href"] if link else ""

            # Authors and year
            info_text = info_elem.get_text()
            authors = [a.strip() for a in info_text.split("-")[0].split(",")]
            year = self._extract_year(info_text)

            return Paper(
                paper_id=f"gs_{hash(url)}",
                title=title,
                authors=authors,
                abstract=abstract_elem.get_text() if abstract_elem else "",
                url=url,
                source="google_scholar",
                year=year,
            )
        except Exception as e:
            logger.warning(f"[google_scholar] Parse error: {e}")
            return None

    @staticmethod
    def _extract_year(text: str) -> Optional[int]:
        for word in text.split():
            if word.isdigit() and 1900 <= int(word) <= datetime.now().year:
                return int(word)
        return None
