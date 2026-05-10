"""paper_search MCP tool — concurrent multi-platform search with dedup and sort."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from loguru import logger

from ..config import Config
from ..jcr.loader import load_jcr_index
from ..jcr.models import JcrIndex
from ..jcr.updater import (
    ensure_jcr_data_current,
    get_data_dir,
    get_jcr_data_source_dir,
    try_save_index_size,
)
from ..models import Paper, WosSearchOptions
from ..search import SEARCHER_REGISTRY

# ── JCR index singleton ───────────────────────────────────────────────────
_jcr_index: Optional[JcrIndex] = None


@dataclass
class PlatformDiagnostics:
    platform: str
    enabled: bool = True
    query: Optional[str] = None
    request_url: Optional[str] = None
    status_code: Optional[int] = None
    api_key_present: Optional[bool] = None
    result_count: Optional[int] = None
    error: Optional[str] = None
    exception_type: Optional[str] = None


@dataclass
class PaperSearchRunResult:
    papers: List[Paper]
    failures: List[str] = field(default_factory=list)
    diagnostics: List[PlatformDiagnostics] = field(default_factory=list)


def _get_jcr_index(config: Optional[Config] = None) -> Optional[JcrIndex]:
    """Get or lazily load JCR index. Returns None if no data available."""
    global _jcr_index

    if config is None:
        config = Config()
    if not config.jcr.get("enabled"):
        return None

    config_dir = config.jcr.get("data_dir", "")
    auto_update_days = int(config.jcr.get("auto_update_days", 7))

    data_dir = get_data_dir(config_dir)
    data_changed = ensure_jcr_data_current(
        config_dir=config_dir,
        auto_update_days=auto_update_days,
    )
    if _jcr_index is not None and _jcr_index.size > 0 and not data_changed:
        return _jcr_index

    source_dir = get_jcr_data_source_dir(data_dir)
    if source_dir is None:
        return None

    _jcr_index = load_jcr_index(str(source_dir))
    if _jcr_index.size > 0:
        try_save_index_size(data_dir, _jcr_index.size)
        return _jcr_index
    return None


def _title_similarity(a: str, b: str) -> float:
    """Normalized similarity ratio between two titles."""
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _dedup_papers(papers: List[Paper], threshold: float = 0.85) -> List[Paper]:
    """Deduplicate papers by DOI or title similarity.

    Keeps the first occurrence (higher priority platform wins).
    Merges citations from duplicates — takes the max value.
    """
    seen_dois: set[str] = set()
    result: List[Paper] = []

    for paper in papers:
        # DOI-based dedup
        if paper.doi:
            doi_lower = paper.doi.lower()
            if doi_lower in seen_dois:
                # Merge citations into existing
                for existing in result:
                    if existing.doi and existing.doi.lower() == doi_lower:
                        existing.citations = max(existing.citations, paper.citations)
                        break
                continue
            seen_dois.add(doi_lower)

        # Title-based dedup
        is_dup = False
        for existing in result:
            if _title_similarity(paper.title, existing.title) >= threshold:
                # Merge citations
                existing.citations = max(existing.citations, paper.citations)
                is_dup = True
                break
        if is_dup:
            continue

        result.append(paper)

    return result


def _sort_papers(papers: List[Paper], sort_by: str = "relevance") -> List[Paper]:
    """Sort papers by relevance (default), date, or citations."""
    if sort_by == "date":
        return sorted(
            papers,
            key=_paper_date_sort_value,
            reverse=True,
        )
    if sort_by == "citations":
        return sorted(papers, key=lambda p: p.citations, reverse=True)
    # relevance — keep original order (platform priority)
    return papers


def _paper_date_sort_value(paper: Paper) -> int:
    """Return a comparable ordinal for mixed datetime/year records."""
    if paper.published_date is not None:
        return paper.published_date.date().toordinal()
    if paper.year is not None:
        return datetime(paper.year, 1, 1).date().toordinal()
    return 0


def _enrich_with_jcr(papers: List[Paper], index: Optional[JcrIndex]) -> None:
    """Enrich papers with JCR metrics in-place. Skips if index is None."""
    if index is None:
        return
    for paper in papers:
        if not paper.journal:
            continue
        entry = index.lookup(issn="", journal=paper.journal)
        if entry is None:
            continue
        if entry.impact_factor is not None:
            paper.impact_factor = entry.impact_factor
        if entry.jcr_quartile:
            paper.jcr_quartile = entry.jcr_quartile
        if entry.cas_quartile:
            paper.cas_quartile = entry.cas_quartile
        if entry.ccf_rank:
            paper.ccf_rank = entry.ccf_rank
        if entry.is_warning:
            paper.is_warning = True


def _filter_by_jcr(
    papers: List[Paper],
    min_if: Optional[float] = None,
    jcr_quartile: Optional[str] = None,
    cas_quartile: Optional[str] = None,
    ccf_rank: Optional[str] = None,
    exclude_warning: bool = False,
) -> List[Paper]:
    """Filter papers by JCR-related criteria."""
    result = papers
    if min_if is not None:
        result = [p for p in result if p.impact_factor is not None and p.impact_factor >= min_if]
    if jcr_quartile:
        allowed = _expand_quartile(jcr_quartile)
        result = [p for p in result if p.jcr_quartile and p.jcr_quartile.upper() in allowed]
    if cas_quartile:
        allowed = _expand_quartile(cas_quartile)
        result = [p for p in result if p.cas_quartile and p.cas_quartile in allowed]
    if ccf_rank:
        allowed_ranks = {r.strip().upper() for r in ccf_rank.split(",")}
        result = [p for p in result if p.ccf_rank and p.ccf_rank.upper() in allowed_ranks]
    if exclude_warning:
        result = [p for p in result if not p.is_warning]
    return result


def _expand_quartile(q: str) -> set[str]:
    """Expand quartile filter: 'Q1' -> {'Q1'}, 'Q1,Q2' -> {'Q1','Q2'},
    '1' -> {'1','Q1'}, '1,2' -> {'1','2','Q1','Q2'}."""
    parts = [p.strip().upper() for p in q.split(",")]
    result: set[str] = set()
    for p in parts:
        result.add(p)
        # Numeric form also matches Q-form
        if p in ("1", "2", "3", "4"):
            result.add(f"Q{p}")
        elif p in ("Q1", "Q2", "Q3", "Q4"):
            result.add(p[1])  # also match numeric
    return result


def _resolve_target_platforms(platforms: Optional[List[str]], config: Config) -> List[str]:
    """Resolve explicit platforms or fall back to env-backed defaults."""
    if platforms:
        return platforms
    return config.enabled_platforms()


def _validate_platform_specific_options(
    target_platforms: List[str],
    wos_options: Optional[WosSearchOptions] = None,
) -> None:
    """Validate that platform-specific options match the requested platform set."""
    if wos_options and wos_options.to_search_kwargs() and "webofscience" not in target_platforms:
        raise ValueError(
            "wos_options requires 'webofscience' in platforms or enabled default platforms."
        )


def _build_search_kwargs(
    name: str,
    *,
    max_results: int,
    sort_by: str,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    author: Optional[str] = None,
    journal: Optional[str] = None,
    wos_options: Optional[WosSearchOptions] = None,
) -> dict[str, Any]:
    """Build per-platform search kwargs from the shared tool contract."""
    kwargs: dict[str, Any] = {
        "max_results": max_results,
        "sort_by": sort_by,
    }
    if year_from is not None:
        kwargs["year_from"] = year_from
    if year_to is not None:
        kwargs["year_to"] = year_to
    if author:
        kwargs["author"] = author
    if journal:
        kwargs["journal"] = journal
    if name == "webofscience" and wos_options:
        kwargs.update(wos_options.to_search_kwargs())
    return kwargs


def _diagnostics_from_searcher(name: str, searcher: Any) -> PlatformDiagnostics:
    snapshot = {}
    if hasattr(searcher, "diagnostics_snapshot"):
        snapshot = searcher.diagnostics_snapshot()
    elif hasattr(searcher, "last_diagnostics"):
        snapshot = dict(getattr(searcher, "last_diagnostics") or {})
    if "platform" not in snapshot:
        snapshot["platform"] = name
    return PlatformDiagnostics(**snapshot)


def _format_platform_failure(diag: PlatformDiagnostics) -> str:
    if diag.error:
        return diag.error
    if not diag.enabled:
        return f"{diag.platform} is disabled by configuration."
    return f"{diag.platform} search failed."


async def paper_search_with_diagnostics(
    query: str,
    platforms: Optional[List[str]] = None,
    max_results: int = 10,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    author: Optional[str] = None,
    sort_by: str = "relevance",
    min_citations: Optional[int] = None,
    journal: Optional[str] = None,
    min_if: Optional[float] = None,
    jcr_quartile: Optional[str] = None,
    cas_quartile: Optional[str] = None,
    ccf_rank: Optional[str] = None,
    exclude_warning: bool = False,
    wos_options: Optional[WosSearchOptions] = None,
    config: Optional[Config] = None,
) -> PaperSearchRunResult:
    """Search papers and return result papers plus per-platform diagnostics."""
    if config is None:
        config = Config()

    target_platforms = _resolve_target_platforms(platforms, config)
    _validate_platform_specific_options(target_platforms, wos_options)

    diagnostics: List[PlatformDiagnostics] = []
    failures: List[str] = []

    # Instantiate searchers
    searchers: Dict[str, Any] = {}
    explicit_platforms = bool(platforms)
    for name in target_platforms:
        cls = SEARCHER_REGISTRY.get(name)
        if cls is None:
            logger.warning(f"Unknown platform: {name}")
            diag = PlatformDiagnostics(
                platform=name,
                enabled=False,
                error=f"Unknown platform: {name}.",
            )
            diagnostics.append(diag)
            if explicit_platforms:
                failures.append(diag.error or f"{name} failed")
            continue
        searchers[name] = cls(config)

    if not searchers:
        logger.warning("No enabled platforms to search")
        return PaperSearchRunResult(papers=[], failures=failures, diagnostics=diagnostics)

    # Build search tasks with semaphore for concurrency limit
    semaphore = asyncio.Semaphore(config.max_concurrent_searches)

    async def _search_one(name: str, searcher: Any) -> tuple[str, List[Paper]]:
        async with semaphore:
            try:
                kwargs = _build_search_kwargs(
                    name,
                    max_results=max_results,
                    sort_by=sort_by,
                    year_from=year_from,
                    year_to=year_to,
                    author=author,
                    journal=journal,
                    wos_options=wos_options,
                )
                papers = await searcher.search(query, **kwargs)
                return name, papers
            except Exception as e:
                logger.error(f"[{name}] Search error: {e}")
                if hasattr(searcher, "reset_diagnostics"):
                    searcher.reset_diagnostics(query=query)
                if hasattr(searcher, "update_diagnostics"):
                    searcher.update_diagnostics(
                        error=f"{name} search failed: {e}",
                        exception_type=type(e).__name__,
                    )
                return name, []

    # Run all searches concurrently
    tasks = [_search_one(name, s) for name, s in searchers.items()]
    results = await asyncio.gather(*tasks)
    results_map = dict(results)

    for name in target_platforms:
        if name not in searchers:
            continue
        diag = _diagnostics_from_searcher(name, searchers[name])
        diagnostics.append(diag)
        if not results_map.get(name) and diag.error:
            failures.append(_format_platform_failure(diag))

    # Merge in platform-priority order
    all_papers: List[Paper] = []
    for name in target_platforms:
        if name in results_map:
            all_papers.extend(results_map[name])

    # Dedup and sort
    all_papers = _dedup_papers(all_papers)
    all_papers = _sort_papers(all_papers, sort_by)

    # JCR enrichment (in-place)
    jcr_index = _get_jcr_index(config)
    _enrich_with_jcr(all_papers, jcr_index)

    # Author filter (post-search)
    if author:
        author_lower = author.lower()
        all_papers = [
            p for p in all_papers
            if any(author_lower in a.lower() for a in p.authors)
        ]

    # Citation count filter (post-search)
    if min_citations is not None:
        all_papers = [p for p in all_papers if p.citations >= min_citations]

    # Journal filter (post-search, case-insensitive keyword match)
    if journal:
        journal_lower = journal.lower()
        all_papers = [
            p for p in all_papers
            if p.journal and journal_lower in p.journal.lower()
        ]

    # JCR-based filters (post-enrichment)
    if any([min_if, jcr_quartile, cas_quartile, ccf_rank, exclude_warning]):
        all_papers = _filter_by_jcr(
            all_papers,
            min_if=min_if,
            jcr_quartile=jcr_quartile,
            cas_quartile=cas_quartile,
            ccf_rank=ccf_rank,
            exclude_warning=exclude_warning,
        )

    return PaperSearchRunResult(papers=all_papers, failures=failures, diagnostics=diagnostics)


async def paper_search(
    query: str,
    platforms: Optional[List[str]] = None,
    max_results: int = 10,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    author: Optional[str] = None,
    sort_by: str = "relevance",
    min_citations: Optional[int] = None,
    journal: Optional[str] = None,
    min_if: Optional[float] = None,
    jcr_quartile: Optional[str] = None,
    cas_quartile: Optional[str] = None,
    ccf_rank: Optional[str] = None,
    exclude_warning: bool = False,
    wos_options: Optional[WosSearchOptions] = None,
    config: Optional[Config] = None,
) -> List[Paper]:
    """Search academic papers across platforms concurrently.

    Args:
        query: Search keywords.
        platforms: Platform names to search. None = use env-backed defaults.
        max_results: Max results per platform.
        year_from: Filter by start year.
        year_to: Filter by end year.
        author: Filter by author.
        sort_by: 'relevance', 'date', or 'citations'.
        min_citations: Minimum citation count filter.
        journal: Journal name keyword filter (case-insensitive match).
        min_if: Minimum JCR Impact Factor filter.
        jcr_quartile: JCR quartile filter (e.g. 'Q1', 'Q1,Q2').
        cas_quartile: CAS quartile filter (e.g. '1', '1,2').
        ccf_rank: CCF rank filter (e.g. 'A', 'A,B').
        exclude_warning: Exclude journals on warning list.
        wos_options: Web of Science-only native options (doi, issn, document_type, page).
        config: Application config.

    Returns:
        Deduplicated and sorted list of Paper objects.
    """
    result = await paper_search_with_diagnostics(
        query=query,
        platforms=platforms,
        max_results=max_results,
        year_from=year_from,
        year_to=year_to,
        author=author,
        sort_by=sort_by,
        min_citations=min_citations,
        journal=journal,
        min_if=min_if,
        jcr_quartile=jcr_quartile,
        cas_quartile=cas_quartile,
        ccf_rank=ccf_rank,
        exclude_warning=exclude_warning,
        wos_options=wos_options,
        config=config,
    )
    return result.papers
