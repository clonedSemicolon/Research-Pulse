"""Relevance ranking and per-topic selection.

No LLM required: papers are scored with a transparent heuristic combining
keyword relevance, recency, and (when available) early citation counts. This
keeps the default pipeline zero-cost while still surfacing the best items.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from functools import lru_cache
from typing import List

from .config import Topic
from .models import Paper
from .venues import CORE_ORDER, enrich_paper, lookup_core

# Bare stopwords are useless relevance signals; auto-generated topics
# (e.g. `follow "machine learning for healthcare"`) may contain them.
_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in",
    "into", "is", "it", "of", "on", "or", "the", "to", "using", "via", "with",
})


@lru_cache(maxsize=1024)
def _keyword_pattern(keyword: str) -> "re.Pattern[str]":
    """Whole-word (or whole-phrase) matcher, tolerant of a plural 's'.

    Substring matching produced false positives ("text" in "context",
    "gene" in "generated", "rna" in "international"); word boundaries
    fix that while `s?` still catches simple plurals ("transformers").
    """
    return re.compile(r"(?<!\w)" + re.escape(keyword) + r"s?(?!\w)")


def _scoring_keywords(keywords: List[str]) -> List[str]:
    return [k for k in keywords if k.strip() and k.lower() not in _STOPWORDS]


def _keyword_hits(paper: Paper, keywords: List[str]) -> int:
    """Weighted whole-word hits: title matches count double."""
    title = paper.title.lower()
    abstract = paper.abstract.lower()
    hits = 0
    for kw in keywords:
        pattern = _keyword_pattern(kw.lower())
        if pattern.search(title):
            hits += 2
        elif pattern.search(abstract):
            hits += 1
    return hits


def _keyword_score(paper: Paper, keywords: List[str]) -> float:
    kws = _scoring_keywords(keywords)
    if not kws:
        return 0.0
    return _keyword_hits(paper, kws) / (len(kws) * 2)


def _recency_score(paper: Paper) -> float:
    if not paper.published:
        return 0.3
    age_days = (datetime.now(timezone.utc) - paper.published).total_seconds() / 86400
    # 1.0 today, decaying gently over a week.
    return max(0.0, 1.0 - (age_days / 7.0))


def _citation_score(paper: Paper) -> float:
    if paper.citations <= 0:
        return 0.0
    # Log-dampened so a few early citations help without dominating.
    return min(1.0, math.log10(paper.citations + 1) / 2.0)


def _core_score(paper: Paper) -> float:
    rank = paper.core_rank or lookup_core(paper.venue)
    return CORE_ORDER.get(rank, 0) / 4.0


def score_paper(paper: Paper, topic: Topic) -> float:
    enrich_paper(paper)
    return (
        0.50 * _keyword_score(paper, topic.keywords)
        + 0.25 * _recency_score(paper)
        + 0.15 * _citation_score(paper)
        + 0.10 * _core_score(paper)
    )


# Sources that are already topically filtered upstream (by category / server)
# and may therefore be kept even with a weak textual keyword match.
_CURATED_SOURCES = {"arxiv", "biorxiv", "medrxiv"}


def _relevant(paper: Paper, topic: Topic) -> bool:
    """Drop obviously off-topic items from broad full-text sources (OpenAlex).

    arXiv/bioRxiv are pre-filtered by category, so they pass through. Broad
    sources need real topical evidence: a whole-word keyword match in the
    title, or at least two distinct keyword hits in the abstract. A single
    incidental abstract mention is no longer enough.
    """
    kws = _scoring_keywords(topic.keywords)
    if not kws:
        return True
    if paper.source.lower() in _CURATED_SOURCES:
        return True
    threshold = 2 if len(kws) > 1 else 1
    return _keyword_hits(paper, kws) >= threshold


def rank_for_topic(papers: List[Paper], topic: Topic, limit: int) -> List[Paper]:
    """Filter for relevance, score, sort, and trim papers for a single topic."""
    candidates = [p for p in papers if _relevant(p, topic)]
    for p in candidates:
        p.score = score_paper(p, topic)
    ranked = sorted(candidates, key=lambda p: p.score, reverse=True)
    return ranked[:limit]
