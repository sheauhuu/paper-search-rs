use crate::config::Config;
use crate::error::{AppError, AppResult};
use crate::model::{
    JcrLookupInput, JcrLookupResult, PaperSearchInput, PaperSearchResult, ToolError,
};
use crate::search::service::SearchService;
use rmcp::handler::server::tool::ToolRouter;
use rmcp::handler::server::wrapper::{Json, Parameters};
use rmcp::{ServerHandler, ServiceExt, tool, tool_handler, tool_router};
use std::sync::Arc;

#[derive(Clone)]
pub struct PaperSearchServer {
    tool_router: ToolRouter<Self>,
    search: SearchService,
}

#[tool_router]
impl PaperSearchServer {
    pub fn new(config: Arc<Config>) -> AppResult<Self> {
        let search = SearchService::new(config.clone())?;
        let mut tool_router = Self::tool_router();
        if !config.jcr.enabled {
            tool_router.remove_route("jcr_lookup");
        }
        Ok(Self {
            tool_router,
            search,
        })
    }

    #[tool(
        name = "paper_search",
        description = "Search academic papers across the enabled arXiv, Semantic Scholar, Scopus, and Web of Science providers. Returns normalized structured paper records, provider failures, and optional diagnostics."
    )]
    async fn paper_search(
        &self,
        Parameters(input): Parameters<PaperSearchInput>,
    ) -> Result<Json<PaperSearchResult>, Json<PaperSearchResult>> {
        match self.search.search(input).await {
            Ok(outcome) if outcome.all_providers_failed => Err(Json(PaperSearchResult {
                error: Some(ToolError {
                    code: "all_providers_failed".into(),
                    message: "all targeted search providers failed".into(),
                }),
                ..outcome.result
            })),
            Ok(outcome) => Ok(Json(outcome.result)),
            Err(error) => Err(Json(PaperSearchResult {
                error: Some(tool_error(error)),
                ..PaperSearchResult::default()
            })),
        }
    }

    #[tool(
        name = "jcr_lookup",
        description = "Look up JCR, CAS, CCF, and warning-list journal metrics by journal name or ISSN. Available only when JCR is enabled."
    )]
    async fn jcr_lookup(
        &self,
        Parameters(input): Parameters<JcrLookupInput>,
    ) -> Result<Json<JcrLookupResult>, Json<JcrLookupResult>> {
        match self.search.jcr().lookup(&input).await {
            Ok(result) => Ok(Json(result)),
            Err(error) => Err(Json(JcrLookupResult {
                found: false,
                journal: input.journal,
                issn: input.issn,
                metrics: None,
                error: Some(tool_error(error)),
            })),
        }
    }
}

#[tool_handler(
    router = self.tool_router,
    name = "paper-search-mcp",
    version = "0.2.0",
    instructions = "Use paper_search for academic metadata search. Results are structured JSON and individual provider failures do not discard successful provider results."
)]
impl ServerHandler for PaperSearchServer {}

pub async fn run(config: Config) -> AppResult<()> {
    let server = PaperSearchServer::new(Arc::new(config))?;
    let service = match server.serve(rmcp::transport::stdio()).await {
        Ok(service) => service,
        Err(rmcp::service::ServerInitializeError::ConnectionClosed(_)) => return Ok(()),
        Err(error) => {
            return Err(AppError::Upstream(format!(
                "MCP stdio startup failed: {error}"
            )));
        }
    };
    service
        .waiting()
        .await
        .map_err(|error| AppError::Upstream(format!("MCP stdio service failed: {error}")))?;
    Ok(())
}

fn tool_error(error: AppError) -> ToolError {
    let code = match &error {
        AppError::InvalidRequest(_) => "invalid_request",
        AppError::Config(_) => "configuration_error",
        AppError::Jcr(_) => "jcr_unavailable",
        AppError::Upstream(_) => "upstream_error",
        AppError::Parse(_) => "parse_error",
        AppError::Io(_) => "io_error",
        AppError::Json(_) => "json_error",
    };
    ToolError {
        code: code.into(),
        message: error.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tool_router_can_hide_jcr() {
        let mut router = PaperSearchServer::tool_router();
        assert!(router.has_route("paper_search"));
        assert!(router.has_route("jcr_lookup"));
        router.remove_route("jcr_lookup");
        assert!(!router.has_route("jcr_lookup"));
    }

    #[test]
    fn handler_version_matches_package() {
        assert_eq!(env!("CARGO_PKG_VERSION"), "0.2.0");
    }
}
