"""Downloads the case symbols render_case.py needs into the symbols folder.

Pinned to a commit so a rename upstream can't break it. Run by import_hud.py
with --fetch, or on its own.
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from render_case import CASE_SYMBOLS, SYMBOLS  # noqa: E402

COMMIT = "97cfe9934f0795e8d179bf88b966ad759afbc0b0"  # SF Symbols 7 export
BASE = f"https://raw.githubusercontent.com/brendanballon/sfsymbols-svg/{COMMIT}/symbols/"


def main() -> int:
    SYMBOLS.mkdir(parents=True, exist_ok=True)
    failed = 0
    for symbol in {s for s in CASE_SYMBOLS.values() if s}:
        target = SYMBOLS / symbol
        if target.is_file():
            continue
        try:
            with urllib.request.urlopen(BASE + symbol, timeout=20) as response:
                target.write_bytes(response.read())
            print(f"{symbol} -> downloaded", flush=True)
        except Exception as exc:  # offline, moved, rate-limited
            print(f"{symbol}: {exc}", flush=True)
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
