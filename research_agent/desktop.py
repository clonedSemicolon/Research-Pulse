"""ResearchPulse Desktop Application.

A modern, minimalist desktop GUI for browsing research papers, managing topics,
and tracking reading history. All CLI commands available via GUI.
"""

from __future__ import annotations

import threading
import webbrowser
from datetime import datetime
from typing import Dict, List, Optional

try:
    import customtkinter as ctk
    from customtkinter import CTk, CTkFrame, CTkLabel, CTkButton, CTkEntry
    from customtkinter import CTkScrollableFrame, CTkTextbox, CTkOptionMenu
    from customtkinter import CTkCheckBox, CTkTabview, CTkProgressBar
except ImportError:
    raise ImportError(
        "customtkinter is required for the desktop app. "
        "Install it with: pip install research-pulse[desktop]"
    )

from .config import ROOT, load_topics, topics_by_id
from .local_config import ensure_ready, get_topics, save
from .memory import ResearchMemory
from .models import Paper
from .search import search_papers, search_by_topic, _search_cache
from .venues import enrich_paper, CORE_ORDER, list_venues, filter_papers, enrich_papers, lookup_core


# ── Modern Theme ─────────────────────────────────────────────────────────

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

COLORS = {
    "bg": "#0f0f14",
    "surface": "#1a1a24",
    "surface_light": "#252532",
    "card": "#1e1e2e",
    "card_hover": "#2a2a3c",
    "accent": "#6c63ff",
    "accent_hover": "#5a52e0",
    "accent_dim": "#4a42c0",
    "text": "#e8e6f0",
    "text_secondary": "#a8a6b8",
    "text_muted": "#6c6a7a",
    "success": "#4ade80",
    "warning": "#fbbf24",
    "error": "#f87171",
    "star": "#fbbf24",
    "border": "#2a2a3c",
    "divider": "#1f1f2e",
}

FONT_TITLE = ("Segoe UI", 20, "bold")
FONT_HEADING = ("Segoe UI", 14, "bold")
FONT_SUBHEADING = ("Segoe UI", 12, "bold")
FONT_BODY = ("Segoe UI", 11)
FONT_SMALL = ("Segoe UI", 10)
FONT_TINY = ("Segoe UI", 9)


# ── Helpers ──────────────────────────────────────────────────────────────

def _truncate(text: str, max_len: int = 150) -> str:
    return text[:max_len] + "..." if len(text) > max_len else text


def _core_badge(rank: str) -> str:
    if not rank:
        return ""
    return f" [{rank}]"


def _stars(rating: int) -> str:
    return "\u2605" * rating + "\u2606" * (5 - rating)


# ── Paper Card Widget ────────────────────────────────────────────────────

class PaperCard(CTkFrame):
    """A clean, modern card displaying a paper summary."""

    def __init__(self, master, paper: Paper, index: int, on_click=None, **kwargs):
        super().__init__(master, fg_color=COLORS["card"], corner_radius=10, **kwargs)
        self.paper = paper
        self.index = index
        self.on_click = on_click

        self.grid_columnconfigure(0, weight=1)

        content = CTkFrame(self, fg_color="transparent")
        content.grid(row=0, column=0, sticky="ew", padx=16, pady=14)
        content.grid_columnconfigure(0, weight=1)

        badge_frame = CTkFrame(content, fg_color=COLORS["accent"], corner_radius=12, width=28, height=28)
        badge_frame.grid(row=0, column=0, sticky="w", pady=(0, 8))
        badge_frame.grid_propagate(False)
        CTkLabel(
            badge_frame,
            text=str(index),
            font=("Segoe UI", 10, "bold"),
            text_color="#ffffff",
        ).place(relx=0.5, rely=0.5, anchor="center")

        rank_badge = _core_badge(paper.core_rank or "")
        CTkLabel(
            content,
            text=f"{paper.title}{rank_badge}",
            font=FONT_SUBHEADING,
            text_color=COLORS["text"],
            wraplength=520,
            anchor="w",
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(0, 6))

        abstract = _truncate(paper.abstract or "No abstract available.", 180)
        CTkLabel(
            content,
            text=abstract,
            font=FONT_SMALL,
            text_color=COLORS["text_secondary"],
            wraplength=520,
            anchor="w",
            justify="left",
        ).grid(row=2, column=0, sticky="ew", pady=(0, 8))

        footer = CTkFrame(content, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew")
        footer.grid_columnconfigure(0, weight=1)

        meta_parts = []
        if paper.authors:
            meta_parts.append(paper.authors[0] + (" et al." if len(paper.authors) > 1 else ""))
        if paper.published:
            meta_parts.append(paper.published.strftime("%Y-%m-%d"))
        if paper.citations:
            meta_parts.append(f"{paper.citations} cit.")
        if hasattr(paper, "score") and paper.score:
            meta_parts.append(f"{paper.score:.2f}")

        CTkLabel(
            footer,
            text=" \u00b7 ".join(meta_parts),
            font=FONT_TINY,
            text_color=COLORS["text_muted"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        if paper.source:
            source_frame = CTkFrame(footer, fg_color=COLORS["surface_light"], corner_radius=8)
            source_frame.grid(row=0, column=1, sticky="e", padx=(8, 0))
            CTkLabel(
                source_frame,
                text=paper.source,
                font=FONT_TINY,
                text_color=COLORS["text_secondary"],
            ).pack(padx=8, pady=2)

        CTkButton(
            footer,
            text="Open",
            width=60,
            height=28,
            font=FONT_SMALL,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            command=lambda: self._open_paper(),
        ).grid(row=0, column=2, sticky="e", padx=(8, 0))

        self.bind("<Enter>", lambda e: self.configure(fg_color=COLORS["card_hover"]))
        self.bind("<Leave>", lambda e: self.configure(fg_color=COLORS["card"]))
        self.bind("<Button-1>", lambda e: self._on_click())
        for child in self.winfo_children():
            child.bind("<Button-1>", lambda e: self._on_click())

    def _open_paper(self):
        if self.paper.url:
            webbrowser.open(self.paper.url)

    def _on_click(self):
        if self.on_click:
            self.on_click(self.paper, self.index)


# ── Paper Detail Panel ───────────────────────────────────────────────────

class PaperDetailPanel(CTkFrame):
    """Right-side panel showing full paper details."""

    def __init__(self, master, memory: ResearchMemory, **kwargs):
        super().__init__(master, fg_color=COLORS["surface"], **kwargs)
        self.memory = memory
        self.current_paper: Optional[Paper] = None
        self.current_index: int = 0

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = CTkFrame(self, fg_color=COLORS["bg"], corner_radius=0)
        header.grid(row=0, column=0, sticky="ew", padx=0, pady=0)
        header.grid_columnconfigure(0, weight=1)

        self.title_label = CTkLabel(
            header,
            text="Select a paper to view details",
            font=FONT_HEADING,
            text_color=COLORS["text"],
            wraplength=360,
            anchor="w",
            justify="left",
        )
        self.title_label.grid(row=0, column=0, sticky="ew", padx=16, pady=16)

        self.content = CTkTextbox(
            self,
            font=("Consolas", 11),
            text_color=COLORS["text"],
            fg_color=COLORS["card"],
            corner_radius=8,
            wrap="word",
        )
        self.content.grid(row=1, column=0, sticky="nsew", padx=12, pady=12)

        actions = CTkFrame(self, fg_color=COLORS["bg"], corner_radius=0)
        actions.grid(row=2, column=0, sticky="ew", padx=0, pady=0)

        btn_frame = CTkFrame(actions, fg_color="transparent")
        btn_frame.pack(fill="x", padx=12, pady=12)

        CTkButton(
            btn_frame,
            text="Open in Browser",
            font=FONT_SMALL,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            command=self._open_browser,
        ).pack(side="left", padx=(0, 8))

        CTkButton(
            btn_frame,
            text="Rate",
            font=FONT_SMALL,
            fg_color=COLORS["surface_light"],
            hover_color=COLORS["card_hover"],
            command=self._rate_paper,
        ).pack(side="left", padx=(0, 8))

        self.rating_var = ctk.StringVar(value="")
        CTkLabel(
            btn_frame,
            textvariable=self.rating_var,
            font=FONT_SMALL,
            text_color=COLORS["star"],
        ).pack(side="left")

    def show_paper(self, paper: Paper, index: int):
        self.current_paper = paper
        self.current_index = index

        rank = _core_badge(paper.core_rank or "")
        self.title_label.configure(text=f"{paper.title}{rank}")

        self.content.configure(state="normal")
        self.content.delete("1.0", "end")

        lines = []
        if paper.authors:
            lines.append(f"Authors: {', '.join(paper.authors[:5])}")
        if paper.published:
            lines.append(f"Published: {paper.published.strftime('%Y-%m-%d')}")
        if paper.venue:
            lines.append(f"Venue: {paper.venue}{_core_badge(paper.core_rank or '')}")
        if paper.url:
            lines.append(f"URL: {paper.url}")
        if paper.citations:
            lines.append(f"Citations: {paper.citations}")
        if paper.source:
            lines.append(f"Source: {paper.source}")
        if hasattr(paper, "score") and paper.score:
            lines.append(f"Relevance Score: {paper.score:.3f}")

        lines.append("")
        lines.append("\u2500" * 40)
        lines.append("")
        lines.append(paper.abstract or "No abstract available.")

        self.content.insert("1.0", "\n".join(lines))
        self.content.configure(state="disabled")

        mem = self.memory.get_paper(paper.url or paper.title)
        if mem and mem.rating:
            self.rating_var.set(_stars(mem.rating))
        else:
            self.rating_var.set("")

    def _open_browser(self):
        if self.current_paper and self.current_paper.url:
            webbrowser.open(self.current_paper.url)

    def _rate_paper(self):
        if not self.current_paper:
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("Rate Paper")
        dialog.geometry("280x160")
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(fg_color=COLORS["surface"])

        CTkLabel(
            dialog,
            text="Rate this paper (1-5):",
            font=FONT_BODY,
        ).pack(pady=(20, 10))

        rating_var = ctk.StringVar(value="5")
        CTkOptionMenu(
            dialog,
            values=["1", "2", "3", "4", "5"],
            variable=rating_var,
            font=FONT_BODY,
        ).pack(pady=(0, 10))

        def save_rating():
            rating = int(rating_var.get())
            paper = self.current_paper
            self.memory.record_paper(
                paper_id=paper.url or paper.title,
                title=paper.title,
                url=paper.url or "",
                source=paper.source or "",
                rating=rating,
            )
            self.rating_var.set(_stars(rating))
            dialog.destroy()

        CTkButton(
            dialog,
            text="Save",
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            command=save_rating,
        ).pack(pady=(0, 16))


# ── Loading Indicator ────────────────────────────────────────────────────

class LoadingIndicator(CTkFrame):
    """Animated loading indicator."""

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)

        self.label = CTkLabel(
            self,
            text="Loading...",
            font=FONT_BODY,
            text_color=COLORS["text_secondary"],
        )
        self.label.pack(pady=30)

        self._dots = 0
        self._running = False

    def start(self, message: str = "Loading"):
        self._running = True
        self._message = message
        self._animate()

    def stop(self):
        self._running = False

    def _animate(self):
        if not self._running:
            return
        self._dots = (self._dots + 1) % 4
        dots = "." * self._dots
        self.label.configure(text=f"{self._message}{dots}")
        self.after(300, self._animate)


# ── Navigation Button ────────────────────────────────────────────────────

class NavButton(CTkButton):
    """Modern navigation button with icon support."""

    def __init__(self, master, text: str, command=None, active=False, **kwargs):
        super().__init__(
            master,
            text=text,
            font=FONT_BODY,
            fg_color=COLORS["accent"] if active else "transparent",
            hover_color=COLORS["accent_hover"] if active else COLORS["surface_light"],
            anchor="w",
            height=36,
            corner_radius=8,
            command=command,
            **kwargs,
        )


# ── Filter Dropdown Builder ──────────────────────────────────────────────

def _make_filter_dropdown(parent, label: str, values: List[str], variable: ctk.StringVar, command):
    """Build a compact label+dropdown combo for the filter bar."""
    group = CTkFrame(parent, fg_color="transparent")
    group.pack(side="left", padx=(0, 6), pady=0)

    CTkLabel(
        group,
        text=label,
        font=FONT_TINY,
        text_color=COLORS["text_muted"],
    ).pack(side="left", padx=(0, 3))

    menu = CTkOptionMenu(
        group,
        values=values,
        variable=variable,
        font=FONT_SMALL,
        width=100,
        height=28,
        fg_color=COLORS["bg"],
        button_color=COLORS["accent"],
        button_hover_color=COLORS["accent_hover"],
        command=command,
    )
    menu.pack(side="left")
    return menu


# ── Main Application ─────────────────────────────────────────────────────

class ResearchPulseApp(CTk):
    """Main desktop application window."""

    def __init__(self):
        super().__init__()

        self.title("ResearchPulse")
        self.geometry("1200x750")
        self.minsize(900, 600)
        self.configure(fg_color=COLORS["bg"])

        self.memory = ResearchMemory()
        self._all_papers: List[Paper] = []  # original, unfiltered papers
        self.papers: List[Paper] = []       # currently displayed (filtered/sorted)
        self._display_title: str = ""       # current display title (for filter bar context)
        self.current_topic: str = ""
        self._loading = False
        self._active_nav = "today"
        self.venue_map: Dict[str, str] = {}  # display name -> catalog name for venue dropdown

        self._build_ui()
        self._load_topics()

    # ── Sidebar ──────────────────────────────────────────────────────────

    def _build_ui(self):
        """Build the main layout."""
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── Sidebar ──────────────────────────────────────────────────────
        sidebar = CTkFrame(self, fg_color=COLORS["surface"], width=240, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        # Logo
        logo_frame = CTkFrame(sidebar, fg_color="transparent")
        logo_frame.pack(fill="x", padx=16, pady=(20, 16))

        CTkLabel(
            logo_frame,
            text="ResearchPulse",
            font=("Segoe UI", 18, "bold"),
            text_color=COLORS["accent"],
        ).pack(anchor="w")

        CTkLabel(
            logo_frame,
            text="Daily Research Digest",
            font=FONT_TINY,
            text_color=COLORS["text_muted"],
        ).pack(anchor="w", pady=(2, 0))

        # Search
        search_frame = CTkFrame(sidebar, fg_color="transparent")
        search_frame.pack(fill="x", padx=16, pady=(0, 16))

        CTkLabel(
            search_frame,
            text="Search",
            font=FONT_SMALL,
            text_color=COLORS["text_secondary"],
        ).pack(anchor="w", pady=(0, 4))

        self.search_entry = CTkEntry(
            search_frame,
            placeholder_text="Search papers...",
            font=FONT_BODY,
            height=34,
            border_width=1,
            border_color=COLORS["border"],
            fg_color=COLORS["bg"],
        )
        self.search_entry.pack(fill="x", pady=(0, 6))
        self.search_entry.bind("<Return>", lambda e: self._on_search())

        CTkButton(
            search_frame,
            text="Search",
            font=FONT_SMALL,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            height=30,
            command=self._on_search,
        ).pack(fill="x")

        # Topics
        topics_frame = CTkFrame(sidebar, fg_color="transparent")
        topics_frame.pack(fill="x", padx=16, pady=(0, 12))

        CTkLabel(
            topics_frame,
            text="Topics",
            font=FONT_SMALL,
            text_color=COLORS["text_secondary"],
        ).pack(anchor="w", pady=(0, 4))

        self.topics_frame = CTkScrollableFrame(
            topics_frame,
            fg_color="transparent",
            height=160,
        )
        self.topics_frame.pack(fill="x")

        # Navigation
        nav_frame = CTkFrame(sidebar, fg_color="transparent")
        nav_frame.pack(fill="x", padx=12, pady=(8, 16))

        CTkLabel(
            nav_frame,
            text="Navigation",
            font=FONT_SMALL,
            text_color=COLORS["text_secondary"],
        ).pack(anchor="w", padx=4, pady=(0, 8))

        self.nav_buttons = {}

        nav_items = [
            ("today", "Today's Papers", self._load_today),
            ("search_results", "Search Results", None),
            ("recommendations", "Recommendations", self._show_recommendations),
            ("conferences", "Conferences", self._show_conferences),
            ("history", "Reading History", self._show_history),
            ("follow", "Follow Topic", self._show_follow_dialog),
            ("settings", "Settings", self._show_settings),
        ]

        for nav_id, text, command in nav_items:
            btn = NavButton(
                nav_frame,
                text=text,
                command=command or (lambda: None),
                active=(nav_id == self._active_nav),
            )
            btn.pack(fill="x", pady=1)
            self.nav_buttons[nav_id] = btn

        # Status bar
        status_frame = CTkFrame(sidebar, fg_color=COLORS["bg"], corner_radius=0)
        status_frame.pack(side="bottom", fill="x")

        self.status_var = ctk.StringVar(value="Ready")
        CTkLabel(
            status_frame,
            textvariable=self.status_var,
            font=FONT_TINY,
            text_color=COLORS["text_muted"],
        ).pack(padx=16, pady=12)

        # ── Main Content ─────────────────────────────────────────────────
        main = CTkFrame(self, fg_color=COLORS["bg"])
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_rowconfigure(0, weight=0)  # filter bar - auto height
        main.grid_rowconfigure(1, weight=1)  # content area
        main.grid_columnconfigure(0, weight=1)
        main.grid_columnconfigure(1, weight=0)  # detail panel fixed width

        self._build_filter_bar(main)

        self.papers_frame = CTkScrollableFrame(
            main,
            fg_color="transparent",
        )
        self.papers_frame.grid(row=1, column=0, sticky="nsew", padx=(8, 0), pady=(4, 8))

        self.detail_panel = PaperDetailPanel(
            main,
            memory=self.memory,
            width=420,
        )
        self.detail_panel.grid(row=1, column=1, sticky="nsew", padx=(0, 8), pady=(4, 8))
        self.detail_panel.grid_propagate(False)

        self.loading = LoadingIndicator(main)

    # ── Filter Bar ───────────────────────────────────────────────────────

    def _build_filter_bar(self, parent):
        """Build the horizontal filter bar above the paper list."""
        self.filter_bar = CTkFrame(parent, fg_color=COLORS["surface"], corner_radius=0)
        self.filter_bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=0, pady=0)

        # ── Filter dropdowns (left side) ──
        dropdowns_row = CTkFrame(self.filter_bar, fg_color="transparent")
        dropdowns_row.pack(fill="x", padx=(12, 8), pady=(10, 0))

        self.sort_filter_var = ctk.StringVar(value="Relevance")
        _make_filter_dropdown(
            dropdowns_row, "Sort:",
            ["Relevance", "Newest", "Oldest", "Most Cited", "Title A-Z"],
            self.sort_filter_var, self._on_filter_changed,
        )

        self.core_filter_var = ctk.StringVar(value="Any CORE")
        _make_filter_dropdown(
            dropdowns_row, "CORE:",
            ["Any CORE", "A*", "A", "B", "C"],
            self.core_filter_var, self._on_filter_changed,
        )

        current_year = datetime.now().year
        years = ["Any Year"] + [str(y) for y in range(current_year, current_year - 5, -1)]
        self.year_filter_var = ctk.StringVar(value="Any Year")
        _make_filter_dropdown(
            dropdowns_row, "Year:",
            years,
            self.year_filter_var, self._on_filter_changed,
        )

        self.citations_filter_var = ctk.StringVar(value="Any Citations")
        _make_filter_dropdown(
            dropdowns_row, "Citations:",
            ["Any Citations", "5+", "10+", "25+", "50+", "100+"],
            self.citations_filter_var, self._on_filter_changed,
        )

        # Build venue dropdown from CORE catalog
        venue_values = self._build_venue_list()
        self.venue_filter_var = ctk.StringVar(value="All Venues")
        _make_filter_dropdown(
            dropdowns_row, "Venue:",
            venue_values,
            self.venue_filter_var, self._on_filter_changed,
        )

        self.show_filter_var = ctk.StringVar(value="20")
        _make_filter_dropdown(
            dropdowns_row, "Show:",
            ["10", "20", "30", "50", "100"],
            self.show_filter_var, self._on_filter_changed,
        )

        # ── Title filter + action buttons (bottom row) ──
        bottom_row = CTkFrame(self.filter_bar, fg_color="transparent")
        bottom_row.pack(fill="x", padx=(12, 8), pady=(6, 10))

        CTkLabel(
            bottom_row,
            text="Title:",
            font=FONT_TINY,
            text_color=COLORS["text_muted"],
        ).pack(side="left", padx=(0, 4))

        self.title_filter_var = ctk.StringVar()
        self.title_filter_var.trace_add("write", self._on_filter_changed)
        title_entry = CTkEntry(
            bottom_row,
            textvariable=self.title_filter_var,
            placeholder_text="Filter by title or abstract...",
            font=FONT_SMALL,
            height=28,
            width=220,
            border_width=1,
            border_color=COLORS["border"],
            fg_color=COLORS["bg"],
        )
        title_entry.pack(side="left", padx=(0, 8))
        title_entry.bind("<Return>", lambda e: self._apply_filters())

        # Active filter count indicator
        self.filter_active_label = CTkLabel(
            bottom_row,
            text="",
            font=FONT_TINY,
            text_color=COLORS["accent"],
        )
        self.filter_active_label.pack(side="left", padx=(4, 10))

        # Apply button (primary action)
        self.apply_btn = CTkButton(
            bottom_row,
            text="Apply",
            font=FONT_SMALL,
            width=64,
            height=28,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            command=self._apply_filters,
        )
        self.apply_btn.pack(side="right", padx=(4, 0))

        # Reset button
        CTkButton(
            bottom_row,
            text="Reset",
            font=FONT_SMALL,
            width=64,
            height=28,
            fg_color=COLORS["surface_light"],
            hover_color=COLORS["error"],
            command=self._reset_filters,
        ).pack(side="right", padx=(0, 4))

    def _build_venue_list(self) -> List[str]:
        """Build venue name list from CORE catalog, sorted by rank then name."""
        entries = list_venues()
        self.venue_map = {}
        venue_entries = []
        for entry in entries:
            names = entry.get("names", [])
            label = names[0] if names else entry.get("id", "")
            core = entry.get("core", "")
            display = f"{label} [{core}]" if core else label
            self.venue_map[display] = label  # map display name back to venue name for filtering
            venue_entries.append((core, label, display))

        # Sort by CORE rank (A* first), then alphabetically
        venue_entries.sort(key=lambda e: (-CORE_ORDER.get(e[0], 0), e[1].lower()))
        return ["All Venues"] + [ve[2] for ve in venue_entries]

    # ── Filter Logic ─────────────────────────────────────────────────────

    def _on_filter_changed(self, *args):
        """Called when any filter widget value changes - updates indicator only."""
        self._update_filter_indicator()

    def _apply_filters(self, event=None):
        """Apply current filter values to the paper list (explicit user action)."""
        self._refresh_display()

    def _get_filter_values(self):
        """Get current filter values in a normalized dict."""
        core = self.core_filter_var.get()
        year = self.year_filter_var.get()
        citations = self.citations_filter_var.get()
        venue = self.venue_filter_var.get()

        cit_val = 0
        if citations != "Any Citations":
            cit_val = int(citations.replace("+", ""))

        # Map venue display name back to catalog name
        venue_name = None
        if venue and venue != "All Venues":
            venue_name = self.venue_map.get(venue, venue)

        return {
            "core_min": None if core == "Any CORE" else core,
            "year": None if year == "Any Year" else int(year),
            "min_citations": cit_val,
            "venue": venue_name,
            "sort": self.sort_filter_var.get(),
            "title_filter": self.title_filter_var.get().strip().lower(),
            "max_show": int(self.show_filter_var.get()),
        }

    def _get_active_filter_count(self) -> int:
        """Return how many filters are currently active (non-default)."""
        count = 0
        if self.core_filter_var.get() != "Any CORE":
            count += 1
        if self.year_filter_var.get() != "Any Year":
            count += 1
        if self.citations_filter_var.get() != "Any Citations":
            count += 1
        if self.venue_filter_var.get() != "All Venues":
            count += 1
        if self.sort_filter_var.get() != "Relevance":
            count += 1
        if self.title_filter_var.get().strip():
            count += 1
        return count

    def _update_filter_indicator(self):
        """Update the active filter count label."""
        count = self._get_active_filter_count()
        if count > 0:
            self.filter_active_label.configure(text=f"{count} filter{'s' if count > 1 else ''} active")
        else:
            self.filter_active_label.configure(text="")

    def _refresh_display(self):
        """Re-apply current filters to the original paper list and update display."""
        self._update_filter_indicator()

        if not self._all_papers:
            return

        filters = self._get_filter_values()
        papers = list(self._all_papers)

        # Apply CORE / Year / Venue filters (post-fetch)
        venues_list = [filters["venue"]] if filters["venue"] else None
        filtered = filter_papers(
            papers,
            venues=venues_list,
            core_min=None,  # we handle CORE exact-match below
            year=filters["year"],
        )

        # Apply CORE rank filter -- exact match, not min-rank
        if filters["core_min"]:
            target_rank = filters["core_min"]
            filtered = [
                p for p in filtered
                if (p.core_rank or lookup_core(p.venue)) == target_rank
            ]

        # Apply citation filter
        if filters["min_citations"] > 0:
            filtered = [p for p in filtered if p.citations >= filters["min_citations"]]

        # Apply title/abstract text filter
        if filters["title_filter"]:
            query = filters["title_filter"]
            filtered = [
                p for p in filtered
                if query in p.title.lower()
                or query in (p.abstract or "").lower()
            ]

        # Apply sorting
        filtered = self._sort_papers(filtered, filters["sort"])

        # Apply show limit
        max_show = filters["max_show"]
        if len(filtered) > max_show:
            filtered = filtered[:max_show]

        self._display_papers(filtered, self._display_title)
        self.status_var.set(f"Showing {len(filtered)} of {len(self._all_papers)} papers")

    def _sort_papers(self, papers: List[Paper], sort_mode: str) -> List[Paper]:
        """Sort papers by the selected sort mode."""
        if sort_mode == "Newest":
            papers.sort(key=lambda p: p.published or datetime.min, reverse=True)
        elif sort_mode == "Oldest":
            papers.sort(key=lambda p: p.published or datetime.min, reverse=False)
        elif sort_mode == "Most Cited":
            papers.sort(key=lambda p: p.citations, reverse=True)
        elif sort_mode == "Title A-Z":
            papers.sort(key=lambda p: p.title.lower())
        else:  # Relevance (default)
            papers.sort(
                key=lambda p: p.score if hasattr(p, "score") and p.score else 0,
                reverse=True,
            )
        return papers

    def _reset_filters(self):
        """Reset all filters to default and show all papers."""
        self.sort_filter_var.set("Relevance")
        self.core_filter_var.set("Any CORE")
        self.year_filter_var.set("Any Year")
        self.citations_filter_var.set("Any Citations")
        self.venue_filter_var.set("All Venues")
        self.title_filter_var.set("")
        self._update_filter_indicator()

        if self._all_papers:
            self.papers = list(self._all_papers)
            self._display_papers(self.papers, self._display_title)
            self.status_var.set(f"Showing {len(self.papers)} papers")

    # ── Navigation ───────────────────────────────────────────────────────

    def _set_active_nav(self, nav_id: str):
        """Update active navigation button."""
        for nid, btn in self.nav_buttons.items():
            if nid == nav_id:
                btn.configure(fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"])
            else:
                btn.configure(fg_color="transparent", hover_color=COLORS["surface_light"])
        self._active_nav = nav_id

    def _load_topics(self):
        """Load and display topic checkboxes."""
        topics_list, _ = load_topics()
        current = get_topics() or ensure_ready(verbose=False, force_zotero=True)

        for widget in self.topics_frame.winfo_children():
            widget.destroy()

        self.topic_vars: Dict[str, ctk.BooleanVar] = {}

        for topic in topics_list[:10]:
            var = ctk.BooleanVar(value=topic.id in current)
            self.topic_vars[topic.id] = var

            CTkCheckBox(
                self.topics_frame,
                text=topic.label,
                variable=var,
                font=FONT_SMALL,
                text_color=COLORS["text"],
                fg_color=COLORS["accent"],
                hover_color=COLORS["accent_hover"],
                border_color=COLORS["border"],
                command=lambda tid=topic.id: self._on_topic_toggle(tid),
            ).pack(anchor="w", pady=2)

    def _on_topic_toggle(self, topic_id: str):
        """Handle topic checkbox toggle."""
        selected = [tid for tid, var in self.topic_vars.items() if var.get()]
        save(selected, source="manual")
        self.status_var.set(f"Topics: {', '.join(selected[:3])}{'...' if len(selected) > 3 else ''}")

    def _clear_topic_selections(self):
        """Uncheck all topic checkboxes (used when searching independently)."""
        for var in self.topic_vars.values():
            var.set(False)

    # ── Search / Load Data ───────────────────────────────────────────────

    def _on_search(self):
        """Handle search button click."""
        query = self.search_entry.get().strip()
        if not query or self._loading:
            return

        self._loading = True
        self._set_active_nav("search_results")
        self._clear_topic_selections()
        self.status_var.set(f"Searching: {query}...")
        self._clear_papers()
        self._show_loading("Searching")

        def do_search():
            try:
                results = search_papers(
                    query,
                    days=30,
                    limit=50,
                )
                self.after(0, lambda: self._on_data_loaded(results, f"Search: {query}"))
            except Exception as e:
                self.after(0, lambda: self.status_var.set(f"Error: {e}"))
            finally:
                self.after(0, self._hide_loading)
                self._loading = False

        threading.Thread(target=do_search, daemon=True).start()

    def _load_today(self):
        """Load today's papers for selected topics."""
        if self._loading:
            return

        selected = [tid for tid, var in self.topic_vars.items() if var.get()]
        if not selected:
            self.status_var.set("Select at least one topic")
            return

        self._loading = True
        self._set_active_nav("today")
        self.status_var.set("Loading papers...")
        self._clear_papers()
        self._show_loading("Loading papers")

        def do_load():
            try:
                all_papers = []
                for topic_id in selected[:3]:
                    papers = search_by_topic(topic_id, days=7, limit=25)
                    all_papers.extend(papers)

                seen = set()
                unique = []
                for p in all_papers:
                    key = p.id or p.url or p.title
                    if key not in seen:
                        seen.add(key)
                        unique.append(p)

                enrich_papers(unique)
                self.after(0, lambda: self._on_data_loaded(unique, "Today's Papers"))
            except Exception as e:
                self.after(0, lambda: self.status_var.set(f"Error: {e}"))
            finally:
                self.after(0, self._hide_loading)
                self._loading = False

        threading.Thread(target=do_load, daemon=True).start()

    def _show_recommendations(self):
        """Show personalized recommendations."""
        if self._loading:
            return

        self._loading = True
        self._set_active_nav("recommendations")
        self.status_var.set("Generating recommendations...")
        self._clear_papers()
        self._show_loading("Analyzing your interests")

        def do_recommend():
            try:
                from .recommend import get_recommendations

                selected = [tid for tid, var in self.topic_vars.items() if var.get()]
                all_papers = []
                for topic_id in selected[:2]:
                    papers = search_by_topic(topic_id, days=14, limit=15)
                    all_papers.extend(papers)

                seen = set()
                unique = []
                for p in all_papers:
                    key = p.id or p.url or p.title
                    if key not in seen:
                        seen.add(key)
                        unique.append(p)

                recommendations = get_recommendations(unique, self.memory, limit=15)
                papers = [rec.paper for rec in recommendations]

                self.after(0, lambda: self._on_data_loaded(papers, "Recommended for You"))
            except Exception as e:
                self.after(0, lambda: self.status_var.set(f"Error: {e}"))
            finally:
                self.after(0, self._hide_loading)
                self._loading = False

        threading.Thread(target=do_recommend, daemon=True).start()

    def _show_conferences(self):
        """Show CORE-ranked conferences."""
        self._set_active_nav("conferences")
        self._clear_papers()
        self._all_papers = []
        self.papers = []
        self._display_title = ""

        try:
            entries = list_venues()
            if not entries:
                CTkLabel(
                    self.papers_frame,
                    text="No conferences found.",
                    font=FONT_BODY,
                    text_color=COLORS["text_secondary"],
                ).pack(pady=40)
                return

            CTkLabel(
                self.papers_frame,
                text=f"CORE-Ranked Conferences ({len(entries)})",
                font=FONT_HEADING,
                text_color=COLORS["text"],
            ).pack(anchor="w", padx=8, pady=(8, 16))

            sorted_entries = sorted(entries, key=lambda e: CORE_ORDER.get(e.get("core", ""), 0), reverse=True)

            for entry in sorted_entries[:50]:
                names = entry.get("names", [])
                label = names[0] if names else entry.get("id", "")
                core = entry.get("core", "")
                field = entry.get("field", "")

                card = CTkFrame(self.papers_frame, fg_color=COLORS["card"], corner_radius=8)
                card.pack(fill="x", padx=8, pady=3)

                rank_color = {
                    "A*": COLORS["accent"],
                    "A": COLORS["success"],
                    "B": COLORS["warning"],
                    "C": COLORS["text_muted"],
                }.get(core, COLORS["text_muted"])

                badge = CTkFrame(card, fg_color=rank_color, corner_radius=10, width=40, height=24)
                badge.pack(side="left", padx=(12, 8), pady=10)
                badge.grid_propagate(False)
                CTkLabel(
                    badge,
                    text=core or "?",
                    font=("Segoe UI", 9, "bold"),
                    text_color="#ffffff",
                ).place(relx=0.5, rely=0.5, anchor="center")

                info_frame = CTkFrame(card, fg_color="transparent")
                info_frame.pack(side="left", fill="x", expand=True, pady=10)

                CTkLabel(
                    info_frame,
                    text=label,
                    font=FONT_SUBHEADING,
                    text_color=COLORS["text"],
                    anchor="w",
                ).pack(anchor="w")

                if field:
                    CTkLabel(
                        info_frame,
                        text=field,
                        font=FONT_TINY,
                        text_color=COLORS["text_muted"],
                        anchor="w",
                    ).pack(anchor="w")

            self.status_var.set(f"Conferences: {len(entries)} venues")
        except Exception as e:
            self.status_var.set(f"Error: {e}")

    def _show_history(self):
        """Show reading history."""
        self._set_active_nav("history")
        self._clear_papers()
        self._all_papers = []
        self.papers = []
        self._display_title = ""

        recent = self.memory.get_recent_papers(days=30)

        if not recent:
            CTkLabel(
                self.papers_frame,
                text="No reading history yet.\nStart by loading today's papers!",
                font=FONT_BODY,
                text_color=COLORS["text_secondary"],
            ).pack(pady=40)
            self.status_var.set("History: 0 papers")
            return

        CTkLabel(
            self.papers_frame,
            text=f"Reading History ({len(recent)})",
            font=FONT_HEADING,
            text_color=COLORS["text"],
        ).pack(anchor="w", padx=8, pady=(8, 12))

        for mem in recent:
            stars = _stars(mem.rating) if mem.rating else ""
            card = CTkFrame(self.papers_frame, fg_color=COLORS["card"], corner_radius=8)
            card.pack(fill="x", padx=8, pady=3)

            info = CTkFrame(card, fg_color="transparent")
            info.pack(fill="x", padx=12, pady=10)

            CTkLabel(
                info,
                text=mem.title,
                font=FONT_SUBHEADING,
                text_color=COLORS["text"],
                wraplength=500,
                anchor="w",
            ).pack(anchor="w")

            meta = f"{stars}  {mem.read_date[:10]}  {mem.source}"
            CTkLabel(
                info,
                text=meta,
                font=FONT_TINY,
                text_color=COLORS["text_muted"],
            ).pack(anchor="w", pady=(2, 0))

        self.status_var.set(f"History: {len(recent)} papers")

    def _show_follow_dialog(self):
        """Show follow topic dialog."""
        self._set_active_nav("follow")

        dialog = ctk.CTkToplevel(self)
        dialog.title("Follow Research Area")
        dialog.geometry("400x200")
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(fg_color=COLORS["surface"])

        CTkLabel(
            dialog,
            text="Follow a Research Area",
            font=FONT_HEADING,
        ).pack(pady=(20, 16))

        CTkLabel(
            dialog,
            text="Describe your research area in plain English:",
            font=FONT_SMALL,
            text_color=COLORS["text_secondary"],
        ).pack(pady=(0, 8))

        entry = CTkEntry(
            dialog,
            placeholder_text="e.g., quantum error correction",
            font=FONT_BODY,
            width=300,
        )
        entry.pack(pady=(0, 16))

        def do_follow():
            phrase = entry.get().strip()
            if not phrase:
                return

            dialog.destroy()
            self._loading = True
            self.status_var.set(f"Following: {phrase}...")
            self._clear_papers()
            self._show_loading("Setting up topic")

            def follow_thread():
                try:
                    from .config import add_topic
                    import re

                    slug = re.sub(r"[^a-z0-9]+", "-", phrase.strip().lower()).strip("-")[:40] or "topic"

                    topics_list, _ = load_topics()
                    by_id = topics_by_id(topics_list)

                    topic_id = slug
                    if phrase.lower() in by_id:
                        topic_id = phrase.lower()

                    if topic_id not in by_id:
                        add_topic(
                            topic_id,
                            phrase.title(),
                            phrase.split(),
                            openalex=phrase,
                            semanticscholar=phrase,
                            europepmc=phrase,
                        )

                    current = get_topics()
                    if topic_id not in current:
                        current.append(topic_id)
                        save(current, source="follow")

                    papers = search_by_topic(topic_id, days=30, limit=15)

                    self.after(0, lambda: self._on_data_loaded(papers, f"Following: {phrase}"))
                    self.after(0, lambda: self._load_topics())
                except Exception as e:
                    self.after(0, lambda: self.status_var.set(f"Error: {e}"))
                finally:
                    self.after(0, self._hide_loading)
                    self._loading = False

            threading.Thread(target=follow_thread, daemon=True).start()

        CTkButton(
            dialog,
            text="Follow",
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            command=do_follow,
        ).pack()

    def _show_settings(self):
        """Show settings dialog."""
        self._set_active_nav("settings")

        dialog = ctk.CTkToplevel(self)
        dialog.title("Settings")
        dialog.geometry("400x350")
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(fg_color=COLORS["surface"])

        CTkLabel(
            dialog,
            text="Settings",
            font=FONT_HEADING,
        ).pack(pady=(20, 16))

        info_frame = CTkFrame(dialog, fg_color=COLORS["card"], corner_radius=8)
        info_frame.pack(fill="x", padx=16, pady=(0, 12))

        CTkLabel(
            info_frame,
            text=f"Data Directory: {ROOT}",
            font=FONT_SMALL,
            text_color=COLORS["text_secondary"],
            wraplength=350,
        ).pack(anchor="w", padx=12, pady=(12, 4))

        CTkLabel(
            info_frame,
            text=f"Papers in Memory: {len(self.memory.papers)}",
            font=FONT_SMALL,
        ).pack(anchor="w", padx=12, pady=4)

        CTkLabel(
            info_frame,
            text=f"Insights Generated: {len(self.memory.insights)}",
            font=FONT_SMALL,
        ).pack(anchor="w", padx=12, pady=(4, 12))

        actions_frame = CTkFrame(dialog, fg_color="transparent")
        actions_frame.pack(fill="x", padx=16, pady=(0, 16))

        def clear_cache():
            _search_cache.clear()
            self.status_var.set("Cache cleared")

        CTkButton(
            actions_frame,
            text="Clear Search Cache",
            font=FONT_SMALL,
            fg_color=COLORS["surface_light"],
            hover_color=COLORS["card_hover"],
            command=clear_cache,
        ).pack(fill="x", pady=4)

        def clear_history():
            self.memory.papers.clear()
            self.memory.save()
            self.status_var.set("History cleared")

        CTkButton(
            actions_frame,
            text="Clear Reading History",
            font=FONT_SMALL,
            fg_color=COLORS["surface_light"],
            hover_color=COLORS["card_hover"],
            command=clear_history,
        ).pack(fill="x", pady=4)

        CTkButton(
            actions_frame,
            text="Close",
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            command=dialog.destroy,
        ).pack(fill="x", pady=(8, 0))

    # ── Helpers ──────────────────────────────────────────────────────────

    def _show_loading(self, message: str = "Loading"):
        """Show loading indicator."""
        self.loading.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)
        self.loading.start(message)

    def _hide_loading(self):
        """Hide loading indicator."""
        self.loading.stop()
        self.loading.grid_forget()

    def _on_data_loaded(self, papers: List[Paper], title: str):
        """Called when data fetch completes. Stores papers and applies filters."""
        self._all_papers = papers
        self._display_title = title
        self._refresh_display()

    def _display_papers(self, papers: List[Paper], title: str):
        """Display papers in the list."""
        self._clear_papers()
        self.papers = papers

        if not papers:
            CTkLabel(
                self.papers_frame,
                text="No papers found.\nTry adjusting your filters or search terms.",
                font=FONT_BODY,
                text_color=COLORS["text_secondary"],
            ).pack(pady=40)
            self.status_var.set(f"{title} \u2014 0 papers")
            return

        title_frame = CTkFrame(self.papers_frame, fg_color="transparent")
        title_frame.pack(fill="x", padx=8, pady=(8, 12))

        CTkLabel(
            title_frame,
            text=f"{title}",
            font=FONT_HEADING,
            text_color=COLORS["text"],
        ).pack(side="left")

        CTkLabel(
            title_frame,
            text=f"{len(papers)} papers",
            font=FONT_SMALL,
            text_color=COLORS["text_muted"],
        ).pack(side="left", padx=(8, 0))

        for i, paper in enumerate(papers, 1):
            card = PaperCard(
                self.papers_frame,
                paper=paper,
                index=i,
                on_click=self._on_paper_click,
            )
            card.pack(fill="x", padx=8, pady=3)

        self.status_var.set(f"{title} \u2014 {len(papers)} papers")

    def _on_paper_click(self, paper: Paper, index: int):
        """Handle paper card click."""
        self.detail_panel.show_paper(paper, index)

    def _clear_papers(self):
        """Clear the paper widgets from the display only."""
        for widget in self.papers_frame.winfo_children():
            widget.destroy()
        self.papers = []


# ── Entry Point ──────────────────────────────────────────────────────────

def run_desktop():
    """Launch the ResearchPulse desktop application."""
    app = ResearchPulseApp()
    app.mainloop()
