use super::{Provider, ProviderError, ProviderSearchResult};
use crate::config::Config;
use crate::error::AppError;
use crate::infra::http::HttpClient;
use crate::model::{Paper, PaperSearchInput, ProviderName, SortBy};
use async_trait::async_trait;
use chrono::{DateTime, Datelike, Utc};
use reqwest::header::HeaderMap;
use serde::Deserialize;

const API_URL: &str = "https://export.arxiv.org/api/query";

#[derive(Debug)]
pub struct ArxivProvider {
    http: HttpClient,
    max_results: u32,
}

impl ArxivProvider {
    pub fn new(config: &Config) -> Result<Self, ProviderError> {
        let provider_config = config.provider(ProviderName::Arxiv);
        Ok(Self {
            http: HttpClient::new(ProviderName::Arxiv, provider_config, config)?,
            max_results: provider_config.max_results,
        })
    }
}

#[async_trait]
impl Provider for ArxivProvider {
    fn name(&self) -> ProviderName {
        ProviderName::Arxiv
    }

    async fn search(
        &self,
        input: &PaperSearchInput,
    ) -> Result<ProviderSearchResult, ProviderError> {
        let sort_by = match input.sort_by {
            SortBy::Date => "submittedDate",
            SortBy::Relevance | SortBy::Citations => "relevance",
        };
        let params = vec![
            ("search_query".into(), input.query.clone()),
            (
                "max_results".into(),
                input.max_results.min(self.max_results).to_string(),
            ),
            ("sortBy".into(), sort_by.into()),
            ("sortOrder".into(), "descending".into()),
        ];
        let response = self.http.get(API_URL, &params, HeaderMap::new()).await?;
        let feed: AtomFeed = quick_xml::de::from_str(&response.body)
            .map_err(|error| AppError::Parse(format!("[arxiv] invalid Atom response: {error}")))?;

        let papers = feed
            .entries
            .into_iter()
            .filter_map(|entry| parse_entry(entry).ok())
            .filter(|paper| {
                input
                    .year_from
                    .is_none_or(|year| paper.year.is_some_and(|value| value >= year))
                    && input
                        .year_to
                        .is_none_or(|year| paper.year.is_some_and(|value| value <= year))
            })
            .collect::<Vec<_>>();

        Ok(ProviderSearchResult {
            papers,
            status_code: Some(response.status_code),
            request_url: Some(response.request_url),
            cached: response.cached,
            message: (input.sort_by == SortBy::Citations)
                .then(|| "arXiv does not support citation sorting; relevance was used".into()),
        })
    }
}

#[derive(Debug, Deserialize)]
struct AtomFeed {
    #[serde(rename = "entry", default)]
    entries: Vec<AtomEntry>,
}

#[derive(Debug, Deserialize)]
struct AtomEntry {
    #[serde(default)]
    id: String,
    #[serde(default)]
    title: String,
    #[serde(default)]
    summary: String,
    #[serde(default)]
    published: String,
    #[serde(rename = "author", default)]
    authors: Vec<AtomAuthor>,
    #[serde(rename = "link", default)]
    links: Vec<AtomLink>,
    #[serde(rename = "category", default)]
    categories: Vec<AtomCategory>,
    #[serde(default)]
    doi: Option<String>,
}

#[derive(Debug, Deserialize)]
struct AtomAuthor {
    #[serde(default)]
    name: String,
}

#[derive(Debug, Deserialize)]
struct AtomLink {
    #[serde(rename = "@href", default)]
    href: String,
    #[serde(rename = "@type", default)]
    content_type: String,
}

#[derive(Debug, Deserialize)]
struct AtomCategory {
    #[serde(rename = "@term", default)]
    term: String,
}

fn parse_entry(entry: AtomEntry) -> Result<Paper, AppError> {
    let published_date = DateTime::parse_from_rfc3339(entry.published.trim())
        .map_err(|error| AppError::Parse(format!("[arxiv] invalid date: {error}")))?
        .with_timezone(&Utc);
    let pdf_url = entry
        .links
        .iter()
        .find(|link| link.content_type == "application/pdf")
        .map(|link| link.href.clone());
    let paper_id = entry
        .id
        .trim_end_matches('/')
        .rsplit('/')
        .next()
        .unwrap_or_default()
        .to_owned();

    Ok(Paper {
        paper_id,
        title: collapse_whitespace(&entry.title),
        authors: entry
            .authors
            .into_iter()
            .map(|author| author.name)
            .collect(),
        abstract_text: collapse_whitespace(&entry.summary),
        doi: entry.doi.filter(|value| !value.is_empty()),
        published_date: Some(published_date),
        year: Some(published_date.year()),
        url: entry.id,
        pdf_url,
        source: ProviderName::Arxiv,
        sources: vec![ProviderName::Arxiv],
        categories: entry
            .categories
            .into_iter()
            .map(|category| category.term)
            .collect(),
        ..Paper::default()
    })
}

fn collapse_whitespace(value: &str) -> String {
    value.split_whitespace().collect::<Vec<_>>().join(" ")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_atom_entry() {
        let feed: AtomFeed = quick_xml::de::from_str(
            r#"<feed xmlns="http://www.w3.org/2005/Atom">
              <entry><id>https://arxiv.org/abs/2501.00001</id><title>A paper</title>
              <summary>An abstract</summary><published>2025-01-02T00:00:00Z</published>
              <author><name>Alice</name></author>
              <link href="https://arxiv.org/pdf/2501.00001" type="application/pdf" />
              <category term="cs.AI" /></entry></feed>"#,
        )
        .expect("fixture should parse");
        let paper = parse_entry(feed.entries.into_iter().next().unwrap()).unwrap();
        assert_eq!(paper.paper_id, "2501.00001");
        assert_eq!(paper.authors, ["Alice"]);
        assert_eq!(paper.year, Some(2025));
    }
}
