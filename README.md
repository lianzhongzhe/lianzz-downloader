# lianzz-downloader(v1.1.0)

[简体中文(v1.0.0)](/README_zh.md)

> **Package distribution name**: `lianzz-downloader` (used by `pip install`)
> **Python import name**: `fastdownloader` (used by `import fastdownloader`)
> **CLI command**: `fastdownloader` / `fastdownloader-gui`

A fast, multi-threaded, segmented file downloader powered by HTTP Range requests. A file is split into N segments, each fetched concurrently by an independent thread, and written in-place to the same on-disk file — the same approach used by IDM, aria2, and axel.

Benchmark against a local server capped at 2 MB/s per connection, downloading an 80 MB file:

| Threads | Time   | Avg speed   | Speedup |
| ------- | ------ | ----------- | ------- |
| 1       | 41 s   | 1.93 MB/s   | 1.00×   |
| 8       | 5.3 s  | 15.2 MB/s   | **7.85×** |
| 16      | 2.8 s  | 28.3 MB/s   | **14.6×** |

> The 1-thread and 8-thread downloads of the same file produce identical SHA-1 hashes, confirming correct segment assembly.

## Features

- HTTP Range multi-thread segmented downloads
- HEAD probe with automatic Range-GET fallback
- Auto-retry with exponential backoff (up to 5 retries)
- Global token-bucket rate limiter
- Pause / resume / cancel at any time
- Graceful fallback to single-thread streaming when Range is unsupported
- Live progress callback (speed, ETA, active threads)
- Both a CLI and a clean Tkinter GUI
- Temp file pre-allocation to avoid disk fragmentation
- Python 3.7+ supported

## Installation

From PyPI (recommended):

```bash
pip install lianzz-downloader
```

From source:

```bash
git clone https://github.com/lianzhongzhe/lianzz-downloader
cd lianzz-downloader
pip install .
```

The only runtime dependency is `requests`. Requires **Python 3.7 or newer**.

## Usage

### Command line

```bash
# Basic
fastdownloader https://nodejs.org/dist/v20.10.0/node-v20.10.0-win-x64.zip

# Or via module
python -m fastdownloader https://nodejs.org/dist/v20.10.0/node-v20.10.0-win-x64.zip

# With options
fastdownloader <URL> -o my.zip -n 16 --speed 2048 --header "Authorization: Bearer xxx"
```

Options:

| Option             | Description                                  | Default |
| ------------------ | -------------------------------------------- | ------- |
| `url`              | URL to download (positional)                 | —       |
| `-o / --output`    | Output path                                  | derived from URL |
| `-n / --threads`   | Number of threads (1–32)                     | 8       |
| `--chunk`          | Read chunk size in bytes                     | 64 KB   |
| `--speed`          | Global speed limit in bytes/s (0 = unlimited) | 0       |
| `--retries`        | Max retries per segment                      | 5       |
| `--no-resume`      | Disable resume support                       | —       |
| `--header`         | Extra request header `Key: Value` (repeatable) | —     |
| `-v`               | Verbose debug logging                        | —       |

### GUI

```bash
fastdownloader-gui
```

or:

```bash
python -m fastdownloader.gui
```

A minimal Tkinter window: URL, save path, thread count, speed limit, progress bar, pause / cancel.

### Library usage

```python
from fastdownloader.core import SegmentedDownloader, DownloadConfig

def on_progress(p):
    print(f"{p.percent:5.1f}%  {p.format_speed()}  ETA {p.format_eta()}")

cfg = DownloadConfig(
    url="https://example.com/big.zip",
    output_path="big.zip",
    threads=8,
    speed_limit=0,            # 0 = unlimited
    headers={"Referer": "..."},
)

dl = SegmentedDownloader(cfg, on_progress)
# dl.pause() / dl.resume() / dl.cancel()  available any time
path = dl.run()
```

## Running tests

```bash
# 1) Start the local test server (caps each connection at 2 MB/s, serves an 80 MB file)
python examples/test_server.py 18080 2048 80

# 2) In another terminal, run the comparison benchmark
python examples/benchmark_local.py

# 3) Feature tests (pause/resume, speed limit)
python examples/test_features.py
```

## Implementation notes

- **HTTP Range requests**: each segment issues an independent `Range: bytes=A-B` request and writes to the matching offset of a shared `.part` file
- **Thread pool**: `concurrent.futures.ThreadPoolExecutor`, one worker per segment
- **Pre-allocation**: `os.posix_fallocate` reserves the whole file up front so downloads can `seek+write` without disk fragmentation
- **Resume**: each segment tracks its `downloaded` offset; on retry, the request resumes from that offset
- **HEAD probe**: `HEAD` first to get `Content-Length` and `Accept-Ranges`; falls back to a `Range: bytes=0-0` GET when HEAD is blocked
- **Fallback path**: when the server ignores Range (returns 200), the downloader transparently switches to single-thread `iter_content` streaming
- **Rate limiting**: token-bucket algorithm — a 1 MB/s limit shared across 4 threads yields exactly 1 MB/s aggregate
- **Progress reporting**: all segments share a single `_downloaded_total` (Lock-protected); the main thread samples every 250 ms to compute instantaneous speed and ETA
- **Python 3.7 compatibility**: avoids `pool.shutdown(cancel_futures=...)` (3.9+) by cancelling pending futures manually; relies on `from __future__ import annotations` for PEP 585/604 style hints to stay as strings

## Directory layout

```
lianzz-downloader/
├── fastdownloader/        # Python import name
│   ├── __init__.py
│   ├── __main__.py        # python -m fastdownloader entry
│   ├── core.py            # segmented downloader engine
│   ├── cli.py             # argparse CLI
│   └── gui.py             # Tkinter GUI
├── examples/
│   ├── test_server.py     # local test HTTP server
│   ├── benchmark.py       # external-source comparison
│   ├── benchmark_local.py # local-server comparison
│   └── test_features.py   # pause / speed-limit / thread-count tests
├── LICENSE
├── pyproject.toml         # distribution name: lianzz-downloader
└── README.md
```

> Note: the PyPI distribution name (`lianzz-downloader`) is intentionally decoupled from the import name (`fastdownloader`) to avoid a name collision on PyPI.

## License

MIT
