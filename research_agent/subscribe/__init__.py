"""Subscribe module: subscription management, CLI commands, and pipeline integration.

Submodules:
    models     — Subscription/Subscriber dataclasses, FREQUENCY_DAYS/LABELS
    storage    — CRUD operations on data/subscriptions.json
    csv_loader — Load subscribers from published CSV
    cli        — CLI commands (subscribe, unsubscribe, subscriber, send-digest, send-to)
    service    — Pipeline integration (merge, active topics, mark_sent batch)
"""

from .models import FREQUENCY_DAYS, FREQUENCY_LABELS, Subscriber, Subscription
from .storage import (
    SUBSCRIPTIONS_PATH,
    add_subscription,
    add_topic_to_subscription,
    get_due_subscriptions,
    get_subscription_by_email,
    is_due,
    load_subscriptions,
    mark_sent,
    remove_by_email,
    remove_subscription,
    subscription_count,
)
from .csv_loader import load_subscribers
from .service import active_topic_ids, mark_sent_batch, merge_subscribers

__all__ = [
    "FREQUENCY_DAYS",
    "FREQUENCY_LABELS",
    "SUBSCRIPTIONS_PATH",
    "Subscription",
    "Subscriber",
    "active_topic_ids",
    "add_subscription",
    "add_topic_to_subscription",
    "get_due_subscriptions",
    "get_subscription_by_email",
    "is_due",
    "load_subscribers",
    "load_subscriptions",
    "mark_sent",
    "mark_sent_batch",
    "merge_subscribers",
    "remove_by_email",
    "remove_subscription",
    "subscription_count",
]
