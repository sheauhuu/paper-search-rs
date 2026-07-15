"""Searcher registry — maps platform names to searcher classes."""

from __future__ import annotations

from typing import Dict, Type

from .base import BaseSearcher
from .arxiv import ArxivSearcher
from .semantic_scholar import SemanticScholarSearcher
from .google_scholar import GoogleScholarSearcher
from .crossref import CrossRefSearcher
from .openalex import OpenAlexSearcher
from .pubmed import PubMedSearcher
from .scopus import ScopusSearcher
from .biorxiv import BioRxivSearcher, MedRxivSearcher
from .webofscience import WebOfScienceSearcher

SEARCHER_REGISTRY: Dict[str, Type[BaseSearcher]] = {
    "arxiv": ArxivSearcher,
    "semantic_scholar": SemanticScholarSearcher,
    "google_scholar": GoogleScholarSearcher,
    "crossref": CrossRefSearcher,
    "openalex": OpenAlexSearcher,
    "pubmed": PubMedSearcher,
    "scopus": ScopusSearcher,
    "biorxiv": BioRxivSearcher,
    "medrxiv": MedRxivSearcher,
    "webofscience": WebOfScienceSearcher,
}
