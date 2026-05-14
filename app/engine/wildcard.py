import re
import random
from pathlib import Path

MAX_DEPTH = 10
BLANK_TOKEN = "[blank]"

_FILE_WC_RE = re.compile(r'__([a-zA-Z0-9][a-zA-Z0-9\-]*(?:_[a-zA-Z0-9][a-zA-Z0-9\-]*)*)__')
_INLINE_WC_RE = re.compile(r'\{([^{}]+)\}')
_COND_BLOCK_RE = re.compile(r'\[@([^\]:]+):([^\]]*)\]')
_DIRECTIVE_RE = re.compile(r'^\[@(lock|seq):\s*([^\]]*)\]\s*(?:\n|$)', re.IGNORECASE | re.MULTILINE)
_NEG_BLOCK_RE = re.compile(r'\[NEG\](.*?)\[/NEG\]', re.DOTALL | re.IGNORECASE)


# ── Contradiction checker ─────────────────────────────────────────────────────

_CONTRADICTION_GROUPS: list[tuple[str, frozenset[str]]] = [
    ("camera direction", frozenset({
        "from_front", "from_behind", "from_side", "profile",
        "from_front_perspective", "from_behind_perspective",
    })),
    ("vertical angle", frozenset({
        "from_above", "overhead_view", "bird_s_eye_view", "low_angle", "from_below",
        "from_slightly_above", "slightly_overhead",
    })),
    ("clothing state", frozenset({
        "clothed", "nude", "naked", "fully_nude", "topless",
    })),
    ("sex position", frozenset({
        "doggy_style", "missionary_position", "cowgirl_position",
        "reverse_cowgirl_position", "piledriver_position", "mating_press",
        "prone_bone", "full_nelson", "face_down_ass_up", "wall_sex",
        "sitting_on_face", "straddling", "all_fours",
    })),
    ("body posture", frozenset({
        "standing", "kneeling", "sitting", "lying",
        "on_back", "on_stomach", "crouching",
    })),
]


def _prompt_tags(prompt: str) -> set[str]:
    return {p.strip().lower().replace(" ", "_").replace("-", "_") for p in prompt.split(",") if p.strip()}


_NUDE_SYNONYMS = frozenset({"nude", "naked", "fully_nude"})


def check_contradictions(prompt: str) -> list[str]:
    """Return a list of contradiction descriptions found in the prompt."""
    tags = _prompt_tags(prompt)
    issues = []
    for label, group in _CONTRADICTION_GROUPS:
        hits = sorted(group & tags)
        if len(hits) >= 2:
            # nude/naked/fully_nude are intentionally used together — not a contradiction
            if label == "clothing state" and frozenset(hits) <= _NUDE_SYNONYMS:
                continue
            issues.append(f"{label}: {', '.join(hits)}")
    return issues


# ─────────────────────────────────────────────────────────────────────────────

def _load_lines(wc_file: Path) -> list[str]:
    return [
        l.strip() for l in wc_file.read_text(encoding="utf-8").splitlines()
        if l.strip() and not l.strip().startswith("#")
    ]


def _available(lines: list[str], excluded: set[str]) -> list[str]:
    """Filter excluded entries and blank tokens for random/locked selection."""
    non_blank = [l for l in lines if l != BLANK_TOKEN]
    filtered = [l for l in non_blank if l not in excluded]
    return filtered if filtered else non_blank  # fallback: use all non-blank if everything is excluded


def _parse_range(range_str: str) -> set[int]:
    """Parse '1-3', '1,2,3', '1-3,5,7-9' into a set of 1-based indices."""
    indices: set[int] = set()
    for part in range_str.split(","):
        part = part.strip()
        if "-" in part:
            try:
                lo, hi = part.split("-", 1)
                indices.update(range(int(lo), int(hi) + 1))
            except ValueError:
                pass
        else:
            try:
                indices.add(int(part))
            except ValueError:
                pass
    return indices


def parse_template_directives(
    text: str,
) -> tuple[str, list[str], list[str], dict[str, bool], str]:
    """Extract [@lock: ...], [@seq: ...], and [NEG]...[/NEG] blocks from template text.

    Returns (clean_text, lock_names, seq_names, regen_flags, negative_text).
    regen_flags keys are lowercased wildcard names.
    """
    lock_names: list[str] = []
    seq_names: list[str] = []
    regen_flags: dict[str, bool] = {}

    # Extract [NEG]...[/NEG] block first
    negative_text = ""
    neg_match = _NEG_BLOCK_RE.search(text)
    if neg_match:
        negative_text = neg_match.group(1).strip()
        text = text[:neg_match.start()] + text[neg_match.end():]

    def _handle(m: re.Match) -> str:
        kind = m.group(1).lower()
        items = [i.strip() for i in m.group(2).split(",") if i.strip()]
        if kind == "lock":
            for item in items:
                if item.lower().endswith("(regen)"):
                    name = item[:-7].strip()
                    lock_names.append(name)
                    regen_flags[name.lower()] = True
                else:
                    lock_names.append(item)
        elif kind == "seq":
            seq_names.extend(items)
        return ""

    clean = _DIRECTIVE_RE.sub(_handle, text).strip("\n")
    return clean, lock_names, seq_names, regen_flags, negative_text


def build_template_directives(
    lock_names: list[str],
    seq_names: list[str],
    regen_flags: dict[str, bool],
    negative_text: str = "",
) -> str:
    """Build the [@lock: ...] / [@seq: ...] directive lines and [NEG] block for a template."""
    parts = []
    if lock_names:
        items = [
            f"{n}(regen)" if regen_flags.get(n.lower()) else n
            for n in lock_names
        ]
        parts.append(f"[@lock: {', '.join(items)}]")
    if seq_names:
        parts.append(f"[@seq: {', '.join(seq_names)}]")
    if negative_text.strip():
        parts.append(f"[NEG]\n{negative_text.strip()}\n[/NEG]")
    return "\n".join(parts)


def apply_conditional_blocks(text: str, prompt_num: int) -> str:
    """Resolve [@range: content] blocks for the given 1-based prompt number.

    Blocks whose range includes prompt_num are replaced with their content;
    others are replaced with an empty string. Content may include wildcards
    and inline choices — they are resolved by the normal passes afterward.
    """
    def _sub(m: re.Match) -> str:
        return m.group(2) if prompt_num in _parse_range(m.group(1)) else ""
    return _COND_BLOCK_RE.sub(_sub, text)


def resolve(
    template: str,
    wildcards_dir: Path,
    rng: random.Random,
    exclusions: dict[str, set[str]] | None = None,
    space_flags: dict[str, bool] | None = None,
) -> tuple[str, list[str]]:
    warnings: list[str] = []
    text = template

    # Pass 1: file wildcards __name__ (may introduce inline choices)
    for _ in range(MAX_DEPTH):
        m = _FILE_WC_RE.search(text)
        if not m:
            break
        name = m.group(1)
        wc_file = wildcards_dir / f"{name}.txt"
        if wc_file.exists():
            lines = _load_lines(wc_file)
            if lines:
                excl = exclusions.get(name, set()) if exclusions else set()
                replacement = rng.choice(_available(lines, excl))
                if replacement and space_flags and space_flags.get(name.lower()):
                    replacement += " "
            else:
                replacement = m.group(0)
                warnings.append(f"Wildcard file '{name}.txt' is empty")
        else:
            replacement = m.group(0)
            warnings.append(f"Wildcard file '{name}.txt' not found in {wildcards_dir}")
        text = text[: m.start()] + replacement + text[m.end() :]

    # Pass 2: inline choices {a|b|c}
    for _ in range(MAX_DEPTH):
        m = _INLINE_WC_RE.search(text)
        if not m:
            break
        options = [o.strip() for o in m.group(1).split("|")]
        replacement = rng.choice(options)
        text = text[: m.start()] + replacement + text[m.end() :]

    return text, warnings


def resolve_locks(
    lock_specs: dict[str, str],
    wildcards_dir: Path,
    rng: random.Random,
    exclusions: dict[str, set[str]] | None = None,
    space_flags: dict[str, bool] | None = None,
) -> tuple[dict[str, str], list[str]]:
    """Pick one value per locked wildcard name, resolved once for the whole batch.

    lock_specs maps wildcard name -> pinned value (empty string = pick from file).
    Returns (name -> resolved_value, warnings).
    """
    resolved: dict[str, str] = {}
    warnings: list[str] = []

    for name, override in lock_specs.items():
        if override.strip():
            resolved[name] = override.strip()
        else:
            wc_file = wildcards_dir / f"{name}.txt"
            if wc_file.exists():
                lines = _load_lines(wc_file)
                if lines:
                    excl = exclusions.get(name, set()) if exclusions else set()
                    val = rng.choice(_available(lines, excl))
                    if val and space_flags and space_flags.get(name.lower()):
                        val += " "
                    resolved[name] = val
                else:
                    resolved[name] = f"__{name}__"
                    warnings.append(f"Lock wildcard '{name}.txt' is empty")
            else:
                resolved[name] = f"__{name}__"
                warnings.append(f"Lock wildcard '{name}.txt' not found in {wildcards_dir}")

    return resolved, warnings


def load_sequential_lines(
    seq_names: list[str],
    wildcards_dir: Path,
    exclusions: dict[str, set[str]] | None = None,
) -> tuple[dict[str, list[str]], list[str]]:
    """Load ordered lines for each sequential wildcard name.

    Returns (name -> [line, ...], warnings).
    """
    seq_lines: dict[str, list[str]] = {}
    warnings: list[str] = []

    for name in seq_names:
        wc_file = wildcards_dir / f"{name}.txt"
        if wc_file.exists():
            lines = _load_lines(wc_file)
            if lines:
                excl = exclusions.get(name, set()) if exclusions else set()
                seq_lines[name] = [
                    "" if l == BLANK_TOKEN else l
                    for l in lines if l not in excl
                ]
            else:
                warnings.append(f"Sequential wildcard '{name}.txt' is empty")
        else:
            warnings.append(f"Sequential wildcard '{name}.txt' not found in {wildcards_dir}")

    return seq_lines, warnings


def generate_batch(
    template: str,
    count: int,
    wildcards_dir: Path,
    seed: int | None = None,
    locked_overrides: dict[str, str] | None = None,
    sequential_wildcards: list[str] | None = None,
    exclusions: dict[str, set[str]] | None = None,
    space_flags: dict[str, bool] | None = None,
    deduplicate: bool = True,
    negative_template: str | None = None,
) -> tuple[list[str], int, list[str], dict[str, str], list[str]]:
    """Generate count prompts from template.

    locked_overrides: {name: pinned_value} — same value used for every prompt.
      Empty string = auto-pick once from file.
    sequential_wildcards: [name, ...] — prompt N uses line N from the file,
      clamped to the last line once exhausted.
    negative_template: override for negative template; if None, uses embedded [NEG] block.

    Returns (prompts, seed_used, warnings, resolved_locks, negative_prompts).
    """
    # Parse embedded directives when no explicit config is provided
    template, dir_locks, dir_seqs, _, embedded_neg = parse_template_directives(template)
    if locked_overrides is None and dir_locks:
        locked_overrides = {name: "" for name in dir_locks}
    if sequential_wildcards is None and dir_seqs:
        sequential_wildcards = dir_seqs
    # Use explicit negative_template if provided, else fall back to embedded [NEG] block
    if negative_template is None:
        negative_template = embedded_neg

    if seed is None:
        seed = random.randint(0, 2**32 - 1)

    rng = random.Random(seed)
    all_warnings: list[str] = []

    # Step 1: resolve locked wildcards once and bake into template
    resolved_locks: dict[str, str] = {}
    if locked_overrides:
        resolved_locks, lock_warnings = resolve_locks(locked_overrides, wildcards_dir, rng, exclusions=exclusions, space_flags=space_flags)
        all_warnings.extend(lock_warnings)

    locked_template = template
    for name, value in resolved_locks.items():
        locked_template = re.sub(
            rf'(?i)__{re.escape(name)}__',
            lambda m, v=value: v,
            locked_template,
        )

    # Step 2: pre-load sequential wildcard lines (deterministic, no RNG used)
    seq_lines: dict[str, list[str]] = {}
    if sequential_wildcards:
        seq_lines, seq_warnings = load_sequential_lines(sequential_wildcards, wildcards_dir, exclusions=exclusions)
        all_warnings.extend(seq_warnings)

    # Step 3: generate prompts, applying sequential substitution per prompt index
    results: list[str] = []
    max_attempts = count if not deduplicate else count * 3

    for _ in range(max_attempts):
        if len(results) >= count:
            break

        prompt_idx = len(results)

        # Substitute sequential wildcards for this prompt slot
        seq_template = locked_template
        for name, lines in seq_lines.items():
            value = lines[min(prompt_idx, len(lines) - 1)]
            if value and space_flags and space_flags.get(name.lower()):
                value += " "
            seq_template = re.sub(
                rf'(?i)__{re.escape(name)}__',
                lambda m, v=value: v,
                seq_template,
            )

        # Resolve conditional blocks [@range: content] using 1-based prompt number
        seq_template = apply_conditional_blocks(seq_template, prompt_idx + 1)

        prompt, warnings = resolve(seq_template, wildcards_dir, rng, exclusions=exclusions, space_flags=space_flags)
        all_warnings.extend(warnings)
        for issue in check_contradictions(prompt):
            all_warnings.append(f"Prompt {prompt_idx + 1} contradiction — {issue}")
        if not deduplicate or prompt not in results:
            results.append(prompt)

    if deduplicate and len(results) < count:
        all_warnings.append(
            f"Only {len(results)} unique prompt(s) generated (requested {count}) — "
            "wildcard variety too low to fill the batch without duplicates."
        )

    # Deduplicate warnings while preserving order
    seen: set[str] = set()
    unique_warnings: list[str] = []
    for w in all_warnings:
        if w not in seen:
            seen.add(w)
            unique_warnings.append(w)

    # Generate negative prompts using the same seed (after positive generation)
    negative_prompts: list[str] = []
    if negative_template and negative_template.strip():
        neg_rng = random.Random(seed)
        for i in range(count):
            neg_text = apply_conditional_blocks(negative_template, i + 1)
            neg_prompt, neg_warns = resolve(neg_text, wildcards_dir, neg_rng, exclusions=exclusions, space_flags=space_flags)
            # Normalize: collapse whitespace/newlines, strip leading/trailing commas and spaces
            neg_prompt = ", ".join(p.strip() for p in neg_prompt.replace("\n", ",").split(",") if p.strip())
            negative_prompts.append(neg_prompt)
            for w in neg_warns:
                msg = f"Neg: {w}"
                if msg not in seen:
                    seen.add(msg)
                    unique_warnings.append(msg)

    return results, seed, unique_warnings, resolved_locks, negative_prompts
