"""Comparison benchmark against a local HTTP server."""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastdownloader.core import DownloadConfig, SegmentedDownloader


def sha1(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run(label: str, url: str, threads: int) -> tuple[float, str, int]:
    tmp_dir = tempfile.mkdtemp(prefix=f"dl_test_{label}_")
    out = os.path.join(tmp_dir, "file.bin")

    cfg = DownloadConfig(url=url, output_path=out, threads=threads)
    dl = SegmentedDownloader(cfg, lambda _p: None)

    print(f"[{label}] threads={threads}")
    t0 = time.perf_counter()
    path = dl.run()
    elapsed = time.perf_counter() - t0
    size = os.path.getsize(path)
    digest = sha1(path)
    shutil.rmtree(tmp_dir, ignore_errors=True)
    print(f"[{label}] done  {size/1024/1024:.1f} MB  elapsed {elapsed:.2f}s  "
          f"avg {size/elapsed/1024/1024:.2f} MB/s  sha1={digest[:12]}")
    return elapsed, digest, size


def main():
    url = "http://127.0.0.1:18080/file.bin"
    print("=" * 70)
    print(f"Benchmark: {url}  (server caps each connection at 2 MB/s)")
    print("=" * 70)

    t1, h1, _ = run("1-thread", url, threads=1)
    t8, h8, _ = run("8-thread", url, threads=8)

    if h1 == h8:
        print(f"\nSHA1 match: {h1[:12]}  ✓ content identical")
    else:
        print(f"\nSHA1 mismatch!\n  1-thread: {h1}\n  8-thread: {h8}")
        return 1

    speedup = t1 / t8 if t8 > 0 else 0
    print("=" * 70)
    print(f"1-thread: {t1:.2f}s    8-thread: {t8:.2f}s    speedup: {speedup:.2f}x")
    return 0


if __name__ == "__main__":
    sys.exit(main())