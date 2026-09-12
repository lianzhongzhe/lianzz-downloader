"""Segmented file downloader."""

from .core import (
    DownloadConfig,
    DownloadError,
    ProgressInfo,
    SegmentState,
    SegmentedDownloader,
    _human_size,
    _human_speed,
)

__all__ = [
    "DownloadConfig",
    "DownloadError",
    "ProgressInfo",
    "SegmentState",
    "SegmentedDownloader",
    "_human_size",
    "_human_speed",
]

__version__ = "1.1.0"