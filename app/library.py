import json
import os
from pathlib import Path


class PhraseLibrary:
    """Phrase/wildcard library backed directly by .txt files in wildcards_dir.

    Metadata (space flags, exclusions) is stored in wildcards_meta.json.
    All phrase mutations write to disk immediately; move_phrase(save=False)
    buffers in memory until save() is called (used during drag-reorder).
    """

    def __init__(self, wildcards_dir: Path, meta_path: Path | None = None):
        self._wc_dir = wildcards_dir
        self._meta_path = meta_path or (wildcards_dir.parent / "wildcards_meta.json")
        self._meta: dict = {"space_flags": {}, "exclusions": {}}
        self._cache: dict[str, list[str]] = {}

    def load(self) -> None:
        if self._meta_path.exists():
            try:
                self._meta = json.loads(self._meta_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

    def save(self) -> None:
        """Flush any buffered (drag-reordered) categories to disk."""
        for cat, lines in list(self._cache.items()):
            self._write_file(cat, lines)
        self._cache.clear()

    # ── Internal file I/O ─────────────────────────────────────────────────────

    def _file_for(self, category: str) -> Path:
        return self._wc_dir / f"{category}.txt"

    def _read_file(self, category: str) -> list[str]:
        if category in self._cache:
            return list(self._cache[category])
        f = self._file_for(category)
        if not f.exists():
            return []
        return [
            line.strip()
            for line in f.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    def _write_file(self, category: str, lines: list[str]) -> None:
        f = self._file_for(category)
        try:
            existing = f.read_text(encoding="utf-8").splitlines()
            comments = [l for l in existing if l.strip().startswith("#")]
        except OSError:
            comments = [f"# {category} wildcard entries"]
        header = "\n".join(comments) + "\n" if comments else f"# {category} wildcard entries\n"
        tmp = f.with_suffix(".txt.tmp")
        tmp.write_text(header + "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        os.replace(tmp, f)

    def _save_meta(self) -> None:
        self._meta_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._meta_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._meta, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._meta_path)

    # ── Categories ────────────────────────────────────────────────────────────

    def get_categories(self) -> list[str]:
        if not self._wc_dir.exists():
            return []
        return sorted(f.stem for f in self._wc_dir.glob("*.txt"))

    def add_category(self, name: str) -> bool:
        f = self._file_for(name)
        if f.exists():
            return False
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"# {name} wildcard entries\n", encoding="utf-8")
        return True

    def delete_category(self, name: str) -> bool:
        f = self._file_for(name)
        if f.exists():
            f.unlink()
            self._cache.pop(name, None)
            return True
        return False

    def rename_category(self, old: str, new: str) -> bool:
        old_f = self._file_for(old)
        new_f = self._file_for(new)
        if not old_f.exists() or new_f.exists():
            return False
        old_f.rename(new_f)
        if old in self._cache:
            self._cache[new] = self._cache.pop(old)
        return True

    # ── Phrases ───────────────────────────────────────────────────────────────

    def get_phrases(self, category: str) -> list[str]:
        return self._read_file(category)

    def add_phrase(self, category: str, phrase: str) -> None:
        lines = self._read_file(category)
        lines.append(phrase)
        self._write_file(category, lines)
        self._cache.pop(category, None)

    def delete_phrase(self, category: str, index: int) -> str | None:
        lines = self._read_file(category)
        if 0 <= index < len(lines):
            removed = lines.pop(index)
            self._write_file(category, lines)
            self._cache.pop(category, None)
            return removed
        return None

    def edit_phrase(self, category: str, index: int, new_text: str) -> None:
        lines = self._read_file(category)
        if 0 <= index < len(lines):
            lines[index] = new_text
            self._write_file(category, lines)
            self._cache.pop(category, None)

    def move_phrase(self, category: str, from_idx: int, to_idx: int, save: bool = True) -> None:
        lines = self._read_file(category)
        if 0 <= from_idx < len(lines) and 0 <= to_idx < len(lines):
            phrase = lines.pop(from_idx)
            lines.insert(to_idx, phrase)
            if save:
                self._write_file(category, lines)
                self._cache.pop(category, None)
            else:
                self._cache[category] = lines

    # ── Exclusions ────────────────────────────────────────────────────────────

    def get_excluded(self, category: str) -> set[str]:
        return set(self._meta.get("exclusions", {}).get(category, []))

    def is_excluded(self, category: str, phrase: str) -> bool:
        return phrase in self.get_excluded(category)

    def toggle_exclusion(self, category: str, phrase: str) -> bool:
        excl = self._meta.setdefault("exclusions", {})
        cat_excl = excl.setdefault(category, [])
        if phrase in cat_excl:
            cat_excl.remove(phrase)
            now_excluded = False
        else:
            cat_excl.append(phrase)
            now_excluded = True
        self._save_meta()
        return now_excluded

    def exclude_all(self, category: str) -> None:
        self._meta.setdefault("exclusions", {})[category] = list(self.get_phrases(category))
        self._save_meta()

    def exclude_none(self, category: str) -> None:
        self._meta.setdefault("exclusions", {}).pop(category, None)
        self._save_meta()

    # ── Space flags ───────────────────────────────────────────────────────────

    def get_space_flag(self, category: str) -> bool:
        return self._meta.get("space_flags", {}).get(category, False)

    def set_space_flag(self, category: str, value: bool) -> None:
        flags = self._meta.setdefault("space_flags", {})
        if value:
            flags[category] = True
        else:
            flags.pop(category, None)
        self._save_meta()

    def get_all_space_flags(self) -> dict[str, bool]:
        return {
            cat.lower(): True
            for cat, val in self._meta.get("space_flags", {}).items()
            if val
        }

    def get_all_exclusions(self) -> dict[str, set[str]]:
        return {
            cat.lower(): set(phrases)
            for cat, phrases in self._meta.get("exclusions", {}).items()
            if phrases
        }
