# paper-search-mcp 中文文档

这是 `paper-search-mcp` 的中文使用说明，适合本地调试、Cherry Studio / Claude Desktop 配置，以及常见问题排查。

## 1. 项目定位

`paper-search-mcp` 是一个专注于论文元数据检索的 MCP 服务，支持多平台统一搜索、排序、筛选和期刊指标补充。

当前不负责：

- PDF 下载
- 全文阅读
- 文献管理

这些能力建议交给 Zotero 或其他专门工具。

## 2. 支持的平台

- arXiv
- Semantic Scholar
- Google Scholar
- CrossRef
- PubMed
- Scopus
- bioRxiv
- medRxiv
- Web of Science

## 3. 安装

### pip

```bash
pip install -e .
```

### uv

```bash
uv sync
uv run paper-search-mcp
```

要求 Python `>=3.10`。

## 4. 启动方式

### stdio 模式

适合 MCP 客户端直接拉起：

```bash
paper-search-mcp
```

### SSE / streamable HTTP 模式

```bash
paper-search-mcp -t sse --port 8000
paper-search-mcp -t streamable-http --port 8000
```

## 5. 客户端配置示例

### 最小配置

推荐直接用 `uvx` 从 GitHub 安装并启动：

```json
{
  "mcpServers": {
    "paper-search": {
      "command": "uvx",
      "args": [
        "--native-tls",
        "--from",
        "git+https://github.com/sheauhuu/paper-search-mcp.git",
        "paper-search"
      ]
    }
  }
}
```

### 带环境变量的配置

```json
{
  "mcpServers": {
    "paper-search": {
      "command": "uvx",
      "args": [
        "--native-tls",
        "--from",
        "git+https://github.com/sheauhuu/paper-search-mcp.git",
        "paper-search"
      ],
      "env": {
        "PAPER_SEARCH_DEFAULT_PLATFORMS": "crossref,arxiv,webofscience",
        "CROSSREF_MAILTO": "you@example.com",
        "WOS_API_KEY": "your-wos-key"
      }
    }
  }
}
```

安装后也可以使用 `paper-search-mcp` 这个命令别名。stdio 是默认 transport，因此通常不需要额外写 `--transport stdio`。

## 6. 重要说明：不再支持 config.yaml

这个项目现在只支持环境变量配置。
服务不会把这些配置写入本地 config 文件。实际部署时，把配置放在 MCP 客户端的 `env`、shell 环境变量、容器环境变量或进程管理器里即可。

下面两种情况都会直接启动失败，而不是悄悄忽略：

- 传入 `-c` / `--config`
- 旧的 `config.yaml` 仍然放在历史自动加载位置

如果你之前依赖 `config.yaml`，需要把配置迁移到 `mcpServers.env` 或 shell 环境变量里。

## 7. 常用环境变量

### 平台启用

**`PAPER_SEARCH_DEFAULT_PLATFORMS`** 是唯一的启用开关。列出的平台即为启用；未列出的平台不会出现在 AI 看到的工具描述中。

```
PAPER_SEARCH_DEFAULT_PLATFORMS=arxiv,crossref,webofscience
```

### 核心搜索配置

| 变量 | 必选 | 默认值 | 说明 |
|------|------|--------|------|
| `PAPER_SEARCH_DEFAULT_PLATFORMS` | 否 | `arxiv,semantic_scholar,google_scholar,crossref` | 启用的平台列表（逗号分隔） |
| `PAPER_SEARCH_MAX_RESULTS_PER_PLATFORM` | 否 | `10` | 每个平台最大结果数 |
| `PAPER_SEARCH_MAX_CONCURRENT_SEARCHES` | 否 | `5` | 并发搜索数 |
| `PAPER_SEARCH_TIMEOUT_SECONDS` | 否 | `30` | 请求超时（秒） |
| `PAPER_SEARCH_CACHE_MAX_SIZE` | 否 | `100` | LRU 缓存大小 |
| `PAPER_SEARCH_CACHE_TTL_SECONDS` | 否 | `3600` | 缓存过期时间（秒） |
| `PAPER_SEARCH_RETRY_MAX_RETRIES` | 否 | `3` | 重试次数 |
| `PAPER_SEARCH_RETRY_INITIAL_DELAY_SECONDS` | 否 | `1.0` | 初始重试延迟（秒） |
| `PAPER_SEARCH_RETRY_MAX_DELAY_SECONDS` | 否 | `30.0` | 最大重试延迟（秒） |
| `PAPER_SEARCH_DEBUG` | 否 | `false` | 在工具输出里附带诊断信息 |

### 平台级配置

格式：`PAPER_SEARCH_PLATFORM_<PLATFORM>_<FIELD>`，均为可选。

| 字段 | 示例 | 说明 |
|------|------|------|
| `..._MAX_RESULTS` | `PAPER_SEARCH_PLATFORM_WEBOFSCIENCE_MAX_RESULTS=25` | 覆盖该平台的最大结果数 |
| `..._RATE_LIMIT_RPS` | `PAPER_SEARCH_PLATFORM_ARXIV_RATE_LIMIT_RPS=0.5` | 该平台的请求速率限制（次/秒） |
| `..._PROXY` | `PAPER_SEARCH_PLATFORM_GOOGLE_SCHOLAR_PROXY=true` | 为该平台启用代理 |

`<PLATFORM>` 名称：`ARXIV`、`SEMANTIC_SCHOLAR`、`GOOGLE_SCHOLAR`、`CROSSREF`、`PUBMED`、`SCOPUS`、`BIORXIV`、`MEDRXIV`、`WEBOFSCIENCE`。

### 凭证

仅当对应平台启用时才需要。

| 变量 | 何时必选 | 说明 |
|------|----------|------|
| `SEMANTIC_SCHOLAR_API_KEY` | 可选 | 提高速率限制 |
| `CROSSREF_MAILTO` | 可选 | 加入 CrossRef 礼貌池（更快响应） |
| `PUBMED_API_KEY` | PubMed 启用时 | PubMed API key |
| `SCOPUS_API_KEY` | Scopus 启用时 | Scopus API key |
| `WOS_API_KEY` | Web of Science 启用时 | WoS Starter API key |

### 代理

全部可选。全局生效，或通过 `..._PROXY=true` 为单个平台启用。

| 变量 | 说明 |
|------|------|
| `HTTP_PROXY` | HTTP 代理地址 |
| `HTTPS_PROXY` | HTTPS 代理地址 |
| `SOCKS_PROXY` | SOCKS5 代理地址 |

### JCR / 期刊指标

JCR 是独立于平台的功能模块。启用后，搜索结果会自动补充影响因子、JCR 分区、中科院分区、CCF 等级和预警名单。运行时自动更新默认开启：如果本地没有数据，第一次使用 JCR 时会自动下载 ShowJCR 数据；之后最多按配置间隔检查一次上游仓库。

| 变量 | 必选 | 默认值 | 说明 |
|------|------|--------|------|
| `PAPER_SEARCH_JCR_ENABLED` | 否 | `false` | 启用 JCR 补充和筛选 |
| `PAPER_SEARCH_JCR_DATA_DIR` | 否 | `~/.paper-search-mcp/jcr` | JCR 数据目录。不设置时默认使用 `~/.paper-search-mcp/jcr`。容器部署建议挂载到可写持久目录 |
| `PAPER_SEARCH_JCR_AUTO_UPDATE_DAYS` | 否 | `7` | 运行时检查上游仓库的间隔（天）。设为 `0` 可禁用运行时自动更新和首次自动下载 |
| `PAPER_SEARCH_JCR_MAX_AGE_DAYS` | 否 | `30` | 手动 `update-jcr` CLI 的过期阈值（天） |

手动初始化或刷新 JCR 数据：

```bash
paper-search-mcp update-jcr
```

强制刷新：

```bash
paper-search-mcp update-jcr --force
```

运行时自动更新会先比较 `version.json` 记录的本地 ShowJCR revision 和上游仓库 revision，只有上游变化时才更新。该方案不会新增 MCP 管理工具；AI 客户端在启用 JCR 后正常调用 lookup 或 JCR 过滤即可触发。

## 8. MCP 工具

工具是否暴露会跟随当前配置：

- `paper_search`：始终注册。
- `jcr_lookup`：仅当 `PAPER_SEARCH_JCR_ENABLED=true` 时注册。

### `paper_search`

跨平台搜索论文元数据。常用参数：

| 参数 | 类型 | 必选 | 默认值 | 说明 |
|------|------|------|--------|------|
| `query` | string | 是 | - | 搜索关键词 |
| `platforms` | string[] | 否 | 环境变量默认平台 | 指定搜索平台；为空时搜索所有启用平台 |
| `max_results` | int | 否 | `10` | 每个平台最大结果数 |
| `year_from` / `year_to` | int | 否 | - | 年份范围 |
| `author` | string | 否 | - | 作者名过滤 |
| `sort_by` | string | 否 | `relevance` | `relevance`、`date` 或 `citations` |
| `journal` | string | 否 | - | 期刊/source 名称过滤 |
| `min_citations` | int | 否 | - | 最低引用数 |
| `min_if` | float | 否 | - | 最低影响因子 |
| `jcr_quartile` | string | 否 | - | JCR 分区，例如 `Q1,Q2` |
| `cas_quartile` | string | 否 | - | 中科院分区，例如 `1,2` |
| `ccf_rank` | string | 否 | - | CCF 等级，例如 `A,B` |
| `exclude_warning` | bool | 否 | `false` | 排除预警期刊 |
| `wos_options` | object | 否 | - | Web of Science 原生选项：`doi`、`issn`、`document_type`、`page` |

### `jcr_lookup`

按期刊名或 ISSN 直接查询本地 JCR 指标。该工具只有在 `PAPER_SEARCH_JCR_ENABLED=true` 时才会出现在 MCP 工具列表中。

如果启用 JCR 且本地没有数据，第一次调用会自动下载 ShowJCR 数据，除非设置了 `PAPER_SEARCH_JCR_AUTO_UPDATE_DAYS=0`。

| 参数 | 类型 | 必选 | 默认值 | 说明 |
|------|------|------|--------|------|
| `journal` | string | 否 | - | 期刊名，大小写不敏感 |
| `issn` | string | 否 | - | 期刊 ISSN |

`journal` 和 `issn` 至少需要提供一个。

```json
{
  "journal": "Nature"
}
```

返回结果通常包含影响因子、JCR 分区、JCR 排名/类别、中科院分区、CCF 等级和预警名单状态。

## 9. 常见查询示例

### 跨平台普通检索

```json
{
  "query": "large language model safety",
  "platforms": ["crossref", "arxiv"],
  "max_results": 10,
  "sort_by": "date"
}
```

### WoS 检索

```json
{
  "query": "construction safety",
  "platforms": ["webofscience"],
  "year_from": 2021,
  "year_to": 2025,
  "max_results": 15,
  "sort_by": "relevance"
}
```

### WoS 原生选项

```json
{
  "query": "machine learning",
  "platforms": ["webofscience"],
  "wos_options": {
    "document_type": "Article",
    "page": 2
  }
}
```

## 10. 调试建议

如果你在客户端里只看到 `No papers found.`，建议先打开：

```text
PAPER_SEARCH_DEBUG=true
```

这样工具返回中会附带：

- `platform=...`
- `request_url=...`
- `status=...`
- `error=...`
- `exception_type=...`

这对排查 WoS 的以下问题很有用：

- `WOS_API_KEY` 未配置
- `401 Unauthorized`
- `403 Forbidden`
- fallback 到其他 API 版本
- 网络或代理问题

## 11. Cherry Studio 使用建议

如果你在 Cherry Studio 中使用，优先检查：

1. `mcpServers` 里的 `env` 是否真的传进去了
2. `WOS_API_KEY` 是否配置在对应 server 的 `env` 中，而不是 shell 里
3. 是否还残留旧的 `config.yaml`
4. 是否开启了 `PAPER_SEARCH_DEBUG=true`

## 12. 文档关系

- 根目录 `README.md`：英文主文档，适合项目概览和仓库入口
- `docs/README.md`：文档索引
- `docs/README.zh-CN.md`：中文使用说明
