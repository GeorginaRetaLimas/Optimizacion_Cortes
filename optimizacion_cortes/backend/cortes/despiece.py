"""RF-06: explosión de materiales (despiece).

Cada tipo de persiana define sus holguras y una lista de componentes. Las
medidas y cantidades de cada componente son expresiones aritméticas que pueden
usar:  W (ancho final), H (alto final), las holguras del tipo y las funciones
ceil, floor, round, min y max.

Las reglas se guardan en la base de datos y se editan desde la interfaz, de
modo que Ingeniería puede capturar las fórmulas reales sin tocar código.
"""
from __future__ import annotations

import ast
import math
import operator

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod}
_UN = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUN = {"ceil": math.ceil, "floor": math.floor, "round": round, "min": min, "max": max}


class FormulaError(ValueError):
    pass


def evaluate(expr: str, variables: dict[str, float]) -> float:
    """Evalúa una expresión aritmética de forma segura (sin eval)."""
    try:
        tree = ast.parse(str(expr), mode="eval")
    except SyntaxError as e:
        raise FormulaError(f"Sintaxis inválida en '{expr}'") from e

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return n.value
        if isinstance(n, ast.Name):
            if n.id in variables:
                return variables[n.id]
            raise FormulaError(f"Variable desconocida '{n.id}' en '{expr}'")
        if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
            return _BIN[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _UN:
            return _UN[type(n.op)](ev(n.operand))
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUN
                and not n.keywords):
            return _FUN[n.func.id](*[ev(a) for a in n.args])
        raise FormulaError(f"Elemento no permitido en '{expr}'")

    try:
        return float(ev(tree))
    except ZeroDivisionError as e:
        raise FormulaError(f"División entre cero en '{expr}'") from e


def explode(tipo: dict, ancho_final: float, alto_final: float, cantidad: int) -> list[dict]:
    """Devuelve las piezas rectangulares que requiere `cantidad` persianas."""
    vars_ = {"W": float(ancho_final), "H": float(alto_final)}
    for k, v in (tipo.get("holguras") or {}).items():
        vars_[k] = float(v)
    out = []
    for comp in tipo["componentes"]:
        a = round(evaluate(comp["ancho"], vars_), 1)
        h = round(evaluate(comp["alto"], vars_), 1)
        n = evaluate(comp.get("cantidad", "1"), vars_)
        if a <= 0 or h <= 0:
            raise FormulaError(f"El componente '{comp['nombre']}' resulta con medidas no positivas "
                               f"({a} x {h}) para W={ancho_final}, H={alto_final}")
        if n < 1 or abs(n - round(n)) > 1e-9:
            raise FormulaError(f"La cantidad del componente '{comp['nombre']}' debe ser entera >= 1 (dio {n})")
        out.append({"componente": comp["nombre"], "ancho": a, "alto": h,
                    "cantidad": int(round(n)) * int(cantidad),
                    "veta": comp.get("veta", "ancho")})
    return out


def validate_tipo(tipo: dict) -> None:
    """Prueba las fórmulas con medidas de ejemplo para detectar errores."""
    if not tipo.get("nombre"):
        raise FormulaError("El tipo de persiana necesita un nombre")
    if not tipo.get("componentes"):
        raise FormulaError("El tipo de persiana necesita al menos un componente")
    for comp in tipo["componentes"]:
        if not comp.get("nombre"):
            raise FormulaError("Cada componente necesita un nombre")
        if comp.get("veta", "ancho") not in ("ancho", "alto"):
            raise FormulaError("El sentido de veta debe ser 'ancho' o 'alto'")
    explode(tipo, 1500, 1800, 1)


# Reglas iniciales de ejemplo. IMPORTANTE: son valores de referencia para poder
# operar; Ingeniería de SprintWindow debe sustituirlos por sus fórmulas reales.
DEFAULT_TIPOS = [
    {
        "nombre": "Enrollable",
        "descripcion": "Lienzo de PVC enrollable con margen para el tubo.",
        "holguras": {"holgura_lateral": 35, "margen_enrolle": 250},
        "componentes": [
            {"nombre": "Lienzo", "ancho": "W - holgura_lateral", "alto": "H + margen_enrolle",
             "cantidad": "1", "veta": "alto"},
            {"nombre": "Faldón", "ancho": "W - holgura_lateral", "alto": "80", "cantidad": "1",
             "veta": "ancho"},
        ],
    },
    {
        "nombre": "Vertical",
        "descripcion": "Lamas verticales de 89 mm con traslape.",
        "holguras": {"ancho_lama": 89, "traslape": 10, "holgura_alto": 15},
        "componentes": [
            {"nombre": "Lama", "ancho": "ancho_lama", "alto": "H - holgura_alto",
             "cantidad": "ceil(W / (ancho_lama - traslape))", "veta": "alto"},
        ],
    },
    {
        "nombre": "Panel japonés",
        "descripcion": "Paneles deslizantes de hasta 600 mm con traslape.",
        "holguras": {"ancho_max_panel": 600, "traslape": 50, "holgura_alto": 20},
        "componentes": [
            {"nombre": "Panel",
             "ancho": "(W + traslape * (ceil(W / ancho_max_panel) - 1)) / ceil(W / ancho_max_panel)",
             "alto": "H - holgura_alto", "cantidad": "ceil(W / ancho_max_panel)", "veta": "alto"},
        ],
    },
]
