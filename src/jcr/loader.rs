use crate::error::{AppError, AppResult};
use crate::jcr::model::{JcrEntry, JcrIndex, JcrIndexBuilder, normalize_issn};
use crate::model::JournalMetrics;
use rusqlite::types::ValueRef;
use rusqlite::{Connection, Row};
use std::collections::{BTreeMap, HashSet};
use std::path::{Path, PathBuf};

type TextRow = BTreeMap<String, String>;

pub fn load_jcr_index(data_dir: &Path) -> AppResult<JcrIndex> {
    let database = data_dir.join("jcr.db");
    if database.is_file() {
        match load_sqlite(&database) {
            Ok(index) if !index.is_empty() => {
                tracing::info!(entries = index.len(), "[jcr] loaded SQLite index");
                return Ok(index);
            }
            Ok(_) => tracing::warn!("[jcr] SQLite index was empty; trying CSV fallback"),
            Err(error) => tracing::warn!(%error, "[jcr] SQLite load failed; trying CSV fallback"),
        }
    }

    let index = load_csv(data_dir)?;
    if index.is_empty() {
        return Err(AppError::Jcr(format!(
            "no usable JCR SQLite or CSV data found in {}",
            data_dir.display()
        )));
    }
    tracing::info!(entries = index.len(), "[jcr] loaded CSV index");
    Ok(index)
}

pub fn contains_jcr_data(data_dir: &Path) -> bool {
    data_dir.join("jcr.db").is_file()
        || find_files(data_dir, |name| {
            name.starts_with("JCR") && name.ends_with("UTF8.csv")
        })
        .is_ok_and(|files| !files.is_empty())
}

fn load_sqlite(database: &Path) -> AppResult<JcrIndex> {
    let connection =
        Connection::open_with_flags(database, rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY).map_err(
            |error| AppError::Jcr(format!("could not open {}: {error}", database.display())),
        )?;
    let tables = table_names(&connection)?;
    let mut builder = JcrIndexBuilder::default();

    if let Some(table) = find_latest_table(&tables, "JCR") {
        for row in read_table(&connection, &table)? {
            builder.upsert(jcr_entry(&row));
        }
    }
    if let Some(table) = find_latest_table(&tables, "FQBJCR") {
        for row in read_table(&connection, &table)? {
            builder.upsert(cas_entry(&row));
        }
    }
    if let Some(table) = find_latest_table(&tables, "XR") {
        for row in read_table(&connection, &table)? {
            builder.upsert(xr_entry(&row));
        }
    }
    if let Some(table) = find_latest_table(&tables, "CCF") {
        for row in read_table(&connection, &table)? {
            builder.upsert(ccf_entry(&row));
        }
    }
    if let Some(table) = find_latest_table(&tables, "GJQKYJMD") {
        for row in read_table(&connection, &table)? {
            builder.upsert(warning_entry(&row));
        }
    }
    Ok(builder.build())
}

fn table_names(connection: &Connection) -> AppResult<HashSet<String>> {
    let mut statement = connection
        .prepare("SELECT name FROM sqlite_master WHERE type='table'")
        .map_err(|error| AppError::Jcr(format!("could not inspect JCR tables: {error}")))?;
    let names = statement
        .query_map([], |row| row.get::<_, String>(0))
        .map_err(|error| AppError::Jcr(format!("could not query JCR tables: {error}")))?
        .filter_map(Result::ok)
        .collect();
    Ok(names)
}

fn find_latest_table(tables: &HashSet<String>, prefix: &str) -> Option<String> {
    tables
        .iter()
        .filter(|table| {
            table
                .to_ascii_uppercase()
                .starts_with(&prefix.to_ascii_uppercase())
        })
        .max_by_key(|table| {
            table
                .split(|character: char| !character.is_ascii_digit())
                .filter_map(|value| value.parse::<u32>().ok())
                .max()
                .unwrap_or(0)
        })
        .cloned()
}

fn read_table(connection: &Connection, table: &str) -> AppResult<Vec<TextRow>> {
    if !table
        .chars()
        .all(|character| character.is_alphanumeric() || character == '_')
    {
        return Err(AppError::Jcr(format!("unsafe SQLite table name: {table}")));
    }
    let mut statement = connection
        .prepare(&format!("SELECT * FROM [{table}]"))
        .map_err(|error| AppError::Jcr(format!("could not read table {table}: {error}")))?;
    let columns = statement
        .column_names()
        .into_iter()
        .map(str::to_owned)
        .collect::<Vec<_>>();
    let rows = statement
        .query_map([], |row| row_to_map(row, &columns))
        .map_err(|error| AppError::Jcr(format!("could not query table {table}: {error}")))?
        .filter_map(Result::ok)
        .collect();
    Ok(rows)
}

fn row_to_map(row: &Row<'_>, columns: &[String]) -> rusqlite::Result<TextRow> {
    let mut values = BTreeMap::new();
    for (index, column) in columns.iter().enumerate() {
        let value = match row.get_ref(index)? {
            ValueRef::Null => String::new(),
            ValueRef::Integer(value) => value.to_string(),
            ValueRef::Real(value) => value.to_string(),
            ValueRef::Text(value) => String::from_utf8_lossy(value).into_owned(),
            ValueRef::Blob(_) => String::new(),
        };
        values.insert(column.clone(), value);
    }
    Ok(values)
}

fn load_csv(data_dir: &Path) -> AppResult<JcrIndex> {
    let mut builder = JcrIndexBuilder::default();
    if let Some(path) = latest_file(data_dir, "JCR", "UTF8.csv")? {
        for row in read_csv(&path)? {
            builder.upsert(jcr_entry(&row));
        }
    }
    if let Some(path) = latest_file(data_dir, "FQBJCR", "UTF8.csv")? {
        for row in read_csv(&path)? {
            builder.upsert(cas_entry(&row));
        }
    }
    if let Some(path) = latest_file(data_dir, "XR", "UTF8.csv")? {
        for row in read_csv(&path)? {
            builder.upsert(xr_entry(&row));
        }
    }
    if let Some(path) = latest_file(data_dir, "CCF", "UTF8.csv")? {
        for row in read_csv(&path)? {
            builder.upsert(ccf_entry(&row));
        }
    }
    if let Some(path) = latest_file(data_dir, "GJQKYJMD", ".csv")? {
        for row in read_csv(&path)? {
            builder.upsert(warning_entry(&row));
        }
    }
    Ok(builder.build())
}

fn latest_file(data_dir: &Path, prefix: &str, suffix: &str) -> AppResult<Option<PathBuf>> {
    let mut files = find_files(data_dir, |name| {
        name.starts_with(prefix) && name.ends_with(suffix)
    })?;
    files.sort();
    Ok(files.pop())
}

fn find_files(data_dir: &Path, predicate: impl Fn(&str) -> bool) -> AppResult<Vec<PathBuf>> {
    if !data_dir.is_dir() {
        return Ok(Vec::new());
    }
    let entries = std::fs::read_dir(data_dir).map_err(AppError::Io)?;
    Ok(entries
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .filter(|path| {
            path.file_name()
                .and_then(|name| name.to_str())
                .is_some_and(&predicate)
        })
        .collect())
}

fn read_csv(path: &Path) -> AppResult<Vec<TextRow>> {
    let mut reader = csv::ReaderBuilder::new()
        .flexible(true)
        .from_path(path)
        .map_err(|error| AppError::Jcr(format!("could not read {}: {error}", path.display())))?;
    let headers = reader
        .headers()
        .map_err(|error| AppError::Jcr(format!("invalid CSV headers: {error}")))?
        .iter()
        .map(|value| value.trim_start_matches('\u{feff}').to_owned())
        .collect::<Vec<_>>();
    let mut rows = Vec::new();
    for record in reader.records() {
        let record = record.map_err(|error| AppError::Jcr(format!("invalid CSV row: {error}")))?;
        rows.push(
            headers
                .iter()
                .cloned()
                .zip(record.iter().map(str::to_owned))
                .collect(),
        );
    }
    Ok(rows)
}

fn jcr_entry(row: &TextRow) -> JcrEntry {
    let issn = value(row, &["ISSN"]);
    let eissn = value(row, &["eISSN", "EISSN"]);
    let impact_factor = row
        .iter()
        .find(|(key, _)| key.starts_with("IF(") || key.eq_ignore_ascii_case("IF"))
        .and_then(|(_, value)| parse_float(value));
    JcrEntry {
        issn,
        eissns: (!eissn.is_empty()).then_some(eissn).into_iter().collect(),
        journal: value(row, &["Journal", "Full Journal Title"]),
        metrics: JournalMetrics {
            impact_factor,
            jcr_quartile: find_value(row, |key| key.to_ascii_lowercase().contains("quartile")),
            jcr_rank: find_value(row, |key| key.to_ascii_lowercase().contains("rank")),
            jcr_category: value_option(row, &["Category"]),
            ..JournalMetrics::default()
        },
    }
}

fn cas_entry(row: &TextRow) -> JcrEntry {
    let combined = value(row, &["ISSN/EISSN", "ISSN"]);
    let mut issns = combined
        .split('/')
        .map(normalize_issn)
        .filter(|value| !value.is_empty())
        .collect::<Vec<_>>();
    let issn = issns.first().cloned().unwrap_or_default();
    if !issns.is_empty() {
        issns.remove(0);
    }
    let sub_categories = row
        .iter()
        .filter(|(key, value)| {
            key.starts_with("小类") && !key.contains("分区") && !value.is_empty()
        })
        .map(|(_, value)| value.clone())
        .collect();
    JcrEntry {
        issn,
        eissns: issns,
        journal: value(row, &["Journal"]),
        metrics: JournalMetrics {
            cas_quartile: value_option(row, &["大类分区"]),
            cas_category: value_option(row, &["大类"]),
            cas_sub_categories: sub_categories,
            ..JournalMetrics::default()
        },
    }
}

fn xr_entry(row: &TextRow) -> JcrEntry {
    let quartile = find_value(row, |key| key.contains("新锐分区"))
        .map(|value| value.replace('区', "").trim().to_owned())
        .filter(|value| matches!(value.as_str(), "1" | "2" | "3" | "4"));
    JcrEntry {
        issn: value(row, &["ISSN"]),
        eissns: value_option(row, &["EISSN", "eISSN"]).into_iter().collect(),
        journal: value(row, &["Journal"]),
        metrics: JournalMetrics {
            cas_quartile: quartile,
            ..JournalMetrics::default()
        },
    }
}

fn ccf_entry(row: &TextRow) -> JcrEntry {
    let rank = row.iter().find_map(|(key, value)| {
        if key.contains("推荐类型") || key.contains("推荐类别") {
            ["A", "B", "C"]
                .into_iter()
                .find(|rank| {
                    value.contains(&format!("{rank}类")) || value.contains(&format!("{rank} 类"))
                })
                .map(str::to_owned)
        } else if key.contains("T分区") && value.starts_with('T') {
            Some(value.clone())
        } else {
            None
        }
    });
    JcrEntry {
        journal: value(row, &["Journal"]),
        metrics: JournalMetrics {
            ccf_rank: rank,
            ccf_field: find_value(row, |key| key.contains("领域") && !key.contains("类别")),
            ..JournalMetrics::default()
        },
        ..JcrEntry::default()
    }
}

fn warning_entry(row: &TextRow) -> JcrEntry {
    JcrEntry {
        journal: value(row, &["Journal"]),
        metrics: JournalMetrics {
            is_warning: true,
            warning_reason: find_value(row, |key| key.contains("预警")),
            ..JournalMetrics::default()
        },
        ..JcrEntry::default()
    }
}

fn value(row: &TextRow, names: &[&str]) -> String {
    value_option(row, names).unwrap_or_default()
}

fn value_option(row: &TextRow, names: &[&str]) -> Option<String> {
    row.iter()
        .find(|(key, _)| names.iter().any(|name| key.eq_ignore_ascii_case(name)))
        .map(|(_, value)| value.trim().to_owned())
        .filter(|value| !value.is_empty() && value != "-")
}

fn find_value(row: &TextRow, predicate: impl Fn(&str) -> bool) -> Option<String> {
    row.iter()
        .find(|(key, _)| predicate(key))
        .map(|(_, value)| value.trim().to_owned())
        .filter(|value| !value.is_empty() && value != "-")
}

fn parse_float(value: &str) -> Option<f64> {
    value.trim().trim_start_matches('<').parse().ok()
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn loads_csv_and_merges_metrics() {
        let directory = tempdir().unwrap();
        std::fs::write(
            directory.path().join("JCR2025_UTF8.csv"),
            "Journal,ISSN,eISSN,IF(2025),IF Quartile,Category\nTest Journal,1234-5678,,5.2,Q1,TEST\n",
        )
        .unwrap();
        std::fs::write(
            directory.path().join("FQBJCR2025_UTF8.csv"),
            "Journal,ISSN/EISSN,大类分区,大类\nTest Journal,1234-5678,1,工程技术\n",
        )
        .unwrap();
        let index = load_jcr_index(directory.path()).unwrap();
        let entry = index.lookup("1234-5678", "").unwrap();
        assert_eq!(entry.metrics.impact_factor, Some(5.2));
        assert_eq!(entry.metrics.jcr_quartile.as_deref(), Some("Q1"));
        assert_eq!(entry.metrics.cas_quartile.as_deref(), Some("1"));
    }

    #[test]
    fn selects_latest_year_table() {
        let tables = HashSet::from(["JCR2024".into(), "JCR2025".into()]);
        assert_eq!(
            find_latest_table(&tables, "JCR").as_deref(),
            Some("JCR2025")
        );
    }
}
