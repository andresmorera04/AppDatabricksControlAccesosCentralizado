# Proposal

## Why

La prueba de uso real de la App `securitymanager` (change C9 `web-ui-minimalista`) sobre el workspace Free, con el usuario administrador del workspace, expuso defectos que la suite de C9 no detectó porque sus escenarios y dobles reproducían la misma semántica defectuosa. Observaciones del humano (H5 y siguientes):

1. **Selección de contenedores textual**: para `esquema` el catálogo es un campo de texto; para tabla/vista/volumen/modelo, catálogo y esquema son campos de texto. Debe ser una cascada de listas desplegables de selección única.
2. **Falsos bloqueos de autorización (plano de datos)**: un Metastore/Account Admin, incluso propietario de la tabla, recibe `privilegios_insuficientes` ("le falta el privilegio MANAGE") al otorgar `SELECT`. `SHOW GRANTS` no refleja la propiedad ni al Metastore Admin, y la comprobación exige el privilegio *exacto* solicitado (semántica heredada de C3).
3. **Falsos bloqueos de autorización (plano de control)**: el mismo usuario recibe "le falta CAN_MANAGE" sobre compute serverless, uso de token (PAT) y Databricks App. Causa verificada: `cliente_permisos_sdk.py` omite las entradas ACL `inherited=true`, pero la ACL real incluye `admins → CAN_MANAGE (inherited)`; descartarlas es correcto para escribir y erróneo para evaluar autoridad.
4. **Principal sin filtro por tipo** y, además, defecto de lógica en `app.py`: se usa el *primer principal del tipo* y no el elegido por el usuario (`tipo_principal == "principal"` nunca se cumple).
5. **Volúmenes y external locations** fallan al descubrir: el token OBO carece del scope `unity-catalog`.
6. **Compute serverless** solo muestra "Default Interactive Compute"; falta "Default Automated Compute".
7. **Otorgar `CAN_USE` sobre un SQL Warehouse** termina en un resultado no comprendido y sin efecto (pendiente de texto exacto del error; puede deberse al punto 3 y/o 4).

## What Changes

- **Selección (UI)**: cascada de `selectbox` (catálogo → esquema → objeto), de selección única en los contenedores y múltiple en los objetos finales; el principal se filtra por tipo y se usa realmente el elegido.
- **Autorización de datos**: la decisión de autoridad pasa a Unity Catalog con la credencial OBO del llamante (propiedad, Metastore Admin y herencia incluidos). La previsualización es **orientativa** (no bloquea con regla propia ni por coincidencia exacta); el rechazo de UC se reporta por ítem.
- **Autorización de control**: la autoridad del llamante se evalúa incluyendo las entradas **heredadas** de la ACL y la pertenencia al grupo `admins` (Workspace admin). Se conserva el cerrojo del broker (ninguna escritura del SP sin autoridad del llamante, TOCTOU y aislamiento por llamante). Se corrige el mensaje para que nombre la autoridad realmente evaluada.
- **Descubrimiento UC**: spike para habilitar el scope `unity-catalog` en la App; si no es viable, descubrimiento por SQL con OBO (`SHOW VOLUMES`, `SHOW EXTERNAL LOCATIONS`).
- **Compute serverless**: spike para descubrir "Default Automated Compute" (otro endpoint o identificador configurable en `config/app_properties.json`).
- **Verificación**: pruebas de UI con `streamlit.testing` que reproducen cada observación, y gates integrales `free` y `azure_approval` (perfil `andresAzureDev`, autorizado por el humano) sobre los casos reales; Azure con la regla de costos y App detenida salvo durante las pruebas.
- Una revisión humana del camino de autorización antes de archivar.

## Capabilities

### New Capabilities

(nada)

### Modified Capabilities

- `grant-management-ui`: selección en cascada, filtro y uso del principal elegido, previsualización orientativa en datos, descubrimiento de volúmenes/external locations y del compute serverless automated. (Capability introducida por C9; si C9 no está archivado al aplicar este change, el delta se reconcilia con el de C9.)
- `caller-privilege-resolution`: autoridad del llamante en el plano de control incluye ACL heredadas y `admins`; en el plano de datos la decisión se delega en UC (OBO) en lugar de coincidencia exacta del privilegio solicitado.
- `app-broker-grants`: la validación previa de autoridad del broker usa la misma regla de control (heredado + `admins`).

## Impact

- `app.py` (selectores, principal elegido), `control_accesos/ui/controlador.py`, `servicio_descubrimiento.py`, `servicio_disponibilidad.py`, `servicio_previsualizacion.py`, `servicio_ejecucion.py`.
- `control_accesos/canales/reales/cliente_permisos_sdk.py` (lectura de ACL con heredados para evaluar autoridad, sin cambiar la escritura), `control_accesos/resolucion/resolutor.py`, `modelos.py`, `autorizador_broker.py`, `control_accesos/pipeline/pre_flight.py`.
- `control_accesos/canales/reales/descubrimiento_uc.py`, `descubrimiento_control.py`.
- `config/app_properties.json`, `app.yaml`, `README.md` (scopes de la App y despliegue).
- Deprecia el change pausado `auth-grant-autoridad` (nunca creado) y sustituye la semántica de autoridad por coincidencia exacta de C3 en el contexto de la UI.
- Acciones humanas previstas: actualizar scopes de la App (`databricks apps update`) y reconsentir en navegador; despliegue y pruebas en `andresAzureDev` (secreto del SP Azure vigente solo 2 días desde su entrega; nunca se escribe en el repo).
- Depende de C9 (`web-ui-minimalista`); no bloquea el archivado de `compute-grants-mensaje-feature`.
