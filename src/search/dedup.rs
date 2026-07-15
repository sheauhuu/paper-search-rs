use crate::model::{Paper, ProviderName};
use std::collections::HashMap;
use unicode_normalization::UnicodeNormalization;

const TITLE_SIMILARITY_THRESHOLD: f64 = 0.85;

pub fn deduplicate(papers: Vec<Paper>) -> Vec<Paper> {
    let mut result: Vec<Paper> = Vec::new();
    let mut doi_indexes: HashMap<String, usize> = HashMap::new();

    for paper in papers {
        if let Some(doi) = paper
            .doi
            .as_deref()
            .map(normalize_doi)
            .filter(|doi| !doi.is_empty())
            && let Some(index) = doi_indexes.get(&doi).copied()
        {
            merge_paper(&mut result[index], paper);
            continue;
        }

        let normalized_title = normalize_title(&paper.title);
        if !normalized_title.is_empty()
            && let Some(index) = result.iter().position(|existing| {
                strsim::normalized_levenshtein(&normalized_title, &normalize_title(&existing.title))
                    >= TITLE_SIMILARITY_THRESHOLD
            })
        {
            merge_paper(&mut result[index], paper);
            continue;
        }

        let index = result.len();
        if let Some(doi) = paper
            .doi
            .as_deref()
            .map(normalize_doi)
            .filter(|doi| !doi.is_empty())
        {
            doi_indexes.insert(doi, index);
        }
        result.push(paper);
    }

    result
}

pub fn normalize_doi(value: &str) -> String {
    value
        .trim()
        .trim_start_matches("https://doi.org/")
        .trim_start_matches("http://doi.org/")
        .trim_start_matches("http://dx.doi.org/")
        .trim_end_matches(['.', ',', ';', ')'])
        .to_ascii_lowercase()
}

pub fn normalize_title(value: &str) -> String {
    let normalized = value
        .nfkc()
        .flat_map(char::to_lowercase)
        .collect::<String>();
    let mut output = String::with_capacity(normalized.len());
    let mut previous_space = false;
    for character in normalized.chars() {
        if character.is_alphanumeric() {
            output.push(character);
            previous_space = false;
        } else if !previous_space && !output.is_empty() {
            output.push(' ');
            previous_space = true;
        }
    }
    output.trim().to_owned()
}

fn merge_paper(existing: &mut Paper, incoming: Paper) {
    existing.citations = existing.citations.max(incoming.citations);
    merge_sources(&mut existing.sources, incoming.source);
    for source in incoming.sources {
        merge_sources(&mut existing.sources, source);
    }
    if existing.abstract_text.is_empty() {
        existing.abstract_text = incoming.abstract_text;
    }
    if existing.authors.is_empty() {
        existing.authors = incoming.authors;
    }
    fill_option(&mut existing.doi, incoming.doi);
    fill_option(&mut existing.issn, incoming.issn);
    fill_option(&mut existing.published_date, incoming.published_date);
    fill_option(&mut existing.year, incoming.year);
    fill_option(&mut existing.pdf_url, incoming.pdf_url);
    fill_option(&mut existing.journal, incoming.journal);
    fill_option(&mut existing.volume, incoming.volume);
    fill_option(&mut existing.issue, incoming.issue);
    fill_option(&mut existing.pages, incoming.pages);
    fill_option(&mut existing.journal_metrics, incoming.journal_metrics);
    if existing.url.is_empty() {
        existing.url = incoming.url;
    }
    if existing.categories.is_empty() {
        existing.categories = incoming.categories;
    }
    if existing.keywords.is_empty() {
        existing.keywords = incoming.keywords;
    }
    for (key, value) in incoming.extra {
        existing.extra.entry(key).or_insert(value);
    }
}

fn merge_sources(sources: &mut Vec<ProviderName>, source: ProviderName) {
    if !sources.contains(&source) {
        sources.push(source);
    }
}

fn fill_option<T>(target: &mut Option<T>, source: Option<T>) {
    if target.is_none() {
        *target = source;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn paper(title: &str, doi: Option<&str>, citations: u64, source: ProviderName) -> Paper {
        Paper {
            paper_id: format!("{source}-{citations}"),
            title: title.into(),
            doi: doi.map(str::to_owned),
            citations,
            source,
            sources: vec![source],
            ..Paper::default()
        }
    }

    #[test]
    fn merges_by_normalized_doi() {
        let papers = deduplicate(vec![
            paper(
                "First",
                Some("https://doi.org/10.1/ABC"),
                1,
                ProviderName::Arxiv,
            ),
            paper("Second", Some("10.1/abc"), 9, ProviderName::Scopus),
        ]);
        assert_eq!(papers.len(), 1);
        assert_eq!(papers[0].citations, 9);
        assert_eq!(papers[0].sources.len(), 2);
    }

    #[test]
    fn merges_nearly_identical_titles() {
        let papers = deduplicate(vec![
            paper("A Study of Rust: Safety", None, 0, ProviderName::Arxiv),
            paper(
                "A study of Rust safety",
                None,
                2,
                ProviderName::SemanticScholar,
            ),
        ]);
        assert_eq!(papers.len(), 1);
    }
}
