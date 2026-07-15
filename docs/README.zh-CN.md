# paper-search-rs 中文文档

`paper-search-rs` 是使用 Rust 完全重写的论文元数据搜索 MCP 服务，面向 MCP
`2025-11-25` 规范，只通过 stdio 运行，并返回由 JSON Schema 定义的结构化结果。

旧 Python 实现保存在 `v0` 分支。当前不负责 PDF 下载、全文阅读、RAG 或文献管理。

## 支持的平台

- arXiv
- Semantic Scholar
- Scopus
- Web of Science

默认只启用 `arxiv,semantic_scholar`。Scopus 和 Web of Science 需要 API key，并且必须通过
`PAPER_SEARCH_DEFAULT_PLATFORMS` 显式启用。

## 构建和安装

项目固定使用 Rust `1.95.0`：

```bash
cargo build --release --locked
./target/release/paper-search-rs --version
```

也可以把当前 checkout 安装到 Cargo 的 binary 目录：

```bash
cargo install --path . --locked
```

原生二进制也可以通过 npm 和 PyPI 分发，用户无需在本机编译 Rust。

package 发布后，可以用下面任一命令运行同一个原生 stdio 服务：

```bash
npx --yes paper-search-rs
uvx paper-search-rs
```

两种方式都会选择预编译二进制，不下载源码，也不要求用户安装 Rust 工具链。

## MCP 客户端配置

使用原生二进制的绝对路径：

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

通过 npm package 配置：

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

通过 uvx 和 PyPI wheel 配置：

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

启用 Scopus、WoS 和 JCR：

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

服务只支持 stdio。日志只写入 stderr，不会污染 MCP stdout。

## MCP 工具

### `paper_search`

该工具始终注册。

| 参数 | 类型 | 必选 | 默认值 | 说明 |
|---|---|---:|---|---|
| `query` | string | 是 | - | 1-500 字符的检索词 |
| `platforms` | string[] | 否 | 已启用平台 | 指定本次搜索平台 |
| `max_results` | integer | 否 | `10` | 每个平台结果上限，1-100 |
| `year_from` / `year_to` | integer | 否 | - | 包含边界的年份范围 |
| `sort_by` | string | 否 | `relevance` | `relevance`、`date`、`citations` |
| `author` | string | 否 | - | 作者过滤 |
| `journal` | string | 否 | - | 期刊/source 过滤 |
| `min_citations` | integer | 否 | - | 最低引用数 |
| `min_if` | number | 否 | - | 最低影响因子 |
| `jcr_quartile` | string | 否 | - | 如 `Q1,Q2` |
| `cas_quartile` | string | 否 | - | 如 `1,2` |
| `ccf_rank` | string | 否 | - | 如 `A,B` |
| `exclude_warning` | boolean | 否 | `false` | 排除预警期刊 |
| `wos_options` | object | 否 | - | WoS 的 `doi`、`issn`、`document_type`、`page` |

返回值以 `structuredContent` 为正式结果，同时提供内容相同的 JSON `TextContent` 兼容块。
结果 envelope 包含 `papers`、`failures`、可选 `diagnostics` 和可选全局 `error`。部分平台失败不会丢弃
其他平台结果；全部平台失败时设置 MCP `isError=true`。

### `jcr_lookup`

只有 `PAPER_SEARCH_JCR_ENABLED=true` 时注册。按期刊名、ISSN 或两者查询影响因子、JCR 分区、
中科院分区、CCF 等级和预警信息。

```json
{
  "journal": "Nature"
}
```

## 环境变量

项目只读取环境变量。非法值会让进程启动失败，并在 stderr 输出不含密钥的错误信息。

### 核心设置

| 变量 | 默认值 | 说明 |
|---|---|---|
| `PAPER_SEARCH_DEFAULT_PLATFORMS` | `arxiv,semantic_scholar` | 唯一的平台启用开关 |
| `PAPER_SEARCH_MAX_RESULTS_PER_PLATFORM` | `10` | 平台默认结果上限 |
| `PAPER_SEARCH_MAX_CONCURRENT_SEARCHES` | `5` | 并发平台数 |
| `PAPER_SEARCH_TIMEOUT_SECONDS` | `30` | 上游请求超时 |
| `PAPER_SEARCH_CACHE_MAX_SIZE` | `100` | 成功 GET 缓存容量 |
| `PAPER_SEARCH_CACHE_TTL_SECONDS` | `3600` | 缓存 TTL |
| `PAPER_SEARCH_RETRY_MAX_RETRIES` | `3` | 重试次数 |
| `PAPER_SEARCH_RETRY_INITIAL_DELAY_SECONDS` | `1.0` | 初始退避 |
| `PAPER_SEARCH_RETRY_MAX_DELAY_SECONDS` | `30.0` | 最大退避/Retry-After 等待 |
| `PAPER_SEARCH_DEBUG` | `false` | 返回脱敏的平台诊断信息 |

API key 不会自动启用平台。支持的平台值只有 `arxiv`、`semantic_scholar`、`scopus`、
`webofscience`。

平台覆盖配置格式为 `PAPER_SEARCH_PLATFORM_<PLATFORM>_<FIELD>`，支持：

- `..._MAX_RESULTS`
- `..._RATE_LIMIT_RPS`
- `..._PROXY`

凭证变量：

| 变量 | 要求 |
|---|---|
| `SEMANTIC_SCHOLAR_API_KEY` | 可选，可提高配额 |
| `SCOPUS_API_KEY` | 启用 Scopus 时必需 |
| `WOS_API_KEY` | 启用 WoS 时必需 |

代理地址使用 `HTTP_PROXY`、`HTTPS_PROXY`、`SOCKS_PROXY`。搜索平台只有在对应
`..._PROXY=true` 时使用代理；JCR 原生更新直接使用全局代理设置。

### JCR

| 变量 | 默认值 | 说明 |
|---|---|---|
| `PAPER_SEARCH_JCR_ENABLED` | `false` | 启用指标补充、筛选和 `jcr_lookup` |
| `PAPER_SEARCH_JCR_DATA_DIR` | `~/.paper-search-rs/jcr` | 本地数据目录 |
| `PAPER_SEARCH_JCR_AUTO_UPDATE_DAYS` | `7` | revision 检查间隔；`0` 禁止自动下载和检查 |
| `PAPER_SEARCH_JCR_MAX_AGE_DAYS` | `30` | 手动更新的新鲜度阈值 |

手动更新：

```bash
paper-search-rs update-jcr
paper-search-rs update-jcr --force
```

Rust 版本不调用系统 Git。它通过 HTTPS 下载指定 ShowJCR revision，在 staging 目录解包并验证索引，
最后原子发布；更新失败时继续保留旧数据。

## 开发验证

```bash
cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test --all-targets --all-features
cargo build --release --locked
npm --prefix npm test
node scripts/smoke-npm-local.mjs
scripts/smoke-uvx-local.sh
```

可选公网 smoke：

```bash
cargo test --test live_smoke -- --ignored --nocapture
```

原生目标为 macOS arm64/x86_64、Linux x86_64/arm64 和 Windows x86_64。
