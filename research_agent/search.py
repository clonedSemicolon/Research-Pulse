"""On-demand keyword search across research sources.

Unlike the daily digest (which searches by topic/category), this module
enables free-text search across arXiv, OpenAlex, Semantic Scholar, Crossref,
and Europe PMC for interactive agent queries.

Now uses BM25 ranking for better relevance scoring.

Usage:
    from research_agent.search import search_papers
    results = search_papers("transformer attention efficiency", limit=10)
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from typing import Callable, Dict, List, Optional, Tuple

from .bm25 import rank_papers_combined
from .config import load_settings, load_secrets
from .models import Paper
from .sources import arxiv, openalex, biorxiv, crossref, semanticscholar, europepmc
from .venues import enrich_papers, filter_papers

# ── Search Cache ─────────────────────────────────────────────────────────
# Simple in-memory cache to avoid repeated API calls for the same query

class SearchCache:
    """Cache search results with TTL (time-to-live)."""

    def __init__(self, ttl_seconds: int = 300):  # 5 minutes TTL
        self._cache: Dict[str, Tuple[List[Paper], float]] = {}
        self._ttl = ttl_seconds

    def get(self, key: str) -> Optional[List[Paper]]:
        """Get cached result if it exists and hasn't expired."""
        if key in self._cache:
            result, timestamp = self._cache[key]
            if time.time() - timestamp < self._ttl:
                return result
            else:
                del self._cache[key]
        return None

    def set(self, key: str, result: List[Paper]) -> None:
        """Cache a search result."""
        self._cache[key] = (result, time.time())

    def clear(self) -> None:
        """Clear all cached results."""
        self._cache.clear()

# Global cache instance
_search_cache = SearchCache(ttl_seconds=300)


def _keyword_score(paper: Paper, query: str) -> float:
    """Score a paper's relevance to a free-text query (legacy method)."""
    if not query:
        return 0.0

    query_terms = query.lower().split()
    title_lower = paper.title.lower()
    abstract_lower = paper.abstract.lower()
    haystack = f"{title_lower} {abstract_lower}"

    hits = 0
    for term in query_terms:
        if term in title_lower:
            hits += 3  # Title match is strongest signal
        elif term in abstract_lower:
            hits += 1

    # Normalize by query length
    max_possible = len(query_terms) * 3
    return hits / max_possible if max_possible > 0 else 0.0


def _dedup(papers: List[Paper]) -> List[Paper]:
    """Remove duplicate papers using DOI and title matching."""
    seen_dois = set()
    seen_titles = set()
    unique = []

    for p in papers:
        # Try DOI first
        doi = p.id
        if doi and doi in seen_dois:
            continue

        # Try normalized title
        title_key = re.sub(r'[^a-z0-9]', '', p.title.lower())
        if title_key in seen_titles:
            continue

        # Add to unique list
        if doi:
            seen_dois.add(doi)
        seen_titles.add(title_key)
        unique.append(p)

    return unique


def search_arxiv(query: str, days: int = 30, limit: int = 20) -> List[Paper]:
    """Search arXiv by keyword (not category)."""
    if not query:
        return []

    # Build a keyword search query for arXiv API
    terms = query.strip()
    search_query = f'all:"{terms}"'

    import feedparser
    from .sources.http import get
    from .sources.arxiv import API_URL
    import time

    params = {
        "search_query": search_query,
        "start": 0,
        "max_results": min(limit * 2, 50),
        "sortBy": "relevance",
        "sortOrder": "descending",
    }

    settings = load_settings()
    resp = get(API_URL, params=params)
    time.sleep(settings.arxiv_request_delay)

    if resp is None:
        return []

    feed = feedparser.parse(resp.content)
    papers = []
    for entry in feed.entries:
        papers.append(arxiv._paper_from_entry(entry))

    return papers[:limit]


def search_openalex(query: str, days: int = 30, limit: int = 20,
                    venue: Optional[str] = None) -> List[Paper]:
    """Search OpenAlex by keyword."""
    if not query:
        return []

    secrets = load_secrets()
    results = openalex.fetch(
        query=query,
        lookback_days=days,
        max_results=min(limit * 2, 50),
        mailto=secrets.sender_email,
        venue=venue,
    )

    return results[:limit]


def search_crossref(query: str, days: int = 30, limit: int = 20,
                    venue: Optional[str] = None) -> List[Paper]:
    """Search Crossref by keyword."""
    if not query:
        return []

    secrets = load_secrets()
    results = crossref.fetch(
        query=query,
        lookback_days=days,
        max_results=min(limit * 2, 50),
        mailto=secrets.sender_email,
        venue=venue,
    )

    return results[:limit]


def search_semanticscholar(query: str, days: int = 0, limit: int = 20) -> List[Paper]:
    """Search Semantic Scholar by keyword (all research fields)."""
    if not query:
        return []

    results = semanticscholar.fetch(
        query=query,
        lookback_days=days,
        max_results=min(limit * 2, 50),
    )

    return results[:limit]


def search_europepmc(query: str, days: int = 0, limit: int = 20) -> List[Paper]:
    """Search Europe PMC by keyword (life sciences / biomedical)."""
    if not query:
        return []

    results = europepmc.fetch(
        query=query,
        lookback_days=days,
        max_results=min(limit * 2, 50),
    )

    return results[:limit]


def search_papers(query: str, sources: Optional[List[str]] = None,
                  days: int = 30, limit: int = 10,
                  min_citations: int = 0,
                  use_bm25: bool = True,
                  venues: Optional[List[str]] = None,
                  core_min: Optional[str] = None,
                  year: Optional[int] = None,
                  on_source: Optional[Callable[[str, str, int], None]] = None,
                  use_cache: bool = True
                  ) -> List[Paper]:
    """Search across multiple sources by keyword.

    Args:
        query: Free-text search query
        sources: List of sources to search. Defaults to
                 ["arxiv", "openalex", "semanticscholar", "crossref"].
                 Options: "arxiv", "openalex", "semanticscholar", "crossref",
                 "europepmc"
        days: Look back N days (default 30)
        limit: Maximum results to return (default 10)
        min_citations: Minimum citation count filter (default 0)
        use_bm25: Whether to use BM25 ranking (default True)
        venues: Optional list of conference/journal names or catalog ids
        core_min: Minimum CORE rank (A*, A, B, C)
        year: Publication year filter
        use_cache: Whether to use cached results (default True)

    Returns:
        List of Paper objects sorted by relevance to query.
    """
    if not query.strip():
        return []

    # Check cache first
    if use_cache:
        cache_key = f"{query}:{days}:{limit}:{','.join(sources or [])}:{min_citations}:{use_bm25}"
        cached = _search_cache.get(cache_key)
        if cached is not None:
            return cached

    if sources is None:
        # Semantic Scholar self-skips unless S2_API_KEY is set, so including
        # it here just means it lights up automatically when a key exists.
        sources = ["arxiv", "openalex", "semanticscholar", "crossref"]

    api_venue = venues[0] if venues and len(venues) == 1 else None

    fetchers = {
        "arxiv": lambda: search_arxiv(query, days, limit),
        "openalex": lambda: search_openalex(query, days, limit, venue=api_venue),
        "semanticscholar": lambda: search_semanticscholar(query, days, limit),
        "crossref": lambda: search_crossref(query, days, limit, venue=api_venue),
        "europepmc": lambda: search_europepmc(query, days, limit),
    }
    selected_names = [s for s in sources if s in fetchers]
    selected = [fetchers[s] for s in selected_names]

    # Query every source in parallel; each already has retries + timeouts.
    all_papers: List[Paper] = []
    with ThreadPoolExecutor(max_workers=max(len(selected), 1)) as pool:
        future_to_source = {
            pool.submit(fn): name for name, fn in zip(selected_names, selected)
        }
        for fut in as_completed(future_to_source):
            src = future_to_source[fut]
            try:
                batch = fut.result()
                all_papers.extend(batch)
                if on_source:
                    on_source(src, "done", len(batch))
            except Exception:
                if on_source:
                    on_source(src, "failed", 0)
                continue

    # Deduplicate
    unique = _dedup(all_papers)
    enrich_papers(unique)

    # Venue / CORE / year filters (post-fetch; works across all sources)
    if venues or core_min or year is not None:
        unique = filter_papers(unique, venues=venues, core_min=core_min, year=year)

    # Apply citation filter
    if min_citations > 0:
        unique = [p for p in unique if p.citations >= min_citations]

    # Rank papers
    if use_bm25 and unique:
        # Use BM25 ranking
        ranked = rank_papers_combined(unique, query)
        unique = [paper for paper, score in ranked]
        # Update paper scores
        for paper, score in ranked:
            paper.score = score
    else:
        # Use simple keyword scoring
        for p in unique:
            p.score = _keyword_score(p, query)
        unique.sort(key=lambda p: p.score, reverse=True)

    result = unique[:limit]

    # Cache the result
    if use_cache:
        cache_key = f"{query}:{days}:{limit}:{','.join(sources or [])}:{min_citations}:{use_bm25}"
        _search_cache.set(cache_key, result)

    return result


def search_by_topic(topic_id: str, days: int = 7, limit: int = 10, use_cache: bool = True) -> List[Paper]:
    """Search for papers in a specific topic (uses topic config).

    This is useful when the user wants to see recent papers in a known topic
    without waiting for the daily digest.
    """
    from .config import load_topics, topics_by_id

    # Check cache first
    if use_cache:
        cache_key = f"topic:{topic_id}:{days}:{limit}"
        cached = _search_cache.get(cache_key)
        if cached is not None:
            return cached

    topics, _ = load_topics()
    by_id = topics_by_id(topics)

    if topic_id not in by_id:
        return []

    topic = by_id[topic_id]
    settings = load_settings()
    secrets = load_secrets()

    papers: List[Paper] = []

    if topic.arxiv:
        papers += arxiv.fetch(
            topic.arxiv,
            lookback_days=days,
            delay=settings.arxiv_request_delay,
        )

    if topic.biorxiv:
        papers += biorxiv.fetch(topic.biorxiv, lookback_days=days)

    if topic.openalex:
        papers += openalex.fetch(
            topic.openalex,
            lookback_days=days,
            mailto=secrets.sender_email,
        )

    if topic.semanticscholar:
        papers += semanticscholar.fetch(topic.semanticscholar, lookback_days=days)

    if topic.europepmc:
        papers += europepmc.fetch(topic.europepmc, lookback_days=days)

    # Deduplicate
    unique = _dedup(papers)

    # Score and rank using BM25
    query = " ".join(topic.keywords)
    if unique:
        ranked = rank_papers_combined(unique, query)
        unique = [paper for paper, score in ranked]
        for paper, score in ranked:
            paper.score = score

    result = unique[:limit]

    # Cache the result
    if use_cache:
        cache_key = f"topic:{topic_id}:{days}:{limit}"
        _search_cache.set(cache_key, result)

    return result


def search_all_sources(query: str, days: int = 30, limit: int = 10) -> List[Paper]:
    """Search across ALL available sources.

    Convenience function that searches arXiv, OpenAlex, Semantic Scholar,
    Crossref, and Europe PMC.

    Args:
        query: Free-text search query
        days: Look back N days
        limit: Maximum results per source

    Returns:
        List of Paper objects sorted by relevance
    """
    return search_papers(
        query=query,
        sources=["arxiv", "openalex", "semanticscholar", "crossref", "europepmc"],
        days=days,
        limit=limit,
        use_bm25=True,
    )
