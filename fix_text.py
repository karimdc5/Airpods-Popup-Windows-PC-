from pathlib import Path

path = Path("src/podpop/ui/popup.py")
text = path.read_text(encoding="utf-8")
for bad, good in {
    "\u00e2\u20ac\u00a6": "\u2026",  # ellipsis
    "\u00e2\u20ac\u201d": "\u2014",  # em dash
    "\u00e2\u20ac\u2122": "\u2019",  # right quote
}.items():
    text = text.replace(bad, good)
text = text.replace("box.height() * 0.62", "box.height() * 0.72")
path.write_text(text, encoding="utf-8")
print("repaired")
