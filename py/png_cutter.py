"""
sprite_cutter.py
----------------
Extracts the three largest symbols from a PNG and saves them as
individual PNGs with transparent backgrounds.

Detection:    Dilation + scipy connected components
Background removal: derived from maplibre_pipeline.py

Dependencies:
    pip install Pillow numpy scipy

Usage:
    python sprite_cutter.py
"""

from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

class BoundingBox:
    def __init__(self, x1: int, y1: int, x2: int, y2: int):
        self.x1, self.y1, self.x2, self.y2 = x1, y1, x2, y2

    @property
    def width(self):  return self.x2 - self.x1 + 1

    @property
    def height(self): return self.y2 - self.y1 + 1

    def __repr__(self):
        return f"BBox({self.x1},{self.y1} -> {self.x2},{self.y2}, {self.width}x{self.height}px)"


# ---------------------------------------------------------------------------
# Detection: top 3 by area
# ---------------------------------------------------------------------------

def find_top3(img, alpha_threshold=30, h_dilation=60, v_dilation=10):
    """
    Finds the three largest connected content regions in the image.

    Steps:
    1. Mark all non-transparent pixels as content — including intentional
       white borders (e.g. glow/outline effects around symbols)
    2. Dilate horizontally (h_dilation) and vertically (v_dilation) so
       that separate parts of the same symbol (e.g. lid + basket, wings +
       fuselage) are merged into one connected component
    3. Count connected components using scipy.ndimage.label
    4. Select the 3 largest by bounding box area
    5. Return their original (non-dilated) bounding boxes, sorted left to right

    Note: Using the alpha channel (not color) for the mask ensures that
    white borders are preserved and not mistaken for background.
    Background removal happens later in remove_background().
    """
    arr = np.array(img.convert("RGBA"))
    mask = arr[:, :, 3] > alpha_threshold

    struct = np.ones((v_dilation, h_dilation))
    dilated = ndimage.binary_dilation(mask, structure=struct)
    labeled, n = ndimage.label(dilated)

    components = []
    for i in range(1, n + 1):
        orig = (labeled == i) & mask
        rows = np.where(orig.any(axis=1))[0]
        cols = np.where(orig.any(axis=0))[0]
        if len(rows) == 0 or len(cols) == 0:
            continue
        x1, y1 = int(cols[0]), int(rows[0])
        x2, y2 = int(cols[-1]), int(rows[-1])
        area = (x2 - x1) * (y2 - y1)
        components.append((area, x1, y1, x2, y2))

    if not components:
        return []

    top3 = sorted(components, key=lambda c: c[0], reverse=True)[:3]
    top3.sort(key=lambda c: c[1])
    return [BoundingBox(x1, y1, x2, y2) for _, x1, y1, x2, y2 in top3]


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------

def remove_artifacts(img, span_ratio=0.20):
    """
    Removes narrow edge artifacts such as thin bars or fragments.

    For each column, computes the vertical span (distance from topmost
    to bottommost occupied row). Columns covering less than span_ratio
    of the maximum span are treated as artifacts and cropped out.
    The same logic is applied to rows.

    This works even when the artifact is physically connected to the
    symbol, since a thin bar always has a much smaller span.
    """
    arr = np.array(img.convert("RGBA"))
    content = arr[:, :, 3] > 128

    col_spans = np.array([
        (np.where(content[:, c])[0][-1] - np.where(content[:, c])[0][0] + 1)
        if content[:, c].any() else 0
        for c in range(img.width)
    ])
    row_spans = np.array([
        (np.where(content[r, :])[0][-1] - np.where(content[r, :])[0][0] + 1)
        if content[r, :].any() else 0
        for r in range(img.height)
    ])

    max_col = col_spans.max()
    max_row = row_spans.max()
    if max_col == 0:
        return img

    good_cols = np.where(col_spans >= max_col * span_ratio)[0]
    good_rows = np.where(row_spans >= max_row * span_ratio)[0]
    if len(good_cols) == 0 or len(good_rows) == 0:
        return img

    pad = 3
    x1 = max(0, int(good_cols[0]) - pad)
    x2 = min(img.width - 1,  int(good_cols[-1]) + pad)
    y1 = max(0, int(good_rows[0]) - pad)
    y2 = min(img.height - 1, int(good_rows[-1]) + pad)
    return img.crop((x1, y1, x2 + 1, y2 + 1))


def trim_transparency(img, alpha_threshold=30):
    """
    Crops transparent and near-white edges from the image.
    Useful when cropped symbols have excess empty space (e.g. patterns).
    """
    arr = np.array(img.convert("RGBA"))
    a = arr[:, :, 3]
    is_content = a > alpha_threshold
    rows = np.where(is_content.any(axis=1))[0]
    cols = np.where(is_content.any(axis=0))[0]
    if len(rows) == 0 or len(cols) == 0:
        return img
    return img.crop((int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1))


def remove_background(img, bg_threshold=240, edge_feather=3):
    """
    Removes white/light backgrounds by making them transparent.
    Derived from maplibre_pipeline.py.

    Case 1: Visible white background (alpha > 0, RGB near white)
            -> set alpha to 0, softly blend edges using distance transform
    Case 2: Color bleeding (alpha = 0 but RGB is grey/colored)
            -> normalize RGB to white so colors don't bleed through
               when rendering in MapLibre or the browser
    """
    arr = np.array(img.convert("RGBA")).astype(float)
    r, g, b, a = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2], arr[:, :, 3]

    # Case 1: make visible white background transparent
    is_bg = (a > 10) & (r >= bg_threshold) & (g >= bg_threshold) & (b >= bg_threshold)
    a[is_bg] = 0

    if edge_feather > 0:
        fg_mask = (~is_bg & (a > 10)).astype(float)
        dist = ndimage.distance_transform_edt(fg_mask)
        edge_zone = (dist > 0) & (dist <= edge_feather) & (a > 0)
        a[edge_zone] = np.minimum(a[edge_zone], (dist[edge_zone] / edge_feather) * 255)

    arr[:, :, 3] = np.clip(a, 0, 255)

    # Case 2: fix color bleeding on fully transparent pixels
    fully_transp = arr[:, :, 3] < 10
    arr[fully_transp, 0] = 255
    arr[fully_transp, 1] = 255
    arr[fully_transp, 2] = 255

    # Blend semi-transparent edge pixels towards white
    half_transp = (arr[:, :, 3] >= 10) & (arr[:, :, 3] < 128)
    if half_transp.any():
        factor = (arr[half_transp, 3] / 255.0).reshape(-1, 1)
        arr[half_transp, :3] = arr[half_transp, :3] * factor + 255 * (1 - factor)

    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGBA")


# ---------------------------------------------------------------------------
# Crop and save
# ---------------------------------------------------------------------------

def crop_and_save(img, boxes, names, output_dir, padding=20,
                  trim=False, do_remove_bg=False, do_remove_artifacts=False):
    """Crops each detected bounding box and saves it as a PNG."""
    output_dir.mkdir(parents=True, exist_ok=True)
    saved = []

    for i, bbox in enumerate(boxes):
        name = names[i] if i < len(names) else f"symbol_{i+1:02d}"
        if not name.lower().endswith(".png"):
            name += ".png"

        x1 = max(0, bbox.x1 - padding)
        y1 = max(0, bbox.y1 - padding)
        x2 = min(img.width,  bbox.x2 + padding + 1)
        y2 = min(img.height, bbox.y2 + padding + 1)

        cropped = img.crop((x1, y1, x2, y2))

        if do_remove_artifacts:
            cropped = remove_artifacts(cropped)
        if trim:
            cropped = trim_transparency(cropped)
        if do_remove_bg:
            cropped = remove_background(cropped)

        path = output_dir / name
        cropped.save(path)
        saved.append(path)
        print(f"  ✓ {name}  ({cropped.width}x{cropped.height} px)  [{bbox}]")

    return saved


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif")


def prompt_file_path():
    while True:
        raw = input("Path to input PNG: ").strip().strip('"').strip("'")
        if not raw:
            print("  Please enter a path.")
            continue
        path = Path(raw)
        if not path.exists():
            print(f"  File not found: {path}")
            continue
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            print(f"  Unsupported format '{path.suffix}'")
            continue
        return path


def prompt_folder_path():
    while True:
        raw = input("Path to folder: ").strip().strip('"').strip("'")
        if not raw:
            print("  Please enter a path.")
            continue
        path = Path(raw)
        if not path.exists() or not path.is_dir():
            print(f"  Folder not found: {path}")
            continue
        return path


def prompt_output_dir(default):
    raw = input(f"Output folder [{default}]: ").strip().strip('"').strip("'")
    return Path(raw) if raw else default


def prompt_yes_no(question, info_yes, info_no):
    print(question)
    print(f"  [y] {info_yes}")
    print(f"  [n] {info_no}")
    print()
    while True:
        c = input("Choice [y/n]: ").strip().lower()
        if c == "y":
            return True
        if c == "n":
            return False
        print("  Please enter y or n.")


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------

def process_single(input_path, output_dir, trim, do_remove_bg, do_remove_artifacts):
    img = Image.open(input_path).convert("RGBA")
    print(f"  Image loaded: {input_path.name}  ({img.width}x{img.height} px)\n")

    print("Detecting symbols ...")
    boxes = find_top3(img)

    if not boxes:
        print("  No symbols found.")
        return

    print(f"  {len(boxes)} symbol(s) found\n")
    print(f"Enter names for {len(boxes)} output file(s).")
    print("  (Press Enter to use the default name)\n")

    default_labels = ["small", "medium", "large"]
    names = []
    for i in range(len(boxes)):
        default = default_labels[i] if i < len(default_labels) else f"{input_path.stem}_{i+1:02d}"
        raw = input(f"  Name for symbol {i+1} [{default}]: ").strip().strip('"').strip("'")
        names.append(raw if raw else default)

    print()
    saved = crop_and_save(img, boxes, names, output_dir,
                          trim=trim, do_remove_bg=do_remove_bg,
                          do_remove_artifacts=do_remove_artifacts)
    print(f"\n  {len(saved)} file(s) saved to: {output_dir.resolve()}")


def process_batch(folder, output_dir, trim, do_remove_bg, do_remove_artifacts):
    image_files = sorted([
        f for f in folder.iterdir()
        if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
    ])

    if not image_files:
        print(f"  No image files found in '{folder}'.")
        return

    print(f"  {len(image_files)} image(s) found:\n")
    for f in image_files:
        print(f"    - {f.name}")
    print()

    total_saved = 0
    for img_path in image_files:
        print(f"--- {img_path.name} ---")
        try:
            img = Image.open(img_path).convert("RGBA")
            boxes = find_top3(img)

            if not boxes:
                print("  No symbols found — skipped.\n")
                continue

            img_output_dir = output_dir / img_path.stem
            names = [f"{img_path.stem}_{s}" for s in ["small", "medium", "large"][:len(boxes)]]

            saved = crop_and_save(img, boxes, names, img_output_dir,
                                  trim=trim, do_remove_bg=do_remove_bg,
                                  do_remove_artifacts=do_remove_artifacts)
            total_saved += len(saved)
            print(f"  {len(saved)} symbol(s) saved to: {img_output_dir}\n")

        except Exception as e:
            print(f"  Error processing {img_path.name}: {e}\n")

    print("=" * 50)
    print(f"  Batch complete: {total_saved} file(s) from {len(image_files)} image(s)")
    print(f"  Output: {output_dir.resolve()}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 50)
    print("  Sprite Cutter")
    print("  3 symbols per PNG -> individual PNGs")
    print("=" * 50)
    print()

    trim = prompt_yes_no(
        "Trim transparent edges?",
        "Edges will be removed (recommended for patterns)",
        "Padding is kept"
    )
    print()

    do_remove_bg = prompt_yes_no(
        "Remove white background?",
        "Background becomes transparent (recommended for symbols)",
        "Image stays unchanged"
    )
    print()

    do_remove_artifacts = prompt_yes_no(
        "Remove edge artifacts and bars?",
        "Narrow bars and fragments will be cropped out",
        "Image stays unchanged"
    )
    print()

    print("Mode:")
    print("  [1] Single image  (with custom names)")
    print("  [2] Batch mode    (entire folder, automatic names)")
    print()
    while True:
        mode = input("Choice [1/2]: ").strip()
        if mode in ("1", "2"):
            break
        print("  Please enter 1 or 2.")
    print()

    if mode == "1":
        input_path = prompt_file_path()
        print()
        output_dir = prompt_output_dir(input_path.parent)
        print()
        process_single(input_path, output_dir, trim, do_remove_bg, do_remove_artifacts)
    else:
        folder = prompt_folder_path()
        print()
        output_dir = prompt_output_dir(folder / "output")
        print()
        process_batch(folder, output_dir, trim, do_remove_bg, do_remove_artifacts)


if __name__ == "__main__":
    main()
