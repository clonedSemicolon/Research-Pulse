"""Rich terminal UI for ResearchPulse.

Attractive, progress-aware CLI output with a compact command palette.
Falls back to plain print() when Rich is not installed.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Callable, Dict, Iterator, List, Optional, Tuple

from . import __version__

try:
    from rich import box
    from rich.console import Console, Group
    from rich.panel import Panel
    from rich.progress import (
        BarColumn,
        Progress,
        SpinnerColumn,
        TaskProgressColumn,
        TextColumn,
        TimeElapsedColumn,
    )
    from rich.table import Table
    from rich.text import Text

    HAS_RICH = True
    console = Console(highlight=False)
except ImportError:
    HAS_RICH = False
    console = None  # type: ignore

# ── Branding ────────────────────────────────────────────────────────────

ACCENT = "cyan"
MUTED = "dim"

SOURCE_DISPLAY: Dict[str, str] = {
    "arxiv": "arXiv",
    "openalex": "OpenAlex",
    "semanticscholar": "Semantic Scholar",
    "crossref": "Crossref",
    "europepmc": "Europe PMC",
    "biorxiv": "bioRxiv",
    "medrxiv": "medRxiv",
}

CLI_COMMANDS: List[Tuple[str, str, str]] = [
    ("research-pulse", "Today's digest", "Fetch + open browser preview"),
    ('search "query"', "Search papers", "arXiv, OpenAlex, Crossref, Europe PMC"),
    ('search --venue neurips', "Filter by conference", "Also --core A, --year 2024"),
    ("conferences", "CORE venue list", "Ranked conferences & journals"),
    ('follow "field"', "Follow any topic", "Plain English, no config"),
    ("topics", "Manage topics", "View or pick from 31+ domains"),
    ("config papers N", "Digest size", "Set papers per topic (1–25, default 5)"),
    ("desktop", "Desktop app", "Launch the GUI application"),
    ("chat", "Interactive agent", "Compare, insights, memory"),
    ("help", "Command reference", "Full list of options"),
]

AGENT_COMMANDS: List[Tuple[str, str]] = [
    ("search <query>", "Find papers by keyword"),
    ("search --all <q>", "Search every source"),
    ("topic <id>", "Papers in a topic"),
    ("summarize <n>", "TL;DR for result #n"),
    ("compare <n1> <n2>", "Side-by-side comparison"),
    ("insights", "Trends, gaps, contradictions"),
    ("memory", "Your reading history"),
    ("help", "All agent commands"),
    ("quit", "Save and exit"),
]


def _plain(msg: str) -> None:
    print(msg)


def rule(title: Optional[str] = None) -> None:
    if HAS_RICH:
        console.rule(f"[bold {ACCENT}]{title}[/]" if title else None)
    elif title:
        _plain(f"\n{'─' * 12} {title} {'─' * 12}")


def success(msg: str) -> None:
    if HAS_RICH:
        console.print(f"[bold green]✓[/bold green] {msg}")
    else:
        _plain(f"OK: {msg}")


def info(msg: str) -> None:
    if HAS_RICH:
        console.print(f"[{ACCENT}]›[/] {msg}")
    else:
        _plain(msg)


def warn(msg: str) -> None:
    if HAS_RICH:
        console.print(f"[bold yellow]![/bold yellow] {msg}")
    else:
        _plain(f"WARNING: {msg}")


def error(msg: str) -> None:
    if HAS_RICH:
        console.print(f"[bold red]✗[/bold red] {msg}")
    else:
        _plain(f"ERROR: {msg}")


def banner(subtitle: str = "Your daily pulse on research") -> None:
    """Header shown at startup for main commands."""
    if not HAS_RICH:
        _plain(f"\nResearchPulse v{__version__} — {subtitle}\n")
        return

    title = Text()
    title.append("Research", style=f"bold {ACCENT}")
    title.append("Pulse", style="bold white")
    title.append(f"  v{__version__}", style=MUTED)

    body = Text(subtitle, style=MUTED)
    console.print()
    console.print(
        Panel(
            Group(title, "", body),
            border_style=ACCENT,
            box=box.ROUNDED,
            padding=(0, 2),
        )
    )


def command_palette(title: str = "Commands") -> None:
    """Compact GUI-style command cheat sheet."""
    if not HAS_RICH:
        _plain(f"\n{title}:")
        for cmd, short, _ in CLI_COMMANDS:
            _plain(f"  {cmd:22s}  {short}")
        return

    table = Table(
        show_header=True,
        header_style=f"bold {ACCENT}",
        box=box.SIMPLE_HEAD,
        padding=(0, 1),
        expand=True,
    )
    table.add_column("Command", style=f"bold {ACCENT}", ratio=2)
    table.add_column("What it does", ratio=2)
    table.add_column("Details", style=MUTED, ratio=3)

    for cmd, short, detail in CLI_COMMANDS:
        table.add_row(cmd, short, detail)

    console.print(Panel(table, title=f"[bold]{title}[/bold]", border_style=MUTED))


def agent_palette() -> None:
    """Command reference for the interactive agent."""
    if not HAS_RICH:
        _plain("\nAgent commands:")
        for cmd, desc in AGENT_COMMANDS:
            _plain(f"  {cmd:22s}  {desc}")
        return

    table = Table(show_header=True, header_style=f"bold {ACCENT}", box=box.SIMPLE, expand=True)
    table.add_column("Command", style=f"bold {ACCENT}")
    table.add_column("Description", style=MUTED)
    for cmd, desc in AGENT_COMMANDS:
        table.add_row(cmd, desc)
    console.print(Panel(table, title="[bold]Quick reference[/bold]", border_style=MUTED))


def show_help() -> None:
    banner("Free, open-source research agent")
    command_palette("Daily commands")
    if HAS_RICH:
        console.print()
        extra = Table.grid(padding=(0, 2))
        extra.add_column(style=MUTED)
        extra.add_column()
        extra.add_row("Examples:", "")
        extra.add_row("", '[cyan]research-pulse follow[/] "protein folding"')
        extra.add_row("", "[cyan]research-pulse search[/] \"transformer efficiency\"")
        extra.add_row("", "[cyan]research-pulse topics[/] ai-ml nlp cv")
        extra.add_row("Sources:", "arXiv · OpenAlex · Crossref · Europe PMC · bioRxiv")
        extra.add_row("Keys:", "None required (optional S2_API_KEY for Semantic Scholar)")
        console.print(Panel(extra, title="Tips", border_style=MUTED))
    else:
        _plain('\nExamples: research-pulse follow "protein folding"')


def show_topics(current: List[str], all_topics: list, by_id: dict) -> None:
    """Display topic picker table."""
    if not HAS_RICH:
        _plain("Your topics:")
        for tid in current:
            _plain(f"  * {by_id[tid].label} ({tid})")
        _plain("\nAll topics:")
        for i, t in enumerate(all_topics, 1):
            mark = "*" if t.id in current else " "
            _plain(f"  {mark} {i:2d}. {t.label}  ({t.id})")
        return

    following = Table(show_header=False, box=box.SIMPLE, expand=True)
    following.add_column(style=f"bold {ACCENT}")
    if current:
        for tid in current:
            following.add_row(f"● {by_id[tid].label}  [dim]({tid})[/dim]")
    else:
        following.add_row("[dim]None yet — pick below[/dim]")
    console.print(Panel(following, title="[bold]Following[/bold]", border_style=ACCENT))

    catalog = Table(
        show_header=True,
        header_style=f"bold {ACCENT}",
        box=box.SIMPLE_HEAD,
        expand=True,
    )
    catalog.add_column("#", style=MUTED, width=4, justify="right")
    catalog.add_column("", width=2)
    catalog.add_column("Topic")
    catalog.add_column("ID", style=MUTED)

    for i, t in enumerate(all_topics, 1):
        mark = "[green]●[/green]" if t.id in current else "[dim]○[/dim]"
        catalog.add_row(str(i), mark, t.label, t.id)

    console.print(Panel(catalog, title="[bold]Available topics[/bold]", border_style=MUTED))


def prompt(label: str = "> ") -> str:
    if HAS_RICH:
        return console.input(f"\n[bold {ACCENT}]{label}[/] ").strip()
    return input(f"\n{label}").strip()


def agent_prompt() -> str:
    if HAS_RICH:
        return console.input(f"\n[bold {ACCENT}]You ›[/] ").strip()
    return input("\nYou> ").strip()


def _make_progress(description: str = "Working…") -> Progress:
    return Progress(
        SpinnerColumn(style=ACCENT),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=32, complete_style=ACCENT, finished_style="green"),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )


@contextmanager
def spinner(message: str) -> Iterator[None]:
    """Indeterminate spinner for single long operations."""
    if not HAS_RICH:
        _plain(message + "…")
        yield
        return

    with Progress(
        SpinnerColumn(style=ACCENT),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task(message, total=None)
        yield


@contextmanager
def quiet_logs() -> Iterator[None]:
    """Temporarily suppress INFO logs so progress UI stays clean."""
    import logging
    root = logging.getLogger("research_agent")
    old = root.level
    root.setLevel(logging.WARNING)
    try:
        yield
    finally:
        root.setLevel(old)


@contextmanager
def search_progress(sources: List[str], query: str) -> Iterator[Callable[[str, str, int], None]]:
    """Progress bar while querying multiple sources in parallel."""
    labels = [SOURCE_DISPLAY.get(s, s) for s in sources]

    if not HAS_RICH:
        info(f'Searching {", ".join(labels)} for "{query}"…')
        done: set = set()

        def _cb(source: str, status: str, count: int) -> None:
            if source not in done:
                done.add(source)
                label = SOURCE_DISPLAY.get(source, source)
                suffix = f" ({count} papers)" if status == "done" and count else ""
                _plain(f"  [{len(done)}/{len(sources)}] {label}{suffix}")

        yield _cb
        return

    rule(f'Search · "{query}"')
    callback_holder: List[Optional[Callable]] = [None]

    with _make_progress("Querying sources") as progress:
        task = progress.add_task("Starting…", total=len(sources))
        source_tasks: Dict[str, int] = {}

        def on_source(source: str, status: str, count: int) -> None:
            label = SOURCE_DISPLAY.get(source, source)
            if source not in source_tasks:
                source_tasks[source] = progress.add_task(
                    f"[{label}]", total=1, completed=0
                )
            tid = source_tasks[source]
            if status == "done":
                progress.update(tid, description=f"[green]✓[/green] {label}  ({count})", completed=1)
                progress.advance(task)
            elif status == "failed":
                progress.update(tid, description=f"[red]✗[/red] {label}  (failed)", completed=1)
                progress.advance(task)
            elif status == "skip":
                progress.update(tid, description=f"[dim]–[/dim] {label}  (skipped)", completed=1)
                progress.advance(task)

        callback_holder[0] = on_source
        yield on_source

    console.print()


@contextmanager
def digest_progress(topic_labels: List[str]) -> Iterator[Callable[[str], None]]:
    """Progress for the daily digest pipeline."""
    if not HAS_RICH:
        info("Fetching papers from open-access sources…")
        states: Dict[str, str] = {}

        def _cb(msg: str) -> None:
            _plain(f"  {msg}")

        yield _cb
        return

    rule("Daily digest")
    chips = "  ".join(f"[{ACCENT}]{lbl}[/]" for lbl in topic_labels[:5])
    if len(topic_labels) > 5:
        chips += f"  [dim]+{len(topic_labels) - 5} more[/dim]"
    console.print(f"  Topics: {chips}\n")

    with _make_progress("Building digest") as progress:
        main = progress.add_task("Preparing…", total=max(len(topic_labels), 1))
        topic_task_ids: Dict[str, int] = {}

        def on_progress(msg: str) -> None:
            if msg.startswith("fetch:"):
                tid = msg.split(":", 1)[1]
                label = tid
                topic_task_ids[tid] = progress.add_task(f"  {label}", total=3, completed=0)
            elif msg.startswith("raw:"):
                _, tid, count = msg.split(":", 2)
                if tid in topic_task_ids:
                    progress.update(topic_task_ids[tid], completed=1,
                                    description=f"  {tid}  fetched {count}")
            elif msg.startswith("done:"):
                _, tid, raw, picked = msg.split(":", 3)
                if tid in topic_task_ids:
                    progress.update(
                        topic_task_ids[tid],
                        completed=3,
                        description=(
                            f"  [green]✓[/green] {tid}  "
                            f"{raw} found → [bold]{picked}[/bold] selected"
                        ),
                    )
                progress.advance(main)
            elif msg.startswith("news:"):
                count = msg.split(":", 1)[1]
                progress.update(main, description=f"[green]✓[/green] News items: {count}")
            elif msg.startswith("render:"):
                progress.update(main, description="[green]✓[/green] Rendering preview…", completed=1)

        yield on_progress

    console.print()


def show_digest_summary(papers_by_topic: dict, topic_labels: dict) -> None:
    """Short summary table after digest completes."""
    if not papers_by_topic:
        warn("No new papers today.")
        return

    if not HAS_RICH:
        for tid, papers in papers_by_topic.items():
            lbl = topic_labels.get(tid, tid)
            _plain(f"  {lbl}: {len(papers)} papers")
        return

    table = Table(show_header=True, header_style=f"bold {ACCENT}", box=box.SIMPLE, expand=True)
    table.add_column("Topic")
    table.add_column("Papers", justify="right", style="bold")
    table.add_column("Top result", style=MUTED, ratio=2)

    total = 0
    for tid, papers in papers_by_topic.items():
        lbl = topic_labels.get(tid, tid)
        top = papers[0].title[:55] + "…" if papers and len(papers[0].title) > 55 else (papers[0].title if papers else "—")
        table.add_row(lbl, str(len(papers)), top or "—")
        total += len(papers)

    console.print(Panel(table, title=f"[bold]Digest ready[/bold] · {total} papers", border_style="green"))
