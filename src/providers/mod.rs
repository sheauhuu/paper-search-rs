pub mod arxiv;
pub mod scopus;
pub mod semantic_scholar;
pub mod web_of_science;

use crate::error::AppError;
use crate::model::{Paper, PaperSearchInput, ProviderName};
use async_trait::async_trait;

#[derive(Debug, Clone)]
pub struct ProviderSearchResult {
    pub papers: Vec<Paper>,
    pub status_code: Option<u16>,
    pub request_url: Option<String>,
    pub cached: bool,
    pub message: Option<String>,
}

#[derive(Debug, Clone, thiserror::Error)]
#[error("{message}")]
pub struct ProviderError {
    pub code: String,
    pub message: String,
    pub status_code: Option<u16>,
    pub request_url: Option<String>,
}

impl From<crate::infra::http::HttpError> for ProviderError {
    fn from(error: crate::infra::http::HttpError) -> Self {
        Self {
            code: error.status_code.map_or_else(
                || "network_error".to_owned(),
                |status| format!("http_{status}"),
            ),
            message: error.message,
            status_code: error.status_code,
            request_url: Some(error.request_url),
        }
    }
}

impl From<AppError> for ProviderError {
    fn from(error: AppError) -> Self {
        Self {
            code: "parse_error".into(),
            message: error.to_string(),
            status_code: None,
            request_url: None,
        }
    }
}

#[async_trait]
pub trait Provider: Send + Sync {
    fn name(&self) -> ProviderName;

    async fn search(&self, input: &PaperSearchInput)
    -> Result<ProviderSearchResult, ProviderError>;
}
