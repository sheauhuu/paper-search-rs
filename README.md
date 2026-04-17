# paper-search-mcp

A lightweight Python MCP (Model Context Protocol) server focused on academic paper search. Search-only — no PDF download or reading (those are handled by Zotero / zotero-mcp).

## Features

- **Multi-platform search** — arXiv, Semantic Scholar, Google Scholar, CrossRef, PubMed, Scopus, bioRxiv, medRxiv, Web of Science
- **Concurrent async** — `asyncio.gather` with configurable concurrency limit
- **Config-driven** — platforms, rate limits, proxy, retry all via `config.yaml`
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

### Custom config

```bash
paper-search-mcp -c /path/to/config.yaml
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

With a custom config path:

```json
{
  "mcpServers": {
    "paper-search": {
      "command": "paper-search-mcp",
      "args": ["-c", "/path/to/config.yaml"]
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
| `platforms` | string[] | No | config default | Platform names to search |
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
1. Resolve target platforms (argument > config default)
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

Copy `config.example.yaml` to `config.yaml` and adjust:

```yaml
search:
  default_platforms:
    - arxiv
    - semantic_scholar
    - google_scholar
    - crossref
  max_results_per_platform: 10
  max_concurrent_searches: 5
  timeout_seconds: 30

platforms:
  arxiv:
    enabled: true
    max_results: 50
    rate_limit_rps: 0.33
  google_scholar:
    enabled: true
    max_results: 20
    rate_limit_rps: 0.5
    proxy: true                # needs proxy to access
  semantic_scholar:
    enabled: true
    max_results: 100
    rate_limit_rps: 3.0
    api_key: ${SEMANTIC_SCHOLAR_API_KEY:}
  crossref:
    enabled: true
    max_results: 100
    rate_limit_rps: 3.0
    mailto: ${CROSSREF_MAILTO:}
  pubmed:
    enabled: false
    api_key: ${PUBMED_API_KEY:}
  scopus:
    enabled: false
    api_key: ${SCOPUS_API_KEY:}
  biorxiv:
    enabled: false
    rate_limit_rps: 1.0
  medrxiv:
    enabled: false
    rate_limit_rps: 1.0
  webofscience:
    enabled: false
    api_key: ${WOS_API_KEY:}
    rate_limit_rps: 5.0
    max_results: 50

proxy:
  http: ${HTTP_PROXY:http://127.0.0.1:7890}
  https: ${HTTPS_PROXY:http://127.0.0.1:7890}
  socks5: ${SOCKS_PROXY:}

cache:
  max_size: 100
  ttl_seconds: 3600

retry:
  max_retries: 3
  initial_delay_seconds: 1.0
  max_delay_seconds: 30.0
```

### Environment variables

Config values support `${VAR}` and `${VAR:default}` interpolation:

| Variable | Used by |
|----------|---------|
| `SEMANTIC_SCHOLAR_API_KEY` | Semantic Scholar (optional, higher rate limit) |
| `CROSSREF_MAILTO` | CrossRef polite pool (optional, faster) |
| `PUBMED_API_KEY` | PubMed (required if enabled) |
| `SCOPUS_API_KEY` | Scopus (required if enabled) |
| `WOS_API_KEY` | Web of Science Starter (required if enabled) |
| `HTTP_PROXY` / `HTTPS_PROXY` / `SOCKS_PROXY` | Proxy settings |

## Project Structure

```
src/paper_search_mcp/
├── __init__.py
├── __main__.py           # FastMCP entry + CLI (typer)
├── config.py             # Config loader (YAML + env var interpolation)
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
