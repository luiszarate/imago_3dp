---
name: imago_3dp · Dashboard de impresión 3D
description: Página inicial del operador de impresión 3D, extensión del backend nativo de Odoo 14 CE.
colors:
  o-brand-primary: "#7C7BAD"
  p3d-page: "#f8f9fa"
  p3d-surface: "#ffffff"
  p3d-line: "#dee2e6"
  p3d-ink: "#4c4c4c"
  p3d-ink-strong: "#212529"
  p3d-ink-muted: "#6c757d"
  p3d-critical: "#c0392f"
  p3d-critical-bg: "#fbeceb"
  p3d-warning: "#8a5a00"
  p3d-warning-bg: "#fdf3dc"
  p3d-info: "#1f5f99"
  p3d-info-bg: "#e8f1fb"
  p3d-ok: "#1d7a1d"
  p3d-ok-bg: "#e9f5e9"
  p3d-idle: "#495057"
  p3d-idle-bg: "#e9ecef"
  chart-series-1: "#2a78d6"
  chart-series-2: "#eb6834"
  chart-series-3: "#1baf7a"
  chart-series-4: "#eda100"
  chart-series-5: "#e87ba4"
  chart-series-6: "#008300"
  chart-series-7: "#6250d6"
  chart-series-8: "#e34948"
  chart-status-ok: "#0ca30c"
  chart-status-partial: "#fab219"
  chart-status-failed: "#d03b3b"
  chart-ink-secondary: "#5f5e5a"
  chart-grid: "#ebeae6"
typography:
  wall-poster:
    fontFamily: "Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "2.3rem"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "-0.01em"
  wall-state:
    fontFamily: "Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "1.6rem"
    fontWeight: 600
  wall-detail:
    fontFamily: "Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "1.4rem"
    fontWeight: 400
  wall-row:
    fontFamily: "Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "1.05rem"
    fontWeight: 600
  wall-row-detail:
    fontFamily: "Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "0.95rem"
    fontWeight: 400
  wall-stamp:
    fontFamily: "Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "0.9rem"
    fontWeight: 600
  headline:
    fontFamily: "Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "1.2rem"
    fontWeight: 600
    lineHeight: 1.25
  title:
    fontFamily: "Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "1.15rem"
    fontWeight: 600
  section-title:
    fontFamily: "Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
  body:
    fontFamily: "Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "1.0833rem"
    fontWeight: 400
    fontFeature: "tnum"
  small:
    fontFamily: "Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "0.86em"
    fontWeight: 400
  label:
    fontFamily: "Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "0.8rem"
    fontWeight: 600
    letterSpacing: "0.02em"
  stamp:
    fontFamily: "Roboto, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "0.76rem"
    fontWeight: 600
    letterSpacing: "0.02em"
rounded:
  stamp: "3px"
  surface: "4px"
  pill: "999px"
spacing:
  gap: "16px"
  strip-gap: "10px"
  row: "7px"
  card: "12px 14px"
  panel: "14px 16px"
  page: "12px 16px 24px"
components:
  panel:
    backgroundColor: "{colors.p3d-surface}"
    rounded: "{rounded.surface}"
    padding: "{spacing.panel}"
  action-card:
    backgroundColor: "{colors.p3d-surface}"
    textColor: "{colors.p3d-ink}"
    rounded: "{rounded.surface}"
    padding: "{spacing.card}"
    width: "minmax(260px, 300px)"
  action-card-critical:
    backgroundColor: "{colors.p3d-critical-bg}"
    textColor: "{colors.p3d-critical}"
  action-card-warning:
    backgroundColor: "{colors.p3d-warning-bg}"
    textColor: "{colors.p3d-warning}"
  severity-label-info:
    backgroundColor: "{colors.p3d-info-bg}"
    textColor: "{colors.p3d-info}"
    rounded: "{rounded.pill}"
    padding: "1px 8px 1px 6px"
  station-band-free:
    backgroundColor: "{colors.p3d-ok-bg}"
    textColor: "{colors.p3d-ok}"
    typography: "{typography.headline}"
    padding: "8px 16px"
  station-band-printing:
    backgroundColor: "{colors.p3d-info-bg}"
    textColor: "{colors.p3d-info}"
    typography: "{typography.headline}"
    padding: "8px 16px"
  station-band-out-of-service:
    backgroundColor: "{colors.p3d-idle-bg}"
    textColor: "{colors.p3d-idle}"
    typography: "{typography.headline}"
    padding: "8px 16px"
  stamp-ok:
    textColor: "{colors.p3d-ok}"
    typography: "{typography.stamp}"
    rounded: "{rounded.stamp}"
    padding: "0 6px"
  stamp-failed:
    textColor: "{colors.p3d-critical}"
    typography: "{typography.stamp}"
    rounded: "{rounded.stamp}"
    padding: "0 6px"
  chip-warning:
    backgroundColor: "{colors.p3d-warning-bg}"
    textColor: "{colors.p3d-warning}"
    rounded: "{rounded.pill}"
    padding: "0 7px"
  meter-track:
    backgroundColor: "{colors.p3d-idle-bg}"
    rounded: "{rounded.pill}"
    height: "8px"
  trend-tab-active:
    textColor: "{colors.p3d-ink-strong}"
    padding: "6px 10px"
  wall-next-critical:
    backgroundColor: "{colors.p3d-critical-bg}"
    textColor: "{colors.p3d-ink-strong}"
    typography: "{typography.wall-poster}"
    rounded: "{rounded.surface}"
    padding: "1rem 1.5rem"
---

# Design System: imago_3dp · Dashboard de impresión 3D

## Overview

**Creative North Star: "El tablero del cuarto de impresión"**

El dashboard es una superficie nueva dentro de un mundo ya establecido: el backend de Odoo 14 CE (Roboto, `$o-brand-primary` #7C7BAD, Bootstrap 4, raíz de 12 px). Este documento registra el sistema propio del dashboard como extensión de ese mundo; no redefine Odoo. Botones, pestañas, barra de navegación y panel de control siguen siendo los de Odoo, y todo lo que el dashboard agrega se apoya en los neutrales de Bootstrap y en variables de Odoo.

La pantalla se ordena por lo que exige acción: una línea de resumen, la franja de pendientes ordenada por severidad, la fila de estaciones (una tarjeta por impresora con banda de estado) y, al pie, cola, carretes y tendencias. La densidad es la de un backend de trabajo: superficies blancas planas sobre el gris de página, bordes de 1 px, radio de 4 px y números tabulares. El color de estado es escaso y significa algo; el índigo de Odoo solo marca selección, foco y la acción principal.

El mismo sistema tiene dos lecturas. En la PC del operador se trabaja con clics. En el Modo pantalla se lee a distancia: la raíz crece, desaparecen los botones y el cromo de Odoo, y el primer pendiente se vuelve un cartel.

**Key Characteristics:**
- Extensión del look nativo de Odoo 14; nada de marca propia en esta superficie.
- Superficies planas blancas, borde gris de 1 px, radio de 4 px.
- Estado siempre como palabra + ícono Font Awesome + color, nunca solo color.
- Colores de estado en tonos oscuros aptos para texto, cada uno con su fondo tintado.
- Números tabulares en toda la superficie.
- Un modo pantalla que escala por la raíz `rem`, sin botones y en una sola pantalla a partir de 1200 px.

## Colors

Neutrales de Bootstrap con el índigo de Odoo como único acento de interfaz, más una familia de estados reservada y una paleta de gráficas aparte.

### Primary
- **Índigo Odoo** (`o-brand-primary`): botón principal de cada tarjeta (`btn-primary` de Odoo), contorno de foco (2 px, desplazado 2 px), subrayado de la pestaña activa de Tendencias, selección de texto al 25 % y sombreado del eje en los tooltips de gráficas. Nunca indica un estado.

### Neutral
- **Gris de página** (`p3d-page`, `$gray-100`): fondo de toda la acción cliente.
- **Superficie blanca** (`p3d-surface`, `$o-view-background-color`): paneles, tarjetas, estaciones.
- **Línea** (`p3d-line`, `$gray-300`): bordes de superficie, separadores de filas y tablas, borde de pestañas, barra de desplazamiento de la franja.
- **Tinta** (`p3d-ink`, `$o-main-text-color`): texto corriente, igual que el resto de Odoo.
- **Tinta fuerte** (`p3d-ink-strong`, `$gray-900`): títulos, números del resumen, nombres de estación, enlaces.
- **Tinta tenue** (`p3d-ink-muted`, `$gray-600`): datos secundarios, encabezados de tabla, leyendas, conteos.
- **Inactivo** (`p3d-idle` / `p3d-idle-bg`, `$gray-700` / `$gray-200`): impresora fuera de servicio, sello cancelado y el riel vacío de los medidores.

### Estados
- **Crítico** (`p3d-critical` sobre `p3d-critical-bg`): atrasos, pendientes urgentes, filamento insuficiente, sello Fallido, carrete vacío.
- **Aviso** (`p3d-warning` sobre `p3d-warning-bg`): atención, carrete casi vacío, intento pasado de tiempo, sello Parcial.
- **Información** (`p3d-info` sobre `p3d-info-bg`): impresora imprimiendo, avance estimado, pendientes de tipo aviso.
- **Correcto** (`p3d-ok` sobre `p3d-ok-bg`): impresora libre, sello OK, carrete nuevo o abierto, "Todo al día".

### Gráficas
- **Categóricas** (`chart-series-1` … `chart-series-8`): paleta de referencia de visualización; las series toman los lugares en ese orden fijo (consumo por propósito; la serie única de ocupación y de causas de falla usa el lugar 1).
- **Resultados** (`chart-status-ok`, `chart-status-partial`, `chart-status-failed`): reservados para la serie OK / Parcial / Fallido. Son colores de relleno, no de texto.
- **Tinta y rejilla de gráficas** (`chart-ink-secondary`, `chart-grid`, más `p3d-ink` como texto del tooltip): etiquetas de categoría, leyenda y líneas de división.

### Named Rules
**The Tinta Legible Rule.** Todo texto pasa 4.5:1 sobre su fondo. Por eso la tinta tenue es `$gray-600` y no `$o-main-color-muted` (#a8a8a8), que falla sobre blanco, y por eso los estados de texto son los tonos oscuros `p3d-*`, no los de la paleta de gráficas.

**The Estado con Palabra Rule.** Un estado siempre lleva su palabra y su ícono Font Awesome (Urgente `fa-exclamation-circle`, Atención `fa-exclamation-triangle`, Aviso `fa-info-circle`, Libre `fa-check`, Imprimiendo `fa-cog`, Fuera de servicio `fa-ban`). El color refuerza; nunca es la única señal.

**The Índigo No Es Estado Rule.** El índigo de Odoo marca selección, foco y la acción principal; ningún estado de impresora ni de severidad se pinta con él.

## Typography

**Display Font:** Roboto (con "Helvetica Neue", Arial, sans-serif), la fuente del backend de Odoo 14
**Body Font:** Roboto, igual

**Character:** Una sola familia, jerarquía por tamaño y peso (400 / 500 / 600), cifras tabulares en todo el dashboard para que horas, gramos y conteos se alineen.

Todos los tamaños son `rem` sobre la raíz de Odoo (12 px; cuerpo de 13 px). En Modo pantalla la raíz pasa a `clamp(14px, 1.05vw, 32px)` (≈20 px a 1920) y toda la escala crece con ella; los pasos `wall-*` (estado 1.6rem, detalle 1.4rem, fila 1.05rem, detalle de fila 0.95rem, sello 0.9rem) solo existen en ese modo.

### Hierarchy
- **Cartel** (600, 2.3rem, 1.15, -0.01em, `text-wrap: balance`): solo el primer pendiente en Modo pantalla; su detalle va a 1.4rem en tinta tenue.
- **Headline** (600, 1.2rem, 1.25): título de cada tarjeta de pendiente y palabra de estado en la banda de la estación (1.6rem en Modo pantalla).
- **Title** (600, 1.15rem): nombre de la estación y números del resumen (1.6rem en Modo pantalla).
- **Section title** (600, 1rem): Pendientes, Cola de trabajos, Carretes, Tendencias; el conteo junto al título va en 400 y tinta tenue.
- **Body** (400, 13 px de Odoo): filas, tablas, detalle de tarjeta (0.9em).
- **Small** (400, 0.86em): estado de actualización, leyendas, datos secundarios de filas.
- **Label** (600, 0.8rem, 0.02em): encabezados de grupo en cola y carretes, encabezados de tabla.
- **Sello** (600, 0.76rem, 0.02em, mayúsculas): resultado de intento; la causa dentro del sello vuelve a minúsculas en 500.

### Named Rules
**The Cifras Tabulares Rule.** `font-variant-numeric: tabular-nums` se fija en la raíz del dashboard; ningún bloque lo apaga.

## Layout

Página con relleno de 12 px 16 px 24 px y separación base de 16 px entre bloques.

- **Resumen:** una línea flexible que se envuelve (separación 4 px 20 px entre conteos), con herramientas a la derecha y un borde inferior de 1 px.
- **Franja de pendientes:** una fila desplazable horizontalmente, columnas de 260–300 px, separación de 10 px, `scroll-snap` por proximidad. Ordenada por severidad.
- **Estaciones:** rejilla `auto-fit` de columnas de al menos 290 px: las impresoras se reparten todo el ancho, sin columnas vacías a la derecha.
- **Fila inferior:** áreas "queue spools" / "trends trends". A partir de 1200 px (Bootstrap `lg`) Cola 3fr | Carretes 2fr comparten fila y alto (el panel más corto se estira hasta el más largo, sin huecos de fondo), y Tendencias va debajo a todo el ancho. Por debajo de 1200 px Cola y Carretes quedan en dos columnas iguales. Por debajo de `sm` todo va en una columna, la franja usa tarjetas de 240 px–85 % y se oculta el texto de estado de actualización.
- **Filas:** separadas por línea de 1 px, 7 px de alto de relleno.

**Modo pantalla:**
- La raíz `html` pasa a `clamp(14px, 1.05vw, 32px)`; como Odoo mide en `rem` desde 12 px, todo el dashboard escala para leerse a distancia.
- A partir de 1200 px es una sola pantalla de alto `100vh` con áreas "summary" / "actions queue spools" (6fr 5fr 4fr) / "stations" (todo el ancho, columnas `minmax(20rem, 1fr)`).
- Las filas que pasan los límites (cola 7, filamentos 5, carretes críticos 4, pendientes 1 cartel + 3) se ocultan y se cuentan en una línea visible "+N más".
- Por debajo de 1200 px el modo pantalla se desplaza y lo muestra todo (estaciones `minmax(24rem, 1fr)`).
- Sin botones, sin la barra de Odoo ni el panel de control; solo queda el conmutador para salir, fijo abajo a la derecha al 60 % de opacidad.

**Restricción de plataforma:** Odoo 14 CE no incluye la meta `viewport`, así que en teléfonos la página se maqueta a 980 px. No es una decisión del dashboard.

## Elevation & Depth

El dashboard es plano: la profundidad se expresa con el gris de página contra superficies blancas, bordes de 1 px y fondos tintados de estado. Ninguna superficie propia lleva sombra. La única elevación es el tooltip de las gráficas, que flota sobre la gráfica.

### Shadow Vocabulary
- **Tooltip de gráfica** (`box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08)`): solo el tooltip de ECharts, sobre fondo blanco con borde `chart-grid`.

### Named Rules
**The Plano por Tono Rule.** Una superficie se separa por tono y por borde, no por sombra.

## Shapes

Esquinas apenas suavizadas (4 px) en paneles, tarjetas, estaciones y en el cartel del Modo pantalla; los sellos van a 3 px con borde de 1 px en `currentColor`, como un sello de goma. Las etiquetas de severidad, los chips y los medidores son píldoras (999 px). Las estaciones recortan su contenido (`overflow: hidden`) para que la banda de estado llegue de borde a borde. En Modo pantalla las tarjetas de la franja pierden radio y borde lateral y se vuelven filas con solo una línea inferior.

## Components

### Botones
- **Origen:** los de Odoo, sin restilizar: `btn btn-primary btn-sm` para la acción principal, `btn btn-secondary btn-sm` para las demás, `btn-link` para actualizar.
- **Uno por tarjeta:** cada pendiente trae un solo botón (su acción, o "Abrir"); la estación lleva Terminar intento (principal, solo con trabajo en curso) y Montar carrete.
- **Foco:** contorno de 2 px en índigo Odoo, desplazado 2 px.

### Tarjeta de pendiente
- **Forma:** superficie de 4 px, relleno 12 px 14 px, columna con separación de 4 px.
- **Severidad:** crítica y aviso tiñen el fondo y el borde (35 % / 25 % del color); información queda blanca y solo tiñe su etiqueta.
- **Etiqueta de severidad:** píldora con ícono y palabra (Urgente / Atención / Aviso), 0.78rem 600, sobre blanco al 70 % en tarjetas tintadas.
- **Entrada:** una tarjeta nueva entra con 420 ms `cubic-bezier(0.16, 1, 0.3, 1)` desde 0.35 de opacidad y 6 px abajo. Es la única animación de entrada del sistema.

### Estación
- **Estructura:** cabeza (nombre + modelo), banda de estado de borde a borde, cuerpo (trabajo, medidor de avance estimado), carrete (medidor delgado, gramos), el sello del último intento, acciones al pie.
- **Banda:** Libre en correcto, Imprimiendo en información, Fuera de servicio en inactivo; palabra grande con ícono y "Fin ≈ hh:mm" a la derecha.
- **Movimiento:** el engrane de Imprimiendo gira lento (6 s, lineal, infinito).

### Lectura en vivo
- **Bloque** dentro de la estación, entre el cuerpo y el carrete: fondo `p3d-page`, línea superior de 1 px `p3d-line`, padding 8 × 16 px. Solo aparece en impresoras con conexión.
- **Encabezado:** "Impresora: <estado>" con ícono Font Awesome y el color del estado (información imprimiendo, crítico en error, correcto terminada, `p3d-idle` sin datos o apagada); a la derecha, la antigüedad del dato ("hace 12 s") en tinta tenue.
- **Métricas** en una fila que se envuelve (`small`, tinta normal): boquilla y cama "actual/objetivo °C", capa, minutos imprimiendo y faltantes; sin datos frescos no se muestran.
- **Foto** de la cámara 4:3, radio 4 px, `object-fit: cover`, hasta 22rem de ancho. El bloque es una fila flexible que se envuelve: en una estación ancha la foto va a la derecha de la lectura (`o_p3d_live_info`, base 20rem); en una angosta baja debajo a lo ancho. En Modo pantalla, máximo 9rem de alto.
- El medidor de avance dice "en vivo" cuando la impresora reporta avance y "estimado por tiempo" cuando no: la fuente del dato siempre es visible.

### Sellos de intento
- **Estilo:** texto y borde en el color del resultado (OK correcto, Parcial aviso, Fallido crítico, Cancelado inactivo), mayúsculas, causa en minúsculas tras " · ". Los intentos terminados quedan sellados en su estación.

### Medidor
- **Riel:** píldora de 8 px (5 px el del carrete; 0.75rem en Modo pantalla) sobre `p3d-idle-bg`; relleno información para avance, correcto/aviso/crítico para el estado del carrete. Siempre acompañado de su cifra en texto.

### Chips
- **Aviso:** píldora tintada 0.76rem 600, p. ej. "1 casi vacío" junto al filamento.

### Pestañas de Tendencias
- **Estilo:** `nav-tabs` de Odoo en una fila desplazable sin barra; inactivas en tinta tenue, activa en tinta fuerte 500 con subrayado de 2 px índigo. Gráfica de 250 px; sin datos, mensaje centrado "Sin datos en el periodo".

### Cartel del Modo pantalla
- **Estilo:** superficie tintada según la severidad del primer pendiente, relleno 1rem 1.5rem, palabra de severidad con ícono a 0.55em antes del título, detalle debajo a 1.4rem.

## Do's and Don'ts

### Do:
- **Do** construir sobre las variables de Odoo y Bootstrap (`$gray-*`, `$o-main-text-color`, `$o-brand-primary`) y sobre los componentes nativos de Odoo; el dashboard extiende Odoo 14, no lo reemplaza.
- **Do** acompañar cada estado con su palabra y su ícono Font Awesome, además del color.
- **Do** usar los tonos `p3d-critical`, `p3d-warning`, `p3d-info` y `p3d-ok` para texto y sus fondos `-bg` para tintar superficies.
- **Do** asignar los colores de serie en el orden fijo de la paleta de gráficas y reservar `chart-status-*` para OK / Parcial / Fallido.
- **Do** contar lo que el Modo pantalla oculta en una línea visible "+N más".
- **Do** desactivar toda animación bajo `prefers-reduced-motion: reduce` (entrada de tarjetas y engrane).
- **Do** quitar las clases del Modo pantalla de `html` y `body` al salir de la acción, para no alterar otras pantallas de Odoo.

### Don't:
- **Don't** usar `$o-main-color-muted` (#a8a8a8) para texto: falla 4.5:1 sobre blanco.
- **Don't** usar los colores de gráfica (`chart-status-partial` #fab219 y compañía) como color de texto.
- **Don't** pintar un estado con el índigo de Odoo.
- **Don't** poner sombras en superficies propias del dashboard; la única sombra es el tooltip de gráfica.
- **Don't** mostrar botones ni el cromo de Odoo en Modo pantalla, salvo el conmutador para salir.
- **Don't** agregar animaciones de entrada además de la de tarjetas nuevas.
