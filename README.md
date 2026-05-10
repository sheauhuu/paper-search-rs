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
- Optional `jcr_lookup` tool for direct journal metric lookup
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
        "CROSSREF_MAILTO": "you@example.com",
        "WOS_API_KEY": "your-wos-key"
      }
    }
  }
}
```

## MCP Tools

The available MCP tool surface is configuration-aware:

- `paper_search` is always registered.
- `jcr_lookup` is registered only when `PAPER_SEARCH_JCR_ENABLED=true`.

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

### `jcr_lookup`

Look up local JCR journal metrics directly by journal name or ISSN.

This tool is only exposed when `PAPER_SEARCH_JCR_ENABLED=true`. If JCR is enabled and no local data exists, runtime auto-update downloads ShowJCR data on first use unless `PAPER_SEARCH_JCR_AUTO_UPDATE_DAYS=0`.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `journal` | string | No | - | Journal name keyword, case-insensitive |
| `issn` | string | No | - | Journal ISSN |

At least one of `journal` or `issn` must be provided.

#### Example JCR lookup

```json
{
  "journal": "Nature"
}
```

Typical output includes Impact Factor, JCR quartile, JCR rank/category, CAS quartile/category, CCF rank/field, and warning-list status when available.

## Configuration

The server reads configuration from environment variables only.
It does not write or persist application configuration files. Put runtime settings in your MCP client's `env` block, shell environment, container environment, or process manager.

`--config/-c` is no longer supported. Startup fails fast if:

- `-c /path/to/config.yaml` is supplied, or
- a legacy `config.yaml` is detected in an old auto-load location.

### Platform enabling

**`PAPER_SEARCH_DEFAULT_PLATFORMS`** is the sole enable switch. Platforms listed here are enabled; all others are disabled. The tool description exposed to AI clients only mentions enabled platforms.

```
PAPER_SEARCH_DEFAULT_PLATFORMS=arxiv,crossref,webofscience
```

### Core search settings

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PAPER_SEARCH_DEFAULT_PLATFORMS` | No | `arxiv,semantic_scholar,google_scholar,crossref` | Comma-separated list of enabled platforms |
| `PAPER_SEARCH_MAX_RESULTS_PER_PLATFORM` | No | `10` | Per-platform result cap |
| `PAPER_SEARCH_MAX_CONCURRENT_SEARCHES` | No | `5` | Fan-out concurrency limit |
| `PAPER_SEARCH_TIMEOUT_SECONDS` | No | `30` | HTTP timeout (seconds) |
| `PAPER_SEARCH_CACHE_MAX_SIZE` | No | `100` | LRU cache size |
| `PAPER_SEARCH_CACHE_TTL_SECONDS` | No | `3600` | Cache TTL (seconds) |
| `PAPER_SEARCH_RETRY_MAX_RETRIES` | No | `3` | Retry count |
| `PAPER_SEARCH_RETRY_INITIAL_DELAY_SECONDS` | No | `1.0` | Initial retry delay (seconds) |
| `PAPER_SEARCH_RETRY_MAX_DELAY_SECONDS` | No | `30.0` | Max retry delay (seconds) |
| `PAPER_SEARCH_DEBUG` | No | `false` | Append per-platform diagnostics to tool output |

### Per-platform overrides

Pattern: `PAPER_SEARCH_PLATFORM_<PLATFORM>_<FIELD>`. All optional.

| Field | Example | Description |
|-------|---------|-------------|
| `..._MAX_RESULTS` | `PAPER_SEARCH_PLATFORM_WEBOFSCIENCE_MAX_RESULTS=25` | Override per-platform result cap |
| `..._RATE_LIMIT_RPS` | `PAPER_SEARCH_PLATFORM_ARXIV_RATE_LIMIT_RPS=0.5` | Requests per second limit |
| `..._PROXY` | `PAPER_SEARCH_PLATFORM_GOOGLE_SCHOLAR_PROXY=true` | Enable proxy for this platform |

Supported `<PLATFORM>` names: `ARXIV`, `SEMANTIC_SCHOLAR`, `GOOGLE_SCHOLAR`, `CROSSREF`, `PUBMED`, `SCOPUS`, `BIORXIV`, `MEDRXIV`, `WEBOFSCIENCE`.

### Credentials

Required only when the corresponding platform is enabled.

| Variable | Required when | Description |
|----------|---------------|-------------|
| `SEMANTIC_SCHOLAR_API_KEY` | Optional | Higher rate limit for Semantic Scholar |
| `CROSSREF_MAILTO` | Optional | CrossRef polite pool (faster response) |
| `PUBMED_API_KEY` | PubMed enabled | PubMed API key |
| `SCOPUS_API_KEY` | Scopus enabled | Scopus API key |
| `WOS_API_KEY` | Web of Science enabled | WoS Starter API key |

### Proxy

All optional. Applied globally or per-platform via `..._PROXY=true`.

| Variable | Description |
|----------|-------------|
| `HTTP_PROXY` | HTTP proxy URL |
| `HTTPS_PROXY` | HTTPS proxy URL |
| `SOCKS_PROXY` | SOCKS5 proxy URL |

### JCR / journal metrics

JCR enrichment is a standalone feature, independent of platform selection. When enabled, search results are enriched with Impact Factor, JCR quartile, CAS quartile, CCF rank, and warning list status. Runtime auto-update is enabled by default: if local data is missing, the first JCR use downloads ShowJCR data; after that, the server checks the upstream repository at most once per configured interval.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PAPER_SEARCH_JCR_ENABLED` | No | `false` | Enable JCR enrichment and filters |
| `PAPER_SEARCH_JCR_DATA_DIR` | No | `~/.paper-search-mcp/jcr` | JCR data directory. Defaults to `~/.paper-search-mcp/jcr` if not set. Use a writable persistent directory in containers |
| `PAPER_SEARCH_JCR_AUTO_UPDATE_DAYS` | No | `7` | Runtime upstream-check interval in days. `0` disables runtime auto-update and first-use download |
| `PAPER_SEARCH_JCR_MAX_AGE_DAYS` | No | `30` | Manual `update-jcr` CLI staleness threshold |

To set up or refresh JCR data manually:

```bash
paper-search-mcp update-jcr
```

Runtime auto-update compares the local ShowJCR revision recorded in `version.json` with the upstream repository before updating. It does not add an MCP management tool; AI clients trigger it naturally by using JCR-backed lookup or filters when JCR is enabled.

To force a manual refresh:

```bash
paper-search-mcp update-jcr --force
```

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
|-- jcr/                  # Local ShowJCR update/load logic
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
