# paper-search-mcp

A lightweight Python MCP (Model Context Protocol) server focused on academic paper search. Search-only — no PDF download or reading (those are handled by Zotero / zotero-mcp).

## Features

- **Multi-platform search** — arXiv, Semantic Scholar, Google Scholar, CrossRef, PubMed, Scopus, bioRxiv, medRxiv, Web of Science
- **Concurrent async** — `asyncio.gather` with configurable concurrency limit
- **Env-driven** — platforms, rate limits, proxy, retry all via environment variables
- **Reliability** — per-platform token-bucket rate limiting, exponential-backoff retry with full jitter, LRU request cache
- **Proxy support** — HTTP/HTTPS/SOCKS5, configurable per platform (e.g. Google Scholar in China)

## Install

```bash
pip install -e .
```

Requires Python >= 3.10.

## Quick Start

### stdio mode (default, for Claude Desktop / MCP clients)

```bash
paper-search-mcp
```

### SSE / HTTP mode

```bash
paper-search-mcp -t sse --port 8000
paper-search-mcp -t streamable-http --port 8000
```

## MCP Client Configuration

Add to your MCP client config (e.g. Claude Desktop `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "paper-search": {
      "command": "paper-search-mcp",
      "args": []
    }
  }
}
```

With explicit environment-based configuration:

```json
{
  "mcpServers": {
    "paper-search": {
      "command": "paper-search-mcp",
      "args": [],
      "env": {
        "PAPER_SEARCH_DEFAULT_PLATFORMS": "crossref,arxiv",
        "PAPER_SEARCH_PLATFORM_CROSSREF_ENABLED": "true",
        "PAPER_SEARCH_PLATFORM_ARXIV_ENABLED": "true",
        "CROSSREF_MAILTO": "you@example.com"
      }
    }
  }
}
```

## MCP Tool

### `paper_search`

Search academic papers across multiple platforms.

**Common query parameters**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | — | Search keywords (1–500 chars) |
| `platforms` | string[] | No | env default | Platform names to search |
| `max_results` | int | No | 10 | Max results per platform (1–100) |
| `year_from` | int | No | — | Filter by start year |
| `year_to` | int | No | — | Filter by end year |
| `sort_by` | string | No | `relevance` | Sort: `relevance`, `date`, `citations` |

**Normalized post-search filters**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `author` | string | No | — | Filter by author name |
| `min_citations` | int | No | — | Minimum citation count filter |
| `journal` | string | No | — | Journal name keyword filter (case-insensitive) |
| `min_if` | float | No | — | Minimum JCR Impact Factor |
| `jcr_quartile` | string | No | — | JCR quartile filter, e.g. `Q1,Q2` |
| `cas_quartile` | string | No | — | CAS quartile filter, e.g. `1,2` |
| `ccf_rank` | string | No | — | CCF rank filter, e.g. `A,B` |
| `exclude_warning` | bool | No | `false` | Exclude journals on the warning list |

**Platform-specific advanced options**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `wos_options` | object | No | — | Web of Science-only options: `doi`, `issn`, `document_type`, `page` |

**Platforms:** `arxiv`, `semantic_scholar`, `google_scholar`, `crossref`, `pubmed`, `scopus`, `biorxiv`, `medrxiv`, `webofscience`

**Citation count support:**

| Platform | Citations | Journal |
|----------|-----------|---------|
| Semantic Scholar | citationCount | — |
| CrossRef | is-referenced-by-count | container-title |
| Scopus | citedby-count | prism:publicationName |
| arXiv | — | — |
| Google Scholar | — | — |
| PubMed | — | — |
| bioRxiv / medRxiv | — | category |

**Behavior:**
1. Resolve target platforms (argument > env default)
2. Create concurrent search tasks (limited by `max_concurrent_searches`)
3. Validate platform-specific options, for example `wos_options` requires `webofscience`
4. Merge results, deduplicate by DOI or title similarity (merge citations — take max)
5. Sort by requested order
6. Apply normalized post-search filters: author, min_citations, journal, JCR filters
7. Return formatted paper list

**Web of Science advanced options**

```json
{
  "query": "machine learning",
  "platforms": ["webofscience"],
  "wos_options": {
    "doi": "10.1000/example",
    "document_type": "Article",
    "page": 2
  }
}
```

**Example output:**

```
Source: arxiv
Paper ID: 1706.03762
Title: Attention Is All You Need
Authors: Ashish Vaswani; Noam Shazeer; Niki Parmar; ...
Abstract: The dominant sequence transduction models are based on complex recurrent...
Published: 2017-06-12
Year: 2017
URL: http://arxiv.org/abs/1706.03762v5
PDF: https://arxiv.org/pdf/1706.03762v5
Categories: cs.CL; cs.LG
```

## Configuration

The server now reads configuration from environment variables only. The `--config/-c`
CLI option is deprecated and ignored.

### Environment variables

Core search settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `PAPER_SEARCH_DEFAULT_PLATFORMS` | `arxiv,semantic_scholar,google_scholar,crossref` | Comma-separated default platform list |
| `PAPER_SEARCH_MAX_RESULTS_PER_PLATFORM` | `10` | Per-platform result cap |
| `PAPER_SEARCH_MAX_CONCURRENT_SEARCHES` | `5` | Fan-out concurrency limit |
| `PAPER_SEARCH_TIMEOUT_SECONDS` | `30` | HTTP timeout for source requests |
| `PAPER_SEARCH_CACHE_MAX_SIZE` | `100` | LRU cache size |
| `PAPER_SEARCH_CACHE_TTL_SECONDS` | `3600` | Cache TTL in seconds |
| `PAPER_SEARCH_RETRY_MAX_RETRIES` | `3` | Retry count for retryable failures |
| `PAPER_SEARCH_RETRY_INITIAL_DELAY_SECONDS` | `1.0` | Initial retry delay |
| `PAPER_SEARCH_RETRY_MAX_DELAY_SECONDS` | `30.0` | Max retry delay |
| `PAPER_SEARCH_DEBUG` | `false` | Append per-platform diagnostics to tool output |

Per-platform overrides use the pattern `PAPER_SEARCH_PLATFORM_<PLATFORM>_<FIELD>`:

| Variable pattern | Example |
|------------------|---------|
| `..._ENABLED` | `PAPER_SEARCH_PLATFORM_CROSSREF_ENABLED=true` |
| `..._MAX_RESULTS` | `PAPER_SEARCH_PLATFORM_WEBOFSCIENCE_MAX_RESULTS=25` |
| `..._RATE_LIMIT_RPS` | `PAPER_SEARCH_PLATFORM_ARXIV_RATE_LIMIT_RPS=0.5` |
| `..._PROXY` | `PAPER_SEARCH_PLATFORM_GOOGLE_SCHOLAR_PROXY=true` |

Supported `<PLATFORM>` names: `ARXIV`, `SEMANTIC_SCHOLAR`, `GOOGLE_SCHOLAR`, `CROSSREF`,
`PUBMED`, `SCOPUS`, `BIORXIV`, `MEDRXIV`, `WEBOFSCIENCE`.

Credentials, mailto, proxy, and JCR settings:

| Variable | Used by |
|----------|---------|
| `SEMANTIC_SCHOLAR_API_KEY` | Semantic Scholar (optional, higher rate limit) |
| `CROSSREF_MAILTO` | CrossRef polite pool (optional, faster) |
| `PUBMED_API_KEY` | PubMed (required if enabled) |
| `SCOPUS_API_KEY` | Scopus (required if enabled) |
| `WOS_API_KEY` | Web of Science Starter (required if enabled) |
| `HTTP_PROXY` / `HTTPS_PROXY` / `SOCKS_PROXY` | Proxy settings |
| `PAPER_SEARCH_JCR_ENABLED` | Enable JCR settings block |
| `PAPER_SEARCH_JCR_DATA_DIR` | Custom JCR data directory |
| `PAPER_SEARCH_JCR_AUTO_UPDATE` | Auto-update stale JCR data |
| `PAPER_SEARCH_JCR_MAX_AGE_DAYS` | Staleness threshold for JCR data |

### Debugging

Set `PAPER_SEARCH_DEBUG=true` to append a compact diagnostics section to the tool output.
This is especially useful for distinguishing `No papers found.` from Web of Science
configuration, authentication, entitlement, or network failures.

## Project Structure

```
src/paper_search_mcp/
├── __init__.py
├── __main__.py           # FastMCP entry + CLI (typer)
├── config.py             # Config loader (environment variables + defaults)
├── models.py             # Paper model + tool option models
├── search/
│   ├── __init__.py       # Searcher registry
│   ├── base.py           # BaseSearcher (retry/rate-limit/cache/proxy)
│   ├── arxiv.py
│   ├── google_scholar.py
│   ├── semantic_scholar.py
│   ├── crossref.py
│   ├── pubmed.py
│   ├── scopus.py
│   ├── biorxiv.py        # includes MedRxivSearcher
│   └── webofscience.py
├── tools/
│   ├── __init__.py
│   └── paper_search.py   # Concurrent search + dedup + sort
└── utils/
    ├── __init__.py
    ├── retry.py           # Exponential backoff + full jitter
    ├── rate_limiter.py    # Token bucket
    ├── cache.py           # LRU + SHA-256 key
    └── proxy.py           # Proxy config parser
```

## License

MIT
