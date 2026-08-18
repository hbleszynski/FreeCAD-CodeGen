"""Convert the project PNG artwork into a multi-resolution Windows icon."""

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets" / "freecad-agent.png"
DESTINATION = ROOT / "assets" / "freecad-agent.ico"
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def main() -> None:
    if not SOURCE.is_file():
        raise FileNotFoundError(f"Icon source not found: {SOURCE}")
    with Image.open(SOURCE) as image:
        image.convert("RGBA").save(
            DESTINATION,
            format="ICO",
            sizes=[(size, size) for size in ICON_SIZES],
        )
    print(f"Created: {DESTINATION}")


if __name__ == "__main__":
    main()
