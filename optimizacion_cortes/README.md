# Optimización de Cortes · SprintWindow

Sistema web de optimización de corte (*nesting* 2D) y planeación de producción para láminas de PVC. Resuelve el problema de corte bidimensional con inventario heterogéneo usando un **algoritmo genético**, y genera planos de corte en **PNG** para los operarios.

- Especificación: [`doc/proyecto.md`](doc/proyecto.md)
- Cómo se interpretaron los puntos abiertos de la ERS: [`doc/DECISIONES.md`](doc/DECISIONES.md)

## Requisitos

- Python 3.10 o superior
- Node.js 18 o superior (solo para compilar la interfaz)

## Instalación y ejecución

```bash
# 1. Backend
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Frontend (compila a frontend/dist)
cd ../frontend
npm install
npm run build

# 3. (Opcional) datos de demostración
cd ../backend
python seed.py

# 4. Servidor
python app.py                    # http://localhost:5000
```

Variables de entorno opcionales:

| Variable | Uso | Valor por defecto |
|---|---|---|
| `PORT` | Puerto del servidor | `5000` |
| `SPRINTWINDOW_DB` | Ruta de la base de datos SQLite | `backend/data/cortes.db` |
| `SPRINTWINDOW_ADMIN_PIN` | PIN para Parámetros y Despiece | `1234` |

Para trabajar en la interfaz: `npm run dev` recompila automáticamente al guardar.

## Pruebas

```bash
cd backend
pytest                 # todas, incluida la de rendimiento (~25 s)
pytest -m "not slow"   # sin la prueba de rendimiento
```

## Estructura

```
backend/
  app.py              API REST (Flask) y servidor del frontend
  seed.py             datos de demostración
  cortes/
    packing.py        geometría, kerf/refilado y decodificadores (guillotina / BLF)
    ga.py             algoritmo genético (OX/PMX, swap/inversión/rotación, torneo + elitismo)
    optimizer.py      particionado por material, métricas y secuencia de corte
    validate.py       validación geométrica (solapes, kerf, veta, guillotina)
    render.py         planos PNG y ZIP
    despiece.py       reglas de despiece con fórmulas seguras
    importer.py       carga masiva .csv/.xlsx con validación
    db.py             esquema SQLite y parámetros por defecto
  tests/              pruebas automáticas (pytest)
frontend/
  src/                interfaz en React (Planeación, Inventario, Historial, Despiece, Parámetros)
  public/             index.html y estilos
doc/
  proyecto.md / .pdf  ERS v1.0
  DECISIONES.md       decisiones de diseño
```

## Trazabilidad de requerimientos

| Req. | Dónde se cumple |
|---|---|
| RN-01 Homogeneidad de material | `optimizer.py` (agrupa por color + textura + espesor); prueba `test_material_homogeneity_and_grain` |
| RN-02 Rotación por veta | `packing._orientations`, `validate.check_layout`; marca ⟳90° en el plano |
| RN-03 Kerf | `packing.py` (piezas infladas), `validate.py`; refilado ≥ kerf |
| RN-04 Cola FIFO / prioridad | término w2 + ventana de tolerancia (`ga._displacement`), secuencia global de corte |
| RN-05 Guillotina / libre | `PackParams.guillotine`; verificador `is_guillotine` |
| RN-06 Retazos | `packing.extract_offcuts`; trama verde en el PNG; alta automática al confirmar |
| RF-01 / RF-03 Inventario y retazos | pestaña Inventario; `/api/lotes` |
| RF-02 Carga masiva | `importer.py`; plantillas `.csv`/`.xlsx`; valida todo antes de cargar |
| RF-04 / RF-05 Cola de órdenes | pestaña Planeación: alta, edición, ▲▼ y arrastrar y soltar, recálculo del impacto |
| RF-06 Despiece | pestaña Despiece (editor de fórmulas); vista previa al capturar la orden |
| RF-07 / RF-08 Motor AG | `optimizer.py`, `ga.py` |
| RF-09 Parámetros | pestaña Parámetros (PIN de administrador) |
| RF-10 Simulación | métricas proyectadas antes de confirmar; comparativa contra la corrida anterior |
| RF-11 / RF-12 Planos PNG | `render.py`; descarga individual o en `.zip` |
| RNF-01 ≤ 30 s | T_max = 25 s; `test_performance_200_pieces_50_sheets` |
| RNF-02 Resolución | 3300 × 2550 px a 300 DPI (carta) |
| RNF-03 3 clics | Importar órdenes → Optimizar → Descargar planos |
| RNF-04 Integridad | validación de cada hoja antes de guardar la corrida + pruebas automáticas |
| RNF-05 Arquitectura | frontend React desacoplado + backend Python (Flask, Pillow/Matplotlib) |

> Las fórmulas de despiece precargadas son de referencia. Ingeniería de SprintWindow debe capturar las reales en la pestaña Despiece.
