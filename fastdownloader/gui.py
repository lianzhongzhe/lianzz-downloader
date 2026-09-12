"""Tkinter GUI.

    fastdownloader-gui
    python -m fastdownloader.gui
"""

from __future__ import annotations

import os
import sys
import threading
from urllib.parse import urlparse

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    _TK_AVAILABLE = True
except ImportError:                                # tkinter not in this Python build
    _TK_AVAILABLE = False
    tk = None                                      # type: ignore
    filedialog = None                              # type: ignore
    messagebox = None                              # type: ignore
    ttk = None                                     # type: ignore

try:
    from .core import (
        DownloadCancelled,
        DownloadConfig,
        DownloadError,
        ProgressInfo,
        SegmentedDownloader,
        _human_size,
    )
except ImportError:                                # fallback when run as a plain script
    from core import (                              # type: ignore
        DownloadCancelled,
        DownloadConfig,
        DownloadError,
        ProgressInfo,
        SegmentedDownloader,
        _human_size,
    )


class DownloaderApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Segmented Downloader")
        self.root.geometry("720x380")
        self.root.minsize(620, 340)
        self.root.configure(bg="#fafafa")

        self.dl: SegmentedDownloader | None = None
        self.worker: threading.Thread | None = None
        self.last_info: ProgressInfo | None = None

        self._build_ui()

    # ---------------- UI ----------------

    def _build_ui(self) -> None:
        PAD = {"padx": 10, "pady": 6}

        # URL
        ttk.Label(self.root, text="URL").grid(row=0, column=0, sticky="w", **PAD)
        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(self.root, textvariable=self.url_var)
        self.url_entry.grid(row=0, column=1, columnspan=3, sticky="we", **PAD)

        # Output path
        ttk.Label(self.root, text="Save to").grid(row=1, column=0, sticky="w", **PAD)
        self.output_var = tk.StringVar()
        self.output_entry = ttk.Entry(self.root, textvariable=self.output_var)
        self.output_entry.grid(row=1, column=1, columnspan=2, sticky="we", **PAD)
        ttk.Button(self.root, text="Browse…", command=self._choose_path).grid(
            row=1, column=3, sticky="we", **PAD
        )

        # Threads + speed limit
        ttk.Label(self.root, text="Threads").grid(row=2, column=0, sticky="w", **PAD)
        self.threads_var = tk.IntVar(value=8)
        ttk.Spinbox(self.root, from_=1, to=32, width=6, textvariable=self.threads_var).grid(
            row=2, column=1, sticky="w", **PAD
        )

        ttk.Label(self.root, text="Speed limit (KB/s)").grid(row=2, column=2, sticky="e", **PAD)
        self.speed_var = tk.IntVar(value=0)
        ttk.Spinbox(self.root, from_=0, to=1024 * 1024, width=8, textvariable=self.speed_var).grid(
            row=2, column=3, sticky="w", **PAD
        )

        # Progress bar
        self.progress = ttk.Progressbar(self.root, mode="determinate", maximum=1000)
        self.progress.grid(row=3, column=0, columnspan=4, sticky="we", **PAD)

        # Status line
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(self.root, textvariable=self.status_var, foreground="#555").grid(
            row=4, column=0, columnspan=4, sticky="w", **PAD
        )

        # Buttons
        btn_frame = ttk.Frame(self.root)
        btn_frame.grid(row=5, column=0, columnspan=4, sticky="we", **PAD)
        self.start_btn = ttk.Button(btn_frame, text="Start", command=self._on_start)
        self.start_btn.pack(side="left", padx=5)
        self.pause_btn = ttk.Button(btn_frame, text="Pause", command=self._on_pause, state="disabled")
        self.pause_btn.pack(side="left", padx=5)
        self.cancel_btn = ttk.Button(btn_frame, text="Cancel", command=self._on_cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=5)

        self.root.columnconfigure(1, weight=1)
        self.root.columnconfigure(2, weight=1)

    def _choose_path(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Choose save location",
            initialfile=self.output_var.get() or "download.bin",
            defaultextension=".bin",
        )
        if path:
            self.output_var.set(path)

    # ---------------- Behavior ----------------

    def _on_start(self) -> None:
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Missing URL", "Please enter a URL to download.")
            return
        output = self.output_var.get().strip()
        if not output:
            output = os.path.basename(urlparse(url).path) or "download.bin"
            self.output_var.set(output)

        cfg = DownloadConfig(
            url=url,
            output_path=output,
            threads=int(self.threads_var.get()),
            speed_limit=int(self.speed_var.get()) * 1024,
        )
        self.dl = SegmentedDownloader(cfg, self._on_progress)

        self.start_btn.config(state="disabled")
        self.pause_btn.config(state="normal", text="Pause")
        self.cancel_btn.config(state="normal")
        self.status_var.set("Starting download…")

        self.worker = threading.Thread(target=self._run_download, daemon=True)
        self.worker.start()

    def _run_download(self) -> None:
        assert self.dl is not None
        try:
            self.dl.run()
            self.root.after(0, lambda: self._on_done("Completed", success=True))
        except DownloadCancelled:
            self.root.after(0, lambda: self._on_done("Cancelled", success=False))
        except (DownloadError, Exception) as e:                       # noqa: BLE001
            self.root.after(0, lambda: self._on_done(f"Failed: {e}", success=False))

    def _on_done(self, msg: str, success: bool) -> None:
        self.status_var.set(msg)
        self.start_btn.config(state="normal")
        self.pause_btn.config(state="disabled")
        self.cancel_btn.config(state="disabled")
        if success:
            messagebox.showinfo("Done", f"Download complete\n{self.output_var.get()}")

    def _on_pause(self) -> None:
        if not self.dl:
            return
        if self.dl.is_paused():
            self.dl.resume()
            self.pause_btn.config(text="Pause")
            self.status_var.set("Resumed")
        else:
            self.dl.pause()
            self.pause_btn.config(text="Resume")
            self.status_var.set("Paused")

    def _on_cancel(self) -> None:
        if not self.dl:
            return
        self.dl.cancel()
        self.status_var.set("Cancelling…")

    # ---------------- Progress callback (in worker thread) ----------------

    def _on_progress(self, p: ProgressInfo) -> None:
        self.last_info = p
        # Hop back to the UI thread to update widgets
        self.root.after(0, self._apply_progress, p)

    def _apply_progress(self, p: ProgressInfo) -> None:
        if p.total > 0:
            self.progress["value"] = p.percent * 10
        else:
            self.progress["value"] = 0
        total_str = _human_size(p.total) if p.total else "?"
        self.status_var.set(
            f"{p.filename}  {p.percent:5.1f}%  "
            f"{_human_size(p.downloaded)}/{total_str}  "
            f"{p.format_speed()}  ETA {p.format_eta()}  "
            f"threads {p.active_threads}  {p.status}"
        )


def main() -> None:
    if not _TK_AVAILABLE:
        print(
            "Tkinter is not available in this Python build.\n"
            "On Linux you may need to install the `python3-tk` package; "
            "on Windows / macOS the official python.org installers ship it.",
            file=sys.stderr,
        )
        sys.exit(1)
    root = tk.Tk()                                # type: ignore[misc]
    # Use the closest native-looking ttk theme for the host OS
    try:
        style = ttk.Style()                       # type: ignore[misc]
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "aqua" in style.theme_names():
            style.theme_use("aqua")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass
    DownloaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()