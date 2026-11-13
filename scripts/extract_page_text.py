"""Extract readable text from a saved HTML page (stdlib only)."""
from __future__ import annotations

import html
import re
import sys
from pathlib import Path


def extract(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    # Drop non-content blocks wholesale.
    raw = re.sub(r"(?is)<script\b.*?</script>", " ", raw)
    raw = re.sub(r"(?is)<style\b.*?</style>", " ", raw)
    raw = re.sub(r"(?is)<noscript\b.*?</noscript>", " ", raw)
    raw = re.sub(r"(?is)<svg\b.*?</svg>", " ", raw)
    raw = re.sub(r"(?is)<!--.*?-->", " ", raw)
    # Preserve block boundaries as newlines.
    raw = re.sub(r"(?i)</?(p|div|li|tr|h[1-6]|br|section|article|pre|blockquote)\b[^>]*>", "\n", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    text = html.unescape(raw)
    lines = []
    for line in text.splitlines():
        line = re.sub(r"[ \t\u00a0]+", " ", line).strip()
        if line:
            lines.append(line)
    # Collapse repeated short navigation-like repeats.
    out: list[str] = []
    for line in lines:
        if not out or out[-1] != line:
            out.append(line)
    return "\n".join(out)


if __name__ == "__main__":
    src = Path(sys.argv[1])
    text = extract(src)
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix(".txt")
    out.write_text(text, encoding="utf-8")
    print(f"{out}  chars={len(text)}  lines={text.count(chr(10)) + 1}")
    print("-" * 60)
    print(text[:3000])