use crate::config::Config;
use crate::error::{AppError, AppResult};
use crate::jcr::service::JcrService;
use crate::model::{
    PaperSearchInput, PaperSearchResult, ProviderDiagnostics, ProviderFailure, ProviderName,
};
use crate::providers::Provider;
use crate::providers::arxiv::ArxivProvider;
use crate::providers::scopus::ScopusProvider;
use crate::providers::semantic_scholar::SemanticScholarProvider;
use crate::providers::web_of_science::WebOfScienceProvider;
use crate::search::dedup::deduplicate;
use crate::search::filter::{apply_filters, sort_papers, validate_filters};
use futures::future::join_all;
use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use tokio::sync::Semaphore;

#[derive(Debug, Clone)]
pub struct SearchOutcome {
    pub result: PaperSearchResult,
    pub all_providers_failed: bool,
}

#[derive(Clone)]
pub struct SearchService {
    config: Arc<Config>,
    providers: Arc<HashMap<ProviderName, Arc<dyn Provider>>>,
    jcr: JcrService,
}

impl std::fmt::Debug for SearchService {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("SearchService")
            .field("enabled_platforms", &self.config.search.default_platforms)
            .finish_non_exhaustive()
    }
}

impl SearchService {
    pub fn new(config: Arc<Config>) -> AppResult<Self> {
        let providers: HashMap<ProviderName, Arc<dyn Provider>> = HashMap::from([
            (
                ProviderName::Arxiv,
                Arc::new(ArxivProvider::new(&config).map_err(provider_init_error)?)
                    as Arc<dyn Provider>,
            ),
            (
                ProviderName::SemanticScholar,
                Arc::new(SemanticScholarProvider::new(&config).map_err(provider_init_error)?)
                    as Arc<dyn Provider>,
            ),
            (
                ProviderName::Scopus,
                Arc::new(ScopusProvider::new(&config).map_err(provider_init_error)?)
                    as Arc<dyn Provider>,
            ),
            (
                ProviderName::Webofscience,
                Arc::new(WebOfScienceProvider::new(&config).map_err(provider_init_error)?)
                    as Arc<dyn Provider>,
            ),
        ]);
        Ok(Self {
            jcr: JcrService::new(config.clone()),
            config,
            providers: Arc::new(providers),
        })
    }

    pub fn jcr(&self) -> &JcrService {
        &self.jcr
    }

    pub async fn search(&self, mut input: PaperSearchInput) -> AppResult<SearchOutcome> {
        input.query = input.query.trim().to_owned();
        if input.query.is_empty() || input.query.chars().count() > 500 {
            return Err(AppError::InvalidRequest(
                "query must contain between 1 and 500 characters".into(),
            ));
        }
        if !(1..=100).contains(&input.max_results) {
            return Err(AppError::InvalidRequest(
                "max_results must be between 1 and 100".into(),
            ));
        }
        validate_filters(&input)?;
        let targets = self.resolve_targets(&input)?;
        let semaphore = Arc::new(Semaphore::new(self.config.search.max_concurrent_searches));
        let calls = targets.iter().copied().map(|target| {
            let provider = self
                .providers
                .get(&target)
                .expect("provider registry is complete")
                .clone();
            let semaphore = semaphore.clone();
            let input = input.clone();
            async move {
                let permit = semaphore.acquire_owned().await;
                let response = match permit {
                    Ok(_permit) => provider.search(&input).await,
                    Err(_) => unreachable!("search semaphore remains alive during fan-out"),
                };
                (target, response)
            }
        });

        let mut papers = Vec::new();
        let mut failures = Vec::new();
        let mut diagnostics = Vec::new();
        let mut completed = 0_usize;
        for (platform, response) in join_all(calls).await {
            match response {
                Ok(response) => {
                    completed += 1;
                    let result_count = response.papers.len();
                    papers.extend(response.papers);
                    diagnostics.push(ProviderDiagnostics {
                        platform,
                        enabled: true,
                        request_url: response.request_url,
                        status_code: response.status_code,
                        result_count: Some(result_count),
                        cached: Some(response.cached),
                        message: response.message,
                    });
                }
                Err(error) => {
                    diagnostics.push(ProviderDiagnostics {
                        platform,
                        enabled: true,
                        request_url: error.request_url.clone(),
                        status_code: error.status_code,
                        result_count: None,
                        cached: None,
                        message: Some(error.message.clone()),
                    });
                    failures.push(ProviderFailure {
                        platform,
                        code: error.code,
                        message: error.message,
                    });
                }
            }
        }

        self.jcr.enrich(&mut papers).await;
        papers = apply_filters(papers, &input);
        papers = deduplicate(papers);
        sort_papers(&mut papers, input.sort_by);
        let all_providers_failed = completed == 0 && !failures.is_empty();
        Ok(SearchOutcome {
            result: PaperSearchResult {
                papers,
                failures,
                diagnostics: self.config.search.debug.then_some(diagnostics),
                error: None,
            },
            all_providers_failed,
        })
    }

    fn resolve_targets(&self, input: &PaperSearchInput) -> AppResult<Vec<ProviderName>> {
        let requested = input
            .platforms
            .clone()
            .unwrap_or_else(|| self.config.search.default_platforms.clone());
        if requested.is_empty() {
            return Err(AppError::InvalidRequest(
                "no search platforms are enabled".into(),
            ));
        }
        let enabled = self
            .config
            .search
            .default_platforms
            .iter()
            .copied()
            .collect::<HashSet<_>>();
        let mut seen = HashSet::new();
        let mut targets = Vec::new();
        for platform in requested {
            if !enabled.contains(&platform) {
                return Err(AppError::InvalidRequest(format!(
                    "platform {platform} is not enabled by PAPER_SEARCH_DEFAULT_PLATFORMS"
                )));
            }
            if seen.insert(platform) {
                targets.push(platform);
            }
        }
        if input.wos_options.is_some() && !targets.contains(&ProviderName::Webofscience) {
            return Err(AppError::InvalidRequest(
                "wos_options requires webofscience in the resolved platforms".into(),
            ));
        }
        Ok(targets)
    }

    #[cfg(test)]
    fn with_providers(
        config: Arc<Config>,
        providers: HashMap<ProviderName, Arc<dyn Provider>>,
    ) -> Self {
        Self {
            jcr: JcrService::new(config.clone()),
            config,
            providers: Arc::new(providers),
        }
    }
}

fn provider_init_error(error: crate::providers::ProviderError) -> AppError {
    AppError::Config(format!("could not initialize provider: {}", error.message))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{Paper, ProviderName};
    use crate::providers::{ProviderError, ProviderSearchResult};
    use async_trait::async_trait;

    #[derive(Debug)]
    struct FakeProvider {
        name: ProviderName,
        result: Result<Vec<Paper>, ProviderError>,
    }

    #[async_trait]
    impl Provider for FakeProvider {
        fn name(&self) -> ProviderName {
            self.name
        }

        async fn search(
            &self,
            _input: &PaperSearchInput,
        ) -> Result<ProviderSearchResult, ProviderError> {
            self.result.clone().map(|papers| ProviderSearchResult {
                papers,
                status_code: Some(200),
                request_url: Some("https://example.test/search".into()),
                cached: false,
                message: None,
            })
        }
    }

    #[test]
    fn default_provider_enum_has_only_first_release_sources() {
        assert_eq!(ProviderName::ALL.len(), 4);
    }

    #[tokio::test]
    async fn preserves_partial_results() {
        let service = fake_service(false);
        let outcome = service.search(search_input()).await.unwrap();
        assert!(!outcome.all_providers_failed);
        assert_eq!(outcome.result.papers.len(), 1);
        assert_eq!(outcome.result.failures.len(), 1);
    }

    #[tokio::test]
    async fn reports_total_provider_failure() {
        let service = fake_service(true);
        let outcome = service.search(search_input()).await.unwrap();
        assert!(outcome.all_providers_failed);
        assert!(outcome.result.papers.is_empty());
        assert_eq!(outcome.result.failures.len(), 2);
    }

    fn fake_service(all_fail: bool) -> SearchService {
        let mut config = Config::from_env().unwrap();
        config.search.default_platforms = vec![ProviderName::Arxiv, ProviderName::SemanticScholar];
        config.jcr.enabled = false;
        let success = Paper {
            paper_id: "1".into(),
            title: "Paper".into(),
            source: ProviderName::Arxiv,
            sources: vec![ProviderName::Arxiv],
            ..Paper::default()
        };
        let failure = ProviderError {
            code: "network_error".into(),
            message: "network unavailable".into(),
            status_code: None,
            request_url: None,
        };
        let providers: HashMap<ProviderName, Arc<dyn Provider>> = HashMap::from([
            (
                ProviderName::Arxiv,
                Arc::new(FakeProvider {
                    name: ProviderName::Arxiv,
                    result: if all_fail {
                        Err(failure.clone())
                    } else {
                        Ok(vec![success])
                    },
                }) as Arc<dyn Provider>,
            ),
            (
                ProviderName::SemanticScholar,
                Arc::new(FakeProvider {
                    name: ProviderName::SemanticScholar,
                    result: Err(failure),
                }) as Arc<dyn Provider>,
            ),
        ]);
        SearchService::with_providers(Arc::new(config), providers)
    }

    fn search_input() -> PaperSearchInput {
        serde_json::from_value(serde_json::json!({"query": "rust"})).unwrap()
    }
}
