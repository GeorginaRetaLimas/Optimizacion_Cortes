"""RF-11 / RF-12 / RNF-02: planos de corte en PNG.

Lienzo de 3300 x 2550 px con metadatos de 300 DPI: carta horizontal a 300 DPI
(supera el mínimo de 1920 x 1080 y se imprime a tamaño completo).
"""
from __future__ import annotations

import io
import os
import zipfile

import matplotlib
from PIL import Image, ImageDraw, ImageFont

W_PX, H_PX, DPI = 3300, 2550, 300
_FONT_DIR = os.path.join(os.path.dirname(matplotlib.__file__), "mpl-data", "fonts", "ttf")
_FONT = os.path.join(_FONT_DIR, "DejaVuSans.ttf")
_FONT_B = os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf")

# Colores claros (texto negro legible) + tramas para distinguir > 12 órdenes
PALETTE = ["#8ecae6", "#ffb703", "#90be6d", "#f4a6a6", "#cdb4db", "#f9c74f",
           "#a3c4f3", "#ffcfd2", "#b9fbc0", "#fde4cf", "#98f5e1", "#e9c46a"]
PATTERNS = [None, "diag", "cross", "dots"]
SCRAP_BG, SCRAP_LINE = "#d9d9d9", "#9a9a9a"
OFFCUT_BG, OFFCUT_LINE = "#d8f3dc", "#2d6a4f"

_font_cache: dict = {}


def font(size: int, bold: bool = False):
    key = (size, bold)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(_FONT_B if bold else _FONT, size)
    return _font_cache[key]


def order_styles(orders: list) -> dict:
    """Asigna a cada orden un color y una trama estables para toda la corrida."""
    styles = {}
    for i, oid in enumerate(orders):
        styles[oid] = (PALETTE[i % len(PALETTE)], PATTERNS[(i // len(PALETTE)) % len(PATTERNS)])
    return styles


def _hatch(img: Image.Image, box, color, kind="diag", step=18, width=2):
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    if x1 - x0 < 2 or y1 - y0 < 2:
        return
    tile = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    w, h = tile.size
    if kind in ("diag", "cross"):
        for k in range(-h, w, step):
            d.line([(k, h), (k + h, 0)], fill=color, width=width)
    if kind == "cross":
        for k in range(0, w + h, step):
            d.line([(k, h), (k - h, 0)], fill=color, width=width)
    if kind == "dots":
        for yy in range(step // 2, h, step):
            for xx in range(step // 2, w, step):
                d.ellipse([xx - 3, yy - 3, xx + 3, yy + 3], fill=color)
    img.paste(tile, (x0, y0), tile)


def _fmt(v: float) -> str:
    return f"{v:g}" if abs(v - round(v)) > 1e-9 else f"{int(round(v))}"


def _fit_label(lines: list[str], max_w: float, max_h: float):
    """Busca el mayor tamaño de letra con el que caben las líneas."""
    for size in (40, 34, 30, 26, 22, 19, 16):
        f = font(size)
        widths = [f.getbbox(t)[2] for t in lines]
        lh = size + 6
        if max(widths) <= max_w - 10 and lh * len(lines) <= max_h - 8:
            return f, lh
    return None, 0


def _draw_label(img: Image.Image, box, lines_options: list[list[str]]):
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    for vertical in (False, True):
        mw, mh = (bh, bw) if vertical else (bw, bh)
        for lines in lines_options:
            f, lh = _fit_label(lines, mw, mh)
            if f is None:
                continue
            tw = int(max(f.getbbox(t)[2] for t in lines)) + 4
            th = lh * len(lines)
            tile = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
            d = ImageDraw.Draw(tile)
            for i, t in enumerate(lines):
                lw = f.getbbox(t)[2]
                d.text(((tw - lw) / 2, i * lh), t, fill="black", font=f)
            if vertical:
                tile = tile.rotate(90, expand=True)
            img.paste(tile, (int(x0 + (bw - tile.width) / 2), int(y0 + (bh - tile.height) / 2)), tile)
            return True
        if bw >= bh:  # solo se prueba vertical si la pieza es más alta que ancha
            break
    return False


def render_sheet(run_label: str, sheet: dict, total: int, styles: dict) -> bytes:
    img = Image.new("RGB", (W_PX, H_PX), "white")
    d = ImageDraw.Draw(img)
    M = 70

    # ------------------------------------------------------------ encabezado
    d.rectangle([0, 0, W_PX, 300], fill="#1d3557")
    d.text((M, 28), "SprintWindow · Plano de corte", fill="white", font=font(56, True))
    tag = "  (RETAZO)" if sheet["es_retazo"] else ""
    d.text((M, 108), f"Corrida {run_label}   ·   Hoja {sheet['hoja_id']} ({sheet['secuencia']} de {total})"
                     f"   ·   Lote {sheet['codigo']}{tag}", fill="white", font=font(42, True))
    d.text((M, 172), f"{_fmt(sheet['ancho'])} × {_fmt(sheet['alto'])} mm   ·   Color: {sheet['color']}"
                     f"   ·   Textura: {sheet['textura']}   ·   Espesor: {_fmt(sheet['espesor'])} mm",
           fill="white", font=font(38))
    mode = "Guillotina" if sheet["modo_corte"] == "guillotina" else "Anidamiento libre (CNC)"
    d.text((M, 228), f"Corte: {mode}   ·   Kerf: {_fmt(sheet['kerf'])} mm   ·   "
                     f"Refilado: {_fmt(sheet['refilado'])} mm por lado", fill="#cfe0f5", font=font(34))
    # Indicador de veta
    vx = W_PX - 820
    if sheet["veta_direccional"]:
        d.rounded_rectangle([vx, 60, W_PX - M, 240], 18, fill="#e63946")
        d.text((vx + 30, 75), "VETA DIRECCIONAL", fill="white", font=font(38, True))
        ay = 185
        d.line([(vx + 40, ay), (W_PX - M - 80, ay)], fill="white", width=12)
        d.polygon([(W_PX - M - 40, ay), (W_PX - M - 95, ay - 32), (W_PX - M - 95, ay + 32)], fill="white")
    else:
        d.rounded_rectangle([vx, 60, W_PX - M, 240], 18, fill="#457b9d")
        d.text((vx + 30, 85), "SIN VETA", fill="white", font=font(40, True))
        d.text((vx + 30, 150), "Rotación 90° permitida", fill="white", font=font(34))

    # ---------------------------------------------------------- zona de dibujo
    table_w = 860
    area = (M + 60, 380, W_PX - table_w - M - 40, H_PX - 260)
    aw, ah = area[2] - area[0], area[3] - area[1]
    s = min(aw / sheet["ancho"], ah / sheet["alto"])
    sw, sh = sheet["ancho"] * s, sheet["alto"] * s
    ox, oy = area[0] + (aw - sw) / 2, area[1] + (ah - sh) / 2

    def box(x, y, w, h):  # mm -> px (origen abajo-izquierda)
        return (ox + x * s, oy + sh - (y + h) * s, ox + (x + w) * s, oy + sh - y * s)

    sheet_box = (ox, oy, ox + sw, oy + sh)
    d.rectangle(sheet_box, fill=SCRAP_BG)
    _hatch(img, sheet_box, SCRAP_LINE, "diag", step=22, width=2)
    # Línea de refilado
    t = sheet["refilado"]
    tb = box(t, t, sheet["ancho"] - 2 * t, sheet["alto"] - 2 * t)
    for i in range(int(tb[0]), int(tb[2]), 24):
        d.line([(i, tb[1]), (min(i + 12, tb[2]), tb[1])], fill="#555", width=2)
        d.line([(i, tb[3]), (min(i + 12, tb[2]), tb[3])], fill="#555", width=2)
    for i in range(int(tb[1]), int(tb[3]), 24):
        d.line([(tb[0], i), (tb[0], min(i + 12, tb[3]))], fill="#555", width=2)
        d.line([(tb[2], i), (tb[2], min(i + 12, tb[3]))], fill="#555", width=2)

    # Retazos recuperables
    for r in sheet["retazos"]:
        b = box(r["x"], r["y"], r["ancho"], r["alto"])
        d.rectangle(b, fill=OFFCUT_BG)
        _hatch(img, b, "#52b788", "diag", step=26, width=3)
        d.rectangle(b, outline=OFFCUT_LINE, width=4)
        _draw_label(img, b, [["RETAZO RECUPERABLE", f"{_fmt(r['ancho'])} × {_fmt(r['alto'])} mm"],
                             ["RETAZO", f"{_fmt(r['ancho'])}×{_fmt(r['alto'])}"], ["R"]])

    # Piezas
    for n, p in enumerate(sheet["piezas"], start=1):
        b = box(p["x"], p["y"], p["ancho"], p["alto"])
        color, pattern = styles.get(p["orden_id"], (PALETTE[0], None))
        d.rectangle(b, fill=color)
        if pattern:
            _hatch(img, b, "#00000040", pattern, step=20, width=2)
        d.rectangle(b, outline="black", width=3)
        dims = f"{_fmt(p['ancho_pieza'])} × {_fmt(p['alto_pieza'])}"
        rot = "  ⟳90°" if p["rotada"] else ""
        comp = f"{p['tipo']} · {p['componente']}" if p["componente"] else p["tipo"]
        _draw_label(img, b, [
            [f"#{n}  {p['orden']}", comp, dims + rot],
            [f"#{n}  {p['orden']}", dims + rot],
            [f"#{n} {p['orden']}"],
            [f"#{n}" + ("⟳" if p["rotada"] else "")],
        ])

    # Cotas generales
    d.text((ox + sw / 2 - 120, oy - 62), f"{_fmt(sheet['ancho'])} mm", fill="black", font=font(40, True))
    tl = Image.new("RGBA", (420, 60), (0, 0, 0, 0))
    ImageDraw.Draw(tl).text((0, 0), f"{_fmt(sheet['alto'])} mm", fill="black", font=font(40, True))
    tl = tl.rotate(90, expand=True)
    img.paste(tl, (int(ox - 75), int(oy + sh / 2 - 200)), tl)
    d.rectangle(sheet_box, outline="black", width=5)

    # ------------------------------------------------------ tabla de piezas
    tx0 = W_PX - table_w - M
    d.text((tx0, 360), "Piezas en la hoja", fill="black", font=font(40, True))
    rows = sheet["piezas"]
    avail = H_PX - 260 - 430
    cols = 1 if len(rows) * 40 <= avail else 2
    per_col = max(1, -(-len(rows) // cols))
    rh = max(18, min(40, avail // max(1, per_col)))
    fs = max(14, min(28, rh - 8))
    cw = table_w // cols
    for n, p in enumerate(rows, start=1):
        c, k = divmod(n - 1, per_col)
        x, y = tx0 + c * cw, 420 + k * rh
        color, _ = styles.get(p["orden_id"], (PALETTE[0], None))
        d.rectangle([x, y + 3, x + rh - 10, y + rh - 7], fill=color, outline="black")
        rot = " ⟳90°" if p["rotada"] else ""
        txt = (f"#{n} {p['orden']} · {p['componente'] or p['tipo']} · "
               f"{_fmt(p['ancho_pieza'])}×{_fmt(p['alto_pieza'])}{rot}")
        f = font(fs)
        while f.getbbox(txt)[2] > cw - rh - 10 and len(txt) > 8:
            txt = txt[:-2]
        d.text((x + rh, y + (rh - fs) / 2 - 2), txt, fill="black", font=f)

    # ------------------------------------------------------------------ pie
    d.rectangle([0, H_PX - 220, W_PX, H_PX], fill="#f1f3f5")
    d.line([(0, H_PX - 220), (W_PX, H_PX - 220)], fill="#adb5bd", width=3)
    stats = (f"Aprovechamiento: {sheet['aprovechamiento']:.1f} %     Merma: {sheet['merma']:.1f} %     "
             f"Retazos recuperables: {sheet['pct_retazos']:.1f} %     Total de piezas: {len(rows)}")
    d.text((M, H_PX - 190), stats, fill="black", font=font(50, True))
    ly = H_PX - 95
    d.rectangle([M, ly, M + 60, ly + 50], fill=SCRAP_BG)
    _hatch(img, (M, ly, M + 60, ly + 50), SCRAP_LINE, "diag", 14, 2)
    d.rectangle([M, ly, M + 60, ly + 50], outline="black", width=2)
    d.text((M + 80, ly + 6), "Merma", fill="black", font=font(34))
    lx = M + 260
    d.rectangle([lx, ly, lx + 60, ly + 50], fill=OFFCUT_BG)
    _hatch(img, (lx, ly, lx + 60, ly + 50), "#52b788", "diag", 14, 3)
    d.rectangle([lx, ly, lx + 60, ly + 50], outline=OFFCUT_LINE, width=3)
    d.text((lx + 80, ly + 6), "Retazo recuperable (reingresa al inventario)", fill="black", font=font(34))
    d.text((lx + 900, ly + 6), "⟳90° = pieza girada respecto a su sentido de veta   ·   "
                               "- - - refilado   ·   cotas en mm", fill="black", font=font(34))

    buf = io.BytesIO()
    img.save(buf, "PNG", dpi=(DPI, DPI), optimize=True)
    return buf.getvalue()


def render_zip(run_label: str, sheets: list[dict], styles: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for s in sheets:
            png = render_sheet(run_label, s, len(sheets), styles)
            z.writestr(f"{run_label}_{s['hoja_id']}_{s['codigo']}.png", png)
    return buf.getvalue()
