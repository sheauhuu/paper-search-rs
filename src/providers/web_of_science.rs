use super::{Provider, ProviderError, ProviderSearchResult};
use crate::config::Config;
use crate::error::AppError;
use crate::infra::http::{HttpClient, HttpError, HttpResponse};
use crate::model::{Paper, PaperSearchInput, ProviderName, SortBy, WosSearchOptions};
use async_trait::async_trait;
use chrono::{TimeZone, Utc};
use reqwest::header::{ACCEPT, HeaderMap, HeaderValue};
use serde_json::Value;
use std::collections::BTreeMap;

const BASE_URL: &str = "https://api.clarivate.com/apis/wos-starter";
const FIELD_TAGS: &[&str] = &[
    "TS=", "TI=", "AU=", "SO=", "PY=", "DO=", "IS=", "VL=", "PG=", "CS=", "DT=", "PMID=", "FPY=",
    "DOP=", "AI=", "UT=", "OG=", "SUR=",
];

#[derive(Debug)]
pub struct WebOfScienceProvider {
    http: HttpClient,
    api_key: Option<String>,
    max_results: u32,
}

impl WebOfScienceProvider {
    pub fn new(config: &Config) -> Result<Self, ProviderError> {
        let provider_config = config.provider(ProviderName::Webofscience);
        Ok(Self {
            http: HttpClient::new(ProviderName::Webofscience, provider_config, config)?,
            api_key: provider_config.api_key.clone(),
            max_results: provider_config.max_results,
        })
    }

    async fn request_with_fallback(
        &self,
        params: &[(String, String)],
        headers: HeaderMap,
    ) -> Result<HttpResponse, HttpError> {
        let primary = format!("{BASE_URL}/v2/documents");
        match self.http.get(&primary, params, headers.clone()).await {
            Ok(response) => Ok(response),
            Err(error)
                if error.status_code.is_none()
                    || error.status_code == Some(404)
                    || error.status_code.is_some_and(|status| status >= 500) =>
            {
                let fallback = format!("{BASE_URL}/v1/documents");
                self.http.get(&fallback, params, headers).await
            }
            Err(error) => Err(error),
        }
    }
}

#[async_trait]
impl Provider for WebOfScienceProvider {
    fn name(&self) -> ProviderName {
        ProviderName::Webofscience
    }

    async fn search(
        &self,
        input: &PaperSearchInput,
    ) -> Result<ProviderSearchResult, ProviderError> {
        let api_key = self.api_key.as_ref().ok_or_else(|| ProviderError {
            code: "missing_credentials".into(),
            message: "WOS_API_KEY is required when Web of Science is enabled".into(),
            status_code: None,
            request_url: None,
        })?;
        let query = build_query(input);
        let options = input.wos_options.as_ref().cloned().unwrap_or_default();
        let params = vec![
            ("q".into(), query),
            ("db".into(), "WOS".into()),
            (
                "limit".into(),
                input.max_results.min(self.max_results).min(50).to_string(),
            ),
            ("page".into(), options.page.unwrap_or(1).to_string()),
            ("sortField".into(), sort_field(input.sort_by).into()),
        ];
        let mut headers = HeaderMap::new();
        headers.insert(
            "x-apikey",
            HeaderValue::from_str(api_key).map_err(|_| ProviderError {
                code: "invalid_api_key".into(),
                message: "WOS_API_KEY contains invalid header characters".into(),
                status_code: None,
                request_url: None,
            })?,
        );
        headers.insert(ACCEPT, HeaderValue::from_static("application/json"));
        let response = self.request_with_fallback(&params, headers).await.map_err(|error| {
            let mut provider_error = ProviderError::from(error);
            provider_error.message = match provider_error.status_code {
                Some(401) => "Web of Science returned 401 Unauthorized; check WOS_API_KEY and Starter API entitlement".into(),
                Some(403) => "Web of Science returned 403 Forbidden; check Starter API account permissions".into(),
                Some(404) => "Web of Science Starter API endpoint was not found".into(),
                _ => provider_error.message,
            };
            provider_error
        })?;
        let payload: Value = serde_json::from_str(&response.body).map_err(|error| {
            AppError::Parse(format!("[webofscience] invalid JSON response: {error}"))
        })?;
        let papers = payload
            .get("hits")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(parse_record)
            .collect();

        Ok(ProviderSearchResult {
            papers,
            status_code: Some(response.status_code),
            request_url: Some(response.request_url),
            cached: response.cached,
            message: None,
        })
    }
}

fn build_query(input: &PaperSearchInput) -> String {
    let upper = input.query.to_ascii_uppercase();
    let mut parts = vec![if FIELD_TAGS
        .iter()
        .any(|tag| upper.starts_with(tag) || upper.contains(&format!(" {tag}")))
    {
        input.query.clone()
    } else {
        format!("TS=({})", input.query)
    }];
    if input.year_from.is_some() || input.year_to.is_some() {
        parts.push(format!(
            "PY=({}-{})",
            input.year_from.unwrap_or(1900),
            input.year_to.unwrap_or(2099)
        ));
    }
    if let Some(author) = input
        .author
        .as_deref()
        .filter(|value| !value.trim().is_empty())
    {
        parts.push(format!("AU=({author})"));
    }
    if let Some(journal) = input
        .journal
        .as_deref()
        .filter(|value| !value.trim().is_empty())
    {
        parts.push(format!("SO=({journal})"));
    }
    if let Some(options) = &input.wos_options {
        append_options(&mut parts, options);
    }
    parts.join(" AND ")
}

fn append_options(parts: &mut Vec<String>, options: &WosSearchOptions) {
    if let Some(doi) = options
        .doi
        .as_deref()
        .filter(|value| !value.trim().is_empty())
    {
        parts.push(format!("DO=\"{doi}\""));
    }
    if let Some(issn) = options
        .issn
        .as_deref()
        .filter(|value| !value.trim().is_empty())
    {
        parts.push(format!("IS={issn}"));
    }
    if let Some(document_types) = options.document_type.as_deref() {
        let values = document_types
            .split(',')
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(|value| format!("\"{value}\""))
            .collect::<Vec<_>>();
        if !values.is_empty() {
            parts.push(format!("DT=({})", values.join(" OR ")));
        }
    }
}

const fn sort_field(sort_by: SortBy) -> &'static str {
    match sort_by {
        SortBy::Relevance => "RS+D",
        SortBy::Date => "PY+D",
        SortBy::Citations => "TC+D",
    }
}

fn parse_record(record: &Value) -> Option<Paper> {
    let uid = string_at(record, &["uid"]);
    let title = string_at(record, &["title"]);
    if uid.is_none() && title.is_none() {
        return None;
    }
    let source = record.get("source").unwrap_or(&Value::Null);
    let identifiers = record.get("identifiers").unwrap_or(&Value::Null);
    let names = record
        .pointer("/names/authors")
        .and_then(Value::as_array)
        .map(|authors| {
            authors
                .iter()
                .filter_map(|author| string_at(author, &["displayName"]))
                .collect()
        })
        .unwrap_or_default();
    let citations = record
        .get("citations")
        .and_then(Value::as_array)
        .and_then(|items| items.first())
        .and_then(|item| {
            item.get("citingArticlesCount")
                .or_else(|| item.get("count"))
        })
        .and_then(Value::as_u64)
        .unwrap_or(0);
    let keywords = record
        .pointer("/keywords/authorKeywords")
        .and_then(Value::as_array)
        .map(|values| {
            values
                .iter()
                .filter_map(Value::as_str)
                .map(str::to_owned)
                .collect()
        })
        .unwrap_or_default();
    let categories = record
        .get("types")
        .and_then(Value::as_array)
        .map(|values| {
            values
                .iter()
                .filter_map(Value::as_str)
                .map(str::to_owned)
                .collect()
        })
        .unwrap_or_default();
    let year = source
        .get("publishYear")
        .and_then(Value::as_i64)
        .and_then(|value| i32::try_from(value).ok());
    let published_date = year.and_then(|year| Utc.with_ymd_and_hms(year, 1, 1, 0, 0, 0).single());
    let uid = uid.unwrap_or_default();
    let mut extra = BTreeMap::new();
    if let Some(value) = source.get("pages").and_then(format_pages) {
        extra.insert("pages_raw".into(), Value::String(value.clone()));
    }

    Some(Paper {
        paper_id: uid.clone(),
        title: title.unwrap_or_else(|| "No title".into()).trim().to_owned(),
        authors: names,
        abstract_text: string_at(record, &["abstract"]).unwrap_or_default(),
        doi: string_at(identifiers, &["doi"]),
        issn: string_at(identifiers, &["issn"]),
        published_date,
        year,
        url: if uid.is_empty() {
            String::new()
        } else {
            format!("https://www.webofscience.com/wos/woscc/full-record/{uid}")
        },
        source: ProviderName::Webofscience,
        sources: vec![ProviderName::Webofscience],
        journal: string_at(source, &["sourceTitle"]),
        categories,
        keywords,
        citations,
        volume: string_at(source, &["volume"]),
        issue: string_at(source, &["issue"]),
        pages: source.get("pages").and_then(format_pages),
        extra,
        ..Paper::default()
    })
}

fn string_at(value: &Value, path: &[&str]) -> Option<String> {
    path.iter()
        .try_fold(value, |current, key| current.get(*key))
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .map(str::to_owned)
}

fn format_pages(value: &Value) -> Option<String> {
    if let Some(value) = value.as_str() {
        return (!value.is_empty()).then(|| value.to_owned());
    }
    let object = value.as_object()?;
    if let Some(range) = object.get("range").and_then(Value::as_str) {
        return Some(range.to_owned());
    }
    let begin = object.get("begin").and_then(Value::as_str);
    let end = object.get("end").and_then(Value::as_str);
    match (begin, end) {
        (Some(begin), Some(end)) => Some(format!("{begin}-{end}")),
        _ => object.get("count").map(ToString::to_string),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn base_input() -> PaperSearchInput {
        serde_json::from_value(serde_json::json!({"query": "machine learning"})).unwrap()
    }

    #[test]
    fn builds_tagged_query() {
        let mut input = base_input();
        input.year_from = Some(2020);
        input.year_to = Some(2025);
        input.wos_options = Some(WosSearchOptions {
            document_type: Some("Article, Review".into()),
            ..WosSearchOptions::default()
        });
        assert_eq!(
            build_query(&input),
            "TS=(machine learning) AND PY=(2020-2025) AND DT=(\"Article\" OR \"Review\")"
        );
    }

    #[test]
    fn parses_wos_record() {
        let value = serde_json::json!({
            "uid": "WOS:1", "title": "Paper", "abstract": "Text",
            "names": {"authors": [{"displayName": "Alice"}]},
            "source": {"sourceTitle": "Journal", "publishYear": 2025, "pages": {"range": "1-5"}},
            "identifiers": {"doi": "10.1/test", "issn": "1234-5678"},
            "citations": [{"citingArticlesCount": 3}], "types": ["Article"]
        });
        let paper = parse_record(&value).unwrap();
        assert_eq!(paper.citations, 3);
        assert_eq!(paper.journal.as_deref(), Some("Journal"));
        assert_eq!(paper.pages.as_deref(), Some("1-5"));
    }
}
