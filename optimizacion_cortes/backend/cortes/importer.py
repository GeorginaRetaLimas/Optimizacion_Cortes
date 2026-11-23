"""RF-02: carga masiva desde .csv / .xlsx con validación previa.

Primero se valida todo el archivo; solo si no hay errores se permite cargarlo.
Los encabezados no distinguen mayúsculas ni acentos.
"""
from __future__ import annotations

import csv
import io
import unicodedata

from openpyxl import Workbook, load_workbook

LOT_COLUMNS = ["codigo", "ancho", "alto", "espesor", "color", "textura",
               "veta_direccional", "cantidad", "costo_unitario"]
LOT_REQUIRED = ["codigo", "ancho", "alto", "espesor", "color", "textura", "cantidad"]

ORDER_COLUMNS = ["numero", "cliente", "tipo_persiana", "ancho_final", "alto_final", "cantidad",
                 "color", "textura", "espesor", "prioridad"]

ALIASES = {"código": "codigo", "veta": "veta_direccional", "direccionalidad_veta": "veta_direccional",
           "costo": "costo_unitario", "calibre": "espesor", "tipo": "tipo_persiana",
           "orden": "numero", "numero_orden": "numero", "lote": "cliente"}

TRUE = {"1", "si", "sí", "s", "true", "verdadero", "x", "yes", "y"}
FALSE = {"0", "no", "n", "false", "falso", ""}


class ImportFormatError(ValueError):
    pass


def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    s = s.strip().lower().replace(" ", "_").replace("(mm)", "").strip("_")
    return ALIASES.get(s, s)


def read_table(filename: str, data: bytes) -> list[dict]:
    name = filename.lower()
    if name.endswith(".xlsx"):
        try:
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as e:
            raise ImportFormatError("No se pudo leer el archivo .xlsx") from e
        ws = wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        header = next(it, None)
        if not header:
            raise ImportFormatError("El archivo está vacío")
        keys = [_norm(h) for h in header]
        out = []
        for r in it:
            if r is None or all(v in (None, "") for v in r):
                continue
            out.append({k: ("" if v is None else v) for k, v in zip(keys, r)})
        return out
    if name.endswith(".csv"):
        text = None
        for enc in ("utf-8-sig", "latin-1"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        try:
            dialect = csv.Sniffer().sniff(text[:2048], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(io.StringIO(text), dialect)
        header = next(reader, None)
        if not header:
            raise ImportFormatError("El archivo está vacío")
        keys = [_norm(h) for h in header]
        return [dict(zip(keys, r)) for r in reader if any(c.strip() for c in r)]
    raise ImportFormatError("Formato no soportado: use .csv o .xlsx")


def _num(v, field, errors, row, positive=True, integer=False, required=True):
    if v is None or str(v).strip() == "":
        if required:
            errors.append({"fila": row, "campo": field, "mensaje": "Campo obligatorio vacío"})
        return None
    try:
        x = float(str(v).replace(",", ".").strip())
    except ValueError:
        errors.append({"fila": row, "campo": field, "mensaje": f"'{v}' no es un número"})
        return None
    if integer and x != int(x):
        errors.append({"fila": row, "campo": field, "mensaje": "Debe ser un número entero"})
        return None
    if positive and x <= 0:
        errors.append({"fila": row, "campo": field, "mensaje": "Debe ser mayor que cero"})
        return None
    if not positive and x < 0:
        errors.append({"fila": row, "campo": field, "mensaje": "No puede ser negativo"})
        return None
    return int(x) if integer else x


def _text(v, field, errors, row, required=True):
    s = str(v if v is not None else "").strip()
    if required and not s:
        errors.append({"fila": row, "campo": field, "mensaje": "Campo obligatorio vacío"})
    return s


def validate_lots(table: list[dict]) -> tuple[list[dict], list[dict]]:
    errors: list[dict] = []
    valid: list[dict] = []
    if table:
        missing = [c for c in LOT_REQUIRED if c not in table[0]]
        if missing:
            return [], [{"fila": 1, "campo": ", ".join(missing),
                         "mensaje": "Faltan columnas obligatorias en el encabezado"}]
    seen: dict[str, int] = {}
    for i, r in enumerate(table, start=2):  # fila 1 = encabezado
        e0 = len(errors)
        lot = {
            "codigo": _text(r.get("codigo"), "codigo", errors, i),
            "ancho": _num(r.get("ancho"), "ancho", errors, i),
            "alto": _num(r.get("alto"), "alto", errors, i),
            "espesor": _num(r.get("espesor"), "espesor", errors, i),
            "color": _text(r.get("color"), "color", errors, i),
            "textura": _text(r.get("textura"), "textura", errors, i),
            "cantidad": _num(r.get("cantidad"), "cantidad", errors, i, positive=False, integer=True),
            "costo_unitario": _num(r.get("costo_unitario"), "costo_unitario", errors, i,
                                   positive=False, required=False),
        }
        veta = str(r.get("veta_direccional", "")).strip().lower()
        if veta in TRUE:
            lot["veta_direccional"] = True
        elif veta in FALSE:
            lot["veta_direccional"] = False
        else:
            errors.append({"fila": i, "campo": "veta_direccional",
                           "mensaje": f"'{r.get('veta_direccional')}' no es sí/no"})
        if lot["codigo"]:
            if lot["codigo"] in seen:
                errors.append({"fila": i, "campo": "codigo",
                               "mensaje": f"Código repetido (también en la fila {seen[lot['codigo']]})"})
            seen.setdefault(lot["codigo"], i)
        if len(errors) == e0:
            valid.append(lot)
    return valid, errors


def validate_orders(table: list[dict], tipos: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    """Órdenes con despiece automático (tipo de persiana registrado) o
    'Manual', en cuyo caso ancho_final/alto_final son las medidas de la pieza."""
    errors: list[dict] = []
    valid: list[dict] = []
    if table:
        missing = [c for c in ("numero", "tipo_persiana", "ancho_final", "alto_final", "cantidad",
                               "color", "textura", "espesor") if c not in table[0]]
        if missing:
            return [], [{"fila": 1, "campo": ", ".join(missing),
                         "mensaje": "Faltan columnas obligatorias en el encabezado"}]
    seen: set[str] = set()
    for i, r in enumerate(table, start=2):
        e0 = len(errors)
        o = {
            "numero": _text(r.get("numero"), "numero", errors, i),
            "cliente": _text(r.get("cliente"), "cliente", errors, i, required=False),
            "tipo_persiana": _text(r.get("tipo_persiana"), "tipo_persiana", errors, i),
            "ancho_final": _num(r.get("ancho_final"), "ancho_final", errors, i),
            "alto_final": _num(r.get("alto_final"), "alto_final", errors, i),
            "cantidad": _num(r.get("cantidad"), "cantidad", errors, i, integer=True),
            "color": _text(r.get("color"), "color", errors, i),
            "textura": _text(r.get("textura"), "textura", errors, i),
            "espesor": _num(r.get("espesor"), "espesor", errors, i),
        }
        pr = str(r.get("prioridad", "") or "Normal").strip().capitalize()
        if pr not in ("Normal", "Urgente"):
            errors.append({"fila": i, "campo": "prioridad", "mensaje": "Use Normal o Urgente"})
        o["prioridad"] = pr
        if o["tipo_persiana"] and o["tipo_persiana"] != "Manual" and o["tipo_persiana"] not in tipos:
            errors.append({"fila": i, "campo": "tipo_persiana",
                           "mensaje": f"Tipo '{o['tipo_persiana']}' no registrado"})
        if o["numero"] in seen:
            errors.append({"fila": i, "campo": "numero", "mensaje": "Número de orden repetido"})
        seen.add(o["numero"])
        if len(errors) == e0:
            valid.append(o)
    return valid, errors


def template(kind: str, fmt: str) -> bytes:
    if kind == "lotes":
        cols = LOT_COLUMNS
        sample = [["PVC-BL-2440", 2440, 1220, 3, "Blanco", "Liso", "no", 20, 850],
                  ["PVC-NO-2440", 2440, 1220, 3, "Nogal", "Veta madera", "sí", 10, 1100]]
    else:
        cols = ORDER_COLUMNS
        sample = [["OP-1001", "Cliente A", "Vertical", 1500, 1800, 1, "Blanco", "Liso", 3, "Normal"],
                  ["OP-1002", "Cliente B", "Manual", 600, 400, 8, "Nogal", "Veta madera", 3, "Urgente"]]
    if fmt == "xlsx":
        wb = Workbook()
        ws = wb.active
        ws.append(cols)
        for s in sample:
            ws.append(s)
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    w.writerows(sample)
    return buf.getvalue().encode("utf-8-sig")
