from datetime import datetime
from pathlib import Path


def write_prompts_to_file(prompts: list[str], output_dir: Path, filename: str | None = None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    if filename is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"prompts_{timestamp}.txt"
    output_path = output_dir / filename
    output_path.write_text("\n".join(prompts), encoding="utf-8")
    return output_path
