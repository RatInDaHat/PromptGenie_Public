# PromptGenie

A dark-themed desktop app for generating batches of AI image/video prompts with wildcard support, a reusable phrase library, and full template management. Built for ComfyUI workflows where you need 10–20 related but varied prompts per session.

Also ships a **ComfyUI custom node** that runs the same wildcard engine inside ComfyUI, and a **WAN/LTX motion prompt generator** (`wan_gen.py`) that uses a local vision model to write video prompts from your generated images.

---

## Features

### Wildcard Engine
- **Inline choices** — `{option1|option2|option3}` picks one randomly per prompt
- **File wildcards** — `__filename__` loads a `.txt` file and picks a random line
- **Nesting** — wildcards can contain other wildcards, resolved recursively
- **Locked wildcards** — pin a wildcard to the same value across the entire batch (e.g., keep clothing consistent across all scenes)
  - **Regen mode** — per-lock checkbox to re-pick from the file on every Generate click (last resolved value is shown greyed out for reference)
- **Sequential wildcards** — wildcard values advance in order across prompts (prompt 1 → line 1, prompt 2 → line 2, clamped at end of list); token matching is case-insensitive
- **Blank token** — add `[blank]` as a phrase in any sequential wildcard file to produce an empty slot for that prompt position; blank entries are skipped in random/locked selection
- **Exclusions** — mark individual entries as excluded; skipped during random and locked selection, with bulk **Exclude All** / **Exclude None** via right-click menu
- **Space flags** — per-category ⎵ toggle appends a trailing space to all resolved values from that wildcard, useful when concatenating multiple wildcards without a separator
- **Conditional blocks** — `[@range: content]` includes content only on specific prompt numbers; supports ranges and lists (`[@1-3: in the rain]`, `[@1,3,5: at night]`)
- **Adjacent wildcard support** — `__tag1____tag2__` correctly resolves both tokens (no space needed between them)
- **Negative prompt block** — wrap content in `[NEG]...[/NEG]` to split it into a separate negative prompt output

### Phrase Library
- Categorized phrase browser with 12 built-in categories (sentence-style and tag-style)
- Add, edit, delete, and reorder phrases via drag-and-drop or ↑/↓ buttons
- Auto-syncs from matching wildcard `.txt` files when you switch categories
- **Bidirectional sync** — Sync ↓ button pulls new entries from the wildcard file and writes all library phrases back to it; the two sources are always kept in agreement
- Creating a new phrase category automatically creates the matching wildcard `.txt` file and updates all wildcard pickers
- Double right-click or middle-click to instantly exclude/include a phrase
- Right-click context menu: Edit, Delete, Exclude/Include, Exclude All, Exclude None
- **Blank phrase** — Add [blank] button inserts the `[blank]` sequential token into any category
- Excluded items shown in muted rose — still visible but clearly inactive

### Template Editor
- Multi-line template editor
- Quick-insert buttons for `{a|b|c}`, `__wildcard__`, and `[@1-3:]` conditional block syntax
- Wildcard file picker — browse available `.txt` files and insert with one click
- **Lock panel** — add any wildcard as a locked entry directly from the template panel; each row shows the pinned value and a Regen checkbox
- **Sequential panel** — designate wildcards to advance line-by-line across the batch
- Save and load named templates; sortable by most recent or alphabetical
- Count spinner (1–50 prompts per batch)
- All lock, regen, and sequential settings are saved and restored on relaunch

### Output
- Scrollable output panel showing all generated prompts
- Seed display — every generation records its seed so results are reproducible
- Lock seed to regenerate the exact same batch
- Optional prompt numbering toggle
- Copy all prompts to clipboard or save to a `.txt` file

### General
- Fully dark-themed UI (CustomTkinter)
- Resizable panel dividers
- Window position and size restored on relaunch (opens on the same monitor it was closed on)
- All popup windows (dialogs, template manager) open centered over the main window
- All user data (phrases, settings, templates) persists between sessions

---

## Installation

**Requirements:** Python 3.10+

```bash
pip install -r requirements.txt
```

```bash
python main.py
```

---

## ComfyUI Node

The wildcard engine ships as a ComfyUI custom node. Install it once and use PromptGenie templates directly inside your ComfyUI workflows.

### Install

```bash
python comfyui_node/install.py "C:/path/to/ComfyUI/custom_nodes"
```

This copies the node, engine, and web extension into ComfyUI. Restart ComfyUI to load it.

### Available Nodes

| Node | Purpose |
|---|---|
| `PromptGenie` | Generate a batch of prompts from a template + wildcard engine |
| `PromptGenieLoadTemplate` | Load a named template from the templates folder |
| `PromptGenieResolve` | Re-resolve a batch using inherited locked values from a prior node |
| `PromptGenieConcat` | Merge up to 8 prompt batches into one list |
| `PromptGeniePair` | Pair prompts with locked values for chaining across nodes |
| `PromptGenieUnpack` | Unpack a paired batch back into prompts + locked values |
| `PromptGenieI2VSource` | Read booru prompt and scene metadata from PNG image metadata |
| `PromptGenieReadFile` | Read a text file line-by-line into a prompt list |
| `PromptGenieWANCollect` | Collect WAN/LTX motion prompt files from a folder |
| `PromptGenieCounter` | Count items in a list |
| `PromptGenieFolderPicker` | UI widget for selecting a folder path |

---

## WAN / LTX Motion Prompt Generator

`wan_gen.py` uses a local vision model (LM Studio, Ollama, or any OpenAI-compatible API) to analyze your generated images and write motion prompts for WAN or LTX-Video.

### Usage

```bash
# Single folder
python wan_gen.py "H:/ComfyUI/output/MyScene/123456"

# Batch all subfolders
python wan_gen.py "H:/ComfyUI/output/MyScene" --batch --overwrite

# LTX-Video cinematic prose mode
python wan_gen.py "H:/ComfyUI/output/MyScene/123456" --model-type ltx

# Dry run (preview without writing)
python wan_gen.py "H:/ComfyUI/output/MyScene/123456" --dry-run
```

### Options

| Option | Default | Description |
|---|---|---|
| `--model` | `local-model` | Model name as shown in LM Studio |
| `--host` | `http://localhost:1234` | API host (LM Studio default) |
| `--model-type` | `wan` | `wan` = short motion tags; `ltx` = cinematic prose paragraph |
| `--dry-run` | off | Print prompts without writing files |
| `--overwrite` | off | Overwrite existing output files |
| `--prefix` | none | Filter images by filename prefix (e.g. `gen__`) |
| `--batch` | off | Process all subfolders inside the given folder |

### Output files

Each processed folder gets two files:
- `gen__wan.txt` / `gen__ltx.txt` — one motion prompt per line, one per image
- `gen__wan_neg.txt` / `gen__ltx_neg.txt` — matching negative prompts

### Scene-aware hints

When image metadata contains PromptGenie template info, the generator reads the original booru tags and injects scene-specific motion hints to keep the model on task. **Clothing transition sequences** use lookahead — the generator reads the next image's tags to describe the exact wardrobe change rather than a generic motion.

Motion hint text lives in `data/prompt_hints.json` — edit it freely to tune how the model is prompted for each scene type without touching the code:

```json
{
  "walk": "The subject must be visibly walking — legs stepping forward in a natural alternating rhythm...",
  "dance": "The subject must be actively dancing — body swaying, arms moving expressively...",
  "fight": "The subject must be in active combat motion — striking, blocking, dodging...",
  ...
}
```

Add any key you need — the key name is matched against detected scene tags, and the value is appended to the model's instruction for that clip.

---

## Project Structure

```
PromptGenie/
├── main.py                    # Entry point
├── wan_gen.py                 # WAN/LTX motion prompt generator
├── requirements.txt
├── app/
│   ├── engine/
│   │   └── wildcard.py        # Wildcard engine (no UI imports — ComfyUI node ready)
│   ├── ui/
│   │   ├── app_window.py      # Root window, 3-column resizable layout
│   │   ├── library_panel.py   # Phrase library browser
│   │   ├── template_panel.py  # Template editor + wildcard controls
│   │   ├── output_panel.py    # Generated output + seed controls
│   │   ├── template_manager.py # Saved template browser
│   │   └── utils.py           # Shared UI helpers (centering, dialogs)
│   ├── library.py             # Phrase library CRUD + exclusions + space flags
│   ├── settings.py            # App settings persistence
│   ├── template_library.py    # Template save/load
│   └── exporter.py            # Save prompts to file
├── comfyui_node/
│   ├── __init__.py            # All ComfyUI node classes
│   ├── wildcard.py            # Engine copy (installed into ComfyUI)
│   ├── install.py             # Installer script
│   └── web/                   # ComfyUI frontend extension
└── data/
    ├── phrases.json           # Phrase library (committed as default dataset)
    ├── prompt_hints.json      # Motion hint text by scene type (edit to tune)
    ├── templates/             # Saved templates (.json, one per file)
    └── wildcards/             # Wildcard .txt files (one entry per line)
```

---

## Wildcard Syntax

| Syntax | Behavior |
|---|---|
| `{a\|b\|c}` | Pick one option randomly per prompt |
| `__filename__` | Pick one line randomly from `wildcards/filename.txt` |
| Nesting | `{__colors__\|vivid __lighting__}` — resolved recursively |
| `[@1-3: text]` | Include `text` only on prompts 1, 2, and 3 |
| `[@1,3,5: text]` | Include `text` only on prompts 1, 3, and 5 |
| `[@2-4,6: text]` | Include `text` on prompts 2, 3, 4, and 6 |
| `[@lock: name(regen), ...]` | Lock directive — pin wildcards for the batch; `(regen)` re-picks each run |
| `[NEG]...[/NEG]` | Negative prompt block — split into a separate negative output |

**Example template:**
```
[@lock: character_tag(regen), lighting_tag]
[NEG]bad anatomy, blurry, watermark[/NEG]
__character_tag__, __action_tag__[@1-5: running fast], __camera_tag__, __lighting_tag__, __style_tag__
```

---

## Wildcard Files

Wildcard files live in `data/wildcards/` — one value per line, lines starting with `#` are treated as comments. Add `[blank]` as a line to produce an empty slot in sequential mode.

The phrase library auto-syncs with matching wildcard files (e.g., the `Style_Tag` category syncs from `style_tag.txt`). Creating a new phrase category creates the matching `.txt` file automatically. You can add your own `.txt` files and they'll appear in all wildcard pickers.

---

## Conditional Blocks

Use `[@range: content]` anywhere in your template to include content only on specific prompt numbers:

```
a woman walking[@1-3: in the rain][@4-6: in bright sunlight], __style_tag__
```

Prompts 1–3 get "in the rain", prompts 4–6 get "in bright sunlight", the rest get neither. The content inside the block is fully resolved (wildcards and inline choices work inside it).

---

## Sequential Wildcards

Sequential wildcards step through their file line by line — prompt 1 uses line 1, prompt 2 uses line 2, and so on. When the file runs out of lines the last line repeats.

Add `[blank]` as a line to produce an empty value for that prompt slot (useful when a descriptor only applies to some scenes). Blank entries are ignored in random and locked modes.

Token matching is case-insensitive: `__myWildcard__` in the template matches a sequential entry named `mywildcard`.

---

## Future Plans

- ComfyUI web panel integration (full app UI embedded as a ComfyUI side panel)
