use crate::model::JournalMetrics;
use std::collections::HashMap;
use std::sync::Arc;

#[derive(Debug, Clone, Default, PartialEq)]
pub struct JcrEntry {
    pub issn: String,
    pub eissns: Vec<String>,
    pub journal: String,
    pub metrics: JournalMetrics,
}

#[derive(Debug, Clone, Default)]
pub struct JcrIndex {
    entries: Arc<[JcrEntry]>,
    issn_index: Arc<HashMap<String, usize>>,
    journal_index: Arc<HashMap<String, usize>>,
}

impl JcrIndex {
    pub fn lookup(&self, issn: &str, journal: &str) -> Option<&JcrEntry> {
        if !issn.is_empty()
            && let Some(index) = self.issn_index.get(&normalize_issn(issn))
        {
            return self.entries.get(*index);
        }
        self.journal_index
            .get(&normalize_journal(journal))
            .and_then(|index| self.entries.get(*index))
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }
}

#[derive(Debug, Default)]
pub(crate) struct JcrIndexBuilder {
    entries: Vec<JcrEntry>,
    issn_index: HashMap<String, usize>,
    journal_index: HashMap<String, usize>,
}

impl JcrIndexBuilder {
    pub fn upsert(&mut self, incoming: JcrEntry) {
        self.upsert_with_aliases(incoming, std::iter::empty());
    }

    pub fn upsert_with_aliases(
        &mut self,
        mut incoming: JcrEntry,
        aliases: impl IntoIterator<Item = String>,
    ) {
        incoming.issn = normalize_issn(&incoming.issn);
        incoming.eissns = incoming
            .eissns
            .into_iter()
            .map(|value| normalize_issn(&value))
            .filter(|value| !value.is_empty())
            .collect();
        let journal_key = normalize_journal(&incoming.journal);
        let alias_keys = aliases
            .into_iter()
            .map(|alias| normalize_journal(&alias))
            .filter(|alias| !alias.is_empty() && alias != &journal_key)
            .collect::<Vec<_>>();
        let index = (!incoming.issn.is_empty())
            .then(|| self.issn_index.get(&incoming.issn).copied())
            .flatten()
            .or_else(|| self.journal_index.get(&journal_key).copied())
            .or_else(|| {
                alias_keys
                    .iter()
                    .find_map(|alias| self.journal_index.get(alias).copied())
            });

        let index = if let Some(index) = index {
            merge_entry(&mut self.entries[index], incoming);
            index
        } else {
            let index = self.entries.len();
            self.entries.push(incoming);
            index
        };
        let entry = &self.entries[index];
        if !entry.issn.is_empty() {
            self.issn_index.insert(entry.issn.clone(), index);
        }
        for issn in &entry.eissns {
            self.issn_index.insert(issn.clone(), index);
        }
        if !journal_key.is_empty() {
            self.journal_index.insert(journal_key, index);
        }
        for alias in alias_keys {
            self.journal_index.insert(alias, index);
        }
    }

    pub fn build(self) -> JcrIndex {
        JcrIndex {
            entries: self.entries.into(),
            issn_index: Arc::new(self.issn_index),
            journal_index: Arc::new(self.journal_index),
        }
    }
}

pub fn normalize_issn(value: &str) -> String {
    let normalized = value
        .chars()
        .filter(|character| !character.is_whitespace() && *character != '-')
        .flat_map(char::to_uppercase)
        .collect::<String>();
    match normalized.as_str() {
        "" | "N/A" | "NA" | "NONE" => String::new(),
        _ => normalized,
    }
}

pub fn normalize_journal(value: &str) -> String {
    value
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_lowercase()
}

fn merge_entry(target: &mut JcrEntry, source: JcrEntry) {
    if target.issn.is_empty() {
        target.issn = source.issn;
    }
    for issn in source.eissns {
        if !target.eissns.contains(&issn) {
            target.eissns.push(issn);
        }
    }
    if target.journal.is_empty() {
        target.journal = source.journal;
    }
    let target_metrics = &mut target.metrics;
    let source_metrics = source.metrics;
    fill(
        &mut target_metrics.impact_factor,
        source_metrics.impact_factor,
    );
    fill(
        &mut target_metrics.jcr_quartile,
        source_metrics.jcr_quartile,
    );
    fill(&mut target_metrics.jcr_rank, source_metrics.jcr_rank);
    fill(
        &mut target_metrics.jcr_category,
        source_metrics.jcr_category,
    );
    if source_metrics.cas_quartile.is_some() {
        target_metrics.cas_quartile = source_metrics.cas_quartile;
    }
    fill(
        &mut target_metrics.cas_category,
        source_metrics.cas_category,
    );
    if target_metrics.cas_sub_categories.is_empty() {
        target_metrics.cas_sub_categories = source_metrics.cas_sub_categories;
    }
    fill(&mut target_metrics.ccf_rank, source_metrics.ccf_rank);
    fill(&mut target_metrics.ccf_field, source_metrics.ccf_field);
    target_metrics.is_warning |= source_metrics.is_warning;
    fill(
        &mut target_metrics.warning_reason,
        source_metrics.warning_reason,
    );
}

fn fill<T>(target: &mut Option<T>, source: Option<T>) {
    if target.is_none() {
        *target = source;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn merges_records_by_issn() {
        let mut builder = JcrIndexBuilder::default();
        builder.upsert(JcrEntry {
            issn: "1234-5678".into(),
            journal: "Test Journal".into(),
            metrics: JournalMetrics {
                impact_factor: Some(5.0),
                ..JournalMetrics::default()
            },
            ..JcrEntry::default()
        });
        builder.upsert(JcrEntry {
            issn: "12345678".into(),
            journal: "Test Journal".into(),
            metrics: JournalMetrics {
                cas_quartile: Some("1".into()),
                ..JournalMetrics::default()
            },
            ..JcrEntry::default()
        });
        let index = builder.build();
        let entry = index.lookup("1234-5678", "").unwrap();
        assert_eq!(entry.metrics.impact_factor, Some(5.0));
        assert_eq!(entry.metrics.cas_quartile.as_deref(), Some("1"));
    }

    #[test]
    fn missing_issns_do_not_merge_unrelated_journals() {
        let mut builder = JcrIndexBuilder::default();
        builder.upsert(JcrEntry {
            issn: "N/A".into(),
            journal: "First Journal".into(),
            metrics: JournalMetrics {
                impact_factor: Some(1.0),
                ..JournalMetrics::default()
            },
            ..JcrEntry::default()
        });
        builder.upsert(JcrEntry {
            issn: "N/A".into(),
            journal: "Second Journal".into(),
            metrics: JournalMetrics {
                impact_factor: Some(2.0),
                ..JournalMetrics::default()
            },
            ..JcrEntry::default()
        });

        let index = builder.build();
        assert_eq!(index.len(), 2);
        assert_eq!(
            index
                .lookup("", "First Journal")
                .unwrap()
                .metrics
                .impact_factor,
            Some(1.0)
        );
        assert_eq!(
            index
                .lookup("", "Second Journal")
                .unwrap()
                .metrics
                .impact_factor,
            Some(2.0)
        );
    }

    #[test]
    fn aliases_resolve_to_the_merged_journal_entry() {
        let mut builder = JcrIndexBuilder::default();
        builder.upsert(JcrEntry {
            issn: "0162-8828".into(),
            journal: "IEEE Transactions on Pattern Analysis and Machine Intelligence".into(),
            metrics: JournalMetrics {
                impact_factor: Some(20.4),
                ..JournalMetrics::default()
            },
            ..JcrEntry::default()
        });
        builder.upsert_with_aliases(
            JcrEntry {
                journal: "IEEE Transactions on Pattern Analysis and Machine Intelligence".into(),
                metrics: JournalMetrics {
                    ccf_rank: Some("A".into()),
                    ..JournalMetrics::default()
                },
                ..JcrEntry::default()
            },
            ["TPAMI".into()],
        );

        let index = builder.build();
        let entry = index.lookup("", "TPAMI").unwrap();
        assert_eq!(entry.metrics.impact_factor, Some(20.4));
        assert_eq!(entry.metrics.ccf_rank.as_deref(), Some("A"));
    }
}
