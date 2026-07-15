use std::time::Duration;

pub fn is_retryable_status(status: u16) -> bool {
    status == 408 || status == 429 || status >= 500
}

pub fn backoff_delay(attempt: u32, initial: Duration, maximum: Duration, jitter: f64) -> Duration {
    let exponent = attempt.min(20);
    let base = initial.mul_f64(f64::from(2_u32.saturating_pow(exponent)));
    let bounded = base.min(maximum);
    bounded.mul_f64(0.5 + jitter.clamp(0.0, 1.0) * 0.5)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn retry_statuses_are_narrow() {
        assert!(is_retryable_status(408));
        assert!(is_retryable_status(429));
        assert!(is_retryable_status(503));
        assert!(!is_retryable_status(401));
        assert!(!is_retryable_status(404));
    }

    #[test]
    fn backoff_is_bounded() {
        let delay = backoff_delay(10, Duration::from_secs(1), Duration::from_secs(30), 1.0);
        assert_eq!(delay, Duration::from_secs(30));
    }
}
