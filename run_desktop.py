"""Entry point for the ResearchPulse desktop application."""

import sys
import os

# Add the parent directory to sys.path if running from source
if __name__ == "__main__":
    # Try to import and run the desktop app
    try:
        from research_agent.desktop import run_desktop
        run_desktop()
    except ImportError as e:
        print(f"Error: {e}")
        print("\nPlease install required dependencies:")
        print("  pip install research-pulse[desktop]")
        input("\nPress Enter to exit...")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        input("\nPress Enter to exit...")
        sys.exit(1)
