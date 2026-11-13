"""Print DuckDuckGo result URLs from a saved HTML page."""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote


def main() -> int:
    text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
    for href in re.findall(r'class="result__a"[^>]*href="([^"]+)"', text):
        match = re.search(r"uddg=([^&]+)", href)
        if match:
            print(unquote(match.group(1)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())