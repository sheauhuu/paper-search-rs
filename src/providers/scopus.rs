use super::{Provider, ProviderError, ProviderSearchResult};
use crate::config::Config;
use crate::error::AppError;
use crate::infra::http::HttpClient;
use crate::model::{Paper, PaperSearchInput, ProviderName, SortBy};
use async_trait::async_trait;
use chrono::{DateTime, Datelike, NaiveDate, Utc};
use reqwest::header::{ACCEPT, HeaderMap, HeaderValue};
use serde::Deserialize;
use serde_json::Value;
use std::collections::BTreeMap;

const API_URL: &str = "https://api.elsevier.com/content/search/scopus";

#[derive(Debug)]
pub struct ScopusProvider {
    http: HttpClient,
    api_key: Option<String>,
    max_results: u32,
}

impl ScopusProvider {
    pub fn new(config: &Config) -> Result<Self, ProviderError> {
        let provider_config = config.provider(ProviderName::Scopus);
        Ok(Self {
            http: HttpClient::new(ProviderName::Scopus, provider_config, config)?,
            api_key: provider_config.api_key.clone(),
            max_results: provider_config.max_results,
        })
    }
}

#[async_trait]
impl Provider for ScopusProvider {
    fn name(&self) -> ProviderName {
        ProviderName::Scopus
    }

    async fn search(
        &self,
        input: &PaperSearchInput,
    ) -> Result<ProviderSearchResult, ProviderError> {
        let api_key = self.api_key.as_ref().ok_or_else(|| ProviderError {
            code: "missing_credentials".into(),
            message: "SCOPUS_API_KEY is required when Scopus is enabled".into(),
            status_code: None,
            request_url: None,
        })?;
        let mut query = input.query.clone();
        if let Some(from) = input.year_from {
            query.push_str(&format!(" AND PUBYEAR > {}", from.saturating_sub(1)));
        }
        if let Some(to) = input.year_to {
            query.push_str(&format!(" AND PUBYEAR < {}", to.saturating_add(1)));
        }
        let sort = match input.sort_by {
            SortBy::Relevance => "relevancy",
            SortBy::Date => "-coverDate",
            SortBy::Citations => "-citedby-count",
        };
        let params = vec![
            ("query".into(), query),
            (
                "count".into(),
                input.max_results.min(self.max_results).to_string(),
            ),
            ("sort".into(), sort.into()),
        ];
        let mut headers = HeaderMap::new();
        headers.insert(
            "x-els-apikey",
            HeaderValue::from_str(api_key).map_err(|_| ProviderError {
                code: "invalid_api_key".into(),
                message: "SCOPUS_API_KEY contains invalid header characters".into(),
                status_code: None,
                request_url: None,
            })?,
        );
        headers.insert(ACCEPT, HeaderValue::from_static("application/json"));
        let response = self.http.get(API_URL, &params, headers).await?;
        let (papers, skipped) = parse_payload(&response.body)?;

        Ok(ProviderSearchResult {
            papers,
            status_code: Some(response.status_code),
            request_url: Some(response.request_url),
            cached: response.cached,
            message: (skipped > 0).then(|| format!("skipped {skipped} malformed Scopus record(s)")),
        })
    }
}

#[derive(Debug, Deserialize)]
struct ScopusPayload {
    #[serde(rename = "search-results")]
    search_results: ScopusResults,
}

#[derive(Debug, Deserialize, Default)]
struct ScopusResults {
    #[serde(rename = "entry", default)]
    entries: Vec<Value>,
}

#[derive(Debug, Deserialize)]
struct ScopusEntry {
    #[serde(rename = "dc:identifier", default)]
    identifier: String,
    #[serde(rename = "dc:title", default)]
    title: String,
    #[serde(rename = "dc:creator")]
    creator: Option<String>,
    #[serde(rename = "dc:description")]
    description: Option<String>,
    #[serde(rename = "prism:doi")]
    doi: Option<String>,
    #[serde(rename = "prism:coverDate")]
    cover_date: Option<String>,
    #[serde(rename = "prism:url")]
    url: Option<String>,
    #[serde(rename = "prism:publicationName")]
    publication_name: Option<String>,
    #[serde(rename = "prism:issn")]
    issn: Option<String>,
    #[serde(rename = "prism:aggregationType")]
    aggregation_type: Option<String>,
    #[serde(
        rename = "citedby-count",
        default,
        deserialize_with = "deserialize_u64"
    )]
    cited_by_count: u64,
    #[serde(rename = "prism:volume")]
    volume: Option<String>,
    #[serde(rename = "prism:issueIdentifier")]
    issue: Option<String>,
    #[serde(rename = "prism:pageRange")]
    pages: Option<String>,
}

fn parse_payload(body: &str) -> Result<(Vec<Paper>, usize), AppError> {
    let payload: ScopusPayload = serde_json::from_str(body)
        .map_err(|error| AppError::Parse(format!("[scopus] invalid JSON response: {error}")))?;
    let mut skipped = 0;
    let papers = payload
        .search_results
        .entries
        .into_iter()
        .filter_map(|record| match serde_json::from_value(record) {
            Ok(record) => parse_entry(record),
            Err(_) => {
                skipped += 1;
                None
            }
        })
        .collect();
    Ok((papers, skipped))
}

fn parse_entry(item: ScopusEntry) -> Option<Paper> {
    if item.identifier.is_empty() && item.title.is_empty() {
        return None;
    }
    let published_date = item
        .cover_date
        .as_deref()
        .and_then(|value| NaiveDate::parse_from_str(value, "%Y-%m-%d").ok())
        .and_then(|date| date.and_hms_opt(0, 0, 0))
        .map(|date| DateTime::<Utc>::from_naive_utc_and_offset(date, Utc));
    let doi = item.doi.filter(|value| !value.is_empty());
    let url = item
        .url
        .filter(|value| !value.is_empty())
        .or_else(|| doi.as_ref().map(|doi| format!("https://doi.org/{doi}")))
        .unwrap_or_default();
    let mut extra = BTreeMap::new();
    if let Some(kind) = item.aggregation_type.filter(|value| !value.is_empty()) {
        extra.insert("aggregation_type".into(), serde_json::Value::String(kind));
    }

    Some(Paper {
        paper_id: item.identifier.trim_start_matches("SCOPUS_ID:").to_owned(),
        title: item.title,
        authors: item.creator.into_iter().collect(),
        abstract_text: item.description.unwrap_or_default(),
        doi,
        issn: item.issn,
        published_date,
        year: published_date.map(|date| date.year()),
        url,
        source: ProviderName::Scopus,
        sources: vec![ProviderName::Scopus],
        journal: item.publication_name,
        citations: item.cited_by_count,
        volume: item.volume,
        issue: item.issue,
        pages: item.pages,
        extra,
        ..Paper::default()
    })
}

fn deserialize_u64<'de, D>(deserializer: D) -> Result<u64, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let value = serde_json::Value::deserialize(deserializer)?;
    match value {
        serde_json::Value::Number(number) => number
            .as_u64()
            .ok_or_else(|| serde::de::Error::custom("citation count is not an unsigned integer")),
        serde_json::Value::String(value) => value.parse().map_err(serde::de::Error::custom),
        serde_json::Value::Null => Ok(0),
        _ => Err(serde::de::Error::custom("invalid citation count")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_scopus_record() {
        let (papers, skipped) = parse_payload(
            r#"{"search-results":{"entry":[{"dc:identifier":"SCOPUS_ID:1","dc:title":"Paper",
            "prism:coverDate":"2025-01-02","prism:doi":"10.1/test","citedby-count":"4"}]}}"#,
        )
        .unwrap();
        assert_eq!(skipped, 0);
        let paper = papers.into_iter().next().unwrap();
        assert_eq!(paper.paper_id, "1");
        assert_eq!(paper.citations, 4);
        assert_eq!(paper.year, Some(2025));
    }

    #[test]
    fn skips_malformed_scopus_records() {
        let (papers, skipped) = parse_payload(
            r#"{"search-results":{"entry":[
                {"dc:identifier":"SCOPUS_ID:bad","dc:title":"Bad","citedby-count":{}},
                {"dc:identifier":"SCOPUS_ID:good","dc:title":"Usable","citedby-count":"2"}
            ]}}"#,
        )
        .unwrap();
        assert_eq!(skipped, 1);
        assert_eq!(papers.len(), 1);
        assert_eq!(papers[0].paper_id, "good");
    }
}
