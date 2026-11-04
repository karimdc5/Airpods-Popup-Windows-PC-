from pathlib import Path

path = Path("src/podpop/ui/popup.py")
text = path.read_text(encoding="utf-8")
old = """        image = self._case_art
        if image is None:
            sprites = turntable.frames(self.view.family, "case")
            image = sprites[0] if sprites else None"""
new = """        sprites = turntable.frames(self.view.family, "case")
        image = sprites[0] if sprites else self._case_art"""
assert old in text, "pattern not found"
path.write_text(text.replace(old, new), encoding="utf-8")
print("patched")
