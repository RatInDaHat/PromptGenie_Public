import json
import os
from datetime import datetime
from pathlib import Path


class TemplateLibrary:
    def __init__(self, path: Path):
        # Accept either a directory or the old templates.json path — normalise to dir
        if path.suffix == ".json":
            self.path = path.parent / "templates"
        else:
            self.path = path

    def load(self) -> None:
        self.path.mkdir(parents=True, exist_ok=True)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _file(self, name: str) -> Path:
        return self.path / f"{_safe(name)}.json"

    def _read(self, name: str) -> dict | None:
        f = self._file(name)
        if not f.exists():
            return None
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _write(self, record: dict) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        f = self._file(record["name"])
        tmp = f.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, f)

    def _all_records(self) -> list[dict]:
        records = []
        for f in self.path.glob("*.json"):
            try:
                rec = json.loads(f.read_text(encoding="utf-8"))
                if "name" in rec and "template" in rec:
                    records.append(rec)
            except (json.JSONDecodeError, OSError):
                pass
        return records

    # ── Public API (same as before) ───────────────────────────────────────────

    def save_template(self, name: str, text: str) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        existing = self._read(name)
        if existing:
            existing["template"] = text
            existing["last_used"] = now
            self._write(existing)
        else:
            self._write({"name": name, "template": text, "created_at": now, "last_used": now})

    def delete_template(self, name: str) -> None:
        f = self._file(name)
        if f.exists():
            f.unlink()

    def rename_template(self, old: str, new: str) -> bool:
        if self._file(new).exists():
            return False
        rec = self._read(old)
        if rec is None:
            return False
        old_file = self._file(old)
        rec["name"] = new
        self._write(rec)
        old_file.unlink(missing_ok=True)
        return True

    def touch_last_used(self, name: str) -> None:
        rec = self._read(name)
        if rec:
            rec["last_used"] = datetime.now().isoformat(timespec="seconds")
            self._write(rec)

    def get_templates(self, sort: str = "recent") -> list[dict]:
        records = self._all_records()
        if sort == "alpha":
            return sorted(records, key=lambda t: t["name"].lower())
        return sorted(records, key=lambda t: t.get("last_used") or "", reverse=True)

    def get_text(self, name: str) -> str | None:
        rec = self._read(name)
        return rec["template"] if rec else None

    def exists(self, name: str) -> bool:
        return self._file(name).exists()

    # kept for compat — no-op since each save is already atomic per file
    def save(self) -> None:
        pass


def _safe(name: str) -> str:
    """Convert a template name to a safe filename."""
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
