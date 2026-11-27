# Proposal

## Why

El mensaje de "feature no habilitada" del canal real del plano de control (`CanalControlComputo._MensajeFeatureNoHabilitada`) quedó, desde el archivado de `grants-apps-tokens` (C8), con texto fijo de *"Token Permissions API"*: hoy un cómputo/warehouse cuyo control de acceso no está habilitado reporta un mensaje ajeno a su tipo. Además, la ampliación del canal en C8 dejó dos escenarios de la suite de aceptación de `grants-compute` (C7) obsoletos: uno usa `DATABRICK_APP` como "tipo no soportado" (ya soportado desde C8) y otro espera el texto genérico "not enabled". Es un defecto de **wording** y de **suite de aceptación**, sin cambio de comportamiento especificado.

## What Changes

- `CanalControlComputo._MensajeFeatureNoHabilitada`: mensaje **neutral respecto al tipo de objeto** (no fija "Token Permissions API"), conservando la marca "(feature no habilitada)".
- Alinear los dos tests de aceptación obsoletos de `tests/aceptacion/test_aceptacion_compute_grants.py` con la realidad post-C8: "tipo no soportado" con un tipo del plano de datos, y aserción del mensaje neutral en la activación de feature.

## Capabilities

### New Capabilities

(nada)

### Modified Capabilities

(nada)

## Impact

- Código de producción del canal real del plano de control (C7/C8): `control_accesos/canales/reales/canal_control_computo.py`.
- Suite de aceptación de `grants-compute`: `tests/aceptacion/test_aceptacion_compute_grants.py`.
- Sin cambio de comportamiento especificado: change con `skip_specs: true` (sin delta-spec).
- Lateral e independiente de `web-ui-minimalista` (C9): puede implementarse en paralelo sin bloquearlo.
