"""Subscription service layer: merge, active topics, and send logic.

Used by the pipeline to combine CSV and local subscribers, determine
which topics to fetch, and update last_sent after delivery.
"""

from __future__ import annotations

from typing import List, Set, Tuple

from ..log import get as _log
from .models import Subscriber, Subscription
from .csv_loader import load_subscribers
from .storage import get_due_subscriptions, mark_sent

log = _log("subscribe.service")


def active_topic_ids(subs: List[Subscriber], known: Set[str]) -> Set[str]:
    """Return the union of subscriber topic IDs that exist in topics.yaml.

    Logs a warning for any subscriber topic not in the known set.
    """
    active: Set[str] = set()
    for s in subs:
        for t in s.topics:
            if t in known:
                active.add(t)
            else:
                log.warning(
                    "subscriber %s has topic %r not in topics.yaml — "
                    "papers for this topic will not be fetched",
                    s.email, t,
                )
    return active


def merge_subscribers(
    csv_subs: List[Subscriber],
    due_local: List[Subscription],
) -> Tuple[List[Subscriber], List[str]]:
    """Merge CSV and local subscribers, returning (subscribers, local_tokens).

    Deduplicates by email (case-insensitive). When a local subscription's
    email matches a CSV subscriber, the local topics are merged into the CSV
    entry. The local token is always tracked so mark_sent fires after send.
    """
    subscribers = list(csv_subs)
    local_subs_tokens: List[str] = []
    csv_emails = {s.email.lower() for s in subscribers}

    for ls in due_local:
        if ls.email.lower() not in csv_emails:
            subscribers.append(Subscriber(
                email=ls.email,
                topics=ls.topics,
                token=ls.token,
            ))
        else:
            for s in subscribers:
                if s.email.lower() == ls.email.lower():
                    merged = set(s.topics)
                    merged.update(ls.topics)
                    s.topics = sorted(merged)
                    break
            log.info("skipping duplicate: %s (already in CSV)", ls.email)
        local_subs_tokens.append(ls.token)

    return subscribers, local_subs_tokens


def mark_sent_batch(tokens: Set[str]) -> None:
    """Call mark_sent for each token in the set."""
    for token in tokens:
        mark_sent(token)
