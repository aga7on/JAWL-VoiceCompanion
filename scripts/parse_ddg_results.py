"""Extract DuckDuckGo search results from a saved HTML page."""
from __future__ import annotations

import re
import sys
from pathlib import Path


def main() -> int:
    path = Path(sys.argv[1])
    text = path.read_text(encoding="utf-8", errors="replace")

    def clean(fragment: str) -> str:
        fragment = re.sub(r"<[^>]+>", "", fragment)
        return re.sub(r"\s+", " ", fragment).strip()

    titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', text, re.S)
    snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', text, re.S)

    pairs = list(zip(titles[:10], snippets[:10]))
    if not pairs:
        print("no results parsed")
        return 1

    for index, (title, snippet) in enumerate(pairs, 1):
        print(f"{index}. {clean(title)}")
        print(f"   {clean(snippet)[:200]}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())