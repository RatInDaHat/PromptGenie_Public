import json
import random as _random
from pathlib import Path

from .wildcard import generate_batch, resolve_locks, parse_template_directives

_CONFIG_FILE = Path(__file__).parent / "config.txt"


def _read_data_dir() -> Path:
    if _CONFIG_FILE.exists():
        p = Path(_CONFIG_FILE.read_text(encoding="utf-8").strip())
        if p.is_dir():
            return p
    return Path(".")


def _load_template_names() -> list[str]:
    templates_dir = _read_data_dir() / "templates"
    if not templates_dir.is_dir():
        return ["(no templates found)"]
    try:
        names = []
        for f in templates_dir.glob("*.json"):
            try:
                rec = json.loads(f.read_text(encoding="utf-8"))
                if "name" in rec:
                    names.append(rec["name"])
            except Exception:
                pass
        return sorted(names, key=str.lower) if names else ["(no templates found)"]
    except Exception:
        return ["(error reading templates folder)"]


def _get_template_text(name: str, data_dir: Path) -> str:
    templates_dir = data_dir / "templates"
    try:
        for f in templates_dir.glob("*.json"):
            try:
                rec = json.loads(f.read_text(encoding="utf-8"))
                if rec.get("name") == name:
                    return rec.get("template", "")
            except Exception:
                pass
    except Exception:
        pass
    return ""


def _derive_wan_name(template_name: str) -> str | None:
    """Return W_<Scene> for a D_/S_/etc. template name, or None if already W_ or no underscore."""
    if not template_name or template_name.upper().startswith("W_"):
        return None
    parts = template_name.split("_", 1)
    if len(parts) < 2:
        return None
    return f"W_{parts[1]}"


# ── Load Template node ────────────────────────────────────────────────────────

class PromptGenieLoadTemplate:
    """Select a saved PromptGenie template by name and output its text.

    Wire the output into PromptGenie Batch's template input. Directives
    ([@lock:], [@seq:]) are preserved so the Batch node handles them
    automatically.

    Hit Refresh in the ComfyUI menu after saving new templates in the
    desktop app to update the dropdown.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "template_name": (_load_template_names(), {}),
                "data_dir": ("STRING", {
                    "default": str(_read_data_dir()),
                    "placeholder": "path to PromptGenie/data folder",
                }),
            },
            "optional": {
                "wan_template_name": ("STRING", {
                    "default": "",
                    "placeholder": "Auto (W_Doggy, W_Missionary...) — override here if needed",
                }),
            },
        }

    @classmethod
    def IS_CHANGED(cls, template_name, data_dir="", wan_template_name=""):
        try:
            d = Path(data_dir.strip()) if data_dir.strip() else _read_data_dir()
            templates_dir = d / "templates"
            mtimes = [f.stat().st_mtime for f in templates_dir.glob("*.json")] if templates_dir.is_dir() else []
            return max(mtimes) if mtimes else 0
        except Exception:
            return 0

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("template", "wan_template", "wan_template_name")
    FUNCTION = "load"
    CATEGORY = "PromptGenie"

    def load(self, template_name: str, data_dir: str = "", wan_template_name: str = ""):
        d = Path(data_dir.strip()) if data_dir.strip() else _read_data_dir()
        template = _get_template_text(template_name, d)
        wan_name = wan_template_name.strip() if wan_template_name.strip() else _derive_wan_name(template_name)
        wan_template = _get_template_text(wan_name, d) if wan_name else ""
        return (template, wan_template, wan_name or "")


# ── Batch generation node ─────────────────────────────────────────────────────

class PromptGenieNode:
    """Generate a batch of prompts from a wildcard template.

    Paste a template copied from the PromptGenie desktop app, or wire in
    the output of PromptGenie Load Template. [@lock:] and [@seq:] directives
    are parsed automatically so locked and sequential wildcards behave
    exactly as authored in the desktop app.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "template": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "[@lock: character]\n[@seq: outfit]\n__character__ wearing __outfit__",
                }),
                "count": ("INT", {"default": 10, "min": 1, "max": 100, "step": 1}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF}),
                "wildcards_dir": ("STRING", {
                    "default": str(_read_data_dir() / "wildcards"),
                    "placeholder": "path to wildcards folder",
                }),
                "number_prompts": ("BOOLEAN", {"default": False, "label_on": "numbered", "label_off": "plain"}),
            },
            "optional": {
                "locked_values": ("STRING", {
                    "forceInput": True,
                    "tooltip": "JSON from another PromptGenie Batch node. Locked wildcards matching keys here will use those values instead of picking randomly.",
                }),
                "prefix": ("STRING", {
                    "multiline": False,
                    "default": "",
                    "placeholder": "Danielle, 1girl, ..., indoors, hotel room",
                    "forceInput": True,
                }),
                "negative_template": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "[@3-40: clothing, dressed, clothed]",
                }),
                "wan_template": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "Wire from PromptGenie Load Template wan_template output",
                    "forceInput": True,
                }),
                "wan_output_path": ("STRING", {
                    "multiline": False,
                    "default": "",
                    "placeholder": "C:/path/to/wan_prompts.txt  (leave blank to skip saving)",
                }),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "INT", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("prompts", "negative_prompts", "warnings", "seed_used", "resolved_locks", "wan_prompts", "wan_negative_prompts")
    OUTPUT_IS_LIST = (True, True, False, False, False, True, True)
    FUNCTION = "generate"
    CATEGORY = "PromptGenie"
    OUTPUT_NODE = False

    def generate(self, template: str, count: int, seed: int, wildcards_dir: str,
                 number_prompts: bool, locked_values: str = "", prefix: str = "",
                 negative_template: str = "", wan_template: str = "",
                 wan_output_path: str = ""):
        wc_dir = Path(wildcards_dir.strip()) if wildcards_dir.strip() else _read_data_dir() / "wildcards"
        neg_override = negative_template.strip() if negative_template.strip() else None

        # Build locked_overrides from the template's [@lock:] directive
        _, dir_locks, _, _, _ = parse_template_directives(template)
        locked_overrides = {name: "" for name in dir_locks} if dir_locks else None

        # If upstream locked_values are connected, pin matching names to those values
        if locked_values and locked_values.strip() and locked_overrides:
            try:
                incoming = json.loads(locked_values.strip())
                for name in dir_locks:
                    if name in incoming:
                        locked_overrides[name] = incoming[name]
            except Exception:
                pass

        prompts, seed_used, warnings, resolved_locks, negative_prompts = generate_batch(
            template=template,
            count=count,
            wildcards_dir=wc_dir,
            seed=seed,
            locked_overrides=locked_overrides,
            negative_template=neg_override,
        )

        resolved_locks_json = json.dumps(resolved_locks) if resolved_locks else "{}"

        if prefix and prefix.strip():
            pfx = prefix.strip().rstrip(",").strip()
            prompts = [f"{pfx}, {p}" for p in prompts]

        if number_prompts:
            prompts = [f"{i + 1}. {p}" for i, p in enumerate(prompts)]

        if not negative_prompts:
            negative_prompts = [""] * len(prompts)

        # Generate matching WAN prompts using the same seed so indices align
        wan_prompts: list[str] = []
        wan_negative_prompts: list[str] = []
        if wan_template and wan_template.strip():
            try:
                wp, _, _, _, wn = generate_batch(
                    template=wan_template.strip(),
                    count=count,
                    wildcards_dir=wc_dir,
                    seed=seed_used,
                )
                wan_prompts = wp
                wan_negative_prompts = wn if wn else [""] * len(wp)
            except Exception:
                pass

        if not wan_prompts:
            wan_prompts = [""] * len(prompts)
        if not wan_negative_prompts:
            wan_negative_prompts = [""] * len(prompts)

        # Save WAN prompts to file if a path was specified
        if wan_output_path and wan_output_path.strip() and any(p for p in wan_prompts):
            try:
                out = Path(wan_output_path.strip())
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text("\n".join(p for p in wan_prompts if p), encoding="utf-8")
                if any(n for n in wan_negative_prompts):
                    neg_out = out.with_stem(out.stem + "_neg")
                    neg_out.write_text("\n".join(n for n in wan_negative_prompts if n), encoding="utf-8")
            except Exception:
                pass

        return (prompts, negative_prompts, "\n".join(warnings), seed_used, resolved_locks_json, wan_prompts, wan_negative_prompts)


# ── Resolve node (resolve wildcards once for session consistency) ─────────────

class PromptGenieResolve:
    """Resolve a set of wildcards once and output them as a string.

    Wire the output into PromptGenie Batch's prefix input so every act node
    in the workflow shares the same environment, character description, or any
    other wildcard that should stay consistent across multiple batches.

    Example wildcards input: "environment_tag, character_tag"
    Example output: "indoors, luxury hotel room, warm lighting, Danielle, 1girl"
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "wildcards": ("STRING", {
                    "multiline": False,
                    "default": "environment_tag",
                    "placeholder": "environment_tag, character_tag",
                }),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF}),
                "wildcards_dir": ("STRING", {
                    "default": str(_read_data_dir() / "wildcards"),
                    "placeholder": "path to wildcards folder",
                }),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("resolved",)
    FUNCTION = "resolve"
    CATEGORY = "PromptGenie"

    def resolve(self, wildcards: str, seed: int, wildcards_dir: str):
        wc_dir = Path(wildcards_dir.strip()) if wildcards_dir.strip() else _read_data_dir() / "wildcards"
        names = [n.strip() for n in wildcards.split(",") if n.strip()]
        lock_specs = {name: "" for name in names}
        rng = _random.Random(seed)
        resolved, _ = resolve_locks(lock_specs, wc_dir, rng)
        result = ", ".join(v.strip().rstrip(",") for v in resolved.values() if v.strip())
        return (result,)


# ── Concat node (merge prompt lists from multiple act nodes) ─────────────────

class PromptGenieConcat:
    """Merge prompt lists from up to 8 PromptGenie Batch nodes into one ordered list.

    Connect each act node's prompts output to an input here. Lists are
    appended in slot order (1→2→3...). Empty/unconnected slots are skipped.
    """

    INPUT_IS_LIST = True

    @classmethod
    def INPUT_TYPES(cls):
        req = {"forceInput": True}
        # Optional slots: no forceInput so they can be left unconnected.
        # When unconnected ComfyUI passes [""] (empty string in a list); concat filters these.
        opt = {"forceInput": False, "default": ""}
        return {
            "required": {
                "prompts_1": ("STRING", req),
            },
            "optional": {
                "prompts_2": ("STRING", opt),
                "prompts_3": ("STRING", opt),
                "prompts_4": ("STRING", opt),
                "prompts_5": ("STRING", opt),
                "prompts_6": ("STRING", opt),
                "prompts_7": ("STRING", opt),
                "prompts_8": ("STRING", opt),
            },
        }

    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("prompts", "count")
    OUTPUT_IS_LIST = (True, False)
    FUNCTION = "concat"
    CATEGORY = "PromptGenie"

    @staticmethod
    def _is_prompt(s: str) -> bool:
        # Disabled nodes bypass their locked_values JSON as a prompt — reject those.
        t = s.strip() if s else ""
        return bool(t) and not t.startswith("{")

    def concat(self, prompts_1, prompts_2=None, prompts_3=None, prompts_4=None,
               prompts_5=None, prompts_6=None, prompts_7=None, prompts_8=None):
        result = [p for p in prompts_1 if self._is_prompt(p)]
        for batch in [prompts_2, prompts_3, prompts_4, prompts_5, prompts_6, prompts_7, prompts_8]:
            if batch:
                result.extend(p for p in batch if self._is_prompt(p))
        return (result, len(result))


# ── Pair / Unpack nodes (fix ComfyUI multi-list sync) ────────────────────────

_PAIR_SEP = "\x00PG\x00"  # null-byte sentinel, won't appear in prompts


class PromptGeniePair:
    """Zip prompts + negative_prompts into one synchronized list.

    ComfyUI drives its batch loop from a single list output. When prompts and
    negative_prompts come out of separate slots they run as independent loops
    and the negative gets stuck on index 0.  Feed both into this node first —
    it zips them into one list so a single loop drives both.

    Wire: PromptGenie Batch → PromptGenie Pair → PromptGenie Unpack → CLIP encoders
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompts": ("STRING", {"forceInput": True}),
                "negative_prompts": ("STRING", {"forceInput": True}),
            },
        }

    INPUT_IS_LIST = True
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("pairs",)
    OUTPUT_IS_LIST = (True,)
    FUNCTION = "pair"
    CATEGORY = "PromptGenie"

    def pair(self, prompts, negative_prompts):
        result = []
        for i, pos in enumerate(prompts):
            neg = negative_prompts[i] if i < len(negative_prompts) else ""
            result.append(f"{pos}{_PAIR_SEP}{neg}")
        return (result,)


class PromptGenieUnpack:
    """Split one paired string back into prompt + negative_prompt.

    Connect to the output of PromptGenie Pair.  Both outputs come from the
    same node in each batch iteration, so ComfyUI keeps them in sync.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "pair": ("STRING", {"forceInput": True}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("prompt", "negative_prompt")
    FUNCTION = "unpack"
    CATEGORY = "PromptGenie"

    def unpack(self, pair: str):
        if _PAIR_SEP in pair:
            pos, neg = pair.split(_PAIR_SEP, 1)
            return (pos, neg)
        return (pair, "")


# ── I2V Source node (index-based image + prompt loader for i2v) ───────────────

_I2V_STATE_FILE = ".promptgenie_i2v"


class PromptGenieI2VSource:
    """Load one image and its matching WAN prompt by index for i2v workflows.

    On each run the node loads the image and prompt at the current index, then
    advances the index so the next queue run picks the next image. Queue N times
    to process all N images automatically.

    Set current_index to 0 to auto-advance each run, or any positive value to
    jump to a specific image (state updates so the next run continues from there).

    The index state is saved to a small file (.promptgenie_i2v) inside the
    folder so it persists between ComfyUI sessions.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "folder_path": ("STRING", {
                    "default": "",
                    "placeholder": "C:/ComfyUI/output/session1",
                }),
                "prompts_file": ("STRING", {
                    "default": "",
                    "placeholder": "leave blank to auto-detect *_wan.txt",
                }),
                "current_index": ("INT", {
                    "default": 1, "min": 1, "max": 9999,
                    "tooltip": "Image index. Behaviour depends on index_mode.",
                }),
                "index_mode": (["auto", "set", "fixed"], {
                    "default": "auto",
                    "tooltip": "auto = advance each run ignoring current_index  |  set = jump to current_index once then auto-advance (safe to queue 61 runs)  |  fixed = always use current_index every run",
                }),
            },
            "optional": {
                "neg_prompts_file": ("STRING", {
                    "default": "",
                    "placeholder": "leave blank to auto-detect *_wan_neg.txt",
                }),
                "filename_prefix": ("STRING", {
                    "default": "",
                    "placeholder": "gen_  (leave blank for all images)",
                }),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING", "INT", "INT")
    RETURN_NAMES = ("image", "prompt", "neg_prompt", "current_index", "total")
    FUNCTION = "load"
    CATEGORY = "PromptGenie"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")  # always re-execute so index advances each run

    def load(self, folder_path, prompts_file, current_index=1, index_mode="auto",
             neg_prompts_file="", filename_prefix=""):
        import numpy as np
        import torch
        from PIL import Image as _PILImage

        folder = Path(folder_path.strip())
        prefix = filename_prefix.strip()
        state_file = folder / _I2V_STATE_FILE

        print(f"[PromptGenieI2VSource] folder={folder} | exists={folder.is_dir()}")
        print(f"[PromptGenieI2VSource] prompts_file={repr(prompts_file)} | prefix={repr(prefix)} | index_mode={index_mode} | current_index={current_index}")

        # Collect and sort image files
        image_files = []
        if folder.is_dir():
            for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
                for f in folder.glob(ext):
                    if f.name == _I2V_STATE_FILE:
                        continue
                    if not prefix or f.name.startswith(prefix):
                        image_files.append(f)
        image_files.sort(key=lambda f: f.name)
        print(f"[PromptGenieI2VSource] images found: {len(image_files)}")

        # Auto-detect WAN prompts file if not specified
        def _auto_detect_wan(folder: Path, neg: bool) -> Path | None:
            candidates = sorted(folder.glob("*_wan_neg.txt" if neg else "*_wan.txt"))
            candidates = [f for f in candidates if ("_neg" in f.name) == neg]
            print(f"[PromptGenieI2VSource] auto-detect neg={neg}: {[f.name for f in candidates]}")
            return candidates[0] if candidates else None

        def _resolve_path(val: str, folder: Path) -> Path | None:
            if not val:
                return None
            p = Path(val)
            if not p.is_absolute():
                p = folder / p  # treat bare filename as relative to folder
            return p

        # Read prompts
        prompts, neg_prompts = [], []
        pf_str = prompts_file.strip() if prompts_file else ""
        pf = _resolve_path(pf_str, folder) if pf_str else None
        if pf and not pf.exists():
            print(f"[PromptGenieI2VSource] prompts_file not found, falling back to auto-detect")
            pf = None
        if pf is None:
            pf = _auto_detect_wan(folder, neg=False)
        print(f"[PromptGenieI2VSource] prompts path={pf} | exists={pf.exists() if pf else 'N/A'}")
        if pf and pf.exists():
            prompts = [l for l in pf.read_text(encoding="utf-8").splitlines() if l.strip()]
        print(f"[PromptGenieI2VSource] prompts loaded: {len(prompts)}")

        nf_str = neg_prompts_file.strip() if neg_prompts_file else ""
        nf = _resolve_path(nf_str, folder) if nf_str else None
        if nf and not nf.exists():
            print(f"[PromptGenieI2VSource] neg_prompts_file not found, falling back to auto-detect")
            nf = None
        if nf is None:
            nf = _auto_detect_wan(folder, neg=True)
        print(f"[PromptGenieI2VSource] neg path={nf} | exists={nf.exists() if nf else 'N/A'}")
        if nf and nf.exists():
            neg_prompts = [l for l in nf.read_text(encoding="utf-8").splitlines() if l.strip()]
        print(f"[PromptGenieI2VSource] neg_prompts loaded: {len(neg_prompts)}")

        count = len(image_files)
        if prompts:
            count = min(count, len(prompts))

        if count == 0:
            print("[PromptGenieI2VSource] count=0, returning dummy")
            dummy = torch.zeros(1, 64, 64, 3)
            return (dummy, "", "", 0, 0)

        # State file: "next_idx:last_set_index"
        # last_set_index lets "set" mode apply the jump exactly once per new target.
        try:
            parts = state_file.read_text(encoding="utf-8").strip().split(":")
            state_next = int(parts[0])
            last_set = int(parts[1]) if len(parts) > 1 else 0
        except Exception:
            state_next, last_set = 1, 0

        if index_mode == "fixed":
            idx = max(1, min(current_index, count))
            next_idx = idx  # don't advance state
            new_last_set = 0
        elif index_mode == "set" and current_index != last_set:
            # Fresh jump — apply once, then subsequent runs fall through to auto
            idx = max(1, min(current_index, count))
            next_idx = (idx % count) + 1
            new_last_set = current_index
        else:
            # auto, or "set" with the same index already applied
            idx = state_next
            next_idx = (idx % count) + 1
            new_last_set = last_set if index_mode == "set" else 0

        state_file.write_text(f"{next_idx}:{new_last_set}", encoding="utf-8")

        idx = max(1, min(idx, count))
        i = idx - 1  # 0-based

        img = _PILImage.open(image_files[i]).convert("RGB")
        arr = np.array(img).astype(np.float32) / 255.0
        image_tensor = torch.from_numpy(arr).unsqueeze(0)

        prompt = prompts[i] if i < len(prompts) else ""
        neg = neg_prompts[i] if i < len(neg_prompts) else ""

        print(f"[PromptGenieI2VSource] idx={idx}/{count} | prompt={repr(prompt[:80])} | neg={repr(neg[:60])}")
        return {"ui": {"current_index": [idx]}, "result": (image_tensor, prompt, neg, idx, count)}


# ── Read File node (load saved prompt list for i2v workflows) ─────────────────

class PromptGenieReadFile:
    """Load a saved prompts .txt file and output each line as a list item.

    Use this in an i2v workflow to load the _wan.txt saved by PromptGenie Batch.
    Pair with a folder image loader — line N matches image N.
    Connect wan_negative_prompts by pointing a second Read File node at the _wan_neg.txt.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "file_path": ("STRING", {
                    "multiline": False,
                    "default": "",
                    "placeholder": "C:/path/to/prompts_wan.txt",
                }),
            },
        }

    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("prompts", "count")
    OUTPUT_IS_LIST = (True, False)
    FUNCTION = "read"
    CATEGORY = "PromptGenie"

    @classmethod
    def IS_CHANGED(cls, file_path: str):
        try:
            p = Path(file_path.strip())
            return p.stat().st_mtime if p.exists() else 0
        except Exception:
            return 0

    def read(self, file_path: str):
        p = Path(file_path.strip())
        if not p.exists():
            return ([""], 0)
        lines = [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
        if not lines:
            return ([""], 0)
        return (lines, len(lines))


# ── WAN Collect node (merge + save WAN prompts from multiple batch nodes) ─────

class PromptGenieWANCollect:
    """Merge WAN prompt lists from up to 8 Batch nodes and save to a single file.

    Connect each Batch node's wan_prompts output to a positive slot and its
    wan_negative_prompts to the matching negative slot. Lists are merged in
    slot order (1→2→3...) to match the image file sequence.

    Set output_path to save the merged WAN prompts for use in the i2v workflow.
    A _neg.txt file is saved alongside if any negative prompts are connected.
    """

    INPUT_IS_LIST = True

    @classmethod
    def INPUT_TYPES(cls):
        pos = {"forceInput": True}
        neg = {"forceInput": True}
        return {
            "required": {
                "wan_prompts_1": ("STRING", pos),
                "output_path": ("STRING", {}),
            },
            "optional": {
                "wan_prompts_2": ("STRING", pos),
                "wan_prompts_3": ("STRING", pos),
                "wan_prompts_4": ("STRING", pos),
                "wan_prompts_5": ("STRING", pos),
                "wan_prompts_6": ("STRING", pos),
                "wan_prompts_7": ("STRING", pos),
                "wan_prompts_8": ("STRING", pos),
                "wan_negative_1": ("STRING", neg),
                "wan_negative_2": ("STRING", neg),
                "wan_negative_3": ("STRING", neg),
                "wan_negative_4": ("STRING", neg),
                "wan_negative_5": ("STRING", neg),
                "wan_negative_6": ("STRING", neg),
                "wan_negative_7": ("STRING", neg),
                "wan_negative_8": ("STRING", neg),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "INT")
    RETURN_NAMES = ("wan_prompts", "wan_negative_prompts", "count")
    OUTPUT_IS_LIST = (True, True, False)
    OUTPUT_NODE = True
    FUNCTION = "collect"
    CATEGORY = "PromptGenie"

    def collect(self, wan_prompts_1, output_path,
                wan_prompts_2=None, wan_prompts_3=None, wan_prompts_4=None,
                wan_prompts_5=None, wan_prompts_6=None, wan_prompts_7=None,
                wan_prompts_8=None,
                wan_negative_1=None, wan_negative_2=None, wan_negative_3=None,
                wan_negative_4=None, wan_negative_5=None, wan_negative_6=None,
                wan_negative_7=None, wan_negative_8=None):

        # Merge positive lists in slot order
        pos_result = list(wan_prompts_1)
        for batch in [wan_prompts_2, wan_prompts_3, wan_prompts_4, wan_prompts_5,
                      wan_prompts_6, wan_prompts_7, wan_prompts_8]:
            if batch:
                pos_result.extend(batch)

        # Merge negative lists in same slot order
        neg_result = []
        for batch in [wan_negative_1, wan_negative_2, wan_negative_3, wan_negative_4,
                      wan_negative_5, wan_negative_6, wan_negative_7, wan_negative_8]:
            if batch:
                neg_result.extend(batch)

        # Pad neg to match pos length
        while len(neg_result) < len(pos_result):
            neg_result.append("")

        # Save to file
        path_str = output_path[0] if isinstance(output_path, list) else output_path
        if path_str and path_str.strip():
            try:
                out = Path(path_str.strip())
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text("\n".join(p for p in pos_result if p), encoding="utf-8")
                if any(n for n in neg_result):
                    neg_out = out.with_stem(out.stem + "_neg")
                    neg_out.write_text("\n".join(n for n in neg_result if n), encoding="utf-8")
            except Exception:
                pass

        return (pos_result, neg_result, len(pos_result))


# ── Counter node ─────────────────────────────────────────────────────────────

class PromptGenieCounter:
    """Count sampler runs and reset automatically each batch.

    Connect any node's output to trigger — it passes straight through
    unchanged. Wire PromptGenieConcat count → total. Place it anywhere in
    the per-item execution path (e.g. KSampler → Counter → VAE Decode).
    """

    _count: int = 0

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "trigger": ("*", {"forceInput": True}),
                "total": ("INT", {"forceInput": True}),
            }
        }

    RETURN_TYPES = ("*", "INT", "STRING")
    RETURN_NAMES = ("trigger", "count", "label")
    FUNCTION = "tick"
    CATEGORY = "PromptGenie"

    @classmethod
    def IS_CHANGED(cls, trigger, total: int):
        return float("nan")

    def tick(self, trigger, total: int):
        PromptGenieCounter._count += 1
        if PromptGenieCounter._count > total:
            PromptGenieCounter._count = 1
        return (trigger, PromptGenieCounter._count, f"{PromptGenieCounter._count} / {total}")


# ── Folder Picker node ───────────────────────────────────────────────────────

class PromptGenieFolderPicker:
    """Output a folder path chosen via a Browse button in the node UI.

    Wire the output into any node that accepts a folder path string.
    The Browse button opens a native OS folder dialog on the ComfyUI server.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "folder_path": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": "Click Browse or paste a path",
                }),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("folder_path",)
    FUNCTION = "get_path"
    CATEGORY = "PromptGenie"

    def get_path(self, folder_path: str):
        return (folder_path.strip(),)


# Register the folder-browse API endpoint (runs once at import time).
try:
    from server import PromptServer
    from aiohttp import web as _web
    import threading as _threading

    @PromptServer.instance.routes.get("/promptgenie/browse_folder")
    async def _browse_folder_handler(request):
        result = {"path": ""}

        def _pick():
            try:
                import tkinter as _tk
                from tkinter import filedialog as _fd
                import ctypes, ctypes.wintypes
                root = _tk.Tk()
                # Position root at cursor so dialog appears on the correct monitor
                try:
                    pt = ctypes.wintypes.POINT()
                    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                    root.geometry(f"+{pt.x}+{pt.y}")
                    root.update_idletasks()  # flush geometry before withdrawing
                except Exception:
                    pass
                root.withdraw()
                root.wm_attributes("-topmost", True)
                path = _fd.askdirectory(title="Select Folder", parent=root)
                root.destroy()
                result["path"] = path or ""
            except Exception:
                pass

        t = _threading.Thread(target=_pick, daemon=True)
        t.start()
        t.join(timeout=120)
        return _web.json_response({"path": result["path"]})

except Exception:
    pass  # outside ComfyUI context (unit tests, etc.)


# ─────────────────────────────────────────────────────────────────────────────

WEB_DIRECTORY = "./web"

NODE_CLASS_MAPPINGS = {
    "PromptGenieLoadTemplate": PromptGenieLoadTemplate,
    "PromptGenie": PromptGenieNode,
    "PromptGenieResolve": PromptGenieResolve,
    "PromptGenieConcat": PromptGenieConcat,
    "PromptGeniePair": PromptGeniePair,
    "PromptGenieUnpack": PromptGenieUnpack,
    "PromptGenieCounter": PromptGenieCounter,
    "PromptGenieReadFile": PromptGenieReadFile,
    "PromptGenieI2VSource": PromptGenieI2VSource,
    "PromptGenieWANCollect": PromptGenieWANCollect,
    "PromptGenieFolderPicker": PromptGenieFolderPicker,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PromptGenieLoadTemplate": "PromptGenie Load Template",
    "PromptGenie": "PromptGenie Batch",
    "PromptGenieResolve": "PromptGenie Resolve",
    "PromptGenieConcat": "PromptGenie Concat",
    "PromptGeniePair": "PromptGenie Pair",
    "PromptGenieUnpack": "PromptGenie Unpack",
    "PromptGenieCounter": "PromptGenie Counter",
    "PromptGenieReadFile": "PromptGenie Read File",
    "PromptGenieI2VSource": "PromptGenie I2V Source",
    "PromptGenieWANCollect": "PromptGenie WAN Collect",
    "PromptGenieFolderPicker": "PromptGenie Folder Picker",
}
