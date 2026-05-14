"""
wan_gen.py  —  Generate WAN motion prompts for a folder of images using a local vision model.

Uses the OpenAI-compatible chat/completions API — works with LM Studio, Ollama (/v1), etc.

Usage:
    python wan_gen.py <folder> [options]

Options:
    --model       Model name as shown in LM Studio (default: local-model)
    --host        API host (default: http://localhost:1234)
    --model-type  wan (short motion tags) or ltx (cinematic prose). Default: wan
    --dry-run     Print prompts without writing files
    --overwrite   Overwrite existing output files if present
    --prefix      Image filename prefix filter (e.g. gen__)
    --batch       Process all subfolders inside <folder>

Examples:
    python wan_gen.py "H:/ComfyUI/output/MyScene/123456"
    python wan_gen.py "H:/ComfyUI/output/MyScene" --batch --overwrite
    python wan_gen.py "H:/ComfyUI/output/MyScene/123456" --model-type ltx --dry-run
"""

import argparse
import base64
import json
import pathlib
import sys
import textwrap
import time

try:
    import httpx
except ImportError:
    import urllib.request, urllib.error
    httpx = None

try:
    from PIL import Image as _PIL
except ImportError:
    _PIL = None

try:
    import sys as _sys
    _sys.path.insert(0, str(pathlib.Path(__file__).parent))
    from app.engine.wildcard import generate_batch as _generate_batch
    from app.engine.wildcard import parse_template_directives as _parse_directives
    _WILDCARD_ENGINE = True
except Exception:
    _WILDCARD_ENGINE = False

IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
CHAT_ENDPOINT = "/v1/chat/completions"

SYSTEM_PROMPT = """You write motion prompts for AI image-to-video models.
The image is a still frame — write the motion that should be animated FROM this pose.
Each clip is exactly 5 seconds: describe one simple, continuous motion that fits that duration.
Output ONE line, under 15 words, plain comma-separated phrases.
Describe body movement and, when the action is out of frame, add one camera motion (pan down, pan up, zoom in, etc.).
Rules: no brackets, no underscores, no appearance descriptions, no "body reaction:" prefix."""

LTX_SYSTEM_PROMPT = """You write video generation prompts for LTX-Video, a multimodal video model with a long-context tokenizer that uses interleaved attention.
The image is a still frame — your output drives what is animated FROM this pose. Each clip is exactly 5 seconds. No timestamps. Output only plain English prose.

Write one continuous paragraph structured in two parts:
First, describe the subject's appearance, pose, composition, and setting in concise natural language.
Then describe every moving body part, composition change, and manipulation that naturally evolves from that initial frame.

End with one sentence of audio: body sounds, environment sounds, or foley paired with the motion. If no natural sound fits, name a fitting music genre and mood instead.

Rules: no section labels, no bullet points, no booru tags, no underscores, no timestamps, no meta-commentary. Continuous natural prose only."""

NEG_PROMPT = (
    "worst quality, low quality, blurry, artifacts, watermark, text, static, "
    "no motion, frozen frame, jerky motion, morphing, bad anatomy, deformed, "
    "distorted, extra limbs, extra heads, multiple heads, multiple faces"
)

LTX_NEG_PROMPT = (
    "morphing, distortion, warping, flicker, jitter, blur, artifacts, glitch, "
    "overexposure, watermark, text, worst quality, low quality"
)

# Load scene-specific motion hints from data/prompt_hints.json.
# Edit that file to add hint text for any scene type — no code changes needed.
try:
    _HINT_MAP: dict[str, str] = json.loads(
        (pathlib.Path(__file__).parent / "data" / "prompt_hints.json").read_text(encoding="utf-8")
    )
except Exception:
    _HINT_MAP = {}

# Maps booru framing tags to plain-English descriptions passed as camera context to the model.
_FRAMING_MAP = {
    "upper_body":           "upper body shot (waist up)",
    "lower_body":           "lower body shot (waist down)",
    "full_body":            "full body shot",
    "close-up":             "close-up shot",
    "close_up":             "close-up shot",
    "from_above":           "shot from above",
    "from_slightly_above":  "shot from slightly above",
    "from_below":           "shot from below",
    "from_slightly_below":  "shot from slightly below",
    "from_front":           "front-facing shot",
    "from_behind":          "shot from behind",
    "from_side":            "side-angle shot",
    "profile":              "profile shot",
    "pov":                  "POV shot",
    "facing_viewer":        "facing camera",
}

# Root keywords for clothing detection — any booru tag *containing* one of these is treated as
# a clothing tag. Short roots are intentional: catches compound tags like "skinny_jeans" (→ jeans),
# "ribbed_tank_top" (→ tank), "chambray_shirt" (→ shirt), "thigh_highs" (→ thigh_high).
_CLOTHING_KEYWORDS = frozenset({
    # tops
    "shirt", "blouse", "sweater", "jacket", "coat", "hoodie", "cardigan",
    "turtleneck", "camisole", "bustier", "corset", "bra", "bikini",
    "tank_top", "tube_top", "crop_top", "halter",
    # bottoms
    "pants", "jeans", "skirt", "shorts", "leggings", "trousers", "sweatpants",
    "underwear", "panties", "thong", "g-string", "lingerie",
    # full garments
    "dress", "nightgown", "robe", "kimono", "swimsuit", "negligee", "bodysuit", "jumpsuit",
    # hosiery/footwear
    "stockings", "thigh_high", "pantyhose", "heels", "shoes", "boots", "socks",
    # state words (exact enough that substring is safe)
    "clothed", "topless", "bottomless", "shirtless", "nude", "naked",
})

# Camera/composition/quality tags that must be stripped from booru before sending to the model.
_BOORU_STOP_TAGS = frozenset({
    "pov", "from_above", "from_below", "from_slightly_above", "from_slightly_below",
    "from_front", "from_behind", "from_side", "from_left", "from_right",
    "upper_body", "lower_body", "full_body", "profile", "close-up", "close_up",
    "slight_angle", "facing_viewer",
    "looking_at_viewer", "looking_up_at_viewer", "looking_down_at_viewer",
    "looking_back_at_viewer",
    "detailed_background", "4k", "photorealistic", "high_resolution",
    "skin_imperfections", "pores", "realistic_skin_texture", "best_quality",
    "sensual", "flirtatious", "intimate",
})

# Strip character boilerplate up to and including any of these anchors
_BOORU_CHAR_ANCHORS = ("solo,",)

# Maps template name prefixes to plain-English action descriptions used when
# PNG metadata is available but the exact booru prompt cannot be reconstructed.
# Add entries here to match your own template naming convention.
_TEMPLATE_ACTIONS: dict[str, str] = {
    # Examples — edit to match your templates:
    # "Portrait_Studio":   "a person posing in a studio setting",
    # "Fashion_Sequence":  "a person changing outfits, garments coming off and on",
}


def _clean_booru(booru: str) -> str:
    """Strip character boilerplate and camera/quality tags from a raw booru prompt string."""
    for anchor in _BOORU_CHAR_ANCHORS:
        idx = booru.find(anchor)
        if idx != -1:
            booru = booru[idx + len(anchor):].strip().lstrip(",").strip()
            break
    result = []
    for tag in booru.split(","):
        tag = tag.strip()
        if not tag:
            continue
        if tag.lower() in _BOORU_STOP_TAGS:
            break
        result.append(tag)
    return ", ".join(result)


def _extract_framing(booru: str) -> str:
    """Return a plain-English camera framing description from raw booru tags, or empty string."""
    for tag in booru.split(","):
        t = tag.strip().lower()
        if t in _FRAMING_MAP:
            return _FRAMING_MAP[t]
    return ""


def _clothing_diff(current_booru: str, next_booru: str) -> tuple[list[str], list[str]]:
    """Return (removed, added) clothing tag lists between two raw booru strings."""
    def _clothes(b: str) -> set[str]:
        result = set()
        for tag in b.split(","):
            t = tag.strip().lower()
            if t and any(kw in t for kw in _CLOTHING_KEYWORDS):
                result.add(t)
        return result
    cur = _clothes(current_booru)
    nxt = _clothes(next_booru)
    return sorted(cur - nxt), sorted(nxt - cur)


def _detect_scene_key(action: str, booru: str) -> str:
    """Match action/booru text against hint keys in prompt_hints.json.

    Checks if any key from the hint map appears as a word in the combined
    action + booru string. Edit data/prompt_hints.json to add or change hints.
    """
    combined = (action + " " + booru).lower()
    for key in _HINT_MAP:
        if key.lower() in combined:
            return key
    return ""


def _extract_scene_info(img_path: pathlib.Path, img_index: int = 0) -> tuple[str, str]:
    """Return (template_action, image_prompt) from PNG metadata.

    img_index: 1-based position in sorted image list.

    Primary path (requires wildcard engine): re-runs the PromptGenie batch
    chain from the PNG metadata with the original seed to reproduce the exact
    booru prompt used to generate this specific image.

    Fallback: returns the template action description from _TEMPLATE_ACTIONS.
    """
    if _PIL is None or img_path.suffix.lower() != ".png":
        return "", ""
    try:
        img = _PIL.open(img_path)
        raw = img.info.get("prompt", "")
        if not raw:
            return "", ""
        data = json.loads(raw)

        # ── Build the ordered PromptGenie batch chain ──────────────────────
        pg = {}
        for nid, node in data.items():
            if node.get("class_type") == "PromptGenie":
                inp = node.get("inputs") or {}
                t_ref = inp.get("template")
                lv_ref = inp.get("locked_values")
                seed_ref = inp.get("seed")
                pg[nid] = {
                    "count":    int(inp.get("count", 1)),
                    "tnode":    t_ref[0] if isinstance(t_ref, list) else None,
                    "from":     lv_ref[0] if isinstance(lv_ref, list) else None,
                    "wc_dir":   inp.get("wildcards_dir", ""),
                    "seed_ref": seed_ref,
                }

        successor = {info["from"]: nid for nid, info in pg.items() if info["from"]}
        root = next((nid for nid, info in pg.items() if info["from"] is None), None)

        # ── Try to reproduce the exact prompt via the wildcard engine ──────
        booru = ""
        action = ""

        if _WILDCARD_ENGINE and root and img_index > 0:
            seed_ref = pg[root]["seed_ref"]
            if isinstance(seed_ref, list):
                seed_node_id = seed_ref[0]
                seed = int((data.get(seed_node_id, {}).get("inputs") or {}).get("seed", 0))
            else:
                seed = int(seed_ref or 0)

            inherited_locks: dict = {}
            cumulative = 0
            cur = root
            while cur is not None:
                info = pg[cur]
                tnode_id = info["tnode"]
                tname_raw = ""
                template_text = ""
                if tnode_id and tnode_id in data:
                    tnode_inp = data[tnode_id].get("inputs") or {}
                    tname_raw = tnode_inp.get("template_name", "")
                    data_dir_raw = tnode_inp.get("data_dir", "")
                    if data_dir_raw:
                        tmpl_dir = pathlib.Path(data_dir_raw) / "templates"
                        for tf in tmpl_dir.glob("*.json"):
                            try:
                                rec = json.loads(tf.read_text(encoding="utf-8"))
                                if rec.get("name") == tname_raw:
                                    template_text = rec.get("template", "")
                                    break
                            except Exception:
                                pass

                wc_dir = pathlib.Path(info["wc_dir"]) if info["wc_dir"] else pathlib.Path("data/wildcards")
                _, dir_locks, _, _, _ = _parse_directives(template_text)
                locked_overrides = {n: inherited_locks.get(n, "") for n in (dir_locks or [])}

                prompts, _, _, resolved_locks, _ = _generate_batch(
                    template=template_text,
                    count=info["count"],
                    wildcards_dir=wc_dir,
                    seed=seed,
                    locked_overrides=locked_overrides or None,
                )
                inherited_locks.update(resolved_locks or {})

                start = cumulative + 1
                cumulative += info["count"]

                if img_index <= cumulative:
                    local_idx = img_index - start
                    booru = prompts[local_idx] if local_idx < len(prompts) else ""
                    if tname_raw in _TEMPLATE_ACTIONS:
                        action = _TEMPLATE_ACTIONS[tname_raw]
                    break

                cur = successor.get(cur)

        # ── Fallback: template-category action only ────────────────────────
        if not action and root:
            cur = root
            cumulative = 0
            while cur is not None:
                cumulative += pg[cur]["count"]
                if img_index <= cumulative or img_index == 0:
                    tnode_id = pg[cur]["tnode"]
                    if tnode_id and tnode_id in data:
                        tname = (data[tnode_id].get("inputs") or {}).get("template_name", "")
                        if tname in _TEMPLATE_ACTIONS:
                            action = _TEMPLATE_ACTIONS[tname]
                    break
                cur = successor.get(cur)

        return action, booru
    except Exception:
        pass
    return "", ""


def _img_to_b64(img_path: pathlib.Path) -> str:
    return base64.b64encode(img_path.read_bytes()).decode("utf-8")


def _generate(host: str, model: str, image_b64: str, action: str, booru: str,
              next_booru: str = "", model_type: str = "wan") -> str:
    """Call OpenAI-compatible chat completions with a vision message."""
    is_ltx = model_type.lower() == "ltx"
    sys_prompt = LTX_SYSTEM_PROMPT if is_ltx else SYSTEM_PROMPT
    max_tok = 400 if is_ltx else 80
    temp = 0.70 if is_ltx else 0.65

    # Look up a scene-specific hint to keep the model on task
    scene_key = _detect_scene_key(action, booru)
    hint_text = _HINT_MAP.get(scene_key, "") if scene_key else ""
    hint = (" " + hint_text) if hint_text else ""

    if booru and next_booru:
        current_tags = _clean_booru(booru)
        next_tags = _clean_booru(next_booru)
        framing = _extract_framing(booru)
        framing_hint = f"\nCurrent framing: {framing}" if framing else ""

        removed, added = _clothing_diff(booru, next_booru)
        if removed:
            removal_str = " and ".join(t.replace("_", " ") for t in removed)
            diff_line = f"\nClothing removed in this clip: {removal_str}"
        else:
            diff_line = ""

        if is_ltx:
            instruction = (
                f"Current frame: {current_tags}\n"
                f"Next frame: {next_tags}{framing_hint}{diff_line}\n\n"
                f"Write a cinematic video prompt describing ONLY the clothing transition — "
                f"the specific garment(s) being changed and how. "
                f"Include a camera move and lighting note. "
                f"Do not describe the result state — describe the act of changing."
            )
        else:
            instruction = (
                f"Current frame: {current_tags}\n"
                f"Next frame: {next_tags}{framing_hint}{diff_line}\n\n"
                f"Write the motion for ONLY this clothing change — "
                f"the specific garment(s) and the exact movement used to change them. "
                f"Do not describe what the result looks like — describe the act. "
                f"Add a camera movement if needed to keep the action in frame."
            )
    elif booru:
        tags = _clean_booru(booru)
        framing = _extract_framing(booru)
        framing_hint = f"\nCurrent framing: {framing}" if framing else ""
        if is_ltx:
            instruction = (
                f"Image tags: {tags}{framing_hint}\n\n"
                f"Write a cinematic video prompt animating FROM this pose. "
                f"If the image already shows the action, describe its rhythm and continuation. "
                f"If the image doesn't yet show the action described in the tags, describe the motion to get there. "
                f"Include a camera direction and lighting note. 3-5 sentences.{hint}"
            )
        else:
            instruction = (
                f"Image tags: {tags}{framing_hint}\n\n"
                f"Write the motion to animate FROM this pose. "
                f"If the image already shows the action, describe its rhythm and continuation. "
                f"If the image doesn't yet show the action, describe the motion to get there. "
                f"If the framing doesn't show where the action is happening, add a camera pan or zoom. "
                f"Plain words only, no brackets.{hint}"
            )
    elif action:
        if is_ltx:
            instruction = (
                f"Scene: {action}\n\n"
                f"Write a cinematic video prompt animating FROM this pose. "
                f"Describe the body movement, include a camera direction, and note the lighting. 3-5 sentences.{hint}"
            )
        else:
            instruction = (
                f"Scene: {action}\n\n"
                f"Write the motion to animate FROM this pose: what should move, "
                f"which direction, what rhythm or pace. Plain words only, no brackets.{hint}"
            )
    else:
        if is_ltx:
            instruction = (
                "Write a cinematic video prompt animating FROM this pose. "
                "Describe the body movement and rhythm, include a camera direction, and note the lighting. 3-5 sentences."
            )
        else:
            instruction = (
                "Write the motion to animate FROM this pose: what body parts should move, "
                "which direction, and at what rhythm or pace. Plain words only, no brackets."
            )

    user_parts = [
        {"type": "text", "text": instruction},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
    ]

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_parts},
        ],
        "max_tokens": max_tok,
        "temperature": temp,
        "stream": False,
    }

    url = host.rstrip("/") + CHAT_ENDPOINT

    if httpx:
        resp = httpx.post(url, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
    else:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read())

    choices = data.get("choices", [])
    if not choices:
        raise ValueError(f"Empty choices in response: {json.dumps(data)[:300]}")
    return choices[0]["message"]["content"].strip()


def _clean(text: str, model_type: str = "wan") -> str:
    """Strip quotes, bracket notation, and boilerplate prefixes.

    WAN mode: collapses to a single line, strips trailing period, replaces underscores.
    LTX mode: preserves multi-line prose, keeps sentence punctuation.
    """
    import re
    is_ltx = model_type.lower() == "ltx"

    text = text.strip().strip('"').strip("'")

    if is_ltx:
        first, *rest = text.splitlines()
        for pfx in ("body reaction:", "body_reaction:", "motion:", "action:", "prompt:"):
            if first.lower().startswith(pfx):
                first = first[len(pfx):].strip()
        text = " ".join(s.strip() for s in [first] + rest if s.strip())
        text = text.replace("[", "").replace("]", "")
        text = re.sub(r"\s{2,}", " ", text).strip()
        check = text.lower()
    else:
        text = text.splitlines()[0].strip()
        if text.endswith("."):
            text = text[:-1]
        for pfx in ("body reaction:", "body_reaction:", "motion:", "action:", "prompt:"):
            if text.lower().startswith(pfx):
                text = text[len(pfx):].strip()
        text = text.replace("[", "").replace("]", "")
        text = text.replace("_", " ")
        text = re.sub(r"\s{2,}", " ", text).strip().strip(",").strip()
        check = text.lower()

    _no_motion = ("no motion", "no motion detected", "static", "no movement", "cannot determine")
    if any(check.startswith(p) for p in _no_motion):
        return ""
    return text


def process_folder(folder: pathlib.Path, model: str, host: str,
                   dry_run: bool, overwrite: bool, prefix: str,
                   model_type: str = "wan") -> None:
    suffix = "ltx" if model_type.lower() == "ltx" else "wan"
    wan_out = folder / f"gen__{suffix}.txt"
    neg_out = folder / f"gen__{suffix}_neg.txt"

    if wan_out.exists() and not overwrite:
        print(f"  Skipping {folder.name} — {wan_out.name} exists (use --overwrite to replace)")
        return

    images = sorted(
        f for f in folder.iterdir()
        if f.suffix.lower() in IMG_EXTS and (not prefix or f.name.startswith(prefix))
    )

    if not images:
        print(f"  No images found in {folder.name}")
        return

    print(f"\n{'='*60}")
    print(f"Folder : {folder.name}")
    print(f"Images : {len(images)}")
    print(f"Model  : {model}")
    print(f"Type   : {model_type.upper()}")
    print(f"{'='*60}")
    neg = LTX_NEG_PROMPT if model_type.lower() == "ltx" else NEG_PROMPT

    wan_lines = []
    neg_lines = []

    for i, img_path in enumerate(images, 1):
        action, booru = _extract_scene_info(img_path, img_index=i)

        # Look ahead one image for clothing-change sequences to describe the transition.
        next_booru = ""
        if "strip" in action.lower() or "fashion" in action.lower():
            if i < len(images):
                next_action, nb = _extract_scene_info(images[i], img_index=i + 1)
                if nb:
                    next_booru = nb

        print(f"  [{i:>3}/{len(images)}] {img_path.name}", end="", flush=True)

        if dry_run:
            print(" (dry-run, skipping)")
            wan_lines.append(f"[dry-run] {img_path.name}")
            neg_lines.append(neg)
            continue

        try:
            t0 = time.time()
            b64 = _img_to_b64(img_path)
            response = _generate(host, model, b64, action, booru,
                                 next_booru=next_booru, model_type=model_type)
            response = _clean(response, model_type=model_type)
            if not response:
                response = action
            elapsed = time.time() - t0
            print(f"  ({elapsed:.1f}s)")
            print(f"        → {textwrap.shorten(response, 100)}")
            wan_lines.append(response)
            neg_lines.append(neg)
        except Exception as e:
            print(f"  ERROR: {e}")
            wan_lines.append(f"[error] {img_path.name}")
            neg_lines.append(neg)

    if not dry_run:
        wan_out.write_text("\n".join(wan_lines), encoding="utf-8")
        neg_out.write_text("\n".join(neg_lines), encoding="utf-8")
        print(f"\n  Written: {wan_out.name} ({len(wan_lines)} lines)")
        print(f"  Written: {neg_out.name}")
    else:
        print(f"\n  [dry-run] Would write {len(wan_lines)} lines to {wan_out.name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", help="Folder containing images (or parent folder with --batch)")
    parser.add_argument("--model", default="local-model", help="Model name (default: local-model)")
    parser.add_argument("--host", default="http://localhost:1234", help="API host (default: http://localhost:1234 for LM Studio)")
    parser.add_argument("--dry-run", action="store_true", help="Print without writing files")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing output files")
    parser.add_argument("--prefix", default="", help="Image filename prefix filter (e.g. gen__)")
    parser.add_argument("--batch", action="store_true", help="Process all subfolders inside <folder>")
    parser.add_argument("--model-type", default="wan", choices=["wan", "ltx"],
                        help="Prompt style: wan (short motion tags) or ltx (cinematic prose). Default: wan")
    args = parser.parse_args()

    root = pathlib.Path(args.folder)
    if not root.exists():
        print(f"Error: folder not found: {root}")
        sys.exit(1)

    if args.batch:
        subfolders = sorted(d for d in root.iterdir() if d.is_dir())
        if not subfolders:
            print(f"No subfolders found in {root}")
            sys.exit(1)
        print(f"Batch mode: {len(subfolders)} subfolders")
        for sub in subfolders:
            process_folder(sub, args.model, args.host, args.dry_run, args.overwrite, args.prefix,
                           model_type=args.model_type)
    else:
        process_folder(root, args.model, args.host, args.dry_run, args.overwrite, args.prefix,
                       model_type=args.model_type)

    print("\nDone.")


if __name__ == "__main__":
    main()
