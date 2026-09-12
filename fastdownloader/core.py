"""SegmentedDownloader — a multi-threaded file downloader powered by HTTP Range.

Usage example:

    from fastdownloader.core import SegmentedDownloader, DownloadConfig

    def on_progress(p):
        print(f"{p.percent:5.1f}%  {p.downloaded}/{p.total}  "
              f"{p.format_speed()}  ETA {p.format_eta()}")

    cfg = DownloadConfig(
        url="https://example.com/big.zip",
        output_path="big.zip",
        threads=8,
    )
    SegmentedDownloader(cfg, on_progress).run()
"""

from __future__ import annotations

import logging
import os
import threading
import time
import urllib.parse
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Optional

import requests

log = logging.getLogger("fastdownloader.core")


# -------------------------- Data structures --------------------------

@dataclass
class DownloadConfig:
    """Full configuration for a download task."""

    url: str
    output_path: str
    threads: int = 8
    chunk_size: int = 64 * 1024                 # 64 KB
    max_retries: int = 5
    connect_timeout: float = 15.0
    read_timeout: float = 30.0
    speed_limit: int = 0                        # bytes per second; 0 = unlimited
    user_agent: str = "SegmentedDownloader/1.0"
    headers: dict = field(default_factory=dict)
    resume: bool = True
    min_segment_size: int = 1 * 1024 * 1024     # minimum size of one segment: 1 MB


@dataclass
class SegmentState:
    """Runtime state of a single segment."""

    index: int
    start: int                                  # byte offset start (inclusive)
    end: int                                    # byte offset end (inclusive)
    downloaded: int = 0                         # bytes downloaded so far within the segment (for resume)
    status: str = "pending"                     # pending / downloading / done / failed
    retries: int = 0


@dataclass
class ProgressInfo:
    """Real-time snapshot reported to the GUI / CLI."""

    downloaded: int = 0
    total: int = 0
    speed: float = 0.0                          # bytes per second
    elapsed: float = 0.0
    eta: float = 0.0
    active_threads: int = 0
    percent: float = 0.0
    filename: str = ""
    status: str = ""

    def format_speed(self) -> str:
        return _human_speed(self.speed)

    def format_eta(self) -> str:
        if self.eta <= 0 or not self.total:
            return "--:--"
        s = int(self.eta)
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        if h:
            return f"{h:d}:{m:02d}:{sec:02d}"
        return f"{m:02d}:{sec:02d}"


# -------------------------- Exceptions --------------------------

class DownloadCancelled(Exception):
    """User cancellation or upper-layer interruption."""


class DownloadError(Exception):
    """Unrecoverable download error."""


# -------------------------- Utility functions --------------------------

def _human_speed(bps: float) -> str:
    units = ["B/s", "KB/s", "MB/s", "GB/s"]
    i = 0
    val = float(bps)
    while val >= 1024 and i < len(units) - 1:
        val /= 1024
        i += 1
    return f"{val:6.2f} {units[i]}"


def _human_size(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    val = float(n)
    while val >= 1024 and i < len(units) - 1:
        val /= 1024
        i += 1
    return f"{val:.2f} {units[i]}"


# -------------------------- Main class --------------------------

class SegmentedDownloader:
    """Download a large file in parallel via HTTP Range requests."""

    def __init__(
        self,
        config: DownloadConfig,
        progress_cb: Optional[Callable[[ProgressInfo], None]] = None,
    ):
        self.cfg = config
        self.progress_cb = progress_cb

        # Control events
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._cancel = threading.Event()

        # Global progress (thread-safe)
        self._lock = threading.Lock()
        self._downloaded_total = 0
        self._active = 0
        self._total_size = 0
        self._supports_range = False
        self._filename = ""

        # Speed sampling
        self._last_sample_time = 0.0
        self._last_sample_downloaded = 0
        self._instant_speed = 0.0

        # Segments
        self._segments: list[SegmentState] = []
        self._start_time = 0.0

    # ---------------- Public control ----------------

    def pause(self) -> None:
        self._pause_event.clear()

    def resume(self) -> None:
        self._pause_event.set()

    def cancel(self) -> None:
        self._cancel.set()
        self._pause_event.set()               # wake up any blocked worker

    def is_paused(self) -> bool:
        return not self._pause_event.is_set()

    # ---------------- Main flow ----------------

    def run(self) -> str:
        """Synchronously execute the download and return the final file path."""
        self._start_time = time.time()
        out_dir = os.path.dirname(os.path.abspath(self.cfg.output_path))
        os.makedirs(out_dir or ".", exist_ok=True)

        # 1) Probe
        total, supports_range, filename = self._probe()
        self._total_size = total
        self._supports_range = supports_range
        self._filename = filename or self._guess_filename()

        log.info(
            "probe done url=%s size=%s range=%s filename=%s",
            self.cfg.url, _human_size(total) if total else "?",
            supports_range, self._filename,
        )

        # 2) Fall back to single-thread streaming if Range is unavailable
        if not supports_range or total <= 0:
            log.warning("server does not support Range or size is unknown; "
                        "falling back to single-thread streaming download")
            return self._single_thread_download()

        # 3) Pre-allocate the temp file
        tmp_path = self.cfg.output_path + ".part"
        self._prepare_tmp_file(tmp_path, total)

        # 4) Split into segments
        self._segments = self._split_into_segments(total, self.cfg.threads)
        seg_size = self._segments[0].end - self._segments[0].start + 1
        log.info("segments=%d  segment_size≈%s",
                 len(self._segments), _human_size(seg_size))

        # 5) Optional rate limiter
        limiter = _TokenBucket(self.cfg.speed_limit) if self.cfg.speed_limit > 0 else None

        # 6) Multi-thread download
        with ThreadPoolExecutor(max_workers=len(self._segments)) as pool:
            futures: list[Future] = []
            for seg in self._segments:
                if seg.downloaded >= (seg.end - seg.start + 1):
                    seg.status = "done"
                    continue
                futures.append(pool.submit(self._download_segment, tmp_path, seg, limiter))

            try:
                while True:
                    done = sum(1 for s in self._segments if s.status == "done")
                    if done == len(self._segments):
                        break
                    if self._cancel.is_set():
                        raise DownloadCancelled("cancelled by user")
                    self._report_progress()
                    time.sleep(0.25)
            except DownloadCancelled:
                # Python 3.7/3.8 do not support cancel_futures= on
                # ThreadPoolExecutor.shutdown(); cancel not-yet-started
                # futures manually. The cancel event checked inside
                # _download_segment stops the in-flight workers.
                for fut in futures:
                    if not fut.done():
                        fut.cancel()
                pool.shutdown(wait=False)
                raise
            finally:
                self._report_progress(final=True)

            for f in futures:
                exc = f.exception()
                if exc and not isinstance(exc, DownloadCancelled):
                    raise exc

        # 7) Commit to disk
        if os.path.exists(self.cfg.output_path):
            os.remove(self.cfg.output_path)
        os.replace(tmp_path, self.cfg.output_path)
        log.info("download complete: %s", self.cfg.output_path)
        return self.cfg.output_path

    # ---------------- Probe ----------------

    def _probe(self):
        """HEAD request to obtain size, Range support, and suggested filename."""
        headers = dict(self.cfg.headers)
        headers.setdefault("User-Agent", self.cfg.user_agent)
        try:
            r = requests.head(
                self.cfg.url,
                headers=headers,
                allow_redirects=True,
                timeout=self.cfg.connect_timeout,
            )
            r.raise_for_status()
            total = int(r.headers.get("Content-Length") or 0)
            supports = r.headers.get("Accept-Ranges", "").lower() == "bytes"
            filename = self._filename_from_cd(r.headers.get("Content-Disposition")) \
                       or self._guess_filename()
            return total, supports, filename
        except requests.RequestException as e:
            log.debug("HEAD failed, falling back to Range GET probe: %s", e)
            return self._probe_with_get()

    def _probe_with_get(self):
        """Probe via Range: bytes=0-0; wastes 1 byte as a side effect."""
        headers = dict(self.cfg.headers)
        headers["Range"] = "bytes=0-0"
        headers.setdefault("User-Agent", self.cfg.user_agent)
        r = requests.get(
            self.cfg.url,
            headers=headers,
            stream=True,
            timeout=self.cfg.connect_timeout,
        )
        if r.status_code == 206:
            cr = r.headers.get("Content-Range", "")
            try:
                total = int(cr.split("/")[-1])
            except (ValueError, IndexError):
                total = 0
            r.close()
            return total, True, self._guess_filename()
        if r.status_code == 200:
            total = int(r.headers.get("Content-Length") or 0)
            r.close()
            return total, False, self._guess_filename()
        r.close()
        raise DownloadError(f"probe failed: HTTP {r.status_code}")

    def _filename_from_cd(self, cd: Optional[str]) -> str:
        if not cd:
            return ""
        import re
        m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)\"?", cd, re.IGNORECASE)
        if m:
            try:
                from urllib.parse import unquote
                return unquote(m.group(1))
            except Exception:
                return m.group(1)
        return ""

    def _guess_filename(self) -> str:
        path = urllib.parse.urlparse(self.cfg.url).path
        name = os.path.basename(path)
        return name or "download.bin"

    # ---------------- File preparation ----------------

    @staticmethod
    def _prepare_tmp_file(path: str, total: int) -> None:
        """Pre-allocate disk space (works on Windows / Linux / macOS)."""
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        try:
            try:
                os.posix_fallocate(fd, 0, total)
            except (AttributeError, OSError):
                # Windows: seek to end-1 and write one byte
                os.lseek(fd, total - 1, os.SEEK_SET)
                os.write(fd, b"\x00")
        finally:
            os.close(fd)

    # ---------------- Segmentation ----------------

    def _split_into_segments(self, total: int, threads: int) -> list[SegmentState]:
        threads = max(1, min(threads, 32))
        per = total // threads
        if per < self.cfg.min_segment_size and total >= self.cfg.min_segment_size:
            threads = max(1, total // self.cfg.min_segment_size)
            per = total // threads
        segs: list[SegmentState] = []
        cur = 0
        for i in range(threads):
            start = cur
            end = (start + per - 1) if i < threads - 1 else (total - 1)
            segs.append(SegmentState(index=i, start=start, end=end))
            cur = end + 1
        return segs

    # ---------------- Single-thread fallback ----------------

    def _single_thread_download(self) -> str:
        headers = dict(self.cfg.headers)
        headers.setdefault("User-Agent", self.cfg.user_agent)
        out = self.cfg.output_path
        with requests.get(
            self.cfg.url,
            headers=headers,
            stream=True,
            timeout=(self.cfg.connect_timeout, self.cfg.read_timeout),
        ) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length") or 0)
            self._total_size = total
            self._report_progress()
            with open(out, "wb") as f:
                for chunk in r.iter_content(chunk_size=self.cfg.chunk_size):
                    self._pause_event.wait()
                    if self._cancel.is_set():
                        raise DownloadCancelled("cancelled by user")
                    if chunk:
                        f.write(chunk)
                        with self._lock:
                            self._downloaded_total += len(chunk)
                        self._report_progress()
        self._report_progress(final=True)
        return out

    # ---------------- Segment download ----------------

    def _download_segment(self, tmp_path: str, seg: SegmentState,
                          limiter: Optional["_TokenBucket"]) -> None:
        """Download a single segment and write it to the right offset of tmp_path."""
        seg.status = "downloading"
        with self._lock:
            self._active += 1

        url = self.cfg.url
        headers = dict(self.cfg.headers)
        headers.setdefault("User-Agent", self.cfg.user_agent)

        # Current write offset (resume start point)
        cur = seg.start + seg.downloaded
        if cur > seg.end:
            seg.status = "done"
            with self._lock:
                self._active -= 1
            return

        backoff = 1.0
        try:
            while True:
                if self._cancel.is_set():
                    raise DownloadCancelled("cancelled by user")
                self._pause_event.wait()
                if self._cancel.is_set():
                    raise DownloadCancelled("cancelled by user")

                rng = f"bytes={cur}-{seg.end}"
                headers["Range"] = rng
                try:
                    with requests.get(
                        url,
                        headers=headers,
                        stream=True,
                        timeout=(self.cfg.connect_timeout, self.cfg.read_timeout),
                    ) as r:
                        if r.status_code not in (200, 206):
                            raise DownloadError(f"segment {seg.index} HTTP {r.status_code}")

                        with open(tmp_path, "rb+", buffering=0) as f:
                            f.seek(cur)
                            for chunk in r.iter_content(chunk_size=self.cfg.chunk_size):
                                if not chunk:
                                    continue
                                self._pause_event.wait()
                                if self._cancel.is_set():
                                    raise DownloadCancelled("cancelled by user")

                                n = len(chunk)
                                f.write(chunk)
                                cur += n
                                with self._lock:
                                    self._downloaded_total += n

                                if limiter is not None:
                                    limiter.consume(n)

                    # Segment finished
                    seg.status = "done"
                    return

                except (requests.RequestException, DownloadError, OSError) as e:
                    seg.retries += 1
                    if seg.retries > self.cfg.max_retries:
                        raise DownloadError(
                            f"segment {seg.index} still failing after "
                            f"{self.cfg.max_retries} retries: {e}"
                        )
                    log.warning("segment %d failed on attempt %d: %s, retrying in %.1fs",
                                seg.index, seg.retries, e, backoff)
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 30.0)
        finally:
            with self._lock:
                self._active -= 1

    # ---------------- Progress reporting ----------------

    def _report_progress(self, final: bool = False) -> None:
        if self.progress_cb is None:
            return
        now = time.time()
        elapsed = now - self._start_time if self._start_time else 0.0
        with self._lock:
            downloaded = self._downloaded_total
            active = self._active
        total = self._total_size

        # Instantaneous speed via deltas between samples
        if self._last_sample_time and not final:
            dt = now - self._last_sample_time
            if dt > 0:
                self._instant_speed = (downloaded - self._last_sample_downloaded) / dt

        self._last_sample_time = now
        self._last_sample_downloaded = downloaded

        # Average speed (used when instant is unavailable)
        avg = downloaded / elapsed if elapsed > 0 else 0.0
        speed = self._instant_speed if self._instant_speed > 0 else avg

        eta = (total - downloaded) / speed if (speed > 0 and total > 0) else 0.0
        percent = (downloaded / total * 100.0) if total > 0 else 0.0

        info = ProgressInfo(
            downloaded=downloaded,
            total=total,
            speed=speed,
            elapsed=elapsed,
            eta=eta,
            active_threads=active,
            percent=percent,
            filename=self._filename,
            status="done" if final else ("paused" if self.is_paused() else "downloading"),
        )
        try:
            self.progress_cb(info)
        except Exception as e:                                # noqa: BLE001
            log.debug("progress_cb error: %s", e)


# -------------------------- Rate limiter --------------------------

class _TokenBucket:
    """Simple token-bucket rate limiter."""

    def __init__(self, rate_bps: int):
        self.rate = float(rate_bps)
        self.capacity = float(rate_bps)              # 1-second burst
        self.tokens = self.capacity
        self._lock = threading.Lock()
        self._last = time.monotonic()

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self._last
        self._last = now
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)

    def consume(self, n: int) -> None:
        if self.rate <= 0:
            return
        while True:
            with self._lock:
                self._refill()
                if self.tokens >= n:
                    self.tokens -= n
                    return
                # How long until we have n tokens?
                need = n - self.tokens
                wait = need / self.rate if self.rate > 0 else 0.05
            time.sleep(min(wait, 0.5))