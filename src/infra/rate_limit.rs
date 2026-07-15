use std::sync::Arc;
use std::time::Duration;
use tokio::sync::Mutex;
use tokio::time::{Instant, sleep_until};

#[derive(Debug, Clone)]
pub struct RateLimiter {
    interval: Duration,
    next_allowed: Arc<Mutex<Instant>>,
}

impl RateLimiter {
    pub fn per_second(requests_per_second: f64) -> Self {
        Self {
            interval: Duration::from_secs_f64(1.0 / requests_per_second),
            next_allowed: Arc::new(Mutex::new(Instant::now())),
        }
    }

    pub async fn acquire(&self) {
        let mut next_allowed = self.next_allowed.lock().await;
        let now = Instant::now();
        if *next_allowed > now {
            sleep_until(*next_allowed).await;
        }
        *next_allowed = Instant::now() + self.interval;
    }
}
