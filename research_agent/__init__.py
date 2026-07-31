"""ResearchPulse: a free, open-source daily research-paper newsletter agent."""

import sys as _sys

__version__ = "0.5.8"


def _force_utf8_console() -> None:
    """Make stdout/stderr tolerate Unicode on legacy Windows code pages.

    Paper titles and abstracts routinely contain characters like \u03c0, \u00e9,
    or \u2013 that crash the default Windows cp1252 console. Reconfiguring to
    UTF-8 (with replacement) keeps the agent usable everywhere.
    """
    for stream in (_sys.stdout, _sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            # Older Python or a non-reconfigurable stream (e.g. piped): ignore.
            pass


_force_utf8_console()
