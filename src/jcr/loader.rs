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

pub fn detect_jcr_year(data_dir: &Path) -> AppResult<Option<u32>> {
    let database = data_dir.join("jcr.db");
    if database.is_file() {
        match sqlite_jcr_year(&database) {
            Ok(Some(year)) => return Ok(Some(year)),
            Ok(None) => {}
            Err(error) => {
                tracing::warn!(%error, "[jcr] could not detect year from SQLite; trying CSV")
            }
        }
    }

    Ok(latest_file(data_dir, "JCR", "UTF8.csv")?
        .as_deref()
        .and_then(|path| path.file_name())
        .and_then(|name| name.to_str())
        .and_then(year_from_name))
}

fn sqlite_jcr_year(database: &Path) -> AppResult<Option<u32>> {
    let connection =
        Connection::open_with_flags(database, rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY).map_err(
            |error| AppError::Jcr(format!("could not open {}: {error}", database.display())),
        )?;
    Ok(find_latest_table(&table_names(&connection)?, "JCR")
        .as_deref()
        .and_then(year_from_name))
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
            builder.upsert_with_aliases(ccf_entry(&row), ccf_aliases(&row));
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
        .filter_map(|table| family_year(table, prefix).map(|year| (year, table)))
        .max_by_key(|(year, _)| *year)
        .map(|(_, table)| table.clone())
}

fn family_year(value: &str, prefix: &str) -> Option<u32> {
    if !value.get(..prefix.len())?.eq_ignore_ascii_case(prefix) {
        return None;
    }
    let remainder = value.get(prefix.len()..)?;
    let year = remainder.get(..4)?;
    if !year.bytes().all(|byte| byte.is_ascii_digit())
        || remainder
            .as_bytes()
            .get(4)
            .is_some_and(|byte| !matches!(byte, b'-' | b'_'))
    {
        return None;
    }
    year.parse().ok()
}

fn year_from_name(value: &str) -> Option<u32> {
    value
        .split(|character: char| !character.is_ascii_digit())
        .filter(|part| part.len() == 4)
        .filter_map(|part| part.parse::<u32>().ok())
        .max()
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
            builder.upsert_with_aliases(ccf_entry(&row), ccf_aliases(&row));
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
    let files = find_files(data_dir, |name| {
        name.ends_with(suffix) && family_year(name, prefix).is_some()
    })?;
    Ok(files.into_iter().max_by_key(|path| {
        path.file_name()
            .and_then(|name| name.to_str())
            .and_then(|name| family_year(name, prefix))
            .unwrap_or(0)
    }))
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
            jcr_category: indexed_value(row, "Category"),
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
            cas_quartile: value_option(row, &["大类分区"])
                .as_deref()
                .and_then(parse_cas_quartile),
            cas_category: value_option(row, &["大类"]),
            cas_sub_categories: sub_categories,
            ..JournalMetrics::default()
        },
    }
}

fn xr_entry(row: &TextRow) -> JcrEntry {
    let quartile = value_option(row, &["大类新锐分区"])
        .as_deref()
        .and_then(parse_cas_quartile)
        .or_else(|| {
            find_value(row, |key| {
                key.starts_with("大类") && key.contains("新锐分区")
            })
            .as_deref()
            .and_then(parse_cas_quartile)
        });
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

fn ccf_aliases(row: &TextRow) -> Vec<String> {
    [
        "刊物名称",
        "刊物简称",
        "会议缩写",
        "会议简称",
        "Abbreviation",
        "Acronym",
    ]
    .into_iter()
    .filter_map(|name| value_option(row, &[name]))
    .collect()
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
    names.iter().find_map(|name| {
        row.iter()
            .filter(|(key, _)| key.eq_ignore_ascii_case(name))
            .find_map(|(_, value)| normalized_value(value))
    })
}

fn find_value(row: &TextRow, predicate: impl Fn(&str) -> bool) -> Option<String> {
    row.iter()
        .filter(|(key, _)| predicate(key))
        .find_map(|(_, value)| normalized_value(value))
}

fn indexed_value(row: &TextRow, base: &str) -> Option<String> {
    value_option(row, &[base]).or_else(|| {
        row.iter()
            .filter_map(|(key, value)| {
                let (prefix, suffix) = key.rsplit_once('_')?;
                if !prefix.eq_ignore_ascii_case(base) {
                    return None;
                }
                let index = suffix.parse::<u32>().ok()?;
                normalized_value(value).map(|value| (index, value))
            })
            .min_by_key(|(index, _)| *index)
            .map(|(_, value)| value)
    })
}

fn normalized_value(value: &str) -> Option<String> {
    let value = value.trim();
    (!value.is_empty()
        && value != "-"
        && !value.eq_ignore_ascii_case("N/A")
        && !value.eq_ignore_ascii_case("NA")
        && !value.eq_ignore_ascii_case("NONE"))
    .then(|| value.to_owned())
}

fn parse_cas_quartile(value: &str) -> Option<String> {
    let value = value
        .trim()
        .strip_prefix('Q')
        .unwrap_or(value.trim())
        .trim();
    value
        .chars()
        .next()
        .filter(|value| matches!(value, '1' | '2' | '3' | '4'))
        .map(|value| value.to_string())
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
            directory.path().join("JCR2025-UTF8.csv"),
            "Journal,ISSN,EISSN,IF(2025),Category_1,IF Quartile(2025)_1,IF Rank(2025)_1\nTest Journal,1234-5678,,5.2,TEST CATEGORY,Q1,1/100\n",
        )
        .unwrap();
        std::fs::write(
            directory.path().join("FQBJCR2025-UTF8.csv"),
            "Journal,ISSN/EISSN,大类分区,大类\nTest Journal,1234-5678,1 [1/1091],工程技术\n",
        )
        .unwrap();
        let index = load_jcr_index(directory.path()).unwrap();
        let entry = index.lookup("1234-5678", "").unwrap();
        assert_eq!(entry.metrics.impact_factor, Some(5.2));
        assert_eq!(entry.metrics.jcr_quartile.as_deref(), Some("Q1"));
        assert_eq!(entry.metrics.jcr_category.as_deref(), Some("TEST CATEGORY"));
        assert_eq!(entry.metrics.cas_quartile.as_deref(), Some("1"));
        assert_eq!(detect_jcr_year(directory.path()).unwrap(), Some(2025));
    }

    #[test]
    fn prefers_primary_xr_quartile_over_older_cas_data() {
        let directory = tempdir().unwrap();
        std::fs::write(
            directory.path().join("JCR2025-UTF8.csv"),
            "Journal,ISSN,IF(2025)\nTest Journal,1234-5678,5.2\n",
        )
        .unwrap();
        std::fs::write(
            directory.path().join("FQBJCR2025-UTF8.csv"),
            "Journal,ISSN/EISSN,大类分区\nTest Journal,1234-5678,2 [20/100]\n",
        )
        .unwrap();
        std::fs::write(
            directory.path().join("XR2026-UTF8.csv"),
            "Journal,ISSN,EISSN,大类新锐分区,大类2新锐分区\nTest Journal,1234-5678,,1 区,\n",
        )
        .unwrap();
        std::fs::write(
            directory.path().join("XR2026Conferences-UTF8.csv"),
            "会议缩写,Journal,分区,Top\nTEST,Test Conference,1,Top\n",
        )
        .unwrap();

        let index = load_jcr_index(directory.path()).unwrap();
        let entry = index.lookup("1234-5678", "").unwrap();
        assert_eq!(entry.metrics.cas_quartile.as_deref(), Some("1"));
    }

    #[test]
    fn selects_latest_year_table() {
        let tables = HashSet::from([
            "JCR2024".into(),
            "JCR2025".into(),
            "JCR2026Supplement".into(),
        ]);
        assert_eq!(
            find_latest_table(&tables, "JCR").as_deref(),
            Some("JCR2025")
        );
    }

    #[test]
    fn ignores_placeholders_and_indexes_ccf_abbreviations() {
        let directory = tempdir().unwrap();
        std::fs::write(
            directory.path().join("JCR2025-UTF8.csv"),
            concat!(
                "Journal,ISSN,EISSN,IF(2025),Category_1,IF Quartile(2025)_1\n",
                "Frontiers in Artificial Intelligence,N/A,2624-8212,6.7,COMPUTER SCIENCE,N/A\n",
                "Another Missing-ISSN Journal,N/A,,2.0,TEST CATEGORY,Q2\n",
                "IEEE Transactions on Pattern Analysis and Machine Intelligence,0162-8828,,20.4,COMPUTER SCIENCE,Q1\n"
            ),
        )
        .unwrap();
        std::fs::write(
            directory.path().join("CCF2026-UTF8.csv"),
            concat!(
                "刊物名称,Journal,年份,出版社,网址,领域,CCF推荐类别（国际学术刊物/会议）,CCF推荐类型\n",
                "TPAMI,IEEE Transactions on Pattern Analysis and Machine Intelligence,2026,IEEE,,人工智能,推荐国际学术刊物,A类\n",
                "AAAI,AAAI Conference on Artificial Intelligence,2026,AAAI,,人工智能,推荐国际学术会议,A类\n"
            ),
        )
        .unwrap();
        std::fs::write(
            directory.path().join("CCFT2025-UTF8.csv"),
            "中文刊名,Journal,CCF推荐类别,T分区\n错误数据,Wrong Journal,计算领域高质量科技期刊分级目录,T1\n",
        )
        .unwrap();

        let index = load_jcr_index(directory.path()).unwrap();
        let frontiers = index
            .lookup("", "Frontiers in Artificial Intelligence")
            .unwrap();
        assert_eq!(frontiers.metrics.impact_factor, Some(6.7));
        assert_eq!(frontiers.metrics.jcr_quartile, None);
        assert_eq!(
            index
                .lookup("", "Another Missing-ISSN Journal")
                .unwrap()
                .metrics
                .impact_factor,
            Some(2.0)
        );

        let tpami = index.lookup("", "TPAMI").unwrap();
        assert_eq!(tpami.metrics.impact_factor, Some(20.4));
        assert_eq!(tpami.metrics.ccf_rank.as_deref(), Some("A"));
        let aaai = index.lookup("", "AAAI").unwrap();
        assert_eq!(aaai.journal, "AAAI Conference on Artificial Intelligence");
        assert_eq!(aaai.metrics.ccf_rank.as_deref(), Some("A"));
        assert!(index.lookup("", "Wrong Journal").is_none());
    }

    #[test]
    fn detects_year_from_latest_sqlite_table() {
        let directory = tempdir().unwrap();
        let database = directory.path().join("jcr.db");
        let connection = Connection::open(&database).unwrap();
        connection
            .execute_batch(
                "CREATE TABLE JCR2024 (Journal TEXT); CREATE TABLE JCR2025 (Journal TEXT);",
            )
            .unwrap();

        assert_eq!(detect_jcr_year(directory.path()).unwrap(), Some(2025));
    }
}
