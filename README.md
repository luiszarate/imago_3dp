# Imago – Impresión 3D (`imago_3dp`)

Módulo de Odoo 14 Community para Imago Aerospace. Gestiona las **solicitudes de impresión 3D** de ingeniería, las **4 impresoras** (como centros de trabajo de MRP) y el **inventario de filamento por carrete** (un lote = un carrete), con consumo real en gramos, incluidos los intentos fallidos.

- Versión: `14.0.1.0.0` · Licencia LGPL-3 · Depende de `mrp`, `stock`, `mail` (sin Enterprise, sin `purchase`).
- Especificación y decisiones técnicas: [`SPEC.md`](SPEC.md) (la sección 14 registra cada punto [VERIFICAR]).

## Qué hace

| Quién | Qué |
|---|---|
| Ingeniero (todo usuario interno) | Crea la solicitud con 5 campos (qué se imprime, propósito, filamento, piezas, fecha) + archivo o link y la **Envía**. Ve toda la cola, edita solo las suyas en Borrador/Aclarar. |
| Operador de impresión 3D | Revisa (actividad automática), pide aclaración, rechaza o **pone en cola**; **inicia** cada intento (impresora + carrete) y lo **termina** (resultado, gramos por carrete, piezas OK, causa de falla, minutos de mano de obra); **entrega**. Gestiona impresoras y carretes. |
| Responsable de impresión 3D | Todo lo anterior + catálogos (filamentos, materiales, propósitos), borrar y **reabrir** solicitudes. |

Flujo de estados: `Borrador → Enviada → (Aclarar) → En cola → Imprimiendo → Post-proceso → Entregada` (+ `Rechazada`, `Cancelada`). Un intento incompleto regresa la solicitud a *En cola*; al completar las piezas pasa a *Post-proceso*.

### Integración con MRP / Inventario
- Cada solicitud genera **una MO** del producto genérico *Prototipo impreso 3D*; cada intento genera **una WO `[MCH]`** en la impresora usada (la ocupación de impresoras es la misma para producción y prototipos). Los minutos de mano de obra crean una WO **`[LAB]`** en el centro de mano de obra con su registro de productividad.
- Al terminar cada intento se descuenta el filamento **del carrete exacto** (movimiento de stock validado al momento). No se permite consumir más de lo disponible.
- En WOs de producción en una impresora (p. ej. operación 70 del Holom) el botón **[Registrar filamento]** descuenta el carrete y aparece en el reporte como *Producción*.
- Recepción de filamento: botón **[Generar carretes]** crea un lote por carrete (`ABS-NEG-0007`) hacia la ubicación 3D. **[Pesar carrete]** ajusta el inventario con báscula y tara; **[Marcar como agotado]** lo deja en 0 y lo desmonta.
- Aviso automático (chatter + actividad al operador) cuando un carrete queda en o bajo el umbral (150 g por defecto).

### Menú *Impresión 3D*
Solicitudes (Mis solicitudes · Cola de impresión) · Impresoras (kanban con estado, ETA y carrete montado) · Carretes · Reportes (Intentos, Tasa de fallos, Consumo de filamento, Ocupación de impresoras) · Configuración (Filamentos, Materiales, Propósitos, Ajustes).

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
66 pruebas automáticas en `tests/` cubren los criterios A-01…A-18 del SPEC (flujo, consumo, carretes, seguridad).

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
- Fuera de alcance v0.1: alias de correo, lectura de G-code/3MF, costeo por proyecto, Gantt, mantenimiento, APIs de impresoras (ver `SPEC.md` §13).

## Estructura
```
models/    filament_material, print_purpose, print_request, print_job, print_consumption,
           product_template, stock_production_lot, stock_move, stock_picking,
           mrp_workcenter, mrp_production, mrp_workorder, res_company, res_config_settings
wizards/   request_message, job_start, job_finish, workorder_filament,
           spool_receive, spool_weigh, spool_mount (+ vistas)
views/     solicitudes, intentos, consumo, filamento/carretes, impresoras, WO, recepción, ajustes, menús
security/  grupos, reglas de registro, ACL
data/      secuencias, materiales, propósitos, producto genérico, tipos de actividad
tests/     common, test_request_flow, test_consumption, test_spools, test_security
```
