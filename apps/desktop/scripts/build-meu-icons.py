"""Rebuild Meu Windows icon assets from the original transparent source image.

Developer-only image pipeline: Pillow is needed to regenerate, not to run Meu.
Usage: python apps/desktop/scripts/build-meu-icons.py SOURCE.png
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


def build(source: Path) -> None:
    image = Image.open(source).convert("RGBA")
    # Ignore low-alpha noise in generated assets so the symbol fills the icon.
    alpha = image.getchannel("A").point(lambda value: 255 if value >= 24 else 0)
    bounds = alpha.getbbox()
    if bounds is None:
        raise ValueError("source image is transparent")
    image = image.crop(bounds)
    size = max(image.size)
    square = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    square.alpha_composite(image, ((size - image.width) // 2, (size - image.height) // 2))
    output = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    mark = square.resize((452, 452), Image.Resampling.LANCZOS)
    output.alpha_composite(mark, (30, 30))
    assets = Path(__file__).resolve().parents[1] / "assets"
    output.save(assets / "meu-icon.png", optimize=True)
    output.save(assets / "meu-icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: build-meu-icons.py SOURCE.png")
    build(Path(sys.argv[1]))
