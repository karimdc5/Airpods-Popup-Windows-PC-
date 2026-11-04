"""Guards against text damaged by a wrong encoding round trip.

Reading a UTF-8 file as ANSI and writing it back as UTF-8 turns "…" into
"â€¦", and an unescaped backslash in an edit script can drop a control
character (a tab or carriage return) into the middle of a line. Both have
happened here once; these tests stop them coming back silently.
"""

import subprocess
from pathlib import Path

from podpop.ui.popup import NO_READING, Action

ROOT = Path(__file__).resolve().parent.parent
TEXT = {".py", ".md", ".toml", ".yml", ".yaml", ".txt", ".ps1", ".cfg", ".ini"}
# What UTF-8 punctuation looks like after being decoded as cp1252.
MOJIBAKE = ("â€", "Ã¢", "Â·", "Â ")


def test_status_strings_are_single_characters():
    assert Action.CONNECTING.value == "Connecting…"  # one ellipsis character, not "..."
    assert Action.FAILED.value == "Couldn’t connect"  # typographic apostrophe
    assert NO_READING == "—" and len(NO_READING) == 1  # em dash


def _tracked_text_files():
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    return [ROOT / f for f in files if Path(f).suffix.lower() in TEXT]


def test_no_double_encoded_punctuation():
    damaged = []
    for path in _tracked_text_files():
        text = path.read_text(encoding="utf-8")
        damaged += [f"{path.relative_to(ROOT)}: {m!r}" for m in MOJIBAKE if m in text]
    assert not damaged, damaged


def test_no_byte_order_marks_or_stray_control_characters():
    problems = []
    for path in _tracked_text_files():
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            problems.append(f"{path.relative_to(ROOT)}: byte order mark")
        allowed = {"\n", "\t"} | ({"\r"} if path.suffix == ".ps1" else set())
        for number, line in enumerate(raw.decode("utf-8").split("\n"), 1):
            if path.suffix == ".md" and "\t" in line:
                problems.append(f"{path.relative_to(ROOT)}:{number}: tab")
            bad = [c for c in line if ord(c) < 32 and c not in allowed]
            if bad:
                problems.append(f"{path.relative_to(ROOT)}:{number}: control character {bad[0]!r}")
    assert not problems, problems
