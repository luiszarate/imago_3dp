# CLAUDE.md — imago_3dp

Módulo de Odoo 14 CE para Imago Aerospace: solicitudes de impresión 3D, impresoras (centros de trabajo) y carretes de filamento (lotes).

## Fuente de verdad
- `SPEC.md` en esta carpeta. Leerlo completo antes de escribir código. La **sección 14** registra los resultados de cada [VERIFICAR] y las decisiones tomadas.
- Contexto general: `../IMAGO_Holom_Odoo14_MRP_Plan_v0.1.docx` y `../IMAGO_Manual_Piloto_MRP_Holom_Odoo14.pdf`.

## Reglas
- Python, Odoo **14.0 CE** únicamente (`stock.production.lot`, `stock.inventory`, `attrs` en vistas). Sin módulos Enterprise.
- Código en inglés; etiquetas y mensajes de UI en español.
- Resolver cada punto **[VERIFICAR]** del SPEC leyendo el código fuente de Odoo 14 y registrar el resultado en la sección 14 del SPEC.
- Verificar todo con cuidado: cada criterio A-01…A-18 debe tener prueba en `tests/` y pasar.
- Después de cada modificación de código, actualizar `README.md` y este `CLAUDE.md`.
- Nunca trabajar contra la base productiva. La validación funcional se hará en `manuf_test`.

## Estado
- v0.1 (14.0.1.0.0) **implementada** (66 pruebas propias; desinstalación limpia verificada).
- Pruebas actuales: **129/129 OK** en Odoo 14 CE (v0.1 + dashboard + impresión combinada + telemetría) y **218** del puente (`bridge/tests`, pytest).
- Pendiente: validación funcional en `manuf_test` y manual de usuario.
- v0.2 (`SPEC.md` §16) **implementada**: F1 dashboard (14.0.2.0.0), F2 puente + drivers + telemetría y F3 alertas (14.0.2.2.0). Pendiente: confirmar qué significa `state 4` + `err 1` de la CR-M4 tras detener una impresión (decisión 40), V-05 detrás del proxy de producción y V-06 (filestore) en `manuf_test`.
- Impresión combinada (REQ-3DP-113, 14.0.2.1.0) **implementada** (`SPEC.md` §17; decisiones 33–39, incluida la revisión de código) y actualización desde 14.0.2.0.0 verificada.
- Diseño: `PRODUCT.md`, `DESIGN.md` (+ `.impeccable/design.json`) y el brief/contrato de superficie en `.impeccable/surfaces/` (Impeccable). Estructura: franja de acciones sobre las estaciones, con Modo pantalla. Revisión final de diseño: *ship*. Cambios visuales al dashboard deben respetar los tokens y reglas de `DESIGN.md`.

## Impresión combinada (no romper)
- Una sola WO `[MCH]` por placa, en la MO de la solicitud líder; los demás intentos no tienen WO y sus consumos se ligan a la MO de su propia solicitud (`consumption.workorder_id` vacío).
- `job._finish` rechaza intentos de una combinada; solo `imago.print.batch._finish_combined` los cierra (parámetro privado `from_batch`, nunca contexto).
- `job.batch_id`/`share` y los campos de `imago.print.batch` solo se escriben como superusuario desde `_start_combined`/`_finish_combined` (tras `_check_operator`); el operador tiene ACL de solo lectura sobre la combinada (`_mail_post_access = 'read'`).
- Reparto por **mayor resto** (`_allocate`): nunca negativo y suma exacta; una parte que redondea a 0 g se rechaza antes de cerrar nada.
- Indicadores de impresora: `counts_for_printer` + `printer_result` (peor resultado de la placa).
- Los indicadores de solicitud usan `allocated_minutes` y los consumos propios.

## Telemetría (no romper)
- El usuario técnico del puente es **portal** + `group_print_bridge` (constraint); su API key la genera un administrador de accesos con *Generar API key*.
- `get_config`/`push_telemetry` validan al usuario del puente y escriben como superusuario; `imago.printer.status`/`event` solo se escriben como superusuario (write/create bloqueados).
- Claves desconocidas en una impresora la rechazan sin guardar su valor (la Creality Box expone la contraseña WiFi). `progress_known` distingue "sin avance" de 0 %.
- Las alertas se abren una vez, se cierran solas (`alert_open`) y no se reabren antes de 10 min; la telemetría no cambia solicitudes, intentos ni stock.
- Validación del lote: números finitos y acotados, texto sin caracteres de control, foto verificada con Pillow, nunca una excepción que aborte el lote.
- Tiempo real: mandan los **minutos** capturados (prellenados con la impresora); la hora de fin se deriva y es editable.
- El puente: solo lectura (Flashforge sin `~M601`), solo IPv4 privadas, `https` obligatorio, `offline` tras 3 lecturas fallidas.
- `lanhttp._DeadlineSocket` no debe cerrar el socket real mientras haya un lector abierto (decisión 49: el cuerpo llega después de los encabezados en la Creality Box y en la cámara).

## Reglas de diseño v0.2 (no romper al implementar)
- Dashboard: los botones llaman por `/web/dataset/call_button` (con `_rpc` model/method la acción vuelve sin `views`). Plantillas QWeb clásicas: cálculos (`Math.*`) en el view model de JS, no en la plantilla. Modo pantalla debe limpiar las clases de `body`/`html` al salir de la acción.
- Tras cambiar `static/`, reiniciar Odoo (o `?debug=assets`) para ver el cambio.
- Odoo está en AWS: **el puente envía** el estado a Odoo (`execute_kw` con API key de un usuario técnico). Odoo nunca se conecta a la planta.
- **Solo lectura:** lista blanca de comandos (Creality solo `function=get`; Flashforge solo `~M601 S1/~M602/~M115/~M119/~M105/~M27`). Ningún método de Odoo manda órdenes a una impresora.
- **Lista blanca de campos:** el JSON de la Creality Box trae la contraseña WiFi (`wifipasswd`) y otros datos de red. Se descartan en el puente y Odoo rechaza las claves desconocidas.
- La telemetría **no** cambia estados de solicitud, resultados de intento ni stock; solo crea eventos, alertas y actividades.
- El estado en vivo va en `imago.printer.status`, no en `mrp.workcenter`. Las IPs se aceptan solo como IPv4 privada literal.

## Puntos clave del diseño (no romper)
- `print_request._ensure_production`: la MO necesita un movimiento de componente *marcador* de 0 g; sin él Odoo 14 no confirma la MO.
- Consumo de desarrollo = movimiento `raw` de la MO de la solicitud, validado al terminar el intento (necesario para `button_mark_done`). Consumo de WO de producción = movimiento independiente (no tocar la validación de consumo de la BOM del Holom).
- Cambios de `state` solo vía `_set_state` (escritura `sudo`, tras validar estado/grupo/dueño); `write`/`create` solo aceptan `state` con `env.su`. **No** usar banderas de contexto para saltar validaciones: el cliente RPC puede enviarlas.
- Consumos con `stock_move_id` son inmutables (write/unlink bloqueados); solicitudes/intentos con consumo contabilizado no se borran.
- UdM de stock del filamento = gramo (constraint).
- Los no-operadores no pueden fijar `OPERATOR_FIELDS` (ver `print_request.py`).
- `sudo()` / `SUPERUSER_ID` solo en escrituras acotadas tras verificar el grupo: montar/desmontar carrete, fuera de servicio, ajuste de inventario del carrete (`stock.inventory.action_validate` exige gerente de inventario), efectos de `action_submit` y cancelación del solicitante.
- `printer_status` es no almacenado: para validar usar `_printer_running_workorder()` (búsqueda fresca).

## Cómo probar (Docker, base desechable)
```bash
# Postgres 12 + red (una vez)
docker network create imago3dp-net
docker run -d --name imago3dp-db --network imago3dp-net -e POSTGRES_USER=odoo -e POSTGRES_PASSWORD=odoo -e POSTGRES_DB=postgres postgres:12
# Pruebas del módulo
docker run --rm --platform linux/amd64 --network imago3dp-net -e HOST=imago3dp-db -e USER=odoo -e PASSWORD=odoo -v "$PWD":/mnt/extra-addons/imago_3dp odoo:14 odoo -d test_imago_3dp --addons-path=/mnt/extra-addons,/usr/lib/python3/dist-packages/odoo/addons -i imago_3dp --test-enable --test-tags=/imago_3dp --stop-after-init --log-level=test
```
`.claude/launch.json` levanta la instancia local (`odoo14-local-instance`, `../../Local Instance`) en el puerto 8069. La base desechable `p3d_demo` tiene datos de demostración del dashboard (usuario `admin`).
