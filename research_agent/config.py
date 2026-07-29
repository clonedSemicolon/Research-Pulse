"""Configuration loading for ResearchPulse.

Reads YAML config (topics + settings) and environment-based secrets. A tiny
.env loader is included so local runs work without extra dependencies; in
GitHub Actions the same values come from repository Secrets.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

PKG_DIR = Path(__file__).resolve().parent
BUNDLED_DIR = PKG_DIR / "bundled"


def _dev_root() -> Optional[Path]:
    """Project root when running from a git checkout (not an installed wheel)."""
    root = PKG_DIR.parent
    if (root / "pyproject.toml").is_file() and (root / "config" / "topics.yaml").is_file():
        return root
    return None


def _user_root() -> Path:
    """Writable home for pip installs (~/.research-pulse or RESEARCHPULSE_HOME)."""
    env = os.environ.get("RESEARCHPULSE_HOME", "").strip()
    root = Path(env) if env else Path.home() / ".research-pulse"
    root.mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "preview").mkdir(parents=True, exist_ok=True)
    return root


def _seed_user_config(user_config: Path) -> None:
    """Copy default YAML/CSV into the user config dir on first pip install."""
    bundled = BUNDLED_DIR / "config"
    user_config.mkdir(parents=True, exist_ok=True)
    for fname in ("topics.yaml", "settings.yaml", "subscribers.sample.csv"):
        src = bundled / fname
        dst = user_config / fname
        if src.is_file() and not dst.is_file():
            shutil.copy2(str(src), str(dst))


def _resolve_root() -> Path:
    dev = _dev_root()
    return dev if dev else _user_root()


def _resolve_config_dir() -> Path:
    dev = _dev_root()
    if dev:
        return dev / "config"
    user_config = _user_root() / "config"
    _seed_user_config(user_config)
    return user_config


def _resolve_template_dir() -> Path:
    dev = _dev_root()
    if dev and (dev / "templates").is_dir():
        return dev / "templates"
    return BUNDLED_DIR / "templates"


ROOT = _resolve_root()
CONFIG_DIR = _resolve_config_dir()
TEMPLATE_DIR = _resolve_template_dir()


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines). Does not overwrite real env vars."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(ROOT / ".env")


@dataclass
class Topic:
    id: str
    label: str
    keywords: List[str]
    arxiv: List[str]
    biorxiv: List[str]
    openalex: Optional[str] = None
    # Free-text queries for the cross-domain sources. Optional; topics
    # without arXiv coverage should set at least one of these.
    semanticscholar: Optional[str] = None
    europepmc: Optional[str] = None


@dataclass
class NewsFeed:
    name: str
    url: str


@dataclass
class Settings:
    papers_per_topic: int
    news_items: int
    lookback_days: int
    abstract_max_chars: int
    arxiv_request_delay: float
    newsletter_name: str
    newsletter_tagline: str


@dataclass
class Secrets:
    subscribers_csv_url: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_key: str
    sender_email: str
    sender_name: str
    site_url: str
    groq_api_key: str
    gemini_api_key: str
    ollama_host: str
    ollama_model: str
    # Backup SMTP (optional, for fallback)
    smtp_host_backup: str = ""
    smtp_port_backup: int = 587
    smtp_user_backup: str = ""
    smtp_key_backup: str = ""
    # Admin token for private commands
    admin_token: str = ""


def load_topics(path: Optional[Path] = None) -> Tuple[List[Topic], List[NewsFeed]]:
    path = path or (CONFIG_DIR / "topics.yaml")
    data: Dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    topics = [
        Topic(
            id=t["id"],
            label=t["label"],
            keywords=t.get("keywords", []) or [],
            arxiv=t.get("arxiv", []) or [],
            biorxiv=t.get("biorxiv", []) or [],
            openalex=t.get("openalex"),
            semanticscholar=t.get("semanticscholar"),
            europepmc=t.get("europepmc"),
        )
        for t in data.get("topics", [])
    ]
    feeds = [
        NewsFeed(name=f["name"], url=f["url"]) for f in data.get("news_feeds", [])
    ]
    return topics, feeds


def load_settings(path: Optional[Path] = None) -> Settings:
    path = path or (CONFIG_DIR / "settings.yaml")
    data: Dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Settings(
        papers_per_topic=int(data.get("papers_per_topic", 5)),
        news_items=int(data.get("news_items", 5)),
        lookback_days=int(data.get("lookback_days", 2)),
        abstract_max_chars=int(data.get("abstract_max_chars", 360)),
        arxiv_request_delay=float(data.get("arxiv_request_delay", 3)),
        newsletter_name=data.get("newsletter_name", "ResearchPulse"),
        newsletter_tagline=data.get("newsletter_tagline", ""),
    )


def load_secrets() -> Secrets:
    return Secrets(
        subscribers_csv_url=os.environ.get("SUBSCRIBERS_CSV_URL", "").strip(),
        smtp_host=os.environ.get("SMTP_HOST", "smtp-relay.brevo.com").strip(),
        smtp_port=int(os.environ.get("SMTP_PORT", "587") or "587"),
        smtp_user=os.environ.get("SMTP_USER", "").strip(),
        smtp_key=os.environ.get("SMTP_KEY", "").strip(),
        sender_email=os.environ.get("SENDER_EMAIL", "").strip(),
        sender_name=os.environ.get("SENDER_NAME", "ResearchPulse").strip(),
        site_url=os.environ.get("SITE_URL", "").strip().rstrip("/"),
        groq_api_key=os.environ.get("GROQ_API_KEY", "").strip(),
        gemini_api_key=os.environ.get("GEMINI_API_KEY", "").strip(),
        ollama_host=os.environ.get("OLLAMA_HOST", "").strip().rstrip("/"),
        ollama_model=os.environ.get("OLLAMA_MODEL", "llama3.2").strip(),
        # Backup SMTP (optional)
        smtp_host_backup=os.environ.get("SMTP_HOST_BACKUP", "").strip(),
        smtp_port_backup=int(os.environ.get("SMTP_PORT_BACKUP", "587") or "587"),
        smtp_user_backup=os.environ.get("SMTP_USER_BACKUP", "").strip(),
        smtp_key_backup=os.environ.get("SMTP_KEY_BACKUP", "").strip(),
        # Admin token for private commands
        admin_token=os.environ.get("RP_ADMIN_TOKEN", "").strip(),
    )


def topics_by_id(topics: List[Topic]) -> Dict[str, Topic]:
    return {t.id: t for t in topics}


def _yaml_str(value: str) -> str:
    """Quote a scalar for inline YAML, escaping embedded quotes."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _yaml_list(values: List[str]) -> str:
    if not values:
        return "[]"
    return "[" + ", ".join(_yaml_str(v) for v in values) + "]"


def add_topic(topic_id: str, label: str, keywords: List[str],
              arxiv: List[str] = None, biorxiv: List[str] = None,
              openalex: str = None, semanticscholar: str = None,
              europepmc: str = None) -> bool:
    """Append a new topic to config/topics.yaml. Returns True if added.

    Appends a formatted text block rather than re-serializing the whole file,
    so the maintainer comments and hand-tuned formatting are preserved.
    """
    path = CONFIG_DIR / "topics.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    existing = [t["id"] for t in data.get("topics", [])]
    if topic_id in existing:
        return False

    lines = [
        f"  - id: {topic_id}",
        f"    label: {_yaml_str(label)}",
        f"    keywords: {_yaml_list(keywords)}",
        f"    arxiv: {_yaml_list(arxiv or [])}",
        f"    biorxiv: {_yaml_list(biorxiv or [])}",
        f"    openalex: {_yaml_str(openalex or label.lower())}",
    ]
    if semanticscholar:
        lines.append(f"    semanticscholar: {_yaml_str(semanticscholar)}")
    if europepmc:
        lines.append(f"    europepmc: {_yaml_str(europepmc)}")
    block = "\n".join(lines) + "\n"

    text = path.read_text(encoding="utf-8")
    # Insert new topics after the last existing topic but before the
    # news-feeds section (and its introductory comment, if any).
    news_idx = text.find("\nnews_feeds:")
    if news_idx == -1:
        new_text = text.rstrip("\n") + "\n\n" + block
    else:
        # Walk back over any comment/blank lines that introduce news_feeds so
        # the topic block stays with the other topics.
        head_text = text[:news_idx]
        head_lines = head_text.split("\n")
        cut = len(head_lines)
        while cut > 0 and (head_lines[cut - 1].lstrip().startswith("#")
                           or head_lines[cut - 1].strip() == ""):
            cut -= 1
        head = "\n".join(head_lines[:cut]).rstrip("\n")
        tail = "\n".join(head_lines[cut:]) + text[news_idx:]
        new_text = head + "\n\n" + block + "\n" + tail.lstrip("\n")

    path.write_text(new_text, encoding="utf-8")
    return True
