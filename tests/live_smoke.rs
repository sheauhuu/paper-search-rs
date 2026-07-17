use rmcp::model::CallToolRequestParams;
use rmcp::transport::{ConfigureCommandExt, TokioChildProcess};
use rmcp::{ServiceExt, serde_json};
use std::path::Path;
use tokio::process::Command;

fn search_server(platforms: &str) -> TokioChildProcess {
    let command = Command::new(env!("CARGO_BIN_EXE_paper-search-rs")).configure(|command| {
        command
            .env("PAPER_SEARCH_DEFAULT_PLATFORMS", platforms)
            .env("PAPER_SEARCH_JCR_ENABLED", "false")
            .env("PAPER_SEARCH_TIMEOUT_SECONDS", "30")
            .env("RUST_LOG", "error");
    });
    TokioChildProcess::new(command).expect("server process should be configurable")
}

async fn search_providers(platforms: &[&str]) -> serde_json::Value {
    let client =
        ().serve(search_server(&platforms.join(",")))
            .await
            .expect("stdio server should initialize");
    let result = client
        .call_tool(
            CallToolRequestParams::new("paper_search").with_arguments(
                serde_json::json!({
                    "query": "large language models",
                    "platforms": platforms,
                    "max_results": 2,
                    "sort_by": "relevance"
                })
                .as_object()
                .expect("fixture is an object")
                .clone(),
            ),
        )
        .await
        .expect("paper_search call should complete");
    let is_error = result.is_error;
    let structured = result
        .structured_content
        .expect("paper_search should return structured content");
    client
        .cancel()
        .await
        .expect("client should shut down cleanly");
    assert_ne!(is_error, Some(true), "live search failed: {structured}");
    structured
}

fn require_credential(name: &str) {
    assert!(
        std::env::var_os(name).is_some_and(|value| !value.is_empty()),
        "{name} must be loaded before running this ignored live test"
    );
}

fn assert_provider_result(structured: &serde_json::Value, provider: &str) {
    let failures = structured["failures"]
        .as_array()
        .expect("failures should be an array");
    assert!(
        failures.is_empty(),
        "{provider} returned failures: {structured}"
    );
    let papers = structured["papers"]
        .as_array()
        .expect("papers should be an array");
    assert!(
        !papers.is_empty(),
        "{provider} returned no papers: {structured}"
    );
    assert!(
        papers
            .iter()
            .all(|paper| paper["source"].as_str() == Some(provider)),
        "{provider} returned an unexpected source: {structured}"
    );
}

#[tokio::test]
#[ignore = "uses live academic APIs"]
async fn searches_public_providers() {
    let structured = search_providers(&["arxiv", "semantic_scholar"]).await;
    let papers = structured["papers"]
        .as_array()
        .expect("papers should be an array");
    assert!(
        !papers.is_empty(),
        "at least one public provider should return a paper: {structured}"
    );
}

#[tokio::test]
#[ignore = "requires live Scopus credentials"]
async fn searches_scopus_with_credentials() {
    require_credential("SCOPUS_API_KEY");
    let structured = search_providers(&["scopus"]).await;
    assert_provider_result(&structured, "scopus");
}

#[tokio::test]
#[ignore = "requires live Web of Science credentials"]
async fn searches_web_of_science_with_credentials() {
    require_credential("WOS_API_KEY");
    let structured = search_providers(&["webofscience"]).await;
    assert_provider_result(&structured, "webofscience");
}

fn jcr_server(data_dir: &Path) -> TokioChildProcess {
    let command = Command::new(env!("CARGO_BIN_EXE_paper-search-rs")).configure(|command| {
        command
            .env("PAPER_SEARCH_DEFAULT_PLATFORMS", "arxiv")
            .env("PAPER_SEARCH_JCR_ENABLED", "true")
            .env("PAPER_SEARCH_JCR_DATA_DIR", data_dir)
            .env("PAPER_SEARCH_JCR_AUTO_UPDATE_DAYS", "0")
            .env("RUST_LOG", "error");
    });
    TokioChildProcess::new(command).expect("JCR server process should be configurable")
}

#[tokio::test]
#[ignore = "downloads and queries live ShowJCR data"]
async fn updates_and_queries_live_jcr() {
    let directory = tempfile::tempdir().expect("temporary JCR directory should be created");
    let output = Command::new(env!("CARGO_BIN_EXE_paper-search-rs"))
        .arg("update-jcr")
        .arg("--force")
        .env("PAPER_SEARCH_JCR_ENABLED", "true")
        .env("PAPER_SEARCH_JCR_DATA_DIR", directory.path())
        .env("PAPER_SEARCH_TIMEOUT_SECONDS", "120")
        .env("RUST_LOG", "error")
        .output()
        .await
        .expect("update-jcr should run");
    assert!(
        output.status.success(),
        "update-jcr failed with {}: {}",
        output.status,
        String::from_utf8_lossy(&output.stderr)
    );

    let version: serde_json::Value = serde_json::from_slice(
        &std::fs::read(directory.path().join("version.json"))
            .expect("version metadata should be written"),
    )
    .expect("version metadata should be valid JSON");
    assert!(
        version["jcr_year"]
            .as_u64()
            .is_some_and(|year| year >= 2025),
        "published JCR year should come from the live dataset: {version}"
    );
    assert!(
        version["index_size"]
            .as_u64()
            .is_some_and(|size| size > 1_000),
        "live JCR index should contain real data: {version}"
    );

    let client =
        ().serve(jcr_server(directory.path()))
            .await
            .expect("JCR stdio server should initialize");
    let result = client
        .call_tool(
            CallToolRequestParams::new("jcr_lookup").with_arguments(
                serde_json::json!({"journal": "Nature"})
                    .as_object()
                    .expect("fixture is an object")
                    .clone(),
            ),
        )
        .await
        .expect("live JCR lookup should complete");
    let is_error = result.is_error;
    let structured = result
        .structured_content
        .expect("jcr_lookup should return structured content");
    assert_ne!(is_error, Some(true), "live JCR lookup failed: {structured}");
    assert_eq!(structured["found"], true);
    assert!(
        structured["metrics"]["jcr_category"]
            .as_str()
            .is_some_and(|category| !category.is_empty()),
        "live JCR category should be populated: {structured}"
    );
    assert!(
        matches!(
            structured["metrics"]["cas_quartile"].as_str(),
            Some("1" | "2" | "3" | "4")
        ),
        "live CAS quartile should be normalized: {structured}"
    );

    let ccf_result = client
        .call_tool(
            CallToolRequestParams::new("jcr_lookup").with_arguments(
                serde_json::json!({"journal": "AAAI"})
                    .as_object()
                    .expect("fixture is an object")
                    .clone(),
            ),
        )
        .await
        .expect("live CCF abbreviation lookup should complete");
    let ccf_is_error = ccf_result.is_error;
    let ccf_structured = ccf_result
        .structured_content
        .expect("CCF lookup should return structured content");
    assert_ne!(
        ccf_is_error,
        Some(true),
        "live CCF lookup failed: {ccf_structured}"
    );
    assert_eq!(ccf_structured["found"], true);
    assert_eq!(ccf_structured["metrics"]["ccf_rank"], "A");
    assert_eq!(ccf_structured["metrics"]["ccf_field"], "人工智能");

    client
        .cancel()
        .await
        .expect("client should shut down cleanly");
}
