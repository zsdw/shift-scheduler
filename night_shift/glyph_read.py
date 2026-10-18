"""Single-glyph cells (A, 5 …) that Windows OCR drops: compare the cell's glyph shape (2026-10-07).

Templates come from the same image (cells already read with one character) and from Windows fonts.
A reading is accepted only with a clear best match; the caller adds the per-hour headcount check.
"""
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

SIZE = (20, 28)
LABELS = [*'ABCDE', *'123456789']
FONTS = ['malgun.ttf', 'malgunbd.ttf', 'arial.ttf', 'arialbd.ttf', 'NanumGothic.ttf', 'NanumGothicBold.ttf', 'gulim.ttc']
ACCEPT = .72      # minimum similarity of the best label
MARGIN = .08      # best label must beat every other label by this much


def glyph(image, box):
    """Binary glyph of the ink inside a cell, cropped to its bounding box; None if not one glyph."""
    x0, y0, x1, y1 = map(round, box)
    gray = np.asarray(ImageOps.grayscale(image.crop((x0 + 4, y0 + 4, x1 - 4, y1 - 4))), dtype=float)
    if not gray.size: return None
    bg = float(np.percentile(gray, 85))
    ink = gray < max(20, bg * .55)
    # Ink touching the cell edge is a corner memo mark or border residue, not the glyph.
    ink[:2, :] = ink[-2:, :] = False
    ink[:, :2] = ink[:, -2:] = False
    if ink.sum() < 6: return None
    cols = np.flatnonzero(ink.any(axis=0))
    runs = np.split(cols, np.flatnonzero(np.diff(cols) > 2) + 1)
    weights = [int(ink[:, r].sum()) for r in runs]
    main = [r for r, w in zip(runs, weights) if w > .2 * sum(weights)]
    # One glyph only: no '.', no second character; tiny specks (memo triangles) are dropped.
    if len(main) != 1: return None
    ink = ink[:, main[0].min():main[0].max() + 1]
    rows_ = np.flatnonzero(ink.any(axis=1))
    vruns = np.split(rows_, np.flatnonzero(np.diff(rows_) > 2) + 1)
    vmain = max(vruns, key=lambda r: int(ink[r].sum()))
    ink = ink[vmain.min():vmain.max() + 1]
    ys, xs = np.nonzero(ink)
    if len(ys) < 6: return None
    crop = ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return _norm(crop)


def _norm(crop):
    h, w = crop.shape
    side = max(h, w * SIZE[1] / SIZE[0])
    canvas = np.zeros((int(np.ceil(side)), int(np.ceil(side * SIZE[0] / SIZE[1]))), bool)
    oy, ox = (canvas.shape[0] - h) // 2, (canvas.shape[1] - w) // 2
    canvas[oy:oy + h, ox:ox + w] = crop
    img = Image.fromarray((canvas * 255).astype('uint8')).resize(SIZE, Image.BILINEAR)
    return np.asarray(img, dtype=float) / 255


def _font_templates():
    out = {}
    folder = Path('C:/Windows/Fonts')
    for name in FONTS:
        path = folder / name
        if not path.exists(): continue
        font = ImageFont.truetype(str(path), 48)
        for label in LABELS:
            im = Image.new('L', (80, 80), 255)
            ImageDraw.Draw(im).text((10, 5), label, font=font, fill=0)
            ink = np.asarray(im) < 128
            ys, xs = np.nonzero(ink)
            out.setdefault(label, []).append(_norm(ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1]))
    return out


_FONTS = None


def similarity(a, b):
    a, b = a - a.mean(), b - b.mean()
    den = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / den) if den else 0.0


def classify(shape, local):
    """(label, score, runner_up_score). local: {label: [glyph arrays]} from the same image."""
    global _FONTS
    if _FONTS is None: _FONTS = _font_templates()
    scores = {}
    for label in LABELS:
        found = local.get(label, []) + _FONTS.get(label, [])
        if found: scores[label] = max(similarity(shape, t) for t in found)
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    if not ranked: return None, 0.0, 0.0
    return ranked[0][0], ranked[0][1], ranked[1][1] if len(ranked) > 1 else 0.0


def confident(label, score, second):
    return label is not None and score >= ACCEPT and score - second >= MARGIN
