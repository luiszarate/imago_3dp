# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
- **Operador de impresión 3D** (primario): el encargado de las impresoras de Imago Aerospace. Revisa solicitudes, asigna impresora y carrete, inicia y termina cada intento, registra gramos reales y entrega piezas. Trabaja en su PC con Odoo abierto todo el turno.
- **Jefe de manufactura**: revisa ocupación, fallas y consumo de filamento para decidir prioridades y compras.
- **Ingenieros** (solicitantes): quieren saber cuándo sale su pieza y en qué lugar de la cola va.

## Product Purpose
Módulo de Odoo 14 CE (`imago_3dp`) que gestiona las solicitudes de impresión 3D de ingeniería y producción, las impresoras como centros de trabajo de MRP y el inventario de filamento por carrete (un lote = un carrete), con consumo real en gramos, incluidos los intentos fallidos. El dashboard del operador es su página inicial: en un vistazo muestra qué imprime cada máquina, qué sigue en la cola, qué carretes se acaban y qué requiere acción.

Éxito: el operador no tiene que abrir cinco menús para saber qué hacer ahora, y nadie le pregunta "¿cómo va mi pieza?".

## Positioning
La ocupación de impresoras y el consumo de filamento viven en los mismos centros de trabajo, órdenes de fabricación y lotes que usa la producción del Holom. El dashboard une el estado registrado en Odoo con (desde la fase F2) el estado leído de las impresoras en la red local.

## Operating Context
- Dos modos de uso: **PC del operador** (trabaja con clics: iniciar/terminar intento, montar carrete) y **pantalla mural** del cuarto de impresión que se lee a distancia, casi sin clics.
- Impresoras: 2 × Creality CR-M4 y 1 × Flashforge Adventurer 4 (hasta 4 centros `3DP-01…04`).
- Odoo en AWS (`erp.imago.aero`); validación funcional en la base `manuf_test`.
- Vocabulario: solicitud (`PRT-AAAA-NNNN`), intento, carrete (`ABS-NEG-0007`), WO `[MCH]` (máquina) y `[LAB]` (mano de obra), post-proceso, propósito.

## Capabilities and Constraints
- Odoo 14 Community únicamente; acción cliente con widgets clásicos (`AbstractAction` + QWeb) y Apache ECharts 5.5.1 local, sin compilación npm.
- Contenido del dashboard: estado por impresora, indicadores, alertas, cola de trabajos (enviadas, en cola, post-proceso), inventario de carretes, intentos recientes y gráficas (ocupación, resultados, causas de falla, consumo por propósito).
- F1 muestra el estado según los registros de Odoo; la telemetría en vivo (avance, temperaturas, cámara) llega en F2 (`SPEC.md` §16).
- El dashboard es solo para el grupo Operador/Responsable; una vista de solo lectura para ingenieros está en el backlog (REQ-3DP-110).
- Textos de interfaz en español; código en inglés.

## Brand Commitments
Seguir el look nativo de Odoo 14 (decisión del usuario, 21-Oct-2026). La marca de Imago Aerospace no es obligatoria en esta superficie.

## Evidence on Hand
- Datos reales: no hay todavía; la base local `p3d_demo` tiene datos de demostración generados.
- No inventar métricas, tiempos ni estados de impresora que el sistema no registre.

## Product Principles
1. Lo que exige acción va primero: atrasos, carretes por acabarse, impresiones por cerrar.
2. Un vistazo desde lejos, un clic desde cerca: legible en pantalla mural, operable en la PC.
3. Honestidad de la fuente: distinguir lo registrado en Odoo, lo estimado y lo leído de la impresora.
4. Odoo es la fuente de verdad del negocio; el dashboard no inventa ni modifica datos.

## Accessibility & Inclusion
Estados nunca solo por color: siempre con texto o ícono. Lectura a distancia en pantalla mural.
