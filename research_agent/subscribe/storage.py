"""Local subscription storage (data/subscriptions.json).

Provides CRUD operations, frequency checking, and mark_sent tracking
for subscriptions managed via the CLI.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..config import ROOT
from .models import FREQUENCY_DAYS, Subscription

SUBSCRIPTIONS_PATH = ROOT / "data" / "subscriptions.json"


def _load_raw() -> dict:
    if not SUBSCRIPTIONS_PATH.exists():
        return {}
    try:
        return json.loads(SUBSCRIPTIONS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_raw(data: dict) -> None:
    SUBSCRIPTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUBSCRIPTIONS_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_subscriptions() -> List[Subscription]:
    raw = _load_raw()
    subs: List[Subscription] = []
    for item in raw.get("subscriptions", []):
        subs.append(Subscription(
            email=item.get("email", ""),
            frequency=item.get("frequency", "daily"),
            topics=item.get("topics", []),
            token=item.get("token", ""),
            confirmed=item.get("confirmed", True),
            created_at=item.get("created_at", ""),
            last_sent=item.get("last_sent", ""),
        ))
    return subs


def add_subscription(email: str, frequency: str, topics: List[str]) -> Subscription:
    raw = _load_raw()
    subs = raw.get("subscriptions", [])

    for s in subs:
        if s.get("email", "").lower() == email.lower():
            s["frequency"] = frequency
            s["topics"] = topics
            raw["subscriptions"] = subs
            _save_raw(raw)
            return Subscription(
                email=s["email"],
                frequency=s["frequency"],
                topics=s["topics"],
                token=s.get("token", ""),
                confirmed=s.get("confirmed", True),
                created_at=s.get("created_at", ""),
                last_sent=s.get("last_sent", ""),
            )

    now = datetime.now(timezone.utc).isoformat()
    token = uuid.uuid4().hex[:12]

    entry = {
        "email": email,
        "frequency": frequency,
        "topics": topics,
        "token": token,
        "confirmed": True,
        "created_at": now,
        "last_sent": "",
    }
    subs.append(entry)
    raw["subscriptions"] = subs
    _save_raw(raw)
    return Subscription(**entry)  # type: ignore[arg-type]


def remove_subscription(token: str) -> bool:
    raw = _load_raw()
    subs = raw.get("subscriptions", [])
    before = len(subs)
    raw["subscriptions"] = [s for s in subs if s.get("token") != token]
    _save_raw(raw)
    return len(raw["subscriptions"]) < before


def remove_by_email(email: str) -> bool:
    raw = _load_raw()
    subs = raw.get("subscriptions", [])
    before = len(subs)
    raw["subscriptions"] = [
        s for s in subs if s.get("email", "").lower() != email.lower()
    ]
    _save_raw(raw)
    return len(raw["subscriptions"]) < before


def add_topic_to_subscription(email: str, topic: str) -> bool:
    """Add a topic to an existing subscription. Returns True if updated."""
    raw = _load_raw()
    subs = raw.get("subscriptions", [])

    for s in subs:
        if s.get("email", "").lower() == email.lower():
            topics = s.get("topics", [])
            if topic not in topics:
                topics.append(topic)
                s["topics"] = topics
                raw["subscriptions"] = subs
                _save_raw(raw)
            return True
    return False


def get_subscription_by_email(email: str) -> Optional[Subscription]:
    """Get subscription by email address."""
    raw = _load_raw()
    for item in raw.get("subscriptions", []):
        if item.get("email", "").lower() == email.lower():
            return Subscription(
                email=item.get("email", ""),
                frequency=item.get("frequency", "daily"),
                topics=item.get("topics", []),
                token=item.get("token", ""),
                confirmed=item.get("confirmed", True),
                created_at=item.get("created_at", ""),
                last_sent=item.get("last_sent", ""),
            )
    return None


def is_due(sub: Subscription) -> bool:
    """Check whether a subscription should be sent today."""
    if not sub.last_sent:
        return True

    try:
        last = datetime.fromisoformat(sub.last_sent)
    except (ValueError, TypeError):
        return True

    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)

    days_needed = FREQUENCY_DAYS.get(sub.frequency, 1)
    now = datetime.now(timezone.utc)
    delta = (now - last).days

    return delta >= days_needed


def get_due_subscriptions() -> List[Subscription]:
    return [s for s in load_subscriptions() if s.confirmed and is_due(s)]


def mark_sent(token: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    raw = _load_raw()
    for item in raw.get("subscriptions", []):
        if item.get("token") == token:
            item["last_sent"] = now
            break
    _save_raw(raw)


def subscription_count() -> int:
    return len(load_subscriptions())
