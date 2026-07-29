"""Local user preferences (topics, etc.) stored in data/local.json.

First run auto-detects topics from Zotero when available, otherwise uses
sensible defaults. After that, just run `research-pulse` with no flags.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from .config import ROOT, load_topics, topics_by_id

LOCAL_PATH = ROOT / "data" / "local.json"
DEFAULT_TOPICS = ["ai-ml", "nlp"]
MIN_PAPERS_PER_TOPIC = 1
MAX_PAPERS_PER_TOPIC = 25


def _load_raw() -> dict:
    if not LOCAL_PATH.exists():
        return {}
    try:
        return json.loads(LOCAL_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_local(data: dict) -> None:
    LOCAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def save(topics: List[str], source: str = "manual") -> bool:
    """Persist the user's topic choices. Returns False if every id was invalid."""
    # Load all topics including custom ones from topics.yaml
    topics_list, _ = load_topics()
    valid = set(t.id for t in topics_list)
    cleaned = [t for t in topics if t in valid]
    if topics and not cleaned:
        return False
    if not cleaned:
        cleaned = list(DEFAULT_TOPICS)
    data = _load_raw()
    data["topics"] = cleaned
    data["source"] = source
    _write_local(data)
    return True


def get_topics() -> List[str]:
    """Return saved topics, or empty if never configured."""
    topics = _load_raw().get("topics", [])
    return topics if isinstance(topics, list) else []


def get_source() -> str:
    return _load_raw().get("source", "")


def get_papers_per_topic() -> Optional[int]:
    """User override for digest size, or None to use config/settings.yaml."""
    val = _load_raw().get("papers_per_topic")
    if isinstance(val, int) and MIN_PAPERS_PER_TOPIC <= val <= MAX_PAPERS_PER_TOPIC:
        return val
    return None


def set_papers_per_topic(count: int) -> None:
    """Save papers-per-topic for local digests (stored in data/local.json)."""
    if not MIN_PAPERS_PER_TOPIC <= count <= MAX_PAPERS_PER_TOPIC:
        raise ValueError(
            f"Count must be between {MIN_PAPERS_PER_TOPIC} and {MAX_PAPERS_PER_TOPIC}"
        )
    data = _load_raw()
    data["papers_per_topic"] = count
    if not data.get("topics"):
        data["topics"] = get_topics() or list(DEFAULT_TOPICS)
    _write_local(data)


def clear_papers_per_topic() -> None:
    """Remove local override; fall back to config/settings.yaml."""
    data = _load_raw()
    data.pop("papers_per_topic", None)
    _write_local(data)


def effective_papers_per_topic() -> int:
    """Papers per topic for the local digest (local override → settings.yaml)."""
    override = get_papers_per_topic()
    if override is not None:
        return override
    from .config import load_settings
    return load_settings().papers_per_topic


def ensure_ready(verbose: bool = True, force_zotero: bool = False) -> List[str]:
    """Return topic list; auto-configure silently on first run.

    If force_zotero is True, re-detect from Zotero and save (when available).
    Manual topic choices (source=manual or follow) are never overwritten unless
    force_zotero is explicitly requested.
    """
    existing = get_topics()
    source = get_source()

    if existing and source in ("manual", "follow") and not force_zotero:
        return existing

    if existing and not force_zotero:
        return existing

    # First run or explicit Zotero re-sync
    if force_zotero or not existing:
        source = "default"
        chosen: List[str] = []

        try:
            from .zotero import detect_topics, find_zotero_db

            if find_zotero_db():
                matches = detect_topics()
                chosen = [t[0] for t in matches if t[2] >= 0.15][:5]
                if chosen:
                    source = "zotero"
        except Exception:
            pass

        if not chosen:
            chosen = list(DEFAULT_TOPICS)
            source = "default"

        save(chosen, source=source)

        if verbose:
            from . import ui
            labels = topics_by_id(load_topics()[0])
            names = [labels[t].label if t in labels else t for t in chosen]
            where = "Zotero library" if source == "zotero" else "defaults"
            ui.info(f"Topics from {where}: {', '.join(names)}")
            ui.info("Change anytime: research-pulse topics")

        return chosen

    return existing
