"""Simple command-line interface for ResearchPulse.

Designed for daily use with minimal setup:

    pip install -r requirements.txt
    research-pulse              # today's digest (opens in browser)
    research-pulse search "query"
    research-pulse topics       # view or change your topics
"""

from __future__ import annotations

import argparse
import platform
import subprocess
import sys
import webbrowser
from typing import List, Optional

from . import __version__
from .config import ROOT, load_topics, topics_by_id, add_topic, load_settings
from .local_config import (
    clear_papers_per_topic,
    effective_papers_per_topic,
    ensure_ready,
    get_papers_per_topic,
    get_source,
    get_topics,
    save,
    set_papers_per_topic,
    MIN_PAPERS_PER_TOPIC,
    MAX_PAPERS_PER_TOPIC,
    LOCAL_PATH,
)
from . import ui
from .subscribe.cli import cmd_subscribe, cmd_subscriber, cmd_send_digest, cmd_send_to


def _open_preview() -> None:
    previews = sorted((ROOT / "preview").glob("*.html"))
    if previews:
        path = previews[0]
        try:
            if platform.system() == "Darwin":
                subprocess.run(["open", str(path)], check=False, 
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif platform.system() == "Windows":
                subprocess.run(["start", str(path)], shell=True, check=False,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                webbrowser.open(path.as_uri())
            ui.success("Opened preview in browser")
        except Exception:
            ui.info(f"Open this file in your browser: {path}")
        ui.info(str(path))
    else:
        ui.warn("No preview generated.")


def _resolve_digest_topics() -> List[str]:
    """Load saved topics; only auto-detect on first run."""
    topics_list, _ = load_topics()
    by_id = topics_by_id(topics_list)

    topics = get_topics()
    if topics:
        valid = [t for t in topics if t in by_id]
        if valid:
            if len(valid) != len(topics):
                save(valid, source=get_source() or "manual")
            return valid
        ui.warn("Saved topics are no longer in the catalog — re-run: research-pulse topics")

    return ensure_ready(verbose=False)


def cmd_today(open_browser: bool = True) -> int:
    """Fetch and show today's digest using saved topics."""
    ui.banner()
    topics = _resolve_digest_topics()

    # If no topics are set, prompt user to select
    if not topics:
        ui.rule("Welcome to ResearchPulse!")
        ui.info("You haven't selected any topics yet.")
        ui.info("Run 'research-pulse topics' to select your research interests.\n")
        ui.info("Or follow a topic: research-pulse follow \"your research area\"")
        return 0

    topics_list, _ = load_topics()
    labels = topics_by_id(topics_list)
    names = [labels[t].label if t in labels else t for t in topics]

    ui.info(f"Following: {', '.join(names)}")
    ui.info(f"Config: {LOCAL_PATH}")

    from .pipeline import run

    with ui.quiet_logs(), ui.digest_progress(names) as on_progress:
        rc = run(dry_run=True, topic_override=topics, on_progress=on_progress)

    if rc == 0:
        ui.success("Digest preview ready")
        if open_browser:
            _open_preview()
        else:
            ui.info(f"Saved to {ROOT / 'preview'}")
    else:
        ui.error("Digest failed — check your connection and try again.")
    return rc


def _parse_search_args(rest: List[str]) -> tuple:
    """Parse search query and optional --venue, --core, --year flags."""
    venues: List[str] = []
    core_min: Optional[str] = None
    year: Optional[int] = None
    query_parts: List[str] = []
    i = 0
    while i < len(rest):
        arg = rest[i]
        if arg == "--venue" and i + 1 < len(rest):
            venues = [v.strip() for v in rest[i + 1].split(",") if v.strip()]
            i += 2
        elif arg == "--core" and i + 1 < len(rest):
            core_min = rest[i + 1].strip()
            i += 2
        elif arg == "--year" and i + 1 < len(rest):
            try:
                year = int(rest[i + 1])
            except ValueError:
                ui.warn(f"Invalid year: {rest[i + 1]}")
            i += 2
        else:
            query_parts.append(arg)
            i += 1
    return " ".join(query_parts), venues, core_min, year


def cmd_search(query: str, venues: Optional[List[str]] = None,
               core_min: Optional[str] = None, year: Optional[int] = None) -> int:
    if not query.strip():
        ui.warn('Usage: research-pulse search "your query" [--venue neurips,icml] [--core A] [--year 2024]')
        ui.command_palette()
        return 1

    ui.banner("Search across free open-access sources")
    from .agent import display_papers
    from .search import search_papers

    sources = ["arxiv", "openalex", "semanticscholar", "crossref"]
    filters = []
    if venues:
        filters.append(f"venue={','.join(venues)}")
    if core_min:
        filters.append(f"CORE>={core_min}")
    if year:
        filters.append(f"year={year}")
    subtitle = query if not filters else f"{query} ({', '.join(filters)})"

    with ui.quiet_logs(), ui.search_progress(sources, subtitle) as on_source:
        papers = search_papers(
            query, limit=10, on_source=on_source,
            venues=venues or None, core_min=core_min, year=year,
        )

    if papers:
        display_papers(papers, f"Search · {query}")
        ui.success(f"{len(papers)} papers ranked by relevance")
    else:
        ui.warn("No papers found — try different keywords or check your connection.")
    return 0 if papers else 1


def cmd_conferences(rest: List[str]) -> int:
    """List CORE-ranked conferences from the bundled catalog."""
    from .venues import list_venues

    core_min = None
    if rest and rest[0] == "--core" and len(rest) > 1:
        core_min = rest[1]

    entries = list_venues(core_min)
    if not entries:
        ui.warn("No venues found. Add config/core_venues.yaml to customize.")
        return 1

    ui.banner("CORE-ranked conferences & journals")
    if core_min:
        ui.info(f"Showing venues with CORE rank >= {core_min}")

    for entry in sorted(entries, key=lambda e: (e.get("core", ""), e.get("id", ""))):
        names = entry.get("names", [])
        label = names[0] if names else entry.get("id", "")
        field = entry.get("field", "")
        core = entry.get("core", "?")
        extra = f" · {field}" if field else ""
        ui.info(f"[CORE {core}] {label} ({entry.get('id', '')}){extra}")

    ui.success(f"{len(entries)} venues — filter search with --venue id or name")
    return 0


def cmd_topics(args: List[str]) -> int:
    """Show or set topics. No args = interactive picker."""
    topics_list, _ = load_topics()
    by_id = topics_by_id(topics_list)
    current = get_topics() or ensure_ready(verbose=False)

    if args and args[0] in ("show", "list", "current"):
        ui.banner("Your research topics")
        ui.info(f"Config file: {LOCAL_PATH}")
        if current:
            ui.info(f"Source: {get_source() or 'unknown'}")
            for tid in current:
                ui.info(f"  • {by_id[tid].label} ({tid})" if tid in by_id else f"  • {tid}")
        else:
            ui.warn("No topics saved yet — run: research-pulse topics")
        return 0

    if args:
        unknown = [a for a in args if a not in by_id]
        if unknown:
            ui.error(f"Unknown topic(s): {', '.join(unknown)}")
            ui.info("Run: research-pulse topics")
            ui.info("Use topic IDs (e.g. ai-ml nlp cv), not display names.")
            return 1
        if not save(args, source="manual"):
            ui.error("No valid topics to save.")
            return 1
        names = [by_id[t].label for t in args if t in by_id]
        ui.success(f"Saved {len(names)} topic(s)")
        for n in names:
            ui.info(n)
        ui.info(f"Config: {LOCAL_PATH}")
        return 0

    ui.banner("Manage your research topics")
    ui.show_topics(current, topics_list, by_id)
    ui.info("Enter numbers to follow (e.g. 1 3 5), or press Enter to keep current")

    try:
        raw = ui.prompt("Select › ")
    except (EOFError, KeyboardInterrupt):
        print()
        return 0

    if not raw:
        return 0

    try:
        indices = [int(x) - 1 for x in raw.replace(",", " ").split()]
        chosen = [topics_list[i].id for i in indices if 0 <= i < len(topics_list)]
    except (ValueError, IndexError):
        ui.error("Invalid input — use numbers like: 1 3 5")
        return 1

    if not chosen:
        ui.warn("No topics selected.")
        return 1

    if not save(chosen, source="manual"):
        ui.error("Could not save topics.")
        return 1
    ui.success(f"Following {len(chosen)} topic(s)")
    for tid in chosen:
        ui.info(by_id[tid].label)
    ui.info(f"Config: {LOCAL_PATH}")
    return 0


def cmd_zotero(rest: List[str]) -> int:
    """Detect Zotero library topics; optionally apply them to the digest."""
    apply = "--apply" in rest or "-a" in rest
    if apply:
        from .zotero import detect_topics, find_zotero_db

        if not find_zotero_db():
            ui.warn("Zotero database not found.")
            ui.info("Install Zotero or set ZOTERO_DATA_DIR to your data folder.")
            return 1
        matches = detect_topics()
        chosen = [t[0] for t in matches if t[2] >= 0.15][:5]
        if not chosen:
            ui.warn("Could not match your library to known topics.")
            return 1
        save(chosen, source="zotero")
        labels = topics_by_id(load_topics()[0])
        ui.success(f"Applied {len(chosen)} topic(s) from Zotero")
        for tid in chosen:
            ui.info(labels[tid].label if tid in labels else tid)
        return 0

    from .zotero import detect_and_print
    return detect_and_print()


def cmd_help() -> int:
    ui.show_help()
    return 0


def _slugify(text: str) -> str:
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return slug[:40] or "topic"


def cmd_follow(args: List[str]) -> int:
    """Follow any research area described in plain English."""
    phrase = " ".join(args).strip().strip('"').strip("'")
    if not phrase:
        ui.warn('Usage: research-pulse follow "your research area"')
        ui.info('Example: research-pulse follow "quantum error correction"')
        return 1

    ui.banner(f'Following · "{phrase}"')

    topics_list, _ = load_topics()
    by_id = topics_by_id(topics_list)

    match = None
    if phrase.lower() in by_id:
        match = phrase.lower()
    else:
        for t in topics_list:
            if t.label.lower() == phrase.lower():
                match = t.id
                break

    if match is None:
        topic_id = _slugify(phrase)
        if topic_id in by_id:
            match = topic_id
        else:
            keywords = [w for w in phrase.split() if len(w) > 2][:6] or [phrase]
            add_topic(
                topic_id,
                phrase.title(),
                keywords,
                arxiv=[],
                biorxiv=[],
                openalex=phrase,
                semanticscholar=phrase,
                europepmc=phrase,
            )
            match = topic_id
            ui.success(f"Created topic: {phrase.title()} ({topic_id})")

    current = get_topics()
    if match not in current:
        # Ask user if they want to replace or add
        if current:
            current_labels = []
            labels_map = topics_by_id(load_topics()[0])
            for t in current:
                if t in labels_map:
                    current_labels.append(labels_map[t].label)
                else:
                    current_labels.append(t.replace("-", " ").title())
            ui.info(f"\nCurrent topics: {', '.join(current_labels)}")
            ui.info("\nOptions:")
            ui.info("  1 = Replace all topics with this one")
            ui.info("  2 = Add to existing topics")
            try:
                choice = ui.prompt("Choose (1 or 2) › ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0

            if choice == "1":
                # Replace all topics
                save([match], source="follow")
                ui.info(f"Replaced all topics with: {phrase.title()}")
            else:
                # Add to existing topics
                current.append(match)
                save(current, source="follow")
                ui.info(f"Added {phrase.title()} to your topics")
        else:
            # No existing topics, just set this one
            save([match], source="follow")
            ui.info(f"Set topic: {phrase.title()}")
    else:
        ui.info("Already following this topic")

    # Also add to subscription if exists
    from .subscription import add_topic_to_subscription, load_subscriptions
    subs = load_subscriptions()
    if subs:
        # Update all subscriptions with the new topic
        for sub in subs:
            add_topic_to_subscription(sub.email, match)
        ui.info(f"Updated {len(subs)} subscription(s) with new topic")
    else:
        ui.info("No active subscriptions. Run 'research-pulse subscribe <email>' to subscribe.")

    from .search import search_by_topic
    from .agent import display_papers

    with ui.quiet_logs(), ui.spinner(f"Fetching recent papers for {phrase}"):
        papers = search_by_topic(match, days=30, limit=10)

    if papers:
        display_papers(papers, f"Recent · {phrase}")
        ui.success(f"{len(papers)} papers — they'll also appear in tomorrow's digest")
    else:
        ui.warn("No recent papers yet — check back in your next digest.")
    return 0


def cmd_config(args: List[str]) -> int:
    """View or change local preferences (papers per topic, etc.)."""
    default = load_settings().papers_per_topic
    current = effective_papers_per_topic()
    override = get_papers_per_topic()

    if not args or args[0] == "show":
        ui.banner("Local settings")
        ui.info(f"Config file: {LOCAL_PATH}")
        saved = get_topics()
        if saved:
            labels = topics_by_id(load_topics()[0])
            names = [labels[t].label if t in labels else t for t in saved]
            ui.info(f"Topics ({get_source() or 'unknown'}): {', '.join(names)}")
        else:
            ui.info("Topics: not set yet (run research-pulse topics)")
        ui.info(f"Papers per topic: [bold]{current}[/]" if ui.HAS_RICH else f"Papers per topic: {current}")
        if override is not None:
            ui.info(f"  (your override; default in settings.yaml is {default})")
        else:
            ui.info(f"  (from config/settings.yaml — default {default})")
        ui.info(f"Range: {MIN_PAPERS_PER_TOPIC}–{MAX_PAPERS_PER_TOPIC}")
        ui.info("Set: research-pulse config papers 10")
        return 0

    if args[0] == "papers":
        if len(args) == 1:
            ui.info(f"Papers per topic: {current}")
            return 0
        if args[1].lower() in ("reset", "default", "clear"):
            clear_papers_per_topic()
            ui.success(f"Reset to default ({default} papers per topic)")
            return 0
        try:
            count = int(args[1])
        except ValueError:
            ui.error(f"Usage: research-pulse config papers <{MIN_PAPERS_PER_TOPIC}-{MAX_PAPERS_PER_TOPIC}>")
            ui.info("Or: research-pulse config papers reset")
            return 1
        try:
            set_papers_per_topic(count)
        except ValueError as exc:
            ui.error(str(exc))
            return 1
        ui.success(f"Papers per topic set to {count}")
        ui.info("Applies to your next digest (research-pulse)")
        return 0

    ui.warn(f"Unknown setting: {args[0]}")
    ui.info("Try: research-pulse config")
    return 1


def _mask_email(email: str) -> str:
    """Show only the first character before @ and one * per hidden char."""
    if "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    if len(local) <= 1:
        return f"*@{domain}"
    return f"{local[0]}{'*' * (len(local) - 1)}@{domain}"




def cmd_test_email(args: List[str]) -> int:
    """Send a test email to verify delivery. Private command — requires admin token."""
    from .config import load_secrets

    secrets = load_secrets()

    # Gate: require admin token as first argument
    if not args or args[0] != secrets.admin_token:
        ui.error("Unauthorized. Usage: research-pulse test-email <token> [recipient]")
        ui.info("The token must match RP_ADMIN_TOKEN in your .env file.")
        return 1

    # Determine recipient: second arg or default to sender email
    target = args[1] if len(args) > 1 else "aurgho1998@gmail.com"

    subject = f"ResearchPulse Test Email — {__import__('datetime').datetime.now():%Y-%m-%d %H:%M}"
    html = """\
<html>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
  <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 10px; text-align: center;">
    <h1 style="margin: 0;">ResearchPulse</h1>
    <p style="margin: 10px 0 0 0; opacity: 0.9;">Email Delivery Test</p>
  </div>
  <div style="padding: 20px; background: #f8f9fa; border-radius: 10px; margin-top: 20px;">
    <h2 style="color: #333;">Test Successful!</h2>
    <p style="color: #666;">If you're reading this, your email sending configuration is working correctly.</p>
    <table style="width: 100%; border-collapse: collapse; margin-top: 15px;">
      <tr><td style="padding: 8px; border-bottom: 1px solid #ddd; font-weight: bold;">SMTP Host</td><td style="padding: 8px; border-bottom: 1px solid #ddd;">{host}</td></tr>
      <tr><td style="padding: 8px; border-bottom: 1px solid #ddd; font-weight: bold;">Sender</td><td style="padding: 8px; border-bottom: 1px solid #ddd;">{sender}</td></tr>
      <tr><td style="padding: 8px; border-bottom: 1px solid #ddd; font-weight: bold;">Recipient</td><td style="padding: 8px; border-bottom: 1px solid #ddd;">{recipient}</td></tr>
      <tr><td style="padding: 8px; font-weight: bold;">Timestamp</td><td style="padding: 8px;">{timestamp}</td></tr>
    </table>
  </div>
  <p style="text-align: center; color: #999; margin-top: 20px; font-size: 12px;">
    ResearchPulse — Daily Research Digest<br>
    <a href="https://researchpulse.online" style="color: #667eea;">researchpulse.online</a>
  </p>
</body>
</html>
""".format(
        host=secrets.smtp_host,
        sender=secrets.sender_email,
        recipient=target,
        timestamp=__import__('datetime').datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
    )

    from .mailer import Mailer

    ui.banner("Email Delivery Test")

    mailer = Mailer(secrets)
    if not mailer.configured:
        ui.error("SMTP not configured. Check SMTP_HOST, SMTP_USER, SMTP_KEY, SENDER_EMAIL in .env")
        return 1

    with mailer:
        ui.info(f"Sending test email to: {target}")
        ui.info(f"Using SMTP: {secrets.smtp_host}:{secrets.smtp_port}")
        success = mailer.send(target, subject, html)

    if success:
        ui.success(f"Test email sent successfully to {target}")
        ui.info("Check your inbox (and spam folder) for the test email.")
    else:
        ui.error("Failed to send test email. Check SMTP credentials and try again.")
    return 0 if success else 1




def cmd_add_topic(args: List[str]) -> int:
    """Add a new topic to config/topics.yaml."""
    parser = argparse.ArgumentParser(prog="research-pulse add-topic", add_help=False)
    parser.add_argument("--id", required=True, help="Topic ID (lowercase, no spaces)")
    parser.add_argument("--label", required=True, help="Human-friendly name")
    parser.add_argument("--keywords", required=True, help="Comma-separated keywords")
    parser.add_argument("--arxiv", default="", help="Comma-separated arXiv codes (e.g. cs.AI,cs.LG)")
    parser.add_argument("--biorxiv", default="", help="Comma-separated: biorxiv,medrxiv")
    parser.add_argument("--openalex", default="", help="OpenAlex search query")
    parser.add_argument("--semanticscholar", default="", help="Semantic Scholar search query")
    parser.add_argument("--europepmc", default="", help="Europe PMC search query")

    try:
        opts = parser.parse_args(args)
    except SystemExit:
        ui.warn("Usage: research-pulse add-topic --id ID --label \"Name\" --keywords \"kw1,kw2\"")
        return 1

    topic_id = opts.id.strip().lower().replace(" ", "-")
    label = opts.label.strip()
    keywords = [k.strip() for k in opts.keywords.split(",") if k.strip()]
    arxiv = [a.strip() for a in opts.arxiv.split(",") if a.strip()]
    biorxiv = [b.strip() for b in opts.biorxiv.split(",") if b.strip()]
    openalex = opts.openalex.strip() or None
    semanticscholar = opts.semanticscholar.strip() or None
    europepmc = opts.europepmc.strip() or None

    if not topic_id or not label or not keywords:
        ui.error("--id, --label, and --keywords are required.")
        return 1

    added = add_topic(topic_id, label, keywords, arxiv, biorxiv, openalex,
                      semanticscholar, europepmc)
    if added:
        ui.success(f"Added topic: {label} ({topic_id})")
        ui.info(f"Use it: research-pulse topics {topic_id}")
    else:
        ui.warn(f"Topic '{topic_id}' already exists.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]

    if not argv:
        return cmd_today()

    if argv[0] in ("-h", "--help", "help"):
        return cmd_help()

    if argv[0] in ("-v", "--version", "version"):
        ui.info(f"ResearchPulse v{__version__}")
        return 0

    cmd = argv[0]
    rest = argv[1:]

    if cmd in ("today", "digest", "run"):
        return cmd_today()

    if cmd == "search":
        query, venues, core_min, year = _parse_search_args(rest)
        return cmd_search(query, venues=venues or None, core_min=core_min, year=year)

    if cmd == "conferences":
        return cmd_conferences(rest)

    if cmd == "topics":
        return cmd_topics(rest)

    if cmd == "zotero":
        return cmd_zotero(rest)

    if cmd in ("follow", "add"):
        return cmd_follow(rest)

    if cmd in ("subscribe", "sub"):
        return cmd_subscribe(rest)

    if cmd in ("unsubscribe", "unsub"):
        return _cmd_unsubscribe(rest)

    if cmd in ("subscriber", "subscribers"):
        return cmd_subscriber(rest)

    if cmd in ("chat", "agent"):
        from .agent import run_agent
        return run_agent()

    if cmd == "setup":
        return cmd_topics([])

    if cmd == "add-topic":
        return cmd_add_topic(rest)

    if cmd == "test-email":
        return cmd_test_email(rest)

    if cmd == "send-digest":
        return cmd_send_digest(rest)

    if cmd == "send-to":
        return cmd_send_to(rest)

    if cmd in ("desktop", "gui", "app"):
        try:
            from .desktop import run_desktop
            run_desktop()
            return 0
        except ImportError:
            ui.error("Desktop app requires customtkinter.")
            ui.info("Install with: pip install research-pulse[desktop]")
            return 1

    if cmd in ("config", "papers", "settings"):
        if cmd in ("papers", "settings") and rest:
            return cmd_config(["papers"] + rest)
        if cmd == "papers" and not rest:
            return cmd_config(["papers"])
        return cmd_config(rest)

    if cmd == "commands":
        ui.banner()
        ui.command_palette()
        return 0

    return cmd_search(f"{cmd} {' '.join(rest)}".strip())


def cli_entry() -> None:
    """Console script entry for setuptools / pip / pipx."""
    raise SystemExit(main())


if __name__ == "__main__":
    cli_entry()
