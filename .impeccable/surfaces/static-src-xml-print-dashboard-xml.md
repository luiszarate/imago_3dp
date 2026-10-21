---
version: 1
slug: "static-src-xml-print-dashboard-xml"
primary_target: "static/src/xml/print_dashboard.xml"
related_targets: ["static/src/scss/print_dashboard.scss","static/src/js/print_dashboard.js"]
---

# Dashboard del operador de impresión 3D

Scope: acción cliente `imago_3dp_dashboard` (Odoo 14), página inicial del operador. Modo: **Operate**.

Audiencia y tarea: el operador (PC, con clics) decide qué hacer ahora; el jefe de manufactura y los ingenieros leen la pantalla mural del cuarto. Contenido: pendientes, estaciones (impresoras), cola de trabajos (por revisar, en cola, post-proceso), carretes (resumen por filamento + críticos) y tendencias. Restricciones: look nativo de Odoo 14 (Roboto, `$o-brand-primary` #7C7BAD, componentes Bootstrap 4 de Odoo), sin datos inventados, F1 muestra lo registrado en Odoo.

## Direction contract

THESIS: Lo que exige acción manda la pantalla; el cuarto de impresión se lee como una fila de estaciones debajo. Rechaza el tablero de mosaicos de KPI con gráficas al frente.

OWN-WORLD: Odoo 14 nativo: superficies blancas sobre gris de fondo de Odoo, tinta #212529, índigo #7C7BAD solo para selección y la acción principal, colores de estado reservados (ok #0ca30c, aviso #fab219, crítico #d03b3b, imprimiendo = azul información) siempre con palabra e ícono Font Awesome. Bordes de 1 px, radio 4 px, números tabulares.

STORY: El operador ve en dos segundos qué está atrasado, qué carrete se acaba y qué máquina espera trabajo; resuelve cada pendiente con el botón que trae su tarjeta. Desde lejos, cualquiera ve qué imprime cada estación y cuándo termina.

FIRST VIEWPORT: Barra de resumen en una línea (imprimiendo n/N, en cola, por revisar, post-proceso, atrasadas, fallos 7 d) con el botón Modo pantalla a la derecha. Debajo, la franja de acciones: tarjetas en una fila desplazable, ordenadas por severidad, cada una con su único botón. Debajo, la fila de estaciones a todo el ancho: banda de estado con palabra grande, solicitud en curso, avance estimado con hora de fin, carrete y gramos, y sellos de los últimos intentos. Al pie, tres paneles: cola, carretes, tendencias (pestañas entre cuatro gráficas).

Signature move: la franja de acciones; en Modo pantalla se vuelve una banda de "siguiente acción" a escala de cartel (donación de la señalización de aeropuerto), sin botones ni menú de Odoo. Los intentos terminados quedan sellados en su estación (OK / Fallido · causa), nunca desaparecen (donación de la cartera de boletos).

FORM: "Franja de acciones sobre las estaciones", posición 1 de mi lista ordenada; seed key 3c745ad7.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Unresolved
- Telemetría en vivo (F2) reemplazará el avance estimado por el leído de la impresora.
- Vista de solo lectura para ingenieros (REQ-3DP-110).
