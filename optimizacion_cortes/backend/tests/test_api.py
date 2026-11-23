"""Pruebas de punta a punta de la API (RF-01 a RF-12)."""
import io
import zipfile

import pytest
from openpyxl import Workbook
from PIL import Image

from app import create_app
from cortes.despiece import FormulaError, evaluate

PIN = {"X-Admin-Pin": "1234"}


@pytest.fixture()
def c(tmp_path):
    app = create_app(str(tmp_path / "t.db"))
    client = app.test_client()
    client.put("/api/parametros", json={"tiempo_max": 3, "semilla": 1}, headers=PIN)
    return client


def lot(c, codigo, **kw):
    b = dict(codigo=codigo, ancho=2440, alto=1220, espesor=3, color="Blanco", textura="Liso",
             veta_direccional=False, cantidad=5, costo_unitario=800)
    b.update(kw)
    r = c.post("/api/lotes", json=b)
    assert r.status_code == 201, r.json
    return r.json


def test_lot_crud_and_validation(c):
    l = lot(c, "A1")
    assert c.post("/api/lotes", json={"codigo": "A1", "ancho": 1, "alto": 1, "espesor": 1, "color": "x",
                                      "textura": "y", "cantidad": 1}).status_code == 409
    r = c.post("/api/lotes", json={"codigo": "B", "ancho": -5, "alto": "x", "espesor": 3, "color": "",
                                   "textura": "L", "cantidad": 1.5})
    assert r.status_code == 400
    assert {e["campo"] for e in r.json["errores"]} >= {"ancho", "alto", "color", "cantidad"}
    r = c.put(f"/api/lotes/{l['id']}", json={"cantidad": 9, "veta_direccional": True})
    assert r.json["cantidad"] == 9 and r.json["veta_direccional"] == 1
    assert c.delete(f"/api/lotes/{l['id']}").status_code == 200
    assert c.get("/api/lotes").json == []


def test_bulk_import_validates_before_loading(c):
    bad = "codigo,ancho,alto,espesor,color,textura,veta_direccional,cantidad\nX1,2440,1220,3,Blanco,Liso,no,4\n" \
          "X2,abc,1220,3,Blanco,Liso,quizá,2\n"
    r = c.post("/api/lotes/importar", data={"archivo": (io.BytesIO(bad.encode()), "inv.csv"), "confirmar": "1"})
    assert r.status_code == 422 and not r.json["cargado"]
    assert {(e["fila"], e["campo"]) for e in r.json["errores"]} == {(3, "ancho"), (3, "veta_direccional")}
    assert c.get("/api/lotes").json == []  # nada se cargó

    wb = Workbook()
    ws = wb.active
    ws.append(["Código", "Ancho (mm)", "Alto", "Espesor", "Color", "Textura", "Veta", "Cantidad", "Costo"])
    ws.append(["X1", 2440, 1220, 3, "Nogal", "Veta madera", "sí", 4, 1100])
    ws.append(["X2", 3050, 1830, 3, "Nogal", "Veta madera", "si", 2, None])
    buf = io.BytesIO()
    wb.save(buf)
    r = c.post("/api/lotes/importar", data={"archivo": (io.BytesIO(buf.getvalue()), "inv.xlsx"), "confirmar": "1"})
    assert r.status_code == 200 and r.json["cargado"] and r.json["nuevos"] == 2
    assert all(l["veta_direccional"] == 1 for l in c.get("/api/lotes").json)


def test_templates_download(c):
    for k in ("lotes", "ordenes"):
        for f in ("csv", "xlsx"):
            assert c.get(f"/api/plantillas/{k}.{f}").status_code == 200


def test_despiece_and_formula_safety(c):
    r = c.post("/api/despiece", json={"tipo_persiana": "Vertical", "ancho_final": 1500, "alto_final": 1800,
                                      "cantidad": 2})
    assert r.json == [{"componente": "Lama", "ancho": 89.0, "alto": 1785.0, "cantidad": 38, "veta": "alto"}]
    for expr in ("__import__('os')", "W.__class__", "9**9**9", "open('x')"):
        with pytest.raises(FormulaError):
            evaluate(expr, {"W": 1})
    assert c.put("/api/tipos/Nuevo", json={"componentes": [{"nombre": "A", "ancho": "W", "alto": "H",
                                                              "cantidad": "1"}]}).status_code == 403
    r = c.put("/api/tipos/Nuevo", headers=PIN, json={"holguras": {"h": 5}, "componentes": [
        {"nombre": "A", "ancho": "W - h", "alto": "H/2", "cantidad": "2", "veta": "ancho"}]})
    assert r.status_code == 200
    r = c.put("/api/tipos/Malo", headers=PIN, json={"componentes": [{"nombre": "A", "ancho": "W - zz",
                                                                       "alto": "H", "cantidad": "1"}]})
    assert r.status_code == 400


def test_queue_order_and_reorder(c):
    for n, pr in (("A", "Normal"), ("B", "Normal"), ("C", "Urgente"), ("D", "Urgente")):
        r = c.post("/api/ordenes", json=dict(numero=n, tipo_persiana="Manual", ancho_final=300, alto_final=200,
                                             cantidad=2, color="Blanco", textura="Liso", espesor=3, prioridad=pr))
        assert r.status_code == 201
    q = c.get("/api/ordenes").json
    assert [o["numero"] for o in q] == ["C", "D", "A", "B"]  # urgentes al frente, en orden de llegada
    ids = [o["id"] for o in q][::-1]
    q = c.post("/api/ordenes/reordenar", json={"ids": ids}).json
    assert [o["numero"] for o in q] == ["B", "A", "D", "C"]
    assert c.post("/api/ordenes/reordenar", json={"ids": ids[:2]}).status_code == 400


def test_full_flow_optimize_render_confirm(c):
    lot(c, "BL", cantidad=6)
    lot(c, "NO", color="Nogal", textura="Veta", veta_direccional=True, cantidad=3)
    lot(c, "RZ", ancho=900, alto=700, cantidad=1, es_retazo=True)
    c.post("/api/ordenes", json=dict(numero="OP1", tipo_persiana="Vertical", ancho_final=1200, alto_final=1000,
                                     cantidad=1, color="Nogal", textura="Veta", espesor=3))
    c.post("/api/ordenes", json=dict(numero="OP2", tipo_persiana="Manual", color="Blanco", textura="Liso",
                                     espesor=3, piezas=[{"ancho": 500, "alto": 400, "cantidad": 4},
                                                        {"ancho": 1200, "alto": 600, "cantidad": 2}]))
    c.post("/api/ordenes", json=dict(numero="OP3", tipo_persiana="Manual", ancho_final=300, alto_final=300,
                                     cantidad=3, color="Rojo", textura="Liso", espesor=3))
    run = c.post("/api/corridas", json={}).json
    m = run["metricas"]
    assert m["ordenes_cubiertas"] == 2 and m["ordenes_pendientes"] == 1  # Rojo: sin inventario
    assert 0 < m["aprovechamiento"] <= 100 and m["merma_neta"] >= 0
    assert [s["secuencia"] for s in run["hojas"]] == list(range(1, len(run["hojas"]) + 1))

    # RF-11 / RNF-02: PNG de alta resolución
    png = c.get(f"/api/corridas/{run['id']}/hojas/H001.png")
    im = Image.open(io.BytesIO(png.data))
    assert im.size[0] >= 1920 and im.size[1] >= 1080
    assert 150 <= round(im.info["dpi"][0]) <= 300
    z = zipfile.ZipFile(io.BytesIO(c.get(f"/api/corridas/{run['id']}/planos.zip").data))
    assert len(z.namelist()) == len(run["hojas"])

    # Confirmación: descuenta inventario y da de alta retazos
    before = {l["codigo"]: l["cantidad"] for l in c.get("/api/lotes").json}
    r = c.post(f"/api/corridas/{run['id']}/confirmar")
    assert r.status_code == 200
    after = c.get("/api/lotes").json
    used = {}
    for s in run["hojas"]:
        used[s["codigo"]] = used.get(s["codigo"], 0) + 1
    for l in after:
        if l["codigo"] in before and not l["codigo"].startswith("RZ-"):
            assert l["cantidad"] == before[l["codigo"]] - used.get(l["codigo"], 0)
    new_offcuts = [l for l in after if l["codigo"].startswith("RZ-C-")]
    assert len(new_offcuts) == m["retazos_generados"]
    pend = [o["numero"] for o in c.get("/api/ordenes").json]
    assert pend == ["OP3"]
    assert c.post(f"/api/corridas/{run['id']}/confirmar").status_code == 409  # no se confirma dos veces


def test_changes_make_simulation_obsolete(c):
    lot(c, "BL")
    c.post("/api/ordenes", json=dict(numero="OP1", tipo_persiana="Manual", ancho_final=300, alto_final=200,
                                     cantidad=2, color="Blanco", textura="Liso", espesor=3))
    run = c.post("/api/corridas", json={}).json
    c.post("/api/ordenes", json=dict(numero="OP2", tipo_persiana="Manual", ancho_final=300, alto_final=200,
                                     cantidad=2, color="Blanco", textura="Liso", espesor=3))
    assert c.get(f"/api/corridas/{run['id']}").json["estado"] == "obsoleta"
    assert c.post(f"/api/corridas/{run['id']}/confirmar").status_code == 409


def test_params_require_admin_and_validate(c):
    assert c.put("/api/parametros", json={"kerf": 4}).status_code == 403
    r = c.put("/api/parametros", json={"kerf": 20, "refilado": 5}, headers=PIN)
    assert r.status_code == 400
    r = c.put("/api/parametros", json={"kerf": 4, "modo_corte": "libre", "cruce": "PMX"}, headers=PIN)
    assert r.json["kerf"] == 4 and r.json["modo_corte"] == "libre"
