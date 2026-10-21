# imago-3dp-bridge (puente local de impresoras 3D)

Programa pequeño que corre **en la red de la planta**, lee el estado de las impresoras 3D por su IP y lo **envía** a Odoo 14 (`erp.imago.aero`) con el JSON-RPC estándar. Es la pieza "puente local" de la sección 16 del `SPEC.md` del módulo `imago_3dp` (D-11…D-20).

- Odoo está en AWS y no ve la red de la planta; el navegador tampoco puede leer las impresoras. El puente hace **solo conexiones salientes**: HTTP/TCP hacia las impresoras de la LAN y HTTPS hacia Odoo. No abre puertos de entrada.
- La lista de impresoras **no** vive en el puente: se descarga de Odoo (`imago.printer.bridge.get_config`), desde la pestaña *Conexión* de cada centro de trabajo.
- Solo usa la biblioteca estándar de Python 3.11 (sin dependencias).

## Qué lee

| Driver | Impresora | Cómo |
|---|---|---|
| `creality_box` | CR-M4 con Creality WiFi Box V3.04b06 | `GET http://IP:81/protocal.csp?fname=Info&opt=main&function=get` (JSON) |
| `flashforge_tcp` | Flashforge Adventurer 4 (fw v2.3.3) | TCP 8899: `~M119`, `~M105`, `~M27` (y `~M115` una vez al arrancar) |
| cámara | Adventurer 4 | Un cuadro JPEG del flujo MJPEG `http://IP:8080/?action=stream` |

Cada lectura se convierte al esquema común de SPEC 16.6 (`state`, `progress`, temperaturas, capas, tiempos, archivo, error, foto). Se envía un solo lote con todas las impresoras cada `poll_seconds` (10 s por defecto).

Reglas de normalización relevantes (verificadas con las impresoras reales el 21-Oct-2026):
- **CR-M4**: `connect 0` → `offline`; `err`/`error` ≠ 0 → `error`; `pause 1` → `paused`; `state 1` (o `mcu_is_print 1`) → `printing`; `state 2` → `finished`; `state 0` → `idle` (también durante el precalentamiento). En impresiones lanzadas desde USB, `printProgress` se queda en 0: se reporta avance **desconocido** (vacío), no 0 %. `printLeftTime` solo se usa con avance > 5 %. `printJobTime` está en segundos.
- **Adventurer 4**: `READY` → `idle`; `BUILDING_FROM_SD` → `printing`; `PAUSED` → `paused`; `BUILDING_COMPLETED` → `finished`. El firmware **no** reporta `BUILDING_COMPLETED` al terminar: se queda en `BUILDING_FROM_SD` con `100/100` y ambos objetivos de temperatura en 0; eso se reporta como `finished`. `SD printing byte x/100` es porcentaje. El tiempo restante se estima con el ritmo de avance observado (solo con avance ≥ 5 %).
- Una impresora se reporta `reachable: false` / `offline` solo tras **3 lecturas fallidas seguidas** (la Creality Box y la Adventurer pierden peticiones sueltas); mientras tanto se repite el último estado bueno (sin foto).
- Fotos: cada `snapshot_seconds` mientras imprime y cada `idle_snapshot_seconds` (300 s) en reposo. Fotos de más de 512 KB se descartan.

## Seguridad

- **Solo lectura.** El puente no envía ninguna orden de control: el driver Creality solo puede armar la URL con `function=get`, y el driver Flashforge solo puede enviar `~M115`, `~M119`, `~M105` y `~M27` (cualquier otro comando se rechaza antes de llegar al socket). **No** se envían `~M601 S1` / `~M602`: las consultas responden sin tomar el control, y tomarlo compite con FlashPrint.
- **Quita secretos.** El JSON de la Creality Box trae la contraseña del WiFi en texto plano (`wifipasswd`) y otros datos (`ssid`, `apclissid`, `apclimac`, `ownerId`, `DIDString`, `APILicense`, `InitString`). El driver solo copia una lista blanca de campos de estado; esos valores nunca se registran en el log ni se envían a Odoo.
- **Solo IPs privadas.** Antes de cada conexión el puente vuelve a validar que el host sea una IPv4 privada literal (sin DNS, loopback, link-local, multicast), aunque Odoo ya lo haya validado. La cámara solo se lee si su host es la misma IP de la impresora. No sigue redirecciones ni usa proxies para la LAN.
- Límites: 3 s por operación de red y un **plazo total** por consulta (Creality 5 s incluyendo conexión, encabezados y cuerpo; Flashforge 3 s por comando; cámara 5 s), 64 KB por respuesta, cámara 2 MB; Odoo 10 s por llamada. Un equipo que envíe un byte cada pocos segundos no puede retener el puente.
- **Datos hostiles.** Números fuera de rango, infinitos o gigantes (p. ej. `10**400`), JSON anidado sin fin y textos con caracteres de control o de dirección (bidi) nunca rompen el ciclo: la lectura se cuenta como fallida o el campo queda vacío. Los textos de la impresora se limpian y recortan (archivo 128, error 256, log 80 caracteres); capas y minutos mayores a 100 000 se descartan.
- La **API key** se lee de la variable de entorno (o de un *secret* de Docker) y nunca se escribe en el log. Exija `https` para `ODOO_URL`.
- Recomendación para TI (SPEC 16.2): aislar las impresoras en una VLAN/SSID al que solo tengan acceso el equipo del puente y las PCs con Creality Print/FlashPrint, y fijar sus IPs con reservas DHCP.

## Variables de entorno

| Variable | Obligatoria | Ejemplo / notas |
|---|---|---|
| `ODOO_URL` | sí | `https://erp.imago.aero` (debe ser https) |
| `ODOO_DB` | sí | nombre de la base, p. ej. `manuf_test` para pruebas |
| `ODOO_LOGIN` | sí | login del usuario técnico, p. ej. `puente-3dp@imago.aero` |
| `ODOO_API_KEY` | sí* | API key del usuario técnico |
| `ODOO_API_KEY_FILE` | — | *alternativa a `ODOO_API_KEY`: ruta a un archivo con la llave (Docker secret) |
| `BRIDGE_LOG_LEVEL` | — | `DEBUG`, `INFO` (defecto), `WARNING`, `ERROR` |
| `BRIDGE_ALLOW_INSECURE_HTTP` | — | `1` solo para una base de pruebas local por `http://` |

Si falta una variable obligatoria el puente termina de inmediato con un mensaje claro (código de salida 2). Si Odoo rechaza el usuario o la llave, termina con código 3. Si Odoo no responde, **no** termina: sigue leyendo las impresoras y reintenta con espera exponencial (5, 10, 20, 40, 60 s); al volver envía solo el estado más reciente.

## Crear el usuario técnico y su API key en Odoo 14

1. *Ajustes → Usuarios y compañías → Usuarios → Crear*: nombre "Puente impresoras 3D", login p. ej. `puente-3dp@imago.aero`, tipo **Portal**.
2. En permisos agregue **solo** el grupo *Puente de impresoras (técnico)* (`imago_3dp.group_print_bridge`). Debe ser portal y no interno: un usuario interno es también Solicitante y podría leer las solicitudes; Odoo rechaza un puente con usuario interno.
3. *Impresión 3D → Configuración → Puentes de impresoras → Crear*: nombre del puente y **usuario** = el usuario técnico. Guarde.
4. En el mismo formulario pulse **Generar API key** (requiere ser administrador de accesos). La llave se muestra **una sola vez**: cópiela al equipo del puente (`ODOO_API_KEY` o un archivo para `ODOO_API_KEY_FILE`). Nadie necesita iniciar sesión como el usuario técnico.
5. En cada centro de trabajo impresora, pestaña *Conexión*: driver, IP, puerto (se propone solo), cámara y puente.

Para revocar el acceso pulse **Revocar API keys** en el puente (o archive el usuario técnico); el puente reintentará y registrará el rechazo hasta que reciba una llave nueva.

## Instalación con Docker (recomendado)

En el equipo de la planta (mini-PC, Raspberry de 64 bits, PC del cuarto de impresión) con Docker:

```bash
cd bridge
docker build -t imago-3dp-bridge:0.2.0 .

# La llave en un archivo legible solo por el usuario del contenedor (uid 10001)
printf '%s' 'LA_API_KEY' | sudo tee /etc/imago-3dp-bridge.key >/dev/null
sudo chown 10001 /etc/imago-3dp-bridge.key && sudo chmod 400 /etc/imago-3dp-bridge.key

docker run -d --name imago-3dp-bridge --restart unless-stopped \
  --read-only --tmpfs /tmp:rw,noexec,nosuid,size=8m \
  --cap-drop ALL --security-opt no-new-privileges \
  --memory 128m --pids-limit 64 \
  -e ODOO_URL=https://erp.imago.aero \
  -e ODOO_DB=NOMBRE_DE_LA_BASE \
  -e ODOO_LOGIN=puente-3dp@imago.aero \
  -e ODOO_API_KEY_FILE=/run/secrets/odoo_api_key \
  -v /etc/imago-3dp-bridge.key:/run/secrets/odoo_api_key:ro \
  imago-3dp-bridge:0.2.0

docker logs -f imago-3dp-bridge
```

El contenedor corre con un usuario sin privilegios (uid 10001), con el sistema de archivos de solo lectura (`--read-only`; el puente no escribe a disco, `/tmp` queda como tmpfs por si acaso), sin capacidades de Linux (`--cap-drop ALL`) y sin poder escalar privilegios (`no-new-privileges`). Se detiene limpio con `docker stop` (SIGTERM).

- **Imagen base fijada por digest.** El `Dockerfile` usa `python:3.11-slim@sha256:…` (índice multi-arquitectura: sirve en amd64 y en Raspberry arm64), para que una reconstrucción no traiga otra imagen sin que nadie lo note. Para actualizarla (parches de seguridad de Debian/Python), revise el digest nuevo con `docker buildx imagetools inspect python:3.11-slim`, cámbielo en el `Dockerfile`, reconstruya y vuelva a correr las pruebas.
- **Rotación de la API key.** En Odoo, en el formulario del puente, pulse **Generar API key**, copie la llave nueva al archivo del equipo del puente y reinicie el contenedor (`docker restart imago-3dp-bridge`); después pulse **Revocar API keys** para invalidar las anteriores (o hágalo primero si la llave pudo haberse filtrado: el puente registrará el rechazo y reintentará hasta recibir la nueva). Rote la llave al menos una vez al año y siempre que cambie quien administra el equipo del puente.

## Instalación con Python (sin Docker)

Requiere Python 3.11 o superior; no hay dependencias que instalar.

```bash
cd bridge
export ODOO_URL=https://erp.imago.aero ODOO_DB=NOMBRE_DE_LA_BASE ODOO_LOGIN=puente-3dp@imago.aero
export ODOO_API_KEY_FILE=$HOME/.imago-3dp-bridge.key
python3 -m imago_bridge
```

Para dejarlo como servicio use systemd (`Restart=always`, `EnvironmentFile=` con permisos 600).

## Pruebas

Las pruebas no se conectan a ninguna impresora ni a Odoo (sockets y HTTP simulados; cualquier conexión real hace fallar la prueba). Usan respuestas reales capturadas el 21-Oct-2026 en `tests/fixtures/` (sin datos sensibles).

```bash
python3 -m venv /tmp/bridge-venv
/tmp/bridge-venv/bin/pip install -r bridge/requirements-dev.txt
/tmp/bridge-venv/bin/python -m pytest bridge/tests -q     # desde la raíz del repositorio
```

Cobertura de los criterios de SPEC 16.13: B-01 `test_creality.py`, B-02 y B-03 `test_flashforge.py` / `test_creality.py`, B-04 `test_camera.py`, B-05 `test_service.py`, B-06 `test_netguard.py` y `test_service.py`; contrato del lote en `test_schema.py`; configuración y cliente JSON-RPC en `test_config_and_client.py`.

## Estructura

```
bridge/
├── Dockerfile, requirements.txt (vacío: solo stdlib), requirements-dev.txt (pytest), pytest.ini
├── imago_bridge/
│   ├── __main__.py      arranque, señales, logging a stdout
│   ├── config.py        variables de entorno (la llave nunca se muestra)
│   ├── odoo_client.py   JSON-RPC /jsonrpc: authenticate, get_config, push_telemetry
│   ├── remote_config.py validación de get_config (impresoras con host no permitido se descartan)
│   ├── service.py       ciclo: configuración, lectura en paralelo, lote, backoff
│   ├── schema.py        PrinterStatus (inmutable) y armado del lote
│   ├── netguard.py      solo IPv4 privada literal
│   ├── lanhttp.py       GET a la LAN sin proxies ni redirecciones
│   ├── camera.py        un JPEG del flujo MJPEG
│   └── drivers/         base (lista blanca, regla de 3 fallos), creality_box, flashforge_tcp
└── tests/               pytest + fixtures
```
