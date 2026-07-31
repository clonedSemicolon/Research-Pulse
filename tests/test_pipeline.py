"""Comprehensive pipeline + subscription tests.

Covers: default topics, custom topics, custom papers_per_topic,
multiple frequencies, multi-subscriber merges, edge cases.
Patches file paths so real data is never modified.
"""

import json
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research_agent.models import Paper, NewsItem
from research_agent.subscribers import Subscriber
from research_agent.subscription import (
    Subscription, is_due, FREQUENCY_DAYS, add_subscription,
    load_subscriptions, remove_subscription, remove_by_email,
    add_topic_to_subscription, get_subscription_by_email,
    get_due_subscriptions, mark_sent, subscription_count,
    _load_raw, _save_raw,
)
from research_agent.pipeline import _active_topic_ids, _dedup, _fetch_topic
from research_agent.render import render_digest
from research_agent.rank import rank_for_topic
from research_agent.config import (
    Settings, Secrets, Topic, load_topics, topics_by_id,
)

# ── temp subscription file ───────────────────────────────────────────────────
_tmp_sub = Path(tempfile.mktemp(suffix=".json", prefix="rp_test_sub_"))
import research_agent.subscription as sub_mod
_ORIG_SUB_PATH = sub_mod.SUBSCRIPTIONS_PATH
sub_mod.SUBSCRIPTIONS_PATH = _tmp_sub

# ── helpers ──────────────────────────────────────────────────────────────────

def _make_paper(pid, title="Paper Title", source="test"):
    return Paper(
        id=pid, title=title, abstract="Abstract text.", authors=["Alice"],
        url=f"https://example.com/{pid}", source=source, summary="Summary.",
    )

def _today():
    return datetime.now(timezone.utc)

def _days_ago(n):
    return (_today() - timedelta(days=n)).isoformat()

def _write_subs(entries):
    _tmp_sub.write_text(json.dumps({"subscriptions": entries}, indent=2), encoding="utf-8")

passed = 0
failed = 0

def check(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}  {detail}")


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 1 — is_due with every frequency
# ═══════════════════════════════════════════════════════════════════════════════
print("\n=== TEST 1: is_due() across all frequencies ===")

for freq, days in FREQUENCY_DAYS.items():
    s = Subscription(email="a@b.c", frequency=freq, last_sent=_days_ago(days))
    check(f"{freq} at boundary ({days}d) -> due", is_due(s) is True)

    s = Subscription(email="a@b.c", frequency=freq, last_sent=_days_ago(days - 1))
    check(f"{freq} one day early ({days-1}d) -> not due", is_due(s) is False)

    s = Subscription(email="a@b.c", frequency=freq, last_sent=_days_ago(days + 10))
    check(f"{freq} overdue ({days+10}d) -> due", is_due(s) is True)

s = Subscription(email="a@b.c", frequency="weekly", last_sent="")
check("empty last_sent -> due", is_due(s) is True)

s = Subscription(email="a@b.c", frequency="weekly", last_sent="2026-07-20T10:00:00")
try:
    result = is_due(s)
    check("naive datetime no crash", True)
    check("naive datetime -> due", result is True)
except TypeError:
    check("naive datetime no crash", False, "TypeError raised")

s = Subscription(email="a@b.c", frequency="3days", last_sent=_days_ago(-2))
check("future last_sent -> not due", is_due(s) is False)

s = Subscription(email="a@b.c", frequency="unknown_freq", last_sent=_days_ago(2))
check("unknown freq defaults to 1d -> due", is_due(s) is True)
s = Subscription(email="a@b.c", frequency="unknown_freq", last_sent=_days_ago(0))
check("unknown freq 0d -> not due", is_due(s) is False)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 2 — add / load / remove subscriptions
# ═══════════════════════════════════════════════════════════════════════════════
print("\n=== TEST 2: add / load / remove subscriptions ===")

# ensure clean slate
_write_subs([])

s1 = add_subscription("alice@test.com", "3days", ["ai-ml", "nlp"])
check("add new: returns Subscription", isinstance(s1, Subscription))
check("add new: email", s1.email == "alice@test.com")
check("add new: topics", s1.topics == ["ai-ml", "nlp"])
check("add new: frequency", s1.frequency == "3days")
check("add new: has token", len(s1.token) > 0)
check("add new: confirmed", s1.confirmed is True)

loaded = load_subscriptions()
check("load: 1 sub", len(loaded) == 1)
check("load: preserves email", loaded[0].email == "alice@test.com")
check("load: preserves topics", loaded[0].topics == ["ai-ml", "nlp"])

s1b = add_subscription("alice@test.com", "weekly", ["cv"])
check("update: same token", s1b.token == s1.token)
loaded = load_subscriptions()
check("update: changed topics", loaded[0].topics == ["cv"])
check("update: changed frequency", loaded[0].frequency == "weekly")
check("update: still 1 sub", len(loaded) == 1)

s2 = add_subscription("bob@test.com", "monthly", ["robotics", "security"])
loaded = load_subscriptions()
check("2 subs loaded", len(loaded) == 2)

found = get_subscription_by_email("bob@test.com")
check("get_by_email: finds bob", found is not None and found.email == "bob@test.com")
check("get_by_email: bob topics", found.topics == ["robotics", "security"])
check("get_by_email: miss returns None", get_subscription_by_email("nobody@test.com") is None)
check("get_by_email: case-insensitive", get_subscription_by_email("BOB@TEST.COM") is not None)

removed = remove_subscription(s1.token)
check("remove by token: success", removed is True)
loaded = load_subscriptions()
check("after remove: 1 sub", len(loaded) == 1)
check("after remove: is bob", loaded[0].email == "bob@test.com")

removed = remove_by_email("bob@test.com")
check("remove by email: success", removed is True)
loaded = load_subscriptions()
check("after remove: 0 subs", len(loaded) == 0)

# add_topic_to_subscription
add_subscription("carol@test.com", "weekly", ["ai-ml"])
check("add_topic: returns True", add_topic_to_subscription("carol@test.com", "nlp") is True)
loaded = load_subscriptions()
check("add_topic: new topic added", "nlp" in loaded[0].topics)
check("add_topic: original kept", "ai-ml" in loaded[0].topics)
check("add_topic: no duplicate", add_topic_to_subscription("carol@test.com", "nlp") is True)
loaded = load_subscriptions()
check("add_topic: nlp count=1", loaded[0].topics.count("nlp") == 1)
check("add_topic: miss returns False", add_topic_to_subscription("nobody@test.com", "cv") is False)

# mark_sent
add_subscription("dave@test.com", "3days", ["ai-ml"])
loaded = load_subscriptions()
dave = [s for s in loaded if s.email == "dave@test.com"][0]
check("mark_sent: last_sent empty initially", dave.last_sent == "")
mark_sent(dave.token)
loaded = load_subscriptions()
dave = [s for s in loaded if s.email == "dave@test.com"][0]
check("mark_sent: last_sent updated", dave.last_sent != "")
check("mark_sent: is recent", (_today() - datetime.fromisoformat(dave.last_sent).replace(tzinfo=timezone.utc)).seconds < 10)

# get_due_subscriptions
add_subscription("eve@test.com", "3days", ["cv"])
raw = _load_raw()
for item in raw["subscriptions"]:
    if item["email"] == "eve@test.com":
        item["last_sent"] = _days_ago(4)
_save_raw(raw)
due = get_due_subscriptions()
due_emails = [s.email for s in due]
check("eve due (4d >= 3d)", "eve@test.com" in due_emails)
check("dave not due (just sent)", "dave@test.com" not in due_emails)

check("subscription_count >= 2", subscription_count() >= 2)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 3 — _active_topic_ids with known, unknown, and mixed topics
# ═══════════════════════════════════════════════════════════════════════════════
print("\n=== TEST 3: _active_topic_ids ===")

known = {"ai-ml", "nlp", "cv", "robotics"}

subs = [Subscriber(email="a@b.c", topics=["ai-ml", "nlp"])]
check("all known", _active_topic_ids(subs, known) == {"ai-ml", "nlp"})

subs = [Subscriber(email="a@b.c", topics=["fake", "nope"])]
check("all unknown -> empty", len(_active_topic_ids(subs, known)) == 0)

subs = [Subscriber(email="a@b.c", topics=["ai-ml", "fake", "cv"])]
active = _active_topic_ids(subs, known)
check("mixed: known included", "ai-ml" in active and "cv" in active)
check("mixed: unknown excluded", "fake" not in active)

subs = [
    Subscriber(email="a@b.c", topics=["ai-ml", "nlp"]),
    Subscriber(email="b@c.d", topics=["nlp", "cv"]),
]
check("overlapping deduped", _active_topic_ids(subs, known) == {"ai-ml", "nlp", "cv"})

subs = [Subscriber(email="a@b.c", topics=[])]
check("empty topics -> empty active", len(_active_topic_ids(subs, known)) == 0)

subs = [Subscriber(email="a@b.c", topics=["AI-ML"])]
check("case-sensitive: uppercase not matched", len(_active_topic_ids(subs, known)) == 0)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 4 — pipeline merge logic (CSV + local duplicate)
# ═══════════════════════════════════════════════════════════════════════════════
print("\n=== TEST 4: pipeline merge (CSV + local) ===")

def simulate_merge(csv_subs, due_local):
    subscribers = list(csv_subs)
    local_subs_tokens = []
    csv_emails = {s.email.lower() for s in subscribers}
    for ls in due_local:
        if ls.email.lower() not in csv_emails:
            subscribers.append(Subscriber(email=ls.email, topics=ls.topics, token=ls.token))
        else:
            for s in subscribers:
                if s.email.lower() == ls.email.lower():
                    merged = set(s.topics)
                    merged.update(ls.topics)
                    s.topics = sorted(merged)
                    break
        local_subs_tokens.append(ls.token)
    return subscribers, local_subs_tokens

# A: no duplicate
csv = [Subscriber(email="csv@test.com", topics=["ai-ml"], token="csv-t")]
local = [Subscription(email="local@test.com", frequency="3days", topics=["nlp", "cv"], token="loc-t")]
subs, tokens = simulate_merge(csv, local)
check("no dup: 2 subs", len(subs) == 2)
check("no dup: local token tracked", "loc-t" in tokens)
check("no dup: csv topics", subs[0].topics == ["ai-ml"])
check("no dup: local topics", sorted(subs[1].topics) == ["cv", "nlp"])

# B: duplicate email -> merge
csv = [Subscriber(email="same@test.com", topics=["ai-ml"], token="csv-t")]
local = [Subscription(email="same@test.com", frequency="3days", topics=["ai-ml", "nlp", "cv"], token="loc-t")]
subs, tokens = simulate_merge(csv, local)
check("dup: 1 sub", len(subs) == 1)
check("dup: topics merged", set(subs[0].topics) == {"ai-ml", "nlp", "cv"})
check("dup: local token tracked", "loc-t" in tokens)
check("dup: csv token on sub", subs[0].token == "csv-t")

# C: case-insensitive duplicate
csv = [Subscriber(email="x@test.com", topics=["ai-ml"], token="csv-t")]
local = [Subscription(email="X@Test.Com", frequency="weekly", topics=["robotics"], token="loc-t")]
subs, tokens = simulate_merge(csv, local)
check("ci dup: 1 sub", len(subs) == 1)
check("ci dup: topics merged", set(subs[0].topics) == {"ai-ml", "robotics"})

# D: multiple local, one dup one new
csv = [Subscriber(email="a@test.com", topics=["ai-ml"], token="csv-t")]
local = [
    Subscription(email="a@test.com", frequency="3days", topics=["nlp"], token="t-a"),
    Subscription(email="b@test.com", frequency="weekly", topics=["cv"], token="t-b"),
]
subs, tokens = simulate_merge(csv, local)
check("multi: 2 subs", len(subs) == 2)
check("multi: a merged", set(subs[0].topics) == {"ai-ml", "nlp"})
check("multi: b added", subs[1].email == "b@test.com" and subs[1].topics == ["cv"])
check("multi: both tokens", set(tokens) == {"t-a", "t-b"})

# E: empty CSV, only local
csv = []
local = [Subscription(email="only@test.com", frequency="3days", topics=["cv"], token="t-o")]
subs, tokens = simulate_merge(csv, local)
check("empty csv: 1 sub", len(subs) == 1)
check("empty csv: correct email", subs[0].email == "only@test.com")

# F: empty local, only CSV
csv = [Subscriber(email="only@test.com", topics=["ai-ml"], token="csv-t")]
local = []
subs, tokens = simulate_merge(csv, local)
check("empty local: 1 sub", len(subs) == 1)
check("empty local: no tokens", len(tokens) == 0)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 5 — render_digest per-subscriber topics
# ═══════════════════════════════════════════════════════════════════════════════
print("\n=== TEST 5: render_digest per-subscriber topics ===")

test_settings = Settings(
    papers_per_topic=5, news_items=3, lookback_days=7, abstract_max_chars=360,
    arxiv_request_delay=3.0, newsletter_name="TestDigest", newsletter_tagline="Test",
)
test_secrets = Secrets(
    subscribers_csv_url="", smtp_host="", smtp_port=587, smtp_user="", smtp_key="",
    sender_email="", sender_name="", site_url="https://example.com",
    groq_api_key="", gemini_api_key="", ollama_host="", ollama_model="",
)
papers_by_topic = {
    "ai-ml": [_make_paper("p1", "AI Paper 1"), _make_paper("p2", "AI Paper 2")],
    "nlp": [_make_paper("p3", "NLP Paper 1")],
    "cv": [_make_paper("p4", "CV Paper 1")],
}
topic_labels = {"ai-ml": "AI & ML", "nlp": "NLP", "cv": "Computer Vision"}
news = [NewsItem(title="News1", url="https://n1", source="test")]

# 1 topic
sub_1 = Subscriber(email="one@test.com", topics=["ai-ml"], token="tok1")
html_1 = render_digest(sub_1, papers_by_topic, topic_labels, news, test_settings, test_secrets)
check("1-topic: has AI papers", "AI Paper 1" in html_1)
check("1-topic: no NLP", "NLP Paper 1" not in html_1)
check("1-topic: no CV", "CV Paper 1" not in html_1)
check("1-topic: unsubscribe link", "unsubscribe" in html_1.lower())
check("1-topic: token in link", "tok1" in html_1)

# 2 topics
sub_2 = Subscriber(email="two@test.com", topics=["ai-ml", "nlp"], token="tok2")
html_2 = render_digest(sub_2, papers_by_topic, topic_labels, news, test_settings, test_secrets)
check("2-topic: has AI", "AI Paper 1" in html_2)
check("2-topic: has NLP", "NLP Paper 1" in html_2)
check("2-topic: no CV", "CV Paper 1" not in html_2)

# all topics
sub_all = Subscriber(email="all@test.com", topics=["ai-ml", "nlp", "cv"], token="tok3")
html_all = render_digest(sub_all, papers_by_topic, topic_labels, news, test_settings, test_secrets)
check("all-topic: has all papers", all(p in html_all for p in ["AI Paper 1", "NLP Paper 1", "CV Paper 1"]))

# unknown topic (no papers)
sub_unk = Subscriber(email="unk@test.com", topics=["fake-topic"], token="tok4")
html_unk = render_digest(sub_unk, papers_by_topic, topic_labels, news, test_settings, test_secrets)
check("unknown topic: no crash", html_unk is not None and len(html_unk) > 0)

# empty topics
sub_empty = Subscriber(email="empty@test.com", topics=[], token="tok5")
html_empty = render_digest(sub_empty, papers_by_topic, topic_labels, news, test_settings, test_secrets)
check("empty topics: no crash", html_empty is not None and len(html_empty) > 0)

# unsubscribe URL
check("unsub URL: has site_url", "example.com" in html_1)
check("unsub URL: has action", "action=unsubscribe" in html_1)

# no token -> no unsub URL
sub_notok = Subscriber(email="notok@test.com", topics=["ai-ml"], token="")
html_notok = render_digest(sub_notok, papers_by_topic, topic_labels, news, test_settings, test_secrets)
check("no token: still renders", html_notok is not None)

# different subscribers get different HTML
check("different subs -> different HTML", html_1 != html_2)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 6 — custom papers_per_topic via rank_for_topic
# ═══════════════════════════════════════════════════════════════════════════════
print("\n=== TEST 6: papers_per_topic limits ===")

test_topic = Topic(id="ai-ml", label="AI & ML", keywords=["artificial", "intelligence"],
                    arxiv=["cs.AI"], biorxiv=[], openalex=None)

many_papers = [_make_paper(f"p{i}", f"Artificial Intelligence Research Paper {i}") for i in range(20)]

ranked_3 = rank_for_topic(many_papers, test_topic, 3)
check("limit=3 -> <=3 papers", len(ranked_3) <= 3)

ranked_10 = rank_for_topic(many_papers, test_topic, 10)
check("limit=10 -> <=10 papers", len(ranked_10) <= 10)

ranked_1 = rank_for_topic(many_papers, test_topic, 1)
check("limit=1 -> <=1 paper", len(ranked_1) <= 1)

few = [_make_paper(f"p{i}", f"Artificial Intelligence Research Paper {i}") for i in range(3)]
ranked_more = rank_for_topic(few, test_topic, 10)
check("limit > available -> all 3", len(ranked_more) == 3)

ranked_0 = rank_for_topic(many_papers, test_topic, 0)
check("limit=0 -> 0 papers", len(ranked_0) == 0)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 7 — _dedup
# ═══════════════════════════════════════════════════════════════════════════════
print("\n=== TEST 7: _dedup ===")

class FakeCache:
    def is_seen(self, pid): return False

cache = FakeCache()

papers = [_make_paper("p1", "Title One"), _make_paper("p2", "Title Two")]
check("no dups: both kept", len(_dedup(papers, cache)) == 2)

papers = [_make_paper("p1", "Title One"), _make_paper("p1", "Again")]
check("same id: 1 kept", len(_dedup(papers, cache)) == 1)

papers = [_make_paper("p1", "Title! One"), _make_paper("p2", "Title One")]
check("same normalized title: 1 kept", len(_dedup(papers, cache)) == 1)

papers = [Paper(id="", title="X", abstract="", authors=[], url="", source="")]
check("empty id: dropped", len(_dedup(papers, cache)) == 0)

class SeenHit:
    def is_seen(self, pid): return pid == "p-old"

papers = [_make_paper("p-old", "Old"), _make_paper("p-new", "New")]
deduped = _dedup(papers, SeenHit())
check("seen cache: old dropped", all(p.id != "p-old" for p in deduped))
check("seen cache: new kept", any(p.id == "p-new" for p in deduped))

# multiple distinct papers
papers = [_make_paper(f"p{i}", f"Unique Title {i}") for i in range(10)]
check("10 unique: all kept", len(_dedup(papers, cache)) == 10)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 8 — full pipeline dry-run
# ═══════════════════════════════════════════════════════════════════════════════
print("\n=== TEST 8: pipeline dry-run (topic_override) ===")

from research_agent.pipeline import run

# topic_override mode bypasses subscription loading, uses local@preview
# Tests: fetch -> dedup -> rank -> summarize -> render -> write preview
rc = run(dry_run=True, topic_override=["software-eng"])
check("dry-run software-eng: exit 0", rc == 0)

rc = run(dry_run=True, topic_override=["ai-ml", "nlp"])
check("dry-run 2 topics: exit 0", rc == 0)

rc = run(dry_run=True, topic_override=["ai-ml", "cv", "robotics"])
check("dry-run 3 topics: exit 0", rc == 0)

# single custom topic
rc = run(dry_run=True, topic_override=["test-custom-topic"])
check("dry-run custom topic: exit 0", rc == 0)

# check preview files exist
from research_agent.config import ROOT
preview_dir = ROOT / "preview"
previews = sorted(preview_dir.glob("*.html"))
check("preview files created", len(previews) >= 1)
if previews:
    # latest preview has content
    latest_html = previews[-1].read_text(encoding="utf-8")
    check("preview has HTML content", len(latest_html) > 100)
    check("preview has newsletter name", "ResearchPulse" in latest_html or "Digest" in latest_html)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 9 — mark_sent + frequency cycle
# ═══════════════════════════════════════════════════════════════════════════════
print("\n=== TEST 9: mark_sent + frequency cycle ===")

_write_subs([{
    "email": "mark@test.com", "frequency": "3days",
    "topics": ["ai-ml"], "token": "tok-mark",
    "confirmed": True, "created_at": _days_ago(10), "last_sent": "",
}])

loaded = load_subscriptions()
check("before mark_sent: empty", loaded[0].last_sent == "")

mark_sent("tok-mark")
loaded = load_subscriptions()
check("after mark_sent: set", loaded[0].last_sent != "")
check("after mark_sent: not due", is_due(loaded[0]) is False)

# simulate 3 days passing
raw = _load_raw()
raw["subscriptions"][0]["last_sent"] = _days_ago(3)
_save_raw(raw)
loaded = load_subscriptions()
check("3 days later: due again", is_due(loaded[0]) is True)

# mark_sent again, check it updates
mark_sent("tok-mark")
loaded = load_subscriptions()
prev = datetime.fromisoformat(_days_ago(3).replace("+00:00", ""))
# just verify it changed
check("re-mark_sent: last_sent changed", loaded[0].last_sent != _days_ago(3))


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 10 — unconfirmed subscribers excluded
# ═══════════════════════════════════════════════════════════════════════════════
print("\n=== TEST 10: unconfirmed subscribers excluded ===")

_write_subs([
    {
        "email": "confirmed@test.com", "frequency": "3days",
        "topics": ["ai-ml"], "token": "tok-c",
        "confirmed": True, "created_at": _days_ago(5), "last_sent": _days_ago(4),
    },
    {
        "email": "unconfirmed@test.com", "frequency": "3days",
        "topics": ["ai-ml"], "token": "tok-u",
        "confirmed": False, "created_at": _days_ago(5), "last_sent": _days_ago(4),
    },
])

all_subs = load_subscriptions()
check("load: both returned", len(all_subs) == 2)
due = get_due_subscriptions()
due_emails = [s.email for s in due]
check("confirmed in due", "confirmed@test.com" in due_emails)
check("unconfirmed NOT in due", "unconfirmed@test.com" not in due_emails)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 11 — custom topics from topics.yaml
# ═══════════════════════════════════════════════════════════════════════════════
print("\n=== TEST 11: custom topics integration ===")

topics_list, _ = load_topics()
by_id = topics_by_id(topics_list)

check("test-custom-topic exists", "test-custom-topic" in by_id)
check("machine-learning-for-healthcare exists", "machine-learning-for-healthcare" in by_id)
check("artificial-intelligence exists", "artificial-intelligence" in by_id)

custom_sub = Subscriber(
    email="custom@test.com",
    topics=["software-eng", "test-custom-topic", "machine-learning-for-healthcare", "artificial-intelligence"],
    token="tok-custom",
)
active = _active_topic_ids([custom_sub], set(by_id.keys()))
check("all 4 custom topics active", active == set(custom_sub.topics))

papers_custom = {
    "software-eng": [_make_paper("se1", "SE Paper")],
    "test-custom-topic": [_make_paper("tc1", "Custom Topic Paper")],
    "machine-learning-for-healthcare": [_make_paper("ml1", "ML Healthcare Paper")],
    "artificial-intelligence": [_make_paper("ai1", "AI Paper")],
}
labels_custom = {
    "software-eng": "Software Engineering",
    "test-custom-topic": "Test Custom Topic",
    "machine-learning-for-healthcare": "Machine Learning For Healthcare",
    "artificial-intelligence": "Artificial Intelligence",
}
html_custom = render_digest(custom_sub, papers_custom, labels_custom, news, test_settings, test_secrets)
check("custom: has SE Paper", "SE Paper" in html_custom)
check("custom: has Custom Topic Paper", "Custom Topic Paper" in html_custom)
check("custom: has ML Healthcare Paper", "ML Healthcare Paper" in html_custom)
check("custom: has AI Paper", "AI Paper" in html_custom)
check("custom: all 4 labels present", all(l in html_custom for l in labels_custom.values()))


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 12 — topic with no papers (empty section skipped)
# ═══════════════════════════════════════════════════════════════════════════════
print("\n=== TEST 12: topic with no papers ===")

sub_np = Subscriber(email="np@test.com", topics=["ai-ml", "nlp"], token="tok-np")
papers_sparse = {"ai-ml": [_make_paper("p1", "AI Paper")]}  # no nlp
html_np = render_digest(sub_np, papers_sparse, topic_labels, news, test_settings, test_secrets)
check("sparse: has AI Paper", "AI Paper" in html_np)
check("sparse: no crash", html_np is not None)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 13 — render with many papers per topic
# ═══════════════════════════════════════════════════════════════════════════════
print("\n=== TEST 13: render with many papers ===")

many = {k: [_make_paper(f"{k}-{i}", f"{k} Paper {i}") for i in range(15)] for k in ["ai-ml", "nlp", "cv"]}
sub_many = Subscriber(email="many@test.com", topics=["ai-ml", "nlp", "cv"], token="tok-many")
html_many = render_digest(sub_many, many, topic_labels, news, test_settings, test_secrets)
check("many papers: has first AI paper", "ai-ml-0" in html_many or "AI Paper 0" in html_many)
check("many papers: has last AI paper", "ai-ml-14" in html_many or "AI Paper 14" in html_many)
check("many papers: renders all 3 topics", all(
    l.replace("&", "&amp;") in html_many or l in html_many for l in topic_labels.values()
))


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 14 — multi-subscriber dry-run with different topic sets
# ═══════════════════════════════════════════════════════════════════════════════
print("\n=== TEST 14: multi-subscriber render simulation ===")

# Simulate what the pipeline does: render per-subscriber with shared papers_by_topic
shared_papers = {
    "ai-ml": [_make_paper("ai1", "AI Paper"), _make_paper("ai2", "AI Paper 2")],
    "nlp": [_make_paper("nlp1", "NLP Paper")],
    "cv": [_make_paper("cv1", "CV Paper")],
    "robotics": [_make_paper("rob1", "Robotics Paper")],
}
shared_labels = {"ai-ml": "AI & ML", "nlp": "NLP", "cv": "Computer Vision", "robotics": "Robotics"}

subs = [
    Subscriber(email="a@test.com", topics=["ai-ml", "nlp"], token="t-a"),
    Subscriber(email="b@test.com", topics=["cv"], token="t-b"),
    Subscriber(email="c@test.com", topics=["ai-ml", "cv", "robotics"], token="t-c"),
    Subscriber(email="d@test.com", topics=["nlp"], token="t-d"),
]

htmls = {}
for s in subs:
    htmls[s.email] = render_digest(s, shared_papers, shared_labels, news, test_settings, test_secrets)

check("a: has AI and NLP", "AI Paper" in htmls["a@test.com"] and "NLP Paper" in htmls["a@test.com"])
check("a: no CV or Rob", "CV Paper" not in htmls["a@test.com"] and "Robotics Paper" not in htmls["a@test.com"])

check("b: only CV", "CV Paper" in htmls["b@test.com"] and "AI Paper" not in htmls["b@test.com"])

check("c: has AI+CV+Rob", all(p in htmls["c@test.com"] for p in ["AI Paper", "CV Paper", "Robotics Paper"]))
check("c: no NLP", "NLP Paper" not in htmls["c@test.com"])

check("d: only NLP", "NLP Paper" in htmls["d@test.com"] and "AI Paper" not in htmls["d@test.com"])

# Each has correct unsubscribe token
check("a: unsub tok t-a", "t-a" in htmls["a@test.com"])
check("b: unsub tok t-b", "t-b" in htmls["b@test.com"])
check("c: unsub tok t-c", "t-c" in htmls["c@test.com"])
check("d: unsub tok t-d", "t-d" in htmls["d@test.com"])

# All HTMLs are different (different topic combos)
unique_htmls = set(htmls.values())
check("all 4 digests unique", len(unique_htmls) == 4)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 15 — frequency: all 4 durations
# ═══════════════════════════════════════════════════════════════════════════════
print("\n=== TEST 15: frequency: all 4 durations with mark_sent cycle ===")

_write_subs([])

for freq, days in FREQUENCY_DAYS.items():
    email = f"{freq}@test.com"
    add_subscription(email, freq, ["ai-ml"])
    loaded = load_subscriptions()
    sub = [s for s in loaded if s.email == email][0]

    # just subscribed, last_sent empty -> due
    check(f"{freq}: new sub is due", is_due(sub) is True)

    # mark_sent
    mark_sent(sub.token)
    loaded = load_subscriptions()
    sub = [s for s in loaded if s.email == email][0]
    check(f"{freq}: after send, not due", is_due(sub) is False)

    # simulate (days - 1) passing -> still not due
    raw = _load_raw()
    for item in raw["subscriptions"]:
        if item["email"] == email:
            item["last_sent"] = _days_ago(days - 1)
    _save_raw(raw)
    loaded = load_subscriptions()
    sub = [s for s in loaded if s.email == email][0]
    check(f"{freq}: {days-1}d later, not due", is_due(sub) is False)

    # simulate exactly `days` passing -> due
    raw = _load_raw()
    for item in raw["subscriptions"]:
        if item["email"] == email:
            item["last_sent"] = _days_ago(days)
    _save_raw(raw)
    loaded = load_subscriptions()
    sub = [s for s in loaded if s.email == email][0]
    check(f"{freq}: {days}d later, due", is_due(sub) is True)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 16 — edge cases
# ═══════════════════════════════════════════════════════════════════════════════
print("\n=== TEST 16: edge cases ===")

# Paper with minimal fields
min_paper = Paper(id="min", title="", abstract="", authors=[], url="", source="")
check("minimal paper: no crash in render", True)
html_min = render_digest(
    Subscriber(email="e@test.com", topics=["ai-ml"], token="t"),
    {"ai-ml": [min_paper]}, {"ai-ml": "AI"}, news, test_settings, test_secrets,
)
check("minimal paper: renders", html_min is not None and len(html_min) > 0)

# Paper with special chars in title
spec_paper = _make_paper("spec", '<script>alert("xss")</script>')
html_spec = render_digest(
    Subscriber(email="e@test.com", topics=["ai-ml"], token="t"),
    {"ai-ml": [spec_paper]}, {"ai-ml": "AI"}, news, test_settings, test_secrets,
)
check("XSS: script tag escaped", "<script>" not in html_spec)

# Very long author list
long_authors_paper = _make_paper("la", "Long Authors Paper")
long_authors_paper.authors = [f"Author {i}" for i in range(50)]
html_la = render_digest(
    Subscriber(email="e@test.com", topics=["ai-ml"], token="t"),
    {"ai-ml": [long_authors_paper]}, {"ai-ml": "AI"}, news, test_settings, test_secrets,
)
check("50 authors: no crash", html_la is not None)

# Subscriber with many topics
many_topics_sub = Subscriber(
    email="many@test.com",
    topics=[f"topic-{i}" for i in range(30)],
    token="t-many",
)
# Only 2 topics have papers
papers_few = {"topic-0": [_make_paper("p0", "P0")], "topic-29": [_make_paper("p29", "P29")]}
labels_many = {f"topic-{i}": f"Topic {i}" for i in range(30)}
html_mt = render_digest(many_topics_sub, papers_few, labels_many, news, test_settings, test_secrets)
check("30 topics, 2 with papers: has P0", "P0" in html_mt)
check("30 topics, 2 with papers: has P29", "P29" in html_mt)
check("30 topics: no crash", html_mt is not None)


# ═══════════════════════════════════════════════════════════════════════════════
# CLEANUP & SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════

# Restore original path
sub_mod.SUBSCRIPTIONS_PATH = _ORIG_SUB_PATH
# Remove temp file
try:
    _tmp_sub.unlink()
except (OSError, FileNotFoundError):
    pass

print(f"\n{'='*60}")
total = passed + failed
print(f"  {passed}/{total} passed", end="")
if failed:
    print(f",  {failed} FAILED")
else:
    print("  -- all clear!")
print(f"{'='*60}")

sys.exit(1 if failed else 0)
