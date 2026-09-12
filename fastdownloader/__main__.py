"""Allow running the CLI via `python -m fastdownloader`."""

from .cli import main

if __name__ == "__main__":
    import sys
    sys.exit(main())