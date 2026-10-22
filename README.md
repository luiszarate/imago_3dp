# Imago – Impresión 3D (`imago_3dp`)

Módulo de Odoo 14 Community para Imago Aerospace. Gestiona las **solicitudes de impresión 3D** de ingeniería, las **4 impresoras** (como centros de trabajo de MRP) y el **inventario de filamento por carrete** (un lote = un carrete), con consumo real en gramos, incluidos los intentos fallidos.

- Versión: `14.0.2.2.0` · Licencia LGPL-3 · Depende de `mrp`, `stock`, `mail` (sin Enterprise, sin `purchase`).
- Especificación y decisiones técnicas: [`SPEC.md`](SPEC.md) (la sección 14 registra cada punto [VERIFICAR]).

## Qué hace

| Quién | Qué |
|---|---|
| Ingeniero (todo usuario interno) | Crea la solicitud con 5 campos (qué se imprime, propósito, filamento, piezas, fecha) + archivo o link y la **Envía**. Ve toda la cola, edita solo las suyas en Borrador/Aclarar. |
| Operador de impresión 3D | Revisa (actividad automática), pide aclaración, rechaza o **pone en cola**; **inicia** cada intento (impresora + carrete) y lo **termina** (resultado, gramos por carrete, piezas OK, causa de falla, minutos de mano de obra); **entrega**. Gestiona impresoras y carretes. |
| Responsable de impresión 3D | Todo lo anterior + catálogos (filamentos, materiales, propósitos), borrar y **reabrir** solicitudes. |

Flujo de estados: `Borrador → Enviada → (Aclarar) → En cola → Imprimiendo → Post-proceso → Entregada` (+ `Rechazada`, `Cancelada`). Un intento incompleto regresa la solicitud a *En cola*; al completar las piezas pasa a *Post-proceso*.

### Impresión combinada (varias solicitudes en una placa)
- En **Iniciar impresión**, el campo *Imprimir junto con* agrega otras solicitudes en cola que van en la misma placa. Se crea una **impresión combinada** (`PRB-2026-0001`) con un intento por solicitud y **una sola** WO `[MCH]` (la ocupación de la impresora no se duplica).
- **Terminar intento** abre un asistente único: gramos por carrete de toda la placa, resultado y piezas por solicitud y el **reparto** (por defecto proporcional a los gramos estimados, editable; debe sumar 100 %). Gramos, minutos de máquina y mano de obra se reparten con esa proporción y cada consumo va a la MO de su solicitud.
- Los indicadores por impresora cuentan la placa una vez, con su **peor resultado** (una pieza fallida cuenta como falla de la impresora); los de solicitud y propósito usan la parte de cada una. El tiempo de máquina queda en la MO de la solicitud líder; la parte de cada solicitud está en *Minutos asignados*. Mientras la placa está en curso no se puede cancelar ni terminar una de sus solicitudes por separado.
- Consulta: *Reportes → Impresiones combinadas*. Detalle en `SPEC.md` §17.

### Integración con MRP / Inventario
- Cada solicitud genera **una MO** del producto genérico *Prototipo impreso 3D*; cada intento genera **una WO `[MCH]`** en la impresora usada (la ocupación de impresoras es la misma para producción y prototipos). Los minutos de mano de obra crean una WO **`[LAB]`** en el centro de mano de obra con su registro de productividad.
- Al terminar cada intento se descuenta el filamento **del carrete exacto** (movimiento de stock validado al momento). No se permite consumir más de lo disponible.
- En WOs de producción en una impresora (p. ej. operación 70 del Holom) el botón **[Registrar filamento]** descuenta el carrete y aparece en el reporte como *Producción*.
- Recepción de filamento: botón **[Generar carretes]** crea un lote por carrete (`ABS-NEG-0007`) hacia la ubicación 3D. **[Pesar carrete]** ajusta el inventario con báscula y tara; **[Marcar como agotado]** lo deja en 0 y lo desmonta.
- Aviso automático (chatter + actividad al operador) cuando un carrete queda en o bajo el umbral (150 g por defecto).

### Dashboard del operador (v0.2, fase F1)
Primer elemento del menú para Operador y Responsable; se puede fijar como *Acción inicial* del usuario.
- **Línea de resumen:** imprimiendo n/N, en cola, por revisar, en post-proceso, atrasadas y fallos de 7 días.
- **Pendientes:** franja de tarjetas ordenada por severidad, cada una con su botón (Iniciar, Terminar intento, Montar carrete, Abrir). Cubre atrasadas, por revisar, post-proceso, intentos que superaron su estimado, filamento insuficiente, carretes casi vacíos e impresoras libres con trabajo en cola.
- **Estaciones:** una tarjeta por impresora con su estado, la solicitud en curso, el avance **estimado por tiempo** con la hora de fin, el carrete montado y el sello de su último intento (resultado y causa). Las tarjetas se reparten todo el ancho; en una tarjeta ancha la foto de la cámara va junto a la lectura de la impresora.
- **Cola de trabajos** (por revisar, en cola, post-proceso), **Carretes** (resumen por filamento + montados y casi vacíos) y **Tendencias** (ECharts, en pestañas): ocupación 7 d, resultados 30 d, causas de falla y consumo por propósito en 8 semanas. Cola y Carretes comparten fila a la misma altura; Tendencias va debajo a todo el ancho.
- **Modo pantalla** para la pantalla mural: oculta el menú de Odoo y los botones, agranda el texto y destaca la siguiente acción.
- Se actualiza cada 15 s (las gráficas, cada minuto) y se pausa con la pestaña oculta. La lectura en vivo de las impresoras llega en la fase F2.

### Menú *Impresión 3D*
Dashboard · Solicitudes (Mis solicitudes · Cola de impresión) · Impresoras (kanban con estado, ETA y carrete montado) · Carretes · Reportes (Intentos, Tasa de fallos, Consumo de filamento, Ocupación de impresoras) · Configuración (Filamentos, Materiales, Propósitos, Ajustes).

## Instalación
1. Copiar la carpeta `imago_3dp` al `addons_path` de Odoo 14.
2. Actualizar la lista de aplicaciones e instalar **Imago – Impresión 3D**.

## Configuración inicial (después de instalar)
1. Crear la ubicación interna `Horiz/Stock/3DP` y seleccionarla en *Ajustes → Manufactura → Impresión 3D*.
2. Crear o convertir los centros de trabajo `3DP-01` … `3DP-04` con **Es impresora 3D**, modelo y materiales compatibles. Conservar el `3DP` del piloto como **centro de mano de obra 3D**.
3. Piloto Wing LH: en la BOM, mover la operación 70 `[MCH]` al centro de una impresora (o dejar `3DP-01` y cambiar la impresora en la WO).
4. Crear los productos de filamento (uno por material + color + diámetro) con **Es filamento 3D**: el formulario propone almacenable, por lote, g / kg. Indicar la tara del carrete.
5. Asignar el grupo **Operador de impresión 3D** al encargado y **Responsable** al jefe (*Ajustes → Usuarios*).
6. Elegir el **operador por defecto** en Ajustes.
7. Recibir el inventario inicial de carretes con **Generar carretes** y pegar etiquetas (reporte estándar de lotes).

> Ajustes solo lo puede guardar un administrador (limitación estándar de `res.config.settings`).

## Pruebas
129 pruebas automáticas de Odoo en `tests/` cubren los criterios A-01…A-18 del SPEC (flujo, consumo, carretes, seguridad), A-19/A-30 del dashboard (`test_dashboard.py`), A-31…A-43 de la impresión combinada (`test_combined.py`) y A-20…A-29 de las impresoras en vivo y alertas (`test_telemetry.py`). El puente tiene 218 pruebas propias: `python -m pytest bridge/tests -q`.

```bash
odoo -d test_imago_3dp -i imago_3dp --test-enable --test-tags=/imago_3dp --stop-after-init --log-level=test
```

Con Docker (lo que se usó en desarrollo, sobre una base desechable — **nunca** sobre la productiva):

```bash
docker network create imago3dp-net
docker run -d --name imago3dp-db --network imago3dp-net -e POSTGRES_USER=odoo -e POSTGRES_PASSWORD=odoo -e POSTGRES_DB=postgres postgres:12
docker run --rm --platform linux/amd64 --network imago3dp-net -e HOST=imago3dp-db -e USER=odoo -e PASSWORD=odoo -v "$PWD":/mnt/extra-addons/imago_3dp odoo:14 odoo -d test_imago_3dp --addons-path=/mnt/extra-addons,/usr/lib/python3/dist-packages/odoo/addons -i imago_3dp --test-enable --test-tags=/imago_3dp --stop-after-init --log-level=test
```

## Notas técnicas
- Odoo 14 no confirma una MO sin componentes (ni con BOM vacía): la MO de cada solicitud lleva un componente *marcador* de 0 g del filamento, que Odoo cancela al cerrarla. Los consumos de prototipos son componentes de esa MO; los de producción son movimientos independientes para no alterar la validación de consumo de la BOM del Holom. Detalle en `SPEC.md` §14.
- Los cambios de estado solo ocurren dentro de los métodos `action_*` (escritura `sudo` tras validar estado, grupo y dueño); `write` rechaza cambios de estado directos aunque el cliente envíe contexto. Consumos ya contabilizados no se editan ni se borran (corregir con [Pesar carrete]).
- La unidad de stock de un filamento debe ser el **gramo** (la de compra, cualquier unidad de peso).
- Los ajustes de carrete usan `stock.inventory` y se validan como superusuario (Odoo exige el grupo Gerente de inventario) tras verificar el grupo Operador 3D.
- Tras cambiar archivos estáticos (JS/SCSS/XML de `static/`), reinicia Odoo o abre con `?debug=assets`: en modo normal Odoo cachea el paquete de assets por proceso.
- Fuera de alcance v0.1: alias de correo, lectura de G-code/3MF, costeo por proyecto, Gantt, mantenimiento, APIs de impresoras (ver `SPEC.md` §13).

## Impresoras en vivo (v0.2 F2/F3)
- **Conexión por impresora:** en el centro de trabajo, pestaña *Conexión*: tipo (Creality WiFi Box / Flashforge), IP privada, puerto, cámara y puente.
- **Puente local** (`bridge/`, Python sin dependencias, Docker): corre en un equipo de la planta, lee las impresoras solo en modo lectura y envía su estado a Odoo por HTTPS con la API key de un usuario técnico **portal**. Odoo nunca se conecta a la planta. Instrucciones en [`bridge/README.md`](bridge/README.md).
- **Odoo guarda** el último estado por impresora (*Impresión 3D → Estado en vivo*) y los cambios de estado (*Reportes → Eventos de impresoras*). La telemetría nunca cambia solicitudes, intentos ni stock.
- **Alertas** (actividad al operador y tarjeta en *Pendientes*): imprime sin intento en Odoo, terminó con el intento abierto, error y sin comunicación con una impresión en curso. Se cierran solas cuando la condición desaparece; un cron revisa cada 5 min. Umbrales en *Ajustes → Impresoras en vivo*.
- **Dashboard:** cada estación muestra lo que dice la impresora (estado, temperaturas, capa, minutos, archivo, foto de la cámara y antigüedad del dato); el avance es "en vivo" cuando la impresora lo reporta y "estimado por tiempo" si no (las CR-M4 no reportan avance en impresiones desde USB). El resumen indica si el puente está en línea.
- **Tiempo real de impresión:** al terminar un intento, el operador confirma o corrige los *Minutos reales de impresión* (prellenados con lo que reportó la impresora o con el reloj); la hora de fin se calcula sola y también se puede editar. La ocupación de la impresora usa ese valor.
- Configuración: crear el usuario técnico portal con el grupo *Puente de impresoras (técnico)*, crear el puente en *Configuración → Puentes de impresoras*, pulsar **Generar API key** (administrador de accesos) y ligar las impresoras. Detalle en `SPEC.md` §16.12; hallazgos y decisiones en §16.2 y §14 (40–46).

## Estructura
```
models/    filament_material, print_purpose, print_request, print_job, print_batch, print_consumption,
           product_template, stock_production_lot, stock_move, stock_picking,
           mrp_workcenter, mrp_production, mrp_workorder, res_company, res_config_settings,
           print_dashboard (+ print_dashboard_charts), mrp_workcenter_link,
           printer_bridge, printer_telemetry, printer_status, printer_event
wizards/   request_message, job_start, job_finish, batch_finish, workorder_filament,
           spool_receive, spool_weigh, spool_mount (+ vistas)
views/     solicitudes, intentos, consumo, filamento/carretes, impresoras, WO, recepción, ajustes,
           dashboard (acción cliente), assets, menús
static/    src/js (dashboard + gráficas), src/xml (plantillas QWeb), src/scss, lib/echarts (5.5.1, Apache-2.0)
security/  grupos, reglas de registro, ACL
data/      secuencias, materiales, propósitos, producto genérico, tipos de actividad
tests/     common, test_request_flow, test_consumption, test_spools, test_security, test_dashboard, test_combined,
           test_telemetry
bridge/    puente local (imago_bridge: config, odoo_client, drivers creality_box / flashforge_tcp, camera; tests)
```
