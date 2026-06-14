from __future__ import annotations

import json
import re
import unicodedata
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
PROMPTS_DIR = PROJECT_ROOT / "prompts"
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_UPLOAD = DATA_DIR / "upload" / "normal"
DEFAULT_OUTPUT = DATA_DIR / "output"


def load_json(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    with path.open(encoding="utf-8-sig") as f:
        return json.load(f)


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", str(text))
    text = re.sub(r"\s+", "", text)
    text = text.replace("（", "(").replace("）", ")")
    return text.lower()


def glob_files(directory: Path, pattern: str) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(
        p for p in directory.iterdir() if p.is_file() and fnmatch(p.name, pattern)
    )


def read_prompt(name: str, **kwargs: str) -> str:
    text = (PROMPTS_DIR / name).read_text(encoding="utf-8")
    for key, value in kwargs.items():
        text = text.replace(f"{{{{{key}}}}}", value)
    return text


def save_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def chapter_code_from_name(name: str) -> str | None:
    m = re.search(r"(CH\d+(?:\.\d+)*)", name, re.I)
    return m.group(1).upper() if m else None
