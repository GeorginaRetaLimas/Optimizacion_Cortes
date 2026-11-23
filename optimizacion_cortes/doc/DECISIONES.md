# Decisiones de diseño e interpretación de la ERS

La ERS v1.0 deja algunos puntos abiertos o ambiguos. Este documento registra cómo se resolvió cada uno en la implementación, para que el equipo y el cliente puedan validarlos o pedir cambios.

## 1. Material (RN-01, RF-07)

- Los subproblemas se agrupan por **(color, textura, espesor)**, no solo por (color, textura) como dice RF-07, porque RN-01 exige que coincida también el espesor.
- Al comparar se ignoran mayúsculas y espacios ("Blanco " = "blanco").
- Por eso se agregó el campo **espesor** a las hojas (RF-01) y a las órdenes (RF-04).

## 2. Convención de ejes y veta (RN-02)

- Toda medida está en milímetros. Hojas y piezas se describen como **Ancho (W) × Alto (H)**. El origen está en la esquina inferior izquierda.
- En una hoja con veta direccional, **la veta corre paralela al ancho** (eje X).
- Cada componente de una pieza indica qué dimensión debe ir paralela a la veta (`veta = ancho | alto`). Por ejemplo, una lama vertical lleva la veta a lo largo de su alto.
- En hojas con veta direccional el motor nunca gira las piezas. En hojas lisas puede girarlas 90°.
- En el plano, la marca **⟳90°** indica que la pieza quedó girada respecto a su orientación de veta. Solo puede aparecer en hojas sin veta.

## 3. Kerf y refilado (RN-03, RF-09)

- **Refilado**: banda perimetral que se descarta en cada lado. El área útil es `[r, W−r] × [r, H−r]`.
- **Kerf**: separación mínima entre piezas adyacentes y entre una pieza y un retazo.
- Para que la separación respecto al borde refilado también cumpla RN-03 sin contar el kerf dos veces, se exige **refilado ≥ kerf**. El sistema rechaza parámetros que no cumplan esta condición.
- Implementación: cada pieza se "infla" a (w+k, h+k) dentro de una caja útil de (W−2r+k) × (H−2r+k).

## 4. Función de aptitud (sección 4.2)

Se conservan los tres términos de la ERS, normalizados para que los pesos se puedan comparar entre sí:

```
F = w1 · Σ_j (A_merma,j / A_hoja,j)
  + w2 · Σ_i (P_i · ΔT_i) / Σ_i P_i
  − w3 · Σ_k A_retazo,k / Σ_j A_hoja,j
  + w4 · (Σ_j A_hoja,j / Σ A_piezas − 1)
  + 1000 · (área de piezas sin colocar / área total de piezas)
```

- **Merma y retazos no se traslapan**: merma = área de la hoja − piezas − retazos recuperables. Así un retazo no se cuenta dos veces.
- **Término w4 (consumo de material)**: es un término **agregado** a la ERS. En pruebas con 200 piezas, la fórmula original premiaba repartir las piezas en más hojas, porque cada hoja nueva deja retazos que "bonifican" en w3. En modo guillotina el resultado fue 21 hojas con 70 % de aprovechamiento sin w4, contra 19 hojas y 77 % con w4. En anidamiento libre no hubo diferencia (18 hojas en ambos casos). Si se quiere la fórmula exacta de la ERS, basta con poner `w4 = 0`.
- **Penalización por faltante**: obliga al motor a cubrir primero todas las piezas posibles.

## 5. Desplazamiento en la cola ΔT_i y ventana de tolerancia (RN-04)

- La "terminación" de una orden es la posición, dentro de la secuencia de corte, de la última hoja que contiene una de sus piezas.
- Las órdenes se ordenan por terminación (los empates se resuelven por su posición en la cola). ΔT_i = máx(0, rango obtenido − posición original − ventana).
- **Ventana de tolerancia**: número de posiciones que una orden puede atrasarse sin penalización. Esto permite el *batching* de órdenes cercanas del mismo material.
- P_i vale 1 para órdenes normales y `peso_urgente` (3 por defecto) para las urgentes.
- Las órdenes urgentes nuevas se insertan en la cola detrás de las urgentes ya existentes. El usuario puede reordenar después.
- **Prioridad entre materiales**: cada material se optimiza por separado (RF-07). Después se arma una **secuencia global de corte**: las hojas se ordenan según la orden más prioritaria que contienen. La métrica "Adherencia a la cola" es el % de órdenes con ΔT = 0 (KPI 3: > 95 %).

## 6. Decodificadores y selección de hojas (sección 4.1)

- **Guillotina**: partición recursiva de rectángulos libres, con elección del rectángulo por *Best Area Fit* y la regla de corte que deja el sobrante más grande. Los patrones son siempre cortables de borde a borde, y las pruebas lo verifican.
- **Anidamiento libre (CNC)**: MaxRects con regla *Bottom-Left*, equivalente a BLF para rectángulos.
- **Orden de apertura de hojas**: cuando una pieza no cabe en ninguna hoja abierta, se abre primero un **retazo** (el más pequeño de los que la alojan, RF-03). Si no hay, se abre una hoja nueva, empezando por la de mayor área y, en empate, la de menor costo.
- Si el gen pide una rotación que no cabe y la textura lo permite, se intenta la otra orientación.

## 7. Retazos recuperables (RN-06)

- Un sobrante califica como retazo si su lado largo es ≥ L_min y su lado corto es ≥ A_min, en cualquier orientación.
- Al confirmar el corte, cada retazo se da de alta en el inventario como lote `RZ-<corrida>-<n>`, con el mismo material y veta, y un costo prorrateado por área. Así entra en la siguiente optimización.

## 8. Despiece (RF-06)

- La ERS no incluye las fórmulas de despiece. Se implementó un **editor de reglas por tipo de persiana**: holguras con nombre y fórmulas aritméticas para ancho, alto y cantidad.
- Las fórmulas se evalúan de forma segura, sin `eval`.
- Las reglas que vienen precargadas (Enrollable, Vertical, Panel japonés) son **de referencia**. Ingeniería de SprintWindow debe sustituirlas por las reales.
- Las piezas se calculan al capturar la orden y se guardan con ella, así que un cambio posterior en las reglas no altera órdenes ya registradas.

## 9. Confirmación, órdenes parciales y consistencia

- Una simulación se puede **confirmar** una sola vez. Al hacerlo se descuentan hojas, se dan de alta los retazos y se registran las piezas cortadas.
- Si falta material, la orden se corta parcialmente y **queda en la cola con sus piezas restantes**.
- Cualquier cambio en inventario, cola o parámetros deja **obsoletas** las simulaciones sin confirmar, para que nunca se confirme un plan con datos viejos.
- Antes de guardar una corrida se valida cada hoja con pruebas geométricas: sin solapes, separación ≥ kerf, dentro del área útil, veta respetada y patrón guillotinable cuando aplica. Si alguna falla, la corrida se rechaza (RNF-04).

## 10. Planos PNG (RNF-02)

- Las imágenes miden **3300 × 2550 px a 300 DPI**: tamaño carta horizontal a resolución completa. Superan el mínimo de 1920 × 1080 y se imprimen sin escalar.
- Si el texto no cabe dentro de una pieza pequeña, se reduce a su número (#n), y la tabla lateral muestra el detalle completo.

## 11. Usabilidad (RNF-03) y roles

- **Flujo de 3 clics** en la pestaña Planeación: ① Importar órdenes (el servidor valida y carga en el mismo paso), ② Optimizar, ③ Descargar planos (.zip).
- Parámetros y reglas de despiece están protegidos con un PIN de administrador (variable de entorno `SPRINTWINDOW_ADMIN_PIN`, por defecto `1234`). Es un control básico; si se necesita gestión real de usuarios, habría que agregar autenticación.

## 12. Rendimiento (RNF-01)

- T_max por defecto es 25 s y se reparte entre los materiales según su número de piezas. El caso de 200 piezas y 50 hojas termina en ≤ 30 s, y lo verifica `test_performance_200_pieces_50_sheets`.

## 13. Bibliotecas (RNF-05)

- La ERS **recomienda** DEAP/PyGAD y Shapely/rectpack. El algoritmo genético y los decodificadores se programaron directamente en Python, sin esas dependencias, por tres razones:
  - el cromosoma necesita genes `(ID_Pieza, Rotación)`, y los cruces OX y PMX deben mover la rotación junto con la pieza;
  - el decodificador tiene que aplicar kerf, refilado, veta y la política de retazos;
  - así no hay dependencias pesadas que instalar.
- Se usan Flask para la API, Pillow para dibujar los planos (con la fuente DejaVu que trae Matplotlib) y openpyxl para leer y escribir Excel.
