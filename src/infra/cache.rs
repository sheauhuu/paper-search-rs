use moka::future::Cache;
use std::sync::Arc;
use std::time::Duration;

#[derive(Debug, Clone)]
pub struct CachedResponse {
    pub body: Arc<str>,
    pub status_code: u16,
    pub request_url: Arc<str>,
}

#[derive(Clone)]
pub struct ResponseCache {
    inner: Cache<String, Arc<CachedResponse>>,
}

impl std::fmt::Debug for ResponseCache {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("ResponseCache")
            .finish_non_exhaustive()
    }
}

impl ResponseCache {
    pub fn new(max_capacity: u64, time_to_live: Duration) -> Self {
        Self {
            inner: Cache::builder()
                .max_capacity(max_capacity)
                .time_to_live(time_to_live)
                .build(),
        }
    }

    pub async fn get(&self, key: &str) -> Option<Arc<CachedResponse>> {
        self.inner.get(key).await
    }

    pub async fn insert(&self, key: String, value: CachedResponse) {
        self.inner.insert(key, Arc::new(value)).await;
    }
}
