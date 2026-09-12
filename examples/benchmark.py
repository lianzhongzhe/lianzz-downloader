"""Comparison benchmark: single-thread vs multi-thread segmented download.

Downloads the same file twice and compares wall time.
Default test URLs: Hetzner 100MB file + Speedtest 10MB file.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time

# Make the script runnable from the examples/ subdirectory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastdownloader.core import DownloadConfig, SegmentedDownloader

# A few common Range-test URLs
TEST_URLS = {
    "hetzner_100mb":  "http://speed.hetzner.de/100MB.bin",
    "hetzner_1gb":    "http://speed.hetzner.de/1GB.bin",
    "ovh_100mb":      "https://proof.ovh.net/files/100Mb.dat",
    "tele2_10mb":     "http://speedtest.tele2.net/10MB.zip",
    "node_28mb":      "https://nodejs.org/dist/v20.10.0/node-v20.10.0-win-x64.zip",
    "python_11mb":    "https://www.python.org/ftp/python/3.12.0/python-3.12.0-embed-amd64.zip",
}


def run_one(label: str, url: str, threads: int) -> float:
    tmp_dir = tempfile.mkdtemp(prefix=f"dl_test_{label}_")
    out = os.path.join(tmp_dir, "file.bin")

    def on_progress(_p):
        # silent
        pass

    cfg = DownloadConfig(url=url, output_path=out, threads=threads)
    dl = SegmentedDownloader(cfg, on_progress)

    print(f"[{label}] threads={threads}  url={url}")
    t0 = time.perf_counter()
    try:
        path = dl.run()
        elapsed = time.perf_counter() - t0
        size = os.path.getsize(path)
        speed_mb = size / elapsed / 1024 / 1024
        print(f"[{label}] done  {size/1024/1024:.1f} MB  elapsed {elapsed:.2f}s  "
              f"avg {speed_mb:.2f} MB/s  -> {path}")
        return elapsed
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def main():
    url_key = sys.argv[1] if len(sys.argv) > 1 else "hetzner_100mb"
    if url_key not in TEST_URLS:
        print(f"available URLs: {list(TEST_URLS)}")
        return 1
    url = TEST_URLS[url_key]

    print("=" * 60)
    print(f"Benchmark: {url_key} = {url}")
    print("=" * 60)

    t1 = run_one("1-thread", url, threads=1)
    t8 = run_one("8-thread", url, threads=8)

    speedup = t1 / t8 if t8 > 0 else 0
    print("=" * 60)
    print(f"1-thread: {t1:.2f}s    8-thread: {t8:.2f}s    speedup: {speedup:.2f}x")
    return 0


if __name__ == "__main__":
    sys.exit(main())