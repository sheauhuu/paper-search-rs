"""FastMCP entry point + CLI (typer)."""

from __future__ import annotations

from typing import List, Literal, Optional

import typer
from fastmcp import FastMCP
from loguru import logger
from pydantic import Field

from .config import Config
from .jcr.loader import load_jcr_index
from .models import SortBy, WosSearchOptions
from .jcr.updater import get_data_dir, needs_update, save_version, update_jcr_data
from .tools.paper_search import (
    PlatformDiagnostics,
    _get_jcr_index,
    paper_search_with_diagnostics as _paper_search_with_diagnostics,
)

# ── Config singleton ──────────────────────────────────────────────────────
_config: Optional[Config] = None


def _get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config


def _load_runtime_config(config_path: Optional[str] = None) -> Config:
    """Load runtime config and convert legacy-config misuse into a clean CLI exit."""
    try:
        return Config(config_path)
    except ValueError as exc:
        logger.error(f"[config] {exc}")
        raise typer.Exit(code=1) from exc


def _format_debug_section(diagnostics: list[PlatformDiagnostics]) -> str:
    """Render compact diagnostics for client-visible debugging."""
    lines = ["[debug]"]
    for diag in diagnostics:
        lines.append(f"platform={diag.platform}")
        lines.append(f"enabled={diag.enabled}")
        if diag.api_key_present is not None:
            lines.append(f"api_key={'set' if diag.api_key_present else 'unset'}")
        if diag.query:
            lines.append(f"query={diag.query}")
        if diag.request_url:
            lines.append(f"request_url={diag.request_url}")
        if diag.status_code is not None:
            lines.append(f"status={diag.status_code}")
        if diag.result_count is not None:
            lines.append(f"result_count={diag.result_count}")
        if diag.error:
            lines.append(f"error={diag.error}")
        if diag.exception_type:
            lines.append(f"exception_type={diag.exception_type}")
        lines.append("---")
    if lines[-1] == "---":
        lines.pop()
    return "\n".join(lines)


# ── MCP server ────────────────────────────────────────────────────────────
mcp = FastMCP("paper-search-mcp")


def _build_tool_description(config: Config) -> str:
    """Build config-aware tool description exposing only enabled platforms."""
    enabled = config.enabled_platforms()
    if not enabled:
        return "Search academic papers. No platforms are currently enabled."

    parts = [
        f"Search academic papers across: {', '.join(enabled)}.",
        "If platforms is omitted, all enabled platforms are searched.",
        "",
        "Common query parameters:",
        "- query: search keywords",
        "- platforms: target sources, or all enabled platforms if omitted",
        "- max_results: per-platform result cap",
        "- year_from / year_to: publication year range",
        "- sort_by: relevance, date, or citations",
        "",
        "Normalized post-search filters:",
        "- author: author name keyword filter",
        "- journal: journal/source name keyword filter",
        "- min_citations: keep only papers with citations >= value",
    ]

    if "webofscience" in enabled:
        parts.extend([
            "",
            "Web of Science Starter notes:",
            "- Advanced options: pass through wos_options",
            "- Supports fielded search via query: TS, AU, SO, PY, DO, IS, DT tags",
            "- Example: TS=(machine learning) AND PY=(2020-2024)",
            "- wos_options fields: doi, issn, document_type, page",
        ])

    if config.jcr.get("enabled"):
        parts.extend([
            "",
            "JCR / journal metrics (requires local JCR data):",
            "- Impact Factor, JCR quartile, CAS quartile, CCF rank, warning list",
            "- Filters: min_if, jcr_quartile, cas_quartile, ccf_rank, exclude_warning",
        ])

    parts.append(
        "\nReturns plain-text paper records including title, authors, abstract, DOI, "
        "URL, citations, journal metadata, and JCR fields when available."
    )
    return "\n".join(parts)


async def paper_search_tool(
    query: str = Field(..., description="Search keywords", min_length=1, max_length=500),
    platforms: Optional[List[str]] = Field(
        default=None,
        description="Platform names to search. Empty = use all enabled platforms.",
    ),
    max_results: int = Field(default=10, ge=1, le=100, description="Max results per platform"),
    year_from: Optional[int] = Field(default=None, description="Filter by start year"),
    year_to: Optional[int] = Field(default=None, description="Filter by end year"),
    author: Optional[str] = Field(default=None, description="Filter by author name"),
    sort_by: SortBy = Field(
        default="relevance",
        description="Sort order: relevance, date, or citations",
    ),
    min_citations: Optional[int] = Field(
        default=None,
        description="Minimum citation count filter. Only papers with citations >= this value are returned.",
    ),
    journal: Optional[str] = Field(
        default=None,
        description="Journal name keyword filter (case-insensitive). e.g. 'Nature', 'ICML'",
    ),
    min_if: Optional[float] = Field(
        default=None,
        description="Minimum JCR Impact Factor filter. Only papers with IF >= this value are returned.",
    ),
    jcr_quartile: Optional[str] = Field(
        default=None,
        description="JCR quartile filter. e.g. 'Q1', 'Q1,Q2'. Matches Q1-Q4 format.",
    ),
    cas_quartile: Optional[str] = Field(
        default=None,
        description="CAS (中科院) quartile filter. e.g. '1', '1,2'. Matches 1-4 format.",
    ),
    ccf_rank: Optional[str] = Field(
        default=None,
        description="CCF rank filter. e.g. 'A', 'A,B'. Matches A/B/C.",
    ),
    exclude_warning: bool = Field(
        default=False,
        description="Exclude journals on the 中科院预警 list.",
    ),
    wos_options: Optional[WosSearchOptions] = Field(
        default=None,
        description=(
            "Web of Science-only advanced options. "
            "Requires 'webofscience' in platforms or enabled defaults."
        ),
    ),
) -> str:
    """Search academic papers across platforms."""
    config = _get_config()
    result = await _paper_search_with_diagnostics(
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
    if not result.papers:
        text = "\n".join(result.failures) if result.failures else "No papers found."
    else:
        text = "\n\n---\n\n".join(p.to_text() for p in result.papers)

    if config.debug_enabled:
        debug_text = _format_debug_section(result.diagnostics)
        text = f"{text}\n\n{debug_text}" if debug_text else text

    return text


# Register tool with default config at import time (for tests, introspection).
# Overwritten in run() with config-aware description after env is loaded.
mcp.tool(name="paper_search", description=_build_tool_description(_get_config()))(
    paper_search_tool
)


# ── JCR lookup tool ───────────────────────────────────────────────────────

_JCR_LOOKUP_DESC = """Look up JCR journal metrics by journal name or ISSN.

Requires JCR data loaded (run `paper-search-mcp update-jcr` first).
Returns Impact Factor, JCR quartile, CAS quartile, CCF rank, and warning list status."""


def _format_jcr_entry(entry: object) -> str:
    """Format a JcrEntry as plain text."""
    lines = []
    if getattr(entry, "journal", None):
        lines.append(f"Journal: {entry.journal}")
    if getattr(entry, "issn", None):
        lines.append(f"ISSN: {entry.issn}")
    if getattr(entry, "impact_factor", None) is not None:
        lines.append(f"Impact Factor: {entry.impact_factor}")
    if getattr(entry, "jcr_quartile", None):
        lines.append(f"JCR Quartile: {entry.jcr_quartile}")
    if getattr(entry, "jcr_rank", None):
        lines.append(f"JCR Rank: {entry.jcr_rank}")
    if getattr(entry, "jcr_category", None):
        lines.append(f"JCR Category: {entry.jcr_category}")
    if getattr(entry, "cas_quartile", None):
        lines.append(f"CAS Quartile: {entry.cas_quartile}")
    if getattr(entry, "cas_category", None):
        lines.append(f"CAS Category: {entry.cas_category}")
    if getattr(entry, "cas_sub_categories", None):
        lines.append(f"CAS Sub-categories: {'; '.join(entry.cas_sub_categories)}")
    if getattr(entry, "ccf_rank", None):
        lines.append(f"CCF Rank: {entry.ccf_rank}")
    if getattr(entry, "ccf_field", None):
        lines.append(f"CCF Field: {entry.ccf_field}")
    if getattr(entry, "is_warning", None):
        lines.append("Warning: journal on warning list")
        if getattr(entry, "warning_reason", None):
            lines.append(f"Warning Reason: {entry.warning_reason}")
    return "\n".join(lines) if lines else "No JCR data found."


async def jcr_lookup_tool(
    journal: Optional[str] = Field(
        default=None,
        description="Journal name (case-insensitive match). e.g. 'Nature', 'Safety Science'",
    ),
    issn: Optional[str] = Field(
        default=None,
        description="ISSN of the journal. e.g. '0028-0836'",
    ),
) -> str:
    """Look up JCR metrics for a journal."""
    config = _get_config()

    if not journal and not issn:
        return "Provide at least one of: journal name or ISSN."

    jcr_index = _get_jcr_index(config)
    if jcr_index is None:
        return (
            "JCR data not available. "
            "Run `paper-search-mcp update-jcr` to download data first, "
            "and set PAPER_SEARCH_JCR_ENABLED=true."
        )

    entry = jcr_index.lookup(issn=issn or "", journal=journal or "")
    if entry is None:
        return f"No JCR data found for {'ISSN ' + issn if issn else journal}."

    return _format_jcr_entry(entry)


def _register_jcr_lookup(config: Config) -> None:
    """Register jcr_lookup tool only when JCR is enabled."""
    if config.jcr.get("enabled"):
        mcp.tool(name="jcr_lookup", description=_JCR_LOOKUP_DESC)(jcr_lookup_tool)


# Register with default config at import time (for tests).
_register_jcr_lookup(_get_config())

# ── CLI ───────────────────────────────────────────────────────────────────
app = typer.Typer(add_completion=False, help="paper-search-mcp — Academic paper search MCP server")


@app.callback(invoke_without_command=True)
def run(
    ctx: typer.Context,
    host: str = typer.Option("127.0.0.1", help="Bind host (SSE/HTTP only)"),
    port: int = typer.Option(8000, min=1, max=65535, help="Bind port (SSE/HTTP only)"),
    transport: Optional[Literal["stdio", "sse", "streamable-http"]] = typer.Option(
        None,
        "--transport",
        "-t",
        help="Transport: stdio (default), sse, or streamable-http",
    ),
    config_path: Optional[str] = typer.Option(
        None,
        "--config",
        "-c",
        help="Unsupported. Use environment variables instead of file-based config.",
    ),
) -> None:
    """Run the paper-search-mcp server (default when no subcommand is given)."""
    # If a subcommand was invoked, skip server startup
    if ctx.invoked_subcommand is not None:
        return

    # Load config early
    global _config
    _config = _load_runtime_config(config_path)
    enabled = _config.enabled_platforms()
    logger.info(f"paper-search-mcp starting | enabled platforms: {', '.join(enabled)}")

    # Re-register tool with config-aware description (only mentions enabled platforms)
    mcp.tool(name="paper_search", description=_build_tool_description(_config))(
        paper_search_tool
    )

    # Conditionally register jcr_lookup (only when JCR is enabled)
    _register_jcr_lookup(_config)

    if not transport or transport == "stdio":
        mcp.run(transport="stdio")
    else:
        logger.info(f"Starting on {host}:{port} with transport '{transport}'")
        mcp.run(transport=transport, host=host, port=port)


@app.command(name="update-jcr", help="Download or update JCR data from ShowJCR repo")
def update_jcr(
    config_path: Optional[str] = typer.Option(
        None,
        "--config",
        "-c",
        help="Unsupported. Use environment variables instead of file-based config.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Force update even if data is recent",
    ),
) -> None:
    """Download or update JCR journal metrics data."""
    config = _load_runtime_config(config_path)
    config_dir = config.jcr.get("data_dir", "")
    data_dir = get_data_dir(config_dir)

    if not force and not needs_update(data_dir, max_age_days=config.jcr.get("max_age_days", 30)):
        logger.info("JCR data is up to date. Use --force to update anyway.")
        typer.echo("JCR data is up to date. Use --force to update anyway.")
        return

    logger.info("Updating JCR data...")
    typer.echo("Downloading/updating JCR data from ShowJCR repo...")
    try:
        csv_dir = update_jcr_data(config_dir)
        save_version(data_dir)
        # Verify by loading
        index = load_jcr_index(str(csv_dir))
        msg = f"JCR data updated successfully: {index.size} journals indexed"
        logger.info(msg)
        typer.echo(msg)
    except RuntimeError as e:
        logger.error(str(e))
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
