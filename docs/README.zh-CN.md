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

### 带环境变量的配置

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

## 6. 重要说明：不再支持 config.yaml

这个项目现在只支持环境变量配置。

下面两种情况都会直接启动失败，而不是悄悄忽略：

- 传入 `-c` / `--config`
- 旧的 `config.yaml` 仍然放在历史自动加载位置

如果你之前依赖 `config.yaml`，需要把配置迁移到 `mcpServers.env` 或 shell 环境变量里。

## 7. 常用环境变量

### 核心搜索配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PAPER_SEARCH_DEFAULT_PLATFORMS` | `arxiv,semantic_scholar,google_scholar,crossref` | 默认搜索平台 |
| `PAPER_SEARCH_MAX_RESULTS_PER_PLATFORM` | `10` | 每个平台最大结果数 |
| `PAPER_SEARCH_MAX_CONCURRENT_SEARCHES` | `5` | 并发搜索数 |
| `PAPER_SEARCH_TIMEOUT_SECONDS` | `30` | 请求超时 |
| `PAPER_SEARCH_DEBUG` | `false` | 在工具输出里附带诊断信息 |

### 平台级配置

格式：`PAPER_SEARCH_PLATFORM_<PLATFORM>_<FIELD>`

示例：

- `PAPER_SEARCH_PLATFORM_ARXIV_RATE_LIMIT_RPS=0.5`
- `PAPER_SEARCH_PLATFORM_GOOGLE_SCHOLAR_PROXY=true`
- `PAPER_SEARCH_PLATFORM_WEBOFSCIENCE_MAX_RESULTS=25`

平台的启用/停用由 `PAPER_SEARCH_DEFAULT_PLATFORMS` 控制，列在其中的平台即为启用状态。

### 凭证相关

- `CROSSREF_MAILTO`
- `SEMANTIC_SCHOLAR_API_KEY`
- `PUBMED_API_KEY`
- `SCOPUS_API_KEY`
- `WOS_API_KEY`

### 代理相关

- `HTTP_PROXY`
- `HTTPS_PROXY`
- `SOCKS_PROXY`

### JCR 相关

- `PAPER_SEARCH_JCR_ENABLED`
- `PAPER_SEARCH_JCR_DATA_DIR`
- `PAPER_SEARCH_JCR_AUTO_UPDATE`
- `PAPER_SEARCH_JCR_MAX_AGE_DAYS`

## 8. 常见查询示例

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

## 9. 调试建议

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

## 10. Cherry Studio 使用建议

如果你在 Cherry Studio 中使用，优先检查：

1. `mcpServers` 里的 `env` 是否真的传进去了
2. `WOS_API_KEY` 是否配置在对应 server 的 `env` 中，而不是 shell 里
3. 是否还残留旧的 `config.yaml`
4. 是否开启了 `PAPER_SEARCH_DEBUG=true`

## 11. 文档关系

- 根目录 `README.md`：英文主文档，适合项目概览和仓库入口
- `docs/README.md`：文档索引
- `docs/README.zh-CN.md`：中文使用说明
