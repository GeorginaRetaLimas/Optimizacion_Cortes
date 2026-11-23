"""Persistencia en SQLite (inventario, cola de órdenes, despiece, parámetros y
corridas de optimización)."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

from .despiece import DEFAULT_TIPOS

SCHEMA = """
CREATE TABLE IF NOT EXISTS lotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    ancho REAL NOT NULL CHECK (ancho > 0),
    alto REAL NOT NULL CHECK (alto > 0),
    espesor REAL NOT NULL CHECK (espesor > 0),
    color TEXT NOT NULL,
    textura TEXT NOT NULL,
    veta_direccional INTEGER NOT NULL DEFAULT 0,
    cantidad INTEGER NOT NULL CHECK (cantidad >= 0),
    costo_unitario REAL,
    es_retazo INTEGER NOT NULL DEFAULT 0,
    origen TEXT DEFAULT '',
    creado TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS tipos_persiana (
    nombre TEXT PRIMARY KEY,
    descripcion TEXT DEFAULT '',
    holguras TEXT NOT NULL DEFAULT '{}',
    componentes TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS ordenes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT NOT NULL UNIQUE,
    cliente TEXT DEFAULT '',
    tipo_persiana TEXT NOT NULL,
    ancho_final REAL,
    alto_final REAL,
    cantidad INTEGER NOT NULL DEFAULT 1,
    color TEXT NOT NULL,
    textura TEXT NOT NULL,
    espesor REAL NOT NULL,
    prioridad TEXT NOT NULL DEFAULT 'Normal' CHECK (prioridad IN ('Normal', 'Urgente')),
    posicion INTEGER NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendiente',
    creado TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS piezas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    orden_id INTEGER NOT NULL REFERENCES ordenes(id) ON DELETE CASCADE,
    componente TEXT DEFAULT '',
    ancho REAL NOT NULL CHECK (ancho > 0),
    alto REAL NOT NULL CHECK (alto > 0),
    cantidad INTEGER NOT NULL CHECK (cantidad > 0),
    cortadas INTEGER NOT NULL DEFAULT 0,
    veta TEXT NOT NULL DEFAULT 'ancho'
);
CREATE TABLE IF NOT EXISTS parametros (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS corridas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creado TEXT DEFAULT CURRENT_TIMESTAMP,
    estado TEXT NOT NULL DEFAULT 'simulada',
    parametros TEXT NOT NULL,
    resultado TEXT NOT NULL
);
"""

# RF-09: parámetros configurables (valores por defecto)
DEFAULT_PARAMS = {
    "kerf": 3.0,                 # mm (RN-03)
    "refilado": 10.0,            # mm por lado; debe ser >= kerf
    "retazo_min_largo": 300.0,   # mm (RN-06, L_min)
    "retazo_min_ancho": 150.0,   # mm (RN-06, A_min)
    "modo_corte": "guillotina",  # "guillotina" | "libre" (RN-05)
    "w1": 1.0,                   # peso de la merma
    "w2": 0.5,                   # peso de la prioridad de cola frente al ahorro
    "w3": 0.3,                   # peso de la bonificación de retazos
    "w4": 1.0,                   # peso del consumo de material
    "ventana_tolerancia": 2,     # posiciones de cola (RN-04)
    "peso_urgente": 3.0,         # P_i de órdenes urgentes
    "poblacion": 60,
    "generaciones": 300,         # G_max
    "estancamiento": 60,         # X
    "tiempo_max": 25.0,          # T_max en segundos (RNF-01: <= 30 s)
    "cruce": "OX",               # "OX" | "PMX"
    "prob_cruce": 0.9,
    "prob_mutacion": 0.3,
    "semilla": None,
}


def connect(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)
    for k, v in DEFAULT_PARAMS.items():
        con.execute("INSERT OR IGNORE INTO parametros(clave, valor) VALUES (?, ?)", (k, json.dumps(v)))
    if con.execute("SELECT COUNT(*) FROM tipos_persiana").fetchone()[0] == 0:
        for t in DEFAULT_TIPOS:
            save_tipo(con, t)
    con.commit()


@contextmanager
def tx(con: sqlite3.Connection):
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise


def rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


# ----------------------------------------------------------------- parámetros
def get_params(con) -> dict:
    p = dict(DEFAULT_PARAMS)
    for r in con.execute("SELECT clave, valor FROM parametros"):
        p[r["clave"]] = json.loads(r["valor"])
    return p


def set_params(con, values: dict) -> None:
    for k, v in values.items():
        con.execute("INSERT OR REPLACE INTO parametros(clave, valor) VALUES (?, ?)", (k, json.dumps(v)))


# -------------------------------------------------------------------- despiece
def get_tipos(con) -> list[dict]:
    out = []
    for r in con.execute("SELECT * FROM tipos_persiana ORDER BY nombre"):
        out.append({"nombre": r["nombre"], "descripcion": r["descripcion"],
                     "holguras": json.loads(r["holguras"]), "componentes": json.loads(r["componentes"])})
    return out


def get_tipo(con, nombre: str) -> dict | None:
    return next((t for t in get_tipos(con) if t["nombre"] == nombre), None)


def save_tipo(con, t: dict) -> None:
    con.execute("INSERT OR REPLACE INTO tipos_persiana(nombre, descripcion, holguras, componentes) "
                "VALUES (?, ?, ?, ?)",
                (t["nombre"], t.get("descripcion", ""), json.dumps(t.get("holguras") or {}),
                 json.dumps(t["componentes"])))


# -------------------------------------------------------------------- órdenes
def get_orders(con, estado: str | None = "pendiente") -> list[dict]:
    q = "SELECT * FROM ordenes"
    args: tuple = ()
    if estado:
        q += " WHERE estado = ?"
        args = (estado,)
    orders = rows(con.execute(q + " ORDER BY posicion, id", args))
    pieces = rows(con.execute("SELECT * FROM piezas ORDER BY id"))
    by_order: dict[int, list] = {}
    for pc in pieces:
        pc["pendientes"] = pc["cantidad"] - pc["cortadas"]
        by_order.setdefault(pc["orden_id"], []).append(pc)
    for o in orders:
        o["piezas"] = by_order.get(o["id"], [])
        o["total_piezas"] = sum(p["cantidad"] for p in o["piezas"])
        o["piezas_pendientes"] = sum(p["pendientes"] for p in o["piezas"])
    return orders


def next_position(con) -> int:
    r = con.execute("SELECT COALESCE(MAX(posicion), -1) + 1 FROM ordenes").fetchone()
    return int(r[0])


def normalize_positions(con) -> None:
    ids = [r[0] for r in con.execute(
        "SELECT id FROM ordenes WHERE estado = 'pendiente' ORDER BY posicion, id")]
    for i, oid in enumerate(ids):
        con.execute("UPDATE ordenes SET posicion = ? WHERE id = ?", (i, oid))


def obsolete_runs(con) -> None:
    """Cualquier cambio en inventario, cola o parámetros deja obsoletas las
    simulaciones que aún no se confirmaron."""
    con.execute("UPDATE corridas SET estado = 'obsoleta' WHERE estado = 'simulada'")
