"""Entry point for standalone executable."""

import sys
import os

# Add the parent directory to path when running as module
if __name__ == "__main__":
    # For PyInstaller - add the bundled directory to path
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        sys.path.insert(0, os.path.dirname(sys.executable))
    
    from research_agent.cli import main
    raise SystemExit(main())
