use rmcp::model::CallToolRequestParams;
use rmcp::transport::{ConfigureCommandExt, TokioChildProcess};
use rmcp::{ServiceExt, serde_json};
use tokio::process::Command;

#[tokio::test]
#[ignore = "uses live academic APIs"]
async fn searches_public_providers() {
    let command = Command::new(env!("CARGO_BIN_EXE_paper-search-rs")).configure(|command| {
        command
            .env("PAPER_SEARCH_DEFAULT_PLATFORMS", "arxiv,semantic_scholar")
            .env("PAPER_SEARCH_JCR_ENABLED", "false")
            .env("PAPER_SEARCH_TIMEOUT_SECONDS", "30")
            .env("RUST_LOG", "error");
    });
    let process = TokioChildProcess::new(command).expect("server process should be configurable");
    let client = ().serve(process).await.expect("stdio server should initialize");
    let result = client
        .call_tool(
            CallToolRequestParams::new("paper_search").with_arguments(
                serde_json::json!({
                    "query": "large language models",
                    "platforms": ["arxiv", "semantic_scholar"],
                    "max_results": 2,
                    "sort_by": "relevance"
                })
                .as_object()
                .unwrap()
                .clone(),
            ),
        )
        .await
        .expect("paper_search call should complete");
    let structured = result
        .structured_content
        .expect("paper_search should return structured content");
    let papers = structured["papers"]
        .as_array()
        .expect("papers should be an array");
    assert!(
        !papers.is_empty(),
        "at least one public provider should return a paper: {structured}"
    );
    client
        .cancel()
        .await
        .expect("client should shut down cleanly");
}
