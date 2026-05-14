"""
wan_export.py — Convert a PromptGenie batch PNG to Wan2.2 I2V prompts.

Usage:
    python wan_export.py <any_png_from_batch> [output.txt]

If output path is omitted, saves wan_prompts.txt next to the PNG.
"""

import sys
import json
from pathlib import Path
from PIL import Image

# Load tag config from data/wan_export_tags.json.
# Edit that file to change which tags are stripped or mapped without touching this code.
try:
    _tag_cfg = json.loads(
        (Path(__file__).parent / "data" / "wan_export_tags.json").read_text(encoding="utf-8")
    )
    STRIP_TAGS: set[str] = set(_tag_cfg.get("strip_tags", []))
    TAG_MAP: dict[str, str] = _tag_cfg.get("tag_map", {})
except Exception:
    STRIP_TAGS = set()
    TAG_MAP = {}

# ── Wan2.2 I2V suffix ──────────────────────────────────────────────────────

WAN_SUFFIX = "smooth fluid motion, natural body movement, cinematic, high quality"

# ── Bridge motion overrides for strip sequence ─────────────────────────────

def _tags(raw: str) -> set[str]:
    return {p.strip().lower().replace(" ", "_").replace("-", "_") for p in raw.split(",")}


def _bridge_motion(raw: str) -> str | None:
    """Return a bridge motion prompt if this is a stripping transition, else None."""
    t = _tags(raw)

    # Prompt 1: fully clothed — motion is removing the top
    if "clothed" in t:
        # Extract clothing items for context
        clothing = [
            p.strip().replace("_", " ")
            for p in raw.split(",")
            if p.strip().lower() not in STRIP_TAGS
            and p.strip().lower() not in {"clothed", "standing", "sensual_pose",
                                          "flirtatious", "from_front", "upper_body",
                                          "facing_viewer"}
            and not any(q in p.lower() for q in ["y.o.", "4k", "8k", "photo",
                                                   "skin_", "high_res", "detailed",
                                                   "pores", "pool", "outdoor",
                                                   "indoor", "background"])
        ]
        ctx = ", ".join(clothing[:3]) if clothing else "her outfit"
        return (
            f"wearing {ctx}, slowly pulling her top up and off, undressing, "
            f"removing her shirt, stripping, {WAN_SUFFIX}"
        )

    # Prompt 2: topless, removing bottoms
    if any(k in t for k in {"removing_shorts", "hands_on_waistband",
                              "removing_pants", "removing_skirt"}):
        BOTTOM_WORDS = ["shorts", "jeans", "skirt", "pants", "leggings",
                        "culottes", "chinos", "trousers"]
        bottom_tags = [
            p.strip().replace("_", " ")
            for p in raw.split(",")
            if any(b in p.lower() for b in BOTTOM_WORDS)
            and not any(x in p.lower() for x in ["removing", "waistband"])
        ]
        ctx = bottom_tags[0] if bottom_tags else "her bottoms"
        return (
            f"topless, sliding {ctx} down her legs, removing her bottoms, "
            f"stripping, undressing, {WAN_SUFFIX}"
        )

    return None


def convert_prompt(raw: str) -> str:
    bridge = _bridge_motion(raw)
    if bridge:
        return bridge

    parts = [p.strip() for p in raw.split(",") if p.strip()]
    converted = []
    for tag in parts:
        key = tag.lower().replace(" ", "_").replace("-", "_")
        if key in STRIP_TAGS:
            continue
        if key in TAG_MAP:
            converted.append(TAG_MAP[key])
        else:
            converted.append(tag.replace("_", " ").replace("-", " "))
    if not converted:
        return WAN_SUFFIX
    return ", ".join(converted) + ", " + WAN_SUFFIX


def _clean_raw(prompt: str) -> str:
    """Strip stray brackets and whitespace left by template conditional syntax."""
    return prompt.strip().strip("]").strip("[").strip()


def extract_prompts_from_png(png_path: Path) -> list[str]:
    img = Image.open(png_path)
    meta = img.info
    if "prompt" not in meta:
        raise ValueError("No ComfyUI metadata found in this PNG.")
    data = json.loads(meta["prompt"])
    for node in data.values():
        pm = node.get("inputs", {}).get("preview_markdown")
        if pm:
            entries = [p.strip() for p in pm.strip().split("\n\n") if p.strip()]
            # Filter out embedded [NEG]...[/NEG] blocks stored between prompts
            prompts = [
                _clean_raw(e) for e in entries
                if not e.strip().startswith("[NEG]")
            ]
            return [p for p in prompts if p]
    raise ValueError(
        "No prompt list found. Ensure your workflow includes a PromptGenie preview node."
    )


def main():
    if len(sys.argv) < 2:
        print("Usage: python wan_export.py <any_png_from_batch> [output.txt]")
        sys.exit(1)

    png_path = Path(sys.argv[1])
    if not png_path.exists():
        print(f"File not found: {png_path}")
        sys.exit(1)

    print(f"Reading metadata from: {png_path.name}")
    prompts = extract_prompts_from_png(png_path)
    print(f"Found {len(prompts)} prompts.")

    wan_prompts = [convert_prompt(p) for p in prompts]

    out_path = Path(sys.argv[2]) if len(sys.argv) >= 3 else png_path.parent / "wan_prompts.txt"
    out_path.write_text("\n".join(wan_prompts), encoding="utf-8")
    print(f"Saved to: {out_path}")

    print("\nPreview (first 3):")
    for i, p in enumerate(wan_prompts[:3], 1):
        print(f"  [{i}] {p}")


if __name__ == "__main__":
    main()
