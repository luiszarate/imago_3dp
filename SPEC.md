# imago_3dp — Especificación funcional y técnica v0.1

| Campo | Valor |
|---|---|
| Módulo | `imago_3dp` |
| Versión objetivo | `14.0.1.0.0` |
| Plataforma | Odoo 14 Community Edition (Python 3.6–3.8) |
| Empresa | Imago Aerospace |
| Documento relacionado | `IMAGO_Holom_Odoo14_MRP_Plan_v0.1.docx` (secciones 4.1, 4.2, 4.4, 6.1) y `IMAGO_Manual_Piloto_MRP_Holom_Odoo14.pdf` |
| Fecha | 13-Oct-2026 |
| Estado | Especificación para desarrollo (v0.1) |

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
| REQ-3DP-106 | Integración con APIs de impresoras (OctoPrint, PrusaLink) para estado en vivo. |
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

---

## 15. Entorno de desarrollo y pruebas sugerido

- Odoo 14 CE con PostgreSQL 12, en Docker (`odoo:14` + `postgres:12`) o *source checkout* rama `14.0`.
- Ejecutar pruebas:
  ```bash
  odoo -d test_imago_3dp -i imago_3dp --test-enable --stop-after-init --log-level=test
  ```
- **No** ejecutar sobre la base productiva. La validación funcional se hará después en `manuf_test` (`https://erp.imago.aero`), donde se generará el manual y la prueba piloto.
- La instalación real de Imago contiene módulos propios (`purchase_order_approved`, `import.tracking`). El módulo no debe depender de ellos ni modificarlos.
