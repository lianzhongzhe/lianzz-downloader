"""Command-line entry:

    fastdownloader URL [-o PATH] [-n 8] [--speed 1024] [--no-resume]

Or via Python module:

    python -m fastdownloader URL [-o PATH] [-n 8]

Examples:

    fastdownloader https://example.com/file.zip -n 8
    python -m fastdownloader https://example.com/file.zip -n 8 -o my.zip
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from urllib.parse import urlparse

from .core import (
    DownloadCancelled,
    DownloadConfig,
    DownloadError,
    ProgressInfo,
    SegmentedDownloader,
    _human_size,
)


def _build_progress_bar(p: ProgressInfo, width: int = 40) -> str:
    if p.total <= 0:
        filled = 0
    else:
        filled = int(width * p.downloaded / p.total)
        filled = max(0, min(width, filled))
    bar = "█" * filled + "·" * (width - filled)
    return f"[{bar}] {p.percent:5.1f}%"


def _progress_printer(p: ProgressInfo) -> None:
    bar = _build_progress_bar(p)
    total = _human_size(p.total) if p.total else "?"
    line = (
        f"\r{bar}  "
        f"{_human_size(p.downloaded)}/{total}  "
        f"{p.format_speed()}  "
        f"ETA {p.format_eta()}  "
        f"threads {p.active_threads}  "
        f"{p.status:<6}"
    )
    sys.stdout.write(line)
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fastdownloader",
        description="Multi-threaded segmented file downloader powered by HTTP Range.",
    )
    parser.add_argument("url", help="URL to download")
    parser.add_argument("-o", "--output", help="Output path; defaults to filename derived from URL")
    parser.add_argument("-n", "--threads", type=int, default=8, help="Number of threads (1-32), default 8")
    parser.add_argument(
        "--chunk", type=int, default=64 * 1024,
        help="Read chunk size in bytes, default 64 KB",
    )
    parser.add_argument(
        "--speed", type=int, default=0,
        help="Global speed limit in bytes/s, 0 = unlimited",
    )
    parser.add_argument(
        "--retries", type=int, default=5,
        help="Maximum retries per segment, default 5",
    )
    parser.add_argument(
        "--no-resume", action="store_true",
        help="Disable resume support",
    )
    parser.add_argument(
        "--header", action="append", default=[],
        help="Extra request header in 'Key: Value' form; may be repeated",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging",
    )

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    headers: dict[str, str] = {}
    for h in args.header:
        if ":" in h:
            k, v = h.split(":", 1)
            headers[k.strip()] = v.strip()

    output = args.output
    if not output:
        # The downloader will fill in the real filename from the response;
        # this is just a placeholder so the temp file has a sensible name.
        path = urlparse(args.url).path
        output = os.path.basename(path) or "download.bin"

    cfg = DownloadConfig(
        url=args.url,
        output_path=output,
        threads=max(1, min(args.threads, 32)),
        chunk_size=max(4 * 1024, args.chunk),
        speed_limit=max(0, args.speed),
        max_retries=max(0, args.retries),
        resume=not args.no_resume,
        headers=headers,
    )

    dl = SegmentedDownloader(cfg, _progress_printer)
    try:
        path = dl.run()
    except DownloadCancelled:
        print("\n[cancelled] download aborted")
        return 130
    except DownloadError as e:
        print(f"\n[failed] {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        dl.cancel()
        print("\n[interrupted] cancelled by user")
        return 130
    else:
        print(f"\n[done] saved to {path}")
        return 0


if __name__ == "__main__":
    sys.exit(main())