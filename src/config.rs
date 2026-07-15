use crate::error::{AppError, AppResult};
use crate::model::ProviderName;
use std::collections::HashMap;
use std::env;
use std::path::PathBuf;
use std::str::FromStr;
use std::time::Duration;

#[derive(Debug, Clone)]
pub struct SearchConfig {
    pub default_platforms: Vec<ProviderName>,
    pub max_results_per_platform: u32,
    pub max_concurrent_searches: usize,
    pub timeout: Duration,
    pub cache_max_size: u64,
    pub cache_ttl: Duration,
    pub retry_max_retries: u32,
    pub retry_initial_delay: Duration,
    pub retry_max_delay: Duration,
    pub debug: bool,
}

#[derive(Debug, Clone)]
pub struct ProviderConfig {
    pub api_key: Option<String>,
    pub max_results: u32,
    pub rate_limit_rps: f64,
    pub proxy_enabled: bool,
}

#[derive(Debug, Clone, Default)]
pub struct ProxyConfig {
    pub http: Option<String>,
    pub https: Option<String>,
    pub socks5: Option<String>,
}

#[derive(Debug, Clone)]
pub struct JcrConfig {
    pub enabled: bool,
    pub data_dir: PathBuf,
    pub auto_update_days: u64,
    pub max_age_days: u64,
}

#[derive(Debug, Clone)]
pub struct Config {
    pub search: SearchConfig,
    pub providers: HashMap<ProviderName, ProviderConfig>,
    pub proxy: ProxyConfig,
    pub jcr: JcrConfig,
}

impl Config {
    pub fn from_env() -> AppResult<Self> {
        let default_platforms =
            parse_platforms("PAPER_SEARCH_DEFAULT_PLATFORMS", "arxiv,semantic_scholar")?;
        let max_results_per_platform =
            parse_range::<u32>("PAPER_SEARCH_MAX_RESULTS_PER_PLATFORM", 10, 1, 100)?;
        let max_concurrent_searches =
            parse_range::<usize>("PAPER_SEARCH_MAX_CONCURRENT_SEARCHES", 5, 1, 64)?;
        let timeout_seconds = parse_range::<u64>("PAPER_SEARCH_TIMEOUT_SECONDS", 30, 1, 600)?;
        let cache_max_size = parse_range::<u64>("PAPER_SEARCH_CACHE_MAX_SIZE", 100, 1, 100_000)?;
        let cache_ttl_seconds =
            parse_range::<u64>("PAPER_SEARCH_CACHE_TTL_SECONDS", 3600, 1, 604_800)?;
        let retry_max_retries = parse_range::<u32>("PAPER_SEARCH_RETRY_MAX_RETRIES", 3, 0, 20)?;
        let retry_initial =
            parse_range::<f64>("PAPER_SEARCH_RETRY_INITIAL_DELAY_SECONDS", 1.0, 0.0, 300.0)?;
        let retry_max =
            parse_range::<f64>("PAPER_SEARCH_RETRY_MAX_DELAY_SECONDS", 30.0, 0.0, 3600.0)?;
        if retry_initial > retry_max {
            return Err(AppError::Config(
                "PAPER_SEARCH_RETRY_INITIAL_DELAY_SECONDS must not exceed PAPER_SEARCH_RETRY_MAX_DELAY_SECONDS"
                    .into(),
            ));
        }

        let debug = parse_bool("PAPER_SEARCH_DEBUG", false)?;
        let proxy = ProxyConfig {
            http: optional_env("HTTP_PROXY"),
            https: optional_env("HTTPS_PROXY"),
            socks5: optional_env("SOCKS_PROXY"),
        };
        validate_proxy(&proxy)?;

        let mut providers = HashMap::new();
        for name in ProviderName::ALL {
            let defaults = provider_defaults(name, max_results_per_platform);
            let prefix = format!(
                "PAPER_SEARCH_PLATFORM_{}",
                name.as_str().to_ascii_uppercase()
            );
            let api_key = match name {
                ProviderName::SemanticScholar => optional_env("SEMANTIC_SCHOLAR_API_KEY"),
                ProviderName::Scopus => optional_env("SCOPUS_API_KEY"),
                ProviderName::Webofscience => optional_env("WOS_API_KEY"),
                ProviderName::Arxiv => None,
            };
            providers.insert(
                name,
                ProviderConfig {
                    api_key,
                    max_results: parse_range(&format!("{prefix}_MAX_RESULTS"), defaults.0, 1, 200)?,
                    rate_limit_rps: parse_range(
                        &format!("{prefix}_RATE_LIMIT_RPS"),
                        defaults.1,
                        0.01,
                        1000.0,
                    )?,
                    proxy_enabled: parse_bool(&format!("{prefix}_PROXY"), false)?,
                },
            );
        }

        let data_dir = optional_env("PAPER_SEARCH_JCR_DATA_DIR")
            .map(PathBuf::from)
            .unwrap_or_else(default_jcr_data_dir);

        Ok(Self {
            search: SearchConfig {
                default_platforms,
                max_results_per_platform,
                max_concurrent_searches,
                timeout: Duration::from_secs(timeout_seconds),
                cache_max_size,
                cache_ttl: Duration::from_secs(cache_ttl_seconds),
                retry_max_retries,
                retry_initial_delay: Duration::from_secs_f64(retry_initial),
                retry_max_delay: Duration::from_secs_f64(retry_max),
                debug,
            },
            providers,
            proxy,
            jcr: JcrConfig {
                enabled: parse_bool("PAPER_SEARCH_JCR_ENABLED", false)?,
                data_dir,
                auto_update_days: parse_range("PAPER_SEARCH_JCR_AUTO_UPDATE_DAYS", 7, 0, 3650)?,
                max_age_days: parse_range("PAPER_SEARCH_JCR_MAX_AGE_DAYS", 30, 0, 3650)?,
            },
        })
    }

    pub fn provider(&self, name: ProviderName) -> &ProviderConfig {
        self.providers
            .get(&name)
            .expect("all provider configurations are initialized")
    }
}

fn provider_defaults(name: ProviderName, global_max: u32) -> (u32, f64) {
    match name {
        ProviderName::Arxiv => (50, 0.33),
        ProviderName::SemanticScholar => (100, 3.0),
        ProviderName::Scopus => (global_max, 2.0),
        ProviderName::Webofscience => (50, 5.0),
    }
}

fn parse_platforms(name: &str, default: &str) -> AppResult<Vec<ProviderName>> {
    let raw = env::var(name).unwrap_or_else(|_| default.to_owned());
    parse_platform_list(name, &raw)
}

fn parse_platform_list(name: &str, raw: &str) -> AppResult<Vec<ProviderName>> {
    let platforms = raw
        .split(',')
        .filter(|value| !value.trim().is_empty())
        .map(|value| ProviderName::from_str(value).map_err(AppError::Config))
        .collect::<AppResult<Vec<_>>>()?;
    if platforms.is_empty() {
        return Err(AppError::Config(format!(
            "{name} must enable at least one search platform"
        )));
    }
    Ok(platforms)
}

fn parse_bool(name: &str, default: bool) -> AppResult<bool> {
    let Some(value) = optional_env(name) else {
        return Ok(default);
    };
    match value.to_ascii_lowercase().as_str() {
        "1" | "true" | "yes" | "on" => Ok(true),
        "0" | "false" | "no" | "off" => Ok(false),
        _ => Err(AppError::Config(format!(
            "{name} must be a boolean (true/false)"
        ))),
    }
}

fn parse_range<T>(name: &str, default: T, minimum: T, maximum: T) -> AppResult<T>
where
    T: FromStr + PartialOrd + Copy + std::fmt::Display,
{
    let value = match optional_env(name) {
        Some(raw) => raw
            .parse::<T>()
            .map_err(|_| AppError::Config(format!("{name} has an invalid value")))?,
        None => default,
    };
    if value < minimum || value > maximum {
        return Err(AppError::Config(format!(
            "{name} must be between {minimum} and {maximum}"
        )));
    }
    Ok(value)
}

fn optional_env(name: &str) -> Option<String> {
    env::var(name)
        .ok()
        .map(|value| value.trim().to_owned())
        .filter(|value| !value.is_empty())
}

fn validate_proxy(proxy: &ProxyConfig) -> AppResult<()> {
    for (name, value) in [
        ("HTTP_PROXY", proxy.http.as_deref()),
        ("HTTPS_PROXY", proxy.https.as_deref()),
        ("SOCKS_PROXY", proxy.socks5.as_deref()),
    ] {
        if let Some(value) = value {
            url::Url::parse(value)
                .map_err(|_| AppError::Config(format!("{name} must be a valid proxy URL")))?;
        }
    }
    Ok(())
}

fn default_jcr_data_dir() -> PathBuf {
    dirs::home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".paper-search-rs")
        .join("jcr")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn provider_names_are_stable() {
        assert_eq!(ProviderName::Arxiv.to_string(), "arxiv");
        assert!(ProviderName::from_str("crossref").is_err());
    }

    #[test]
    fn rejects_empty_default_platform_list() {
        let error = parse_platform_list("PAPER_SEARCH_DEFAULT_PLATFORMS", " , ")
            .expect_err("an empty platform list must fail startup");
        assert!(
            error
                .to_string()
                .contains("PAPER_SEARCH_DEFAULT_PLATFORMS must enable at least one")
        );
    }
}
