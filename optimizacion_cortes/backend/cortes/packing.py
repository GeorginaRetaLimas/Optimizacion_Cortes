"""Geometría y decodificadores constructivos (sección 4.1 de la ERS).

Convenciones (ver doc/DECISIONES.md):
- Unidades en milímetros. Origen en la esquina inferior izquierda de la hoja.
- Eje X = ancho (W) de la hoja. Si la textura es direccional, la veta corre
  paralela al eje X. Una pieza sin rotar coloca su ancho (W) sobre el eje X.
- Refilado r: banda perimetral que se descarta. Área útil = [r, W-r] x [r, H-r].
- Kerf k (RN-03): se modela "inflando" cada pieza a (w+k, h+k) dentro de una
  caja útil de (W-2r+k) x (H-2r+k). Así entre dos piezas queda siempre un
  espacio >= k, y ninguna pieza invade el refilado (que se valida >= k).
"""
from __future__ import annotations

from dataclasses import dataclass, field

EPS = 1e-6


@dataclass(frozen=True)
class Piece:
    idx: int
    w: float  # ancho de la pieza (va sobre X cuando no está rotada)
    h: float  # alto de la pieza
    order_id: int
    order_rank: int  # posición de la orden en la cola (0 = primero)
    label: str = ""


@dataclass
class SheetUnit:
    uid: str  # identificador único de la unidad física (lote#n)
    lot_id: int
    code: str
    w: float
    h: float
    is_offcut: bool = False
    cost: float = 0.0


@dataclass
class Placement:
    piece: int
    x: float  # coordenadas reales (mm) desde la esquina inferior izquierda
    y: float
    w: float
    h: float
    rotated: bool


@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float


@dataclass
class SheetLayout:
    unit: SheetUnit
    placements: list[Placement] = field(default_factory=list)
    offcuts: list[Rect] = field(default_factory=list)

    @property
    def area(self) -> float:
        return self.unit.w * self.unit.h

    @property
    def used_area(self) -> float:
        return sum(p.w * p.h for p in self.placements)

    @property
    def offcut_area(self) -> float:
        return sum(r.w * r.h for r in self.offcuts)

    @property
    def scrap_area(self) -> float:
        return max(0.0, self.area - self.used_area - self.offcut_area)


@dataclass
class PackParams:
    kerf: float = 3.0
    trim: float = 10.0
    offcut_min_long: float = 300.0
    offcut_min_short: float = 150.0
    guillotine: bool = True
    allow_rotation: bool = True  # False si la textura es direccional (RN-02)


# --------------------------------------------------------------------------
# Bins (en coordenadas "infladas", relativas al área útil)
# --------------------------------------------------------------------------
class _MaxRectsBin:
    """Anidamiento libre: MaxRects con regla Bottom-Left (equivale a BLF)."""

    def __init__(self, W: float, H: float):
        self.W, self.H = W, H
        self.free: list[tuple[float, float, float, float]] = [(0.0, 0.0, W, H)]
        self.used: list[tuple[float, float, float, float]] = []

    def find(self, w: float, h: float):
        best = None
        for fx, fy, fw, fh in self.free:
            if w <= fw + EPS and h <= fh + EPS:
                score = (fy + h, fx)
                if best is None or score < best[0]:
                    best = (score, fx, fy)
        return None if best is None else (best[1], best[2])

    def place(self, x: float, y: float, w: float, h: float) -> None:
        r = (x, y, w, h)
        self.used.append(r)
        new_free = []
        for f in self.free:
            if _intersects(f, r):
                new_free.extend(_split_maxrect(f, r))
            else:
                new_free.append(f)
        self.free = _prune(new_free)


class _GuillotineBin:
    """Corte guillotina: partición recursiva, rectángulos libres disjuntos."""

    def __init__(self, W: float, H: float):
        self.W, self.H = W, H
        self.free: list[tuple[float, float, float, float]] = [(0.0, 0.0, W, H)]
        self.used: list[tuple[float, float, float, float]] = []

    def find(self, w: float, h: float):
        best = None
        for i, (fx, fy, fw, fh) in enumerate(self.free):
            if w <= fw + EPS and h <= fh + EPS:
                score = (fw * fh - w * h, fy, fx)  # Best Area Fit
                if best is None or score < best[0]:
                    best = (score, i)
        if best is None:
            return None
        fx, fy, _, _ = self.free[best[1]]
        return (fx, fy, best[1])

    def place(self, x: float, y: float, w: float, h: float, i: int) -> None:
        fx, fy, fw, fh = self.free.pop(i)
        self.used.append((x, y, w, h))
        rw, th = fw - w, fh - h
        # Regla "Max Area": elige el corte que deja el sobrante más grande
        # (favorece retazos reutilizables, término w3 de la aptitud).
        horiz = [(fx + w, fy, rw, h), (fx, fy + h, fw, th)]
        vert = [(fx + w, fy, rw, fh), (fx, fy + h, w, th)]
        a_h = max(r[2] * r[3] for r in horiz)
        a_v = max(r[2] * r[3] for r in vert)
        for r in (horiz if a_h >= a_v else vert):
            if r[2] > EPS and r[3] > EPS:
                self.free.append(r)


def _intersects(a, b) -> bool:
    return (a[0] < b[0] + b[2] - EPS and b[0] < a[0] + a[2] - EPS
            and a[1] < b[1] + b[3] - EPS and b[1] < a[1] + a[3] - EPS)


def _split_maxrect(f, r):
    fx, fy, fw, fh = f
    rx, ry, rw, rh = r
    out = []
    if rx > fx + EPS:
        out.append((fx, fy, rx - fx, fh))
    if rx + rw < fx + fw - EPS:
        out.append((rx + rw, fy, fx + fw - (rx + rw), fh))
    if ry > fy + EPS:
        out.append((fx, fy, fw, ry - fy))
    if ry + rh < fy + fh - EPS:
        out.append((fx, ry + rh, fw, fy + fh - (ry + rh)))
    return out


def _contains(a, b) -> bool:
    return (b[0] >= a[0] - EPS and b[1] >= a[1] - EPS
            and b[0] + b[2] <= a[0] + a[2] + EPS
            and b[1] + b[3] <= a[1] + a[3] + EPS)


def _prune(rects):
    rects = sorted(set(rects), key=lambda r: -r[2] * r[3])
    kept = []
    for r in rects:
        if not any(_contains(k, r) for k in kept):
            kept.append(r)
    return kept


# --------------------------------------------------------------------------
# Decodificador: cromosoma -> distribución de piezas en hojas
# --------------------------------------------------------------------------
class _OpenSheet:
    def __init__(self, unit: SheetUnit, p: PackParams):
        self.unit = unit
        W = unit.w - 2 * p.trim + p.kerf
        H = unit.h - 2 * p.trim + p.kerf
        self.bin = _GuillotineBin(W, H) if p.guillotine else _MaxRectsBin(W, H)
        self.layout = SheetLayout(unit)


def usable_fits(unit: SheetUnit, w: float, h: float, p: PackParams) -> bool:
    return (w + p.kerf <= unit.w - 2 * p.trim + p.kerf + EPS
            and h + p.kerf <= unit.h - 2 * p.trim + p.kerf + EPS)


def _orientations(piece: Piece, rot_gene: bool, p: PackParams):
    base = [(piece.w, piece.h, False)]
    if not p.allow_rotation or abs(piece.w - piece.h) < EPS:
        return base
    rot = (piece.h, piece.w, True)
    return [rot, base[0]] if rot_gene else [base[0], rot]


def _try_place(sheet: _OpenSheet, piece: Piece, rot_gene: bool, p: PackParams) -> bool:
    k = p.kerf
    for w, h, rotated in _orientations(piece, rot_gene, p):
        found = sheet.bin.find(w + k, h + k)
        if found is None:
            continue
        if p.guillotine:
            x, y, i = found
            sheet.bin.place(x, y, w + k, h + k, i)
        else:
            x, y = found
            sheet.bin.place(x, y, w + k, h + k)
        sheet.layout.placements.append(
            Placement(piece.idx, x + p.trim, y + p.trim, w, h, rotated))
        return True
    return False


def order_stock(units: list[SheetUnit]) -> list[SheetUnit]:
    """Política de apertura de hojas (RF-03): primero retazos (de menor a
    mayor área), después hojas nuevas de mayor a menor área (empate: menor
    costo)."""
    offcuts = sorted((u for u in units if u.is_offcut), key=lambda u: (u.w * u.h, u.uid))
    sheets = sorted((u for u in units if not u.is_offcut),
                    key=lambda u: (-(u.w * u.h), u.cost, u.uid))
    return offcuts + sheets


def decode(chromosome, pieces: list[Piece], stock: list[SheetUnit], p: PackParams,
           with_offcuts: bool = True):
    """Decodificador constructivo. `chromosome` = secuencia de (idx_pieza, rot).

    `stock` debe venir ya ordenado con `order_stock`. Devuelve
    (lista de SheetLayout en orden de apertura, lista de piezas no colocadas).
    """
    open_sheets: list[_OpenSheet] = []
    remaining = list(stock)
    unplaced: list[int] = []
    for idx, rot in chromosome:
        piece = pieces[idx]
        if any(_try_place(s, piece, rot, p) for s in open_sheets):
            continue
        placed = False
        for j, unit in enumerate(remaining):
            fits = usable_fits(unit, piece.w, piece.h, p) or (
                p.allow_rotation and usable_fits(unit, piece.h, piece.w, p))
            if not fits:
                continue
            sheet = _OpenSheet(unit, p)
            if _try_place(sheet, piece, rot, p):
                open_sheets.append(sheet)
                remaining.pop(j)
                placed = True
                break
        if not placed:
            unplaced.append(idx)
    layouts = [s.layout for s in open_sheets]
    if with_offcuts:
        for s in open_sheets:
            s.layout.offcuts = extract_offcuts(s, p)
    return layouts, unplaced


# --------------------------------------------------------------------------
# RN-06: clasificación de sobrantes
# --------------------------------------------------------------------------
def _qualifies(w: float, h: float, p: PackParams) -> bool:
    long_min = max(p.offcut_min_long, p.offcut_min_short)
    short_min = min(p.offcut_min_long, p.offcut_min_short)
    return max(w, h) + EPS >= long_min and min(w, h) + EPS >= short_min


def extract_offcuts(sheet: _OpenSheet, p: PackParams) -> list[Rect]:
    """Devuelve retazos recuperables disjuntos (en coordenadas reales).

    Un rectángulo libre (inflado) de w x h corresponde a un sobrante real de
    (w-k) x (h-k): el kerf del corte que lo separa de la pieza vecina.
    """
    k = p.kerf
    out: list[Rect] = []
    if p.guillotine:
        free = sorted(sheet.bin.free, key=lambda r: -r[2] * r[3])
        for fx, fy, fw, fh in free:
            rw, rh = fw - k, fh - k
            if rw > EPS and rh > EPS and _qualifies(rw, rh, p):
                out.append(Rect(fx + p.trim, fy + p.trim, rw, rh))
        return out
    # Anidamiento libre: los rectángulos libres se traslapan; se extraen de
    # forma voraz el mayor que califique, se marca como ocupado y se repite.
    b = _MaxRectsBin(sheet.bin.W, sheet.bin.H)
    b.free = list(sheet.bin.free)
    while True:
        cands = [f for f in b.free if f[2] - k > EPS and f[3] - k > EPS
                 and _qualifies(f[2] - k, f[3] - k, p)]
        if not cands:
            break
        fx, fy, fw, fh = max(cands, key=lambda r: r[2] * r[3])
        out.append(Rect(fx + p.trim, fy + p.trim, fw - k, fh - k))
        b.place(fx, fy, fw, fh)
    return out
