use clap::{Parser, Subcommand};
use paper_search_rs::config::Config;

#[derive(Debug, Parser)]
#[command(name = "paper-search-rs", version, about)]
struct Cli {
    #[command(subcommand)]
    command: Option<Command>,
}

#[derive(Debug, Subcommand)]
enum Command {
    /// Download or refresh ShowJCR data.
    UpdateJcr {
        /// Refresh even when the local data is recent.
        #[arg(long)]
        force: bool,
    },
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .with_writer(std::io::stderr)
        .init();

    let cli = Cli::parse();
    let config = match Config::from_env() {
        Ok(config) => config,
        Err(error) => {
            eprintln!("{error}");
            std::process::exit(2);
        }
    };

    let result = match cli.command {
        Some(Command::UpdateJcr { force }) => {
            paper_search_rs::jcr::updater::update_jcr(&config, force)
                .await
                .map(|outcome| {
                    println!(
                        "JCR data {}: {} journals indexed at {}",
                        if outcome.changed {
                            "updated"
                        } else {
                            "is current"
                        },
                        outcome.index_size,
                        outcome.remote_ref
                    );
                })
        }
        None => paper_search_rs::mcp::server::run(config).await,
    };

    if let Err(error) = result {
        eprintln!("{error}");
        std::process::exit(1);
    }
}
