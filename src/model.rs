use chrono::{DateTime, Utc};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, JsonSchema, Default)]
#[serde(rename_all = "snake_case")]
pub enum ProviderName {
    #[default]
    Arxiv,
    SemanticScholar,
    Scopus,
    Webofscience,
}

impl ProviderName {
    pub const ALL: [Self; 4] = [
        Self::Arxiv,
        Self::SemanticScholar,
        Self::Scopus,
        Self::Webofscience,
    ];

    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Arxiv => "arxiv",
            Self::SemanticScholar => "semantic_scholar",
            Self::Scopus => "scopus",
            Self::Webofscience => "webofscience",
        }
    }
}

impl std::fmt::Display for ProviderName {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(self.as_str())
    }
}

impl std::str::FromStr for ProviderName {
    type Err = String;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value.trim().to_ascii_lowercase().as_str() {
            "arxiv" => Ok(Self::Arxiv),
            "semantic_scholar" => Ok(Self::SemanticScholar),
            "scopus" => Ok(Self::Scopus),
            "webofscience" => Ok(Self::Webofscience),
            unknown => Err(format!("unsupported platform: {unknown}")),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema, Default)]
#[serde(rename_all = "snake_case")]
pub enum SortBy {
    #[default]
    Relevance,
    Date,
    Citations,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct WosSearchOptions {
    pub doi: Option<String>,
    pub issn: Option<String>,
    pub document_type: Option<String>,
    #[schemars(range(min = 1))]
    pub page: Option<u32>,
}

#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct PaperSearchInput {
    #[schemars(length(min = 1, max = 500))]
    pub query: String,
    pub platforms: Option<Vec<ProviderName>>,
    #[serde(default = "default_max_results")]
    #[schemars(range(min = 1, max = 100))]
    pub max_results: u32,
    pub year_from: Option<i32>,
    pub year_to: Option<i32>,
    #[serde(default)]
    pub sort_by: SortBy,
    pub author: Option<String>,
    pub journal: Option<String>,
    #[schemars(range(min = 0))]
    pub min_citations: Option<u64>,
    #[schemars(range(min = 0.0))]
    pub min_if: Option<f64>,
    pub jcr_quartile: Option<String>,
    pub cas_quartile: Option<String>,
    pub ccf_rank: Option<String>,
    #[serde(default)]
    pub exclude_warning: bool,
    pub wos_options: Option<WosSearchOptions>,
}

const fn default_max_results() -> u32 {
    10
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, JsonSchema, PartialEq)]
pub struct JournalMetrics {
    pub impact_factor: Option<f64>,
    pub jcr_quartile: Option<String>,
    pub jcr_rank: Option<String>,
    pub jcr_category: Option<String>,
    pub cas_quartile: Option<String>,
    pub cas_category: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub cas_sub_categories: Vec<String>,
    pub ccf_rank: Option<String>,
    pub ccf_field: Option<String>,
    #[serde(default)]
    pub is_warning: bool,
    pub warning_reason: Option<String>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, JsonSchema, PartialEq)]
pub struct Paper {
    pub paper_id: String,
    pub title: String,
    #[serde(default)]
    pub authors: Vec<String>,
    #[serde(default, rename = "abstract")]
    pub abstract_text: String,
    pub doi: Option<String>,
    pub issn: Option<String>,
    pub published_date: Option<DateTime<Utc>>,
    pub year: Option<i32>,
    pub url: String,
    pub pdf_url: Option<String>,
    pub source: ProviderName,
    #[serde(default)]
    pub sources: Vec<ProviderName>,
    pub journal: Option<String>,
    #[serde(default)]
    pub categories: Vec<String>,
    #[serde(default)]
    pub keywords: Vec<String>,
    #[serde(default)]
    pub citations: u64,
    pub volume: Option<String>,
    pub issue: Option<String>,
    pub pages: Option<String>,
    pub journal_metrics: Option<JournalMetrics>,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub extra: BTreeMap<String, serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema, PartialEq, Eq)]
pub struct ProviderFailure {
    pub platform: ProviderName,
    pub code: String,
    pub message: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema, PartialEq, Eq)]
pub struct ProviderDiagnostics {
    pub platform: ProviderName,
    pub enabled: bool,
    pub request_url: Option<String>,
    pub status_code: Option<u16>,
    pub result_count: Option<usize>,
    pub cached: Option<bool>,
    pub message: Option<String>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, JsonSchema)]
pub struct PaperSearchResult {
    pub papers: Vec<Paper>,
    #[serde(default)]
    pub failures: Vec<ProviderFailure>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub diagnostics: Option<Vec<ProviderDiagnostics>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<ToolError>,
}

#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema, PartialEq, Eq)]
pub struct ToolError {
    pub code: String,
    pub message: String,
}

#[derive(Debug, Clone, Default, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct JcrLookupInput {
    pub journal: Option<String>,
    pub issn: Option<String>,
}

#[derive(Debug, Clone, Serialize, JsonSchema)]
pub struct JcrLookupResult {
    pub found: bool,
    pub journal: Option<String>,
    pub issn: Option<String>,
    pub metrics: Option<JournalMetrics>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<ToolError>,
}
