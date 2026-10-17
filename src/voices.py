# Voice catalog and model storage for the Hugging Face Piper repository.

import json
import os
import re
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

REPOSITORY = "rhasspy/piper-voices"
API_ROOT = f"https://huggingface.co/api/models/{REPOSITORY}/tree/main"
FILE_ROOT = f"https://huggingface.co/{REPOSITORY}/resolve/main"


@dataclass(frozen=True)
class Voice:
    name: str
    path: str
    size: int = 0

    @property
    def model_url(self):
        return self._file_url(self.path)

    @property
    def config_url(self):
        return self._file_url(self.path + ".json")

    @staticmethod
    def _file_url(path):
        return f"{FILE_ROOT}/{urllib.parse.quote(path, safe='/')}?download=true"


class VoiceCatalog:
    """Fetch a language-scoped catalog and cache only small metadata."""

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.voice_dir = self.data_dir / "voices"
        self.cache_dir = self.data_dir / "catalog"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.voice_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _request(self, path=""):
        url = API_ROOT + ("/" + urllib.parse.quote(path, safe="/") if path else "")
        url += "?recursive=" + ("false" if not path else "true") + "&expand=false"
        request = urllib.request.Request(url, headers={"User-Agent": "Hovir/0.1"})
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)

    def _cache_path(self, language):
        return self.cache_dir / ("root.json" if language is None else f"{language}.json")

    def _cached(self, language):
        try:
            with self._cache_path(language).open(encoding="utf-8") as stream:
                return json.load(stream)
        except (OSError, ValueError):
            return None

    def _save_cache(self, language, value):
        path = self._cache_path(language)
        fd, temp_path = tempfile.mkstemp(dir=path.parent, prefix=".catalog-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False)
            os.replace(temp_path, path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def list_languages(self):
        return self._list(None)

    def list_voices(self, language):
        entries = self._list(language)
        return [Voice(item["name"], item["path"], item.get("size", 0)) for item in entries]

    def _list(self, language):
        with self._lock:
            try:
                listing = self._request(language or "")
                entries = self._normalize(listing, language)
                self._save_cache(language, entries)
                return entries
            except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError):
                cached = self._cached(language)
                if cached is not None:
                    if language is None:
                        return [code for code in cached if isinstance(code, str) and re.fullmatch(r"[a-z]{2,3}", code)]
                    return cached
                raise

    @staticmethod
    def _normalize(listing, language):
        if language is None:
            # The repository's top-level directory names are language codes.
            return sorted({entry["path"].split("/", 1)[0]
                           for entry in listing
                           if entry.get("type") == "directory"
                           and re.fullmatch(r"[a-z]{2,3}", entry.get("path", ""))})
        voices = {}
        for item in listing:
            path = item.get("path", "")
            if not path.endswith(".onnx"):
                continue
            voice_path = path[:-5]
            voices[voice_path] = {
                "name": Path(voice_path).name,
                "path": path,
                "size": item.get("size", 0),
            }
        return [voices[path] for path in sorted(voices)]

    def installed(self, voice):
        model = self.voice_dir / voice.path
        return model.is_file() and Path(str(model) + ".json").is_file()

    def model_path(self, voice):
        return str(self.voice_dir / voice.path)

    def list_installed(self):
        voices = []
        for path in self.voice_dir.rglob("*.onnx"):
            if not Path(str(path) + ".json").is_file():
                continue
            relative = path.relative_to(self.voice_dir).as_posix()
            voices.append(Voice(path.stem, relative))
        return sorted(voices, key=lambda voice: (voice.name.casefold(), voice.path))

    def delete_voice(self, voice):
        model = (self.voice_dir / voice.path).resolve()
        config = Path(str(model) + ".json")
        root = self.voice_dir.resolve()
        if not model.is_relative_to(root) or model.suffix != ".onnx":
            raise ValueError("Invalid voice path")
        removed = False
        for path in (model, config):
            try:
                path.unlink()
                removed = True
            except FileNotFoundError:
                pass
        parent = model.parent
        while parent != root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
        return removed

    def delete_all(self):
        voices = self.list_installed()
        for voice in voices:
            self.delete_voice(voice)
        return len(voices)

    def download(self, voice, progress=None, cancelled=None):
        """Download model and config atomically as a pair."""
        destination = self.voice_dir / voice.path
        destination.parent.mkdir(parents=True, exist_ok=True)
        config_destination = Path(str(destination) + ".json")
        temporary = []
        try:
            for url, final in ((voice.model_url, destination),
                               (voice.config_url, config_destination)):
                fd, temp_name = tempfile.mkstemp(dir=final.parent, prefix=".download-")
                os.close(fd)
                temporary.append((Path(temp_name), final))
                request = urllib.request.Request(url, headers={"User-Agent": "Hovir/0.1"})
                with urllib.request.urlopen(request, timeout=60) as response, open(temp_name, "wb") as output:
                    total = int(response.headers.get("Content-Length") or 0)
                    received = 0
                    while True:
                        if cancelled and cancelled():
                            raise InterruptedError("Download cancelled")
                        chunk = response.read(256 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        received += len(chunk)
                        if progress:
                            progress(received, total)
            # Validate that the companion file is JSON before exposing either file.
            with temporary[1][0].open(encoding="utf-8") as stream:
                json.load(stream)
            os.replace(temporary[0][0], destination)
            os.replace(temporary[1][0], config_destination)
            return str(destination)
        finally:
            for temp_path, _final in temporary:
                try:
                    temp_path.unlink()
                except FileNotFoundError:
                    pass
