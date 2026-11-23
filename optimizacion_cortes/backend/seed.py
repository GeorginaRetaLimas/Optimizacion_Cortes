"""Carga datos de demostración (inventario y cola de órdenes).

Uso:  python seed.py [ruta.db]
Borra los lotes, órdenes y corridas existentes de esa base de datos.
"""
import os
import sys

from app import BASE, create_app

DB = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SPRINTWINDOW_DB",
                                                          os.path.join(BASE, "data", "cortes.db"))
app = create_app(DB)
c = app.test_client()

import sqlite3  # noqa: E402

con = sqlite3.connect(DB)
con.executescript("DELETE FROM piezas; DELETE FROM ordenes; DELETE FROM lotes; DELETE FROM corridas;")
con.commit()
con.close()

LOTES = [
    ("PVC-BL-2440", 2440, 1220, 3, "Blanco", "Liso", False, 25, 850),
    ("PVC-BL-3050", 3050, 1830, 3, "Blanco", "Liso", False, 10, 1450),
    ("PVC-GR-2440", 2440, 1220, 3, "Gris", "Liso", False, 12, 900),
    ("PVC-NO-2440", 2440, 1220, 3, "Nogal", "Veta madera", True, 10, 1100),
    ("PVC-NO-3050", 3050, 1830, 3, "Nogal", "Veta madera", True, 6, 1700),
]
for cod, a, h, e, col, tex, veta, n, costo in LOTES:
    r = c.post("/api/lotes", json=dict(codigo=cod, ancho=a, alto=h, espesor=e, color=col, textura=tex,
                                       veta_direccional=veta, cantidad=n, costo_unitario=costo))
    assert r.status_code == 201, r.json
c.post("/api/lotes", json=dict(codigo="RZ-INICIAL-001", ancho=900, alto=700, espesor=3, color="Blanco",
                               textura="Liso", veta_direccional=False, cantidad=1, costo_unitario=180,
                               es_retazo=True))

ORDENES = [
    dict(numero="OP-1001", cliente="Hotel Victoria", tipo_persiana="Vertical", ancho_final=1800,
         alto_final=1100, cantidad=2, color="Blanco", textura="Liso", espesor=3, prioridad="Normal"),
    dict(numero="OP-1002", cliente="Casa Rmz", tipo_persiana="Panel japonés", ancho_final=1700,
         alto_final=1150, cantidad=1, color="Nogal", textura="Veta madera", espesor=3, prioridad="Normal"),
    dict(numero="OP-1003", cliente="Oficinas Centro", tipo_persiana="Enrollable", ancho_final=1400,
         alto_final=1300, cantidad=3, color="Blanco", textura="Liso", espesor=3, prioridad="Urgente"),
    dict(numero="OP-1004", cliente="Clínica Norte", tipo_persiana="Manual", color="Gris", textura="Liso",
         espesor=3, prioridad="Normal",
         piezas=[dict(componente="Panel", ancho=600, alto=900, cantidad=6, veta="alto"),
                 dict(componente="Tapa", ancho=600, alto=120, cantidad=6, veta="ancho")]),
    dict(numero="OP-1005", cliente="Depto. 12B", tipo_persiana="Vertical", ancho_final=1200,
         alto_final=1000, cantidad=1, color="Nogal", textura="Veta madera", espesor=3, prioridad="Normal"),
    dict(numero="OP-1006", cliente="Escuela Sur", tipo_persiana="Panel japonés", ancho_final=2400,
         alto_final=1100, cantidad=2, color="Blanco", textura="Liso", espesor=3, prioridad="Normal"),
    dict(numero="OP-1007", cliente="Casa Lpz", tipo_persiana="Manual", ancho_final=450, alto_final=300,
         cantidad=10, color="Blanco", textura="Liso", espesor=3, prioridad="Normal"),
]
for o in ORDENES:
    r = c.post("/api/ordenes", json=o)
    assert r.status_code == 201, r.json
print("Datos de demostración cargados en", DB)
