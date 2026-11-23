# Optimización de Cortes · SprintWindow

Aplicación web que planea el corte de láminas de PVC para la fabricación de persianas. Recibe el inventario de hojas y la cola de órdenes de producción, decide qué pieza va en qué hoja y en qué posición, y entrega un plano en PNG por cada hoja para que el operario corte.

El objetivo es desperdiciar menos material sin desordenar la cola de producción. El problema es de corte bidimensional con hojas de tamaños distintos (*2D cutting stock* con inventario heterogéneo) y se resuelve con un algoritmo genético.

Documentos relacionados:

- [`doc/proyecto.md`](doc/proyecto.md): especificación de requerimientos (ERS v1.0).
- [`doc/DECISIONES.md`](doc/DECISIONES.md): cómo se resolvieron los puntos que la ERS dejó abiertos.

---

## Contenido

1. [Flujo de trabajo](#flujo-de-trabajo)
2. [Pantallas](#pantallas)
3. [Cómo decide el corte](#cómo-decide-el-corte)
4. [Reglas de planta que respeta](#reglas-de-planta-que-respeta)
5. [Planos de corte (PNG)](#planos-de-corte-png)
6. [Qué pasa al confirmar un corte](#qué-pasa-al-confirmar-un-corte)
7. [Instalación y ejecución](#instalación-y-ejecución)
8. [Archivos de importación](#archivos-de-importación)
9. [API REST](#api-rest)
10. [Pruebas](#pruebas)
11. [Estructura del proyecto](#estructura-del-proyecto)
12. [Trazabilidad de requerimientos](#trazabilidad-de-requerimientos)
13. [Limitaciones conocidas](#limitaciones-conocidas)
14. [Problemas comunes](#problemas-comunes)

---

## Flujo de trabajo

1. Se registra el inventario: lotes de hojas de PVC y retazos de cortes anteriores. Se capturan a mano o se importan desde Excel/CSV.
2. Se arma la cola de órdenes. Cada orden indica tipo de persiana, medidas, cantidad, material y prioridad. El sistema calcula las piezas rectangulares que lleva cada persiana (despiece).
3. Se pulsa **Optimizar**. El motor separa las órdenes por material, corre el algoritmo genético y muestra métricas proyectadas: hojas que se van a usar, aprovechamiento, merma y órdenes que quedarían sin cubrir.
4. Se revisan los planos. Si la cola cambia, la simulación se recalcula y se compara con la anterior.
5. Se descargan los planos (uno por uno o en un .zip) y se confirma el corte. Al confirmar, el inventario se actualiza solo.

La ruta corta pide tres clics: **Importar órdenes**, **Optimizar** y **Descargar planos**.

---

## Pantallas

### Planeación

Es la pantalla principal y tiene dos columnas.

La columna izquierda es la cola de producción. Cada orden muestra su posición, número, cliente, tipo de persiana, material y cuántas piezas le faltan. Desde aquí se puede:

- importar órdenes desde .csv o .xlsx (el servidor valida el archivo completo y solo lo carga si no tiene errores);
- agregar una orden con un formulario que muestra el despiece en vivo y avisa si no hay hojas de ese material;
- editar o borrar órdenes;
- cambiar el orden con las flechas ▲▼ o arrastrando la orden.

Al reordenar, el sistema corre una simulación rápida de 5 segundos y muestra cuánto cambiaron las métricas ("+0.3 pts vs. antes"). La casilla de recálculo automático lo desactiva.

La columna derecha muestra la última corrida:

- métricas: hojas nuevas consumidas, retazos reutilizados, aprovechamiento global, merma neta, área que queda en retazos, órdenes cubiertas, órdenes pendientes por falta de material, adherencia a la cola y costo estimado de la merma;
- miniaturas de los planos en el orden en que deben cortarse; al hacer clic se ve el plano completo;
- una tabla por material con piezas, hojas, si se permitió rotar, generaciones, motivo de parada y una gráfica de cómo mejoró la solución;
- una tabla por orden con piezas colocadas contra requeridas y cuántas posiciones se atrasó;
- los botones **Descargar planos (.zip)** y **Confirmar orden de corte**.

### Inventario

Tiene dos vistas: hojas y retazos. Cada lote registra código, ancho, alto, espesor, color, textura, si la veta es direccional, cantidad y costo unitario (opcional). La carga masiva acepta .csv y .xlsx, revisa fila por fila y muestra una tabla con cada error (fila, campo y problema). Si un código ya existe, la carga lo actualiza. Hay plantillas descargables en los dos formatos.

Los retazos se pueden registrar a mano. Los que salen de un corte confirmado se agregan solos.

### Historial

Lista las corridas con fecha, estado (simulada, confirmada u obsoleta), hojas, aprovechamiento, merma y órdenes cubiertas. Desde aquí se pueden abrir y descargar los planos de cualquier corrida anterior.

### Despiece

Define cómo se convierte una persiana en piezas. Cada tipo tiene:

- holguras de ensamble con nombre (por ejemplo `holgura_lateral = 35`);
- componentes con fórmulas para ancho, alto y cantidad, y la dimensión que debe ir paralela a la veta.

Las fórmulas pueden usar `W` (ancho final), `H` (alto final), las holguras y las funciones `ceil`, `floor`, `round`, `min` y `max`. Un ejemplo es la lama vertical: ancho `ancho_lama`, alto `H - holgura_alto`, cantidad `ceil(W / (ancho_lama - traslape))`. Abajo hay una prueba con W y H de ejemplo que muestra el resultado al momento.

Las fórmulas se evalúan con un intérprete propio que solo acepta aritmética, así que no se puede ejecutar código desde ellas. Esta pantalla pide el PIN de administrador.

### Parámetros

Configura el proceso y el motor sin tocar código (pide el PIN de administrador):

| Grupo | Parámetros |
|---|---|
| Proceso de corte | kerf, margen de refilado, tamaño mínimo de retazo (lado largo y lado corto), tipo de corte (guillotina o anidamiento libre) |
| Función de aptitud | pesos w1 a w4, ventana de tolerancia de la cola, peso de las órdenes urgentes |
| Algoritmo genético | población, generaciones máximas, generaciones sin mejora, tiempo límite, operador de cruce (OX o PMX), probabilidades de cruce y de mutación, semilla |

Al guardar se validan los rangos. El refilado tiene que ser mayor o igual que el kerf.

---

## Cómo decide el corte

### 1. Separación por material

Una pieza solo puede salir de una hoja con el mismo color, textura y espesor. Por eso el motor divide el trabajo en un subproblema por cada combinación (por ejemplo, "Blanco / Liso / 3 mm") y resuelve cada uno por separado. Para comparar, ignora mayúsculas y espacios.

### 2. Representación de una solución

Una solución (cromosoma) es una lista con todas las piezas en cierto orden. Cada pieza lleva una marca que dice si se gira 90°. Por sí sola la lista no dice dónde va cada pieza; eso lo calcula el decodificador.

### 3. Decodificador

Recorre la lista y coloca cada pieza en la primera hoja abierta donde quepa. Si no cabe en ninguna, abre otra hoja: primero el retazo más pequeño que la aloje y, si no hay, la hoja nueva más grande (en empate, la más barata). Tiene dos modos:

- **Guillotina** (sierra seccionadora): divide el espacio libre en rectángulos que no se traslapan y cada corte va de borde a borde. Elige el rectángulo libre que deja menos sobrante y corta por el lado que deja el retazo más grande.
- **Anidamiento libre** (router CNC): MaxRects con la regla *bottom-left*, que coloca cada pieza lo más abajo y a la izquierda posible.

El kerf se respeta "inflando" cada pieza: una pieza de 500 × 300 con kerf de 3 mm ocupa 503 × 303 dentro de un área útil que también crece 3 mm. Así, entre dos piezas siempre quedan al menos 3 mm.

### 4. Función de aptitud

Califica cada solución; entre menor el valor, mejor:

```
F = w1 · Σ merma_j / área_j                    (merma en cada hoja)
  + w2 · Σ P_i · ΔT_i / Σ P_i                  (atraso de órdenes en la cola)
  − w3 · Σ área_retazos / Σ área_hojas         (premio por dejar retazos grandes)
  + w4 · (Σ área_hojas / Σ área_piezas − 1)    (material consumido)
  + 1000 · fracción de piezas sin colocar
```

- La merma es lo que sobra de una hoja después de quitar piezas y retazos recuperables. Un retazo no cuenta como merma.
- ΔT_i es cuántas posiciones se atrasa la orden i respecto a su lugar en la cola, descontando una ventana de tolerancia. P_i vale 1 para una orden normal y 3 (configurable) para una urgente.
- w4 no viene en la ERS. Se agregó porque, sin él, el motor repartía las piezas en más hojas para ganar el premio de retazos. La explicación está en `doc/DECISIONES.md`.

### 5. Algoritmo genético

- La población inicial tiene soluciones armadas con reglas sencillas (por prioridad de cola, por área, por lado más largo) y el resto al azar.
- Selección por torneo de 3, con elitismo: el 5 % mejor pasa intacto a la siguiente generación, así que la mejor solución nunca empeora.
- Cruce OX u PMX, que mezclan dos listas sin repetir ni perder piezas. La marca de rotación viaja con su pieza.
- Mutación: intercambiar dos piezas, invertir un tramo de la lista o girar una pieza (esto último solo si la textura lo permite).
- Se detiene al llegar a G_max generaciones, al pasar X generaciones sin mejorar o al agotar el tiempo límite. El tiempo (25 s por defecto) se reparte entre los materiales según cuántas piezas tiene cada uno.

### 6. Secuencia de corte y validación

Con todos los materiales resueltos, las hojas se ordenan según la orden más prioritaria que contiene cada una. Esa es la secuencia que se imprime en los planos (H001, H002…).

Antes de guardar la corrida, cada hoja pasa por una validación geométrica: ninguna pieza se encima, la separación es al menos el kerf, todo queda dentro del área útil, no hay piezas giradas sobre veta y, en modo guillotina, el patrón se puede cortar de borde a borde. Si algo falla, la corrida se rechaza.

---

## Reglas de planta que respeta

| Regla | Qué hace el sistema |
|---|---|
| RN-01 Material | Solo asigna una pieza a una hoja del mismo color, textura y espesor |
| RN-02 Veta | Con veta direccional no gira piezas; la dimensión marcada como "veta" va paralela al ancho de la hoja |
| RN-03 Kerf | Deja la separación configurada entre piezas y exige que el refilado sea al menos igual al kerf |
| RN-04 Cola | Penaliza atrasar órdenes; permite agruparlas dentro de la ventana de tolerancia |
| RN-05 Tipo de corte | Guillotina o anidamiento libre, según el parámetro |
| RN-06 Retazos | Marca como retazo recuperable todo sobrante que mida al menos L_min × A_min (300 × 150 mm por defecto) |

---

## Planos de corte (PNG)

Cada hoja usada genera una imagen de 3300 × 2550 píxeles a 300 DPI, que es una hoja carta horizontal impresa a tamaño completo. El plano incluye:

- encabezado con corrida, número de hoja y su lugar en la secuencia, lote, medidas, color, textura, espesor, tipo de corte, kerf y refilado;
- un recuadro de veta: flecha roja si la veta es direccional, o "Sin veta, rotación permitida";
- la hoja a escala con cotas en mm y la línea de refilado punteada;
- cada pieza en el color de su orden (con trama si hay más de 12 órdenes) y una etiqueta con número, orden, tipo y componente, medidas y la marca ⟳90° si se giró. Si la pieza es angosta, el texto se pone vertical; si es muy chica, solo lleva su número;
- retazos recuperables con rayado verde y sus medidas, y la merma con rayado gris;
- una tabla lateral con todas las piezas de la hoja;
- al pie, % de aprovechamiento, % de merma, % de retazos y total de piezas.

Los planos se descargan uno por uno o todos juntos en `planos_C-0001.zip`.

---

## Qué pasa al confirmar un corte

1. Se descuenta del inventario cada hoja y cada retazo usado.
2. Cada retazo recuperable se da de alta como lote nuevo (`RZ-C-0001-001`, …) con el mismo material y veta, y un costo proporcional a su área. En la siguiente optimización ya está disponible.
3. Se registran las piezas cortadas. Una orden completa sale de la cola. Si faltó material, la orden se queda con las piezas que le faltan.
4. La corrida pasa a "confirmada" y no se puede confirmar dos veces.

Cualquier cambio en el inventario, la cola o los parámetros deja obsoletas las simulaciones sin confirmar. Así nunca se confirma un plan hecho con datos viejos.

---

## Instalación y ejecución

Requisitos: Python 3.10 o superior. Node.js 18 o superior solo hace falta si se modifica la interfaz.

La interfaz ya va compilada en `frontend/dist`, así que para usar el sistema basta con Python.

### Linux / macOS

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python seed.py        # opcional: datos de demostración
python app.py
```

### Windows (PowerShell)

Windows PowerShell 5 no acepta `&&`; cada comando va en su propia línea.

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python seed.py
python app.py
```

Si PowerShell no deja activar el entorno, ejecuta antes `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

Con el servidor corriendo, abre **http://localhost:5000**. Para detenerlo, `Ctrl + C`.

### Variables de entorno

| Variable | Uso | Valor por defecto |
|---|---|---|
| `PORT` | Puerto del servidor | `5000` |
| `SPRINTWINDOW_DB` | Archivo de la base de datos SQLite | `backend/data/cortes.db` |
| `SPRINTWINDOW_ADMIN_PIN` | PIN de Parámetros y Despiece | `1234` |

### Datos de demostración

`python seed.py` borra lo que haya en la base y carga cinco lotes (blanco, gris y nogal con veta, en 2440 × 1220 y 3050 × 1830), un retazo y siete órdenes de distintos tipos, una de ellas urgente.

### Modificar la interfaz

El código está en `frontend/src` (React). Después de cambiarlo hay que recompilar:

```bash
cd frontend
npm install
npm run build      # o "npm run dev" para recompilar al guardar
```

El resultado queda en `frontend/dist`, que se sube al repositorio para que nadie más tenga que instalar Node.js.

---

## Archivos de importación

Las dos importaciones aceptan .csv (separado por coma, punto y coma o tabulador) y .xlsx. En los encabezados da igual si hay mayúsculas o acentos. Las plantillas se descargan desde la aplicación.

**Inventario** (`/api/plantillas/lotes.xlsx`):

| Columna | Obligatoria | Ejemplo |
|---|---|---|
| codigo | sí | PVC-BL-2440 |
| ancho, alto, espesor | sí | 2440, 1220, 3 (mm) |
| color, textura | sí | Blanco, Liso |
| veta_direccional | no (por defecto "no") | sí / no |
| cantidad | sí | 20 |
| costo_unitario | no | 850 |

**Órdenes** (`/api/plantillas/ordenes.xlsx`):

| Columna | Obligatoria | Ejemplo |
|---|---|---|
| numero | sí | OP-1001 |
| cliente | no | Hotel Victoria |
| tipo_persiana | sí | Vertical, Enrollable, Panel japonés o Manual |
| ancho_final, alto_final | sí | 1500, 1800 (mm) |
| cantidad | sí | 2 |
| color, textura, espesor | sí | Blanco, Liso, 3 |
| prioridad | no | Normal / Urgente |

Con el tipo `Manual`, `ancho_final × alto_final` es la medida de la pieza y `cantidad` es el número de piezas.

---

## API REST

El backend expone una API JSON en `/api`. La interfaz solo usa estas rutas, así que se puede conectar otro cliente.

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/estado` | Hojas, retazos y órdenes pendientes |
| GET / POST | `/api/lotes` | Listar (`?retazos=0/1`) o crear lotes |
| PUT / DELETE | `/api/lotes/<id>` | Editar o borrar un lote |
| POST | `/api/lotes/importar` | Carga masiva (`archivo`, `confirmar=0/1`) |
| GET | `/api/plantillas/<lotes\|ordenes>.<csv\|xlsx>` | Plantillas |
| GET | `/api/ordenes` | Cola (`?estado=pendiente\|cortada\|todas`) |
| POST | `/api/ordenes` | Crear orden |
| PUT / DELETE | `/api/ordenes/<id>` | Editar o borrar orden |
| POST | `/api/ordenes/reordenar` | Nuevo orden de la cola (`{"ids": [...]}`) |
| POST | `/api/ordenes/importar` | Carga masiva de órdenes |
| GET | `/api/tipos` | Tipos de persiana y sus reglas |
| PUT / DELETE | `/api/tipos/<nombre>` | Guardar o borrar un tipo (requiere PIN) |
| POST | `/api/despiece` | Calcular el despiece de una medida |
| GET / PUT | `/api/parametros` | Leer o guardar parámetros (PUT requiere PIN) |
| POST | `/api/corridas` | Optimizar (`{"tiempo_max": s}` opcional) |
| GET | `/api/corridas`, `/api/corridas/<id>` | Historial y detalle |
| GET | `/api/corridas/<id>/hojas/<H001>.png` | Plano (`?miniatura=1`, `?descargar=1`) |
| GET | `/api/corridas/<id>/planos.zip` | Todos los planos |
| POST | `/api/corridas/<id>/confirmar` | Confirmar la orden de corte |

Las rutas protegidas esperan el encabezado `X-Admin-Pin`.

---

## Pruebas

```bash
cd backend
pip install -r requirements-dev.txt
pytest                 # 43 pruebas, incluida la de rendimiento (~25 s)
pytest -m "not slow"   # sin la de rendimiento
```

Qué revisan:

- geometría en 24 combinaciones (6 instancias × con y sin rotación × guillotina y libre): cada pieza aparece una sola vez, sin solapes, con separación ≥ kerf, dentro del área útil y cortable en guillotina cuando aplica;
- que el validador detecte solapes y patrones que no son guillotina;
- material (RN-01), veta (RN-02), retazos mínimos (RN-06) y uso de retazos antes que hojas nuevas (RF-03);
- que los cruces OX y PMX no repitan ni pierdan piezas, y que la mejor solución nunca empeore;
- adherencia a la cola ≥ 95 % con peso de cola alto;
- rendimiento: 200 piezas y 50 hojas en 30 s o menos;
- la API completa: altas, validaciones, importación con errores, despiece y seguridad de fórmulas, orden de la cola, PIN, simulación, planos PNG (≥ 1920 × 1080 y DPI), ZIP, confirmación y simulaciones obsoletas.

---

## Estructura del proyecto

```
backend/
  app.py              API REST (Flask); también sirve la interfaz
  seed.py             datos de demostración
  requirements.txt    dependencias para ejecutar
  requirements-dev.txt dependencias para pruebas
  cortes/
    packing.py        geometría, kerf y refilado, decodificadores guillotina y bottom-left
    ga.py             algoritmo genético
    optimizer.py      separación por material, métricas y secuencia de corte
    validate.py       validación geométrica
    render.py         planos PNG y ZIP
    despiece.py       reglas de despiece y evaluador de fórmulas
    importer.py       lectura y validación de .csv/.xlsx
    db.py             esquema SQLite y parámetros por defecto
  tests/              pruebas (pytest)
frontend/
  src/                interfaz en React
  public/             index.html y estilos
  dist/               interfaz compilada (la sirve el backend)
  build.mjs           script de compilación (esbuild)
doc/
  proyecto.md, proyecto.pdf   ERS v1.0
  DECISIONES.md               decisiones de diseño
```

Dependencias de ejecución: Flask, Pillow y openpyxl. Si Matplotlib está instalado se usa su fuente; si no, se busca DejaVu en el sistema, luego Segoe UI o Arial en Windows y, al final, la fuente interna de Pillow.

---

## Trazabilidad de requerimientos

| Req. | Dónde se cumple |
|---|---|
| RN-01 a RN-06 | Ver [Reglas de planta](#reglas-de-planta-que-respeta); `optimizer.py`, `packing.py`, `validate.py` |
| RF-01 / RF-03 Inventario y retazos | Pantalla Inventario; `/api/lotes` |
| RF-02 Carga masiva | `importer.py`; valida todo el archivo antes de cargar |
| RF-04 / RF-05 Cola de órdenes | Pantalla Planeación: alta, edición, flechas, arrastrar y soltar, recálculo del impacto |
| RF-06 Despiece | Pantalla Despiece; vista previa al capturar la orden |
| RF-07 / RF-08 Motor | `optimizer.py`, `ga.py` |
| RF-09 Parámetros | Pantalla Parámetros |
| RF-10 Simulación | Métricas antes de confirmar y comparación con la corrida anterior |
| RF-11 / RF-12 Planos PNG | `render.py` |
| RNF-01 ≤ 30 s | Tiempo límite de 25 s; prueba `test_performance_200_pieces_50_sheets` |
| RNF-02 Resolución | 3300 × 2550 px a 300 DPI |
| RNF-03 Tres clics | Importar órdenes, Optimizar, Descargar planos |
| RNF-04 Integridad | Validación de cada hoja antes de guardar y pruebas automáticas |
| RNF-05 Arquitectura | React separado del backend en Python |

---

## Limitaciones conocidas

- Las fórmulas de despiece que vienen cargadas son de ejemplo. Ingeniería de SprintWindow tiene que capturar las reales en la pantalla Despiece.
- El PIN de administrador es un control básico. No hay usuarios ni roles.
- SQLite y una sola optimización a la vez: está pensado para una planta con pocos usuarios simultáneos.
- El motor trabaja con piezas rectangulares; no acomoda formas irregulares.
- Las fechas del historial se guardan en UTC.

---

## Problemas comunes

| Síntoma | Solución |
|---|---|
| La página dice "Frontend no compilado" | Falta `frontend/dist`. Compílalo con `npm run build` o copia la carpeta `dist` ya compilada |
| `ModuleNotFoundError: No module named 'flask'` | No se instalaron las dependencias o el entorno virtual no está activo (`source .venv/bin/activate`) |
| `pip` no se reconoce (Windows) | Usa `python -m pip install -r requirements.txt` |
| `&&` no es un separador válido (PowerShell) | Escribe cada comando en su propia línea |
| `pip` se corta por tiempo de espera | `pip install --timeout 120 --retries 10 -r requirements.txt` |
| "Ya hay una optimización en curso" | Espera a que termine la anterior (máximo el tiempo límite configurado) |
| "La corrida está obsoleta" al confirmar | Cambió algo después de simular; vuelve a pulsar Optimizar |
| Una orden queda "pendiente por falta de stock" | No hay hojas de ese color, textura y espesor, o no alcanzan. Revisa el inventario |
