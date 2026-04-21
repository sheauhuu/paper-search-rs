# paper-search-mcp

A lightweight Python MCP (Model Context Protocol) server for academic paper search.
It focuses on metadata retrieval and filtering across multiple sources. PDF download and
full-text reading are intentionally out of scope.

## Documentation

- English docs index: `docs/README.md`
- Chinese guide: `docs/README.zh-CN.md`

## Features

- Multi-platform search: arXiv, Semantic Scholar, Google Scholar, CrossRef, PubMed, Scopus, bioRxiv, medRxiv, Web of Science
- Concurrent async fan-out with bounded concurrency
- Environment-variable configuration only
- Retry, rate limiting, caching, and optional proxy support
- JCR-based journal enrichment and filtering
- Client-visible diagnostics with `PAPER_SEARCH_DEBUG=true`

## Install

### pip

```bash
pip install -e .
```

### uv

```bash
uv sync
uv run paper-search-mcp
```

Requires Python `>=3.10`.

## Quick Start

### stdio mode

Default mode for MCP clients such as Claude Desktop, Cherry Studio, and other stdio-based integrations.

```bash
paper-search-mcp
```

### SSE / streamable HTTP mode

```bash
paper-search-mcp -t sse --port 8000
paper-search-mcp -t streamable-http --port 8000
```

## MCP Client Configuration

Minimal example:

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

Example with explicit environment variables:

```json
{
  "mcpServers": {
    "paper-search": {
      "command": "paper-search-mcp",
      "args": [],
      "env": {
        "PAPER_SEARCH_DEFAULT_PLATFORMS": "crossref,arxiv,webofscience",
        "PAPER_SEARCH_PLATFORM_CROSSREF_ENABLED": "true",
        "PAPER_SEARCH_PLATFORM_ARXIV_ENABLED": "true",
        "PAPER_SEARCH_PLATFORM_WEBOFSCIENCE_ENABLED": "true",
        "CROSSREF_MAILTO": "you@example.com",
        "WOS_API_KEY": "your-wos-key"
      }
    }
  }
}
```

## MCP Tool

### `paper_search`

Search academic papers across multiple platforms.

#### Common query parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | - | Search keywords (1-500 chars) |
| `platforms` | string[] | No | env default | Platform names to search |
| `max_results` | int | No | `10` | Max results per platform (1-100) |
| `year_from` | int | No | - | Filter by start year |
| `year_to` | int | No | - | Filter by end year |
| `sort_by` | string | No | `relevance` | `relevance`, `date`, or `citations` |

#### Normalized post-search filters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `author` | string | No | - | Filter by author name |
| `min_citations` | int | No | - | Minimum citation count filter |
| `journal` | string | No | - | Case-insensitive journal keyword filter |
| `min_if` | float | No | - | Minimum JCR Impact Factor |
| `jcr_quartile` | string | No | - | JCR quartile, for example `Q1,Q2` |
| `cas_quartile` | string | No | - | CAS quartile, for example `1,2` |
| `ccf_rank` | string | No | - | CCF rank, for example `A,B` |
| `exclude_warning` | bool | No | `false` | Exclude journals on the warning list |

#### Platform-specific advanced options

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `wos_options` | object | No | - | Web of Science-only options: `doi`, `issn`, `document_type`, `page` |

Supported platforms:

- `arxiv`
- `semantic_scholar`
- `google_scholar`
- `crossref`
- `pubmed`
- `scopus`
- `biorxiv`
- `medrxiv`
- `webofscience`

#### Example request

```json
{
  "query": "construction safety",
  "platforms": ["webofscience"],
  "year_from": 2021,
  "year_to": 2025,
  "max_results": 10,
  "sort_by": "relevance"
}
```

#### Example WoS request with native options

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

## Configuration

The server reads configuration from environment variables only.

`--config/-c` is no longer supported. Startup fails fast if:

- `-c /path/to/config.yaml` is supplied, or
- a legacy `config.yaml` is detected in an old auto-load location.

### Core search settings

| Variable | Default | Description |
|----------|---------|-------------|
| `PAPER_SEARCH_DEFAULT_PLATFORMS` | `arxiv,semantic_scholar,google_scholar,crossref` | Comma-separated default platform list |
| `PAPER_SEARCH_MAX_RESULTS_PER_PLATFORM` | `10` | Per-platform result cap |
| `PAPER_SEARCH_MAX_CONCURRENT_SEARCHES` | `5` | Fan-out concurrency limit |
| `PAPER_SEARCH_TIMEOUT_SECONDS` | `30` | HTTP timeout |
| `PAPER_SEARCH_CACHE_MAX_SIZE` | `100` | LRU cache size |
| `PAPER_SEARCH_CACHE_TTL_SECONDS` | `3600` | Cache TTL in seconds |
| `PAPER_SEARCH_RETRY_MAX_RETRIES` | `3` | Retry count |
| `PAPER_SEARCH_RETRY_INITIAL_DELAY_SECONDS` | `1.0` | Initial retry delay |
| `PAPER_SEARCH_RETRY_MAX_DELAY_SECONDS` | `30.0` | Max retry delay |
| `PAPER_SEARCH_DEBUG` | `false` | Append per-platform diagnostics to tool output |

### Per-platform overrides

Pattern: `PAPER_SEARCH_PLATFORM_<PLATFORM>_<FIELD>`

| Pattern | Example |
|---------|---------|
| `..._ENABLED` | `PAPER_SEARCH_PLATFORM_CROSSREF_ENABLED=true` |
| `..._MAX_RESULTS` | `PAPER_SEARCH_PLATFORM_WEBOFSCIENCE_MAX_RESULTS=25` |
| `..._RATE_LIMIT_RPS` | `PAPER_SEARCH_PLATFORM_ARXIV_RATE_LIMIT_RPS=0.5` |
| `..._PROXY` | `PAPER_SEARCH_PLATFORM_GOOGLE_SCHOLAR_PROXY=true` |

Supported `<PLATFORM>` names:

- `ARXIV`
- `SEMANTIC_SCHOLAR`
- `GOOGLE_SCHOLAR`
- `CROSSREF`
- `PUBMED`
- `SCOPUS`
- `BIORXIV`
- `MEDRXIV`
- `WEBOFSCIENCE`

### Credentials, proxy, and JCR settings

| Variable | Used by |
|----------|---------|
| `SEMANTIC_SCHOLAR_API_KEY` | Semantic Scholar |
| `CROSSREF_MAILTO` | CrossRef polite pool |
| `PUBMED_API_KEY` | PubMed |
| `SCOPUS_API_KEY` | Scopus |
| `WOS_API_KEY` | Web of Science Starter |
| `HTTP_PROXY` / `HTTPS_PROXY` / `SOCKS_PROXY` | Proxy settings |
| `PAPER_SEARCH_JCR_ENABLED` | Enable JCR enrichment |
| `PAPER_SEARCH_JCR_DATA_DIR` | Custom JCR data directory |
| `PAPER_SEARCH_JCR_AUTO_UPDATE` | Auto-update stale JCR data |
| `PAPER_SEARCH_JCR_MAX_AGE_DAYS` | JCR staleness threshold |

## Debugging

Set `PAPER_SEARCH_DEBUG=true` to append a compact diagnostics section to the tool output.
This is useful when you need to distinguish:

- genuine `No papers found.` results
- missing credentials
- WoS entitlement/authentication failures
- network or endpoint fallback issues

## Project Structure

```text
src/paper_search_mcp/
|-- __init__.py
|-- __main__.py           # FastMCP entry + CLI (typer)
|-- config.py             # Environment-based config loader
|-- models.py             # Paper model + tool option models
|-- search/
|   |-- __init__.py       # Searcher registry
|   |-- base.py           # BaseSearcher (retry/rate-limit/cache/proxy)
|   |-- arxiv.py
|   |-- google_scholar.py
|   |-- semantic_scholar.py
|   |-- crossref.py
|   |-- pubmed.py
|   |-- scopus.py
|   |-- biorxiv.py        # includes MedRxivSearcher
|   `-- webofscience.py
|-- tools/
|   |-- __init__.py
|   `-- paper_search.py   # Concurrent search + dedup + sort
`-- utils/
    |-- __init__.py
    |-- retry.py
    |-- rate_limiter.py
    |-- cache.py
    `-- proxy.py
```

## License

MIT
