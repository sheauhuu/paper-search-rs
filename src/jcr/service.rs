use crate::config::Config;
use crate::error::{AppError, AppResult};
use crate::jcr::loader::load_jcr_index;
use crate::jcr::model::JcrIndex;
use crate::jcr::updater::{data_source_dir, ensure_current};
use crate::model::{JcrLookupInput, JcrLookupResult, Paper};
use std::sync::Arc;
use tokio::sync::{Mutex, RwLock};

#[derive(Debug, Clone)]
pub struct JcrService {
    config: Arc<Config>,
    index: Arc<RwLock<Option<Arc<JcrIndex>>>>,
    update_lock: Arc<Mutex<()>>,
}

impl JcrService {
    pub fn new(config: Arc<Config>) -> Self {
        Self {
            config,
            index: Arc::new(RwLock::new(None)),
            update_lock: Arc::new(Mutex::new(())),
        }
    }

    pub async fn enrich(&self, papers: &mut [Paper]) {
        let Some(index) = self.get_index().await else {
            return;
        };
        for paper in papers {
            let entry = index.lookup(
                paper.issn.as_deref().unwrap_or_default(),
                paper.journal.as_deref().unwrap_or_default(),
            );
            if let Some(entry) = entry {
                paper.journal_metrics = Some(entry.metrics.clone());
            }
        }
    }

    pub async fn lookup(&self, input: &JcrLookupInput) -> AppResult<JcrLookupResult> {
        let journal = input.journal.as_deref().map(str::trim).unwrap_or_default();
        let issn = input.issn.as_deref().map(str::trim).unwrap_or_default();
        if journal.is_empty() && issn.is_empty() {
            return Err(AppError::InvalidRequest(
                "provide at least one of journal or issn".into(),
            ));
        }
        let Some(index) = self.get_index().await else {
            return Err(AppError::Jcr(
                "JCR data is unavailable; run update-jcr or enable runtime updates".into(),
            ));
        };
        let entry = index.lookup(issn, journal);
        Ok(entry.map_or(
            JcrLookupResult {
                found: false,
                journal: (!journal.is_empty()).then(|| journal.to_owned()),
                issn: (!issn.is_empty()).then(|| issn.to_owned()),
                metrics: None,
                error: None,
            },
            |entry| JcrLookupResult {
                found: true,
                journal: Some(entry.journal.clone()),
                issn: Some(entry.issn.clone()),
                metrics: Some(entry.metrics.clone()),
                error: None,
            },
        ))
    }

    async fn get_index(&self) -> Option<Arc<JcrIndex>> {
        if !self.config.jcr.enabled {
            return None;
        }
        let _guard = self.update_lock.lock().await;
        let changed = match ensure_current(&self.config).await {
            Ok(changed) => changed,
            Err(error) => {
                tracing::warn!(%error, "[jcr] runtime update failed; using existing data");
                false
            }
        };
        if !changed && let Some(index) = self.index.read().await.clone() {
            return Some(index);
        }
        let source = data_source_dir(&self.config.jcr.data_dir)?;
        let loaded = tokio::task::spawn_blocking(move || load_jcr_index(&source))
            .await
            .map_err(|error| AppError::Jcr(format!("JCR load task failed: {error}")))
            .and_then(|result| result)
            .map(Arc::new);
        match loaded {
            Ok(index) => {
                *self.index.write().await = Some(index.clone());
                Some(index)
            }
            Err(error) => {
                tracing::warn!(%error, "[jcr] failed to load index");
                self.index.read().await.clone()
            }
        }
    }
}
