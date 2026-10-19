from __future__ import annotations

import re
from typing import Any

from utils import format as FM

_URL = re.compile(
    r"(?:https?://|www\.|t\.me/|telegram\.me/|telegram\.dog/)"
    r"[A-Za-z0-9._\-/?#=&%]+",
    re.IGNORECASE,
)
_HANDLE = re.compile(r"@[A-Za-z0-9_]+")
_EXTENSION = re.compile(r"(\.[A-Za-z0-9]{2,5})$")
_SEPARATORS = re.compile(r"[\W_]+", re.UNICODE)
_SIZE_TRAILING_ZEROES = re.compile(r"(\.\d*?[1-9])0+(?= [A-Z])")
_SIZE_ZERO_DECIMALS = re.compile(r"\.0+(?= [A-Z])")


def clean_file_name(value: Any, max_length: int = 256) -> str:
    raw = str(value or "")
    raw = _URL.sub(" ", raw)
    raw = _HANDLE.sub(" ", raw)

    extension_match = _EXTENSION.search(raw)
    extension = extension_match.group(1).lower() if extension_match else ""
    if extension:
        raw = raw[: -len(extension)]

    name = _SEPARATORS.sub(" ", raw).strip()
    name = re.sub(r"\s+", " ", name)
    name = name or "file"

    available = max(1, int(max_length) - len(extension) - 1)
    if len(name) > available:
        name = name[:available].rstrip()
    return f"{name} {extension}".strip() if extension else name


def file_button_label(file_name: Any, file_size: Any) -> str:
    size = FM.size(file_size)
    size = _SIZE_TRAILING_ZEROES.sub(r"\1", size)
    size = _SIZE_ZERO_DECIMALS.sub("", size)
    size = size.replace(" ", "")
    prefix = f"{size} @D_W_T_1 "
    name = clean_file_name(file_name, max_length=64 - len(prefix))
    return f"{prefix}{name}"[:64]


def clean_request_title(title: Any, year: Any = None) -> str:
    name = clean_file_name(title)
    if year:
        year_text = clean_file_name(year)
        if year_text not in name:
            name = f"{name} {year_text}"
    return name


__all__ = ["clean_file_name", "file_button_label", "clean_request_title"]
