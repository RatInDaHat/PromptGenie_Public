import json
import os
from pathlib import Path

DEFAULT_SETTINGS: dict = {
    "version": 1,
    "last_template": "__character__, __action__, __lighting__, __camera_angles__, __style__",
    "last_count": 10,
    "last_seed": None,
    "lock_seed": False,
    "wildcards_dir": "data/wildcards",
    "last_output_dir": "output",
    "window_geometry": "1280x760",
    "appearance_mode": "dark",
}


class AppSettings:
    def __init__(self, path: Path):
        self.path = path
        self._data: dict = dict(DEFAULT_SETTINGS)

    def load(self) -> None:
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                self._data.update(loaded)
            except (json.JSONDecodeError, OSError):
                pass

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value) -> None:
        self._data[key] = value
