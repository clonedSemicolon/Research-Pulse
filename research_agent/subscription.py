"""Local subscription management — backward-compatible shim.

All logic has moved to research_agent.subscribe.*. This module re-exports
every public name so existing imports continue to work.
"""

from .subscribe.models import FREQUENCY_DAYS, FREQUENCY_LABELS, Subscription
from .subscribe.storage import (
    SUBSCRIPTIONS_PATH,
    add_subscription,
    add_topic_to_subscription,
    get_due_subscriptions,
    get_subscription_by_email,
    is_due,
    load_subscriptions,
    mark_failed,
    mark_sent,
    remove_by_email,
    remove_subscription,
    subscription_count,
)

__all__ = [
    "FREQUENCY_DAYS",
    "FREQUENCY_LABELS",
    "SUBSCRIPTIONS_PATH",
    "Subscription",
    "add_subscription",
    "add_topic_to_subscription",
    "get_due_subscriptions",
    "get_subscription_by_email",
    "is_due",
    "load_subscriptions",
    "mark_failed",
    "mark_sent",
    "remove_by_email",
    "remove_subscription",
    "subscription_count",
]
