# Especificación de Requerimientos de Software (ERS)

**Proyecto:** Sistema de Optimización de Corte y Planeación de Producción (Nesting 2D)

**Cliente:** SprintWindow (Manufactura y Maquila de Persianas de PVC)

**Enfoque:** Ingeniería de Procesos Industriales e Ingeniería de Software

**Versión:** 1.0

---

## 1. Introducción y Contexto Operativo

### 1.1 Propósito del Documento

Definir los requerimientos funcionales, no funcionales, reglas de negocio y especificaciones algorítmicas para el desarrollo del software de optimización de corte de láminas ("hojas") de PVC de **SprintWindow**. Este documento servirá como línea base técnica entre el área de Ingeniería de Procesos/Producción y el equipo de Desarrollo de Software.

### 1.2 Diagnóstico del Proceso y Alcance

En la manufactura de persianas de PVC, el costo de la materia prima representa el componente principal del costo directo de producción. Actualmente, la planeación de cortes sobre hojas de PVC de dimensiones heterogéneas genera acumulación de merma no aprovechable y tiempos muertos por cambios de configuración (*setups*) en maquinaria.

El sistema abordará un **Problema de Corte Bidimensional con Inventario Heterogéneo (*2D Heterogeneous Bin Packing / Cutting Stock Problem*)**, resuelto mediante **Algoritmos Genéticos (AG)**. El alcance abarca desde la captura de inventario y cola de órdenes hasta la generación de planos visuales de corte en formato `.png` listos para operarios en piso.

### 1.3 Glosario Técnico-Operativo

* **Hoja de PVC (Stock):** Lámina de materia prima virgen o retazo recuperado caracterizada por largo, ancho, espesor, color y textura.
* **Pieza / Componente:** Cada segmento rectangular requerido para ensamblar una persiana según su tipo y dimensiones finales.
* **Merma (Scrap):** Porcentaje de área de una hoja de PVC que no es utilizada tras ejecutar el patrón de corte.
* **Retazo Aprovechable (*Offcut*):** Sobrante rectangular continuo que supera un umbral mínimo de dimensiones definido por ingeniería y puede reingresar al inventario.
* **Kerf (Grosor de Corte):** Ancho de material desbastado o perdido por el paso de la herramienta de corte (sierra, disco o cabezal CNC).
* **Corte Tipo Guillotina:** Restricción física donde cada corte debe atravesar de extremo a extremo la sección de la lámina (propio de sierras escuadradoras/seccionadoras).

---

## 2. Reglas de Negocio e Ingeniería de Procesos

Para que la solución matemática sea viable en la planta de SprintWindow, el motor de software debe respetar estrictamente las siguientes restricciones físicas y operativas:

| ID | Regla de Negocio | Tipo de Restricción | Descripción Operativa |
| --- | --- | --- | --- |
| **RN-01** | **Homogeneidad de Material** | Dura (Inviolable) | Una orden o pieza solo puede asignarse a una hoja de PVC que coincida exactamente en **color, textura y calibre/espesor**. |
| **RN-02** | **Restricción de Rotación por Textura** | Dura (Inviolable) | Si la hoja posee una textura direccional (ej. veta tipo madera o grabado lineal), las piezas **no pueden rotarse 90°** respecto al eje de la veta. En acabados lisos/uniformes, se permite rotación de 90° para maximizar el aprovechamiento. |
| **RN-03** | **Compensación por Grosor de Corte (*Kerf*)** | Dura (Inviolable) | El algoritmo debe reservar una separación mínima configurable (ej. $3\text{ mm}$) entre piezas adyacentes y respecto a los bordes de refilado de la hoja. |
| **RN-04** | **Respeto a la Cola de Órdenes (FIFO / Prioridad)** | Blanda (Ponderada) | El sistema debe priorizar el despacho de las órdenes ubicadas al inicio de la cola de producción, permitiendo agrupar (*batching*) órdenes posteriores del mismo material únicamente dentro de una ventana de tolerancia definida. |
| **RN-05** | **Factibilidad Geométrica de Corte** | Dura / Configurable | El sistema deberá permitir configurar si el patrón generado exige **cortes tipo guillotina** (de borde a borde) o **anidamiento libre** (*nesting* para router CNC). |
| **RN-06** | **Clasificación de Sobrantes** | Informativa / Operativa | Todo sobrante rectangular con dimensiones $\ge L_{\min} \times A_{\min}$ (configurable) se etiquetará en el plano como "Retazo Recuperable" y no como desperdicio puro. |

---

## 3. Requerimientos Funcionales (RF)

### Módulo 1: Gestión de Inventario de Hojas de PVC

* **RF-01 (Alta y Edición de Hojas):** El sistema debe permitir registrar lotes de hojas de PVC especificando: ID/Código de lote, Alto ($mm$), Ancho ($mm$), Color, Textura (con indicador booleano de `direccionalidad_veta`), Cantidad disponible y Costo unitario (opcional para valoración de merma).
* **RF-02 (Carga Masiva de Inventario):** El sistema debe permitir importar el inventario de hojas desde archivos estructurados (`.csv` o `.xlsx`) validando la integridad de los datos antes de cargarlos.
* **RF-03 (Gestión de Retazos):** El sistema debe permitir dar de alta retazos sobrantes de corridas anteriores con sus dimensiones reales para que el algoritmo priorice su consumo antes de abrir hojas nuevas.

### Módulo 2: Gestión de la Cola de Órdenes de Producción

* **RF-04 (Captura de Órdenes):** La interfaz debe permitir agregar órdenes a una cola de trabajo indicando: Número de Orden (ID), Cliente/Lote, Tipo de persiana (ej. enrollable, vertical, panel japonés), Dimensiones requeridas (o despiece automático según tipo de persiana), Cantidad de piezas, Color, Textura y Nivel de Prioridad (Normal, Urgente).
* **RF-05 (Reordenamiento Dinámico de Cola):** El usuario debe poder modificar manualmente el orden de la cola mediante controles de subida/bajada o arrastrar y soltar (*drag & drop*), recalculando el impacto en la planeación.
* **RF-06 (Explosión de Materiales / Despiece):** Dado el tipo y medida final de una persiana ingresada en la orden, el sistema debe traducirla a las piezas geométricas exactas que requieren corte en lámina de PVC, aplicando holguras de ensamble predefinidas.

### Módulo 3: Motor de Optimización (Algoritmo Genético)

* **RF-07 (Agrupamiento por Atributos):** Antes de ejecutar la heurística, el motor debe particionar la cola de órdenes y el inventario en subproblemas independientes agrupados por `(Color, Textura)`.
* **RF-08 (Ejecución de Optimización):** El sistema debe ejecutar un Algoritmo Genético que asigne las piezas de la cola a las hojas disponibles minimizando el desperdicio global y respetando las reglas RN-01 a RN-05.
* **RF-09 (Parámetros Configurables de Proceso):** El usuario administrador debe poder ajustar parámetros operativos sin tocar código: grosor de corte (*kerf* en mm), margen de refilado perimetral de hoja, dimensiones mínimas de retazo aprovechable y peso de prioridad de cola frente al ahorro de material.
* **RF-10 (Simulación y Comparativa):** El sistema debe mostrar métricas proyectadas antes de confirmar la orden de corte: total de hojas consumidas, porcentaje de aprovechamiento global, porcentaje de merma neta y órdenes cubiertas vs. pendientes por falta de stock.

### Módulo 4: Generación de Salidas Gráficas (PNG) y Reportes

* **RF-11 (Exportación de Patrones de Corte en PNG):** Por cada hoja de PVC utilizada en la solución óptima, el sistema debe generar y descargar (individualmente o en un archivo `.zip`) una imagen en formato `.png` de alta resolución.
* **RF-12 (Elementos Visuales del Plano PNG):** Cada imagen `.png` debe contener obligatoriamente:
* Encabezado con ID de Corrida, ID de Hoja, Dimensiones totales ($W \times H$), Color, Textura e indicador visual de dirección de veta (flecha).
* Representación a escala de la hoja y cada pieza anidada con bordes definidos considerando el *kerf*.
* Etiqueta interna en cada pieza indicando: `ID Orden`, `Tipo de Persiana`, `Dimensiones exactas (Ancho x Alto)` y marca si la pieza fue rotada 90°.
* Codificación por color o trama para diferenciar las distintas órdenes dentro de una misma hoja.
* Identificación visual (ej. sombreado rayado verde) de los **retazos aprovechables** y área de **merma** (ej. sombreado gris).
* Resumen numérico al pie de la imagen: `% Aprovechamiento`, `% Merma` y `Total de piezas en la hoja`.



---

## 4. Especificación Técnica del Motor de Algoritmo Genético

Para garantizar convergencia rápida y soluciones de alta calidad industrial, el núcleo algorítmico se regirá por el siguiente diseño:

1. **Codificación Cromosómica:** Representación basada en permutaciones de piezas combinada con un decodificador constructivo (*Decoder*), como *Bottom-Left-Fill (BLF)* o *Guillotine Recursive Split* (según la configuración de corte de SprintWindow). Cada gen almacena `(ID_Pieza, Estado_Rotación)`.
2. **Función de Aptitud (*Fitness Function*):** El algoritmo buscará minimizar una función de costo multiobjetivo expresada como:

$$\min F(x) = w_1 \cdot \sum_{j=1}^{M} \left( \frac{A_{\text{merma}, j}}{A_{\text{hoja}, j}} \right) + w_2 \cdot \sum_{i=1}^{N} P_i \cdot \Delta T_i - w_3 \cdot \sum_{k=1}^{R} A_{\text{retazo}, k}$$



Donde:
* $A_{\text{merma}, j}$ es el área desperdiciada en la hoja $j$.
* $P_i \cdot \Delta T_i$ penaliza el desplazamiento de la orden $i$ respecto a su posición original en la cola de producción.
* $A_{\text{retazo}, k}$ bonifica la consolidación del espacio sobrante en rectángulos grandes y reutilizables (evitando desperdicio fragmentado).
* $w_1, w_2, w_3$ son pesos calibrables por Ingeniería de Procesos.


3. **Operadores Genéticos:**
* **Selección:** Torneo determinístico ($k=3$) con elitismo (conservación del top $5\%$ de mejores individuos por generación).
* **Cruce (*Crossover*):** *Order Crossover (OX)* o *Partially Mapped Crossover (PMX)* para preservar la validez de las permutaciones sin duplicar ni omitir piezas de la cola.
* **Mutación:** Intercambio de posición de dos piezas (*Swap*), inversión de subsecuencia (*Inversion*) y alternancia de rotación (cuando `direccionalidad_veta = False`).


4. **Criterios de Parada:** El algoritmo detendrá su ejecución al alcanzar un número máximo de generaciones ($G_{\max}$), tras $X$ generaciones sin mejora en el *fitness* (estancamiento), o al cumplir un tiempo límite de cómputo configurable ($T_{\max}$).

---

## 5. Requerimientos No Funcionales (RNF)

| Categoría | ID | Especificación |
| --- | --- | --- |
| **Rendimiento** | **RNF-01** | El motor de optimización debe entregar una solución convergente en un tiempo **$\le 30\text{ segundos}$** para lotes estándar de hasta 200 piezas y 50 hojas en inventario. |
| **Calidad Gráfica** | **RNF-02** | Los archivos `.png` generados deben tener una resolución mínima de **1920 × 1080 píxeles (150–300 DPI)**, garantizando legibilidad total al ser visualizados en pantallas industriales o impresos en hojas tamaño carta/A4 para el operador de corte. |
| **Usabilidad (UX)** | **RNF-03** | La interfaz de usuario debe seguir principios de diseño limpio y ergonómico para planta: máximo 3 clics para cargar una orden, lanzar la optimización y descargar los planos `.png`. |
| **Integridad de Datos** | **RNF-04** | El sistema debe validar que la suma de áreas de las piezas asignadas a una hoja nunca exceda el área neta útil de la misma, bloqueando cualquier solapamiento geométrico mediante pruebas unitarias automatizadas. |
| **Arquitectura y Portabilidad** | **RNF-05** | Se recomienda una arquitectura desacoplada: Frontend web responsivo (ej. React/Vue) y Backend en Python (aprovechando ecosistemas como `DEAP`/`PyGAD` para el AG, `Shapely`/`rectpack` para geometría y `Matplotlib`/`Pillow` para el renderizado `.png`). |

---

## 6. Criterios de Aceptación y KPIs de Validación

Para dar por concluida la implementación en SprintWindow, el sistema deberá superar un piloto operativo de 2 semanas en paralelo con el método actual, cumpliendo los siguientes indicadores:

1. **Reducción de Merma:** Disminución mínima del **12% al 18%** en el desperdicio total de PVC respecto al promedio histórico de corte manual/empírico.
2. **Cero Defectos de Especificación:** **0% de errores** en asignación de color, sentido de textura/veta o dimensiones de corte imputables al plano generado.
3. **Adherencia al Programa de Producción:** Cumplimiento superior al **95%** en el respeto a la secuencia de entrega dictada por la cola de órdenes.
4. **Trazabilidad Visual:** Aprobación explícita por parte de los supervisores y operarios de corte respecto a la claridad y facilidad de lectura de los patrones `.png` generados.
