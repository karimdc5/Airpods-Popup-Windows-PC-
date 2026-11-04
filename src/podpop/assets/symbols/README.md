# Case symbols (not included)

`scripts/render_case.py` turns SF Symbol SVGs from this folder into the case
pictures shown beside the buds (`<name>_case.png` in `%APPDATA%\PodPop\hud`).

The SVGs come from [brendanballon/sfsymbols-svg](https://github.com/brendanballon/sfsymbols-svg),
an export of Apple's **SF Symbols**. Apple's SF Symbols licence doesn't allow
redistributing them, so they're **not part of this repository**: everything in
this folder except this README is git-ignored, and so are the PNGs rendered
from them. Put the files you have here, then run `scripts/import_hud.py`.

Expected file names (see `CASE_SYMBOLS` in `scripts/render_case.py`):

| PodPop name | SVG |
|---|---|
| `airpods` | `airpods.chargingcase.svg` |
| `airpodsGen3` | `airpods.gen3.chargingcase.wireless.svg` |
| `airpodsGen4` | `airpods.gen4.chargingcase.wireless.svg` |
| `airpodsPro`, `airpodsPro3` | `airpods.pro.chargingcase.wireless.svg` |
| `beatsstudio` | `beats.studiobuds.chargingcase.svg` |
| `airpodsMax`, `beatssolo` | none (headphones have no case) |
