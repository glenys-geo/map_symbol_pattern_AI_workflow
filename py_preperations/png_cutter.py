"""
sprite_cutter.py
----------------
Extracts 1, 2, or 3 symbols/patterns from a PNG and saves them as
individual PNGs with a transparent background and a defined output size.

Detection:          Zone-based split + dilation/scipy for tight bounding boxes
Background removal: derived from maplibre_pipeline.py
Seamless tiling:    adapted from work by Artem iG (MIT License)

Project note:
    This script was created for the Sprite Builder workflow with support from Codex.
    The related test environment uses OpenFreeMap basemap styles and MapLibre GL JS.
    See THIRD_PARTY_LICENSES.md for third-party license details.

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
# Detection
# ---------------------------------------------------------------------------

def tight_bbox_in_zone(mask, x_start, x_end):
    """
    Returns the tight bounding box of all content pixels within a
    horizontal zone [x_start, x_end] of the given mask.
    """
    zone = mask[:, x_start:x_end + 1]
    rows = np.where(zone.any(axis=1))[0]
    cols = np.where(zone.any(axis=0))[0]
    if len(rows) == 0 or len(cols) == 0:
        return None
    return BoundingBox(
        x_start + int(cols[0]),
        int(rows[0]),
        x_start + int(cols[-1]),
        int(rows[-1])
    )


def find_symbols(img, count=3, alpha_threshold=30, h_dilation=60, v_dilation=10):
    """
    Finds exactly `count` symbols/patterns in the image.

    Strategy:
    - Divide the image into `count` equal vertical zones
    - Within each zone, dilate (h + v) to merge parts of the same symbol
      (e.g. lid + basket, wings + fuselage, separate pattern tiles)
    - Find the largest connected component per zone
    - Return its tight original bounding box

    Using zones instead of global component detection makes the result
    reliable regardless of whether symbols touch, overlap in projection,
    or are separated by white space. It also correctly handles cases where
    the number of symbols is known in advance (1, 2, or 3).

    Note: The alpha channel (not color) is used for the mask so that
    intentional white borders around symbols are preserved.
    Background removal happens later in remove_background().
    """
    arr = np.array(img.convert("RGBA"))
    mask = arr[:, :, 3] > alpha_threshold

    w = img.width
    zone_width = w // count
    zones = []
    for i in range(count):
        x_start = i * zone_width
        x_end   = (i + 1) * zone_width - 1 if i < count - 1 else w - 1
        zones.append((x_start, x_end))

    struct  = np.ones((v_dilation, h_dilation))
    dilated = ndimage.binary_dilation(mask, structure=struct)
    labeled, _ = ndimage.label(dilated)

    boxes = []
    for x_start, x_end in zones:
        # Find the largest component within this zone
        zone_labels = labeled[:, x_start:x_end + 1]
        ids, counts = np.unique(zone_labels[zone_labels > 0], return_counts=True)
        if len(ids) == 0:
            continue
        dominant = ids[np.argmax(counts)]

        # Tight bbox using original (non-dilated) mask
        orig = (labeled == dominant) & mask
        bbox = tight_bbox_in_zone(orig, x_start, x_end)
        if bbox is not None:
            boxes.append(bbox)

    return boxes


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------

def remove_artifacts(img, span_ratio=0.20):
    """
    Removes narrow edge artifacts such as thin bars or fragments.

    For each column, computes the vertical span (topmost to bottommost
    occupied row). Columns covering less than span_ratio of the maximum
    span are treated as artifacts and cropped out. Same logic for rows.

    Works even when the artifact is physically connected to the symbol,
    since a thin bar always has a much smaller span.
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


def trim_edges(img, alpha_threshold=30, edge_sample_size=5):
    """
    Crops empty borders from the image. Handles three cases automatically:

    Case 1 — Transparent edges, opaque content:
              After remove_background(), or patterns with transparent bg.
              Crops to the bounding box of all opaque pixels (alpha > threshold).

    Case 2 — Opaque solid-color border around content:
              Patterns with a uniform background color (white, yellow-green, etc.).
              Background color is sampled from the image edges (not corners, to
              avoid color-bleeding artifacts from transparent pixels). Crops to
              the bounding box of all non-background pixels.

    Case 3 — No clear border: image is returned unchanged.
    """
    arr = np.array(img.convert("RGBA"))
    r, g, b, a = arr[:,:,0], arr[:,:,1], arr[:,:,2], arr[:,:,3]
    h, w = arr.shape[:2]
    s = edge_sample_size

    # Case 1: transparent edges present — crop to opaque content
    if a.min() < alpha_threshold:
        is_content = a > alpha_threshold
        rows = np.where(is_content.any(axis=1))[0]
        cols = np.where(is_content.any(axis=0))[0]
        if len(rows) == 0 or len(cols) == 0:
            return img
        return img.crop((int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1))

    # Case 2: all pixels opaque — detect solid color border by sampling edges
    # Sample from the outer edge rows/cols (not corners, to avoid color bleeding)
    # Only use pixels that are actually opaque for sampling
    edge_pixels = np.concatenate([
        arr[:s,  :,   :3].reshape(-1, 3),   # top rows
        arr[-s:, :,   :3].reshape(-1, 3),   # bottom rows
        arr[:,   :s,  :3].reshape(-1, 3),   # left cols
        arr[:,   -s:, :3].reshape(-1, 3),   # right cols
    ])
    edge_alpha = np.concatenate([
        a[:s,  :  ].reshape(-1),
        a[-s:, :  ].reshape(-1),
        a[:,   :s ].reshape(-1),
        a[:,   -s:].reshape(-1),
    ])
    # Only sample opaque edge pixels
    opaque_edge = edge_pixels[edge_alpha > alpha_threshold]
    if len(opaque_edge) == 0:
        return img

    bg_r = int(np.median(opaque_edge[:, 0]))
    bg_g = int(np.median(opaque_edge[:, 1]))
    bg_b = int(np.median(opaque_edge[:, 2]))

    tol = 20
    is_bg = (
        (np.abs(r.astype(int) - bg_r) < tol) &
        (np.abs(g.astype(int) - bg_g) < tol) &
        (np.abs(b.astype(int) - bg_b) < tol)
    )
    is_content = ~is_bg

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
            -> set alpha to 0, softly feather edges via distance transform
    Case 2: Color bleeding (alpha = 0 but RGB is grey/colored)
            -> normalize RGB to white to prevent bleed-through when
               rendering in MapLibre or the browser
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


def make_seamless(img, overlap=0.1):
    """
    Blends opposite edges of the image so it tiles without visible seams.
    Adapted from work by Artem iG (MIT License) via
    img2texture.image_to_seamless.

    The overlap parameter controls how strongly the edges are blended:
      0.05 = minimal blending, subtle effect
      0.10 = standard, good balance (default)
      0.25 = stronger blending, smoother seams but more edge overlap
      0.50 = maximum blending

    Applied after trim_edges and before resize_output so the blending
    works on the exact pattern content without any white border.

    Important: img2texture crops the image by the overlap amount on each
    side after blending, which would produce smaller tiles that leave gaps
    when tiled in MapLibre. To fix this, the result is scaled back to the
    original input size using high-quality resampling.

    Dependency: pip install img2texture
    License note: see THIRD_PARTY_LICENSES.md
    """
    from img2texture import image_to_seamless
    original_size = img.size
    # Convert to RGB for processing (avoids alpha-channel artifacts in blending)
    rgb = img.convert("RGB")
    seamless = image_to_seamless(rgb, overlap=overlap)
    # Resize back to original dimensions so tiles fit together exactly
    seamless = seamless.resize(original_size, Image.LANCZOS)
    return seamless.convert("RGBA")


def resize_output(img, size, keep_ratio=True):
    """
    Resizes the image to size x size pixels.

    keep_ratio=True  (default, recommended for symbols):
        Scales to fit within the square, preserving aspect ratio.
        Transparent padding is added on the shorter axis.
        Prevents squashing or stretching of symbols.

    keep_ratio=False (recommended for patterns):
        Scales directly to size x size without padding.
        Avoids transparent edge strips when the crop is near-square.
        Use when the output will be tiled and exact edge alignment matters.
    """
    if not keep_ratio:
        return img.resize((size, size), Image.LANCZOS)

    src_w, src_h = img.size
    scale = min(size / src_w, size / src_h)
    new_w = round(src_w * scale)
    new_h = round(src_h * scale)

    scaled = img.resize((new_w, new_h), Image.LANCZOS)

    canvas = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    offset_x = (size - new_w) // 2
    offset_y = (size - new_h) // 2
    canvas.paste(scaled, (offset_x, offset_y))
    return canvas


# ---------------------------------------------------------------------------
# Crop and save
# ---------------------------------------------------------------------------

def crop_and_save(img, boxes, names, output_dir, padding=20,
                  output_size=256, trim=False, keep_ratio=True,
                  do_seamless=False, seamless_overlap=0.1,
                  do_remove_bg=False, do_remove_artifacts=False):
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
            cropped = trim_edges(cropped)
        if do_remove_bg:
            cropped = remove_background(cropped)
        if do_seamless:
            cropped = make_seamless(cropped, overlap=seamless_overlap)

        cropped = resize_output(cropped, output_size, keep_ratio=keep_ratio)

        path = output_dir / name
        cropped.save(path)
        saved.append(path)
        print(f"  ✓ {name}  ({output_size}x{output_size} px)  [{bbox}]")

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


def prompt_seamless():
    """Asks whether to apply seamless blending and what overlap to use."""
    do_it = prompt_yes_no(
        "Make patterns seamless?",
        "Edge blending applied — removes visible seams when tiling (recommended for patterns)",
        "No blending — image is used as-is"
    )
    if not do_it:
        return False, 0.1
    print()
    print("Seamless overlap (0.0 - 0.5):")
    print("  0.05 = minimal blending")
    print("  0.10 = standard, good balance (default)")
    print("  0.25 = stronger blending")
    print("  0.50 = maximum blending")
    print()
    raw = input("Overlap value [0.1]: ").strip()
    try:
        overlap = float(raw) if raw else 0.1
        overlap = max(0.0, min(0.5, overlap))
    except ValueError:
        overlap = 0.1
    print(f"  -> Overlap: {overlap}")
    return True, overlap


def prompt_count():
    print("How many symbols/patterns are in each PNG?")
    print("  [1] One")
    print("  [2] Two")
    print("  [3] Three")
    print()
    while True:
        c = input("Choice [1/2/3]: ").strip()
        if c in ("1", "2", "3"):
            return int(c)
        print("  Please enter 1, 2, or 3.")


def prompt_output_size():
    raw = input("Output size in pixels [256]: ").strip()
    if not raw:
        return 256
    try:
        size = int(raw)
        if size > 0:
            return size
    except ValueError:
        pass
    print("  Invalid input, using default 256.")
    return 256


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------

DEFAULT_LABELS = {
    1: ["symbol"],
    2: ["small", "large"],
    3: ["small", "medium", "large"],
}


def process_single(input_path, output_dir, count, output_size,
                   trim, keep_ratio, do_seamless, seamless_overlap,
                   do_remove_bg, do_remove_artifacts):
    img = Image.open(input_path).convert("RGBA")
    print(f"  Image loaded: {input_path.name}  ({img.width}x{img.height} px)\n")

    print(f"Detecting {count} symbol(s) ...")
    boxes = find_symbols(img, count=count)

    if not boxes:
        print("  No symbols found.")
        return

    print(f"  {len(boxes)} symbol(s) found\n")
    print(f"Enter names for {len(boxes)} output file(s).")
    print("  (Press Enter to use the default name)\n")

    defaults = DEFAULT_LABELS.get(count, [f"{input_path.stem}_{i+1:02d}" for i in range(count)])
    names = []
    for i in range(len(boxes)):
        default = defaults[i] if i < len(defaults) else f"{input_path.stem}_{i+1:02d}"
        raw = input(f"  Name for symbol {i+1} [{default}]: ").strip().strip('"').strip("'")
        names.append(raw if raw else default)

    print()
    saved = crop_and_save(img, boxes, names, output_dir,
                          output_size=output_size, trim=trim,
                          keep_ratio=keep_ratio,
                          do_seamless=do_seamless,
                          seamless_overlap=seamless_overlap,
                          do_remove_bg=do_remove_bg,
                          do_remove_artifacts=do_remove_artifacts)
    print(f"\n  {len(saved)} file(s) saved to: {output_dir.resolve()}")


def process_batch(folder, output_dir, count, output_size,
                  trim, keep_ratio, do_seamless, seamless_overlap,
                  do_remove_bg, do_remove_artifacts):
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

    defaults = DEFAULT_LABELS.get(count, [f"symbol_{i+1:02d}" for i in range(count)])
    total_saved = 0

    for img_path in image_files:
        print(f"--- {img_path.name} ---")
        try:
            img = Image.open(img_path).convert("RGBA")
            boxes = find_symbols(img, count=count)

            if not boxes:
                print("  No symbols found — skipped.\n")
                continue

            img_output_dir = output_dir / img_path.stem
            names = [f"{img_path.stem}_{s}" for s in defaults[:len(boxes)]]

            saved = crop_and_save(img, boxes, names, img_output_dir,
                                  output_size=output_size, trim=trim,
                                  keep_ratio=keep_ratio,
                                  do_seamless=do_seamless,
                                  seamless_overlap=seamless_overlap,
                                  do_remove_bg=do_remove_bg,
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
    print("  Extract symbols/patterns from PNG files")
    print("=" * 50)
    print()

    count = prompt_count()
    print()

    output_size = prompt_output_size()
    print()

    trim = prompt_yes_no(
        "Trim edges?",
        "White/transparent borders are cropped to the exact pattern boundary",
        "Padding is kept"
    )
    print()

    keep_ratio = prompt_yes_no(
        "Preserve aspect ratio when resizing?",
        "Symbol is centered with transparent padding (recommended for symbols)",
        "Image is stretched to fill the full output size (recommended for patterns)"
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

    do_seamless, seamless_overlap = prompt_seamless()
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
        process_single(input_path, output_dir, count, output_size,
                       trim, keep_ratio, do_seamless, seamless_overlap,
                       do_remove_bg, do_remove_artifacts)
    else:
        folder = prompt_folder_path()
        print()
        output_dir = prompt_output_dir(folder / "output")
        print()
        process_batch(folder, output_dir, count, output_size,
                      trim, keep_ratio, do_seamless, seamless_overlap,
                      do_remove_bg, do_remove_artifacts)


if __name__ == "__main__":
    main()
