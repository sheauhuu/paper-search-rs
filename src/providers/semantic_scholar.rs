use super::{Provider, ProviderError, ProviderSearchResult};
use crate::config::Config;
use crate::error::AppError;
use crate::infra::http::HttpClient;
use crate::model::{Paper, PaperSearchInput, ProviderName};
use async_trait::async_trait;
use chrono::{DateTime, Datelike, NaiveDate, Utc};
use reqwest::header::{HeaderMap, HeaderValue};
use serde::Deserialize;
use serde_json::Value;
use std::collections::BTreeMap;

const API_URL: &str = "https://api.semanticscholar.org/graph/v1/paper/search";
const FIELDS: &str = "title,abstract,year,citationCount,authors,url,publicationDate,externalIds,fieldsOfStudy,openAccessPdf,venue";

#[derive(Debug)]
pub struct SemanticScholarProvider {
    http: HttpClient,
    api_key: Option<String>,
    max_results: u32,
}

impl SemanticScholarProvider {
    pub fn new(config: &Config) -> Result<Self, ProviderError> {
        let provider_config = config.provider(ProviderName::SemanticScholar);
        Ok(Self {
            http: HttpClient::new(ProviderName::SemanticScholar, provider_config, config)?,
            api_key: provider_config.api_key.clone(),
            max_results: provider_config.max_results,
        })
    }
}

#[async_trait]
impl Provider for SemanticScholarProvider {
    fn name(&self) -> ProviderName {
        ProviderName::SemanticScholar
    }

    async fn search(
        &self,
        input: &PaperSearchInput,
    ) -> Result<ProviderSearchResult, ProviderError> {
        let mut params = vec![
            ("query".into(), input.query.clone()),
            (
                "limit".into(),
                input.max_results.min(self.max_results).to_string(),
            ),
            ("fields".into(), FIELDS.into()),
        ];
        if let Some(year) = year_filter(input.year_from, input.year_to) {
            params.push(("year".into(), year));
        }
        let mut headers = HeaderMap::new();
        if let Some(api_key) = &self.api_key {
            headers.insert(
                "x-api-key",
                HeaderValue::from_str(api_key).map_err(|_| ProviderError {
                    code: "invalid_api_key".into(),
                    message: "SEMANTIC_SCHOLAR_API_KEY contains invalid header characters".into(),
                    status_code: None,
                    request_url: None,
                })?,
            );
        }
        let response = self.http.get(API_URL, &params, headers).await?;
        let (papers, skipped) = parse_payload(&response.body)?;

        Ok(ProviderSearchResult {
            papers,
            status_code: Some(response.status_code),
            request_url: Some(response.request_url),
            cached: response.cached,
            message: (skipped > 0)
                .then(|| format!("skipped {skipped} malformed Semantic Scholar record(s)")),
        })
    }
}

fn year_filter(year_from: Option<i32>, year_to: Option<i32>) -> Option<String> {
    match (year_from, year_to) {
        (Some(from), Some(to)) => Some(format!("{from}-{to}")),
        (Some(from), None) => Some(format!("{from}-")),
        (None, Some(to)) => Some(format!("-{to}")),
        (None, None) => None,
    }
}

#[derive(Debug, Deserialize)]
struct SearchPayload {
    #[serde(default)]
    data: Vec<Value>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct SemanticPaper {
    #[serde(default)]
    paper_id: String,
    #[serde(default)]
    title: String,
    #[serde(rename = "abstract")]
    abstract_text: Option<String>,
    year: Option<i32>,
    #[serde(default)]
    citation_count: u64,
    #[serde(default)]
    authors: Vec<SemanticAuthor>,
    #[serde(default)]
    url: String,
    publication_date: Option<String>,
    external_ids: Option<BTreeMap<String, serde_json::Value>>,
    fields_of_study: Option<Vec<String>>,
    open_access_pdf: Option<OpenAccessPdf>,
    venue: Option<String>,
}

#[derive(Debug, Deserialize)]
struct SemanticAuthor {
    #[serde(default)]
    name: String,
}

#[derive(Debug, Deserialize)]
struct OpenAccessPdf {
    url: Option<String>,
}

fn parse_payload(body: &str) -> Result<(Vec<Paper>, usize), AppError> {
    let payload: SearchPayload = serde_json::from_str(body).map_err(|error| {
        AppError::Parse(format!("[semantic_scholar] invalid JSON response: {error}"))
    })?;
    let mut skipped = 0;
    let papers = payload
        .data
        .into_iter()
        .filter_map(|record| match serde_json::from_value(record) {
            Ok(record) => parse_paper(record),
            Err(_) => {
                skipped += 1;
                None
            }
        })
        .collect();
    Ok((papers, skipped))
}

fn parse_paper(item: SemanticPaper) -> Option<Paper> {
    if item.paper_id.is_empty() && item.title.is_empty() {
        return None;
    }
    let published_date = item
        .publication_date
        .as_deref()
        .and_then(|value| NaiveDate::parse_from_str(value.trim(), "%Y-%m-%d").ok())
        .and_then(|date| date.and_hms_opt(0, 0, 0))
        .map(|date| DateTime::<Utc>::from_naive_utc_and_offset(date, Utc));
    let doi = item
        .external_ids
        .as_ref()
        .and_then(|ids| ids.get("DOI"))
        .and_then(serde_json::Value::as_str)
        .map(str::to_owned);

    Some(Paper {
        paper_id: item.paper_id,
        title: item.title,
        authors: item
            .authors
            .into_iter()
            .map(|author| author.name)
            .filter(|name| !name.is_empty())
            .collect(),
        abstract_text: item.abstract_text.unwrap_or_default(),
        doi,
        published_date,
        year: item.year.or_else(|| published_date.map(|date| date.year())),
        url: item.url,
        pdf_url: item.open_access_pdf.and_then(|pdf| pdf.url),
        source: ProviderName::SemanticScholar,
        sources: vec![ProviderName::SemanticScholar],
        journal: item.venue.filter(|value| !value.is_empty()),
        categories: item.fields_of_study.unwrap_or_default(),
        citations: item.citation_count,
        ..Paper::default()
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn builds_year_ranges() {
        assert_eq!(
            year_filter(Some(2020), Some(2025)).as_deref(),
            Some("2020-2025")
        );
        assert_eq!(year_filter(Some(2020), None).as_deref(), Some("2020-"));
    }

    #[test]
    fn parses_semantic_scholar_record() {
        let (papers, skipped) = parse_payload(
            r#"{"data":[{"paperId":"p1","title":"Paper","abstract":"Summary","year":2025,"citationCount":7,
            "authors":[{"name":"Alice"}],"url":"https://example.test/p1",
            "externalIds":{"DOI":"10.1/test"},"openAccessPdf":{"url":"https://example.test/p.pdf"}}]}"#,
        )
        .unwrap();
        assert_eq!(skipped, 0);
        let paper = papers.into_iter().next().unwrap();
        assert_eq!(paper.doi.as_deref(), Some("10.1/test"));
        assert_eq!(paper.abstract_text, "Summary");
        assert_eq!(paper.citations, 7);
    }

    #[test]
    fn skips_malformed_semantic_scholar_records() {
        let (papers, skipped) = parse_payload(
            r#"{"data":[
                {"paperId":"bad","title":42},
                {"paperId":"good","title":"Usable paper","abstract":"Summary"}
            ]}"#,
        )
        .unwrap();
        assert_eq!(skipped, 1);
        assert_eq!(papers.len(), 1);
        assert_eq!(papers[0].paper_id, "good");
    }
}
