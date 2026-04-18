from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


SortBy = Literal["relevance", "date", "citations"]


class WosSearchOptions(BaseModel):
    """Web of Science-specific advanced options exposed by the MCP tool."""

    doi: Optional[str] = Field(default=None, description="Web of Science DOI filter")
    issn: Optional[str] = Field(default=None, description="Web of Science ISSN filter")
    document_type: Optional[str] = Field(
        default=None,
        description="Web of Science document type filter. Comma-separated values are allowed.",
    )
    page: Optional[int] = Field(
        default=None,
        ge=1,
        description="Web of Science result page number (1-based)",
    )

    def to_search_kwargs(self) -> Dict[str, Any]:
        """Return non-empty kwargs for the WoS searcher."""
        return self.model_dump(exclude_none=True)


class Paper(BaseModel):
    """Standardized paper model for all search platforms."""

    paper_id: str = Field(description="Platform-unique ID (arXiv ID, DOI, PMID, etc.)")
    title: str = Field(default="", description="Paper title")
    authors: List[str] = Field(default_factory=list, description="Author names")
    abstract: str = Field(default="", description="Abstract text")
    doi: Optional[str] = Field(default=None, description="Digital Object Identifier")
    published_date: Optional[datetime] = Field(default=None, description="Publication date")
    pdf_url: Optional[str] = Field(default=None, description="Direct PDF link")
    url: str = Field(default="", description="Paper page URL")
    source: str = Field(default="", description="Source platform name")
    categories: List[str] = Field(default_factory=list, description="Subject categories")
    keywords: List[str] = Field(default_factory=list, description="Keywords")
    citations: int = Field(default=0, description="Citation count")
    journal: Optional[str] = Field(default=None, description="Journal name")
    year: Optional[int] = Field(default=None, description="Publication year")
    impact_factor: Optional[float] = Field(default=None, description="JCR Impact Factor")
    jcr_quartile: Optional[str] = Field(default=None, description="JCR quartile (Q1/Q2/Q3/Q4)")
    cas_quartile: Optional[str] = Field(default=None, description="CAS quartile (1/2/3/4)")
    ccf_rank: Optional[str] = Field(default=None, description="CCF rank (A/B/C)")
    is_warning: bool = Field(default=False, description="Journal on warning list")
    extra: Dict[str, Any] = Field(default_factory=dict, description="Platform-specific metadata")

    @staticmethod
    def _format_extra_label(key: str) -> str:
        """Convert internal extra keys to readable plain-text labels."""
        return key.replace("_", " ").strip().title()

    @staticmethod
    def _format_extra_value(value: Any) -> Optional[str]:
        """Format platform-specific metadata values for plain-text output."""
        if value is None:
            return None
        if isinstance(value, dict):
            if value.get("range"):
                return str(value["range"])
            begin = value.get("begin")
            end = value.get("end")
            if begin and end:
                return f"{begin}-{end}"
            if value.get("count"):
                return str(value["count"])
            parts = [f"{k}={v}" for k, v in value.items() if v not in (None, "", [], {})]
            return ", ".join(parts) or None
        if isinstance(value, (list, tuple, set)):
            items = [str(item) for item in value if item]
            return "; ".join(items) or None
        return str(value)

    def to_text(self) -> str:
        """Convert to plain-text representation for MCP output."""
        lines: list[str] = []
        if self.source:
            lines.append(f"Source: {self.source}")
        if self.paper_id:
            lines.append(f"Paper ID: {self.paper_id}")
        if self.title:
            lines.append(f"Title: {self.title}")
        if self.authors:
            lines.append(f"Authors: {'; '.join(self.authors)}")
        if self.abstract:
            lines.append(f"Abstract: {self.abstract}")
        if self.published_date:
            lines.append(f"Published: {self.published_date.strftime('%Y-%m-%d')}")
        if self.year:
            lines.append(f"Year: {self.year}")
        if self.url:
            lines.append(f"URL: {self.url}")
        if self.doi:
            lines.append(f"DOI: {self.doi}")
        if self.pdf_url:
            lines.append(f"PDF: {self.pdf_url}")
        if self.categories:
            lines.append(f"Categories: {'; '.join(self.categories)}")
        if self.keywords:
            lines.append(f"Keywords: {'; '.join(self.keywords)}")
        if self.citations:
            lines.append(f"Citations: {self.citations}")
        if self.journal:
            lines.append(f"Journal: {self.journal}")
        if self.impact_factor is not None:
            lines.append(f"Impact Factor: {self.impact_factor}")
        if self.jcr_quartile:
            lines.append(f"JCR Quartile: {self.jcr_quartile}")
        if self.cas_quartile:
            lines.append(f"CAS Quartile: {self.cas_quartile}")
        if self.ccf_rank:
            lines.append(f"CCF Rank: {self.ccf_rank}")
        if self.is_warning:
            lines.append(f"Warning: journal on warning list")
        if self.extra:
            for k, v in self.extra.items():
                formatted_value = self._format_extra_value(v)
                if formatted_value:
                    lines.append(f"{self._format_extra_label(k)}: {formatted_value}")
        return "\n".join(lines)
