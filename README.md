# ResearchPulse

**Your daily pulse on research.** A free, open-source agent that fetches new papers in your fields and opens them in your browser.

## Install

```bash
pip install research-pulse
```

Or with pipx (Mac/Linux):

```bash
pipx install research-pulse
```

## Desktop App

Launch the GUI application:

```bash
# Install with desktop support
pip install research-pulse[desktop]

# Launch the app
research-pulse desktop
```

Features:
- Dark mode interface
- Browse papers with ranking and venue info
- Search papers across multiple sources
- Manage topics with checkboxes
- Rate papers and track reading history
- Open papers in browser with one click

## CLI Usage

```bash
research-pulse                          # Today's papers
research-pulse search "query"           # Search papers
research-pulse search "attention" --venue neurips,icml --core A --year 2024
research-pulse conferences              # List CORE-ranked venues
research-pulse conferences --core "A*"  # Top-tier only
research-pulse topics                   # View/change topics
research-pulse topics ai-ml nlp cv      # Set topics directly
research-pulse add-topic --id my-field --label "My Field" --keywords "kw1,kw2"
research-pulse chat                     # Interactive agent
research-pulse help                     # All commands
```

## What it does

- Fetches papers from **arXiv, OpenAlex, Europe PMC, bioRxiv, Crossref, Semantic Scholar**
- **Auto-detects topics** from your Zotero library (if installed)
- Opens a clean HTML digest in your browser
- Tracks your reading history and ratings
- 31 built-in research domains (AI, NLP, medicine, physics, etc.)
- Follow any field: `research-pulse follow "quantum computing"`
- **Conference metadata**: venue name, year, and CORE rank (A*, A, B, C) on each paper
- **Filter by conference**: `--venue neurips`, `--core A`, `--year 2024` on search

## Conference filtering

Each paper shows **venue**, **year**, and **CORE rank** when available (from OpenAlex, Crossref, or arXiv comments).

```bash
research-pulse conferences                    # all ranked venues in catalog
research-pulse search "diffusion models" --venue neurips,icml
research-pulse search "LLM reasoning" --core A --year 2024
```

CORE ranks come from a bundled offline catalog (`config/core_venues.yaml`). Edit or extend it for your field — no CORE API key needed.

## Zotero Integration

If you have [Zotero](https://www.zotero.org/) installed, topics are auto-detected from your library on **first run only**. Manual topic choices are kept after that.

```bash
research-pulse zotero              # See detected topics
research-pulse zotero --apply      # Re-sync digest topics from Zotero
```

## Topics

Set topics with **IDs** (the short names in parentheses), not display labels:

```bash
research-pulse topics              # Interactive picker
research-pulse topics ai-ml nlp cv # Set directly
research-pulse topics show         # See current topics + config file path
```

Run `research-pulse topics` with no args to see the full list and current selection.

### One config file — avoid mixing installs

Topic choices are stored in `data/local.json`. **Where that file lives depends on how you run ResearchPulse:**

| How you run it | Config location |
|----------------|-----------------|
| `research-pulse` (pip/pipx) | `%USERPROFILE%\.research-pulse\data\local.json` (Windows) or `~/.research-pulse/data/local.json` |
| `python -m research_agent` from a git clone | `<repo>/data/local.json` |

If you set topics one way but run the digest another, you'll see the wrong topics (often defaults `ai-ml`, `nlp`).

**Fix:** use the same entry point for both, or reinstall from your clone:

```bash
pip install -e "D:\Research Agent"   # editable install — one path for everything
research-pulse topics show           # confirm config file path
```

Set `RESEARCHPULSE_HOME` to force a single config directory anywhere.

## Interactive Agent

```bash
research-pulse chat
```

Inside the agent:
- `search <query>` — search papers
- `summarize <n>` — summarize paper
- `compare <n1> <n2>` — compare papers
- `rate <n> <1-5>` — rate a paper
- `ask <question>` — ask AI about papers
- `insights` — get research insights
- `memory` — view reading history

## Add Custom Topics

```bash
research-pulse add-topic --id data-science --label "Data Science" --keywords "data,analytics,visualization" --arxiv "stat.ML,cs.DB"
```

## License

MIT — see [LICENSE](LICENSE).
