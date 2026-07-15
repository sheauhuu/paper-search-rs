use crate::error::{AppError, AppResult};
use crate::model::{Paper, PaperSearchInput, SortBy};

pub fn validate_filters(input: &PaperSearchInput) -> AppResult<()> {
    if let (Some(from), Some(to)) = (input.year_from, input.year_to)
        && from > to
    {
        return Err(AppError::InvalidRequest(
            "year_from must not exceed year_to".into(),
        ));
    }
    validate_allowed(
        &input.jcr_quartile,
        &["Q1", "Q2", "Q3", "Q4"],
        "jcr_quartile",
    )?;
    validate_allowed(&input.cas_quartile, &["1", "2", "3", "4"], "cas_quartile")?;
    validate_allowed(&input.ccf_rank, &["A", "B", "C"], "ccf_rank")?;
    Ok(())
}

pub fn apply_filters(mut papers: Vec<Paper>, input: &PaperSearchInput) -> Vec<Paper> {
    if let Some(author) = normalized_filter(&input.author) {
        papers.retain(|paper| {
            paper
                .authors
                .iter()
                .any(|value| value.to_lowercase().contains(&author))
        });
    }
    if let Some(journal) = normalized_filter(&input.journal) {
        papers.retain(|paper| {
            paper
                .journal
                .as_deref()
                .is_some_and(|value| value.to_lowercase().contains(&journal))
        });
    }
    if let Some(minimum) = input.min_citations {
        papers.retain(|paper| paper.citations >= minimum);
    }
    if let Some(minimum) = input.min_if {
        papers.retain(|paper| {
            paper
                .journal_metrics
                .as_ref()
                .and_then(|metrics| metrics.impact_factor)
                .is_some_and(|value| value >= minimum)
        });
    }
    if let Some(allowed) = allowed_values(&input.jcr_quartile) {
        papers.retain(|paper| {
            paper
                .journal_metrics
                .as_ref()
                .and_then(|metrics| metrics.jcr_quartile.as_deref())
                .is_some_and(|value| allowed.iter().any(|item| item.eq_ignore_ascii_case(value)))
        });
    }
    if let Some(allowed) = allowed_values(&input.cas_quartile) {
        papers.retain(|paper| {
            paper
                .journal_metrics
                .as_ref()
                .and_then(|metrics| metrics.cas_quartile.as_deref())
                .is_some_and(|value| allowed.iter().any(|item| item == value))
        });
    }
    if let Some(allowed) = allowed_values(&input.ccf_rank) {
        papers.retain(|paper| {
            paper
                .journal_metrics
                .as_ref()
                .and_then(|metrics| metrics.ccf_rank.as_deref())
                .is_some_and(|value| allowed.iter().any(|item| item.eq_ignore_ascii_case(value)))
        });
    }
    if input.exclude_warning {
        papers.retain(|paper| {
            !paper
                .journal_metrics
                .as_ref()
                .is_some_and(|metrics| metrics.is_warning)
        });
    }
    papers
}

pub fn sort_papers(papers: &mut [Paper], sort_by: SortBy) {
    match sort_by {
        SortBy::Relevance => {}
        SortBy::Date => papers.sort_by(|left, right| {
            right
                .published_date
                .cmp(&left.published_date)
                .then_with(|| right.year.cmp(&left.year))
        }),
        SortBy::Citations => {
            papers.sort_by_key(|paper| std::cmp::Reverse(paper.citations));
        }
    }
}

fn validate_allowed(value: &Option<String>, allowed: &[&str], name: &str) -> AppResult<()> {
    let Some(values) = allowed_values(value) else {
        return Ok(());
    };
    if values.is_empty()
        || values
            .iter()
            .any(|value| !allowed.iter().any(|item| item.eq_ignore_ascii_case(value)))
    {
        return Err(AppError::InvalidRequest(format!(
            "{name} contains an unsupported value"
        )));
    }
    Ok(())
}

fn allowed_values(value: &Option<String>) -> Option<Vec<String>> {
    value.as_ref().map(|value| {
        value
            .split(',')
            .map(str::trim)
            .filter(|item| !item.is_empty())
            .map(str::to_owned)
            .collect()
    })
}

fn normalized_filter(value: &Option<String>) -> Option<String> {
    value
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_lowercase)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{JournalMetrics, ProviderName};

    fn input() -> PaperSearchInput {
        serde_json::from_value(serde_json::json!({"query": "rust"})).unwrap()
    }

    #[test]
    fn rejects_reversed_year_range() {
        let mut input = input();
        input.year_from = Some(2025);
        input.year_to = Some(2020);
        assert!(validate_filters(&input).is_err());
    }

    #[test]
    fn applies_metrics_filters() {
        let mut input = input();
        input.min_if = Some(5.0);
        let papers = vec![Paper {
            paper_id: "1".into(),
            title: "Paper".into(),
            source: ProviderName::Arxiv,
            journal_metrics: Some(JournalMetrics {
                impact_factor: Some(7.0),
                ..JournalMetrics::default()
            }),
            ..Paper::default()
        }];
        assert_eq!(apply_filters(papers, &input).len(), 1);
    }
}
