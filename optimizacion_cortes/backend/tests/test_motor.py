"""Pruebas del motor: geometría (RNF-04), reglas RN-01..RN-06 y AG."""
import random
import time

import pytest

from cortes.ga import _ox, _pmx
from cortes.optimizer import optimize
from cortes.packing import PackParams, Piece, SheetUnit, decode, order_stock
from cortes.validate import check_layout, is_guillotine

BASE_PARAMS = dict(kerf=3, refilado=10, retazo_min_largo=300, retazo_min_ancho=150, modo_corte="guillotina",
                   w1=1, w2=0.5, w3=0.3, w4=1, ventana_tolerancia=2, peso_urgente=3, poblacion=30,
                   generaciones=40, estancamiento=20, tiempo_max=5, cruce="OX", prob_cruce=0.9,
                   prob_mutacion=0.3, semilla=7)


def random_instance(seed, n=120):
    rng = random.Random(seed)
    pieces = [Piece(i, rng.choice([89, 150, 300, 450, 600, 800, 1200]),
                    rng.choice([80, 200, 400, 600, 985, 1100]), i % 8, i % 8) for i in range(n)]
    stock = order_stock([SheetUnit(f"L{j}", j, "L", rng.choice([2440, 3050]), rng.choice([1220, 1830]))
                         for j in range(40)] + [SheetUnit("R1", 99, "R", 900, 700, is_offcut=True)])
    return pieces, stock


@pytest.mark.parametrize("guillotine", [True, False])
@pytest.mark.parametrize("rotation", [True, False])
@pytest.mark.parametrize("seed", range(6))
def test_layouts_are_geometrically_valid(seed, rotation, guillotine):
    """RNF-04: sin solapes, separación >= kerf, dentro del área útil, sin
    rotación cuando hay veta y, en modo guillotina, cortable de borde a borde."""
    pieces, stock = random_instance(seed)
    p = PackParams(kerf=4, trim=10, guillotine=guillotine, allow_rotation=rotation)
    rng = random.Random(seed)
    chrom = [(i, rng.random() < 0.5) for i in rng.sample(range(len(pieces)), len(pieces))]
    layouts, unplaced = decode(chrom, pieces, stock, p)
    assert not unplaced
    placed = sorted(pl.piece for l in layouts for pl in l.placements)
    assert placed == list(range(len(pieces)))  # cada pieza exactamente una vez
    for l in layouts:
        assert check_layout(l, p, pieces) == []
        assert l.used_area + l.offcut_area + l.scrap_area == pytest.approx(l.area)


def test_validator_detects_overlap_and_kerf_violation():
    pieces = [Piece(0, 500, 500, 1, 0), Piece(1, 500, 500, 1, 0)]
    p = PackParams(kerf=3, trim=10)
    layouts, _ = decode([(0, False), (1, False)], pieces, [SheetUnit("A", 1, "A", 2000, 1000)], p)
    l = layouts[0]
    l.offcuts = []
    l.placements[1].x = l.placements[0].x + 501  # solo 1 mm de separación (< kerf)
    l.placements[1].y = l.placements[0].y
    assert any("kerf" in e for e in check_layout(l, p, pieces))


def test_guillotine_checker():
    assert is_guillotine([(0, 0, 10, 10), (10, 0, 10, 10), (0, 10, 20, 5)], 0, 0, 20, 20)
    pinwheel = [(0, 0, 20, 10), (20, 0, 10, 20), (10, 20, 20, 10), (0, 10, 10, 20), (10, 10, 10, 10)]
    assert not is_guillotine(pinwheel, 0, 0, 30, 30)


def test_offcuts_respect_minimums():
    p = PackParams(kerf=3, trim=10, offcut_min_long=300, offcut_min_short=150)
    pieces, stock = random_instance(3, 40)
    layouts, _ = decode([(i, False) for i in range(40)], pieces, stock, p)
    for l in layouts:
        for r in l.offcuts:
            assert max(r.w, r.h) >= 300 and min(r.w, r.h) >= 150


def test_offcuts_consumed_before_new_sheets():
    """RF-03: si un retazo puede alojar la pieza, se abre antes que una hoja nueva."""
    p = PackParams()
    pieces = [Piece(0, 400, 300, 1, 0)]
    stock = order_stock([SheetUnit("H", 1, "H", 2440, 1220), SheetUnit("R", 2, "R", 900, 700, is_offcut=True)])
    layouts, _ = decode([(0, False)], pieces, stock, p)
    assert layouts[0].unit.is_offcut


def test_crossovers_keep_valid_permutations():
    rng = random.Random(1)
    for _ in range(200):
        n = rng.randint(2, 30)
        a = tuple((i, rng.random() < .5) for i in rng.sample(range(n), n))
        b = tuple((i, rng.random() < .5) for i in rng.sample(range(n), n))
        i, j = sorted(rng.sample(range(n), 2))
        for child in (_ox(a, b, i, j), _pmx(a, b, i, j)):
            assert sorted(g[0] for g in child) == list(range(n))


def _lot(i, color, textura, veta, ancho=2440, alto=1220, cantidad=10, espesor=3):
    return dict(id=i, codigo=f"L{i}", ancho=ancho, alto=alto, espesor=espesor, color=color, textura=textura,
                veta_direccional=veta, cantidad=cantidad, costo_unitario=100, es_retazo=0)


def _order(i, color, textura, piezas, pos=None, prioridad="Normal", espesor=3):
    return dict(id=i, numero=f"OP-{i}", cliente="", tipo_persiana="Manual", color=color, textura=textura,
                espesor=espesor, prioridad=prioridad, posicion=i if pos is None else pos,
                piezas=[dict(id=i * 100 + k, componente="P", ancho=a, alto=h, pendientes=n, veta=v)
                        for k, (a, h, n, v) in enumerate(piezas)])


def test_material_homogeneity_and_grain():
    """RN-01 (color, textura y espesor) y RN-02 (sin rotación con veta)."""
    lots = [_lot(1, "Blanco", "Liso", False), _lot(2, "Nogal", "Veta", True),
            _lot(3, "Blanco", "Liso", False, espesor=5)]
    orders = [_order(1, "Blanco", "Liso", [(600, 300, 8, "ancho"), (200, 900, 4, "ancho")]),
              _order(2, "Nogal", "Veta", [(89, 1000, 12, "alto"), (500, 400, 3, "ancho")]),
              _order(3, "blanco ", "LISO", [(700, 500, 2, "ancho")], espesor=5)]
    res = optimize(lots, orders, BASE_PARAMS)
    order_mat = {1: ("blanco", "liso", 3.0), 2: ("nogal", "veta", 3.0), 3: ("blanco", "liso", 5.0)}
    for s in res["hojas"]:
        mat = (s["color"].lower(), s["textura"].lower(), s["espesor"])
        for p in s["piezas"]:
            assert order_mat[p["orden_id"]] == mat
            if s["veta_direccional"]:
                assert not p["rotada"]
                # la dimensión marcada como veta va sobre el eje X (paralela a la veta)
                along_x = p["ancho"]
                expected = p["alto_pieza"] if p["veta"] == "alto" else p["ancho_pieza"]
                assert along_x == pytest.approx(expected)
    assert res["metricas"]["ordenes_cubiertas"] == 3


def test_missing_stock_reported_as_pending():
    lots = [_lot(1, "Blanco", "Liso", False, cantidad=1)]
    orders = [_order(1, "Blanco", "Liso", [(1000, 1000, 6, "ancho")]),
              _order(2, "Rojo", "Liso", [(300, 300, 1, "ancho")])]
    res = optimize(lots, orders, BASE_PARAMS)
    st = {o["numero"]: o for o in res["ordenes"]}
    assert not st["OP-1"]["cubierta"] and st["OP-1"]["colocadas"] == 2
    assert st["OP-2"]["motivo"] == "Sin inventario del material"
    assert res["metricas"]["ordenes_pendientes"] == 2


def test_queue_priority_is_respected():
    """RN-04: con peso de cola alto, la secuencia de corte sigue la cola."""
    lots = [_lot(1, "Blanco", "Liso", False, cantidad=20)]
    rng = random.Random(4)
    orders = [_order(i, "Blanco", "Liso", [(rng.choice([300, 600, 900]), rng.choice([200, 400]), 6, "ancho")])
              for i in range(12)]
    res = optimize(lots, orders, {**BASE_PARAMS, "w2": 5, "ventana_tolerancia": 0})
    assert res["metricas"]["adherencia_cola"] >= 95


def test_rejects_trim_smaller_than_kerf():
    with pytest.raises(Exception):
        optimize([_lot(1, "B", "L", False)], [_order(1, "B", "L", [(100, 100, 1, "ancho")])],
                 {**BASE_PARAMS, "kerf": 5, "refilado": 2})


def test_ga_improves_over_initial_population():
    lots = [_lot(1, "B", "L", False, ancho=2440, alto=1220, cantidad=40)]
    rng = random.Random(9)
    orders = [_order(i, "B", "L", [(rng.choice([300, 450, 600, 800, 1200]), rng.choice([150, 200, 400, 600]), 5,
                                    "ancho")]) for i in range(20)]
    res = optimize(lots, orders, {**BASE_PARAMS, "generaciones": 150, "estancamiento": 150, "tiempo_max": 10})
    h = res["grupos"][0]["historial"]
    assert h[-1] <= h[0]
    assert all(b <= a + 1e-12 for a, b in zip(h, h[1:]))  # elitismo: nunca empeora


@pytest.mark.slow
def test_performance_200_pieces_50_sheets():
    """RNF-01: lote estándar de 200 piezas y 50 hojas en <= 30 s con los
    parámetros por defecto (T_max = 25 s)."""
    from cortes.db import DEFAULT_PARAMS
    rng = random.Random(2)
    lots = [_lot(1, "Blanco", "Liso", False, 2440, 1220, 30), _lot(2, "Blanco", "Liso", False, 3050, 1220, 20)]
    orders = [_order(i, "Blanco", "Liso", [(rng.choice([300, 450, 600, 800, 1200]), rng.choice([150, 200, 400, 600]),
                                            5, "ancho") for _ in range(2)]) for i in range(20)]
    t0 = time.monotonic()
    res = optimize(lots, orders, dict(DEFAULT_PARAMS))
    assert time.monotonic() - t0 <= 30
    assert res["metricas"]["ordenes_cubiertas"] == 20
    assert sum(len(s["piezas"]) for s in res["hojas"]) == 200
