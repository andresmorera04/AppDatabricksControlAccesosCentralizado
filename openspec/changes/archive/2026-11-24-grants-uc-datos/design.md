# Design

## Context

Ver la motivación en `proposal.md` (¿por qué?). Este documento explica el cómo, ajustado a la arquitectura real del repo: el contrato `Canal` ya traduce excepciones a resultados por ítem en `control_accesos/canales/contratos.py` (`Otorgar`/`Revocar`), el enrutamiento por plano existe en `pipeline/enrutador.py`, las cinco fases del pipeline consumen canales inyectados (`pipeline_grants.py`), la matriz privilegio x objeto ya declara los privilegios de los 8 tipos de este change (`matriz/matriz_privilegios.py`), el split de pre-flight y la identidad OBO existen desde C3 (`pipeline/pre_flight.py`, `autenticacion/`, `resolucion/`), y la bitácora registra el `usuario` que provoca cada evento (`bitacora/escritores.py`). El transporte real ya está probado sin instalar nada: `tests/integrales/adaptador_sql_databricks.py` ejecuta SQL contra `andresFree` por la Statement Execution API del CLI y `adaptador_canales_reales.py` ya demostró `SHOW GRANT ON <securable>` con el mapa de palabra clave por tipo. Lo que falta es la implementación real de producción del canal SQL: construir GRANT/REVOKE, ejecutarlos, traducir los errores por caso y entregar los grants vigentes reales para la verificación.

## Goals / Non-Goals

**Goals:**
- Canal SQL real de producción (`CanalDatos` concreto) con construcción de GRANT/REVOKE por tipo de objeto, ejecución por sesión inyectada, traducción de errores a mensajes específicos por caso y `ListarGrantsVigentes` real vía `SHOW GRANT`.
- Vertical slice de punta a punta: `PipelineGrants` con canal real + resolutor de C3 + identidad OBO + bitácora, otorgando y verificando grants 1 a 1 reales.
- Suite TDD en las cuatro capas; integrales autocontenidas contra `andresFree` con fixtures propias creadas y destruidas por cada prueba.

**Non-Goals:**
- External locations, connections (C6), cualquier objeto del plano de control (C7/C8), cardinalidades 1 a N y N a 1 (C5) y la UI (C9).
- Instalar `databricks-sdk` o `databricks-sql-connector`: prohibido por la regla de instalación; el transporte integral sigue siendo el CLI ya autenticado.
- Atributos nuevos en `config/app_properties.json` o tablas nuevas: este change no agrega configuración ni persistencia (la sesión se inyecta; los datos del canal son declarativos, no configurables).

## Decisions

### D1 — `CanalSqlDatos` en `control_accesos/canales/reales/`
Implementación concreta de `CanalDatos` en el subpaquete `reales/` (simétrico a `simulados/`; C7/C8 agregarán ahí los canales SDK/REST). El mapa palabra clave SQL por tipo (`CATALOG`, `SCHEMA`, `TABLE` para tabla/streaming/MV/vista, `VOLUME`, `MODEL`) pasa a producción como dato declarativo, igual al ya contrastado en el adaptador integral, pero acotado a los 8 tipos de este change; un tipo fuera de alcance lanza `ErrorCanal` con mensaje explícito (spec - "Objetos fuera del alcance"). La herencia del contrato (`Canal.Otorgar`/`Revocar`) garantiza que nada se propague al pipeline.
- *Alternativa:* ampliar el mapa a los 10 tipos del plano de datos ahora. *Descartada:* `external_location` y `connection` son C6; incluirlas sin sus pruebas infla el alcance.

### D2 — Sesión SQL como puerto inyectable, sin hardcodear conexiones
El canal consume el puerto mínimo `sql(sentencia) -> filas`: `SesionSparkSql` (en el mismo módulo) adapta la `SparkSession` real del entorno de la Databricks App (`.sql(...).collect()` normalizado a filas de texto) y el `SesionSqlDatabricks` del CLI de integrales satisface el mismo puerto tal cual. Así el código de producción se prueba contra el workspace real sin instalar dependencias, y ningún valor de conexión vive en el código (regla No HardCoded).
- *Alternativa:* canal que construya su propia conexión (perfil CLI, warehouse). *Descartada:* incrusta entorno en producción y duplica el transporte ya existente.

### D3 — Clasificación de errores por patrones declarativos sobre el texto del error
La clasificación de cada fallo (permiso denegado, objeto inexistente, principal inexistente, resto) se declara como datos (tuplas/regex sobre el mensaje del workspace, p. ej. `PERMISSION_DENIED`, `SCHEMA_OR_OBJECT_NOT_FOUND`) y produce mensajes específicos en español con los elementos del ítem. Solo el denegado explícito se traduce a `ErrorPrivilegiosInsuficientes`: cualquier patrón no reconocido queda como `fallido` genérico, nunca como privilegios insuficientes (fail-safe). Los patrones exactos se confirman contra `andresFree` en las integrales, como hizo C3 con las rutas de la Permissions API; el caso de permiso denegado se valida a nivel funcional con errores de forma real (decisión del humano) y solo se contrasta en integrales si la respuesta real ocurre de forma natural. Contrastados contra el workspace real: el objeto inexistente se reporta con `SCHEMA_OR_OBJECT_NOT_FOUND` y el principal inexistente con `PRINCIPAL_DOES_NOT_EXIST` (ambos ya incorporados a los patrones declarativos).
- *Alternativa:* códigos estructurados del SDK. *Descartada:* no hay SDK instalado y el transporte CLI entrega texto; los patrones declarativos se ajustan sin tocar lógica.

### D4 — Parseo de `SHOW GRANT` con regla fila propia / fila padre
Cada fila identifica el securable sobre el que nació el otorgamiento. Regla declarada: si la fila describe el objeto consultado, conserva el **tipo consultado** (así tabla delta, streaming table, vista materializada y vista SQL no colapsan en un solo tipo y la verificación por igualdad de ítems funciona); si describe un contenedor padre, se mapea `CATALOG`/`SCHEMA` al tipo contenedor con su identificador de la fila; una palabra no mapeable se omite sin inventar el objeto. Con esto el resolutor de C3 deriva `directo`/`heredado` por comparación de objetos, tal como su design lo declaró, sin modificarlo.
- *Alternativa:* atribuir todas las filas al objeto consultado (como el adaptador integral de C3). *Descartada:* pierde el padre real de los otorgamientos heredados y degrada la vista efectiva a `no_determinado`.

### D5 — Vertical slice por inyección, sin orquestador nuevo
La slice se ensambla inyectando en `PipelineGrants` el canal real de datos, la identidad OBO, el resolutor y las bitácoras; el canal de control sigue siendo el simulado (su implementación real es C7/C8, y este change no enruta ítems de control). El evento de bitácora con el `usuario` del llamante ya lo registra el pipeline: no se toca.
- *Alternativa:* un orquestador propio del plano de datos. *Descartada:* duplicaría fases y rompería la reutilización declarada por `grant-pipeline`.

### D6 — Bitácora verificada en funcionales, no en integrales
El registro del evento con el usuario OBO y el registro del fallo de ejecución en la bitácora de errores se verifican en las funcionales (Spark local + canal real con sesión simulada), porque el transporte CLI de las integrales no es una `SparkSession` para los escritores de la bitácora. El canal real acepta un `registrador_errores` opcional (mismo patrón que el resolutor de C3) y registra ahí cada fallo de ejecución con su detalle, sin que la auditoría se convierta en un fallo en cascada. Las integrales se concentran en lo que solo el workspace demuestra: GRANT real, `SHOW GRANT` real y traducción de errores reales, con la bitácora simulada o ausente. Las filas de bitácora que dejan las funcionales son registros legítimos de auditoría, no estado residual de fixtures.

## Risks / Trade-offs

- [Los códigos de error varían por superficie (SQL vs API) y versión] → patrones declarativos ajustables; el caso no reconocido cae en `fallido` genérico y las integrales contrastan cada patrón contra el workspace real antes de cerrar el change.
- [`CREATE STREAMING TABLE` / vistas materializadas en Free Edition] → el humano confirma que ambos tipos funcionan en `andresFree` (las MV con un SQL Warehouse serverless o con Lakeflow Declarative Pipelines sobre compute serverless; las streaming tables con cualquier compute) y autoriza expresamente el fallback: si Free Edition presentara error o limitación al crearlas, esas dos fixtures se prueban en `andresAzureDev` con marker `azure_approval`.
- [Arranque en frío del warehouse serverless alarga las integrales] → ya mitigado por el sondeo acotado del adaptador CLI (`MAXIMO_SONDEOS`); fixtures mínimas por prueba.
- [TOCTOU entre pre-flight y ejecución] → asumido y aprobado en C3; la verificación post-grant con `SHOW GRANT` es la red de seguridad ya specada.
- [Fixtures residuales si una integral aborta a mitad] → limpieza en `finally` con REVOKE + DROP de lo creado, y nombres únicos por corrida para no chocar con restos viejos.

## Migration Plan

Solo aditivo: nuevo subpaquete `control_accesos/canales/reales/` y pruebas; ningún contrato, tabla ni atributo de configuración cambia. Desplegar consiste en inyectar `CanalSqlDatos` con la sesión del entorno en lugar del simulado; el rollback es volver a inyectar el canal simulado (el pipeline no cambia). Sin migración de datos.

## Open Questions

Ninguna pendiente: la incógnita diferida del patrón del principal inexistente se resolvió al contrastarla contra `andresFree` (`PRINCIPAL_DOES_NOT_EXIST`, incorporado a los patrones); la disponibilidad de streaming table y vista materializada en Free Edition quedó confirmada por el humano y validada en las integrales.
