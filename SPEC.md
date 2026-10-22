# imago_3dp — Especificación funcional y técnica v0.1 / v0.2

| Campo | Valor |
|---|---|
| Módulo | `imago_3dp` |
| Versión objetivo | `14.0.1.0.0` (v0.1) · `14.0.2.0.0` (v0.2 F1) · `14.0.2.1.0` (impresión combinada, sección 17) · `14.0.2.2.0` (v0.2 F2/F3) |
| Plataforma | Odoo 14 Community Edition (Python 3.6–3.8) |
| Empresa | Imago Aerospace |
| Documento relacionado | `IMAGO_Holom_Odoo14_MRP_Plan_v0.1.docx` (secciones 4.1, 4.2, 4.4, 6.1) y `IMAGO_Manual_Piloto_MRP_Holom_Odoo14.pdf` |
| Fecha | 13-Oct-2026 (v0.1) · 21-Oct-2026 (v0.2) |
| Estado | v0.1 implementada · v0.2: F1 (dashboard), F2 (puente, drivers, telemetría) y F3 (alertas) implementadas · impresión combinada (sección 17) implementada |

---

## 0. Instrucciones para quien desarrolla (Claude Code)

1. Este documento es la fuente de verdad. Si algo no está especificado, elegir la solución **más simple y estándar de Odoo 14** y anotarla en la sección 14 (Decisiones tomadas durante el desarrollo).
2. Identificadores de código (modelos, campos, métodos, XML ids) en **inglés**. Etiquetas de interfaz (`string=`), mensajes y ayudas **directamente en español** (no se requiere archivo `.po` en v0.1).
3. Compatibilidad estricta con **Odoo 14 CE**: `stock.production.lot` (no `stock.lot`), `stock.inventory` existe, vistas con `attrs`/`states` (no la sintaxis de Odoo 17), sin dependencias Enterprise (`quality`, `mrp_workorder`, `web_studio`, `helpdesk`).
4. Antes de implementar cada punto marcado como **[VERIFICAR]**, leer el código fuente de Odoo 14 (`addons/mrp`, `addons/stock`) y confirmar el comportamiento. Si no se cumple, aplicar el *fallback* indicado.
5. Incluir pruebas automáticas (`tests/`) para los criterios de aceptación de la sección 12.
6. Mantener actualizados `README.md` y `CLAUDE.md` del módulo después de cada cambio de código.

---

## 1. Propósito

Ingeniería sigue desarrollando y madurando prototipos (del Holom y de otros proyectos) en paralelo con la manufactura. La impresión 3D es una de las herramientas que más se usan. Hay **4 impresoras** compartidas entre:

- **Producción:** piezas ABS del Holom, operación `70 [MCH] Imprimir componentes ABS` de la BOM del Wing LH.
- **Desarrollo:** prototipos, a menudo de una sola vez.

El módulo debe permitir:

1. Que un ingeniero envíe una **solicitud de impresión** al encargado con un formulario corto.
2. Que el encargado gestione la cola, asigne impresora y **carrete específico**, y registre cada intento de impresión.
3. Llevar **inventario de filamento por carrete (lote)** y descontar los gramos reales consumidos, incluidos los intentos fallidos.
4. Medir la **ocupación de cada impresora** en los mismos centros de trabajo que usa producción.

### Principios (heredados del plan MRP)

- **No burocrático:** el ingeniero llena como máximo 5 campos obligatorios y adjunta el archivo.
- Usar Odoo estándar siempre que sea posible (centros de trabajo, MO/WO, lotes, inventario).
- Tiempo de máquina (`[MCH]`) separado de la mano de obra (`[LAB]`), con la misma convención del Anexo B del plan.
- **Sin costeo por proyecto en v0.1:** el "propósito" es solo una clasificación para reportes.

---

## 2. Decisiones de diseño acordadas

| ID | Decisión |
|---|---|
| D-01 | Módulo independiente `imago_3dp`, no dentro de `imago_mrp`: no depende del Holom Build y puede ponerse en producción antes. `imago_mrp` podrá depender de él. |
| D-02 | Todos los ingenieros tienen usuario interno de Odoo: la solicitud se crea desde Odoo. El alias de correo queda fuera de alcance. |
| D-03 | Sin costeo ni cuenta analítica por proyecto en v0.1. |
| D-04 | **Seguimiento por carrete:** los productos de filamento usan `tracking = 'lot'`. Cada carrete físico es un lote con etiqueta. |
| D-05 | Un **centro de trabajo por impresora** (`3DP-01` … `3DP-04`), marcado como impresora 3D. Esto resuelve el pendiente 4.4 del plan. |
| D-06 | Cada solicitud genera, de forma transparente, **una MO** de un producto genérico "Prototipo impreso 3D", y **cada intento** de impresión genera **una WO `[MCH]`** en la impresora usada. Así la ocupación de impresoras es una sola para producción y desarrollo. |
| D-07 | El consumo de filamento se registra **al terminar cada intento**, por carrete y en gramos. |
| D-08 | Unidad de stock del filamento: **gramo (g)**. Unidad de compra: **kg**. Ambas en la categoría estándar *Weight*. |

---

## 3. Roles y grupos de seguridad

Categoría de módulo: **Impresión 3D**.

| Grupo (xml id) | Nombre | Quién | Implica |
|---|---|---|---|
| `group_print_requester` | Solicitante | Todos los usuarios internos (ingenieros) | — . Se agrega a `base.group_user` mediante `implied_ids` en datos, para que todo usuario interno lo tenga. |
| `group_print_operator` | Operador de impresión 3D | Encargado(s) de impresión | `group_print_requester`, `mrp.group_mrp_user`, `stock.group_stock_user` |
| `group_print_manager` | Responsable de impresión 3D | Jefe de manufactura / ingeniería | `group_print_operator` |

### Matriz de acceso (ir.model.access)

| Modelo | Solicitante | Operador | Responsable |
|---|---|---|---|
| `imago.print.request` | R C W | R C W | R C W U |
| `imago.print.job` | R | R C W | R C W U |
| `imago.print.consumption` | R | R C W | R C W U |
| `imago.print.purpose` | R | R | R C W U |
| `imago.filament.material` | R | R | R C W U |
| Wizards (transient) | según acción | R C W | R C W |

(R = leer, C = crear, W = escribir, U = eliminar)

### Reglas de registro

- **Solicitante:** puede **leer todas** las solicitudes de su compañía, para que la cola sea transparente. Solo puede **escribir** las propias (`requester_id = user.id`) en estados `draft` y `needs_info`.
- **Operador/Responsable:** leen y escriben todas.
- Regla multi-compañía estándar por `company_id`.

---

## 4. Flujo del proceso (outline)

```
INGENIERO                         ENCARGADO DE IMPRESIÓN                     SISTEMA
─────────                         ──────────────────────                     ───────
1. Crea solicitud (borrador)
   + adjunta STL/3MF o link
2. [Enviar] ───────────────────▶  3. Recibe actividad "Revisar solicitud"
                                  4a. [Pedir aclaración] ──▶ estado Aclarar ─▶ notifica al ingeniero
   ◀── corrige y [Enviar] de nuevo
                                  4b. [Rechazar] (motivo) ──▶ estado Rechazada
                                  4c. [Poner en cola]: impresora prevista,
                                      estimado slicer (min, g)
                                  5. [Iniciar impresión] (wizard):
                                      impresora + carrete(s) ─────────────▶ crea MO (1a vez) + WO [MCH]
                                                                            en esa impresora, arranca timer,
                                                                            impresora = "Imprimiendo"
                                  6. [Terminar intento] (wizard):
                                      resultado OK/Parcial/Fallido,
                                      gramos reales por carrete,
                                      piezas OK, causa de falla,
                                      min. mano de obra (opcional) ───────▶ termina WO, descuenta filamento
                                                                            del carrete, crea WO [LAB] si aplica
                                      - si faltan piezas → vuelve a "En cola"
                                        (otro intento = paso 5)
                                      - si piezas completas → "Post-proceso"
                                  7. [Entregar] ──────────────────────────▶ cierra MO, estado Entregada,
   ◀──────────────────────────────────────────────────────────────────────  notifica al ingeniero
```

### Estados de la solicitud (`state`)

| Valor | Etiqueta | Quién la mueve |
|---|---|---|
| `draft` | Borrador | Solicitante |
| `submitted` | Enviada | Solicitante → [Enviar] |
| `needs_info` | Aclarar | Operador → [Pedir aclaración] |
| `queued` | En cola | Operador → [Poner en cola] / automático tras intento incompleto |
| `printing` | Imprimiendo | Automático al iniciar intento |
| `post` | Post-proceso | Automático al completar las piezas |
| `done` | Entregada | Operador → [Entregar] |
| `rejected` | Rechazada | Operador → [Rechazar] |
| `cancelled` | Cancelada | Solicitante (solo `draft`/`submitted`/`needs_info`) u Operador |

Transiciones permitidas:

```
draft → submitted | cancelled
submitted → queued | needs_info | rejected | cancelled
needs_info → submitted | cancelled
queued → printing | needs_info | rejected | cancelled
printing → queued | post            (solo vía Terminar intento)
post → printing | done               (reimprimir si se detecta defecto en post-proceso)
done, rejected, cancelled → (final; Responsable puede [Reabrir] → queued)
```

---

## 5. Modelo de datos

### 5.1 `imago.filament.material` (catálogo)

| Campo | Tipo | Notas |
|---|---|---|
| `name` | Char, req. | PLA, ABS, PETG, ASA, TPU, Nylon, PC, Otro |
| `code` | Char | Abreviatura para nombre de lote: `PLA`, `ABS`… |
| `active` | Boolean | default True |
| `sequence` | Integer | |
| `notes` | Text | p. ej. temperatura, requiere cámara cerrada |

Datos iniciales (`noupdate="1"`): PLA, ABS, PETG, ASA, TPU, Nylon, PC.

### 5.2 Extensión de `product.template`

| Campo | Tipo | Notas |
|---|---|---|
| `is_filament` | Boolean | "Es filamento 3D" |
| `filament_material_id` | M2o `imago.filament.material` | req. si `is_filament` |
| `filament_color` | Char | req. si `is_filament` |
| `filament_diameter` | Selection `1.75` / `2.85` | default `1.75` |
| `spool_nominal_g` | Float | default 1000 — gramos netos de un carrete nuevo |
| `spool_tare_g` | Float | default 0 — peso del carrete vacío, se configura por marca |

**Constraint** (`@api.constrains`) cuando `is_filament = True`:
- `type == 'product'` (almacenable)
- `tracking == 'lot'`
- la categoría de `uom_id` es *Weight*

**Onchange** al marcar `is_filament`: proponer `type='product'`, `tracking='lot'`, `uom_id = uom.product_uom_gram`, `uom_po_id = uom.product_uom_kgm`.

Agregar los campos en una página "Impresión 3D" del formulario de producto, visible solo si `is_filament`.

### 5.3 Extensión de `stock.production.lot` (carrete)

| Campo | Tipo | Notas |
|---|---|---|
| `is_spool` | Boolean related `product_id.is_filament`, store | |
| `spool_remaining_g` | Float compute | = `product_qty` del lote en la ubicación 3D (y sububicaciones). Usar el estándar `product_qty` si ya representa lo mismo. |
| `spool_remaining_pct` | Float compute | `remaining / product.spool_nominal_g × 100`; widget `progressbar` |
| `spool_state` | Selection compute, store | `new` (nunca consumido), `open`, `low` (≤ umbral de ajustes), `empty` (≤ 0) |
| `mounted_workcenter_id` | M2o `mrp.workcenter` compute | impresora donde está montado (inverso de 5.4 `mounted_lot_id`) |
| `opened_date` | Datetime | se llena con el primer consumo |

Nombre sugerido del lote al generarlo (ver 7.5): `<MATERIAL_CODE>-<COLOR_ABREV>-<seq>`, p. ej. `ABS-NEG-0007`. La secuencia es una sola: `imago.spool`, padding 4.

### 5.4 Extensión de `mrp.workcenter` (impresora)

| Campo | Tipo | Notas |
|---|---|---|
| `is_3d_printer` | Boolean | "Es impresora 3D" |
| `printer_model` | Char | p. ej. "Prusa MK4" |
| `allowed_material_ids` | M2m `imago.filament.material` | materiales compatibles; vacío = todos |
| `mounted_lot_id` | M2o `stock.production.lot` | carrete actualmente montado; dominio `is_spool = True` |
| `out_of_service` | Boolean | "Fuera de servicio" (mantenimiento) |
| `printer_status` | Selection compute | `free` / `printing` / `out_of_service`. `printing` si existe alguna `mrp.workorder` de este centro en `state = 'progress'` (cubre producción **y** prototipos). |
| `current_workorder_id` | M2o compute | WO en progreso |
| `current_request_id` | M2o compute | solicitud del job en curso, si existe |
| `current_eta` | Datetime compute | `date_start` del job + `est_print_minutes` |

### 5.5 `imago.print.purpose` (propósito / proyecto)

| Campo | Tipo |
|---|---|
| `name` | Char, req. |
| `active` | Boolean |
| `sequence` | Integer |

Datos iniciales: "Holom – maduración de prototipo", "Holom – herramental / jigs", "Otro proyecto de desarrollo", "Uso interno / taller".

### 5.6 `imago.print.request` (solicitud) — hereda `mail.thread`, `mail.activity.mixin`

`_order = 'priority desc, date_required asc, id desc'`

| Campo | Tipo | Req. | Notas |
|---|---|---|---|
| `name` | Char | auto | Secuencia `PRT-%(year)s-` padding 4 → `PRT-2026-0001`. Readonly, default `'Nuevo'`. |
| `title` | Char | **Sí** | "¿Qué se imprime?" |
| `requester_id` | M2o res.users | Sí | default usuario actual; tracking |
| `purpose_id` | M2o `imago.print.purpose` | **Sí** | |
| `reference` | Char | No | Referencia libre: SN de Holom, código de proyecto, part number |
| `filament_product_id` | M2o product.product | **Sí** | dominio `is_filament = True`; muestra material + color |
| `allow_substitute` | Boolean | No | "Acepto material/color equivalente" (default True) |
| `qty_pieces` | Integer | **Sí** | default 1, > 0 |
| `date_required` | Date | **Sí** | tracking |
| `priority` | Selection `0/1/2` | No | Normal / Alta / Urgente; widget `priority` |
| `file_ids` | M2m `ir.attachment` | * | widget `many2many_binary`. *Al enviar se exige `file_ids` **o** `file_url`. |
| `file_url` | Char | * | widget `url` (Drive, Onshape, etc.) |
| `infill_pct` | Integer | No | Opcional |
| `layer_height_mm` | Float | No | Opcional |
| `supports` | Selection `auto/yes/no` | No | default `auto` ("Decide el operador") |
| `notes` | Text | No | Notas técnicas |
| `state` | Selection | — | ver sección 4; tracking; default `draft` |
| `operator_id` | M2o res.users | No | dominio grupo operador; default desde ajustes al enviar; tracking |
| `planned_workcenter_id` | M2o mrp.workcenter | No | dominio `is_3d_printer`; impresora prevista |
| `est_print_minutes` | Integer | No | estimado del slicer por intento |
| `est_grams` | Float | No | estimado del slicer por intento |
| `production_id` | M2o mrp.production | — | readonly; creada en el primer intento |
| `job_ids` | O2m `imago.print.job` | — | intentos |
| `job_count` | Integer compute | | |
| `pieces_ok` | Integer compute | | Σ `job.pieces_ok` |
| `grams_total` | Float compute, store | | Σ consumos |
| `grams_failed` | Float compute, store | | Σ consumos de intentos `failed` |
| `print_minutes_total` | Float compute, store | | Σ duración de intentos |
| `is_late` | Boolean compute (search) | | `date_required < hoy` y estado no final |
| `reject_reason` | Text | | |
| `date_submitted` | Datetime | | al enviar |
| `date_done` | Datetime | | al entregar |
| `company_id` | M2o res.company | Sí | default compañía actual |

### 5.7 `imago.print.job` (intento de impresión)

`_order = 'date_start desc'`

| Campo | Tipo | Notas |
|---|---|---|
| `name` | Char compute | `<request.name>/<attempt_no>`, p. ej. `PRT-2026-0001/2` |
| `request_id` | M2o `imago.print.request` | req., `ondelete='cascade'` |
| `attempt_no` | Integer | consecutivo dentro de la solicitud |
| `workcenter_id` | M2o mrp.workcenter | req., dominio `is_3d_printer` |
| `workorder_id` | M2o mrp.workorder | readonly; WO `[MCH]` |
| `labor_workorder_id` | M2o mrp.workorder | readonly; WO `[LAB]` opcional |
| `operator_id` | M2o res.users | default usuario actual |
| `pieces_planned` | Integer | default = piezas pendientes de la solicitud |
| `pieces_ok` | Integer | capturado al terminar |
| `est_grams`, `est_minutes` | Float/Int | copiados de la solicitud, editables |
| `date_start`, `date_end` | Datetime | |
| `duration_minutes` | Float compute, store | |
| `result` | Selection | `running`, `ok`, `partial`, `failed`, `cancelled` |
| `failure_reason` | Selection | `adhesion` (Adhesión/warping), `spaghetti` (Desprendimiento), `clog` (Boquilla tapada), `runout` (Se acabó el filamento), `layer_shift` (Desfase de capas), `file` (Archivo/diseño), `power` (Corte de energía), `other` (Otro) |
| `failure_note` | Text | obligatorio si `failure_reason = other` |
| `labor_minutes` | Integer | mano de obra de preparación y post-proceso (opcional) |
| `consumption_ids` | O2m `imago.print.consumption` | |
| `grams_total` | Float compute, store | |
| `company_id` | M2o related a la solicitud | |

### 5.8 `imago.print.consumption` (consumo por carrete)

Varias líneas por intento: soporta impresoras multimaterial y el cambio de carrete por *runout*.

| Campo | Tipo | Notas |
|---|---|---|
| `job_id` | M2o `imago.print.job` | `ondelete='cascade'`. Opcional si `workorder_id` está lleno (consumo de producción, 7.7). |
| `workorder_id` | M2o mrp.workorder | para consumos de producción sin solicitud |
| `lot_id` | M2o stock.production.lot | req., dominio `is_spool`, con stock > 0 en ubicación 3D |
| `product_id` | M2o related `lot_id.product_id`, store | |
| `grams` | Float | req., > 0 |
| `stock_move_id` | M2o stock.move | readonly; movimiento generado |
| `date` | Datetime | default now |

### 5.9 Ajustes (`res.company` + `res.config.settings`, sección "Impresión 3D" en Ajustes de Manufactura)

| Campo (en res.company) | Tipo | Default |
|---|---|---|
| `print3d_product_id` | M2o product.product | producto genérico de datos (8.1) |
| `print3d_location_id` | M2o stock.location | ubicación interna `<WH>/Stock/3DP` (crearla en datos si es posible; si no, configurarla manualmente) |
| `print3d_default_operator_id` | M2o res.users | vacío |
| `print3d_low_spool_g` | Float | 150 |
| `print3d_labor_workcenter_id` | M2o mrp.workcenter | centro para la WO `[LAB]` (el `3DP` existente del piloto) |

---

## 6. Interfaz

### 6.1 Menú (app nueva "Impresión 3D", icono propio)

```
Impresión 3D
├── Solicitudes
│   ├── Mis solicitudes        (todos)       filtro requester_id = uid, vista por defecto: lista
│   └── Cola de impresión      (operador)    kanban agrupado por state
├── Impresoras                 (operador)    kanban de mrp.workcenter is_3d_printer
├── Carretes                   (operador)    lista de lotes is_spool
├── Reportes                   (operador)
│   ├── Intentos de impresión                pivot / graph / lista
│   └── Consumo de filamento                 pivot / graph sobre imago.print.consumption
└── Configuración              (responsable)
    ├── Filamentos (productos is_filament)
    ├── Materiales
    ├── Propósitos
    └── Ajustes
```

### 6.2 Formulario de solicitud

- **Header:** botones por estado y grupo (sección 7) + `statusbar` con `draft,submitted,queued,printing,post,done`.
- **Smart buttons:** "Intentos (n)" y "Orden de fabricación" (solo operador).
- **Grupo "Solicitud"** (lo que llena el ingeniero, arriba y destacado): `title`, `purpose_id`, `reference`, `filament_product_id`, `allow_substitute`, `qty_pieces`, `date_required`, `priority`, `file_ids`, `file_url`.
- **Grupo plegable "Parámetros (opcional)":** `infill_pct`, `layer_height_mm`, `supports`, `notes`.
- **Pestaña "Impresión"** (visible desde `submitted`, editable solo por operador): `operator_id`, `planned_workcenter_id`, `est_print_minutes`, `est_grams`, totales calculados y lista de `job_ids` (readonly; se crean por wizard).
- Chatter con seguidores, actividades y mensajes.
- Los campos del ingeniero quedan readonly fuera de `draft`/`needs_info` (`attrs`).

### 6.3 Kanban "Cola de impresión"

- Agrupado por `state`; `group_expand` muestra siempre `submitted`, `needs_info`, `queued`, `printing`, `post`.
- Tarjeta: `name`, `title`, solicitante (avatar), material/color, `qty_pieces`, `date_required` (en rojo si `is_late`), prioridad (estrellas) e impresora prevista.
- **No** permitir arrastrar entre columnas: los cambios de estado van por botones con validación. Usar `records_draggable="0"` o validar en `write` (bloquear cambios de `state` que no vengan de los métodos `action_*`, con un flag de contexto).

### 6.4 Kanban "Impresoras"

- Tarjeta por impresora: nombre/código, modelo, `printer_status` (badge verde/azul/gris), solicitud o WO en curso y ETA, carrete montado con barra de % restante.
- Botones: [Montar carrete] (wizard simple que fija `mounted_lot_id`) y [Fuera de servicio] (toggle).

### 6.5 Lista "Carretes"

- Columnas: lote, material, color, gramos restantes, % (progressbar), estado, impresora montada, fecha de apertura.
- Filtros: "Disponibles", "Casi vacíos", "Vacíos", agrupar por material.
- Botones de fila/encabezado: [Pesar carrete] y [Marcar como agotado].

### 6.6 Búsqueda de solicitudes

Filtros: "Mis solicitudes", "Pendientes" (no finales), "Atrasadas" (`is_late`), "Urgentes", "Asignadas a mí" (operador). Agrupar por estado, impresora prevista, propósito, solicitante y mes.

---

## 7. Lógica de negocio (métodos)

Todos los `action_*` validan el estado de origen y lanzan `UserError` en español si no corresponde.

### 7.1 `action_submit()` — Solicitante
- Requiere estado `draft` o `needs_info`.
- Valida `file_ids` o `file_url`.
- Asigna `name` de la secuencia si es `'Nuevo'`, pone `date_submitted` y `state = 'submitted'`.
- Si está vacío, `operator_id = company.print3d_default_operator_id`.
- Crea una actividad `mail.activity_data_todo` "Revisar solicitud de impresión" para `operator_id`. Si no hay operador, un mensaje al canal o seguidores del grupo operador (mínimo: `message_post`).
- Suscribe al solicitante como seguidor.

### 7.2 `action_request_info()` — Operador
- Wizard `imago.print.request.message.wizard` con modo `info`: campo `message` (Text, req.).
- `state = 'needs_info'` y `message_post(body=message, partner_ids=[requester.partner_id], subtype='mail.mt_comment')` para notificar por correo/Discuss.

### 7.3 `action_reject()` — Operador
- El mismo wizard en modo `reject`: guarda `reject_reason`, `state = 'rejected'` y notifica al solicitante.

### 7.4 `action_queue()` — Operador
- Requiere `planned_workcenter_id`.
- **Advertencia no bloqueante:** si `allowed_material_ids` de la impresora no incluye el material, se muestra en el chatter o con un `return` de notificación.
- `state = 'queued'`.

### 7.5 Iniciar intento — wizard `imago.print.job.start.wizard`

Campos del wizard:

| Campo | Default |
|---|---|
| `workcenter_id` | `planned_workcenter_id` de la solicitud |
| `lot_ids` | M2m carretes; default el `mounted_lot_id` de la impresora; dominio: carretes con stock > 0 y, si `allow_substitute = False`, solo del `filament_product_id` |
| `pieces_planned` | piezas pendientes |
| `est_grams`, `est_minutes` | de la solicitud |

Validaciones:
- Impresora no `out_of_service`.
- **Impresora libre:** si `printer_status == 'printing'`, error con el nombre de la WO en curso.
- **Gramos disponibles:** si el total disponible en los carretes elegidos es menor a `est_grams`, mostrar advertencia en el wizard (campo compute `warning_text`) pero permitir continuar.

Acciones (todo en una transacción):
1. Si `request.production_id` está vacío, crear MO (7.8.1).
2. Crear la WO `[MCH] Impresión 3D – <request.name> – intento <n>` en `workcenter_id` (7.8.2) y llamar a `button_start()` **[VERIFICAR]**.
3. Crear `imago.print.job` con `result='running'` y `date_start=now`. Crear una línea de consumo por carrete con `grams = 0` (se capturan al terminar).
4. Fijar `workcenter.mounted_lot_id` al primer carrete elegido.
5. `request.state = 'printing'` y mensaje en el chatter.

### 7.6 Terminar intento — wizard `imago.print.job.finish.wizard`

| Campo | Notas |
|---|---|
| `result` | `ok` / `partial` / `failed` / `cancelled`, req. |
| `pieces_ok` | default `pieces_planned` si `ok`, 0 si `failed` |
| `line_ids` | carrete + gramos; prellenado con los carretes del inicio. Si hay un solo carrete, default `est_grams`. Se pueden agregar carretes (runout). |
| `failure_reason`, `failure_note` | req. si `result in ('partial','failed')` |
| `labor_minutes` | opcional |

Acciones:
1. Validar gramos > 0 en al menos una línea, salvo `cancelled`.
2. Por línea: crear el consumo y el movimiento de stock (7.8.3).
3. Llamar `workorder.button_finish()` **[VERIFICAR]** y llenar `date_end`.
4. Si `labor_minutes > 0`, crear la WO `[LAB] Preparación/post-proceso – <request.name>` en `company.print3d_labor_workcenter_id`, con un registro `mrp.workcenter.productivity` de duración = `labor_minutes`, usuario operador, `loss_id` productivo y estado `done` (7.8.4).
5. Recalcular `pieces_ok`. Si `request.pieces_ok >= qty_pieces` → `state = 'post'`; si no → `state = 'queued'`.
6. Si el carrete queda en ≤ `print3d_low_spool_g`: mensaje en el chatter de la solicitud y actividad para el operador "Carrete X casi vacío".

### 7.7 Consumo de filamento en WOs de producción — wizard `imago.workorder.filament.wizard`

- Botón **[Registrar filamento]** en el formulario de `mrp.workorder`, visible si `workcenter_id.is_3d_printer` y el usuario es operador. Cubre la operación 70 del Holom.
- Campos: líneas de carrete y gramos.
- Acción: crear `imago.print.consumption` con `workorder_id` y el movimiento de stock ligado a la MO de esa WO (7.8.3).

### 7.8 Integración con MRP / Stock

#### 7.8.1 Crear MO
```python
self.env['mrp.production'].create({
    'product_id': company.print3d_product_id.id,
    'product_qty': 1,
    'product_uom_id': company.print3d_product_id.uom_id.id,
    'bom_id': False,
    'origin': '%s | %s | %s' % (request.name, request.purpose_id.name, request.reference or ''),
    'location_src_id': company.print3d_location_id.id,
    'company_id': company.id,
})
```
Luego `action_confirm()`. Guardar en `request.production_id` y agregar `print_request_id` (M2o) en `mrp.production` para la navegación inversa.
**[VERIFICAR]** que Odoo 14 permite confirmar una MO sin BOM, con producto consumible y sin componentes. Fallback: crear en datos una BOM vacía (sin componentes ni operaciones) para el producto genérico y usarla.

#### 7.8.2 Crear WO por intento
Crear `mrp.workorder` con `production_id`, `workcenter_id`, `name`, `product_uom_id`, `qty_producing`/`qty_production` según exija el modelo en 14, y `state='ready'`.
**[VERIFICAR]** los campos requeridos de `mrp.workorder` en 14 y que `button_start()` funciona en una WO creada manualmente en una MO confirmada. Fallback: agregar la WO vía `production.write({'workorder_ids': [(0, 0, vals)]})` y llamar a `production._action_confirm`/`_plan_workorders` si fuera necesario.
El nombre debe empezar con `[MCH]` (convención del Anexo B del plan) para que los reportes de HH la excluyan de mano de obra.

#### 7.8.3 Movimiento de stock del filamento
Para cada línea de consumo:
- `stock.move`: `product_id` = filamento; `product_uom` = g; `product_uom_qty` = gramos; `location_id = company.print3d_location_id`; `location_dest_id` = `product.property_stock_production` (ubicación virtual de producción); `raw_material_production_id` = MO; `origin = request.name` (o el nombre de la WO).
- `_action_confirm()`, `_action_assign()`, y `move_line` con `lot_id` y `qty_done = grams` (si `_action_assign` no reservó ese lote exacto, reemplazar las move lines).
- `_action_done()` **inmediatamente**, para que el stock del carrete baje al terminar el intento.
- **[VERIFICAR]** que un movimiento `raw` ya `done` antes de cerrar la MO no rompe `button_mark_done()` (que no se consuma dos veces ni falle por `consumption`). Fallback: crear el movimiento **sin** `raw_material_production_id` (movimiento independiente de la ubicación 3D a producción, con `origin` y un nuevo campo `print_consumption_id` en `stock.move`) y dejar la MO solo para el tiempo de máquina.
- Si el lote no tiene stock suficiente: permitir negativo **no**; lanzar `UserError` indicando los gramos disponibles y sugerir [Pesar carrete].

#### 7.8.4 Tiempo de mano de obra manual
`mrp.workcenter.productivity` con `workcenter_id`, `workorder_id`, `user_id`, `loss_id` = primera pérdida `loss_type='productive'` (igual que hace `mrp.workorder` en 14), `date_start = now - labor_minutes`, `date_end = now`. Después, WO en `done`.

#### 7.8.5 `action_deliver()` — Operador
- Requiere `state == 'post'` y ningún job en `running`.
- Cerrar MO: `qty_producing = 1`, terminar WOs pendientes y `button_mark_done()` (manejar wizards de respaldo/consumo con contexto `skip_backorder`, `skip_consumption` **[VERIFICAR]**).
- `state = 'done'`, `date_done = now` y notificar al solicitante: "Tu impresión <name> está lista para recoger".

#### 7.8.6 `action_cancel()`
- Si hay un job `running`: terminarlo como `cancelled` (pedir gramos en el wizard de terminar).
- Si hay MO: `action_cancel()` de la MO si no tiene movimientos `done`; si los tiene, cerrarla como en 7.8.5.

### 7.9 Gestión de carretes

#### 7.9.1 Wizard "Generar carretes" en recepción (`imago.spool.receive.wizard`)
- Botón en `stock.picking` de tipo recepción, visible si alguna línea es de filamento.
- Por cada `stock.move` de filamento: número de carretes (default `product_uom_qty / spool_nominal_g`, redondeado) y gramos por carrete (default `spool_nominal_g`).
- Crea lotes con la secuencia `imago.spool` y nombre `<MAT>-<COLOR3>-<seq>`, y `move_line_ids` con `lot_id`, `qty_done` y `location_dest_id = print3d_location_id`.
- Después el usuario valida la recepción con el botón estándar.
- Imprimir etiquetas con el reporte estándar de lotes de Odoo 14 (no desarrollar reporte nuevo).

#### 7.9.2 Wizard "Pesar carrete" (`imago.spool.weigh.wizard`)
- Campos: `lot_id`, `gross_weight_g` (lo que marca la báscula), `tare_g` (default `product.spool_tare_g`, editable), `net_g` compute, `current_g` (readonly, sistema), `diff_g` compute.
- Acción: ajuste de inventario del lote en `print3d_location_id` a `net_g` con el mecanismo estándar de Odoo 14 **[VERIFICAR]**: `stock.inventory` + `stock.inventory.line` → `action_start` → `action_validate`, o la edición de `stock.quant` en modo inventario. Mensaje en el chatter del lote con la diferencia.

#### 7.9.3 "Marcar como agotado"
Ajusta el lote a 0 (misma mecánica) y limpia `mounted_lot_id` de la impresora si estaba montado.

---

## 8. Datos que entrega el módulo

| Archivo | Contenido | noupdate |
|---|---|---|
| `data/ir_sequence_data.xml` | `imago.print.request` (`PRT-%(year)s-`, 4) y `imago.spool` (4) | 1 |
| `data/filament_material_data.xml` | PLA, ABS, PETG, ASA, TPU, Nylon, PC | 1 |
| `data/print_purpose_data.xml` | 4 propósitos (5.5) | 1 |
| `data/product_data.xml` | Categoría de producto "Impresión 3D" y producto "Prototipo impreso 3D" (`type='consu'`, no vendible ni comprable, en esa categoría) | 1 |
| `data/mail_activity_data.xml` | (opcional) tipo de actividad "Revisar solicitud de impresión" | 1 |

**8.1** El módulo **no** crea impresoras, filamentos ni ubicación por datos, porque dependen del almacén de cada base (`Horiz`). Eso lo hace el manual de configuración (sección 11).

---

## 9. Reportes (vistas pivot/graph estándar, sin QWeb en v0.1)

| Reporte | Modelo | Medidas | Dimensiones |
|---|---|---|---|
| Consumo de filamento | `imago.print.consumption` | `grams` | material, producto, lote, propósito (related store desde job→request), producción vs. desarrollo (`workorder_id` set vs `job_id` set), mes |
| Intentos | `imago.print.job` | count, `duration_minutes`, `grams_total`, `pieces_ok` | impresora, resultado, causa de falla, mes, operador |
| Tasa de fallos | `imago.print.job` | count | resultado × impresora (pivot) |
| Ocupación de impresoras | `mrp.workcenter.productivity` (estándar) | duración | centro de trabajo `is_3d_printer`, mes — acción de menú con dominio |

Para agrupar en `imago.print.consumption` agregar campos related `store=True`: `material_id`, `purpose_id`, `workcenter_id` y `source` (selection `development`/`production`).

---

## 10. Estructura de carpetas

```
imago_3dp/
├── __init__.py
├── __manifest__.py
├── README.md
├── CLAUDE.md
├── SPEC.md                      (este documento)
├── models/
│   ├── __init__.py
│   ├── filament_material.py
│   ├── print_purpose.py
│   ├── print_request.py
│   ├── print_job.py
│   ├── print_consumption.py
│   ├── product_template.py
│   ├── stock_production_lot.py
│   ├── stock_move.py
│   ├── mrp_workcenter.py
│   ├── mrp_production.py
│   ├── mrp_workorder.py
│   ├── res_company.py
│   └── res_config_settings.py
├── wizards/
│   ├── __init__.py
│   ├── request_message_wizard.py(+ _views.xml)
│   ├── job_start_wizard.py      (+ _views.xml)
│   ├── job_finish_wizard.py     (+ _views.xml)
│   ├── workorder_filament_wizard.py (+ _views.xml)
│   ├── spool_receive_wizard.py  (+ _views.xml)
│   └── spool_weigh_wizard.py    (+ _views.xml)
├── views/
│   ├── print_request_views.xml
│   ├── print_job_views.xml
│   ├── print_consumption_views.xml
│   ├── filament_views.xml       (material, product, lot)
│   ├── mrp_workcenter_views.xml
│   ├── mrp_workorder_views.xml
│   ├── stock_picking_views.xml
│   ├── res_config_settings_views.xml
│   └── menus.xml
├── security/
│   ├── security.xml             (categoría, grupos, record rules)
│   └── ir.model.access.csv
├── data/                        (sección 8)
├── static/description/icon.png
└── tests/
    ├── __init__.py
    ├── common.py                (setup: impresoras, filamento, carretes, usuarios por grupo)
    ├── test_request_flow.py
    ├── test_consumption.py
    ├── test_spools.py
    └── test_security.py
```

### `__manifest__.py`
```python
{
    'name': 'Imago – Impresión 3D',
    'version': '14.0.1.0.0',
    'summary': 'Solicitudes de impresión 3D, impresoras y carretes de filamento',
    'author': 'Imago Aerospace',
    'license': 'LGPL-3',
    'category': 'Manufacturing',
    'depends': ['mrp', 'stock', 'mail'],
    'data': [ ... security primero, luego data, wizards, views, menus ... ],
    'application': True,
    'installable': True,
}
```
No depender de `purchase`. La compra de filamento usa el flujo estándar ya instalado en Imago, y el wizard de 7.9.1 opera sobre `stock.picking`.

---

## 11. Configuración inicial (manual, después de instalar)

1. Crear la ubicación interna `Horiz/Stock/3DP` y seleccionarla en Ajustes → Impresión 3D.
2. Crear o convertir 4 centros de trabajo `3DP-01` … `3DP-04` con *Es impresora 3D*, modelo y materiales compatibles. Conservar el `3DP` del piloto como centro de mano de obra (`print3d_labor_workcenter_id`).
3. **Impacto en el piloto Wing LH:** en la BOM, cambiar la operación 70 `[MCH]` al centro de una impresora específica (o dejar `3DP-01` y cambiar la impresora en la WO al ejecutar).
4. Crear los productos de filamento (uno por material + color + diámetro) con *Es filamento*, la tara del carrete y las unidades g/kg.
5. Asignar el grupo *Operador de impresión 3D* al encargado y *Responsable* al jefe.
6. Elegir el operador por defecto.
7. Recibir el inventario inicial de carretes: recepción o ajuste con lotes vía "Generar carretes" y pegar etiquetas.

---

## 12. Criterios de aceptación (deben cubrirse con pruebas en `tests/`)

| ID | Criterio |
|---|---|
| A-01 | Un usuario interno sin permisos de MRP ni de inventario crea y envía una solicitud llenando solo `title`, `purpose_id`, `filament_product_id`, `qty_pieces`, `date_required` + archivo o link. |
| A-02 | Enviar sin archivo ni link lanza `UserError`. |
| A-03 | Al enviar, el operador por defecto recibe una actividad y el solicitante queda como seguidor. |
| A-04 | El operador pide aclaración: estado `needs_info`, el solicitante recibe el mensaje, edita y reenvía. |
| A-05 | Un solicitante no puede editar una solicitud ajena, ni la propia en estado `queued` o posterior. |
| A-06 | Iniciar un intento crea una MO (solo la primera vez) y una WO `[MCH]` en la impresora elegida, en estado `progress`; la impresora aparece `printing`. |
| A-07 | No se puede iniciar un intento en una impresora ocupada (incluida una WO de producción en progreso) ni en una fuera de servicio. |
| A-08 | Terminar un intento `failed` con 85 g del carrete X descuenta exactamente 85 g del lote X, la solicitud vuelve a `queued` y los gramos cuentan en `grams_failed`. |
| A-09 | Un intento con dos carretes (runout) descuenta de cada lote lo capturado. |
| A-10 | No se puede consumir más gramos de los disponibles en el lote. |
| A-11 | Al completar las piezas pasa a `post`; [Entregar] cierra la MO (`done`) y notifica al solicitante. |
| A-12 | `labor_minutes = 30` genera una WO `[LAB]` con 30 min de productividad del operador; el tiempo `[MCH]` no se mezcla con `[LAB]`. |
| A-13 | [Registrar filamento] en una WO de producción en un centro impresora descuenta el lote y aparece en el reporte de consumo como `production`. |
| A-14 | "Generar carretes" en una recepción de 3 kg con carretes de 1000 g crea 3 lotes con nombre de secuencia y 1000 g cada uno en la ubicación 3D. |
| A-15 | "Pesar carrete" con bruto 570 g y tara 250 g deja el lote en 320 g y registra la diferencia. |
| A-16 | Un lote en ≤ umbral aparece como `low` y genera aviso al operador. |
| A-17 | El reporte de consumo agrupa por material, propósito y mes; el de intentos muestra la tasa de fallos por impresora. |
| A-18 | El módulo instala y desinstala limpio en una base Odoo 14 CE con `mrp` y `stock`, y las pruebas pasan con `--test-enable`. |

---

## 13. Fuera de alcance v0.1 (backlog)

| ID | Idea |
|---|---|
| REQ-3DP-101 | Alias de correo para crear solicitudes. |
| REQ-3DP-102 | Leer metadatos del G-code/3MF (PrusaSlicer, Cura, Bambu) para prellenar gramos y minutos estimados. |
| REQ-3DP-103 | Costeo por solicitud y proyecto (cuenta analítica, tarifa por hora de impresora). |
| REQ-3DP-104 | Planeación automática con fechas en la cola (Gantt). |
| REQ-3DP-105 | Mantenimiento preventivo de impresoras por horas de uso. |
| REQ-3DP-106 | Integración con APIs de impresoras para estado en vivo. **→ Lectura de estado especificada en v0.2 (sección 16).** |
| REQ-3DP-107 | Reglas de reabastecimiento sugeridas por consumo promedio. |

---

## 14. Decisiones tomadas durante el desarrollo

(Claude Code: registrar aquí cada decisión técnica, especialmente el resultado de cada **[VERIFICAR]** y si se usó un fallback.)

Verificación hecha leyendo `addons/mrp` y `addons/stock` de la imagen oficial `odoo:14` y ejecutando cada caso en una base Odoo 14 CE aislada (Docker, PostgreSQL 12).

| # | Punto | Resultado | Fecha |
|---|---|---|---|
| 1 | 7.8.1 **[VERIFICAR]** MO sin BOM | **No se cumple.** `mrp.production.action_confirm()` lanza *"Add some materials to consume before marking this MO as to do."* si la MO no tiene `move_raw_ids`. El fallback (BOM vacía) **tampoco funciona**: una BOM sin líneas no genera componentes. Además, al crear la MO por código no se crea el movimiento de producto terminado (lo hace un onchange). **Solución:** se crea el movimiento terminado con `_get_moves_finished_values()` y un movimiento de componente *marcador* de **0 g** del filamento solicitado (`_get_move_raw_values`); con eso la MO se confirma. `button_mark_done()` cancela automáticamente el marcador (0 hecho, 0 pedido). | 13-Oct-2026 |
| 2 | 7.8.2 **[VERIFICAR]** WO manual | **Se cumple.** Campos requeridos en 14: `name`, `production_id`, `workcenter_id`, `product_uom_id`, `consumption`. `mrp.workorder.create()` re-confirma las WOs de una MO confirmada; `button_start()` crea la línea de `mrp.workcenter.productivity`, pasa la WO a `progress` y la MO a `progress`. No se necesitó fallback. `duration_expected` = minutos estimados (o 60 si no hay estimado); si el tiempo real excede el esperado, Odoo marca el excedente con la pérdida *performance* (sigue contando como ocupación). | 13-Oct-2026 |
| 3 | 7.8.3 **[VERIFICAR]** consumo `done` antes de cerrar la MO | **Se cumple para desarrollo.** `_post_inventory()` ignora los movimientos `raw` ya `done` (no hay doble consumo) y, sin BOM, `_get_consumption_issues()` no aplica. Además `_pre_button_mark_done()` exige al menos un componente con cantidad consumida: los consumos ligados a la MO lo satisfacen, así que **ligar el consumo a la MO es necesario** (el fallback impediría cerrar la MO). | 13-Oct-2026 |
| 4 | 7.7 / 7.8.3 consumo en WO de **producción** | Se usa el **fallback** (movimiento independiente 3DP → Producción, sin `raw_material_production_id`, con `origin` = MO y `stock.move.print_consumption_id`). Motivo: la MO del Holom tiene BOM; un componente extra de filamento dispararía el asistente de consumo (`warning`) o bloquearía el cierre (`strict`). Probado con BOM `strict`: la MO cierra normal. | 13-Oct-2026 |
| 5 | 7.8.3 move lines | En lugar de `_action_assign()` se crean directamente las `stock.move.line` con `lot_id` y `qty_done` (repartidas por quant si el lote está en sububicaciones de 3DP) y luego `_action_done()`. Evita que la reserva tome otro lote. Odoo permite quants negativos, por lo que la disponibilidad se valida antes (cantidad − reservado en la ubicación 3D) con `UserError` que sugiere [Pesar carrete]. | 13-Oct-2026 |
| 6 | 7.8.5 **[VERIFICAR]** `skip_backorder` / `skip_consumption` | **Se cumple.** Ambos contextos existen en 14 (`_get_quantity_produced_issues`, `_get_consumption_issues`). Se fija `qty_producing = product_qty`, se terminan WOs pendientes y `button_mark_done()` deja la MO en `done`; si devolviera un asistente se lanza `UserError`. | 13-Oct-2026 |
| 7 | 7.9.2 **[VERIFICAR]** ajuste de inventario | **Se cumple** con `stock.inventory` (`start_empty`, líneas solo del lote, `action_start` → `action_validate`). `action_validate()` exige `stock.group_stock_manager` vía `user_has_groups`, que `sudo()` **no** evita: el ajuste se ejecuta con `with_user(SUPERUSER_ID)` después de verificar el grupo Operador 3D. Se deja mensaje en el chatter del lote con la diferencia. | 13-Oct-2026 |
| 8 | 5.3 `spool_remaining_g` | El `product_qty` estándar suma **todas** las ubicaciones internas, no solo 3DP. Se implementó un compute almacenado sobre `quant_ids` filtrado por `parent_path` de la ubicación 3D (sin ubicación configurada = internas). Depende de `company_id.print3d_location_id` y `print3d_low_spool_g`, así que cambiar el umbral recalcula `spool_state`. | 13-Oct-2026 |
| 9 | 5.8 `grams > 0` | Contradicción en el SPEC: 7.5 crea líneas con 0 g al iniciar. Restricción = `grams >= 0`; para generar el movimiento se exige > 0; al terminar, las líneas que quedan en 0 g se eliminan. | 13-Oct-2026 |
| 10 | Permisos de escritura del operador | `mrp.group_mrp_user` solo **lee** `mrp.workcenter`: montar carrete, desmontar y "Fuera de servicio" escriben con `sudo()` acotado tras verificar el grupo Operador 3D. El operador no puede borrar consumos: las líneas de 0 g sin movimiento se borran con `sudo()`. | 13-Oct-2026 |
| 11 | Regla del solicitante (3) | La regla de escritura (propias en `draft`/`needs_info`) impide efectos secundarios después de `action_submit` (seguidor, actividad): se hacen con `sudo()`. El SPEC permite al solicitante cancelar en `submitted`, que la regla bloquea: `action_cancel` valida dueño + estado y escribe con `sudo()`. Además `write`/`create` rechazan que un no-operador fije campos del operador (impresora, estimados, operador, folio, solicitante ajeno). | 13-Oct-2026 |
| 12 | 6.3 arrastrar en kanban | Doble protección: `records_draggable="0"` y `write()` rechaza cambios de `state` que no vengan de los métodos `action_*`. Las transiciones se escriben con `sudo()` (`_set_state`) tras validar estado, grupo y dueño, y `write` solo acepta `state` con `env.su` (una bandera de contexto se podría falsificar por RPC; corregido tras revisión). | 13-Oct-2026 |
| 13 | 5.4 `printer_status` | Es compute no almacenado y Odoo lo cachea durante la transacción; la validación "impresora ocupada" hace una búsqueda fresca (`_printer_running_workorder`) y la caché se invalida al iniciar/terminar intentos. | 13-Oct-2026 |
| 14 | 6.2 grupo plegable | Odoo 14 no tiene grupos plegables en formularios: "Parámetros (opcional)" es una pestaña del notebook. Los campos de la pestaña "Impresión" son de solo lectura para quien no es operador (campo técnico `user_is_operator`). | 13-Oct-2026 |
| 15 | 7.4 advertencia de material | Se publica en el chatter (no bloquea). El asistente de inicio también muestra la advertencia en `warning_text`. | 13-Oct-2026 |
| 16 | Actividades | Tipos propios "Revisar solicitud de impresión" (se marca hecha al poner en cola/aclarar/rechazar, se elimina al cancelar) y "Carrete casi vacío" (actividad en el lote, sin duplicar). Sin operador por defecto, `action_submit` publica un mensaje a los usuarios del grupo Operador. | 13-Oct-2026 |
| 17 | 6.4 Montar carrete | Se agregó el asistente `imago.spool.mount.wizard` (no estaba en la lista de carpetas). Un carrete solo puede estar montado en una impresora; montarlo en otra lo desmonta de la anterior. | 13-Oct-2026 |
| 18 | 9 Reportes | Menú Reportes con 4 entradas (Intentos, Tasa de fallos, Consumo de filamento, Ocupación de impresoras). Campo almacenado `failure_count` (1 si falló) para obtener la tasa con sumas. | 13-Oct-2026 |
| 19 | 7.9.1 Generar carretes | La cantidad del movimiento se convierte a g (las compras llegan en kg). Se crean lotes y `move_line_ids` con `qty_done` hacia la ubicación 3D; las líneas de reserva sin lote las limpia Odoo al validar. Si la línea ya tiene lotes asignados, se rechaza. Archivo `models/stock_picking.py` agregado (`has_filament_moves`). | 13-Oct-2026 |
| 20 | Reabrir | Si la MO de la solicitud ya está `done`/`cancel`, se desliga y el siguiente intento crea una MO nueva; el botón inteligente lista todas las MOs (`mrp.production.print_request_id`). | 13-Oct-2026 |
| 21 | 5.2 onchange UdM | El onchange estándar `_onchange_uom_id` copia la UdM de stock en la de compra; se sobrescribe para filamentos (g / kg). | 13-Oct-2026 |
| 22 | Datos | Código de lote de Nylon = `NYL`. Secuencias globales (sin compañía). El producto genérico se asigna a la compañía principal en datos. | 13-Oct-2026 |
| 23 | 6.1 Ajustes | `res.config.settings` solo lo guarda un administrador (`base.group_system`), por eso el menú Ajustes se muestra solo a ese grupo. | 13-Oct-2026 |
| 24 | 12 A-18 | Verificado: base nueva con datos demo, `-i imago_3dp --test-enable` → 66/66 pruebas OK; desinstalación sin tablas, columnas, modelos, grupos ni menús residuales; reinstalación OK. | 13-Oct-2026 |
| 25 | Revisión de código | Endurecimiento: UdM de stock del filamento = gramo; rechazar desde `queued` cancela/cierra la MO; [Registrar filamento] no se permite en WOs de una solicitud (evita doble consumo); consumos contabilizados inmutables y no se borran solicitudes/intentos con consumo; ajustes solo sobre lotes carrete; el consumo conserva la MO de su intento tras reabrir; reabrir una solicitud nunca enviada vuelve a borrador; intento OK exige piezas > 0; el centro [LAB] se valida antes de mover stock; bloqueo `FOR UPDATE NOWAIT` de la impresora al iniciar; textos de usuario escapados en HTML del chatter/actividades. | 13-Oct-2026 |
| 26 | 16.11 **[VERIFICAR]** V-01 OWL / `jsLibs` | **Se cumple.** En 14, `web.Widget.willStart` carga `jsLibs`/`cssLibs` (`_loadLibs`), y `AbstractAction` hereda de `Widget`; `ComponentWrapper`/`WidgetAdapterMixin` existen en `web.OwlCompatibility`. Aun así se usó el patrón clásico `AbstractAction` + plantillas QWeb (el de `hr_attendance`), sin el puente OWL ↔ legacy. ECharts se carga solo en el dashboard vía `jsLibs`. | 21-Oct-2026 |
| 27 | 16.10 Datos del dashboard (F1) | Modelo abstracto `imago.print.dashboard` con `get_dashboard_data(include_charts=True)`: exige el grupo Operador (`AccessError` si no) y lee todo con los permisos del usuario. Las gráficas van en `print_dashboard_charts.py` (mismo modelo vía `_inherit`). La cola incluye `post` (post-proceso). En F1, sin telemetría, el avance es **estimado por tiempo** (transcurrido / `est_minutes`, tope 99 %) y la acción "¿ya terminó?" (intento que superó su estimado) sustituye provisionalmente a la alerta `finished_open` de 16.7. | 21-Oct-2026 |
| 28 | 16.10 Diseño (Impeccable) | Diseño con `/impeccable`: PRODUCT.md y brief de superficie en `.impeccable/surfaces/`. Estructura elegida por el usuario: **franja de acciones sobre las estaciones**. Respecto de 16.10: los indicadores son una línea de resumen (no mosaicos); "Alertas abiertas" se convirtió en la **franja de pendientes** (cada tarjeta con su botón: Iniciar, Terminar intento, Montar carrete, Abrir), ordenada por severidad; cada estación muestra el sello de su último intento (antes 3; ver decisión 48); se agregó el inventario de carretes (resumen por filamento + montados/casi vacíos) y las 4 gráficas van en pestañas. **Modo pantalla** (pedido por el usuario): oculta menú, panel de control y botones, escala la fuente raíz con la pantalla (`clamp(14px, 1.05vw, 32px)`, ≈20 px a 1920) y, desde 1200 px, acomoda todo en una sola pantalla 16:9: arriba la siguiente acción con 3 pendientes, la cola y los carretes; abajo las estaciones a todo el ancho. Lo que no cabe se cuenta con una línea visible ("+N pendientes más", "+N más en la cola", "+N filas más de carretes"). Debajo de 1200 px el modo pantalla se desplaza y lo muestra todo. Se recuerda por navegador (`localStorage`). Los pendientes se ordenan por severidad y, dentro de ella, por tipo (atrasada, filamento, ¿ya terminó?, carrete, por revisar, impresora libre, entregar). Revisión de diseño independiente (finish reviewer) aplicada. | 21-Oct-2026 |
| 29 | 16.10 Botones del dashboard | Los botones llaman a los métodos `action_open_*` por `/web/dataset/call_button` (como los botones de formulario): con `_rpc({model, method})` Odoo devuelve la acción sin `views` y el cliente falla en `_loadViews`. | 21-Oct-2026 |
| 30 | Entorno | El backend de Odoo 14 CE no declara `meta viewport`: en un teléfono la página se dibuja a 980 px, así que el dashboard se diseñó para escritorio y pantalla mural. En modo producción Odoo cachea el paquete de assets por proceso: tras cambiar archivos estáticos hay que reiniciar Odoo (o usar `?debug=assets`). | 21-Oct-2026 |
| 31 | Dependencias | Apache ECharts 5.5.1 (Apache-2.0) en `static/lib/echarts/` con `LICENSE` y `NOTICE`, tomado del tarball de npm con integridad sha512 verificada contra el registro. | 21-Oct-2026 |
| 32 | 16.13 A-30 | Verificado: base con 14.0.1.0.0 (rama `main`) actualizada a 14.0.2.0.0 con `-u imago_3dp` → 78/78 pruebas OK. La versión 14.0.2.0.0 se fijó desde F1. | 21-Oct-2026 |
| 33 | 17.7 **[VERIFICAR]** V-08 MO sin WO | **Se cumple.** La MO de una solicitud no líder (solo movimientos `raw` contabilizados, sin WO) se cierra con `button_mark_done()` en Odoo 14; no hizo falta el fallback de WO de 0 min. Prueba `test_v08_non_lead_request_production_can_be_closed`. | 21-Oct-2026 |
| 34 | 17.7 **[VERIFICAR]** V-09 / V-10 | **Se cumplen.** Entregar la líder o la no líder primero no afecta a la otra (cada MO tiene sus consumos). El reparto redondea con la precisión de la UdM del filamento y el último intento con parte absorbe la diferencia: 100 g en tres partes iguales suman 100 g exactos. | 21-Oct-2026 |
| 35 | 17 Implementación | `imago.print.batch` (`models/print_batch.py`) con `_start_combined` / `_finish_combined` (privados, sin banderas de contexto). `request._start_job` se separó en `_create_machine_workorder`, `_create_job` y `_after_job_started` para reutilizarlos; el intento individual de v0.1 no cambia. `job._finish` rechaza los intentos de una combinada salvo con el parámetro privado `from_batch` (no llamable por RPC). El asistente de inicio agrega `extra_request_ids` ("Imprimir junto con") y un resumen de texto del reparto en lugar de una tabla. Los carretes permitidos son la intersección de los de todas las solicitudes. | 21-Oct-2026 |
| 36 | 17 Asistente de terminar | `imago.print.batch.finish.wizard` con carretes (total de la placa) y una línea por solicitud (resultado, piezas, causa, parte %). Los porcentajes se muestran con 2 decimales: si la suma está a ≤ 0.05 puntos de 100 % (p. ej. 3 × 33.33) se normaliza; si no, se rechaza. | 21-Oct-2026 |
| 37 | 17 Indicadores | `counts_for_printer` filtra los indicadores de impresora: acción "Tasa de fallos" (dominio), KPI de fallos 7 d, causas de falla, resultados por impresora y sellos de la estación en el dashboard. El aviso de filamento insuficiente compara los gramos estimados de toda la placa. El Solicitante puede leer todas las combinadas (igual que las solicitudes). | 21-Oct-2026 |
| 38 | 17.8 A-43 | Verificado: base 14.0.2.0.0 con 7 intentos actualizada a 14.0.2.1.0 → todos con `share = 1`, `counts_for_printer = True` y `allocated_minutes = duration_minutes`; 97/97 pruebas OK (105/105 tras la revisión, decisión 39). Flujo completo probado en el navegador (iniciar desde la cola del dashboard, tarjeta de estación, terminar: 60 g + 80 g en la MO de cada solicitud). | 21-Oct-2026 |
| 39 | 17 Revisión de código | Correcciones de la revisión independiente: (1) **HIGH** un operador podía saltarse la combinada por RPC (`job.write({'batch_id': False})`, `batch.write({'state': 'done'})`): campos protegidos en `write`/`create` y ACL del operador sobre la combinada de solo lectura; (2) el reparto usa **mayor resto** (nunca negativo, suma exacta; antes 7 min entre 10 daba −2 al último); (3) si una parte redondea a 0 g se rechaza **antes** de cerrar cualquier intento, nombrando la solicitud; (4) los gramos estimados que el operador edita en el asistente sí se usan para el reparto y el intento líder; (5) los indicadores de impresora usan el peor resultado de la placa (D-26). Pruebas reforzadas (duraciones reales en A-37, minutos exactos en A-39, rutas y accesos) y 9 nuevas: escritura directa, 10 solicitudes, parte que redondea a 0, placa cancelada sin gramos, parte 0 cancelada, solicitud en post-proceso, peor resultado con dos carretes, gramos del asistente, entrega de la líder primero. 105/105 OK. | 21-Oct-2026 |
| 40 | 16.11 **[VERIFICAR]** V-02 CR-M4 | **Se cumple en parte** (impresión real en la .248 lanzada desde USB, captura cada 15 s): precalentando `state 0` (boquilla 260 °C); imprimiendo `state 1` + `mcu_is_print 1` y el archivo en `print` (`BASESE~1.GCO`); `printProgress` 0–1 y capas 0 (sin avance real en impresiones desde USB); `printJobTime` en segundos; `printLeftTime` inservible (saltó de 13 h a 30 h). Al detenerse la impresión quedó `state 4` con `err 1` (`error 0`): el operador confirmó que fue una **cancelación**, así que `state 4` = en reposo y ese `err` se ignora (decisión 48). No se observó `state 2` (terminada) en vivo. | 21-Oct-2026 |
| 41 | 16.11 **[VERIFICAR]** V-03 / V-04 Adventurer 4 | **Se cumplen.** Imprimiendo `BUILDING_FROM_SD`, archivo, temperaturas con objetivo (`T0:240/240 B:105/105`), `M27` = **porcentaje** y capa (`Layer: 48/94`). Al terminar: 100 %, 94/94 y objetivos en 0 durante ~30 s, luego `READY` (nunca `BUILDING_COMPLETED`). Las consultas responden **sin** `~M601` y no interrumpieron la impresión ni a FlashPrint; se quitó `M601/M602` del driver. La cama marcó 5 °C solo en frío; imprimiendo 105 °C reales (V-04 resuelto). 2 de 94 lecturas tuvieron tiempo de espera. | 21-Oct-2026 |
| 42 | 16.11 **[VERIFICAR]** V-05 API key | **Se cumple** (probado en local contra Odoo 14): `authenticate` + `execute_kw` con la API key de un usuario **portal** funciona y ese usuario no puede leer solicitudes. Odoo 14 solo deja crear claves desde la interfaz a usuarios internos, así que el puente tiene *Generar API key* (servidor, `res.users.apikeys._generate` como el usuario técnico; solo `base.group_erp_manager`) y *Revocar API keys*. Falta confirmar detrás del proxy de `erp.imago.aero`. | 21-Oct-2026 |
| 43 | 16 F2 implementación | Odoo: `mrp_workcenter_link.py` (driver, IP privada literal, puerto, cámara en la misma IP, puente; cambiar cualquiera sube `config_version`), `printer_bridge.py` (API, límite de 3 s entre envíos, `clock_skew` si `sent_at` viene > 5 min adelantado), `printer_telemetry.py` (validación pura del contrato 16.6; claves desconocidas rechazan esa impresora sin guardar su valor), `printer_status.py` (último estado; `progress_known` distingue "sin avance" de 0 %; inicio/fin detectados), `printer_event.py` (eventos inmutables). Estado y eventos solo los escribe el sistema (superusuario). Puente en `bridge/` (169 pruebas pytest, solo biblioteca estándar). Prueba de punta a punta en la Mac: el puente real leyó las 3 impresoras y la Odoo local guardó estado, foto de la Adventurer y la alerta de error de la CR-M4. | 21-Oct-2026 |
| 44 | 16.7 F3 alertas | Cuatro alertas, cada una abierta una vez y cerrada sola al desaparecer la condición (evento con `alert_open` + actividad "Alerta de impresora 3D"): `unregistered` (imprime sin WO en progreso), `error`, `offline` (sin datos > `print3d_offline_alert_min` con WO en progreso) y `finished_open` (la impresora terminó —fin detectado después del inicio del intento— y sigue en reposo > `print3d_finished_alert_min`). El precalentamiento de la CR-M4 (reposo) no dispara `finished_open`. Cron cada 5 min. En el dashboard las alertas abiertas entran a la franja de pendientes, y con lectura en vivo no se usa la heurística "¿ya terminó?". | 21-Oct-2026 |
| 45 | Tiempo real de impresión | Petición del usuario: *Terminar intento* (individual y combinada) tiene **Minutos reales de impresión** como dato principal (el operador suele saber cuánto duró, no a qué hora terminó), prellenados con lo que reportó la impresora (`job_time_min` o la ventana inicio/fin detectada, si la impresión empezó después del intento) o, sin lectura, con el reloj. **Fin real de impresión** se calcula con los minutos y también es editable (al cambiarlo se recalculan los minutos). No se aceptan minutos que superen el tiempo transcurrido desde el inicio. Al terminar, la fecha de fin del intento y el último registro de productividad de la WO `[MCH]` se ajustan, así que la ocupación y los minutos por solicitud usan el tiempo real. | 21-Oct-2026 |
| 46 | 16.11 V-06 / V-07 | V-06 (crecimiento del filestore por fotos) **sin verificar** todavía: se reemplaza un adjunto por foto; revisar en `manuf_test` tras unos días. V-07: no se usa ningún otro endpoint de la Creality Box (solo `function=get` de `Info`). | 21-Oct-2026 |
| 47 | Revisión de seguridad F2 | Sin hallazgos críticos ni altos. Corregido: valores `NaN`/infinito y enteros absurdos se rechazan (rompían el JSON del dashboard), un valor hostil nunca aborta el lote, tope de impresoras por envío (2 × las del puente) y sin duplicados, la foto se mide antes de decodificarla y se verifica con Pillow, bloqueo de fila contra envíos simultáneos, formato estricto de `sent_at`, caracteres de control y bidireccionales eliminados del texto, el puente rechaza usuarios internos aunque los promuevan después, enfriamiento de 10 min antes de reabrir la misma alerta, purga de eventos de más de un año, actividades a nombre de OdooBot y la cámara solo en el endpoint del driver. En el puente: plazo total por lectura (no solo por *socket*), números y JSON hostiles convertidos en lectura fallida, texto saneado, imagen Docker fijada por *digest* y ejemplo `docker run` endurecido (215 pruebas). | 21-Oct-2026 |
| 48 | Ajustes del usuario | (1) CR-M4: `state 4` + `err 1` es una impresión **cancelada** en la impresora (confirmado por el operador): el driver la reporta en reposo, sin error; si el intento sigue abierto en Odoo aplica la alerta "terminó con intento abierto". (2) Cada estación del dashboard muestra **solo el sello del último intento** (antes 3), para tarjetas más limpias. | 21-Oct-2026 |
| 49 | Puente 0.2.1 (falla en producción) | En el servidor, las dos CR-M4 se marcaban "fuera de línea" a ratos y la cámara de la Adventurer nunca daba foto, aunque `curl` respondía en 0.3 s. Causa: el envoltorio con plazo total de `lanhttp.py` cerraba el *socket* real cuando http.client terminaba de leer los encabezados de una respuesta "Connection: close"; si el cuerpo llegaba después, la lectura fallaba con `OSError 9` (≈60 % de las lecturas de la Creality Box, 100 % de la cámara). Corregido con conteo de lectores, igual que `socket.makefile`; dos pruebas de regresión que fallan con el código anterior (218 pruebas) y 30/30 lecturas reales correctas más foto válida. | 21-Oct-2026 |

---

## 15. Entorno de desarrollo y pruebas sugerido

- Odoo 14 CE con PostgreSQL 12, en Docker (`odoo:14` + `postgres:12`) o *source checkout* rama `14.0`.
- Ejecutar pruebas:
  ```bash
  odoo -d test_imago_3dp -i imago_3dp --test-enable --stop-after-init --log-level=test
  ```
- **No** ejecutar sobre la base productiva. La validación funcional se hará después en `manuf_test` (`https://erp.imago.aero`), donde se generará el manual y la prueba piloto.
- La instalación real de Imago contiene módulos propios (`purchase_order_approved`, `import.tracking`). El módulo no debe depender de ellos ni modificarlos.

---

## 16. v0.2 — Dashboard del operador, puente local y drivers de impresoras

Versión objetivo `14.0.2.0.0`. Todo lo de v0.1 sigue vigente; en particular, **los "Puntos clave del diseño" de `CLAUDE.md` no cambian**. Las reglas de la sección 0 aplican igual a esta sección.

### 16.1 Objetivo

1. El operador abre Odoo y su **página inicial** es un dashboard gráfico con lo que necesita en el turno: el estado real de cada impresora, la cola, las alertas y los indicadores.
2. El estado de las impresoras (avance, temperaturas, capas, tiempo restante, cámara) se lee **en la red local** de la planta, a partir de la IP que se configura en Odoo para cada impresora.
3. Odoo **cruza** lo que reporta la impresora con lo registrado (intento abierto, WO `[MCH]` en progreso) y avisa cuando no coinciden.

**No** forma parte de v0.2: mandar trabajos, pausar, detener ni cambiar parámetros de las impresoras (control remoto). Todo es **solo lectura** (ver D-15).

### 16.2 Hallazgos del reconocimiento de red (21-Oct-2026)

Se hicieron pruebas de solo lectura desde una Mac en la red de la planta (`192.168.0.0/24`): escaneo de puertos, peticiones HTTP GET y consultas G-code de estado. No se usó ninguna contraseña ni se envió ninguna orden de control.

| | CR-M4 #1 | CR-M4 #2 | Adventurer 4 |
|---|---|---|---|
| IP (al 21-Oct-2026) | `192.168.0.248` | `192.168.0.249` | `192.168.0.61` |
| Conectividad | Módulo WiFi Creality (Creality Box), `boxVersion` V3.04b06, modo WISP | ídem | Ethernet/WiFi propia |
| Firmware | Marlin 2.0.9.1 (12-Ene-2023) | ídem | Flashforge v2.3.3 |
| Puertos abiertos | 21 FTP (`220 Creality_FTP`), 23 telnet (`11NRouter login`), 80 (HTTP Basic auth, lighttpd 1.4.20), **81 (API de estado)**, 8888 (UPnP) | ídem | **8080 (cámara)**, **8899 (control/estado)** |
| Lectura de estado | `GET http://IP:81/protocal.csp?fname=Info&opt=main&function=get` → JSON, **sin autenticación**, sin encabezados CORS | ídem | TCP 8899, comandos de texto `~M601 S1`, `~M115`, `~M119`, `~M105`, `~M27`, `~M602` |
| Cámara | No (`video: 0`) | No | MJPEG `http://IP:8080/?action=stream` (MJPG-Streamer 0.2, 640×480, ~5 fps, `Access-Control-Allow-Origin: *`). `?action=snapshot` **no responde**. |
| Observaciones | `tfCard: 1` | `tfCard: 0` (sin tarjeta SD) | `M601 S1` contesta `Control failed` (FlashPrint tiene el control), pero **las consultas de estado responden igual**. En reposo: `M105` → `T0:21/0 B:5/0` (la lectura de cama de 5 °C es dudosa, ver V-04). |

**Campos útiles del JSON de la Creality Box:** `connect`, `state`, `pause`, `stop`, `err`, `error`, `printProgress`, `dProgress`, `nozzleTemp`, `bedTemp`, `layer`, `TotalLayer`, `printLeftTime`, `printJobTime`, `printStartTime`, `curPosition`, `tfCard`, `model`, `modelVersion`, `boxVersion`.

**Respuestas de la Adventurer 4 (en reposo):**
```
M115 → Machine Type: Flashforge Adventurer 4 / Firmware: v2.3.3 / X: 220 Y: 200 Z: 250 / Tool Count: 1
M119 → MachineStatus: READY / MoveMode: READY / Status: S:0 L:0 J:0 F:0 / LED: 0 / CurrentFile:
M105 → T0:21/0 B:5/0
M27  → SD printing byte 0/100 / Layer: 0/0
```

**Hallazgos de seguridad:**
- El JSON de la Creality Box incluye **la contraseña del WiFi en texto plano** (`wifipasswd`), además de `ssid`, `apclissid`, `apclimac` y `ownerId`, para cualquier equipo de la red.
- Según la integración comunitaria [pcartwright81/Creality-Wifi-Box-Control](https://github.com/pcartwright81/Creality-Wifi-Box-Control), la misma API acepta **pausar y detener** impresiones (`fname=net&opt=iot_conf&function=set&pause=1|stop=1`) sin autenticación. No se probó.
- Recomendación para TI: poner las impresoras en una VLAN o SSID aislado al que solo tenga acceso el equipo del puente (y las PCs con Creality Print/FlashPrint), y fijar sus IPs con reservas DHCP.

**Hosting de Odoo:** `erp.imago.aero` resuelve a `35.89.115.62` (AWS). El servidor **no ve** la red de la planta.

**Consecuencias para el diseño:**
- El navegador no puede leer las impresoras directamente. La Adventurer 4 usa TCP crudo; la Creality Box no envía CORS; y desde una página HTTPS el navegador bloquea las peticiones a `http://192.168.x.x` (contenido mixto).
- Odoo tampoco puede consultarlas, porque está en AWS.
- Por lo tanto se necesita un **puente local**: un programa en la red de la planta que lee las impresoras y **envía** el estado a Odoo. Odoo nunca inicia conexiones hacia la planta y no hay que abrir puertos de entrada.

### 16.3 Decisiones de diseño v0.2

| ID | Decisión |
|---|---|
| D-09 | **Dashboard = acción cliente de Odoo** (`ir.actions.client`, tag `imago_3dp_dashboard`) dentro del módulo, no una aplicación aparte. Se asigna como *Acción inicial* (`res.users.action_id`) de los operadores. |
| D-10 | Gráficas con **Apache ECharts 5.5.1** (licencia Apache-2.0), copiado en `static/lib/echarts/` con su `LICENSE`, **sin** paso de compilación npm. Se carga de forma diferida solo en el dashboard (`jsLibs` de la acción), no en todo el backend. |
| D-11 | **Puente local** (`bridge/`, Python 3.11, servicio independiente de Odoo) que corre en un equipo siempre encendido de la red de la planta (mini-PC, PC del cuarto de impresión o Raspberry; recomendado como contenedor Docker). **No** va conectado a las impresoras: llega a ellas por IP. |
| D-12 | El puente **envía** (push) el estado a Odoo por HTTPS usando el **JSON-RPC estándar** de Odoo (`/jsonrpc`, `execute_kw`) con un **usuario técnico y su API key** de Odoo 14. No se crea un endpoint con autenticación propia: la base se indica de forma explícita, la llave es revocable y se reutiliza el control de acceso de Odoo. |
| D-13 | La **configuración de cada impresora** (driver, IP, puerto, cámara) vive en Odoo, en `mrp.workcenter`. El puente la descarga de Odoo y no tiene una lista local de impresoras. |
| D-14 | El estado en vivo se guarda en un **modelo propio** (`imago.printer.status`, una fila por impresora) y no en `mrp.workcenter`, para no escribir el centro de trabajo cada 10 s (bloqueos con los operadores, `write_date`, caché). Solo se guarda **el último estado** y, aparte, los **cambios de estado** como eventos (`imago.printer.event`); no se guarda cada muestra. |
| D-15 | **Solo lectura.** Los drivers solo pueden emitir una lista blanca de lecturas: Creality, solo `function=get`; Flashforge, solo `~M601 S1`, `~M602`, `~M115`, `~M119`, `~M105`, `~M27`. Odoo no tiene ningún método que mande órdenes a una impresora. |
| D-16 | **La telemetría nunca cambia datos de negocio:** no cambia el estado de solicitudes ni el resultado de intentos, y no mueve stock. Solo genera eventos, alertas y actividades. El operador sigue iniciando y terminando intentos con los asistentes de v0.1 (gramos reales por carrete). |
| D-17 | **Lista blanca de campos:** el puente convierte cada respuesta a un esquema común (16.6) y **descarta todo lo demás**, en particular `wifipasswd`, `ssid`, `apclissid`, `apclimac`, `ownerId`, `DIDString`, `APILicense` e `InitString`. Odoo, además, rechaza las claves desconocidas. |
| D-18 | **Cámara en v0.2 = fotos**, no video en vivo. El puente extrae un cuadro JPEG del flujo MJPEG y lo envía junto con el estado. El video en vivo queda en el backlog (REQ-3DP-108) porque exige servir HTTPS con certificado válido desde la red local. |
| D-19 | Las IPs de impresora se aceptan solo como **IPv4 privada** literal (`ipaddress.ip_address(...).is_private`, sin loopback ni link-local), sin nombres DNS. El puente vuelve a validarlo antes de conectarse. |
| D-20 | El puente vive en este mismo repositorio, en `bridge/`, para versionar juntos el contrato de datos (16.6) y los dos extremos. Odoo no lo importa (no está en `__init__.py`). |

### 16.4 Arquitectura

```
 RED DE LA PLANTA (192.168.0.0/24)                         │  AWS
                                                           │
 ┌───────────────┐  HTTP GET :81 (JSON)                    │  ┌───────────────────────────────┐
 │ CR-M4 #1 / #2 │◀───────────┐                            │  │ Odoo 14 (erp.imago.aero)      │
 └───────────────┘            │   ┌───────────────────┐    │  │                               │
                              ├───│ imago-3dp-bridge  │────┼─▶│ /jsonrpc execute_kw           │
 ┌───────────────┐  TCP :8899 │   │ (Docker, Python)  │    │  │  imago.printer.bridge         │
 │ Adventurer 4  │◀───────────┤   │ - drivers         │    │  │   .get_config()              │
 └───────────────┘  MJPEG     │   │ - normaliza       │    │  │   .push_telemetry(payload)    │
        :8080 ◀───────────────┘   │ - fotos           │    │  │        │                      │
                                  └───────────────────┘    │  │        ▼                      │
                                                           │  │ imago.printer.status / event  │
 ┌──────────────────────┐   HTTPS (sesión del operador)    │  │        │                      │
 │ Navegador operador   │◀─────────────────────────────────┼──│ Acción cliente "Dashboard"    │
 │ (PC o pantalla mural)│   orm: get_dashboard_data()      │  │  (OWL/ECharts)                │
 └──────────────────────┘                                  │  └───────────────────────────────┘
```

La flecha puente → Odoo es **HTTPS saliente** desde la planta; no hay conexiones de entrada.

Ciclo normal:
1. El puente pide su configuración a Odoo al arrancar, cada 5 min, o cuando cambia `config_version`.
2. Lee cada impresora cada `poll_seconds`, por defecto 10 s.
3. Envía un lote con todas las impresoras en una sola llamada.
4. Odoo valida el lote, actualiza `imago.printer.status`, detecta los cambios de estado y crea eventos y alertas.
5. El dashboard consulta a Odoo cada 10 s; las agregaciones pesadas se recalculan cada 60 s.

### 16.5 Modelo de datos

#### 16.5.1 Extensión de `mrp.workcenter` (configuración de conexión)

| Campo | Tipo | Notas |
|---|---|---|
| `printer_driver` | Selection | `none` (Sin conexión, default) / `creality_box` (Creality WiFi Box) / `flashforge_tcp` (Flashforge TCP 8899) |
| `printer_host` | Char | IPv4 privada (D-19). Requerido si `printer_driver != 'none'`. |
| `printer_port` | Integer | Onchange del driver: `creality_box` → 81, `flashforge_tcp` → 8899. Rango 1–65535. |
| `camera_url` | Char | Opcional. Esquema `http`, y el host debe ser **igual** a `printer_host`. Onchange para `flashforge_tcp`: `http://<host>:8080/?action=stream`. |
| `bridge_id` | M2o `imago.printer.bridge` | Puente que lee esta impresora. Requerido si hay driver. |
| `live_status_id` | M2o `imago.printer.status` compute | Fila de estado de la impresora. |
| `live_state` | Selection compute (no almacenado) | Estado en vivo **con frescura**: `no_link` si no hay driver; `stale` (*Sin datos*) si `received_at` tiene más de `print3d_telemetry_stale_s` segundos; si no, `status.state`. |

Constraint: un mismo `printer_host` + `printer_port` no puede repetirse entre centros de trabajo activos.

Edición: estos campos se editan en el formulario del centro de trabajo, en una pestaña "Conexión", por quien ya puede editar centros de trabajo (Manufactura/Administrador). Cualquier cambio incrementa `bridge_id.config_version`.

#### 16.5.2 `imago.printer.bridge` (puente)

| Campo | Tipo | Notas |
|---|---|---|
| `name` | Char, req. | p. ej. "Puente cuarto de impresión" |
| `user_id` | M2o res.users, req. | Usuario técnico con el grupo `group_print_bridge` (16.8). Único. |
| `active` | Boolean | |
| `poll_seconds` | Integer | default 10, mínimo 5 |
| `snapshot_seconds` | Integer | default 30 mientras imprime; 300 en reposo |
| `config_version` | Integer | Se incrementa cuando cambia la configuración de alguna impresora del puente. |
| `last_seen` | Datetime | Último push recibido |
| `bridge_version` | Char | Lo reporta el puente |
| `workcenter_ids` | O2m `mrp.workcenter` (`bridge_id`) | |
| `is_online` | Boolean compute | `last_seen` dentro de 3 × `poll_seconds` |

Métodos (los llama el puente vía `execute_kw`):
- `get_config()` (`@api.model`): identifica el puente por `env.user`. Si el usuario no es el `user_id` de un puente activo, lanza `AccessError`. Devuelve `{config_version, poll_seconds, snapshot_seconds, printers: [{workcenter_id, code, driver, host, port, camera_url}]}`.
- `push_telemetry(payload)` (`@api.model`): valida el lote (16.6), actualiza los estados con `sudo()` acotado tras verificar puente y grupo, crea eventos y alertas (16.7) y devuelve `{ok, config_version, errors: [{workcenter_id, error}]}`. Una impresora con datos inválidos **no** invalida el resto del lote. Pushes del mismo puente con menos de 3 s de separación se ignoran (`ok: false, error: 'rate_limited'`).

#### 16.5.3 `imago.printer.status` (último estado; una fila por impresora)

| Campo | Tipo | Notas |
|---|---|---|
| `workcenter_id` | M2o mrp.workcenter | req., **único**, `ondelete='cascade'` |
| `bridge_id` | M2o | |
| `reachable` | Boolean | el puente pudo conectarse |
| `state` | Selection | `offline`, `idle`, `printing`, `paused`, `finished`, `error`, `unknown` |
| `progress` | Float | 0–100 |
| `nozzle_temp`, `nozzle_target`, `bed_temp`, `bed_target` | Float | °C; target vacío si el driver no lo da |
| `layer`, `layer_total` | Integer | |
| `time_left_min`, `job_time_min` | Integer | vacío si el driver no lo da |
| `file_name` | Char | máx. 128 caracteres |
| `error_text` | Char | máx. 256 caracteres |
| `reported_at` | Datetime | marca de tiempo del puente (UTC) |
| `received_at` | Datetime | marca de tiempo de Odoo al recibir |
| `snapshot` | Binary (`attachment=True`) | último JPEG, máx. 512 KB |
| `snapshot_at` | Datetime | |

#### 16.5.4 `imago.printer.event` (cambios de estado)

| Campo | Tipo | Notas |
|---|---|---|
| `workcenter_id` | M2o | req. |
| `date` | Datetime | |
| `event_type` | Selection | `started`, `paused`, `resumed`, `finished`, `error`, `offline`, `online`, `unregistered` (imprime sin WO en progreso), `finished_open` (terminó con intento abierto) |
| `state_from`, `state_to` | Selection | |
| `workorder_id` | M2o mrp.workorder | WO en progreso en ese momento, si existe |
| `job_id` | M2o imago.print.job | intento `running` en ese momento, si existe |
| `details` | Char | |

Los eventos son inmutables (`write`/`unlink` bloqueados salvo `env.su`). Sirven para el historial de la impresora, las alertas y los indicadores de disponibilidad.

#### 16.5.5 Ajustes (en `res.company` / `res.config.settings`)

| Campo | Default | Uso |
|---|---|---|
| `print3d_telemetry_stale_s` | 60 | A partir de cuántos segundos sin datos se muestra *Sin datos* |
| `print3d_offline_alert_min` | 10 | Minutos sin comunicación, con WO en progreso, antes de alertar |
| `print3d_finished_alert_min` | 5 | Minutos en `finished`/`idle` con intento abierto antes de crear la actividad "Cerrar intento" |

### 16.6 Contrato de datos puente → Odoo (`push_telemetry`)

```json
{
  "bridge_version": "0.2.0",
  "sent_at": "2026-10-21T16:00:00Z",
  "printers": [
    {
      "workcenter_id": 12,
      "reachable": true,
      "state": "printing",
      "progress": 42.0,
      "nozzle_temp": 210.0, "nozzle_target": 210.0,
      "bed_temp": 60.0, "bed_target": 60.0,
      "layer": 120, "layer_total": 300,
      "time_left_min": 95, "job_time_min": 60,
      "file_name": "soporte_ala.gx",
      "error_text": null,
      "snapshot_jpeg_b64": null
    }
  ]
}
```

Validación en Odoo:
- `workcenter_id` debe pertenecer al puente que llama.
- `state` debe estar en la lista de 16.5.3.
- `progress` en 0–100; temperaturas en −20…400 °C; enteros ≥ 0.
- Las cadenas se recortan a su tamaño máximo y se guardan como texto (se escapan al mostrarlas).
- `snapshot_jpeg_b64`: máx. 512 KB decodificado y con firma JPEG (`FF D8`) al inicio; si no la tiene, se descarta solo la foto.
- **Cualquier clave fuera de este esquema se rechaza** (D-17).
- `sent_at` no puede estar más de 5 min en el futuro.

### 16.7 Cruce impresora ↔ Odoo y alertas

Se evalúa en `push_telemetry` cuando cambia `state`, y periódicamente para las condiciones que dependen del tiempo (cron cada 5 min, `ir.cron`). Cada alerta se crea **una sola vez** por (impresora, tipo, WO o impresión) y se cierra sola cuando la condición desaparece.

| Impresora reporta | Odoo tiene | Resultado |
|---|---|---|
| `printing` | WO `[MCH]` en progreso | OK |
| `printing` | **ninguna** WO en progreso | Evento `unregistered` + aviso en el dashboard "Impresión no registrada en Odoo" + actividad al operador por defecto |
| `finished`/`idle` por más de `print3d_finished_alert_min` | intento `running` | Evento `finished_open` + actividad al operador del intento: "Terminó la impresión en 3DP-0X: cerrar intento PRT-…/n" |
| `error` | cualquier cosa | Evento `error` + actividad al operador + tarjeta en rojo |
| sin datos por más de `print3d_offline_alert_min` | WO en progreso | Evento `offline` + aviso "Sin comunicación con 3DP-0X" |
| cualquiera | impresora `out_of_service` | Solo se muestra; no se generan alertas |

### 16.8 Seguridad

- Nuevo grupo `group_print_bridge` ("Puente de impresoras (técnico)"), sin menús. Solo puede llamar a `get_config` y `push_telemetry`; no tiene ACL de escritura directa sobre ningún modelo (las escrituras se hacen con `sudo()` acotado dentro de esos métodos, igual que en la decisión 10 de la sección 14).
- El usuario técnico del puente es un **usuario portal** con solo `group_print_bridge` (no interno: un usuario interno es Solicitante y podría leer solicitudes) y una **API key** de Odoo 14 que genera un administrador de accesos con el botón *Generar API key* del puente (y *Revocar API keys*). La llave vive solo en el equipo del puente, como variable de entorno o *secret* de Docker; nunca en el repositorio ni en Odoo en texto plano.
- `imago.printer.status` e `imago.printer.event`: lectura para Operador y Responsable; sin creación ni escritura vía ACL.
- `imago.printer.bridge`: lectura para Operador y CRUD para Responsable. El usuario técnico no puede leer otros puentes.
- El dashboard es solo para Operador y Responsable. Sus datos se calculan con los permisos del usuario que lo abre; solo el estado en vivo se lee con `sudo()`, porque el operador no tiene escritura sobre esos modelos.
- Defensa en profundidad del puente: solo conecta a IPs privadas de su configuración (D-19), lista blanca de comandos (D-15), tiempos de espera cortos (3 s por consulta) y un máximo de bytes por respuesta (64 KB JSON/TCP, 2 MB por lectura de cámara).

### 16.9 Puente local (`bridge/`)

```
bridge/
├── README.md                 instalación y operación
├── Dockerfile                python:3.11-slim, usuario sin privilegios
├── requirements.txt          requests, Pillow
├── imago_bridge/
│   ├── __main__.py           ciclo principal, señales, backoff
│   ├── config.py             variables de entorno (ODOO_URL, ODOO_DB, ODOO_LOGIN, ODOO_API_KEY)
│   ├── odoo_client.py        execute_kw: get_config / push_telemetry
│   ├── schema.py             PrinterStatus (dataclass inmutable) + normalización
│   ├── drivers/
│   │   ├── base.py           interfaz Driver.read() -> PrinterStatus; lista blanca
│   │   ├── creality_box.py
│   │   └── flashforge_tcp.py
│   └── camera.py             extracción de un cuadro JPEG del MJPEG
└── tests/                    pytest, con las respuestas reales capturadas el 21-Oct-2026 (sin datos sensibles)
```

**Driver `creality_box`:**
- `GET http://host:port/protocal.csp?fname=Info&opt=main&function=get`, con timeout de 3 s.
- Normalización (los códigos se confirman en V-02):
  - `connect = 0` → `offline`
  - `err`/`error ≠ 0` → `error`
  - `pause = 1` → `paused`
  - `state = 1` → `printing`
  - `state = 2` → `finished`
  - `state = 0` → `idle`
  - cualquier otro valor → `unknown`
- `progress = printProgress`, `nozzle_temp = nozzleTemp`, `bed_temp = bedTemp`, `layer`/`layer_total = layer`/`TotalLayer`.
- `time_left_min = printLeftTime / 60` y `job_time_min = printJobTime / 60` (las unidades se confirman en V-02).
- Los targets de temperatura quedan vacíos (el JSON no los trae).
- Todo campo no listado se descarta antes de salir del driver.

**Driver `flashforge_tcp`:**
- Por ciclo: abrir conexión, `~M601 S1` (ignorar `Control failed`), `~M119`, `~M105`, `~M27`, `~M602` y cerrar. `~M115` solo al arrancar.
- Nunca dejar la conexión abierta entre ciclos.
- Normalización de `MachineStatus` (valores por confirmar en V-03): `READY` → `idle`; `BUILDING_FROM_SD` → `printing`; `PAUSED` → `paused`; `BUILDING_COMPLETED` → `finished`; cualquier otro → `unknown`.
- `M105 T0:a/b B:c/d` → temperaturas y targets.
- `M27 SD printing byte x/100` → `progress`; `Layer: a/b` → `layer`/`layer_total`.
- `CurrentFile` → `file_name`.
- `time_left_min` se estima con el avance y el tiempo transcurrido desde que el driver vio el arranque. Si el avance es menor que 5 %, queda vacío.

**Cámara:** lee `camera_url` hasta el primer cuadro completo (`FF D8` … `FF D9`) y cierra la conexión. Reduce la foto a 480 px de ancho con calidad 70 (≈25 KB) y la envía cada `snapshot_seconds`.

**Ajustes al implementar (21-Oct-2026), por lo observado en las impresoras reales** (detalle en la sección 14, decisiones 40–44):
- Solo biblioteca estándar de Python (sin `requests` ni Pillow): la foto se envía a su tamaño nativo (640×480, ≈70 KB) y se descarta localmente si pasa de 512 KB.
- Flashforge: **sin** `~M601 S1`/`~M602`; las consultas responden sin tomar el control y así no se compite con FlashPrint. Lista blanca: `~M115` (una vez), `~M119`, `~M105`, `~M27`. `BUILDING_FROM_SD` con 100 % y calentadores en 0 = `finished`; después pasa directo a `READY`.
- Creality: `state 1` (y `mcu_is_print 1`) = imprimiendo; `state 0` también durante el precalentamiento; en impresiones lanzadas desde USB `printProgress` queda en 0 (o 1) y las capas en 0, así que el avance se reporta como desconocido; `printJobTime` va en segundos.
- Una impresora se reporta `offline` solo tras **3 lecturas fallidas seguidas** (ambos modelos tienen tiempos de espera esporádicos).
- `ODOO_URL` debe ser `https`; `ODOO_API_KEY_FILE` para *secrets*; códigos de salida 2 (configuración) y 3 (credenciales rechazadas); lectura de impresoras en paralelo con límite de 25 s por ciclo.

**Fallos y consumo de red:**
- Si Odoo no responde, el puente reintenta con *backoff* exponencial (hasta 60 s) y sigue leyendo; envía solo el último estado, sin cola de historial.
- Si una impresora no responde, se reporta `reachable: false`.
- Con 3 impresoras, cada 10 s y fotos cada 30 s de la Adventurer, el tráfico de subida es menor a 2 KB/s.

### 16.10 Dashboard (acción cliente)

- Acción `imago_3dp.action_print_dashboard`, primer elemento del menú *Impresión 3D → Dashboard* (Operador). Se asigna como acción inicial de los operadores en la configuración (16.12).
- Datos: método `@api.model get_dashboard_data()` del modelo abstracto `imago.print.dashboard`, llamado con `this._rpc`. Verifica el grupo Operador y devuelve un solo JSON con impresoras, cola, alertas e indicadores. Las fotos se cargan con `/web/image/imago.printer.status/<id>/snapshot?unique=<snapshot_at>`.
- Refresco: estado en vivo cada 10 s; indicadores cada 60 s. **Se pausa** mientras la pestaña está oculta (`document.visibilityState`).

**Contenido (de arriba abajo):**

1. **Indicadores:**
   - Imprimiendo n/N
   - En cola
   - Atrasadas (`is_late`)
   - Carretes bajos (`spool_state = low`)
   - Tasa de fallos de los últimos 7 días
   - Puente en línea / desconectado
2. **Una tarjeta por impresora** (`is_3d_printer`, incluidas las que no tienen driver):
   - Código, modelo y badge de `live_state` (color por estado).
   - **Indicador circular de avance** (gauge de ECharts).
   - Temperaturas de boquilla y cama (actual/objetivo).
   - Capa x/y, tiempo restante y hora estimada de fin.
   - Intento y solicitud de Odoo en curso (folio, título, solicitante) y WO `[MCH]`.
   - Carrete montado con barra de gramos restantes. Si `est_grams` del intento supera los gramos restantes, aviso "Filamento insuficiente".
   - Foto de la cámara, si existe, y antigüedad del dato ("hace 12 s").
   - Botones que reutilizan las acciones de v0.1: abrir solicitud, [Iniciar intento] / [Terminar intento], [Montar carrete].
3. **Alertas abiertas** (16.7) con enlace al registro.
4. **Cola de impresión:** solicitudes `submitted`/`queued` ordenadas como la cola, con prioridad, fecha requerida (en rojo si está atrasada), material e impresora prevista.
5. **Gráficas (ECharts):**
   - Ocupación por impresora en los últimos 7 días, horas por día: desde `mrp.workcenter.productivity` de los centros `is_3d_printer`, la misma fuente que el reporte de ocupación de v0.1.
   - Pareto de causas de falla de los últimos 30 días.
   - Gramos consumidos por propósito por semana (últimas 8 semanas, de `imago.print.consumption`).
   - Tasa de éxito por impresora (últimos 30 días).

Diseño: tarjetas en una cuadrícula adaptable (1 columna en móvil, 2–4 en escritorio), colores de la paleta de Odoo 14 y textos en español. Se puede usar en una pantalla mural en pantalla completa (F11) con un usuario operador.

### 16.11 Puntos [VERIFICAR] de v0.2

| ID | Punto | Cómo verificar / fallback |
|---|---|---|
| V-01 | Montar un componente OWL 1 dentro de una acción cliente de Odoo 14 (`AbstractAction` + `ComponentWrapper` de `web.OwlCompatibility`) y la carga diferida con `jsLibs` | Leer `addons/web/static/src/js` de 14. Fallback: widget clásico (`AbstractAction` + plantillas QWeb) y carga de ECharts con `ajax.loadJS`. |
| V-02 | Códigos de `state` de la Creality Box, significado de `connect`/`err`/`error`/`pause`, y unidades de `printLeftTime`/`printJobTime` | Capturar el JSON cada 10 s durante una impresión real: arranque, pausa, reanudación, fin, cancelación, y apagando la impresora con el módulo encendido. Actualizar la tabla de 16.9 y los fixtures. |
| V-03 | Valores de `MachineStatus` de la Adventurer 4 y significado de `M27` (¿porcentaje o bytes?) durante una impresión | Mismo procedimiento. Confirmar también que consultar cada 10 s **con FlashPrint abierto** no interrumpe la impresión ni desconecta FlashPrint. |
| V-04 | Lectura de cama `B:5` en reposo (Adventurer 4) | Comparar con la pantalla de la impresora en frío y calentando. Si el valor es basura en reposo, mostrarlo solo cuando el target sea > 0. |
| V-05 | API keys de Odoo 14 para un usuario técnico (cómo se generan si nadie inicia sesión con él) y `execute_kw` con API key detrás del proxy de `erp.imago.aero` | Probar en `manuf_test`. Fallback: contraseña aleatoria larga del usuario técnico (sigue siendo autenticación estándar). |
| V-06 | Crecimiento del filestore al reemplazar `snapshot` (`attachment=True`) cada 30 s | Confirmar que el adjunto anterior queda sin referencia y lo borra el GC de filestore de Odoo 14 (autovacuum). Fallback: guardar la foto en un solo `ir.attachment` reutilizado o bajar la frecuencia. |
| V-07 | ¿La Creality Box expone nombre de archivo o temperaturas objetivo en otro endpoint de solo lectura? | Revisar la integración comunitaria y el tráfico de Creality Print (solo peticiones `function=get`). Si no, dejar esos campos vacíos. |

### 16.12 Configuración v0.2 (después de actualizar el módulo)

1. TI: reservar en DHCP las IPs de las impresoras y, de preferencia, aislarlas en una VLAN o SSID (16.2).
2. Crear el usuario técnico "Puente impresoras 3D" como **usuario portal** con solo el grupo *Puente de impresoras (técnico)* (sin acceso interno; el puente lo exige).
3. Crear el registro *Impresión 3D → Configuración → Puentes de impresoras*, ligarlo a ese usuario y pulsar **Generar API key** (administrador de accesos); la clave se muestra una sola vez y se guarda en el equipo del puente (`ODOO_API_KEY` o `ODOO_API_KEY_FILE`).
4. En cada centro de trabajo impresora, pestaña "Conexión": driver, IP, puerto (se propone solo), cámara y puente. Para los valores actuales, ver 16.2.
5. Instalar el puente en el equipo de la planta (`bridge/README.md`): `docker run` con `ODOO_URL=https://erp.imago.aero`, `ODOO_DB`, `ODOO_LOGIN` y `ODOO_API_KEY` (o `ODOO_API_KEY_FILE`). El puente exige `https` salvo `BRIDGE_ALLOW_INSECURE_HTTP=1` (solo pruebas locales).
6. Asignar la acción *Dashboard de impresión 3D* como **Acción inicial** de los usuarios operadores (*Ajustes → Usuarios → Preferencias*).

### 16.13 Criterios de aceptación v0.2

Pruebas de Odoo en `tests/` (mismo comando que v0.1):

| ID | Criterio |
|---|---|
| A-19 | La acción del dashboard existe y `get_dashboard_data()` devuelve impresoras, cola, alertas e indicadores para un Operador; un Solicitante recibe `AccessError`. |
| A-20 | `printer_host` acepta solo IPv4 privada; nombres DNS, IPs públicas, loopback y link-local lanzan `ValidationError`. El onchange del driver propone el puerto y la URL de cámara. `camera_url` con un host distinto al de la impresora se rechaza. |
| A-21 | `get_config()` y `push_telemetry()` funcionan con el usuario del puente y lanzan `AccessError` con cualquier otro usuario, incluido un Operador. |
| A-22 | `push_telemetry()` rechaza una impresora que no pertenece al puente y valores fuera de rango, sin afectar a las demás impresoras válidas del mismo lote. |
| A-23 | Un lote con una clave fuera del esquema (p. ej. `wifipasswd`) se rechaza para esa impresora y ese valor no queda guardado en ningún modelo ni en el log de Odoo. |
| A-24 | El paso `idle → printing` crea el evento `started`; `printing → finished` con intento `running` crea, pasados los minutos configurados, **una** actividad "Cerrar intento" (no se duplica en pushes posteriores). |
| A-25 | `printing` sin WO en progreso crea un solo evento `unregistered` y su alerta, que se cierra cuando el operador inicia el intento. |
| A-26 | Con `received_at` más antiguo que `print3d_telemetry_stale_s`, `live_state = 'stale'`; sin driver, `no_link`. |
| A-27 | Ningún push cambia `state` de solicitudes, `result` de intentos ni genera movimientos de stock. |
| A-28 | Una foto que no es JPEG o que pasa de 512 KB se descarta y el resto del estado sí se guarda. |
| A-29 | Cambiar la IP de una impresora incrementa `config_version` del puente y `push_telemetry` devuelve la versión nueva. |
| A-30 | El módulo actualiza de 14.0.1.0.0 a 14.0.2.0.0 sin perder datos, y las 66 pruebas de v0.1 siguen pasando. |

Pruebas del puente en `bridge/tests/` (`pytest`):

| ID | Criterio |
|---|---|
| B-01 | El parser de la Creality Box convierte el JSON capturado (sin datos sensibles) al esquema común y **no** deja pasar `wifipasswd`, `ssid`, `apclissid`, `apclimac` ni `ownerId`. |
| B-02 | El parser de Flashforge convierte las respuestas capturadas de `M115/M119/M105/M27`, incluido `Control failed` en `M601`. |
| B-03 | Los drivers rechazan cualquier comando fuera de la lista blanca (D-15); el driver Creality nunca arma una URL con `function=set`. |
| B-04 | La extracción de cámara obtiene un JPEG válido de un flujo MJPEG grabado y respeta el límite de bytes. |
| B-05 | Si Odoo no responde, el puente aplica *backoff* sin terminar. Si una impresora no responde, se reporta `reachable: false` y las demás se envían igual. |
| B-06 | El puente rechaza IPs no privadas aunque vengan de la configuración de Odoo. |

### 16.14 Fases de entrega

| Fase | Contenido | Depende de |
|---|---|---|
| F1 | Dashboard con datos de Odoo solamente (indicadores, cola, tarjetas con el estado de Odoo, gráficas) y acción inicial de operadores. A-19, A-30. | — |
| F2 | Campos de conexión, modelos de puente, estado y evento, `get_config`/`push_telemetry`, puente con los dos drivers y fotos de la Adventurer. A-20…A-23, A-26…A-29, B-01…B-06. | V-02, V-03, V-05 |
| F3 | Cruce impresora ↔ Odoo, eventos, alertas y cron. A-24, A-25. | F2 en operación ~1 semana para afinar umbrales |

### 16.15 Backlog v0.2+

| ID | Idea |
|---|---|
| REQ-3DP-108 | Video en vivo de la cámara en el dashboard (el puente sirve HTTPS con certificado válido en la red local, o un túnel). |
| REQ-3DP-109 | Prellenar los gramos del asistente *Terminar intento* con el consumo que reporte la impresora (si algún driver lo da). |
| REQ-3DP-110 | Vista de dashboard de solo lectura para solicitantes ("¿cuándo sale mi pieza?"). |
| REQ-3DP-111 | Disponibilidad (OEE simplificado) por impresora a partir de `imago.printer.event`. |
| REQ-3DP-112 | Control remoto (pausar/detener). **Fuera de alcance por seguridad**: solo si las impresoras quedan en una red aislada y con confirmación en Odoo. |
| REQ-3DP-113 | Impresión combinada: varias solicitudes en una misma placa. **→ Especificada en la sección 17.** |

---

## 17. Impresión combinada (REQ-3DP-113)

Versión objetivo `14.0.2.1.0`. No depende de F2 ni de F3 de la sección 16. Todo lo de v0.1 y v0.2 sigue vigente; los "Puntos clave del diseño" de `CLAUDE.md` no cambian. Especificado e **implementado** el 21-Oct-2026 (decisiones 33–38 de la sección 14).

### 17.1 Necesidad

Dos o más ingenieros envían solicitudes distintas y el operador ve que caben **en la misma placa** (mismo material, misma impresora, una sola corrida del slicer). Hoy no se puede registrar así:
- cada intento pertenece a una sola solicitud (`imago.print.job.request_id`, obligatorio);
- iniciar un intento deja la impresora ocupada (A-07), así que la segunda solicitud no puede arrancar en paralelo.

El atajo actual (cargar todo a una solicitud) sesga el consumo por propósito y deja la otra solicitud sin historial. La impresión combinada registra **una sola corrida física** y conserva **la trazabilidad de cada solicitud**: su MO, sus intentos, sus piezas, su consumo y su estado.

### 17.2 Decisiones de diseño

| ID | Decisión |
|---|---|
| D-21 | Nuevo modelo `imago.print.batch` ("Impresión combinada"): agrupa **un intento por solicitud** que comparten impresora, carretes, inicio y fin. Cada solicitud conserva su propio `imago.print.job`. |
| D-22 | **Una sola WO `[MCH]`** por impresión combinada, en la MO de la solicitud líder (la primera elegida). Así la ocupación de la impresora (`mrp.workcenter.productivity`) se cuenta **una vez** y la regla de impresora ocupada (A-07) no cambia. Los intentos de las demás solicitudes no tienen WO propia. En costeo de MRP, el tiempo de máquina aparece solo en la MO líder; la parte de cada solicitud queda en `allocated_minutes` del intento. |
| D-23 | **Reparto** de gramos y minutos por solicitud mediante `share` (fracción 0–1) en cada intento. Por defecto es proporcional a los **gramos estimados** de cada solicitud; si alguna no tiene estimado, se reparte por partes iguales. El operador puede corregirlo al terminar, y la suma debe ser 100 %. |
| D-24 | El filamento se captura **una vez por carrete** (gramos totales de la placa). Cada carrete se reparte con el mismo `share`, y el consumo de cada solicitud se liga a **su propia MO** (movimiento `raw`, como en v0.1). El último intento absorbe el redondeo, de modo que la suma es exactamente lo capturado. |
| D-25 | El **resultado es por solicitud**. El asistente propone un resultado de placa y lo copia a cada solicitud, pero cada una lleva su propio resultado, piezas OK y causa de falla. Cada solicitud sigue su flujo de v0.1: `post` si completó sus piezas, `queued` si no. |
| D-26 | **Indicadores:** los de impresora (tasa de fallos, resultados por impresora, causas de falla, intentos de 7 días y sellos del dashboard) cuentan la impresión combinada **una vez**, a través del intento líder y con el **peor resultado de la placa** (`printer_result`: fallido > parcial > OK > cancelado) y su causa. Así, una pieza fallida en la placa cuenta como falla de la impresora aunque la líder haya salido bien. Los de solicitud y propósito (consumo, gramos fallidos, minutos) usan la parte de cada solicitud. |
| D-27 | La mano de obra (`labor_minutes`) se captura una vez y se reparte con el mismo `share`. Se crea una WO `[LAB]` por solicitud (redondeo a minutos enteros; el último absorbe la diferencia), con lo que la separación `[MCH]` / `[LAB]` se mantiene. |
| D-28 | Una solicitud que está en una impresión combinada en curso **no se puede cancelar, rechazar ni pedir aclaración**: se lanza un `UserError` que pide terminar primero la impresión combinada, y entonces se puede cancelar esa solicitud. No se permite quitar ni agregar solicitudes a una combinada ya iniciada. |
| D-29 | El intento individual de v0.1 no cambia. La combinación es opcional y se elige en el mismo asistente **Iniciar impresión**. |

### 17.3 Modelo de datos

#### 17.3.1 `imago.print.batch` (nuevo) — hereda `mail.thread`

| Campo | Tipo | Notas |
|---|---|---|
| `name` | Char | Secuencia `PRB-%(year)s-` padding 4 → `PRB-2026-0001`. Readonly. |
| `workcenter_id` | M2o mrp.workcenter | req., dominio `is_3d_printer` |
| `job_ids` | O2m `imago.print.job` (`batch_id`) | un intento por solicitud, al menos 2 |
| `lead_job_id` | M2o `imago.print.job` | intento de la solicitud líder; dueño de la WO |
| `workorder_id` | M2o mrp.workorder | related `lead_job_id.workorder_id` |
| `request_ids` | M2m compute | solicitudes de los intentos |
| `state` | Selection | `running` (En curso) / `done` (Terminada) |
| `date_start`, `date_end` | Datetime | |
| `est_minutes` | Integer | minutos estimados de la **placa completa** (del slicer); req. al iniciar |
| `operator_id` | M2o res.users | |
| `company_id` | M2o res.company | todas las solicitudes deben ser de la misma compañía |

Restricciones:
- una solicitud no puede estar en dos combinadas en curso;
- todos los intentos de una combinada comparten `workcenter_id`.

#### 17.3.2 Extensión de `imago.print.job`

| Campo | Tipo | Notas |
|---|---|---|
| `batch_id` | M2o `imago.print.batch` | vacío en intentos individuales; `ondelete='restrict'` |
| `share` | Float | parte de la placa (0–1); 1.0 en intentos individuales |
| `is_batch_lead` | Boolean compute, store | `batch_id.lead_job_id == self` |
| `counts_for_printer` | Boolean compute, store | `not batch_id or is_batch_lead`. Filtro de los indicadores de impresora (D-26). |
| `printer_result`, `printer_failure_reason` | Selection compute, store | Peor resultado de la placa y su causa (el propio en intentos individuales). `failure_count` del líder usa `printer_result`. |
| `allocated_minutes` | Float compute, store | `duration_minutes × share` |

`imago.print.request.print_minutes_total` pasa a sumar `allocated_minutes` (es idéntico a v0.1 para intentos individuales).

### 17.4 Flujo

**Iniciar** (asistente `imago.print.job.start.wizard` extendido):
1. Campo nuevo `extra_request_ids` (M2m, "Imprimir junto con"). Su dominio son las solicitudes `queued` o `post` de la misma compañía, sin intento en curso y distintas de la principal. Vacío = intento individual de v0.1.
2. Si se eligen solicitudes extra:
   - aparece una tabla de solo lectura con cada solicitud, sus piezas pendientes, los gramos estimados y el `share` propuesto (D-23);
   - `est_minutes` pasa a ser el de la placa completa;
   - los carretes deben ser aceptables para **todas** las solicitudes (`allow_substitute`, materiales compatibles; misma regla de v0.1 aplicada a cada una).
3. Acción en una transacción:
   - bloqueo de la impresora y validaciones de v0.1 (libre, no fuera de servicio, carretes con stock);
   - MO de cada solicitud si no existe (`_ensure_production`);
   - **una** WO `[MCH] Impresión 3D – PRB-… (PRT-A + PRT-B)` en la MO líder, con `button_start()`;
   - un `imago.print.job` por solicitud (`batch_id`, `share`, `pieces_planned`, `result='running'`, líneas de consumo de 0 g por carrete);
   - `imago.print.batch` en `running`;
   - cada solicitud pasa a `printing` con mensaje en su chatter: "Impresión combinada PRB-… con PRT-B".

**Terminar** (asistente nuevo `imago.print.batch.finish.wizard`, que se abre desde cualquiera de las solicitudes, desde el intento o desde la tarjeta del dashboard):

| Campo | Notas |
|---|---|
| `plate_result` | `ok` / `partial` / `failed` / `cancelled`; al cambiar, se copia a cada línea |
| `failure_reason`, `failure_note` | de la placa; se copian a las líneas que fallaron |
| `lot_line_ids` | carrete + gramos **totales** de la placa, prellenado con los carretes del inicio; se pueden agregar carretes (runout) |
| `request_line_ids` | una por solicitud: `result`, `pieces_ok`, `failure_reason`, `share_pct` (editable) |
| `labor_minutes` | total de la placa |

Validaciones:
- las de `_validate_finish` de v0.1, aplicadas a cada línea;
- la suma de `share_pct` debe ser 100 % (tolerancia 0.01), y cada parte debe ser > 0 salvo en las líneas `cancelled`;
- gramos > 0 en al menos un carrete, salvo que todas las líneas sean `cancelled`.

Acción en una transacción:
1. Repartir cada carrete por `share` (D-24), crear los consumos de cada intento y contabilizar sus movimientos (`_post_stock_move` de v0.1, uno por consumo y MO).
2. `button_finish()` de la WO líder.
3. Escribir resultado, piezas, causa y fecha de fin en cada intento.
4. WO `[LAB]` por solicitud según D-27.
5. `_after_job_finished` de cada solicitud.
6. Avisos de carrete bajo.
7. Batch en `done`, con mensaje en el chatter de cada solicitud.

La validación de disponibilidad del lote (A-10) se aplica al **total** del carrete, antes de repartir.

### 17.5 Interfaz

- **Solicitud:** en la pestaña "Impresión", los intentos de una combinada muestran el folio `PRB-…`, la parte (%) y las otras solicitudes. El botón **Terminar intento** abre el asistente de la combinada.
- **Impresión combinada:** formulario de solo lectura (impresora, intentos con su parte y resultado, carretes, WO, chatter). Menú *Impresión 3D → Reportes → Impresiones combinadas* (Operador).
- **Dashboard (16.10):**
  - la estación muestra la impresión combinada como "PRB-2026-0001 · PRT-2026-0012 + PRT-2026-0015" (y "+N" si son más de dos);
  - el avance estimado usa el `est_minutes` de la placa;
  - el botón **Terminar intento** abre el asistente de la combinada;
  - la cola marca las solicitudes en combinada.
- La acción "¿ya terminó?" del dashboard y las alertas de F3 (16.7) se generan **una vez** por impresión combinada.

### 17.6 Seguridad

- Iniciar y terminar combinadas: solo el grupo Operador, igual que los intentos de v0.1.
- `imago.print.batch`: **lectura** para Solicitante y Operador (`_mail_post_access = 'read'` para que el operador escriba en el chatter); eliminación para Responsable, y solo sin consumos contabilizados. **Nadie** la crea ni cambia sus campos por escritura directa (RPC): `create` y `write` de los campos de negocio solo se aceptan como superusuario, y únicamente `_start_combined` / `_finish_combined` lo hacen, después de verificar el grupo Operador.
- En `imago.print.job`, `batch_id` y `share` solo los escribe la combinada (superusuario tras sus validaciones); un `write`/`create` directo con esos campos lanza `AccessError`.
- Los consumos contabilizados siguen siendo inmutables, y una combinada con consumo contabilizado no se borra.

### 17.7 Puntos [VERIFICAR]

| ID | Punto | Cómo verificar / fallback |
|---|---|---|
| V-08 | Una MO sin WO, que solo tiene consumos `raw` ya contabilizados, se cierra con `button_mark_done()` en Odoo 14 (solicitudes no líderes). | Probar en la base de pruebas. Fallback: crear en cada MO no líder una WO `[MCH]` de 0 minutos, marcada hecha al terminar y sin registro de productividad, para que la ocupación no se duplique. |
| V-09 | Que la MO líder se pueda cerrar o cancelar sin afectar a las demás (cada una tiene sus propios consumos). | Probar entregar la líder antes que las demás y al revés. |
| V-10 | Redondeo del reparto con la UdM gramo (precisión de `Product Unit of Measure`): la suma de los consumos debe igualar lo capturado. | Prueba con 100 g en tres partes de 33.33 %. |

### 17.8 Criterios de aceptación

| ID | Criterio |
|---|---|
| A-31 | Iniciar con dos solicitudes en cola en una impresora libre crea una impresión combinada `running`, un intento `running` por solicitud y **una sola** WO `[MCH]` en progreso en la MO líder. Ambas solicitudes quedan en `printing`. |
| A-32 | No se puede combinar si una solicitud no está en `queued`/`post`, si ya tiene un intento en curso o es de otra compañía, si la impresora está ocupada o fuera de servicio, o si un carrete no lo acepta una solicitud sin sustitutos. |
| A-33 | El reparto por defecto de dos solicitudes con 60 g y 40 g estimados es 60/40 %; sin estimados, 50/50 %. El asistente rechaza un reparto que no sume 100 %. |
| A-34 | Terminar con 100 g del carrete X y reparto 60/40 descuenta exactamente 100 g del lote y crea consumos de 60 g y 40 g ligados a la MO de cada solicitud. Con tres partes iguales, la suma de los consumos es 100 g exactos. |
| A-35 | Con dos carretes (runout) de 70 g y 30 g y reparto 60/40, cada lote se reparte con 60/40 (42/28 y 18/12). |
| A-36 | Resultado mixto: A `ok` con sus piezas completas pasa a `post`; B `failed` vuelve a `queued`, y su parte cuenta en `grams_failed` de B y no en la de A. |
| A-37 | La productividad de la impresora registra la duración de la placa **una vez**. `print_minutes_total` de cada solicitud es su parte (`allocated_minutes`). |
| A-38 | La tasa de fallos y los resultados por impresora (reportes v0.1 y dashboard) cuentan una placa fallida combinada como **un** intento. |
| A-39 | `labor_minutes = 30` con reparto 60/40 crea WOs `[LAB]` de 18 y 12 min, cada una en la MO de su solicitud. |
| A-40 | Cancelar, rechazar o pedir aclaración en una solicitud con combinada en curso lanza `UserError`; después de terminar la combinada sí se puede. |
| A-41 | Un Solicitante no puede iniciar ni terminar combinadas y sí puede leer la combinada de su propia solicitud. |
| A-42 | El dashboard muestra en la estación la combinada con sus solicitudes, y **Terminar intento** abre el asistente de la combinada. La acción "¿ya terminó?" aparece una sola vez. |
| A-43 | Los intentos individuales de v0.1 se comportan igual que antes: las 80 pruebas existentes pasan, y el módulo actualiza desde 14.0.2.0.0 sin perder datos (`share = 1`, `counts_for_printer = True` en los intentos existentes). |

### 17.9 Fuera de alcance

- Combinar solicitudes en **impresoras distintas** (eso son intentos individuales en paralelo).
- Agregar o quitar solicitudes de una combinada ya iniciada.
- Reparto por volumen o por tiempo de pieza leído del G-code/3MF (ligado a REQ-3DP-102).
