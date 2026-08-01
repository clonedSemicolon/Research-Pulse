"""Subscription data models and constants."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


FREQUENCY_DAYS: Dict[str, int] = {
    "3days": 3,
    "weekly": 7,
    "biweekly": 14,
    "monthly": 30,
}

FREQUENCY_LABELS: Dict[str, str] = {
    "3days": "Every 3 days",
    "weekly": "Weekly",
    "biweekly": "Biweekly (every 2 weeks)",
    "monthly": "Monthly",
}


@dataclass
class Subscription:
    """A local subscription stored in data/subscriptions.json."""
    email: str
    frequency: str
    topics: List[str] = field(default_factory=list)
    token: str = ""
    confirmed: bool = True
    created_at: str = ""
    last_sent: str = ""


@dataclass
class Subscriber:
    """A subscriber loaded from CSV (Google Sheet or local sample)."""
    email: str
    topics: List[str] = field(default_factory=list)
    token: str = ""
