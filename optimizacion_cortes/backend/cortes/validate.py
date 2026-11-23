"""Validaciones geométricas (RNF-04, RN-01, RN-02, RN-03, RN-05).

Se usan en las pruebas automáticas y también antes de devolver cada corrida:
si alguna falla, la corrida se rechaza en lugar de entregar un plano inválido.
"""
from __future__ import annotations

from .packing import EPS, PackParams, SheetLayout


def _rects(layout: SheetLayout, k: float):
    """Rectángulos 'inflados' con kerf a la derecha y arriba."""
    rs = [(pl.x, pl.y, pl.w + k, pl.h + k) for pl in layout.placements]
    rs += [(o.x, o.y, o.w + k, o.h + k) for o in layout.offcuts]
    return rs


def _overlap(a, b) -> bool:
    return (a[0] < b[0] + b[2] - EPS and b[0] < a[0] + a[2] - EPS
            and a[1] < b[1] + b[3] - EPS and b[1] < a[1] + a[3] - EPS)


def check_layout(layout: SheetLayout, p: PackParams, pieces=None) -> list[str]:
    errors: list[str] = []
    u = layout.unit
    uid = u.uid
    if layout.used_area > (u.w - 2 * p.trim) * (u.h - 2 * p.trim) + EPS:
        errors.append(f"{uid}: el área de piezas excede el área neta útil")
    for pl in layout.placements:
        if (pl.x < p.trim - EPS or pl.y < p.trim - EPS
                or pl.x + pl.w > u.w - p.trim + EPS
                or pl.y + pl.h > u.h - p.trim + EPS):
            errors.append(f"{uid}: la pieza {pl.piece} sale del área útil")
        if pieces is not None:
            pc = pieces[pl.piece]
            exp = (pc.h, pc.w) if pl.rotated else (pc.w, pc.h)
            if abs(pl.w - exp[0]) > EPS or abs(pl.h - exp[1]) > EPS:
                errors.append(f"{uid}: dimensiones alteradas en pieza {pl.piece}")
        if pl.rotated and not p.allow_rotation:
            errors.append(f"{uid}: pieza {pl.piece} rotada sobre textura direccional")
    rs = _rects(layout, p.kerf)
    for i in range(len(rs)):
        for j in range(i + 1, len(rs)):
            if _overlap(rs[i], rs[j]):
                errors.append(f"{uid}: solapamiento o separación menor al kerf "
                              f"entre elementos {i} y {j}")
    if p.guillotine and not is_guillotine(rs, p.trim, p.trim,
                                          u.w - p.trim + p.kerf, u.h - p.trim + p.kerf):
        errors.append(f"{uid}: el patrón no es cortable en guillotina")
    return errors


def is_guillotine(rects, x0, y0, x1, y1) -> bool:
    """Comprueba recursivamente que exista una secuencia de cortes de borde a
    borde que separe todos los rectángulos (coordenadas infladas)."""
    if len(rects) <= 1:
        return True
    for axis in (0, 1):
        lo, hi = (x0, x1) if axis == 0 else (y0, y1)
        cuts = sorted({r[axis] + r[axis + 2] for r in rects})
        for c in cuts:
            if c <= lo + EPS or c >= hi - EPS:
                continue
            a = [r for r in rects if r[axis] + r[axis + 2] <= c + EPS]
            b = [r for r in rects if r[axis] >= c - EPS]
            if len(a) + len(b) == len(rects) and a and b:
                if axis == 0:
                    return (is_guillotine(a, x0, y0, c, y1)
                            and is_guillotine(b, c, y0, x1, y1))
                return (is_guillotine(a, x0, y0, x1, c)
                        and is_guillotine(b, x0, c, x1, y1))
    return False
