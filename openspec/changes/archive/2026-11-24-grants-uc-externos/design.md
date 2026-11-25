# Design

## Context

Ver la motivación en `proposal.md` (¿por qué?). Este documento explica el cómo, ajustado a la arquitectura real del repo: el canal SQL de producción `CanalSqlDatos` ya existe en `control_accesos/canales/reales/canal_sql_datos.py` (C4) con su mapa declarativo de palabra clave por tipo acotado a los 8 tipos de C4, sus patrones declarativos de clasificación de errores, el puerto de sesión inyectado (`SesionSparkSql` en producción, `SesionSqlDatabricks` del CLI en integrales) y el parseo de `SHOW GRANT` con la regla fila propia / fila padre. La matriz de compatibilidad (`matriz/matriz_privilegios.py`) ya declara los privilegios de `EXTERNAL_LOCATION` y `CONNECTION` (C1) y el dominio ya tiene ambos tipos (`dominio/enumeraciones.py`). Las cardinalidades 1 a N y N a 1 ya normalizan lotes a ítems atómicos y reportan resultados parciales (C5, `pipeline/`). Lo que falta es exactamente: admitir los dos tipos externos en el canal SQL (palabras clave `EXTERNAL LOCATION` y `CONNECTION`), contrastar los patrones de error propios de estos objetos y cubrirlo con la suite TDD de las cuatro capas.

## Goals / Non-Goals

**Goals:**
- Extender `CanalSqlDatos` para construir, ejecutar y verificar GRANT/REVOKE/SHOW GRANT sobre `external_location` y `connection`, con los mismos contratos y puertos ya establecidos en C4.
- Contrastar contra `andresFree` los patrones de error específicos de objetos externos (objeto inexistente, permiso denegado) y ajustar los datos declarativos sin tocar lógica.
- Suite TDD en las cuatro capas: unitarias (sentencias, ejecución, errores, grants vigentes), funcionales (flujo y bitácora con sesión simulada), integrales autocontenidas contra `andresFree` con skip justificado si un tipo no es creable, y aceptación trazable 1:1 a los escenarios del spec.

**Non-Goals:**
- Cualquier objeto del plano de control (C7/C8) y la UI (C9). El mensaje de rechazo del canal pasa a referirse solo a tipos del plano de control.
- Instalar `databricks-sdk` o `databricks-sql-connector`: prohibido por la regla de instalación; el transporte integral sigue siendo el CLI ya autenticado.
- Atributos nuevos en `config/app_properties.json` o tablas nuevas: este change no agrega configuración ni persistencia (la sesión se inyecta; los datos del canal son declarativos del módulo, no configuración).
- Cambios en la matriz, el dominio, el pipeline o la normalización de lotes: ya soportan los dos tipos; solo se toca el canal SQL y sus pruebas.

## Decisions

### D1 — Ampliar el mapa de palabras clave a los 10 tipos del plano de datos
`PALABRA_CLAVE_SQL_POR_TIPO_OBJETO` agrega `TipoObjeto.EXTERNAL_LOCATION: "EXTERNAL LOCATION"` y `TipoObjeto.CONNECTION: "CONNECTION"` como dato declarativo. Con ello el canal pasa a soportar los diez tipos del plano de datos (spec - "Cobertura completa del plano de datos") y el rechazo con `ErrorCanal` queda reservado a objetos del plano de control; el mensaje se actualiza para decirlo explícitamente. Las pruebas unitarias previas que afirmaban el rechazo de los dos tipos externos se actualizan como parte del cambio (es su comportamiento el que cambia, no el contrato).
- *Alternativa:* crear un `CanalSqlExternos` aparte. *Descartada:* duplicaría ejecución, traducción de errores y parseo de `SHOW GRANT`; la extensión es puramente declarativa, como anticipó el design D1 de C4.

### D2 — Mismo puerto de sesión inyectada, sin hardcodear conexiones
Los objetos externos se ejecutan por el mismo puerto `sql(sentencia) -> filas`: `SesionSparkSql` en producción y `SesionSqlDatabricks` del CLI en integrales, sin ningún valor de conexión en el código (regla No HardCoded). Los identificadores de external location y connection son nombres simples, por lo que el entrecomillado parte por parte existente (`_IdentificadorSql`) ya los cubre sin cambios.
- *Alternativa:* un transporte nuevo para objetos de metastore. *Descartada:* `EXTERNAL LOCATION` y `CONNECTION` son securables SQL de Unity Catalog como los demás; no requieren otro canal.

### D3 — Patrones de error de objetos externos, contrastados contra el workspace
La clasificación por patrones declarativos se extiende con los códigos propios de objetos externos (`EXTERNAL_LOCATION_NOT_FOUND` y `CONNECTION_NOT_FOUND`, sugerencia aprobada por el humano), contrastados contra el workspace real en las integrales, como hizo C4 con `PRINCIPAL_DOES_NOT_EXIST`. La regla fail-safe no cambia: solo el denegado explícito (`PERMISSION_DENIED`) produce `ErrorPrivilegiosInsuficientes`; un patrón no reconocido cae en `fallido` genérico. El caso de permiso denegado se valida a nivel funcional con errores de forma real y solo se contrasta en integrales si la respuesta real ocurre de forma natural (precedente C4).

**Contrastados contra los workspaces reales (corrida integral de este change):** las formas sugeridas `*_NOT_FOUND` **no** son las que reporta el motor SQL; los códigos reales son de la familia `*_DOES_NOT_EXIST`, con la clase específica encadenada a la genérica:

- external location inexistente en `andresAzureDev`: `ErrorClass=EXTERNAL_LOCATION_DOES_NOT_EXIST.RESOURCE_DOES_NOT_EXIST`, texto `External Location '<nombre>' does not exist.`;
- connection inexistente en `andresFree`: `ErrorClass=RESOURCE_DOES_NOT_EXIST.RESOURCE_DOES_NOT_EXIST`, texto `Connection '<nombre>' does not exist.` (sin clase específica de connection);
- principal inexistente: sigue siendo `PRINCIPAL_DOES_NOT_EXIST` (ya contrastado en C4), y la corrida confirmó que su texto **no** incluye `RESOURCE_DOES_NOT_EXIST`, de modo que el patrón genérico nuevo no colisiona con la clasificación del principal.

Los patrones declarativos incorporan los tres códigos reales (`EXTERNAL_LOCATION_DOES_NOT_EXIST`, `CONNECTION_DOES_NOT_EXIST` por simetría, `RESOURCE_DOES_NOT_EXIST`) y conservan las formas sugeridas `*_NOT_FOUND` como cobertura defensiva de otras superficies. Antes del ajuste, el fail-safe se comportó como está specado: el ítem quedó `fallido` con el texto crudo del motor, nunca `privilegios_insuficientes`.
- *Alternativa:* asumir los patrones sin contrastarlos. *Descartada:* los códigos varían por superficie; las integrales existen precisamente para fijar estos datos contra el workspace — y de hecho la sugerencia aprobada no coincidía con la respuesta real.

### D4 — Parseo de `SHOW GRANT`: fila propia conserva el tipo; contenedor metastore omitido
La palabra clave de la fila se normaliza ya a mayúsculas, por lo que `EXTERNAL LOCATION` (dos palabras) coincide con el mapa sin cambios de normalización. Regla declarada (idéntica a C4): la fila que describe el objeto consultado conserva el **tipo consultado** (`external_location` o `connection`); una fila de contenedor padre de estos objetos (el metastore) no tiene mapeo a tipo del dominio y se omite sin inventar objeto. El resolutor de C3 sigue derivando `directo`/`heredado` por comparación sin modificarlo.
- *Alternativa:* mapear `METASTORE` a un tipo nuevo del dominio. *Descartada:* el metastore no es un tipo gestionado por la app (README lista 15 objetos, sin metastore) e inventarlo degradaría la vista efectiva.

### D5 — Cardinalidades por reutilización, sin tocar el pipeline
La normalización de lotes a ítems atómicos (C5) y el pre-flight contra la matriz y los privilegios efectivos (C3) ya operan sobre cualquier tipo de la matriz; al admitir el canal los dos tipos externos, las cardinalidades 1 a 1, 1 a N y N a 1 funcionan sin cambios en pipeline, planificador ni reporte de lote. Las pruebas del change ejercitan el lote sobre objetos externos vía `PipelineGrants`, sin código nuevo de orquestación.
- *Alternativa:* un camino de lote específico para externos. *Descartada:* rompería la reutilización declarada por `grant-pipeline` y `batch-grant-operations`.

### D6 — Fixtures integrales con perfil por tipo (decisiones del humano) y bitácora en funcionales
Las integrales crean y destruyen sus fixtures por corrida, con perfil asignado por tipo de objeto: **external location contra `andresAzureDev`** (decisión del humano), usando el storage credential existente del workspace y un contenedor de pruebas llamado `test`, datos declarados en la fixture (nunca en el canal); **connection contra `andresFree`** hacia un SQL Server de pruebas accesible por red (host, puerto, autenticación SQL y credenciales provistos por el humano como datos de la fixture; el humano los eliminará al finalizar), con **fallback autorizado a `andresAzureDev`** si el perfil Free presenta problemas. Solo si ambos perfiles fallan para un tipo, su integral queda marcada con skip explícito que documenta la limitación y el caso se cubre en unitarias y funcionales (spec - "Tipo no creable en ningún perfil"). Como en C4, la bitácora con el `usuario` OBO y el registro de errores se verifican en las funcionales (Spark local + canal real con sesión simulada); el canal real acepta el `registrador_errores` opcional sin cambios.
- *Alternativa:* forzar ambas fixtures en `andresFree` (entorno primario). *Descartada por el humano:* la external location requiere el storage credential que vive en el workspace Azure, y aunque la connection se intenta primero en Free, el fallback autorizado evita dejar el change sin integral real por una limitación de entorno.

## Risks / Trade-offs

- [El perfil `andresFree` presenta problemas para crear la connection (red, autenticación, versión de Lakehouse Federation)] → fallback autorizado por el humano a `andresAzureDev`; solo si ambos perfiles fallan, la integral queda con skip justificado y el caso se cubre en unitarias y funcionales.
- [Las credenciales del SQL Server de pruebas quedan como datos de la fixture] → el humano las eliminará al finalizar las pruebas; la fixture las declara como datos de prueba y nunca llegan al código del canal (regla No HardCoded).
- [Los códigos de error de objetos externos difieren de los ya contrastados en C4] → riesgo materializado y resuelto: las formas sugeridas (`EXTERNAL_LOCATION_NOT_FOUND`, `CONNECTION_NOT_FOUND`) no son las reales; el motor reporta `EXTERNAL_LOCATION_DOES_NOT_EXIST.RESOURCE_DOES_NOT_EXIST` y `RESOURCE_DOES_NOT_EXIST.RESOURCE_DOES_NOT_EXIST`. Los patrones declarativos se ajustaron como datos, sin tocar lógica (design D3), y las integrales quedaron en verde tras el ajuste.
- [El patrón genérico `RESOURCE_DOES_NOT_EXIST` podría solaparse con el error de principal inexistente, que se clasifica después] → la corrida integral confirmó que el error real del principal no contiene esa clase; además el solapamiento sería solo de mensaje (ambos casos son `fallido`, nunca `privilegios_insuficientes`), de modo que la regla fail-safe no se degrada.
- [La sintaxis del DDL de la external location varía entre versiones del motor] → materializado: `WITH STORAGE CREDENTIAL` falló con `PARSE_SYNTAX_ERROR` en `andresAzureDev`, que exige `WITH (STORAGE CREDENTIAL ...)`. La fixture usa la sintaxis con paréntesis; el fallo quedó documentado en el skip/motivo de la fábrica.
- [Arranque en frío del warehouse serverless alarga las integrales] → ya mitigado por el sondeo acotado del adaptador CLI (`MAXIMO_SONDEOS`); fixtures mínimas por prueba.
- [TOCTOU entre pre-flight y ejecución] → asumido y aprobado en C3; la verificación post-grant con `SHOW GRANT` es la red de seguridad ya specada.
- [Fixtures residuales si una integral aborta a mitad] → limpieza en `finally` con REVOKE + DROP de lo creado, y nombres únicos por corrida para no chocar con restos viejos.

## Migration Plan

Solo aditivo: se amplía el mapa declarativo y los patrones de error del canal existente, y se agregan pruebas; ningún contrato, tabla ni atributo de configuración cambia. Las pruebas unitarias de C4 que afirmaban el rechazo de los tipos externos se actualizan al nuevo comportamiento (es el único cambio de comportamiento, y es exactamente el objeto del change). Desplegar consiste en inyectar `CanalSqlDatos` con la sesión del entorno, igual que en C4; el rollback es revertir el mapa a los 8 tipos. Sin migración de datos.

## Open Questions

Ninguna pendiente: las fixtures de ambos tipos externos tienen perfil y recursos asignados por decisión del humano (external location en `andresAzureDev` con el storage credential existente y contenedor `test`; connection en `andresFree` hacia el SQL Server de pruebas, con fallback autorizado a `andresAzureDev`), y la extensión de patrones de error (`EXTERNAL_LOCATION_NOT_FOUND`, `CONNECTION_NOT_FOUND`) quedó aprobada, pendiente solo de su contraste final contra el workspace en las integrales, sin cambiar specs, enfoque ni desglose de tareas.
