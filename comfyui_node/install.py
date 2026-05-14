"""Deploy the PromptGenie ComfyUI node to a local ComfyUI installation.

Usage:
    python comfyui_node/install.py <path-to-custom_nodes> [path-to-PromptGenie-data]

Examples:
    python comfyui_node/install.py "H:/ComfyUI_V87/ComfyUI/custom_nodes"
    python comfyui_node/install.py "H:/ComfyUI_V87/ComfyUI/custom_nodes" "E:/VCProjects/PromptGenie/data"

If the data path is omitted it defaults to <repo>/data. The data path is
written to config.txt inside the installed node so the dropdown is
pre-populated on ComfyUI startup.

Run this again after any PromptGenie update to keep the wildcard engine
in sync with the desktop app.
"""

import shutil
import sys
from pathlib import Path

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent
ENGINE_SRC = REPO_ROOT / "app" / "engine" / "wildcard.py"
NODE_SRC = HERE / "__init__.py"
WEB_SRC = HERE / "web"
DEFAULT_DATA_DIR = REPO_ROOT / "data"


def install(custom_nodes_dir: Path, data_dir: Path) -> None:
    dest = custom_nodes_dir / "promptgenie"
    dest.mkdir(parents=True, exist_ok=True)

    shutil.copy2(NODE_SRC, dest / "__init__.py")
    shutil.copy2(ENGINE_SRC, dest / "wildcard.py")
    (dest / "config.txt").write_text(str(data_dir.resolve()), encoding="utf-8")

    if WEB_SRC.is_dir():
        dest_web = dest / "web"
        if dest_web.exists():
            shutil.rmtree(dest_web)
        shutil.copytree(WEB_SRC, dest_web)

    print(f"Installed to: {dest}")
    print(f"  __init__.py  (node)")
    print(f"  wildcard.py  (engine)")
    print(f"  web/         (frontend extension)")
    print(f"  config.txt   -> {data_dir.resolve()}")
    print("\nRestart ComfyUI to load the updated node.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    target = Path(sys.argv[1])
    if not target.is_dir():
        print(f"Error: directory not found: {target}")
        sys.exit(1)

    data = Path(sys.argv[2]) if len(sys.argv) >= 3 else DEFAULT_DATA_DIR
    if not data.is_dir():
        print(f"Error: data directory not found: {data}")
        sys.exit(1)

    install(target, data)
