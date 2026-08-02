"""CSV subscriber loading — backward-compatible shim.

All logic has moved to research_agent.subscribe.csv_loader. This module
re-exports every public name so existing imports continue to work.
"""

from .subscribe.csv_loader import load_subscribers
from .subscribe.models import Subscriber

__all__ = ["Subscriber", "load_subscribers"]
