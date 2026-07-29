"""End-to-end ResearchPulse pipeline.

Steps:
  1. Load config + subscribers.
  2. Determine which topics anyone actually subscribed to (avoid wasted fetches).
  3. Fetch papers per topic (arXiv + bioRxiv + OpenAlex), drop already-seen ones.
  4. Rank, trim to top N, and summarize.
  5. Fetch shared research news (RSS).
  6. Render + send a personalized digest to each subscriber.
  7. Persist the dedup cache.

Run locally without sending:
    python -m research_agent.pipeline --dry-run
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

from . import config as cfg
from .log import get as _log

log = _log("pipeline")
from .cache import SeenCache
from .models import Paper
from .rank import rank_for_topic
from .render import render_digest
from .summarize import Summarizer
from .subscribers import Subscriber, load_subscribers
from .sources import arxiv, biorxiv, europepmc, openalex, rss, semanticscholar
from .subscription import get_due_subscriptions, mark_sent

PREVIEW_DIR = cfg.ROOT / "preview"


def _active_topic_ids(subs: List[Subscriber], known: Set[str]) -> Set[str]:
    active: Set[str] = set()
    for s in subs:
        active.update(t for t in s.topics if t in known)
    return active


def _fetch_topic(topic: cfg.Topic, settings: cfg.Settings, secrets: cfg.Secrets) -> List[Paper]:
    """Fetch one topic from every configured source.

    Non-arXiv sources run in parallel; arXiv runs separately because it asks
    for a polite delay between requests (enforced by the caller's ordering).
    """
    papers: List[Paper] = []

    jobs = []
    if topic.biorxiv:
        jobs.append(lambda: biorxiv.fetch(topic.biorxiv, lookback_days=settings.lookback_days))
    if topic.openalex:
        jobs.append(lambda: openalex.fetch(
            topic.openalex,
            lookback_days=settings.lookback_days,
            mailto=secrets.sender_email,
        ))
    if topic.semanticscholar:
        jobs.append(lambda: semanticscholar.fetch(
            topic.semanticscholar,
            lookback_days=settings.lookback_days,
        ))
    if topic.europepmc:
        jobs.append(lambda: europepmc.fetch(
            topic.europepmc,
            lookback_days=settings.lookback_days,
        ))

    if jobs:
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futures = [pool.submit(j) for j in jobs]
            for fut in as_completed(futures):
                try:
                    papers += fut.result()
                except Exception as exc:  # a failed source never kills the digest
                    log.warning("source fetch failed for %s: %s", topic.id, exc)

    if topic.arxiv:
        papers += arxiv.fetch(
            topic.arxiv,
            lookback_days=settings.lookback_days,
            delay=settings.arxiv_request_delay,
        )
    return papers


def _normalize_title(title: str) -> str:
    """Normalize a paper title for fuzzy dedup across sources."""
    import re
    return re.sub(r"[^a-z0-9]", "", title.lower())


def _dedup(papers: List[Paper], cache: SeenCache) -> List[Paper]:
    """Remove duplicates by ID, by normalized title, and against the seen cache."""
    out: List[Paper] = []
    seen_ids: Set[str] = set()
    seen_titles: Set[str] = set()
    for p in papers:
        if not p.id or p.id in seen_ids or cache.is_seen(p.id):
            continue
        title_key = _normalize_title(p.title) if p.title else ""
        if title_key and title_key in seen_titles:
            continue
        seen_ids.add(p.id)
        if title_key:
            seen_titles.add(title_key)
        out.append(p)
    return out


def run(dry_run: bool = False, limit_subscribers: Optional[int] = None,
        topic_override: Optional[List[str]] = None,
        on_progress: Optional[Callable[[str], None]] = None) -> int:
    topics, feeds = cfg.load_topics()
    settings = cfg.load_settings()
    secrets = cfg.load_secrets()
    by_id = cfg.topics_by_id(topics)
    topic_labels = {t.id: t.label for t in topics}

    # Local CLI runs can override papers_per_topic via data/local.json.
    papers_limit = settings.papers_per_topic
    if topic_override is not None:
        from .local_config import effective_papers_per_topic
        papers_limit = effective_papers_per_topic()

    local_subs_tokens: List[str] = []

    if topic_override:
        subscribers = [Subscriber(email="local@preview", topics=topic_override)]
        log.info("local preview mode with topics: %s", topic_override)
    else:
        subscribers = load_subscribers(secrets)

        due_local = get_due_subscriptions()
        if due_local:
            for ls in due_local:
                subscribers.append(Subscriber(
                    email=ls.email,
                    topics=ls.topics,
                    token=ls.token,
                ))
                local_subs_tokens.append(ls.token)
            log.info(
                "%d due local subscription(s): %s",
                len(due_local),
                ", ".join(f"{s.email}[{s.frequency}]" for s in due_local),
            )

        if limit_subscribers:
            subscribers = subscribers[:limit_subscribers]
    log.info("%d confirmed subscriber(s)", len(subscribers))
    if not subscribers:
        log.info("nothing to do.")
        return 0

    cache = SeenCache()
    summarizer = Summarizer(secrets, settings.abstract_max_chars)
    log.info("summarizer backend: %s", summarizer.backend)

    active = _active_topic_ids(subscribers, set(by_id))
    log.info("fetching %d active topic(s): %s", len(active), sorted(active))

    papers_by_topic: Dict[str, List[Paper]] = {}
    fresh_ids: List[str] = []
    for topic_id in sorted(active):
        topic = by_id[topic_id]
        if on_progress:
            on_progress(f"fetch:{topic_id}")
        raw = _fetch_topic(topic, settings, secrets)
        if on_progress:
            on_progress(f"raw:{topic_id}:{len(raw)}")
        fresh = _dedup(raw, cache)
        ranked = rank_for_topic(fresh, topic, papers_limit)
        summarizer.annotate(ranked)
        papers_by_topic[topic_id] = ranked
        fresh_ids.extend(p.id for p in ranked)
        log.info("  %s: %d fetched -> %d selected", topic_id, len(raw), len(ranked))
        if on_progress:
            on_progress(f"done:{topic_id}:{len(raw)}:{len(ranked)}")

    news = rss.fetch(feeds, per_feed=max(2, settings.news_items))[: settings.news_items]
    log.info("%d news item(s)", len(news))
    if on_progress:
        on_progress(f"news:{len(news)}")

    sent = 0
    if dry_run:
        PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
        if on_progress:
            on_progress("render:preview")
        for sub in subscribers:
            html = render_digest(
                sub, papers_by_topic, topic_labels, news, settings, secrets
            )
            safe = sub.email.replace("@", "_at_").replace("/", "_")
            out = PREVIEW_DIR / f"{safe}.html"
            out.write_text(html, encoding="utf-8")
            sent += 1
            log.info("  [dry-run] wrote %s", out)
        log.info("dry run complete: %d preview file(s) in %s", sent, PREVIEW_DIR)
        return 0

    from .mailer import Mailer

    mailer = Mailer(secrets)
    if not mailer.configured:
        log.error("SMTP not configured. Set SMTP_* and SENDER_EMAIL, or use --dry-run.")
        return 1

    subject = f"{settings.newsletter_name}: your research digest - {datetime.now():%b %d}"
    sent_topic_ids: Set[str] = set()
    sent_local_tokens: Set[str] = set()
    with mailer:
        for sub in subscribers:
            html = render_digest(
                sub, papers_by_topic, topic_labels, news, settings, secrets
            )
            if mailer.send(sub.email, subject, html):
                sent += 1
                sent_topic_ids.update(sub.topics)
                if sub.token and sub.token in local_subs_tokens:
                    sent_local_tokens.add(sub.token)
            time.sleep(0.5)

    for token in sent_local_tokens:
        mark_sent(token)
    if sent_local_tokens:
        log.info("updated last_sent for %d local subscription(s)", len(sent_local_tokens))

    log.info("sent %d/%d digest(s)", sent, len(subscribers))

    # Only mark papers as seen for topics where at least one subscriber
    # received the digest, so failed sends get retried next run.
    actually_sent_ids = []
    for tid in sent_topic_ids:
        for p in papers_by_topic.get(tid, []):
            actually_sent_ids.append(p.id)
    if actually_sent_ids:
        cache.mark(actually_sent_ids)
        cache.save()
        log.info("cache updated.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="ResearchPulse daily digest pipeline")
    parser.add_argument("--dry-run", action="store_true",
                        help="Render previews to ./preview without sending or updating cache.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Only process the first N subscribers (testing).")
    parser.add_argument("--topics", nargs="+", default=None,
                        help="Override subscriber topics for a local-only run (e.g. --topics ai-ml nlp).")
    parser.add_argument("--open", action="store_true",
                        help="Open the first preview in the default browser (implies --dry-run).")
    args = parser.parse_args(argv)
    if args.open:
        args.dry_run = True
    if args.topics:
        args.dry_run = True
    rc = run(dry_run=args.dry_run, limit_subscribers=args.limit,
             topic_override=args.topics)
    if args.open and rc == 0:
        _open_preview()
    return rc


def _open_preview() -> None:
    """Open the first HTML preview in the default browser."""
    import webbrowser
    previews = sorted(PREVIEW_DIR.glob("*.html"))
    if previews:
        webbrowser.open(previews[0].as_uri())


if __name__ == "__main__":
    sys.exit(main())
