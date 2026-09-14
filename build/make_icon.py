"""Render our SVG brand asset to Windows multi-resolution icons."""
from pathlib import Path
import os
import subprocess
from PIL import Image

assets = Path(__file__).resolve().parent / "assets"
subprocess.run(["node", "-e", "require(process.env.SHARP_MODULE||'sharp')(process.argv[1]).png().toFile(process.argv[2])", str(assets / "papermind.svg"), str(assets / "papermind.png")], check=True)
with Image.open(assets / "papermind.png") as bitmap:
    bitmap.save(assets / "papermind.ico", sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
