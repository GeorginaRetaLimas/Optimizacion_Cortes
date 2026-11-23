"""API web del Sistema de Optimización de Corte (SprintWindow).

Ejecutar:  python app.py   (sirve la API en /api y el frontend compilado en /)
"""
from __future__ import annotations

import io
import json
import os
import threading
from functools import wraps

from flask import Flask, abort, jsonify, request, send_file, send_from_directory
from PIL import Image

from cortes import db
from cortes.despiece import FormulaError, explode, validate_tipo
from cortes.importer import ImportFormatError, read_table, template, validate_lots, validate_orders
from cortes.optimizer import OptimizationError, optimize
from cortes.render import order_styles, render_sheet, render_zip

BASE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(BASE, "..", "frontend", "dist")

PARAM_RULES = {  # RF-09: validación de parámetros (tipo, mínimo, máximo)
    "kerf": (float, 0, 50), "refilado": (float, 0, 200),
    "retazo_min_largo": (float, 1, 10000), "retazo_min_ancho": (float, 1, 10000),
    "w1": (float, 0, 100), "w2": (float, 0, 100), "w3": (float, 0, 100), "w4": (float, 0, 100),
    "ventana_tolerancia": (int, 0, 1000), "peso_urgente": (float, 1, 100),
    "poblacion": (int, 4, 1000), "generaciones": (int, 1, 100000), "estancamiento": (int, 1, 100000),
    "tiempo_max": (float, 1, 600), "prob_cruce": (float, 0, 1), "prob_mutacion": (float, 0, 1),
}


def create_app(db_path: str | None = None) -> Flask:
    app = Flask(__name__, static_folder=None)
    db_path = db_path or os.environ.get("SPRINTWINDOW_DB", os.path.join(BASE, "data", "cortes.db"))
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    con = db.connect(db_path)
    db.init(con)
    lock = threading.RLock()  # SQLite + una sola optimización a la vez
    opt_lock = threading.Lock()
    admin_pin = os.environ.get("SPRINTWINDOW_ADMIN_PIN", "1234")
    png_cache: dict = {}

    def err(msg, code=400, **extra):
        return jsonify({"error": msg, **extra}), code

    def admin(f):
        @wraps(f)
        def wrapper(*a, **k):
            if request.headers.get("X-Admin-Pin") != admin_pin:
                return err("Se requiere el PIN de administrador", 403)
            return f(*a, **k)
        return wrapper

    def body() -> dict:
        return request.get_json(silent=True) or {}

    # ------------------------------------------------------------- generales
    @app.get("/api/estado")
    def estado():
        with lock:
            r = con.execute("""SELECT
                (SELECT COALESCE(SUM(cantidad),0) FROM lotes WHERE es_retazo=0) AS hojas,
                (SELECT COALESCE(SUM(cantidad),0) FROM lotes WHERE es_retazo=1) AS retazos,
                (SELECT COUNT(*) FROM ordenes WHERE estado='pendiente') AS ordenes""").fetchone()
            return jsonify(dict(r))

    @app.post("/api/admin/verificar")
    def verificar_admin():
        return jsonify({"ok": body().get("pin") == admin_pin})

    # ---------------------------------------------- RF-01 / RF-03: inventario
    def _lot_from_body(b: dict, es_retazo: bool):
        row = {k: b.get(k, "") for k in ("codigo", "ancho", "alto", "espesor", "color", "textura",
                                         "cantidad", "costo_unitario")}
        row["veta_direccional"] = "si" if b.get("veta_direccional") in (True, 1, "1", "si", "sí", "true") else "no"
        valid, errors = validate_lots([row])
        if errors:
            return None, errors
        lot = valid[0]
        lot["es_retazo"] = 1 if es_retazo else 0
        return lot, []

    @app.get("/api/lotes")
    def lotes():
        q = "SELECT * FROM lotes"
        args: tuple = ()
        if request.args.get("retazos") in ("0", "1"):
            q += " WHERE es_retazo = ?"
            args = (int(request.args["retazos"]),)
        with lock:
            return jsonify(db.rows(con.execute(q + " ORDER BY es_retazo, color, textura, codigo", args)))

    @app.post("/api/lotes")
    def crear_lote():
        b = body()
        lot, errors = _lot_from_body(b, bool(b.get("es_retazo")))
        if errors:
            return err("Datos inválidos", errores=errors)
        with lock:
            if con.execute("SELECT 1 FROM lotes WHERE codigo=?", (lot["codigo"],)).fetchone():
                return err(f"Ya existe un lote con código {lot['codigo']}", 409)
            with db.tx(con):
                cur = con.execute(
                    "INSERT INTO lotes(codigo, ancho, alto, espesor, color, textura, veta_direccional,"
                    " cantidad, costo_unitario, es_retazo, origen) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (lot["codigo"], lot["ancho"], lot["alto"], lot["espesor"], lot["color"], lot["textura"],
                     int(lot["veta_direccional"]), lot["cantidad"], lot["costo_unitario"], lot["es_retazo"],
                     "captura manual"))
                db.obsolete_runs(con)
            return jsonify(dict(con.execute("SELECT * FROM lotes WHERE id=?", (cur.lastrowid,)).fetchone())), 201

    @app.put("/api/lotes/<int:lid>")
    def editar_lote(lid):
        b = body()
        with lock:
            old = con.execute("SELECT * FROM lotes WHERE id=?", (lid,)).fetchone()
            if not old:
                return err("Lote no encontrado", 404)
            merged = {**dict(old), **b}
            lot, errors = _lot_from_body(merged, bool(merged.get("es_retazo")))
            if errors:
                return err("Datos inválidos", errores=errors)
            dup = con.execute("SELECT 1 FROM lotes WHERE codigo=? AND id<>?", (lot["codigo"], lid)).fetchone()
            if dup:
                return err(f"Ya existe un lote con código {lot['codigo']}", 409)
            with db.tx(con):
                con.execute("UPDATE lotes SET codigo=?, ancho=?, alto=?, espesor=?, color=?, textura=?,"
                            " veta_direccional=?, cantidad=?, costo_unitario=?, es_retazo=? WHERE id=?",
                            (lot["codigo"], lot["ancho"], lot["alto"], lot["espesor"], lot["color"],
                             lot["textura"], int(lot["veta_direccional"]), lot["cantidad"],
                             lot["costo_unitario"], lot["es_retazo"], lid))
                db.obsolete_runs(con)
            return jsonify(dict(con.execute("SELECT * FROM lotes WHERE id=?", (lid,)).fetchone()))

    @app.delete("/api/lotes/<int:lid>")
    def borrar_lote(lid):
        with lock, db.tx(con):
            con.execute("DELETE FROM lotes WHERE id=?", (lid,))
            db.obsolete_runs(con)
        return jsonify({"ok": True})

    # ------------------------------------------------- RF-02: carga masiva
    @app.post("/api/lotes/importar")
    def importar_lotes():
        f = request.files.get("archivo")
        if not f:
            return err("Adjunte un archivo .csv o .xlsx en el campo 'archivo'")
        try:
            table = read_table(f.filename, f.read())
        except ImportFormatError as e:
            return err(str(e))
        valid, errors = validate_lots(table)
        if not table:
            errors.append({"fila": 1, "campo": "", "mensaje": "El archivo no contiene filas de datos"})
        resp = {"filas": len(table), "validas": len(valid), "errores": errors,
                "vista_previa": valid[:50], "cargado": False}
        if request.form.get("confirmar") == "1" and not errors:
            with lock, db.tx(con):
                nuevos = actualizados = 0
                for lot in valid:
                    ex = con.execute("SELECT id FROM lotes WHERE codigo=?", (lot["codigo"],)).fetchone()
                    vals = (lot["ancho"], lot["alto"], lot["espesor"], lot["color"], lot["textura"],
                            int(lot["veta_direccional"]), lot["cantidad"], lot["costo_unitario"])
                    if ex:
                        con.execute("UPDATE lotes SET ancho=?, alto=?, espesor=?, color=?, textura=?,"
                                    " veta_direccional=?, cantidad=?, costo_unitario=? WHERE id=?",
                                    vals + (ex["id"],))
                        actualizados += 1
                    else:
                        con.execute("INSERT INTO lotes(codigo, ancho, alto, espesor, color, textura,"
                                    " veta_direccional, cantidad, costo_unitario, origen)"
                                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                                    (lot["codigo"],) + vals + (f"importación {f.filename}",))
                        nuevos += 1
                db.obsolete_runs(con)
            resp.update(cargado=True, nuevos=nuevos, actualizados=actualizados)
        return jsonify(resp), (200 if not errors else 422)

    @app.get("/api/plantillas/<kind>.<fmt>")
    def plantilla(kind, fmt):
        if kind not in ("lotes", "ordenes") or fmt not in ("csv", "xlsx"):
            abort(404)
        mime = "text/csv" if fmt == "csv" else \
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return send_file(io.BytesIO(template(kind, fmt)), mimetype=mime, as_attachment=True,
                         download_name=f"plantilla_{kind}.{fmt}")

    # ----------------------------------------------------- RF-06: despiece
    @app.get("/api/tipos")
    def tipos():
        with lock:
            return jsonify(db.get_tipos(con))

    @app.put("/api/tipos/<path:nombre>")
    @admin
    def guardar_tipo(nombre):
        t = body()
        t["nombre"] = nombre
        try:
            validate_tipo(t)
        except FormulaError as e:
            return err(str(e))
        with lock, db.tx(con):
            db.save_tipo(con, t)
        return jsonify(t)

    @app.delete("/api/tipos/<path:nombre>")
    @admin
    def borrar_tipo(nombre):
        with lock, db.tx(con):
            con.execute("DELETE FROM tipos_persiana WHERE nombre=?", (nombre,))
        return jsonify({"ok": True})

    @app.post("/api/despiece")
    def despiece_preview():
        b = body()
        try:
            if b.get("tipo") is not None:
                tipo = b["tipo"]
            else:
                with lock:
                    tipo = db.get_tipo(con, b.get("tipo_persiana", ""))
                if not tipo:
                    return err("Tipo de persiana no registrado")
            return jsonify(explode(tipo, float(b["ancho_final"]), float(b["alto_final"]),
                                   int(b.get("cantidad", 1))))
        except (FormulaError, KeyError, ValueError, TypeError) as e:
            return err(f"No se pudo calcular el despiece: {e}")

    # --------------------------------------- RF-04 / RF-05: cola de órdenes
    def _build_order(b: dict):
        """Valida una orden y calcula sus piezas. Devuelve (orden, piezas, errores)."""
        with lock:
            tipos = {t["nombre"]: t for t in db.get_tipos(con)}
        manual = b.get("tipo_persiana") == "Manual"
        row = {k: b.get(k, "") for k in ("numero", "cliente", "tipo_persiana", "ancho_final", "alto_final",
                                         "cantidad", "color", "textura", "espesor", "prioridad")}
        if manual and b.get("piezas"):
            row["ancho_final"] = row["ancho_final"] or 1
            row["alto_final"] = row["alto_final"] or 1
            row["cantidad"] = row["cantidad"] or 1
        valid, errors = validate_orders([row], tipos)
        if errors:
            return None, None, errors
        o = valid[0]
        try:
            if manual:
                if b.get("piezas"):
                    piezas = []
                    for i, p in enumerate(b["piezas"], start=1):
                        a, h, n = float(p["ancho"]), float(p["alto"]), int(p["cantidad"])
                        if a <= 0 or h <= 0 or n <= 0:
                            raise ValueError(f"pieza {i}: medidas y cantidad deben ser positivas")
                        veta = p.get("veta", "ancho")
                        if veta not in ("ancho", "alto"):
                            raise ValueError(f"pieza {i}: veta debe ser 'ancho' o 'alto'")
                        piezas.append({"componente": p.get("componente") or f"Pieza {i}",
                                       "ancho": a, "alto": h, "cantidad": n, "veta": veta})
                else:
                    piezas = [{"componente": "Pieza", "ancho": o["ancho_final"], "alto": o["alto_final"],
                               "cantidad": o["cantidad"], "veta": b.get("veta", "ancho")}]
            else:
                piezas = explode(tipos[o["tipo_persiana"]], o["ancho_final"], o["alto_final"], o["cantidad"])
        except (FormulaError, ValueError, KeyError, TypeError) as e:
            return None, None, [{"fila": 0, "campo": "piezas", "mensaje": str(e)}]
        return o, piezas, []

    def _insert_order(o: dict, piezas: list[dict]) -> int:
        if o["prioridad"] == "Urgente":
            # Las urgentes nuevas entran detrás de las urgentes ya existentes
            r = con.execute("SELECT COALESCE(MAX(posicion), -1) FROM ordenes WHERE estado='pendiente'"
                            " AND prioridad='Urgente'").fetchone()
            pos = int(r[0]) + 1
            con.execute("UPDATE ordenes SET posicion = posicion + 1 WHERE estado='pendiente' AND posicion >= ?",
                        (pos,))
        else:
            pos = db.next_position(con)
        cur = con.execute("INSERT INTO ordenes(numero, cliente, tipo_persiana, ancho_final, alto_final, cantidad,"
                          " color, textura, espesor, prioridad, posicion) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                          (o["numero"], o["cliente"], o["tipo_persiana"], o["ancho_final"], o["alto_final"],
                           o["cantidad"], o["color"], o["textura"], o["espesor"], o["prioridad"], pos))
        oid = cur.lastrowid
        for p in piezas:
            con.execute("INSERT INTO piezas(orden_id, componente, ancho, alto, cantidad, veta)"
                        " VALUES (?,?,?,?,?,?)",
                        (oid, p["componente"], p["ancho"], p["alto"], p["cantidad"], p.get("veta", "ancho")))
        db.normalize_positions(con)
        return oid

    @app.get("/api/ordenes")
    def ordenes():
        est = request.args.get("estado", "pendiente")
        with lock:
            return jsonify(db.get_orders(con, None if est == "todas" else est))

    @app.post("/api/ordenes")
    def crear_orden():
        o, piezas, errors = _build_order(body())
        if errors:
            return err("Datos inválidos", errores=errors)
        with lock:
            if con.execute("SELECT 1 FROM ordenes WHERE numero=?", (o["numero"],)).fetchone():
                return err(f"Ya existe la orden {o['numero']}", 409)
            with db.tx(con):
                oid = _insert_order(o, piezas)
                db.obsolete_runs(con)
            return jsonify(next(x for x in db.get_orders(con, None) if x["id"] == oid)), 201

    @app.put("/api/ordenes/<int:oid>")
    def editar_orden(oid):
        b = body()
        with lock:
            old = con.execute("SELECT * FROM ordenes WHERE id=?", (oid,)).fetchone()
            if not old:
                return err("Orden no encontrada", 404)
            cut = con.execute("SELECT COALESCE(SUM(cortadas),0) FROM piezas WHERE orden_id=?", (oid,)).fetchone()[0]
        merged = {**dict(old), **b}
        if cut:
            # Con piezas ya cortadas solo se permiten cambios administrativos
            with lock, db.tx(con):
                pr = merged["prioridad"] if merged["prioridad"] in ("Normal", "Urgente") else old["prioridad"]
                con.execute("UPDATE ordenes SET cliente=?, prioridad=? WHERE id=?", (merged["cliente"], pr, oid))
                db.obsolete_runs(con)
        else:
            if "piezas" not in b and merged["tipo_persiana"] == "Manual":
                with lock:
                    merged["piezas"] = db.rows(con.execute("SELECT componente, ancho, alto, cantidad, veta"
                                                           " FROM piezas WHERE orden_id=?", (oid,)))
            o, piezas, errors = _build_order(merged)
            if errors:
                return err("Datos inválidos", errores=errors)
            with lock:
                dup = con.execute("SELECT 1 FROM ordenes WHERE numero=? AND id<>?", (o["numero"], oid)).fetchone()
                if dup:
                    return err(f"Ya existe la orden {o['numero']}", 409)
                with db.tx(con):
                    con.execute("UPDATE ordenes SET numero=?, cliente=?, tipo_persiana=?, ancho_final=?,"
                                " alto_final=?, cantidad=?, color=?, textura=?, espesor=?, prioridad=?"
                                " WHERE id=?",
                                (o["numero"], o["cliente"], o["tipo_persiana"], o["ancho_final"],
                                 o["alto_final"], o["cantidad"], o["color"], o["textura"], o["espesor"],
                                 o["prioridad"], oid))
                    con.execute("DELETE FROM piezas WHERE orden_id=?", (oid,))
                    for p in piezas:
                        con.execute("INSERT INTO piezas(orden_id, componente, ancho, alto, cantidad, veta)"
                                    " VALUES (?,?,?,?,?,?)",
                                    (oid, p["componente"], p["ancho"], p["alto"], p["cantidad"],
                                     p.get("veta", "ancho")))
                    db.obsolete_runs(con)
        with lock:
            return jsonify(next(x for x in db.get_orders(con, None) if x["id"] == oid))

    @app.delete("/api/ordenes/<int:oid>")
    def borrar_orden(oid):
        with lock, db.tx(con):
            con.execute("DELETE FROM ordenes WHERE id=?", (oid,))
            db.normalize_positions(con)
            db.obsolete_runs(con)
        return jsonify({"ok": True})

    @app.post("/api/ordenes/reordenar")
    def reordenar():
        ids = body().get("ids")
        with lock:
            current = {r[0] for r in con.execute("SELECT id FROM ordenes WHERE estado='pendiente'")}
            if not isinstance(ids, list) or set(ids) != current or len(ids) != len(current):
                return err("La lista debe contener exactamente las órdenes pendientes")
            with db.tx(con):
                for pos, oid in enumerate(ids):
                    con.execute("UPDATE ordenes SET posicion=? WHERE id=?", (pos, oid))
                db.obsolete_runs(con)
            return jsonify(db.get_orders(con))

    @app.post("/api/ordenes/importar")
    def importar_ordenes():
        f = request.files.get("archivo")
        if not f:
            return err("Adjunte un archivo .csv o .xlsx en el campo 'archivo'")
        try:
            table = read_table(f.filename, f.read())
        except ImportFormatError as e:
            return err(str(e))
        with lock:
            tipos = {t["nombre"]: t for t in db.get_tipos(con)}
            existing = {r[0] for r in con.execute("SELECT numero FROM ordenes")}
        valid, errors = validate_orders(table, tipos)
        built = []
        for i, o in enumerate(valid):
            if o["numero"] in existing:
                errors.append({"fila": 0, "campo": "numero", "mensaje": f"La orden {o['numero']} ya existe"})
                continue
            oo, piezas, e = _build_order(o)
            if e:
                errors.extend({**x, "mensaje": f"{o['numero']}: {x['mensaje']}"} for x in e)
            else:
                built.append((oo, piezas))
        if not table:
            errors.append({"fila": 1, "campo": "", "mensaje": "El archivo no contiene filas de datos"})
        resp = {"filas": len(table), "validas": len(built), "errores": errors, "cargado": False}
        if request.form.get("confirmar") == "1" and not errors:
            with lock, db.tx(con):
                for oo, piezas in built:
                    _insert_order(oo, piezas)
                db.obsolete_runs(con)
            resp["cargado"] = True
        return jsonify(resp), (200 if not errors else 422)

    # --------------------------------------------------- RF-09: parámetros
    @app.get("/api/parametros")
    def parametros():
        with lock:
            return jsonify(db.get_params(con))

    @app.put("/api/parametros")
    @admin
    def guardar_parametros():
        b = body()
        clean, errors = {}, []
        for k, v in b.items():
            if k in PARAM_RULES:
                typ, lo, hi = PARAM_RULES[k]
                try:
                    x = typ(float(v)) if typ is int else float(v)
                    if typ is int and float(v) != int(float(v)):
                        raise ValueError
                except (TypeError, ValueError):
                    errors.append(f"{k}: valor inválido")
                    continue
                if not lo <= x <= hi:
                    errors.append(f"{k}: debe estar entre {lo} y {hi}")
                    continue
                clean[k] = x
            elif k == "modo_corte":
                if v not in ("guillotina", "libre"):
                    errors.append("modo_corte: use 'guillotina' o 'libre'")
                else:
                    clean[k] = v
            elif k == "cruce":
                if v not in ("OX", "PMX"):
                    errors.append("cruce: use 'OX' o 'PMX'")
                else:
                    clean[k] = v
            elif k == "semilla":
                clean[k] = None if v in (None, "") else int(v)
        with lock:
            merged = {**db.get_params(con), **clean}
            if merged["refilado"] < merged["kerf"]:
                errors.append("refilado: debe ser mayor o igual al kerf (RN-03)")
            if errors:
                return err("Parámetros inválidos", errores=errors)
            with db.tx(con):
                db.set_params(con, clean)
                db.obsolete_runs(con)
            return jsonify(db.get_params(con))

    # ------------------------------------- RF-08 / RF-10: optimización
    def _run_label(rid: int) -> str:
        return f"C-{rid:04d}"

    def _run(rid: int):
        r = con.execute("SELECT * FROM corridas WHERE id=?", (rid,)).fetchone()
        if not r:
            return None
        return {"id": r["id"], "etiqueta": _run_label(r["id"]), "creado": r["creado"], "estado": r["estado"],
                "parametros": json.loads(r["parametros"]), **json.loads(r["resultado"])}

    @app.post("/api/corridas")
    def optimizar():
        b = body()
        if not opt_lock.acquire(blocking=False):
            return err("Ya hay una optimización en curso", 409)
        try:
            with lock:
                params = db.get_params(con)
                lots = db.rows(con.execute("SELECT * FROM lotes WHERE cantidad > 0"))
                orders = [o for o in db.get_orders(con) if o["piezas_pendientes"] > 0]
            if b.get("tiempo_max"):
                params["tiempo_max"] = max(1.0, min(float(b["tiempo_max"]), float(params["tiempo_max"])))
            if not orders:
                return err("No hay órdenes pendientes en la cola")
            try:
                result = optimize(lots, orders, params)
            except OptimizationError as e:
                return err(str(e), 422)
            with lock, db.tx(con):
                db.obsolete_runs(con)
                cur = con.execute("INSERT INTO corridas(parametros, resultado) VALUES (?, ?)",
                                  (json.dumps(params), json.dumps(result)))
                rid = cur.lastrowid
            with lock:
                return jsonify(_run(rid)), 201
        finally:
            opt_lock.release()

    @app.get("/api/corridas")
    def corridas():
        with lock:
            out = []
            for r in con.execute("SELECT id, creado, estado, resultado FROM corridas ORDER BY id DESC LIMIT 50"):
                m = json.loads(r["resultado"])["metricas"]
                out.append({"id": r["id"], "etiqueta": _run_label(r["id"]), "creado": r["creado"],
                            "estado": r["estado"], "metricas": m})
            return jsonify(out)

    @app.get("/api/corridas/<int:rid>")
    def corrida(rid):
        with lock:
            run = _run(rid)
        return jsonify(run) if run else err("Corrida no encontrada", 404)

    def _styles(run):
        seen = []
        for s in run["hojas"]:
            for p in s["piezas"]:
                if p["orden_id"] not in seen:
                    seen.append(p["orden_id"])
        return order_styles(seen)

    @app.get("/api/corridas/<int:rid>/hojas/<hoja>.png")
    def plano(rid, hoja):
        thumb = request.args.get("miniatura") == "1"
        key = (rid, hoja, thumb)
        if key not in png_cache:
            with lock:
                run = _run(rid)
            if not run:
                abort(404)
            sheet = next((s for s in run["hojas"] if s["hoja_id"] == hoja), None)
            if not sheet:
                abort(404)
            png = render_sheet(run["etiqueta"], sheet, len(run["hojas"]), _styles(run))
            if thumb:
                im = Image.open(io.BytesIO(png))
                im.thumbnail((1100, 1100))
                buf = io.BytesIO()
                im.save(buf, "PNG")
                png = buf.getvalue()
            if len(png_cache) > 400:
                png_cache.clear()
            png_cache[key] = png
        dl = request.args.get("descargar") == "1"
        return send_file(io.BytesIO(png_cache[key]), mimetype="image/png", as_attachment=dl,
                         download_name=f"{_run_label(rid)}_{hoja}.png")

    @app.get("/api/corridas/<int:rid>/planos.zip")
    def planos_zip(rid):
        with lock:
            run = _run(rid)
        if not run:
            abort(404)
        data = render_zip(run["etiqueta"], run["hojas"], _styles(run))
        return send_file(io.BytesIO(data), mimetype="application/zip", as_attachment=True,
                         download_name=f"planos_{run['etiqueta']}.zip")

    @app.post("/api/corridas/<int:rid>/confirmar")
    def confirmar(rid):
        """Confirma la orden de corte: descuenta inventario, da de alta los
        retazos recuperables (RN-06 -> RF-03) y registra las piezas cortadas."""
        with lock:
            run = _run(rid)
            if not run:
                return err("Corrida no encontrada", 404)
            if run["estado"] != "simulada":
                return err(f"La corrida está {run['estado']}; vuelva a optimizar con los datos actuales", 409)
            used: dict[int, int] = {}
            cut: dict[int, int] = {}
            for s in run["hojas"]:
                used[s["lote_id"]] = used.get(s["lote_id"], 0) + 1
                for p in s["piezas"]:
                    cut[p["pieza_id"]] = cut.get(p["pieza_id"], 0) + 1
            for lid, n in used.items():
                r = con.execute("SELECT codigo, cantidad FROM lotes WHERE id=?", (lid,)).fetchone()
                if not r or r["cantidad"] < n:
                    return err("El inventario cambió desde la simulación; vuelva a optimizar", 409)
            with db.tx(con):
                for lid, n in used.items():
                    con.execute("UPDATE lotes SET cantidad = cantidad - ? WHERE id=?", (n, lid))
                    con.execute("DELETE FROM lotes WHERE id=? AND es_retazo=1 AND cantidad=0", (lid,))
                k = 0
                for s in run["hojas"]:
                    for r in s["retazos"]:
                        k += 1
                        costo = (s["costo_unitario"] * (r["ancho"] * r["alto"]) / s["area"]
                                 if s["costo_unitario"] else None)
                        con.execute(
                            "INSERT INTO lotes(codigo, ancho, alto, espesor, color, textura, veta_direccional,"
                            " cantidad, costo_unitario, es_retazo, origen) VALUES (?,?,?,?,?,?,?,1,?,1,?)",
                            (f"RZ-{run['etiqueta']}-{k:03d}", round(r["ancho"], 1), round(r["alto"], 1),
                             s["espesor"], s["color"], s["textura"], int(s["veta_direccional"]),
                             round(costo, 2) if costo else None,
                             f"{run['etiqueta']} {s['hoja_id']}"))
                for pid, n in cut.items():
                    con.execute("UPDATE piezas SET cortadas = MIN(cantidad, cortadas + ?) WHERE id=?", (n, pid))
                con.execute("""UPDATE ordenes SET estado='cortada' WHERE estado='pendiente' AND NOT EXISTS
                               (SELECT 1 FROM piezas p WHERE p.orden_id = ordenes.id AND p.cortadas < p.cantidad)""")
                db.normalize_positions(con)
                con.execute("UPDATE corridas SET estado='confirmada' WHERE id=?", (rid,))
                db.obsolete_runs(con)
            return jsonify({"ok": True, "retazos_dados_de_alta": k,
                            "hojas_descontadas": sum(used.values()), "corrida": _run(rid)})

    # --------------------------------------------------------------- frontend
    @app.get("/")
    @app.get("/<path:path>")
    def frontend(path="index.html"):
        if path.startswith("api/"):
            abort(404)
        full = os.path.join(DIST, path)
        if not os.path.isfile(full):
            path = "index.html"
        if not os.path.isfile(os.path.join(DIST, path)):
            return ("Frontend no compilado. Ejecute 'npm install && npm run build' en la carpeta frontend.",
                    503)
        return send_from_directory(DIST, path)

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    create_app().run(host="0.0.0.0", port=port, debug=False, threaded=True)
