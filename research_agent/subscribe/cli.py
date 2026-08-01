"""CLI commands for subscription management.

Provides: subscribe, unsubscribe, subscriber list/count, send-digest, send-to.
"""

from __future__ import annotations

from typing import List, Optional

from .. import ui
from ..config import load_topics, topics_by_id, load_settings, load_secrets
from ..local_config import get_topics
from .models import FREQUENCY_DAYS, FREQUENCY_LABELS
from .storage import (
    add_subscription,
    get_subscription_by_email,
    get_due_subscriptions,
    is_due,
    load_subscriptions,
    mark_sent,
    mark_failed,
    remove_by_email,
    remove_subscription,
    subscription_count,
)
from .csv_loader import load_subscribers
from .models import Subscriber


def _get_effective_topics(email: str) -> List[str]:
    """Get the best topic list for a subscriber: existing subscription topics
    take priority over local config topics."""
    existing = get_subscription_by_email(email)
    if existing and existing.topics:
        return existing.topics
    return get_topics()


def _mask_email(email: str) -> str:
    """Show only the first character before @ and one * per hidden char."""
    if "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    if len(local) <= 1:
        return f"*@{domain}"
    return f"{local[0]}{'*' * (len(local) - 1)}@{domain}"


def cmd_subscriber(args: List[str]) -> int:
    """Manage subscribers (admin only)."""
    secrets = load_secrets()

    if not args:
        ui.banner("Subscriber Management")
        ui.info("Usage:")
        ui.info("  research-pulse subscriber list <admin_token>   View all subscribers")
        ui.info("  research-pulse subscriber count                Show subscriber count")
        return 0

    # ── List subscribers (admin only) ───────────────────────────────
    if args[0] in ("list", "show", "status"):
        if len(args) < 2 or args[1] != secrets.admin_token:
            ui.error("Unauthorized. Usage: research-pulse subscriber list <admin_token>")
            ui.info("The token must match RP_ADMIN_TOKEN in your .env file.")
            return 1

        subs = load_subscriptions()
        if not subs:
            ui.info("No active subscriptions.")
            return 0
        ui.info(f"{len(subs)} active subscription(s):")
        for s in subs:
            freq = FREQUENCY_LABELS.get(s.frequency, s.frequency)
            topics_str = ", ".join(s.topics) if s.topics else "local topics"
            last = s.last_sent[:10] if s.last_sent else "never"
            due = "yes" if is_due(s) else "no"
            ui.info(
                f"  {s.email}  ·  {freq}  ·  topics: {topics_str}\n"
                f"    last sent: {last}  ·  due: {due}"
                f"  ·  sent: {s.sent_count}  ·  failures: {s.failure_count}"
            )
        return 0

    # ── Count ───────────────────────────────────────────────────────
    if args[0] in ("count", "total"):
        count = subscription_count()
        ui.info(f"{count} active subscription(s)")
        return 0

    ui.error(f"Unknown command: {args[0]}")
    ui.info("Usage: research-pulse subscriber list <admin_token>")
    return 1


def cmd_subscribe(args: List[str]) -> int:
    """Subscribe to research digests on a schedule."""
    # ── Unsubscribe flow ────────────────────────────────────────────
    if args and args[0] in ("unsubscribe", "remove", "delete"):
        return _cmd_unsubscribe(args[1:])

    # ── Quick subscribe with email ──────────────────────────────────
    if args and "@" in args[0]:
        email = args[0]
        topics_list, _ = load_topics()
        labels = topics_by_id(topics_list)
        saved_topics = _get_effective_topics(email)

        if not saved_topics:
            ui.error("No topics configured. Run 'research-pulse setup' first.")
            return 1

        frequency = "3days"
        saved_labels = [labels[t].label for t in saved_topics if t in labels]

        ui.banner("Subscribe to ResearchPulse")
        ui.info(f"  Email:     {email}")
        ui.info(f"  Frequency: Every 3 days")
        ui.info(f"  Topics:    {', '.join(saved_labels)}")
        print()

        try:
            confirm = ui.prompt("Confirm subscription? (y/n) › ").lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if confirm not in ("y", "yes"):
            ui.info("Cancelled.")
            return 0

        add_subscription(email, frequency, saved_topics)
        ui.success(f"Subscribed {email} to every 3 days digests!")
        ui.info(f"Topics: {', '.join(saved_labels)}")
        ui.info("First digest will arrive within 3 day(s).")
        return 0

    # ── Interactive subscribe flow ──────────────────────────────────
    ui.banner("Subscribe to ResearchPulse")

    # Ask for email first so we can check for existing subscription
    email = ""
    try:
        email = ui.prompt("Your email address › ")
    except (EOFError, KeyboardInterrupt):
        print()
        return 0
    if not email or "@" not in email:
        ui.error("Please enter a valid email address.")
        return 1

    topics_list, _ = load_topics()
    labels = topics_by_id(topics_list)
    # Use existing subscription topics if available, otherwise local config
    saved_topics = _get_effective_topics(email)

    custom_topics = [t for t in saved_topics if t not in labels]
    for ct in custom_topics:
        label = ct.replace("-", " ").title()
        labels[ct] = type('Topic', (), {'id': ct, 'label': label})()

    ui.rule("Your topics")
    if saved_topics:
        saved_labels = [labels[t].label for t in saved_topics if t in labels]
        ui.info(f"Your saved topics: {', '.join(saved_labels)}")
        ui.info("\nOptions:")
        ui.info("  Enter = use your saved topics")
        ui.info("  'all' = subscribe to all topics")
        ui.info("  Numbers = pick specific topics (e.g. 1,3,5)\n")
        all_topics = topics_list + [labels[ct] for ct in custom_topics]
        for i, t in enumerate(all_topics, 1):
            marker = " ✓" if t.id in saved_topics else ""
            is_custom = " (custom)" if t.id in custom_topics else ""
            ui.info(f"  {i:2d}. {t.label}{is_custom}{marker}")
        print()
        try:
            topic_choice = ui.prompt("Topics (Enter for saved) › ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if topic_choice == "":
            selected_topics = saved_topics
        elif topic_choice.lower() == "all":
            selected_topics = [t.id for t in all_topics]
        else:
            try:
                indices = [int(x.strip()) - 1 for x in topic_choice.split(",")]
                selected_topics = []
                for idx in indices:
                    if 0 <= idx < len(all_topics):
                        selected_topics.append(all_topics[idx].id)
                    else:
                        ui.error(f"Invalid choice: {idx + 1}")
                        return 1
            except ValueError:
                ui.error("Enter numbers separated by commas, 'all', or press Enter for saved topics.")
                return 1
    else:
        ui.info("Select topics you want to receive papers about.")
        ui.info("Enter topic numbers separated by commas (e.g. 1,3,5) or 'all' for everything.\n")
        for i, t in enumerate(topics_list, 1):
            ui.info(f"  {i:2d}. {t.label}")
        print()
        try:
            topic_choice = ui.prompt("Topics › ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if topic_choice.lower() == "all":
            selected_topics = [t.id for t in topics_list]
        else:
            try:
                indices = [int(x.strip()) - 1 for x in topic_choice.split(",")]
                selected_topics = []
                for idx in indices:
                    if 0 <= idx < len(topics_list):
                        selected_topics.append(topics_list[idx].id)
                    else:
                        ui.error(f"Invalid choice: {idx + 1}")
                        return 1
            except ValueError:
                ui.error("Enter numbers separated by commas or 'all'.")
                return 1

    if not selected_topics:
        ui.error("No topics selected.")
        return 1

    selected_labels = [labels[t].label for t in selected_topics if t in labels]

    ui.rule("Delivery frequency")
    freq_opts = list(FREQUENCY_LABELS.items())
    for i, (key, label) in enumerate(freq_opts, 1):
        ui.info(f"  {i}. {label}")
    try:
        choice = ui.prompt("Choose frequency (1-4) › ")
        idx = int(choice) - 1
        if idx < 0 or idx >= len(freq_opts):
            ui.error("Invalid choice.")
            return 1
        frequency = freq_opts[idx][0]
    except (EOFError, KeyboardInterrupt):
        print()
        return 0
    except (ValueError, IndexError):
        ui.error("Enter a number (1-4).")
        return 1

    freq_label = FREQUENCY_LABELS.get(frequency, frequency)
    print()
    ui.info(f"  Email:     {email}")
    ui.info(f"  Frequency: {freq_label}")
    ui.info(f"  Topics:    {', '.join(selected_labels)}")
    try:
        confirm = ui.prompt("Confirm subscription? (y/n) › ").lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return 0
    if confirm not in ("y", "yes"):
        ui.info("Cancelled.")
        return 0

    add_subscription(email, frequency, selected_topics)

    ui.success(f"Subscribed {email} to {freq_label.lower()} digests!")
    ui.info(f"Topics: {', '.join(selected_labels)}")
    ui.info(f"First digest will arrive within {FREQUENCY_DAYS[frequency]} day(s).")
    ui.info("Manage: research-pulse unsubscribe <email> or research-pulse subscriber list <admin_token>")
    return 0


def _cmd_unsubscribe(args: List[str]) -> int:
    subs = load_subscriptions()
    if not subs:
        ui.info("No active subscriptions to remove.")
        return 0

    if args:
        target = args[0]
        if "@" in target:
            if remove_by_email(target):
                ui.success(f"Unsubscribed {_mask_email(target)}")
            else:
                ui.warn(f"No subscription found for {_mask_email(target)}")
            return 0
        else:
            if remove_subscription(target):
                ui.success(f"Unsubscribed (token: {target})")
            else:
                ui.warn(f"No subscription found with token: {target}")
            return 0

    ui.banner("Unsubscribe")
    ui.info(f"{len(subs)} subscription(s) on file.")
    try:
        email = ui.prompt("Enter the email address to unsubscribe › ")
    except (EOFError, KeyboardInterrupt):
        print()
        return 0
    if not email or "@" not in email:
        ui.warn("Cancelled.")
        return 0

    if remove_by_email(email):
        ui.success(f"Unsubscribed {_mask_email(email)}")
    else:
        ui.warn(f"No subscription found for {_mask_email(email)}")
    return 0


def cmd_send_digest(args: List[str]) -> int:
    """Send digest to all subscribers instantly. Admin only."""
    secrets = load_secrets()

    if not args or args[0] != secrets.admin_token:
        ui.error("Unauthorized. Usage: research-pulse send-digest <admin_token>")
        ui.info("The token must match RP_ADMIN_TOKEN in your .env file.")
        return 1

    ui.banner("Send Digest Now")

    from ..pipeline import run

    subs = load_subscriptions()
    if not subs:
        ui.warn("No active subscriptions found.")
        ui.info("Users must subscribe first: research-pulse subscribe email@example.com")
        return 0

    ui.info(f"Found {len(subs)} subscriber(s)")
    ui.info("Sending digest to all subscribers...\n")

    with ui.quiet_logs(), ui.spinner("Sending digest"):
        rc = run(dry_run=False)

    if rc == 0:
        ui.success("Digest sent successfully!")
    else:
        ui.error("Failed to send digest. Check SMTP configuration.")

    return rc


def cmd_send_to(args: List[str]) -> int:
    """Send digest to a specific subscriber instantly. Secret admin command."""
    secrets = load_secrets()

    if len(args) < 2 or args[0] != secrets.admin_token:
        ui.error("Unknown command.")
        return 1

    target_email = args[1].strip().lower()

    ui.banner("Send to Subscriber")

    from ..pipeline import run
    from ..mailer import Mailer
    from ..render import render_digest
    from ..config import topics_by_id
    from ..sources import rss
    from ..summarize import Summarizer
    from ..cache import SeenCache
    from ..rank import rank_for_topic

    sub = get_subscription_by_email(target_email)
    if not sub:
        csv_subs = load_subscribers(secrets)
        for s in csv_subs:
            if s.email.lower() == target_email:
                sub = s
                break

    if not sub:
        ui.error(f"Subscriber not found: {target_email}")
        ui.info("They must subscribe first: research-pulse subscribe email@example.com")
        return 1

    ui.info(f"Subscriber: {sub.email}")
    ui.info(f"Topics: {', '.join(sub.topics)}\n")

    topics_list, feeds = load_topics()
    settings = load_settings()
    by_id = topics_by_id(topics_list)
    topic_labels = {t.id: t.label for t in topics_list}

    cache = SeenCache()
    summarizer = Summarizer(secrets, settings.abstract_max_chars)

    ui.info("Fetching papers for subscriber's topics...\n")

    from ..pipeline import _fetch_topic, _dedup

    papers_by_topic = {}
    for topic_id in sub.topics:
        if topic_id not in by_id:
            ui.warn(f"Topic '{topic_id}' not found in catalog, skipping")
            continue
        topic = by_id[topic_id]
        with ui.spinner(f"Fetching {topic.label}"):
            raw = _fetch_topic(topic, settings, secrets)
            fresh = _dedup(raw, cache)
            ranked = rank_for_topic(fresh, topic, settings.papers_per_topic)
            summarizer.annotate(ranked)
            papers_by_topic[topic_id] = ranked
            ui.info(f"  {topic.label}: {len(ranked)} papers")

    news = rss.fetch(feeds, per_feed=max(2, settings.news_items))[: settings.news_items]

    html = render_digest(sub, papers_by_topic, topic_labels, news, settings, secrets)

    mailer = Mailer(secrets)
    if not mailer.configured:
        ui.error("SMTP not configured.")
        return 1

    subject = f"{settings.newsletter_name}: your research digest - {__import__('datetime').datetime.now():%b %d}"

    with mailer:
        success = mailer.send(sub.email, subject, html)

    if success:
        ui.success(f"Digest sent to {sub.email}")
        ui.info("Check their inbox.")
        # Track success if this is a local subscription
        local_sub = get_subscription_by_email(target_email)
        if local_sub and local_sub.token:
            mark_sent(local_sub.token)
    else:
        ui.error("Failed to send email.")
        local_sub = get_subscription_by_email(target_email)
        if local_sub and local_sub.token:
            mark_failed(local_sub.token)

    return 0 if success else 1
