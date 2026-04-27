"""
seamless_pattern.py
-------------------
Converts PNG images into seamless tileable patterns and exports them as
scaled SVGs with transparent backgrounds, ready for use in MapLibre.

Steps per image:
  1. Make seamless  — blend edges using img2texture
  2. Vectorize      — convert to SVG using vtracer
  3. Remove white   — strip near-white background paths from the SVG
  4. Scale          — resize SVG to the target output size

Dependencies:
    pip install Pillow vtracer img2texture

Usage:
    python seamless_pattern.py
"""

import os
import re
import xml.etree.ElementTree as ET

from PIL import Image
import vtracer
from img2texture import image_to_seamless


# ---------------------------------------------------------------------------
# vtracer parameters
# ---------------------------------------------------------------------------

VTRACER_PARAMS = {
    "colormode":        "color",
    "hierarchical":     "stacked",
    "mode":             "spline",
    "filter_speckle":   4,
    "color_precision":  6,
    "layer_difference": 16,
    "corner_threshold": 60,
    "length_threshold": 4.0,
    "max_iterations":   10,
    "splice_threshold": 45,
    "path_precision":   3,
}

SUPPORTED_FORMATS = (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp")


# ---------------------------------------------------------------------------
# SVG helpers
# ---------------------------------------------------------------------------

NEAR_WHITE_THRESHOLD = 240


def is_near_white(hex_color: str) -> bool:
    """Returns True if a hex color is close to white."""
    hex_color = hex_color.strip().lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    if len(hex_color) == 8:
        hex_color = hex_color[:6]
    if len(hex_color) != 6:
        return False
    try:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        return r >= NEAR_WHITE_THRESHOLD and g >= NEAR_WHITE_THRESHOLD and b >= NEAR_WHITE_THRESHOLD
    except ValueError:
        return False


def get_fill_color(element) -> str:
    """Extracts the fill color from an SVG element's attributes or style."""
    fill = element.get("fill", "").strip().lower()
    if fill:
        return fill
    style = element.get("style", "").lower()
    match = re.search(r"fill:\s*(#[0-9a-f]+)", style)
    if match:
        return match.group(1)
    return ""


def remove_white_paths(root):
    """Removes all SVG paths with a white or near-white fill color."""
    for parent in root.iter():
        to_remove = []
        for child in parent:
            fill = get_fill_color(child)
            if fill in ("white", "none"):
                to_remove.append(child)
            elif fill.startswith("#") and is_near_white(fill):
                to_remove.append(child)
        for child in to_remove:
            parent.remove(child)


def scale_svg(svg_path: str, target_size: int):
    """Resizes an SVG to the given width and height in pixels."""
    with open(svg_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Add viewBox if missing so the SVG scales correctly
    if "viewBox" not in content:
        w_match = re.search(r'width="([0-9.]+)"', content)
        h_match = re.search(r'height="([0-9.]+)"', content)
        if w_match and h_match:
            content = content.replace(
                "<svg ",
                f'<svg viewBox="0 0 {w_match.group(1)} {h_match.group(1)}" ', 1
            )

    content = re.sub(r'width="[^"]*"',  f'width="{target_size}"',  content)
    content = re.sub(r'height="[^"]*"', f'height="{target_size}"', content)

    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(content)


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------

def process_pattern(input_path: str, output_path: str,
                    output_size: int, overlap: float):
    """
    Converts a single image into a seamless tileable SVG.

    Steps:
      1. Make seamless: blends opposite edges so the image tiles without seams
      2. Vectorize:     converts the result to an SVG using vtracer
      3. Remove white:  strips near-white background paths from the SVG
      4. Scale:         resizes the SVG to the target output size
    """
    base_name    = os.path.splitext(os.path.basename(input_path))[0]
    tmp_seamless = os.path.join(os.path.dirname(input_path), f"_tmp_{base_name}.png")

    try:
        # Step 1: make seamless
        src      = Image.open(input_path)
        seamless = image_to_seamless(src, overlap=overlap)
        seamless.save(tmp_seamless)
        print(f"    Seamless OK")

        # Step 2: vectorize
        vtracer.convert_image_to_svg_py(tmp_seamless, output_path, **VTRACER_PARAMS)

        # Step 3: remove white background paths
        ET.register_namespace("", "http://www.w3.org/2000/svg")
        tree = ET.parse(output_path)
        remove_white_paths(tree.getroot())
        tree.write(output_path, encoding="unicode", xml_declaration=False)
        print(f"    White background removed")

        # Step 4: scale
        scale_svg(output_path, output_size)
        print(f"    -> {output_path}")

    except Exception as e:
        print(f"    Error: {e}")

    finally:
        if os.path.exists(tmp_seamless):
            os.remove(tmp_seamless)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 50)
    print("  Seamless Pattern Generator")
    print("  PNG -> seamless -> SVG")
    print("=" * 50)
    print()

    patterns_dir = input("Path to pattern images folder: ").strip().strip('"').strip("'")
    if not os.path.isdir(patterns_dir):
        print(f"  Folder not found: {patterns_dir}")
        return

    output_size_input = input("Output size in pixels (e.g. 64): ").strip()
    output_size = int(output_size_input) if output_size_input else 64

    print()
    print("Seamless overlap (0.0 – 0.5):")
    print("  0.05 = minimal blending")
    print("  0.10 = standard (recommended)")
    print("  0.25 = stronger blending")
    print("  0.50 = maximum blending")
    overlap_input = input("Overlap value [Enter = 0.1]: ").strip()
    overlap = float(overlap_input) if overlap_input else 0.1
    print(f"  -> Overlap: {overlap}")
    print()

    output_dir = os.path.normpath(os.path.join(patterns_dir, "..", "output_patterns"))
    os.makedirs(output_dir, exist_ok=True)

    pattern_files = sorted([
        f for f in os.listdir(patterns_dir)
        if f.lower().endswith(SUPPORTED_FORMATS)
    ])

    if not pattern_files:
        print(f"  No supported image files found in '{patterns_dir}'.")
        return

    print(f"  {len(pattern_files)} file(s) found:\n")
    for f in pattern_files:
        print(f"    - {f}")
    print()

    for filename in pattern_files:
        print(f"--- {filename} ---")
        input_path  = os.path.join(patterns_dir, filename)
        base_name   = os.path.splitext(filename)[0]
        output_path = os.path.join(output_dir, f"{base_name}_{output_size}.svg")
        process_pattern(input_path, output_path, output_size, overlap)
        print()

    print("=" * 50)
    print(f"  Done! Output: {output_dir}")


if __name__ == "__main__":
    main()
