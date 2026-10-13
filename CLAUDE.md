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
- v0.1 (14.0.1.0.0) **implementada**: modelos, asistentes, vistas, seguridad, datos y 66 pruebas.
- Pruebas: 66/66 OK en Odoo 14 CE (base sin demo y base nueva con demo). Desinstalación limpia verificada.
- Pendiente: validación funcional en `manuf_test` y manual de usuario.

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
`.claude/launch.json` levanta un servidor de demostración local (`ui_demo`) en el puerto 8069.
