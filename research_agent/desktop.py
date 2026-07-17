"""ResearchPulse Desktop Application.

A modern desktop GUI for browsing research papers, managing topics,
and tracking reading history.
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
    from customtkinter import CTkTabview, CTkCheckBox
except ImportError:
    raise ImportError(
        "customtkinter is required for the desktop app. "
        "Install it with: pip install research-pulse[desktop]"
    )

from .config import ROOT, load_topics, topics_by_id
from .local_config import ensure_ready, get_topics, save
from .memory import ResearchMemory
from .models import Paper
from .search import search_papers, search_by_topic
from .venues import enrich_paper, CORE_ORDER


# ── Theme ────────────────────────────────────────────────────────────────

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

COLORS = {
    "bg": "#1a1a2e",
    "sidebar": "#16213e",
    "card": "#0f3460",
    "accent": "#e94560",
    "text": "#ffffff",
    "text_dim": "#a0a0a0",
    "success": "#4ade80",
    "warning": "#fbbf24",
    "star": "#fbbf24",
}


# ── Helpers ──────────────────────────────────────────────────────────────

def _truncate(text: str, max_len: int = 100) -> str:
    return text[:max_len] + "..." if len(text) > max_len else text


def _core_badge(rank: str) -> str:
    if not rank:
        return ""
    return f" [{rank}]"


def _stars(rating: int) -> str:
    return "★" * rating + "☆" * (5 - rating)


# ── Paper Card Widget ────────────────────────────────────────────────────

class PaperCard(CTkFrame):
    """A clickable card displaying a paper summary."""

    def __init__(self, master, paper: Paper, index: int, on_click=None, **kwargs):
        super().__init__(master, fg_color=COLORS["card"], corner_radius=10, **kwargs)
        self.paper = paper
        self.index = index
        self.on_click = on_click

        self.grid_columnconfigure(0, weight=1)

        # Header row
        header = CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        header.grid_columnconfigure(0, weight=1)

        rank_badge = _core_badge(paper.core_rank or "")
        source_badge = f"[{paper.source}]" if paper.source else ""

        CTkLabel(
            header,
            text=f"{index}. {paper.title}{rank_badge}",
            font=("Segoe UI", 13, "bold"),
            text_color=COLORS["text"],
            wraplength=500,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        if source_badge:
            CTkLabel(
                header,
                text=source_badge,
                font=("Segoe UI", 10),
                text_color=COLORS["text_dim"],
            ).grid(row=0, column=1, sticky="e", padx=(8, 0))

        # Abstract
        abstract = _truncate(paper.abstract or "No abstract available.", 200)
        CTkLabel(
            self,
            text=abstract,
            font=("Segoe UI", 11),
            text_color=COLORS["text_dim"],
            wraplength=500,
            anchor="w",
            justify="left",
        ).grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 4))

        # Footer
        footer = CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 10))
        footer.grid_columnconfigure(0, weight=1)

        meta_parts = []
        if paper.authors:
            meta_parts.append(paper.authors[0] + (" et al." if len(paper.authors) > 1 else ""))
        if paper.published:
            meta_parts.append(paper.published.strftime("%Y-%m-%d"))
        if paper.citations:
            meta_parts.append(f"{paper.citations} citations")
        meta_parts.append(f"Score: {paper.score:.2f}" if hasattr(paper, "score") and paper.score else "")

        CTkLabel(
            footer,
            text=" · ".join([m for m in meta_parts if m]),
            font=("Segoe UI", 10),
            text_color=COLORS["text_dim"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        # Open button
        CTkButton(
            footer,
            text="Open",
            width=60,
            height=28,
            font=("Segoe UI", 11),
            fg_color=COLORS["accent"],
            hover_color="#c73e54",
            command=lambda: self._open_paper(),
        ).grid(row=0, column=1, sticky="e")

        # Click binding
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
        super().__init__(master, fg_color=COLORS["bg"], **kwargs)
        self.memory = memory
        self.current_paper: Optional[Paper] = None
        self.current_index: int = 0

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Title
        self.title_label = CTkLabel(
            self,
            text="Select a paper to view details",
            font=("Segoe UI", 16, "bold"),
            text_color=COLORS["text"],
            wraplength=400,
            anchor="w",
            justify="left",
        )
        self.title_label.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))

        # Scrollable content
        self.content = CTkTextbox(
            self,
            font=("Segoe UI", 12),
            text_color=COLORS["text"],
            fg_color=COLORS["sidebar"],
            corner_radius=8,
            wrap="word",
        )
        self.content.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 8))

        # Bottom actions
        actions = CTkFrame(self, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 16))

        CTkButton(
            actions,
            text="Open in Browser",
            font=("Segoe UI", 12),
            fg_color=COLORS["accent"],
            hover_color="#c73e54",
            command=self._open_browser,
        ).pack(side="left", padx=(0, 8))

        CTkButton(
            actions,
            text="★ Rate",
            font=("Segoe UI", 12),
            fg_color=COLORS["card"],
            hover_color="#1a4a7a",
            command=self._rate_paper,
        ).pack(side="left", padx=(0, 8))

        self.rating_var = ctk.StringVar(value="Rating: -")
        CTkLabel(
            actions,
            textvariable=self.rating_var,
            font=("Segoe UI", 11),
            text_color=COLORS["star"],
        ).pack(side="left")

    def show_paper(self, paper: Paper, index: int):
        self.current_paper = paper
        self.current_index = index

        rank = _core_badge(paper.core_rank or "")
        self.title_label.configure(text=f"{index}. {paper.title}{rank}")

        self.content.configure(state="normal")
        self.content.delete("1.0", "end")

        lines = []
        if paper.authors:
            lines.append(f"Authors: {', '.join(paper.authors[:5])}")
        if paper.published:
            lines.append(f"Published: {paper.published.strftime('%Y-%m-%d')}")
        if paper.venue:
            lines.append(f"Venue: {paper.venue}{_core_badge(paper.core_rank or '')}")
        if paper.doi:
            lines.append(f"DOI: {paper.doi}")
        if paper.citations:
            lines.append(f"Citations: {paper.citations}")
        if paper.source:
            lines.append(f"Source: {paper.source}")
        if hasattr(paper, "score") and paper.score:
            lines.append(f"Relevance Score: {paper.score:.3f}")

        lines.append("")
        lines.append("─" * 50)
        lines.append("")
        lines.append(paper.abstract or "No abstract available.")

        self.content.insert("1.0", "\n".join(lines))
        self.content.configure(state="disabled")

        # Update rating
        mem = self.memory.get_paper(paper.doi or paper.url or paper.title)
        if mem and mem.rating:
            self.rating_var.set(f"Rating: {_stars(mem.rating)}")
        else:
            self.rating_var.set("Rating: Not rated")

    def _open_browser(self):
        if self.current_paper and self.current_paper.url:
            webbrowser.open(self.current_paper.url)

    def _rate_paper(self):
        if not self.current_paper:
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("Rate Paper")
        dialog.geometry("300x150")
        dialog.transient(self)
        dialog.grab_set()

        CTkLabel(
            dialog,
            text="Rate this paper (1-5):",
            font=("Segoe UI", 14),
        ).pack(pady=(20, 10))

        rating_var = ctk.StringVar(value="5")
        CTkOptionMenu(
            dialog,
            values=["1", "2", "3", "4", "5"],
            variable=rating_var,
            font=("Segoe UI", 12),
        ).pack(pady=(0, 10))

        def save_rating():
            rating = int(rating_var.get())
            paper = self.current_paper
            self.memory.record_paper(
                paper_id=paper.doi or paper.url or paper.title,
                title=paper.title,
                url=paper.url or "",
                source=paper.source or "",
                rating=rating,
            )
            self.rating_var.set(f"Rating: {_stars(rating)}")
            dialog.destroy()

        CTkButton(
            dialog,
            text="Save",
            fg_color=COLORS["accent"],
            command=save_rating,
        ).pack(pady=(0, 10))


# ── Main Application ─────────────────────────────────────────────────────

class ResearchPulseApp(CTk):
    """Main desktop application window."""

    def __init__(self):
        super().__init__()

        self.title("ResearchPulse — Your Daily Research Digest")
        self.geometry("1200x750")
        self.minsize(900, 600)

        self.memory = ResearchMemory()
        self.papers: List[Paper] = []
        self.current_topic: str = ""

        self._build_ui()
        self._load_topics()

    def _build_ui(self):
        """Build the main layout."""
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── Sidebar ──────────────────────────────────────────────────────
        sidebar = CTkFrame(self, fg_color=COLORS["sidebar"], width=220, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        # Logo
        CTkLabel(
            sidebar,
            text="🔬 ResearchPulse",
            font=("Segoe UI", 18, "bold"),
            text_color=COLORS["accent"],
        ).pack(pady=(20, 20), padx=16, anchor="w")

        # Search
        CTkLabel(
            sidebar,
            text="Search Papers",
            font=("Segoe UI", 11),
            text_color=COLORS["text_dim"],
        ).pack(padx=16, anchor="w")

        self.search_entry = CTkEntry(
            sidebar,
            placeholder_text="Enter query...",
            font=("Segoe UI", 12),
            height=35,
        )
        self.search_entry.pack(fill="x", padx=16, pady=(4, 4))
        self.search_entry.bind("<Return>", lambda e: self._on_search())

        CTkButton(
            sidebar,
            text="Search",
            font=("Segoe UI", 11),
            fg_color=COLORS["accent"],
            hover_color="#c73e54",
            height=30,
            command=self._on_search,
        ).pack(fill="x", padx=16, pady=(0, 16))

        # Topics
        CTkLabel(
            sidebar,
            text="Your Topics",
            font=("Segoe UI", 11),
            text_color=COLORS["text_dim"],
        ).pack(padx=16, anchor="w")

        self.topics_frame = CTkScrollableFrame(
            sidebar,
            fg_color="transparent",
            height=200,
        )
        self.topics_frame.pack(fill="x", padx=16, pady=(4, 16))

        # Navigation buttons
        CTkButton(
            sidebar,
            text="📚 Today's Papers",
            font=("Segoe UI", 12),
            fg_color=COLORS["card"],
            hover_color="#1a4a7a",
            anchor="w",
            height=35,
            command=self._load_today,
        ).pack(fill="x", padx=16, pady=(0, 4))

        CTkButton(
            sidebar,
            text="📖 Reading History",
            font=("Segoe UI", 12),
            fg_color=COLORS["card"],
            hover_color="#1a4a7a",
            anchor="w",
            height=35,
            command=self._show_history,
        ).pack(fill="x", padx=16, pady=(0, 4))

        CTkButton(
            sidebar,
            text="⚙️ Settings",
            font=("Segoe UI", 12),
            fg_color=COLORS["card"],
            hover_color="#1a4a7a",
            anchor="w",
            height=35,
            command=self._show_settings,
        ).pack(fill="x", padx=16, pady=(0, 16))

        # Status
        self.status_var = ctk.StringVar(value="Ready")
        CTkLabel(
            sidebar,
            textvariable=self.status_var,
            font=("Segoe UI", 10),
            text_color=COLORS["text_dim"],
        ).pack(side="bottom", padx=16, pady=(0, 16))

        # ── Main Content ─────────────────────────────────────────────────
        main = CTkFrame(self, fg_color=COLORS["bg"])
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(0, weight=1)

        # Split: papers list (left) + detail (right)
        self.papers_frame = CTkScrollableFrame(
            main,
            fg_color="transparent",
        )
        self.papers_frame.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)

        self.detail_panel = PaperDetailPanel(
            main,
            memory=self.memory,
            width=450,
        )
        self.detail_panel.grid(row=0, column=1, sticky="nsew", padx=(0, 8), pady=8)
        self.detail_panel.grid_propagate(False)

    def _load_topics(self):
        """Load and display topic checkboxes."""
        topics_list, _ = load_topics()
        current = get_topics() or ensure_ready(verbose=False, force_zotero=True)

        for widget in self.topics_frame.winfo_children():
            widget.destroy()

        self.topic_vars: Dict[str, ctk.BooleanVar] = {}

        for topic in topics_list[:15]:  # Limit display
            var = ctk.BooleanVar(value=topic.id in current)
            self.topic_vars[topic.id] = var

            CTkCheckBox(
                self.topics_frame,
                text=topic.label,
                variable=var,
                font=("Segoe UI", 11),
                text_color=COLORS["text"],
                fg_color=COLORS["accent"],
                hover_color="#c73e54",
                command=lambda tid=topic.id: self._on_topic_toggle(tid),
            ).pack(anchor="w", pady=2)

    def _on_topic_toggle(self, topic_id: str):
        """Handle topic checkbox toggle."""
        selected = [tid for tid, var in self.topic_vars.items() if var.get()]
        save(selected, source="manual")
        self.status_var.set(f"Topics: {', '.join(selected[:3])}{'...' if len(selected) > 3 else ''}")

    def _on_search(self):
        """Handle search button click."""
        query = self.search_entry.get().strip()
        if not query:
            return

        self.status_var.set(f"Searching: {query}...")
        self._clear_papers()

        def do_search():
            try:
                results = search_papers(query, days=30, limit=20)
                self.after(0, lambda: self._display_papers(results, f"Search: {query}"))
            except Exception as e:
                self.after(0, lambda: self.status_var.set(f"Error: {e}"))

        threading.Thread(target=do_search, daemon=True).start()

    def _load_today(self):
        """Load today's papers for selected topics."""
        selected = [tid for tid, var in self.topic_vars.items() if var.get()]
        if not selected:
            self.status_var.set("Select at least one topic")
            return

        self.status_var.set("Loading papers...")
        self._clear_papers()

        def do_load():
            try:
                all_papers = []
                for topic_id in selected[:3]:  # Limit to 3 topics
                    papers = search_by_topic(topic_id, days=7, limit=10)
                    all_papers.extend(papers)

                # Deduplicate
                seen = set()
                unique = []
                for p in all_papers:
                    key = p.doi or p.url or p.title
                    if key not in seen:
                        seen.add(key)
                        unique.append(p)

                # Sort by score
                for p in unique:
                    enrich_paper(p)

                self.after(0, lambda: self._display_papers(unique, "Today's Papers"))
            except Exception as e:
                self.after(0, lambda: self.status_var.set(f"Error: {e}"))

        threading.Thread(target=do_load, daemon=True).start()

    def _display_papers(self, papers: List[Paper], title: str):
        """Display papers in the list."""
        self._clear_papers()
        self.papers = papers

        if not papers:
            CTkLabel(
                self.papers_frame,
                text="No papers found.",
                font=("Segoe UI", 14),
                text_color=COLORS["text_dim"],
            ).pack(pady=40)
            self.status_var.set(f"{title} — 0 papers")
            return

        # Title
        CTkLabel(
            self.papers_frame,
            text=f"{title} ({len(papers)} papers)",
            font=("Segoe UI", 15, "bold"),
            text_color=COLORS["text"],
        ).pack(anchor="w", padx=8, pady=(8, 16))

        # Paper cards
        for i, paper in enumerate(papers, 1):
            card = PaperCard(
                self.papers_frame,
                paper=paper,
                index=i,
                on_click=self._on_paper_click,
            )
            card.pack(fill="x", padx=8, pady=4)

        self.status_var.set(f"{title} — {len(papers)} papers")

    def _on_paper_click(self, paper: Paper, index: int):
        """Handle paper card click."""
        self.detail_panel.show_paper(paper, index)

    def _clear_papers(self):
        """Clear the papers list."""
        for widget in self.papers_frame.winfo_children():
            widget.destroy()

    def _show_history(self):
        """Show reading history."""
        self._clear_papers()

        recent = self.memory.get_recent_papers(days=30)

        if not recent:
            CTkLabel(
                self.papers_frame,
                text="No reading history yet.\nStart by loading today's papers!",
                font=("Segoe UI", 14),
                text_color=COLORS["text_dim"],
            ).pack(pady=40)
            self.status_var.set("History: 0 papers")
            return

        CTkLabel(
            self.papers_frame,
            text=f"Reading History ({len(recent)} papers)",
            font=("Segoe UI", 15, "bold"),
            text_color=COLORS["text"],
        ).pack(anchor="w", padx=8, pady=(8, 16))

        for mem in recent:
            stars = _stars(mem.rating) if mem.rating else "Not rated"
            card_frame = CTkFrame(
                self.papers_frame,
                fg_color=COLORS["card"],
                corner_radius=8,
            )
            card_frame.pack(fill="x", padx=8, pady=4)

            CTkLabel(
                card_frame,
                text=mem.title,
                font=("Segoe UI", 12, "bold"),
                text_color=COLORS["text"],
                wraplength=500,
                anchor="w",
            ).pack(anchor="w", padx=12, pady=(8, 2))

            CTkLabel(
                card_frame,
                text=f"{stars} · {mem.read_date[:10]} · {mem.source}",
                font=("Segoe UI", 10),
                text_color=COLORS["text_dim"],
            ).pack(anchor="w", padx=12, pady=(0, 8))

        self.status_var.set(f"History: {len(recent)} papers")

    def _show_settings(self):
        """Show settings dialog."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Settings")
        dialog.geometry("400x300")
        dialog.transient(self)
        dialog.grab_set()

        CTkLabel(
            dialog,
            text="ResearchPulse Settings",
            font=("Segoe UI", 16, "bold"),
        ).pack(pady=(20, 16))

        CTkLabel(
            dialog,
            text=f"Data directory: {ROOT}",
            font=("Segoe UI", 11),
            text_color=COLORS["text_dim"],
            wraplength=350,
        ).pack(pady=(0, 8))

        CTkLabel(
            dialog,
            text=f"Papers in memory: {len(self.memory.papers)}",
            font=("Segoe UI", 11),
        ).pack(pady=(0, 4))

        CTkLabel(
            dialog,
            text=f"Insights generated: {len(self.memory.insights)}",
            font=("Segoe UI", 11),
        ).pack(pady=(0, 16))

        CTkButton(
            dialog,
            text="Close",
            fg_color=COLORS["accent"],
            command=dialog.destroy,
        ).pack(pady=(0, 20))


# ── Entry Point ──────────────────────────────────────────────────────────

def run_desktop():
    """Launch the ResearchPulse desktop application."""
    app = ResearchPulseApp()
    app.mainloop()
