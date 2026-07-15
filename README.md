# paper-search-rs

A native Rust MCP server for academic paper metadata search. It targets MCP `2025-11-25`, runs over
stdio, and returns schema-defined structured results.

The Python implementation is preserved on the `v0` branch. PDF downloading, full-text reading, RAG,
and reference management are intentionally out of scope.

## Features

- Four providers: arXiv, Semantic Scholar, Scopus, and Web of Science
- Bounded async fan-out with provider failure isolation
- Typed `inputSchema`, `outputSchema`, and `structuredContent`
- JSON `TextContent` compatibility copy for every tool result
- DOI/title deduplication, sorting, and normalized post-search filters
- Rate limiting, retry/backoff, caching, timeouts, and HTTP/HTTPS/SOCKS proxy support
- JCR/Impact Factor, CAS quartile, CCF rank, and warning-list enrichment
- Native ShowJCR updates without a system `git` or SQLite dependency

## Build

Requires Rust `1.95.0` (pinned in `rust-toolchain.toml`).

```bash
cargo build --release --locked
./target/release/paper-search-rs --version
```

To install the current checkout into Cargo's binary directory:

```bash
cargo install --path . --locked
```

The native binary can also be distributed through npm and PyPI without compiling Rust locally.

After the packages are published, run the same native stdio server through either package manager:

```bash
npx --yes paper-search-rs
uvx paper-search-rs
```

Both commands select a prebuilt binary. They do not download source code or require a Rust
toolchain on the user's machine.

## MCP Client Configuration

The server supports stdio only. Use an absolute binary path:

```json
{
  "mcpServers": {
    "paper-search": {
      "command": "/absolute/path/to/paper-search-rs",
      "env": {
        "PAPER_SEARCH_DEFAULT_PLATFORMS": "arxiv,semantic_scholar"
      }
    }
  }
}
```

Using the npm package:

```json
{
  "mcpServers": {
    "paper-search": {
      "command": "npx",
      "args": ["--yes", "paper-search-rs"],
      "env": {
        "PAPER_SEARCH_DEFAULT_PLATFORMS": "arxiv,semantic_scholar"
      }
    }
  }
}
```

Using the PyPI wheel through uvx:

```json
{
  "mcpServers": {
    "paper-search": {
      "command": "uvx",
      "args": ["paper-search-rs"],
      "env": {
        "PAPER_SEARCH_DEFAULT_PLATFORMS": "arxiv,semantic_scholar"
      }
    }
  }
}
```

Example with credentialed providers and JCR:

```json
{
  "mcpServers": {
    "paper-search": {
      "command": "/absolute/path/to/paper-search-rs",
      "env": {
        "PAPER_SEARCH_DEFAULT_PLATFORMS": "arxiv,semantic_scholar,scopus,webofscience",
        "SCOPUS_API_KEY": "your-scopus-key",
        "WOS_API_KEY": "your-wos-key",
        "PAPER_SEARCH_JCR_ENABLED": "true"
      }
    }
  }
}
```

## MCP Tools

### `paper_search`

Always registered. If `platforms` is omitted, all providers listed in
`PAPER_SEARCH_DEFAULT_PLATFORMS` are searched.

| Parameter | Type | Required | Default | Description |
|---|---|---:|---|---|
| `query` | string | yes | - | Search query, 1-500 characters |
| `platforms` | string[] | no | enabled defaults | Target enabled providers |
| `max_results` | integer | no | `10` | Result cap per provider, 1-100 |
| `year_from` / `year_to` | integer | no | - | Inclusive publication years |
| `sort_by` | string | no | `relevance` | `relevance`, `date`, or `citations` |
| `author` | string | no | - | Normalized author filter |
| `journal` | string | no | - | Normalized journal/source filter |
| `min_citations` | integer | no | - | Minimum citation count |
| `min_if` | number | no | - | Minimum JCR Impact Factor |
| `jcr_quartile` | string | no | - | Comma-separated `Q1`-`Q4` |
| `cas_quartile` | string | no | - | Comma-separated `1`-`4` |
| `ccf_rank` | string | no | - | Comma-separated `A`-`C` |
| `exclude_warning` | boolean | no | `false` | Exclude warning-list journals |
| `wos_options` | object | no | - | WoS-only `doi`, `issn`, `document_type`, `page` |

Example:

```json
{
  "query": "construction safety",
  "platforms": ["webofscience"],
  "year_from": 2021,
  "year_to": 2025,
  "wos_options": {
    "document_type": "Article",
    "page": 1
  }
}
```

The result envelope contains `papers`, `failures`, optional `diagnostics`, and an optional global
`error`. Partial provider failures do not discard successful results. A complete provider failure
returns the same structured envelope with MCP `isError=true`.

### `jcr_lookup`

Registered only when `PAPER_SEARCH_JCR_ENABLED=true`. Accepts `journal`, `issn`, or both. Results
include Impact Factor, JCR rank/quartile/category, CAS fields, CCF fields, and warning status.

```json
{
  "journal": "Nature"
}
```

## Configuration

Configuration is environment-only. Invalid values fail startup with a redacted stderr message.

### Core

| Variable | Default | Description |
|---|---|---|
| `PAPER_SEARCH_DEFAULT_PLATFORMS` | `arxiv,semantic_scholar` | Sole provider enable switch |
| `PAPER_SEARCH_MAX_RESULTS_PER_PLATFORM` | `10` | Common per-provider fallback cap |
| `PAPER_SEARCH_MAX_CONCURRENT_SEARCHES` | `5` | Fan-out concurrency limit |
| `PAPER_SEARCH_TIMEOUT_SECONDS` | `30` | Upstream request timeout |
| `PAPER_SEARCH_CACHE_MAX_SIZE` | `100` | Successful GET cache capacity |
| `PAPER_SEARCH_CACHE_TTL_SECONDS` | `3600` | Cache TTL |
| `PAPER_SEARCH_RETRY_MAX_RETRIES` | `3` | Retry count |
| `PAPER_SEARCH_RETRY_INITIAL_DELAY_SECONDS` | `1.0` | Initial backoff |
| `PAPER_SEARCH_RETRY_MAX_DELAY_SECONDS` | `30.0` | Maximum backoff/Retry-After wait |
| `PAPER_SEARCH_DEBUG` | `false` | Include redacted provider diagnostics |

`PAPER_SEARCH_DEFAULT_PLATFORMS` is explicit: configuring an API key does not silently enable its
provider. Supported values are `arxiv`, `semantic_scholar`, `scopus`, and `webofscience`.

### Provider settings

Per-provider overrides use `PAPER_SEARCH_PLATFORM_<PLATFORM>_<FIELD>`:

- `..._MAX_RESULTS`
- `..._RATE_LIMIT_RPS`
- `..._PROXY`

Credential variables:

| Variable | Requirement |
|---|---|
| `SEMANTIC_SCHOLAR_API_KEY` | optional; increases available quota |
| `SCOPUS_API_KEY` | required when Scopus is enabled |
| `WOS_API_KEY` | required when Web of Science is enabled |

Proxy URLs are read from `HTTP_PROXY`, `HTTPS_PROXY`, and `SOCKS_PROXY`. A search provider uses the
configured proxy only when its `..._PROXY=true`; native JCR updates use the global proxy settings.

### JCR

| Variable | Default | Description |
|---|---|---|
| `PAPER_SEARCH_JCR_ENABLED` | `false` | Enable enrichment, filters, and `jcr_lookup` |
| `PAPER_SEARCH_JCR_DATA_DIR` | `~/.paper-search-rs/jcr` | Local data root |
| `PAPER_SEARCH_JCR_AUTO_UPDATE_DAYS` | `7` | Runtime revision-check interval; `0` disables auto download/check |
| `PAPER_SEARCH_JCR_MAX_AGE_DAYS` | `30` | Manual update freshness interval |

Manual update:

```bash
paper-search-rs update-jcr
paper-search-rs update-jcr --force
```

Updates fetch an exact ShowJCR revision over HTTPS, extract to a staging directory, validate the
index, and atomically publish it. Existing usable data remains active if an update fails.

## Development

```bash
cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test --all-targets --all-features
cargo build --release --locked
npm --prefix npm test
node scripts/smoke-npm-local.mjs
scripts/smoke-uvx-local.sh
```

The public-provider live smoke test is opt-in:

```bash
cargo test --test live_smoke -- --ignored --nocapture
```

## Native Targets

- `aarch64-apple-darwin`
- `x86_64-apple-darwin`
- `x86_64-unknown-linux-gnu`
- `aarch64-unknown-linux-gnu`
- `x86_64-pc-windows-msvc`

## License

MIT
