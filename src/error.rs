use thiserror::Error;

#[derive(Debug, Error)]
pub enum AppError {
    #[error("configuration error: {0}")]
    Config(String),
    #[error("invalid request: {0}")]
    InvalidRequest(String),
    #[error("upstream request failed: {0}")]
    Upstream(String),
    #[error("upstream response could not be parsed: {0}")]
    Parse(String),
    #[error("JCR data error: {0}")]
    Jcr(String),
    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),
    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),
}

pub type AppResult<T> = Result<T, AppError>;
