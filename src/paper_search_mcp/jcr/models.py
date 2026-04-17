"""JCR data models — journal citation metrics from ShowJCR."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class JcrEntry:
    """Merged journal metrics from JCR + 中科院分区 + CCF + 预警."""

    issn: str = ""
    journal: str = ""
    impact_factor: Optional[float] = None
    jcr_quartile: Optional[str] = None      # Q1/Q2/Q3/Q4
    jcr_rank: Optional[str] = None          # "1/326"
    jcr_category: Optional[str] = None      # "ONCOLOGY(SCIE)"
    cas_quartile: Optional[str] = None      # 中科院大类分区: "1"/"2"/"3"/"4"
    cas_category: Optional[str] = None      # 中科院大类: "医学"
    cas_sub_categories: list[str] = field(default_factory=list)
    ccf_rank: Optional[str] = None          # A/B/C
    ccf_field: Optional[str] = None         # CCF 领域
    is_warning: bool = False
    warning_reason: Optional[str] = None

    def to_dict(self) -> dict:
        d = {
            "impact_factor": self.impact_factor,
            "jcr_quartile": self.jcr_quartile,
        }
        if self.jcr_rank:
            d["jcr_rank"] = self.jcr_rank
        if self.jcr_category:
            d["jcr_category"] = self.jcr_category
        if self.cas_quartile:
            d["cas_quartile"] = self.cas_quartile
        if self.cas_category:
            d["cas_category"] = self.cas_category
        if self.ccf_rank:
            d["ccf_rank"] = self.ccf_rank
        if self.ccf_field:
            d["ccf_field"] = self.ccf_field
        if self.is_warning:
            d["is_warning"] = True
            d["warning_reason"] = self.warning_reason
        return d


class JcrIndex:
    """In-memory index for fast ISSN / journal-name lookups."""

    def __init__(self) -> None:
        self._issn_index: dict[str, JcrEntry] = {}
        self._journal_index: dict[str, JcrEntry] = {}
        self._loaded_year: Optional[int] = None

    def add(self, entry: JcrEntry) -> None:
        """Add entry to both ISSN and journal indexes."""
        if entry.issn:
            self._issn_index[entry.issn] = entry
        # Also index eISSN if present (stored in extra fields during load)
        if entry.journal:
            self._journal_index[entry.journal.lower().strip()] = entry

    def add_issn_alias(self, issn: str, entry: JcrEntry) -> None:
        """Register an additional ISSN pointing to the same entry."""
        if issn:
            self._issn_index[issn] = entry

    def lookup_by_issn(self, issn: str) -> Optional[JcrEntry]:
        return self._issn_index.get(_normalize_issn(issn))

    def lookup_by_journal(self, journal: str) -> Optional[JcrEntry]:
        return self._journal_index.get(journal.lower().strip())

    def lookup(self, issn: str = "", journal: str = "") -> Optional[JcrEntry]:
        """Try ISSN first, then journal name."""
        if issn:
            entry = self.lookup_by_issn(issn)
            if entry:
                return entry
        if journal:
            return self.lookup_by_journal(journal)
        return None

    @property
    def size(self) -> int:
        return len(self._issn_index)

    @property
    def loaded_year(self) -> Optional[int]:
        return self._loaded_year


def _normalize_issn(issn: str | None) -> str:
    """Normalize ISSN: strip hyphens, whitespace, uppercase."""
    if not issn:
        return ""
    return issn.replace("-", "").strip().upper()
