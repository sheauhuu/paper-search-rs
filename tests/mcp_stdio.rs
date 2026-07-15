use rmcp::model::CallToolRequestParams;
use rmcp::transport::{ConfigureCommandExt, TokioChildProcess};
use rmcp::{ServiceExt, serde_json};
use std::process::Stdio;
use tokio::process::Command;
use tokio::time::{Duration, timeout};

fn server_command(jcr_enabled: bool) -> TokioChildProcess {
    server_command_with_platforms(jcr_enabled, "arxiv,semantic_scholar")
}

fn server_command_with_platforms(jcr_enabled: bool, platforms: &str) -> TokioChildProcess {
    let command = Command::new(env!("CARGO_BIN_EXE_paper-search-mcp")).configure(|command| {
        command
            .env("PAPER_SEARCH_DEFAULT_PLATFORMS", platforms)
            .env(
                "PAPER_SEARCH_JCR_ENABLED",
                if jcr_enabled { "true" } else { "false" },
            )
            .env_remove("SCOPUS_API_KEY")
            .env_remove("WOS_API_KEY")
            .env("RUST_LOG", "error");
    });
    TokioChildProcess::new(command).expect("server process should be configurable")
}

#[tokio::test]
async fn exits_cleanly_when_stdio_closes_before_initialize() {
    let mut command = Command::new(env!("CARGO_BIN_EXE_paper-search-mcp"));
    command
        .env("PAPER_SEARCH_JCR_ENABLED", "false")
        .env("RUST_LOG", "error")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    let output = timeout(Duration::from_secs(5), command.output())
        .await
        .expect("server should exit after stdin closes")
        .expect("server process should run");
    assert!(
        output.status.success(),
        "server exited with {}: {}",
        output.status,
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(
        output.stdout.is_empty(),
        "server wrote non-protocol output to stdout: {}",
        String::from_utf8_lossy(&output.stdout)
    );
}

#[tokio::test]
async fn marks_total_provider_failure_as_structured_tool_error() {
    let client =
        ().serve(server_command_with_platforms(false, "scopus"))
            .await
            .expect("stdio server should initialize");
    let result = client
        .call_tool(
            CallToolRequestParams::new("paper_search").with_arguments(
                serde_json::json!({"query": "rust"})
                    .as_object()
                    .unwrap()
                    .clone(),
            ),
        )
        .await
        .expect("provider failures should be returned as tool results");
    assert_eq!(result.is_error, Some(true));
    let structured = result.structured_content.unwrap();
    assert_eq!(structured["error"]["code"], "all_providers_failed");
    assert_eq!(structured["failures"][0]["platform"], "scopus");
    client
        .cancel()
        .await
        .expect("client should shut down cleanly");
}

#[tokio::test]
async fn lists_schema_complete_tools_over_stdio() {
    let client = ().serve(server_command(false)).await.expect("stdio server should initialize");
    let tools = client
        .list_all_tools()
        .await
        .expect("tools/list should succeed");
    assert_eq!(tools.len(), 1);
    let paper_search = tools
        .iter()
        .find(|tool| tool.name == "paper_search")
        .expect("paper_search should be registered");
    assert!(paper_search.input_schema.contains_key("properties"));
    assert!(paper_search.output_schema.is_some());
    client
        .cancel()
        .await
        .expect("client should shut down cleanly");
}

#[tokio::test]
async fn conditionally_registers_jcr_and_rejects_invalid_input() {
    let client = ().serve(server_command(true)).await.expect("stdio server should initialize");
    let tools = client
        .list_all_tools()
        .await
        .expect("tools/list should succeed");
    assert!(tools.iter().any(|tool| tool.name == "paper_search"));
    assert!(tools.iter().any(|tool| tool.name == "jcr_lookup"));
    assert!(tools.iter().all(|tool| tool.output_schema.is_some()));

    let result = client
        .call_tool(
            CallToolRequestParams::new("paper_search").with_arguments(
                serde_json::json!({"query": ""})
                    .as_object()
                    .expect("fixture is an object")
                    .clone(),
            ),
        )
        .await;
    let result = result.expect("tool validation errors should be returned as tool results");
    assert_eq!(result.is_error, Some(true));
    let structured = result
        .structured_content
        .expect("tool errors should retain structured content");
    assert_eq!(structured["error"]["code"], "invalid_request");
    let text = result.content[0]
        .as_text()
        .expect("compatibility content should be text");
    assert_eq!(
        serde_json::from_str::<serde_json::Value>(&text.text).unwrap(),
        structured
    );
    client
        .cancel()
        .await
        .expect("client should shut down cleanly");
}
