use crate::config::{Config, ProviderConfig};
use crate::infra::cache::{CachedResponse, ResponseCache};
use crate::infra::rate_limit::RateLimiter;
use crate::infra::retry::{backoff_delay, is_retryable_status};
use crate::model::ProviderName;
use futures::StreamExt;
use reqwest::header::{HeaderMap, RETRY_AFTER};
use std::sync::Arc;
use std::time::{Duration, SystemTime};
use thiserror::Error;
use tokio::time::sleep;
use url::Url;

const MAX_RESPONSE_BYTES: usize = 16 * 1024 * 1024;

#[derive(Debug, Clone)]
pub struct HttpResponse {
    pub body: Arc<str>,
    pub status_code: u16,
    pub request_url: String,
    pub cached: bool,
}

#[derive(Debug, Clone, Error)]
#[error("{message}")]
pub struct HttpError {
    pub status_code: Option<u16>,
    pub request_url: String,
    pub message: String,
}

#[derive(Debug, Clone)]
pub struct HttpClient {
    provider: ProviderName,
    client: reqwest::Client,
    rate_limiter: RateLimiter,
    cache: ResponseCache,
    max_retries: u32,
    initial_delay: Duration,
    max_delay: Duration,
}

impl HttpClient {
    pub fn new(
        provider: ProviderName,
        provider_config: &ProviderConfig,
        config: &Config,
    ) -> Result<Self, HttpError> {
        let mut builder = reqwest::Client::builder()
            .timeout(config.search.timeout)
            .redirect(reqwest::redirect::Policy::limited(5))
            .user_agent(concat!("paper-search-mcp/", env!("CARGO_PKG_VERSION")))
            .no_proxy();

        if provider_config.proxy_enabled {
            let proxy_url = config
                .proxy
                .socks5
                .as_ref()
                .or(config.proxy.https.as_ref())
                .or(config.proxy.http.as_ref());
            if let Some(proxy_url) = proxy_url {
                let proxy = reqwest::Proxy::all(proxy_url).map_err(|error| HttpError {
                    status_code: None,
                    request_url: String::new(),
                    message: format!("invalid proxy configuration: {error}"),
                })?;
                builder = builder.proxy(proxy);
            }
        }

        let client = builder.build().map_err(|error| HttpError {
            status_code: None,
            request_url: String::new(),
            message: format!("failed to construct HTTP client: {error}"),
        })?;

        Ok(Self {
            provider,
            client,
            rate_limiter: RateLimiter::per_second(provider_config.rate_limit_rps),
            cache: ResponseCache::new(config.search.cache_max_size, config.search.cache_ttl),
            max_retries: config.search.retry_max_retries,
            initial_delay: config.search.retry_initial_delay,
            max_delay: config.search.retry_max_delay,
        })
    }

    pub async fn get(
        &self,
        url: &str,
        params: &[(String, String)],
        headers: HeaderMap,
    ) -> Result<HttpResponse, HttpError> {
        let request_url = build_url(url, params)?;
        let cache_key = format!("{}:{request_url}", self.provider);
        if let Some(cached) = self.cache.get(&cache_key).await {
            return Ok(HttpResponse {
                body: cached.body.clone(),
                status_code: cached.status_code,
                request_url: cached.request_url.to_string(),
                cached: true,
            });
        }

        let mut last_error = None;
        for attempt in 0..=self.max_retries {
            let mut retry_after = None;
            self.rate_limiter.acquire().await;
            match self
                .client
                .get(request_url.clone())
                .headers(headers.clone())
                .send()
                .await
            {
                Ok(response) => {
                    let status = response.status().as_u16();
                    if response.status().is_success() {
                        let final_url = response.url().to_string();
                        let body = read_limited_body(response).await?;
                        let response = CachedResponse {
                            body: Arc::from(body),
                            status_code: status,
                            request_url: Arc::from(final_url.as_str()),
                        };
                        self.cache.insert(cache_key.clone(), response.clone()).await;
                        return Ok(HttpResponse {
                            body: response.body,
                            status_code: status,
                            request_url: final_url,
                            cached: false,
                        });
                    }

                    let error = HttpError {
                        status_code: Some(status),
                        request_url: request_url.to_string(),
                        message: format!("upstream returned HTTP {status}"),
                    };
                    if !is_retryable_status(status) || attempt == self.max_retries {
                        return Err(error);
                    }
                    retry_after = parse_retry_after(response.headers());
                    last_error = Some(error);
                }
                Err(error) => {
                    let request_error = HttpError {
                        status_code: error.status().map(|status| status.as_u16()),
                        request_url: request_url.to_string(),
                        message: if error.is_timeout() {
                            "upstream request timed out".into()
                        } else {
                            format!("upstream request failed: {error}")
                        },
                    };
                    if attempt == self.max_retries {
                        return Err(request_error);
                    }
                    last_error = Some(request_error);
                }
            }

            let delay = retry_after.unwrap_or_else(|| {
                backoff_delay(
                    attempt,
                    self.initial_delay,
                    self.max_delay,
                    rand::random::<f64>(),
                )
            });
            sleep(delay.min(self.max_delay)).await;
        }

        Err(last_error.unwrap_or_else(|| HttpError {
            status_code: None,
            request_url: request_url.to_string(),
            message: "upstream request failed".into(),
        }))
    }
}

fn parse_retry_after(headers: &HeaderMap) -> Option<Duration> {
    let value = headers.get(RETRY_AFTER)?.to_str().ok()?.trim();
    if let Ok(seconds) = value.parse::<u64>() {
        return Some(Duration::from_secs(seconds));
    }
    let retry_at = httpdate::parse_http_date(value).ok()?;
    retry_at.duration_since(SystemTime::now()).ok()
}

fn build_url(url: &str, params: &[(String, String)]) -> Result<Url, HttpError> {
    let mut parsed = Url::parse(url).map_err(|error| HttpError {
        status_code: None,
        request_url: url.to_owned(),
        message: format!("invalid upstream URL: {error}"),
    })?;
    {
        let mut query = parsed.query_pairs_mut();
        for (key, value) in params {
            query.append_pair(key, value);
        }
    }
    Ok(parsed)
}

async fn read_limited_body(response: reqwest::Response) -> Result<String, HttpError> {
    let request_url = response.url().to_string();
    let status_code = response.status().as_u16();
    let mut stream = response.bytes_stream();
    let mut body = Vec::new();
    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(|error| HttpError {
            status_code: Some(status_code),
            request_url: request_url.clone(),
            message: format!("failed while reading upstream response: {error}"),
        })?;
        if body.len().saturating_add(chunk.len()) > MAX_RESPONSE_BYTES {
            return Err(HttpError {
                status_code: Some(status_code),
                request_url,
                message: format!("upstream response exceeds {MAX_RESPONSE_BYTES} bytes"),
            });
        }
        body.extend_from_slice(&chunk);
    }
    String::from_utf8(body).map_err(|_| HttpError {
        status_code: Some(status_code),
        request_url,
        message: "upstream response is not valid UTF-8".into(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use reqwest::header::HeaderValue;

    #[test]
    fn parses_retry_after_seconds() {
        let mut headers = HeaderMap::new();
        headers.insert(RETRY_AFTER, HeaderValue::from_static("12"));
        assert_eq!(parse_retry_after(&headers), Some(Duration::from_secs(12)));
    }

    #[test]
    fn rejects_invalid_retry_after() {
        let mut headers = HeaderMap::new();
        headers.insert(RETRY_AFTER, HeaderValue::from_static("not-a-date"));
        assert_eq!(parse_retry_after(&headers), None);
    }
}
