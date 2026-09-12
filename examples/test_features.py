"""Feature tests: pause/resume, speed limit, thread count."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastdownloader.core import DownloadConfig, ProgressInfo, SegmentedDownloader


URL = "http://127.0.0.1:18080/file.bin"


def banner(name: str):
    print("\n" + "=" * 60)
    print(name)
    print("=" * 60)


def test_pause_resume():
    banner("Test 1: Pause / Resume")
    tmp = tempfile.mkdtemp(prefix="dl_pause_")
    out = os.path.join(tmp, "file.bin")

    state = {"last": None}
    cv = threading.Condition()

    def cb(p: ProgressInfo):
        with cv:
            state["last"] = p
            cv.notify_all()

    cfg = DownloadConfig(url=URL, output_path=out, threads=8)
    dl = SegmentedDownloader(cfg, cb)

    def runner():
        try:
            dl.run()
        except Exception as e:
            print("runner err:", e)

    th = threading.Thread(target=runner, daemon=True)
    th.start()

    # Wait until progress passes ~15%
    with cv:
        cv.wait_for(lambda: state["last"] is not None, 30)
        cv.wait_for(
            lambda: state["last"] is not None
                    and state["last"].percent > 15
                    and state["last"].total > 0,
            60,
        )
        p = state["last"]
        print(f"  before pause: {p.percent:.1f}%  downloaded {_size(p.downloaded)}")

    print("  >> pause")
    dl.pause()
    time.sleep(2)
    p1 = state["last"]
    print(f"  2s after pause: {p1.percent:.1f}%  downloaded {_size(p1.downloaded)}")

    print("  >> resume")
    dl.resume()
    with cv:
        cv.wait_for(lambda: state["last"].percent > p1.percent + 30, 60)

    th.join(timeout=120)
    final = state["last"]
    print(f"  final: {final.percent:.1f}%  status={final.status}")

    ok = os.path.exists(out) and os.path.getsize(out) == 83886080
    print(f"  result: {'✓ file size correct' if ok else '✗ file size wrong'}")
    return ok


def test_speed_limit():
    banner("Test 2: Speed limit 1 MB/s (global token bucket)")
    tmp = tempfile.mkdtemp(prefix="dl_speed_")
    out = os.path.join(tmp, "file.bin")

    cfg = DownloadConfig(url=URL, output_path=out, threads=4, speed_limit=1024 * 1024)
    dl = SegmentedDownloader(cfg, lambda _p: None)

    t0 = time.perf_counter()
    dl.run()
    elapsed = time.perf_counter() - t0
    speed = 83886080 / elapsed / 1024 / 1024

    # speed_limit = global ceiling shared by all threads; independent of thread count
    print(f"  elapsed {elapsed:.2f}s  actual avg {speed:.2f} MB/s")
    print(f"  (limit strategy: global token bucket = 1 MB/s, thread-independent)")
    ok = 0.95 <= speed <= 1.15
    print(f"  result: {'✓ speed limit enforced' if ok else '✗ speed limit wrong'}")
    return ok


def test_many_threads():
    banner("Test 3: 16 threads")
    tmp = tempfile.mkdtemp(prefix="dl_16t_")
    out = os.path.join(tmp, "file.bin")
    cfg = DownloadConfig(url=URL, output_path=out, threads=16)
    dl = SegmentedDownloader(cfg, lambda _p: None)
    t0 = time.perf_counter()
    dl.run()
    elapsed = time.perf_counter() - t0
    speed = 83886080 / elapsed / 1024 / 1024
    print(f"  elapsed {elapsed:.2f}s  avg {speed:.2f} MB/s")
    print(f"  result: {'✓ 16 threads ok' if speed > 5 else '✗ abnormal'}")
    return speed > 5


def _size(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n/1024/1024:.2f} MB"
    if n >= 1024:
        return f"{n/1024:.2f} KB"
    return f"{n} B"


def main() -> int:
    results = []
    results.append(("pause/resume", test_pause_resume()))
    results.append(("speed limit",   test_speed_limit()))
    results.append(("16 threads",    test_many_threads()))

    print("\n" + "=" * 60)
    print("Summary:")
    for name, ok in results:
        print(f"  {'✓' if ok else '✗'} {name}")
    return 0 if all(ok for _, ok in results) else 1


if __name__ == "__main__":
    sys.exit(main())