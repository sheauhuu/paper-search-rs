use crate::config::Config;
use crate::error::{AppError, AppResult};
use crate::jcr::loader::{contains_jcr_data, detect_jcr_year, load_jcr_index};
use chrono::{DateTime, Duration as ChronoDuration, Utc};
use flate2::read::GzDecoder;
use reqwest::header::ACCEPT;
use serde::{Deserialize, Serialize};
use std::fs;
use std::future::Future;
use std::io::Cursor;
use std::path::{Path, PathBuf};
use tempfile::Builder;

const SHOWJCR_REPOSITORY: &str = "https://github.com/hitfyd/ShowJCR";
const REVISION_URL: &str = "https://api.github.com/repos/hitfyd/ShowJCR/commits/HEAD";
const MAX_ARCHIVE_BYTES: usize = 512 * 1024 * 1024;
const MAX_EXTRACTED_BYTES: u64 = 2 * 1024 * 1024 * 1024;

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct VersionInfo {
    pub last_update: Option<DateTime<Utc>>,
    pub last_check: Option<DateTime<Utc>>,
    pub source: Option<String>,
    pub remote_ref: Option<String>,
    pub jcr_year: Option<u32>,
    pub index_size: Option<usize>,
}

#[derive(Debug, Clone)]
pub struct UpdateOutcome {
    pub changed: bool,
    pub index_size: usize,
    pub remote_ref: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct ValidatedDataset {
    index_size: usize,
    jcr_year: Option<u32>,
}

pub async fn ensure_current(config: &Config) -> AppResult<bool> {
    ensure_current_with(config, update_from_remote(config)).await
}

async fn ensure_current_with<F>(config: &Config, update: F) -> AppResult<bool>
where
    F: Future<Output = AppResult<UpdateOutcome>>,
{
    if config.jcr.auto_update_days == 0 {
        return Ok(false);
    }
    let source = data_source_dir(&config.jcr.data_dir);
    if source.is_some()
        && !interval_elapsed(&config.jcr.data_dir, config.jcr.auto_update_days, true)
    {
        return Ok(false);
    }
    let outcome = update.await;
    if outcome.is_err() && source.is_some() {
        let mut version = read_version(&config.jcr.data_dir);
        version.last_check = Some(Utc::now());
        if let Err(error) = write_version(&config.jcr.data_dir, &version) {
            tracing::warn!(%error, "[jcr] could not record failed runtime update check");
        }
    }
    outcome.map(|outcome| outcome.changed)
}

pub async fn update_jcr(config: &Config, force: bool) -> AppResult<UpdateOutcome> {
    let source = data_source_dir(&config.jcr.data_dir);
    if !force
        && source.is_some()
        && !interval_elapsed(&config.jcr.data_dir, config.jcr.max_age_days, false)
    {
        let version = read_version(&config.jcr.data_dir);
        let index_size = source
            .as_deref()
            .map(load_jcr_index)
            .transpose()?
            .map_or(0, |index| index.len());
        return Ok(UpdateOutcome {
            changed: false,
            index_size,
            remote_ref: version.remote_ref.unwrap_or_default(),
        });
    }
    update_from_remote(config).await
}

pub fn data_source_dir(data_dir: &Path) -> Option<PathBuf> {
    let candidates = [
        data_dir.join("current"),
        data_dir.join("repo").join("中科院分区表及JCR原始数据文件"),
        data_dir.to_path_buf(),
    ];
    candidates
        .into_iter()
        .find(|candidate| contains_jcr_data(candidate))
}

async fn update_from_remote(config: &Config) -> AppResult<UpdateOutcome> {
    fs::create_dir_all(&config.jcr.data_dir)?;
    let client = github_client(config)?;
    let revision = fetch_revision(&client).await?;
    let mut version = read_version(&config.jcr.data_dir);
    if version.remote_ref.as_deref() == Some(revision.as_str())
        && let Some(source) = data_source_dir(&config.jcr.data_dir)
    {
        version.last_check = Some(Utc::now());
        if let Some(year) = detect_jcr_year(&source)? {
            version.jcr_year = Some(year);
        }
        write_version(&config.jcr.data_dir, &version)?;
        let index_size = load_jcr_index(&source)?.len();
        return Ok(UpdateOutcome {
            changed: false,
            index_size,
            remote_ref: revision,
        });
    }

    let archive = download_archive(&client, &revision).await?;
    let data_dir = config.jcr.data_dir.clone();
    let revision_for_task = revision.clone();
    let dataset = tokio::task::spawn_blocking(move || {
        extract_validate_publish(&data_dir, &revision_for_task, &archive)
    })
    .await
    .map_err(|error| AppError::Jcr(format!("JCR update task failed: {error}")))??;

    write_successful_update(
        &config.jcr.data_dir,
        version,
        &revision,
        dataset,
        Utc::now(),
    )?;
    Ok(UpdateOutcome {
        changed: true,
        index_size: dataset.index_size,
        remote_ref: revision,
    })
}

fn write_successful_update(
    data_dir: &Path,
    mut version: VersionInfo,
    revision: &str,
    dataset: ValidatedDataset,
    now: DateTime<Utc>,
) -> AppResult<()> {
    version.last_update = Some(now);
    version.last_check = Some(now);
    version.source = Some(SHOWJCR_REPOSITORY.into());
    version.remote_ref = Some(revision.to_owned());
    version.jcr_year = dataset.jcr_year;
    version.index_size = Some(dataset.index_size);
    write_version(data_dir, &version)
}

fn github_client(config: &Config) -> AppResult<reqwest::Client> {
    let mut builder = reqwest::Client::builder()
        .timeout(config.search.timeout)
        .user_agent(concat!("paper-search-rs/", env!("CARGO_PKG_VERSION")))
        .no_proxy();
    if let Some(proxy_url) = config
        .proxy
        .socks5
        .as_ref()
        .or(config.proxy.https.as_ref())
        .or(config.proxy.http.as_ref())
    {
        builder = builder.proxy(
            reqwest::Proxy::all(proxy_url)
                .map_err(|error| AppError::Config(format!("invalid JCR proxy: {error}")))?,
        );
    }
    builder
        .build()
        .map_err(|error| AppError::Jcr(format!("could not build JCR HTTP client: {error}")))
}

async fn fetch_revision(client: &reqwest::Client) -> AppResult<String> {
    #[derive(Deserialize)]
    struct Commit {
        sha: String,
    }
    let response = client
        .get(REVISION_URL)
        .header(ACCEPT, "application/vnd.github+json")
        .send()
        .await
        .map_err(|error| AppError::Jcr(format!("could not check ShowJCR revision: {error}")))?;
    if !response.status().is_success() {
        return Err(AppError::Jcr(format!(
            "ShowJCR revision check returned HTTP {}",
            response.status()
        )));
    }
    let commit: Commit = response
        .json()
        .await
        .map_err(|error| AppError::Jcr(format!("invalid ShowJCR revision response: {error}")))?;
    if commit.sha.is_empty() {
        return Err(AppError::Jcr("ShowJCR revision was empty".into()));
    }
    Ok(commit.sha)
}

async fn download_archive(client: &reqwest::Client, revision: &str) -> AppResult<Vec<u8>> {
    let url = format!("https://api.github.com/repos/hitfyd/ShowJCR/tarball/{revision}");
    let mut response = client
        .get(url)
        .header(ACCEPT, "application/vnd.github+json")
        .send()
        .await
        .map_err(|error| AppError::Jcr(format!("could not download ShowJCR archive: {error}")))?;
    if !response.status().is_success() {
        return Err(AppError::Jcr(format!(
            "ShowJCR archive download returned HTTP {}",
            response.status()
        )));
    }
    let mut bytes = Vec::new();
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(|error| AppError::Jcr(format!("failed while reading ShowJCR archive: {error}")))?
    {
        if bytes.len().saturating_add(chunk.len()) > MAX_ARCHIVE_BYTES {
            return Err(AppError::Jcr(format!(
                "ShowJCR archive exceeds {MAX_ARCHIVE_BYTES} bytes"
            )));
        }
        bytes.extend_from_slice(&chunk);
    }
    Ok(bytes)
}

fn extract_validate_publish(
    data_dir: &Path,
    revision: &str,
    archive: &[u8],
) -> AppResult<ValidatedDataset> {
    let staging = Builder::new()
        .prefix(".jcr-staging-")
        .tempdir_in(data_dir)?;
    let decoder = GzDecoder::new(Cursor::new(archive));
    let mut tar = tar::Archive::new(decoder);
    let mut extracted_bytes = 0_u64;
    for entry in tar
        .entries()
        .map_err(|error| AppError::Jcr(format!("invalid ShowJCR archive: {error}")))?
    {
        let mut entry = entry
            .map_err(|error| AppError::Jcr(format!("invalid ShowJCR archive entry: {error}")))?;
        let kind = entry.header().entry_type();
        if !(kind.is_file() || kind.is_dir()) {
            continue;
        }
        extracted_bytes = extracted_bytes.saturating_add(entry.header().size().unwrap_or(0));
        if extracted_bytes > MAX_EXTRACTED_BYTES {
            return Err(AppError::Jcr("ShowJCR extracted data is too large".into()));
        }
        if !entry
            .unpack_in(staging.path())
            .map_err(|error| AppError::Jcr(format!("could not extract ShowJCR archive: {error}")))?
        {
            return Err(AppError::Jcr(
                "ShowJCR archive contains an unsafe path".into(),
            ));
        }
    }

    let source = find_data_directory(staging.path(), 0)
        .ok_or_else(|| AppError::Jcr("ShowJCR archive contains no usable JCR data".into()))?;
    let index = load_jcr_index(&source)?;
    if index.is_empty() {
        return Err(AppError::Jcr(
            "ShowJCR archive produced an empty index".into(),
        ));
    }
    let dataset = ValidatedDataset {
        index_size: index.len(),
        jcr_year: detect_jcr_year(&source)?,
    };

    let prepared = staging.path().join("prepared");
    fs::rename(&source, &prepared).map_err(|error| {
        AppError::Jcr(format!(
            "could not prepare ShowJCR revision {revision}: {error}"
        ))
    })?;
    publish_directory(data_dir, &prepared)?;
    Ok(dataset)
}

fn find_data_directory(root: &Path, depth: usize) -> Option<PathBuf> {
    if contains_jcr_data(root) {
        return Some(root.to_path_buf());
    }
    if depth >= 8 {
        return None;
    }
    fs::read_dir(root)
        .ok()?
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .filter(|path| path.is_dir())
        .find_map(|path| find_data_directory(&path, depth + 1))
}

fn publish_directory(data_dir: &Path, prepared: &Path) -> AppResult<()> {
    let current = data_dir.join("current");
    let previous = data_dir.join(".previous");
    if previous.exists() {
        fs::remove_dir_all(&previous)?;
    }
    if current.exists() {
        fs::rename(&current, &previous)?;
    }
    if let Err(error) = fs::rename(prepared, &current) {
        if previous.exists() {
            let _ = fs::rename(&previous, &current);
        }
        return Err(AppError::Jcr(format!(
            "could not publish validated JCR data: {error}"
        )));
    }
    if previous.exists() {
        fs::remove_dir_all(previous)?;
    }
    Ok(())
}

fn interval_elapsed(data_dir: &Path, days: u64, use_last_check: bool) -> bool {
    if days == 0 {
        return true;
    }
    let version = read_version(data_dir);
    let timestamp = if use_last_check {
        version.last_check.or(version.last_update)
    } else {
        version.last_update
    };
    timestamp.is_none_or(|timestamp| {
        Utc::now().signed_duration_since(timestamp)
            >= ChronoDuration::days(i64::try_from(days).unwrap_or(i64::MAX))
    })
}

fn read_version(data_dir: &Path) -> VersionInfo {
    let path = data_dir.join("version.json");
    let Ok(bytes) = fs::read(path) else {
        return VersionInfo::default();
    };
    serde_json::from_slice(&bytes).unwrap_or_else(|error| {
        tracing::warn!(%error, "[jcr] invalid version metadata; treating as stale");
        VersionInfo::default()
    })
}

fn write_version(data_dir: &Path, version: &VersionInfo) -> AppResult<()> {
    fs::create_dir_all(data_dir)?;
    let temporary = data_dir.join(format!(".version-{}.tmp", std::process::id()));
    let destination = data_dir.join("version.json");
    let backup = data_dir.join(".version.backup");
    fs::write(&temporary, serde_json::to_vec_pretty(version)?)?;
    if backup.exists() {
        fs::remove_file(&backup)?;
    }
    if destination.exists() {
        fs::rename(&destination, &backup)?;
    }
    if let Err(error) = fs::rename(&temporary, &destination) {
        if backup.exists() {
            let _ = fs::rename(&backup, &destination);
        }
        return Err(AppError::Jcr(format!(
            "could not publish JCR version metadata: {error}"
        )));
    }
    if backup.exists() {
        fs::remove_file(backup)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use flate2::Compression;
    use flate2::write::GzEncoder;

    #[test]
    fn validates_and_publishes_archive() {
        let directory = tempfile::tempdir().unwrap();
        let csv = b"Journal,ISSN,IF(2025),IF Quartile\nTest Journal,1234-5678,5.2,Q1\n";
        let archive = archive_with_file(
            "showjcr-revision/中科院分区表及JCR原始数据文件/JCR2025_UTF8.csv",
            csv,
        );
        let dataset = extract_validate_publish(directory.path(), "revision", &archive).unwrap();
        assert_eq!(dataset.index_size, 1);
        assert_eq!(dataset.jcr_year, Some(2025));
        let source = data_source_dir(directory.path()).expect("published data should be found");
        assert_eq!(load_jcr_index(&source).unwrap().len(), 1);

        let now = Utc::now();
        write_successful_update(
            directory.path(),
            VersionInfo::default(),
            "revision",
            dataset,
            now,
        )
        .unwrap();
        let version = read_version(directory.path());
        assert_eq!(version.jcr_year, Some(2025));
        assert_eq!(version.index_size, Some(1));
        assert_eq!(version.last_update, Some(now));
    }

    #[tokio::test]
    async fn failed_runtime_check_is_throttled_when_local_data_exists() {
        let directory = tempfile::tempdir().unwrap();
        let current = directory.path().join("current");
        fs::create_dir_all(&current).unwrap();
        fs::write(
            current.join("JCR2025-UTF8.csv"),
            "Journal,ISSN,IF(2025)\nTest Journal,1234-5678,5.2\n",
        )
        .unwrap();
        let mut config = Config::from_env().unwrap();
        config.jcr.data_dir = directory.path().to_path_buf();
        config.jcr.auto_update_days = 7;

        let error = ensure_current_with(
            &config,
            std::future::ready(Err(AppError::Jcr("network unavailable".into()))),
        )
        .await
        .expect_err("the original update failure should still be reported");
        assert!(error.to_string().contains("network unavailable"));
        assert!(read_version(directory.path()).last_check.is_some());

        let changed = ensure_current_with(
            &config,
            std::future::ready(Ok(UpdateOutcome {
                changed: true,
                index_size: 1,
                remote_ref: "should-not-run".into(),
            })),
        )
        .await
        .unwrap();
        assert!(
            !changed,
            "a recent failed check should suppress another attempt"
        );
    }

    #[tokio::test]
    async fn failed_first_use_check_is_not_throttled_without_local_data() {
        let directory = tempfile::tempdir().unwrap();
        let mut config = Config::from_env().unwrap();
        config.jcr.data_dir = directory.path().to_path_buf();
        config.jcr.auto_update_days = 7;

        ensure_current_with(
            &config,
            std::future::ready(Err(AppError::Jcr("network unavailable".into()))),
        )
        .await
        .expect_err("the first-use update failure should still be reported");
        assert!(read_version(directory.path()).last_check.is_none());

        let changed = ensure_current_with(
            &config,
            std::future::ready(Ok(UpdateOutcome {
                changed: true,
                index_size: 1,
                remote_ref: "retry".into(),
            })),
        )
        .await
        .unwrap();
        assert!(
            changed,
            "first-use updates should retry when no local data exists"
        );
    }

    #[test]
    fn writes_replaceable_version_metadata() {
        let directory = tempfile::tempdir().unwrap();
        let first = VersionInfo {
            remote_ref: Some("first".into()),
            ..VersionInfo::default()
        };
        let second = VersionInfo {
            remote_ref: Some("second".into()),
            ..VersionInfo::default()
        };
        write_version(directory.path(), &first).unwrap();
        write_version(directory.path(), &second).unwrap();
        assert_eq!(
            read_version(directory.path()).remote_ref.as_deref(),
            Some("second")
        );
        assert!(!directory.path().join(".version.backup").exists());
    }

    fn archive_with_file(path: &str, contents: &[u8]) -> Vec<u8> {
        let encoder = GzEncoder::new(Vec::new(), Compression::default());
        let mut archive = tar::Builder::new(encoder);
        let mut header = tar::Header::new_gnu();
        header.set_size(u64::try_from(contents.len()).unwrap());
        header.set_mode(0o644);
        header.set_cksum();
        archive
            .append_data(&mut header, path, contents)
            .expect("fixture archive entry should be written");
        archive
            .into_inner()
            .expect("fixture archive should finish")
            .finish()
            .expect("fixture gzip should finish")
    }
}
