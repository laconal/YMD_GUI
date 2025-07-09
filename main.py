import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import json
import re
import os
from pathlib import Path
from core import (
    init_client,
    prepare_base_path,
    to_downloadable_track,
    download_track,
    DEFAULT_PATH_PATTERN,
    CoreTrackQuality,
    LyricsFormat,
)
from yandex_music import Client, Track, Album, Playlist

client = None  # Global client (in real app, refactor for better structure)

CONFIG_PATH = Path("config.json")

def get_config_path():
    # This works on Windows; for cross-platform apps, also check Linux/macOS
    appdata = os.getenv("APPDATA")  # C:\Users\<user>\AppData\Roaming
    config_dir = Path(appdata) / "YandexMusicDownloader"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.json"

def load_config():
    path = get_config_path()
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_config(data: dict):
    path = get_config_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

class YandexMusicDownloaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Yandex Music Downloader")
        self.client: Client | None = None
        self.track_results: list[Track] = []

        config = load_config()
        self.token_var = tk.StringVar(value=config.get("token", ""))
        self.output_folder = tk.StringVar(value=config.get("output", ""))
        self.path_pattern = tk.StringVar(value=config.get("path_pattern", str(DEFAULT_PATH_PATTERN)))
        self.search_query = tk.StringVar()
        self.downloadTrack = tk.StringVar()
        self.quality = tk.StringVar(value="NORMAL")
        self.lyrics_format = tk.StringVar(value="TEXT")
        self.embed_cover = tk.BooleanVar(value=True)
        self.skip_existing = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Ready")

        self._build_gui()

    def _build_gui(self):
        frame = ttk.Frame(self.root, padding="10")
        frame.grid(sticky="NSEW")

        ttk.Label(frame, text="Token:").grid(row=0, column=0, sticky="W")
        ttk.Entry(frame, textvariable=self.token_var, width=50).grid(row=0, column=1, columnspan=2)

        ttk.Label(frame, text="Output Folder:").grid(row=1, column=0, sticky="W")
        ttk.Entry(frame, textvariable=self.output_folder, width=40).grid(row=1, column=1)
        ttk.Button(frame, text="Browse", command=self._select_output_folder).grid(row=1, column=2)

        ttk.Label(frame, text="Path Pattern:").grid(row=2, column=0, sticky="W")
        ttk.Entry(frame, textvariable=self.path_pattern, width=50).grid(row=2, column=1, columnspan=2)

        ttk.Label(frame, text="URL:").grid(row=3, column=0, sticky="W")
        ttk.Entry(frame, textvariable=self.downloadTrack, width=50).grid(row=3, column=1, columnspan=2)
        ttk.Button(frame, text="Download", command=self._start_download_url).grid(row=3, column=3)

        ttk.Label(frame, text="Search:").grid(row=4, column=0, sticky="W")
        ttk.Entry(frame, textvariable=self.search_query, width=40).grid(row=4, column=1)
        ttk.Button(frame, text="Search", command=self._start_search).grid(row=4, column=2)

        self.track_listbox = tk.Listbox(frame, selectmode="extended", width=80, height=10)
        self.track_listbox.grid(row=5, column=0, columnspan=3, pady=5)

        ttk.Label(frame, text="Quality:").grid(row=6, column=0, sticky="W")
        ttk.OptionMenu(frame, self.quality, "NORMAL", "LOW", "NORMAL", "LOSSLESS").grid(row=6, column=1, sticky="W")

        ttk.Label(frame, text="Lyrics:").grid(row=7, column=0, sticky="W")
        ttk.OptionMenu(frame, self.lyrics_format, "TEXT", "NONE", "TEXT", "LRC").grid(row=7, column=1, sticky="W")

        ttk.Checkbutton(frame, text="Embed Cover", variable=self.embed_cover).grid(row=8, column=0, columnspan=1)
        ttk.Checkbutton(frame, text="Skip Existing", variable=self.skip_existing).grid(row=8, column=1, columnspan=2)

        ttk.Button(frame, text="Download Selected", command=self._start_download).grid(row=9, column=0, columnspan=3, pady=10)

        ttk.Label(frame, textvariable=self.status_var, foreground="blue").grid(row=10, column=0, columnspan=3)

        self.progress = ttk.Progressbar(frame, orient="horizontal", length=300, mode="determinate")
        self.progress.grid(row=11, column=0, columnspan=2, sticky="W")

        self.remaining_label = ttk.Label(frame, text="Remaining: 0")
        self.remaining_label.grid(row=11, column=2, sticky="E")

    def _select_output_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.output_folder.set(folder)
        folder = filedialog.askdirectory()
        if folder:
            self.output_folder.set(folder)

    def _start_search(self):
        threading.Thread(target=self._search_tracks, daemon=True).start()

    def _search_tracks(self):
        try:
            self._init_client()
            query = self.search_query.get().strip()
            self.status_var.set("Searching...")
            search_result = self.client.search(query)
            self.track_results = search_result.tracks.results if search_result.tracks else []

            self.track_listbox.delete(0, tk.END)
            for i, track in enumerate(self.track_results):
                display = f"{track.title} — {', '.join(a.name for a in track.artists)}"
                self.track_listbox.insert(i, display)
            self.status_var.set(f"Found {len(self.track_results)} tracks.")
        except Exception as e:
            self.status_var.set("Search failed.")
            messagebox.showerror("Error", str(e))

    def _start_download(self):
        self.progress["value"] = 0
        self.remaining_label.config(text="Remaining: 0")
        threading.Thread(target=self._download_selected_tracks, daemon=True).start()

    def _start_download_url(self):
        threading.Thread(target=self._download_track, daemon=True).start()

    def _download_selected_tracks(self):
        try:
            self._init_client()
            output = Path(self.output_folder.get())
            output.mkdir(parents=True, exist_ok=True)

            selected = self.track_listbox.curselection()
            if not selected:
                raise ValueError("No tracks selected.")

            quality = CoreTrackQuality[self.quality.get()]
            lyrics_format = LyricsFormat[self.lyrics_format.get()]
            covers_cache = {}

            total = len(selected)
            self.progress["maximum"] = total
            self.progress["value"] = 0
            self.remaining_label.config(text=f"Remaining: {total}")

            for idx, i in enumerate(selected, 1):
                track = self.track_results[i]
                base_path = prepare_base_path(Path(self.path_pattern.get()), track)
                target_path = output / base_path

                if self.skip_existing.get() and target_path.with_suffix(".mp3").exists():
                    self.status_var.set(f"Skipped (exists): {track.title}")
                else:
                    downloadable = to_downloadable_track(track, quality, target_path)
                    self.status_var.set(f"Downloading: {track.title}")
                    download_track(
                        downloadable,
                        lyrics_format=lyrics_format,
                        embed_cover=self.embed_cover.get(),
                        covers_cache=covers_cache,
                    )

                # Update progress bar and label
                self.progress["value"] = idx
                self.remaining_label.config(text=f"Remaining: {total - idx}")
                self.root.update_idletasks()

            self.status_var.set("Download finished.")
            messagebox.showinfo("Done", "Selected tracks downloaded.")
            save_config({
                "token": self.token_var.get(),
                "output": self.output_folder.get(),
                "path_pattern": self.path_pattern.get()
            })

        except Exception as e:
            self.status_var.set("Error during download.")
            messagebox.showerror("Error", str(e))

    def _init_client(self):
        if self.client:
            return
        self.status_var.set("Connecting to Yandex Music...")
        self.client = init_client(
            self.token_var.get(), timeout=5, max_try_count=3, retry_delay=1
        )
        threading.Thread(target=self._download_track, daemon=True).start()

    def _download_track(self):
        try:
            self.progress["maximum"] = 1
            self.progress["value"] = 0
            self.remaining_label.config(text="Remaining: 1")
            self.status_var.set("Initializing client...")
            self._init_client()

            url = self.downloadTrack.get().strip()
            if not url:
                raise ValueError("URL is empty")

            output = Path(self.output_folder.get())
            output.mkdir(parents=True, exist_ok=True)

            quality = CoreTrackQuality[self.quality.get()]
            lyrics_format = LyricsFormat[self.lyrics_format.get()]
            covers_cache = {}

            # Match URL pattern
            if "track/" in url:
                track_id = self._extract_id_from_url(url, "track")
                track = self.client.tracks([track_id])[0]
                tracks = [track]

            elif "album/" in url:
                album_id = self._extract_id_from_url(url, "album")
                album = self.client.albums_with_tracks(album_id)
                tracks = [vol_track for vol in album.volumes for vol_track in vol]

            elif "playlists/" in url:
                match = re.search(r"/users/([^/]+)/playlists/(\d+)", url)
                if not match:
                    raise ValueError("Invalid playlist URL format")
                user, playlist_id = match.groups()
                playlist: Playlist = self.client.users_playlists(playlist_id, user)
                playlist = playlist.fetch_tracks()
                tracks = [track.track for track in playlist.tracks if track.track]

            else:
                raise ValueError("Unsupported or invalid Yandex Music URL")

            for track in tracks:
                base_path = prepare_base_path(Path(self.path_pattern.get()), track)
                target_path = output / base_path
                if self.skip_existing.get() and target_path.with_suffix(".mp3").exists():
                    continue

                downloadable = to_downloadable_track(track, quality, target_path)
                self.status_var.set(f"Downloading: {track.title}")
                download_track(
                    downloadable,
                    lyrics_format=lyrics_format,
                    embed_cover=self.embed_cover.get(),
                    covers_cache=covers_cache,
                )

            self.status_var.set("Download complete!")
            messagebox.showinfo("Success", "Track(s) downloaded successfully.")
            self.progress["value"] = 1
            self.remaining_label.config(text="Remaining: 0")


        except Exception as e:
            self.status_var.set("Error")
            messagebox.showerror("Error", str(e))


    def _extract_id_from_url(self, url: str, content_type: str) -> int | None:
        match = re.search(rf"{content_type}/(\d+)", url)
        return int(match.group(1)) if match else None



if __name__ == "__main__":
    root = tk.Tk()
    app = YandexMusicDownloaderApp(root)
    root.mainloop()
