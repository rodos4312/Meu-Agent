"""Generate complete Windows MSIX icon variants from assets/meu-icon.png.

Usage: python apps/desktop/scripts/build-meu-appx.py
Requires Pillow only during asset regeneration, never at runtime.
"""

from pathlib import Path
import re
import subprocess

from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
ASSETS = ROOT / "apps" / "desktop" / "assets"
OUT = ASSETS / "meu-appx"


def dimensions(name: str) -> tuple[int, int]:
    bases = {
        "Square44x44Logo": (44, 44),
        "Square150x150Logo": (150, 150),
        "StoreLogo": (50, 50),
        "Wide310x150Logo": (310, 150),
    }
    stem = name.removesuffix(".png")
    prefix = stem.split(".", 1)[0]
    width, height = bases[prefix]
    target = re.search(r"\.targetsize-(\d+)", stem)
    if target:
        edge = int(target.group(1))
        return edge, edge
    scale = re.search(r"\.scale-(\d+)", stem)
    if scale:
        multiplier = int(scale.group(1)) / 100
        return round(width * multiplier), round(height * multiplier)
    return width, height


def build() -> None:
    icon = Image.open(ASSETS / "meu-icon.png").convert("RGBA")
    files = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", "HEAD", "apps/desktop/assets/appx"],
        cwd=ROOT,
        text=True,
    ).splitlines()
    files = [Path(file).name for file in files if file.endswith(".png")]
    if not files:
        raise RuntimeError("No upstream MSIX asset list found")
    OUT.mkdir(parents=True, exist_ok=True)
    for filename in files:
        width, height = dimensions(filename)
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        edge = max(1, round(min(width, height) * 0.84))
        resized = icon.resize((edge, edge), Image.Resampling.LANCZOS)
        canvas.alpha_composite(resized, ((width - edge) // 2, (height - edge) // 2))
        canvas.save(OUT / filename, optimize=True)
    print(f"Generated {len(files)} Meu MSIX images")


if __name__ == "__main__":
    build()
