"""Online search for Creative Commons / public-domain music.

Opt-in network feature (the rest of Media Remix is local). Three sources,
in the order they are offered:

* Openverse (api.openverse.org) — CC audio aggregator, no key needed,
  licence and attribution text come with every result, direct audio URL.
* Internet Archive (archive.org) — netlabel / open-source audio with a
  licence URL; one "item" is an album, each MP3 file becomes a track.
* Jamendo (api.jamendo.com) — optional, needs JAMENDO_CLIENT_ID in .env.
  Search + preview; a download link is used only when the artist allows it
  (audiodownload_allowed), and the credit names both artist and Jamendo as
  the API terms require.

download() saves the file under assets/music/downloads/ with a JSON
sidecar (title, creator, licence, attribution, page URL) that
core/music.py reads to list the track as a preset.
"""
from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import requests

USER_AGENT = "OpenVideoStudio/0.5 (https://github.com/BartokIT/OpenVideoStudio; local-first video tool)"
TIMEOUT = 20
SOURCES = ("openverse", "archive", "jamendo")
SOURCE_LABELS = {"openverse": "Openverse (CC aggregator)", "archive": "Internet Archive (netlabels / public domain)",
                 "jamendo": "Jamendo (needs JAMENDO_CLIENT_ID)"}
MOOD_WORDS = {
    "nostalgic": "piano nostalgic", "cinematic": "cinematic orchestral", "romantic": "romantic acoustic",
    "upbeat": "upbeat happy acoustic", "energetic": "energetic electronic beat", "calm": "ambient calm",
}

_CACHE: dict[tuple, tuple[float, list]] = {}
CACHE_SECONDS = 600


@dataclass
class OnlineTrack:
    source: str
    id: str
    title: str
    creator: str
    duration: float            # seconds, 0 if unknown
    license: str               # short, e.g. "CC BY-NC-SA 3.0", "Public domain"
    license_url: str
    page_url: str
    audio_url: str             # stream / preview URL
    download_url: str          # empty when downloading is not allowed
    attribution: str
    ext: str = "mp3"

    @property
    def downloadable(self) -> bool:
        return bool(self.download_url)

    @property
    def no_derivatives(self) -> bool:
        """CC ND licences: putting music under pictures is an adaptation
        (a "sync"), which ND does not allow, so the track can't go in a film."""
        return bool(re.search(r"\bND\b", self.license or ""))

    def label(self) -> str:
        m, s = divmod(int(self.duration), 60)
        dur = f"{m}:{s:02d}" if self.duration else "?:??"
        return f"{self.title} — {self.creator} · {dur} · {self.license}"


def _get(url: str, params: Optional[dict] = None, headers: Optional[dict] = None) -> requests.Response:
    h = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        h.update(headers)
    r = requests.get(url, params=params, headers=h, timeout=TIMEOUT)
    r.raise_for_status()
    return r


def _cc_label(code: str, version: str = "") -> str:
    code = (code or "").lower().strip()
    if code in ("pdm", "publicdomain", "public domain"):
        return "Public domain"
    if code == "cc0":
        return "CC0" + (f" {version}" if version else "")
    if code.startswith("by") or code.startswith("cc-by") or code.startswith("cc by"):
        core = code.replace("cc-", "").replace("cc ", "").upper().replace("-", " ")
        return f"CC {core}" + (f" {version}" if version else "")
    return code.upper() or "Unknown"


def _license_from_url(url: str) -> str:
    m = re.search(r"creativecommons\.org/(licenses|publicdomain)/([a-z-]+)/([\d.]+)", url or "")
    if not m:
        return "Public domain" if "publicdomain" in (url or "") else ("Unknown" if not url else url)
    kind, code, ver = m.groups()
    if kind == "publicdomain":
        return "CC0" if code == "zero" else "Public domain"
    return _cc_label(code, ver)


def _slug(text: str, n: int = 48) -> str:
    s = re.sub(r"[^\w\-]+", "_", text or "", flags=re.UNICODE).strip("_")
    return (s[:n] or "track").rstrip("_")


# ------------------------------------------------------------- Openverse

def search_openverse(query: str, limit: int = 20) -> list[OnlineTrack]:
    params = {"q": query, "category": "music", "page_size": min(max(limit, 1), 20)}
    key = os.environ.get("OPENVERSE_API_KEY", "").strip()
    headers = {"Authorization": f"Bearer {key}"} if key else None
    data = _get("https://api.openverse.org/v1/audio/", params, headers).json()
    out = []
    for r in data.get("results", []):
        url = r.get("url") or ""
        if not url:
            continue
        lic = _cc_label(r.get("license", ""), r.get("license_version", ""))
        dur = float(r.get("duration") or 0) / 1000.0
        creator = r.get("creator") or "Unknown artist"
        attribution = r.get("attribution") or f"\"{r.get('title')}\" by {creator}, {lic}"
        ext = "mp3"
        ft = (r.get("filetype") or "").lower()
        if ft in ("ogg", "flac", "wav", "m4a"):
            ext = ft
        out.append(OnlineTrack(
            source="openverse", id=str(r.get("id")), title=r.get("title") or "Untitled", creator=creator,
            duration=round(dur, 1), license=lic, license_url=r.get("license_url") or "",
            page_url=r.get("foreign_landing_url") or "", audio_url=url, download_url=url,
            attribution=attribution, ext=ext,
        ))
    return out


# ------------------------------------------------------- Internet Archive

def search_archive(query: str, limit: int = 20, items: int = 6) -> list[OnlineTrack]:
    q = f"({query}) AND mediatype:audio AND (collection:netlabels OR collection:opensource_audio)"
    params = {"q": q, "fl[]": ["identifier", "title", "creator", "licenseurl"], "rows": items, "page": 1,
              "output": "json", "sort[]": "downloads desc"}
    docs = _get("https://archive.org/advancedsearch.php", params).json().get("response", {}).get("docs", [])
    docs = [d for d in docs if d.get("licenseurl")]

    def files_of(doc):
        try:
            meta = _get(f"https://archive.org/metadata/{doc['identifier']}").json()
        except Exception:
            return []
        rows = []
        creator = doc.get("creator")
        if isinstance(creator, list):
            creator = ", ".join(creator)
        lic = _license_from_url(doc.get("licenseurl", ""))
        page = f"https://archive.org/details/{doc['identifier']}"
        for f in meta.get("files", []):
            if "MP3" not in str(f.get("format", "")).upper():
                continue
            name = f.get("name", "")
            url = f"https://archive.org/download/{doc['identifier']}/{requests.utils.quote(name)}"
            title = f.get("title") or re.sub(r"\.mp3$", "", name, flags=re.I)
            try:
                dur = float(f.get("length") or 0)
            except ValueError:
                dur = 0.0
            rows.append(OnlineTrack(
                source="archive", id=f"{doc['identifier']}/{name}", title=title, creator=creator or "Unknown artist",
                duration=round(dur, 1), license=lic, license_url=doc.get("licenseurl", ""), page_url=page,
                audio_url=url, download_url=url,
                attribution=f"\"{title}\" by {creator or 'Unknown artist'} ({doc.get('title', '')}), {lic} — {page}",
            ))
        return rows

    out: list[OnlineTrack] = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        for rows in ex.map(files_of, docs):
            out.extend(rows)
            if len(out) >= limit:
                break
    return out[:limit]


# --------------------------------------------------------------- Jamendo

def jamendo_available() -> bool:
    return bool(os.environ.get("JAMENDO_CLIENT_ID", "").strip())


def search_jamendo(query: str, limit: int = 20) -> list[OnlineTrack]:
    client_id = os.environ.get("JAMENDO_CLIENT_ID", "").strip()
    if not client_id:
        raise RuntimeError("Jamendo needs JAMENDO_CLIENT_ID in studio/.env (free key from devportal.jamendo.com)")
    params = {"client_id": client_id, "format": "json", "limit": min(max(limit, 1), 50), "search": query,
              "include": "licenses", "audioformat": "mp32", "audiodlformat": "mp32"}
    data = _get("https://api.jamendo.com/v3.0/tracks/", params).json()
    out = []
    for r in data.get("results", []):
        lic_url = r.get("license_ccurl") or ""
        lic = _license_from_url(lic_url)
        allowed = bool(r.get("audiodownload_allowed")) and bool(r.get("audiodownload"))
        creator = r.get("artist_name") or "Unknown artist"
        page = r.get("shareurl") or f"https://www.jamendo.com/track/{r.get('id')}"
        out.append(OnlineTrack(
            source="jamendo", id=str(r.get("id")), title=r.get("name") or "Untitled", creator=creator,
            duration=float(r.get("duration") or 0), license=lic, license_url=lic_url, page_url=page,
            audio_url=r.get("audio") or "", download_url=r.get("audiodownload") if allowed else "",
            attribution=f"\"{r.get('name')}\" by {creator}, {lic} — via Jamendo ({page})",
        ))
    return out


# ------------------------------------------------------------- façade

def search(query: str, source: str = "openverse", mood: Optional[str] = None, limit: int = 20) -> list[OnlineTrack]:
    q = (query or "").strip()
    if mood and mood in MOOD_WORDS:
        q = f"{q} {MOOD_WORDS[mood]}".strip()
    if not q:
        raise ValueError("Type something to search for (or pick a mood).")
    key = (source, q.lower(), limit)
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    if source == "openverse":
        res = search_openverse(q, limit)
    elif source == "archive":
        res = search_archive(q, limit)
    elif source == "jamendo":
        res = search_jamendo(q, limit)
    else:
        raise ValueError(f"unknown source {source}")
    _CACHE[key] = (time.time(), res)
    return res


def download(track: OnlineTrack, dest_dir: Path, progress: Optional[Callable[[float, str], None]] = None) -> Path:
    """Saves the track and its sidecar; returns the audio path. Refuses
    tracks whose source does not allow downloading."""
    if not track.downloadable:
        raise PermissionError("This track cannot be downloaded (the artist allows streaming only).")
    if track.no_derivatives:
        raise PermissionError(f"{track.license} does not allow using the music in a video "
                              "(syncing it to pictures is a derivative). Pick another track.")
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    base = f"{track.source}_{_slug(track.id, 24)}_{_slug(track.title)}"
    out = dest_dir / f"{base}.{track.ext}"
    sidecar = dest_dir / f"{base}.json"
    if out.exists() and sidecar.exists():
        return out
    say = progress or (lambda f, m: None)
    say(0.05, f"Downloading “{track.title}”")
    with requests.get(track.download_url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, stream=True) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        tmp = out.with_suffix(out.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                if chunk:
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        say(0.05 + 0.9 * done / total, f"Downloading “{track.title}” {done // 1024} KB")
        if done < 2048:
            tmp.unlink(missing_ok=True)
            raise RuntimeError("Download returned no audio data.")
        tmp.replace(out)
    meta = {**asdict(track), "downloaded_at": datetime.now().isoformat(), "file": out.name}
    sidecar.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    say(1.0, f"“{track.title}” added to your music presets")
    return out
