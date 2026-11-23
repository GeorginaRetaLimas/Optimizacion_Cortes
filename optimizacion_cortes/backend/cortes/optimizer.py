"""Orquestación del motor (RF-07, RF-08, RF-10).

1. Particiona órdenes e inventario por material (color, textura, espesor).
2. Corre un algoritmo genético independiente por cada subproblema.
3. Arma la secuencia global de corte respetando la cola (RN-04) y calcula las
   métricas de simulación (RF-10).
"""
from __future__ import annotations

import time
from collections import defaultdict

from .ga import FitnessParams, GAParams, GeneticOptimizer
from .packing import PackParams, Piece, SheetUnit, order_stock
from .validate import check_layout


class OptimizationError(Exception):
    pass


def material_key(color: str, textura: str, espesor) -> tuple:
    return (str(color).strip().lower(), str(textura).strip().lower(), round(float(espesor), 3))


def material_label(sample: dict) -> str:
    return f"{sample['color']} / {sample['textura']} / {float(sample['espesor']):g} mm"


def optimize(lots: list[dict], orders: list[dict], params: dict) -> dict:
    t0 = time.monotonic()
    if params["refilado"] < params["kerf"]:
        raise OptimizationError("El margen de refilado debe ser mayor o igual al kerf (RN-03).")

    orders = sorted(orders, key=lambda o: o["posicion"])
    queue_rank = {o["id"]: r for r, o in enumerate(orders)}

    # ---------------------------------------------------- RF-07: particionado
    groups: dict[tuple, dict] = defaultdict(lambda: {"orders": [], "lots": []})
    for o in orders:
        groups[material_key(o["color"], o["textura"], o["espesor"])]["orders"].append(o)
    for lot in lots:
        if lot["cantidad"] > 0:
            groups[material_key(lot["color"], lot["textura"], lot["espesor"])]["lots"].append(lot)
    groups = {k: g for k, g in groups.items() if g["orders"]}

    total_pieces = sum(pc["pendientes"] for o in orders for pc in o["piezas"]) or 1
    t_budget = float(params["tiempo_max"])

    sheets_out: list[dict] = []
    order_status: dict[int, dict] = {}
    group_summaries = []
    displacement_all: dict[int, int] = {}

    for key, g in groups.items():
        # Piezas del subproblema (una por unidad pendiente de cortar)
        pieces: list[Piece] = []
        meta: list[dict] = []
        for o in g["orders"]:
            for pc in o["piezas"]:
                # Orientación canónica: la dimensión que debe seguir la veta va
                # sobre el eje X de la hoja (RN-02). veta = "ancho" | "alto".
                swap = pc.get("veta", "ancho") == "alto"
                w, h = float(pc["ancho"]), float(pc["alto"])
                if swap:
                    w, h = h, w
                for n in range(int(pc["pendientes"])):
                    pieces.append(Piece(len(pieces), w, h, o["id"], queue_rank[o["id"]]))
                    meta.append({"order": o, "piece": pc, "swap": swap})
        if not pieces:
            continue
        # Inventario del subproblema (una unidad por hoja física)
        units = []
        for lot in g["lots"]:
            for n in range(int(lot["cantidad"])):
                units.append(SheetUnit(f"{lot['codigo']}#{n + 1}", lot["id"], lot["codigo"],
                                       float(lot["ancho"]), float(lot["alto"]),
                                       bool(lot.get("es_retazo")),
                                       float(lot.get("costo_unitario") or 0)))
        directional = any(bool(l["veta_direccional"]) for l in g["lots"]) or any(
            bool(o.get("veta_direccional")) for o in g["orders"])
        pack = PackParams(kerf=float(params["kerf"]), trim=float(params["refilado"]),
                          offcut_min_long=float(params["retazo_min_largo"]),
                          offcut_min_short=float(params["retazo_min_ancho"]),
                          guillotine=params["modo_corte"] == "guillotina",
                          allow_rotation=not directional)
        fit = FitnessParams(w1=float(params["w1"]), w2=float(params["w2"]), w3=float(params["w3"]),
                            w4=float(params["w4"]),
                            window=int(params["ventana_tolerancia"]),
                            urgent_weight=float(params["peso_urgente"]))
        share = max(1.0, t_budget * len(pieces) / total_pieces)
        ga = GAParams(population=int(params["poblacion"]), generations=int(params["generaciones"]),
                      stagnation=int(params["estancamiento"]), time_limit=share,
                      crossover=params["cruce"], crossover_rate=float(params["prob_cruce"]),
                      mutation_rate=float(params["prob_mutacion"]),
                      seed=params.get("semilla"))
        prio = {o["id"]: (fit.urgent_weight if o["prioridad"] == "Urgente" else 1.0)
                for o in g["orders"]}
        result = GeneticOptimizer(pieces, order_stock(units), pack, fit, ga, prio).run()
        best = result.best

        errors = [e for l in best.layouts for e in check_layout(l, pack, pieces)]
        if errors:  # RNF-04: nunca se entrega un plano inválido
            raise OptimizationError("Validación geométrica fallida: " + "; ".join(errors[:5]))

        sample = g["orders"][0]
        label = material_label(sample)
        displacement_all.update(best.displacement)
        lot_by_id = {l["id"]: l for l in g["lots"]}
        for j, layout in enumerate(best.layouts):
            lot = lot_by_id[layout.unit.lot_id]
            pls = []
            for pl in layout.placements:
                m = meta[pl.piece]
                pls.append({
                    # "rotada": girada 90° respecto a su orientación de veta
                    # (la dimensión indicada en `veta` va paralela al eje X).
                    # En hojas con veta direccional nunca ocurre (RN-02).
                    "x": pl.x, "y": pl.y, "ancho": pl.w, "alto": pl.h,
                    "rotada": pl.rotated, "veta": "alto" if m["swap"] else "ancho",
                    "orden_id": m["order"]["id"], "orden": m["order"]["numero"],
                    "cliente": m["order"].get("cliente", ""),
                    "tipo": m["order"]["tipo_persiana"], "componente": m["piece"].get("componente", ""),
                    "pieza_id": m["piece"].get("id"),
                    "ancho_pieza": float(m["piece"]["ancho"]), "alto_pieza": float(m["piece"]["alto"]),
                })
            area = layout.area
            sheets_out.append({
                "lote_id": lot["id"], "codigo": lot["codigo"], "unidad": layout.unit.uid,
                "es_retazo": bool(lot.get("es_retazo")),
                "ancho": layout.unit.w, "alto": layout.unit.h,
                "color": lot["color"], "textura": lot["textura"], "espesor": float(lot["espesor"]),
                "veta_direccional": bool(lot["veta_direccional"]),
                "material": label, "orden_en_grupo": j,
                "piezas": pls,
                "retazos": [{"x": r.x, "y": r.y, "ancho": r.w, "alto": r.h} for r in layout.offcuts],
                "area": area, "area_piezas": layout.used_area, "area_retazos": layout.offcut_area,
                "area_merma": layout.scrap_area,
                "aprovechamiento": layout.used_area / area * 100,
                "merma": layout.scrap_area / area * 100,
                "pct_retazos": layout.offcut_area / area * 100,
                "costo_unitario": float(lot.get("costo_unitario") or 0),
                "kerf": pack.kerf, "refilado": pack.trim, "modo_corte": params["modo_corte"],
            })
        placed_per_order: dict[int, int] = defaultdict(int)
        for l in best.layouts:
            for pl in l.placements:
                placed_per_order[pieces[pl.piece].order_id] += 1
        req_per_order: dict[int, int] = defaultdict(int)
        for p in pieces:
            req_per_order[p.order_id] += 1
        for o in g["orders"]:
            req, got = req_per_order[o["id"]], placed_per_order[o["id"]]
            order_status[o["id"]] = {"requeridas": req, "colocadas": got,
                                     "cubierta": got == req,
                                     "motivo": "" if got == req else (
                                         "Sin inventario del material" if not g["lots"]
                                         else "Inventario insuficiente")}
        group_summaries.append({
            "material": label, "piezas": len(pieces), "hojas": len(best.layouts),
            "rotacion_permitida": pack.allow_rotation,
            "generaciones": result.generations, "segundos": round(result.elapsed, 2),
            "criterio_parada": result.stop_reason, "aptitud": round(best.fitness, 6),
            "terminos": {k: round(v, 6) for k, v in best.terms.items()},
            "historial": [round(h, 6) for h in result.history],
        })

    # -------------------------------- secuencia global de corte (RN-04, RF-10)
    for s in sheets_out:
        s["prioridad_cola"] = min(queue_rank[p["orden_id"]] for p in s["piezas"])
    sheets_out.sort(key=lambda s: (s["prioridad_cola"], s["material"], s["orden_en_grupo"]))
    for n, s in enumerate(sheets_out, start=1):
        s["hoja_id"] = f"H{n:03d}"
        s["secuencia"] = n

    area_tot = sum(s["area"] for s in sheets_out)
    used = sum(s["area_piezas"] for s in sheets_out)
    off = sum(s["area_retazos"] for s in sheets_out)
    scrap = sum(s["area_merma"] for s in sheets_out)
    covered = [oid for oid, st in order_status.items() if st["cubierta"]]
    on_time = sum(1 for o in orders if displacement_all.get(o["id"], 0) == 0)
    metrics = {
        "hojas_consumidas": sum(1 for s in sheets_out if not s["es_retazo"]),
        "retazos_consumidos": sum(1 for s in sheets_out if s["es_retazo"]),
        "total_hojas": len(sheets_out),
        "aprovechamiento": used / area_tot * 100 if area_tot else 0.0,
        "merma_neta": scrap / area_tot * 100 if area_tot else 0.0,
        "retazos_generados": sum(len(s["retazos"]) for s in sheets_out),
        "pct_retazos": off / area_tot * 100 if area_tot else 0.0,
        "ordenes_total": len(orders),
        "ordenes_cubiertas": len(covered),
        "ordenes_pendientes": len(orders) - len(covered),
        "adherencia_cola": on_time / len(orders) * 100 if orders else 100.0,
        "costo_merma": sum(s["area_merma"] / s["area"] * s["costo_unitario"] for s in sheets_out),
        "segundos": round(time.monotonic() - t0, 2),
    }
    ordenes = []
    for o in orders:
        st = order_status.get(o["id"], {"requeridas": 0, "colocadas": 0, "cubierta": True, "motivo": ""})
        ordenes.append({"id": o["id"], "numero": o["numero"], "posicion": queue_rank[o["id"]] + 1,
                        "prioridad": o["prioridad"], "desplazamiento": displacement_all.get(o["id"], 0),
                        **st})
    return {"metricas": metrics, "hojas": sheets_out, "ordenes": ordenes, "grupos": group_summaries}
