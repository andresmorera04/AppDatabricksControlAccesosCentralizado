# Design

## Context

Ver la motivación en `proposal.md` (¿por qué?). Este documento explica el cómo, ajustado a la arquitectura real del repo: el modelo de dominio 1 a 1 (`SolicitudGrant`, `ItemGrant`, `ResultadoItem`) vive en `control_accesos/dominio/modelos.py` y su fábrica `CrearDesdeConjuntos` ya valida cardinalidad (rechaza N a M y, por ahora, también 1 a N y N a 1, remitiendo a este change); las cinco fases del pipeline (`Planificador`, `PreFlight`, `Ejecutor`, `Verificador`, `Reportador`) ya operan sobre **listas de ítems** (`pipeline/pipeline_grants.py`), el pre-flight resuelve los privilegios efectivos **una vez por objeto distinto** (`pipeline/pre_flight.py`, `_ResolverObjetos` con `dict.fromkeys`), el enrutamiento por plano existe (`pipeline/enrutador.py`), el canal SQL real de datos está en producción desde C4 (`canales/reales/canal_sql_datos.py`), y el pipeline ya registra un evento consolidado por solicitud con el usuario OBO, con degradación controlada si la bitácora falla. La escritura masiva con PySpark por sesión inyectada es el patrón establecido de C2 (`persistencia/capa_persistencia.py`). Lo que falta: un modelo de lote que acepte 1 a N y N a 1 y lo normalice a ítems, un punto de entrada de lote en el pipeline que reutilice las fases, un reporte consolidado del lote con totales por estado agregados con funciones masivas de PySpark, y el registro por ítem en la bitácora de eventos.

## Goals / Non-Goals

**Goals:**
- Modelo de dominio `SolicitudLoteGrant` (inmutable, validado en constructor) que acepta 1 a N y N a 1, rechaza N a M con mensaje de fuera de alcance y normaliza a ítems atómicos en el orden de entrada (spec `batch-grant-operations` - "Normalización de lotes a ítems atómicos").
- Entrada de lote en `PipelineGrants` que reutiliza las cinco fases por ítem sin duplicar orquestación, con resultados parciales por ítem (un fallo nunca aborta el lote).
- `ReporteLoteGrant`: detalle por ítem en el orden de planificación más totales por estado, agregados con funciones masivas de PySpark sobre una sesión inyectada (estándar "PySpark al máximo", sin ciclos por fila).
- Registro en `bitacora_eventos` de cada ítem del lote con el usuario OBO, además del evento consolidado.
- Suite TDD en las cuatro capas; integrales autocontenidas contra `andresFree` (lote 1 a N con fallo parcial y lote N a 1 con principals reales), sin estado residual.

**Non-Goals:**
- Cardinalidad N a M: fuera de alcance (decisión D6 del proyecto); solo se rechaza con mensaje explícito.
- Canales reales del plano de control (C7/C8): en este change los ítems de control siguen con el canal simulado; el lote ya los enruta por plano, listo para inyectar el canal real cuando exista.
- Objetos external location y connection (C6), UI (C9) e informes formales (C10).
- Cambios en `SolicitudGrant` (1 a 1) ni en `ReporteGrant`: el camino 1 a 1 queda intacto; el lote es aditivo.

## Decisions

### D1 — `SolicitudLoteGrant` en el dominio, sin tocar la solicitud 1 a 1
Nueva dataclass inmutable en `control_accesos/dominio/modelos.py` con `principales`, `privilegios` y `objetos` como tuplas validadas en el constructor: conjuntos vacíos rechazados con error explícito por conjunto, N a M (varios principals y varios objetos) rechazado con el mensaje de fuera de alcance, y método `NormalizarAItems()` que produce los ítems recorriendo el eje múltiple (objetos en 1 a N; principals en N a 1) en orden de entrada y, dentro de cada uno, los privilegios en orden de entrada. `SolicitudGrant` no cambia de forma: solo se ajusta el mensaje de `CrearDesdeConjuntos` para remitir al nuevo punto de entrada de lotes (su comportamiento de fábrica 1 a 1 se conserva, retrocompatibilidad con C1–C4).
- *Alternativa:* extender `SolicitudGrant` para representar el lote. *Descartada:* rompería el contrato de la unidad 1 a 1 que consumen pipeline, canales y pruebas de C1–C4.

### D2 — Entrada de lote en `PipelineGrants`, sin orquestador nuevo
`Planificador.PlanificarLote(solicitud_lote)` valida el tipo y devuelve `solicitud_lote.NormalizarAItems()`; `PipelineGrants.ProcesarLote(solicitud_lote, identidad_llamante=None)` y `ProcesarLoteDesdeEntradas(principales, privilegios, objetos, identidad_llamante=None)` construyen/normalizan y ejecutan el mismo flujo `_ProcesarItems` de C1 (pre-flight con split por ítem → ejecución ítem a ítem por canal del plano → verificación → reporte por ítem). El pre-flight ya resuelve los privilegios efectivos una vez por objeto distinto, lo que hace eficiente el lote 1 a N sin consultas repetidas al workspace. El resultado por ítem (`ReporteGrant`) se envuelve en un `ReporteLoteGrant` con la agregación de totales (D3).
- *Alternativa:* un orquestador de lotes aparte que invoque `Procesar` por cada solicitud 1 a 1 derivada. *Descartada:* repetiría el pre-flight y la resolución de privilegios por objeto una vez por solicitud, y multiplicaría los eventos consolidados de bitácora.

### D3 — Agregación del reporte con funciones masivas de PySpark por sesión inyectada
`AgregadorReporteLote` (nuevo módulo en `control_accesos/pipeline/`) recibe la sesión Spark por inyección (mismo patrón que `CapaPersistencia` de C2: local en pruebas, provista por el entorno en la Databricks App), materializa las líneas del reporte en un DataFrame y agrega los totales por estado con `groupBy`/`agg` (funciones masivas, sin ciclos por fila, cumpliendo el estándar y el `proposal.md`). `ReporteLoteGrant` es una dataclass inmutable del dominio del reporte: `lineas` (las del `ReporteGrant`, en orden), `total_items` y `totales_por_estado` (mapa estado → cantidad, con los tres estados presentes aunque queden en cero). El camino 1 a 1 no requiere sesión: la agregación solo se invoca en el camino de lote, que es donde el estándar exige el cálculo masivo.
- *Alternativa:* agregar totales con contadores y ciclos de Python. *Descartada:* viola la regla "PySpark al máximo" declarada en el estándar y en la proposal.

### D4 — Registro por ítem en la bitácora, además del evento consolidado
En el camino de lote, tras el reporte, el pipeline registra un evento por ítem en `bitacora_eventos` (acción canónica propia, constante del módulo; usuario = identidad OBO, o explícitamente sin valor si no hay llamante, igual que en C3; detalle con principal, privilegio, objeto y estado final; resultado derivado del estado) y después el evento consolidado del lote con el desglose por estado (mismo formato del evento de C3). La escritura de los eventos por ítem se hace en un solo lote masivo a través de la capa de persistencia (no una escritura por ítem). La auditoría sigue siendo efecto lateral con degradación controlada: un fallo de la bitácora se registra en `bitacora_errores` (o salida de error) y el reporte se devuelve igual.
- *Alternativa:* registrar solo el evento consolidado. *Descartada:* la proposal exige cada ítem en la bitácora, y la trazabilidad por ítem es la razón de ser del lote auditable.

### D5 — N a 1 integral con principals reales existentes
La integral N a 1 contra `andresFree` usa dos principals reales ya existentes en el workspace: el usuario del llamante (resuelto por SCIM como en C4) y el usuario `andresmg.una@gmail.com` (autorizado expresamente por el humano); si el llamante resultara ser ese mismo usuario, el segundo principal es el grupo `account users` (también autorizado). Se otorga y verifica por principal con `SHOW GRANT` y se revoca todo al final. No se crean usuarios ni grupos: solo grants y revocaciones sobre fixtures propias.
- *Alternativa:* crear principals de prueba por API. *Descartada:* crear usuarios/grupos excede lo que Free Edition y la autorización del humano cubren, y dejaría residuos fuera del alcance de las fixtures.

### D6 — Integrales de lote reutilizando la fábrica de fixtures de C4
Las integrales viven en `tests/integrales/test_grants_batch_andresfree.py` (marker `free`) y reutilizan `FixturesUcDatos` y el transporte CLI (`SesionSqlDatabricks` + `DescubrirWarehouseServerless`) de C4: catálogo y objetos con nombre único por corrida, limpieza total en `finally`. El lote 1 a N mezcla objetos reales con un objeto inexistente para demostrar el resultado parcial real; el lote N a 1 usa los principals de D5. La bitácora se verifica en funcionales con Spark local (mismo criterio que D6 de C4), no en integrales.
- *Alternativa:* una fábrica de fixtures nueva para lotes. *Descartada:* duplicaría infraestructura ya probada; el lote no introduce tipos de objeto nuevos.

## Risks / Trade-offs

- [Lotes grandes multiplican las consultas al workspace: la verificación actual reconsulta `ListarGrantsVigentes(objeto)` por ítem (`pipeline/verificador.py`), así un lote 1 a N de P privilegios × N objetos emite P×N `SHOW GRANT` en lugar de N] → decisión del humano: se acepta el costo por ítem (lecturas idempotentes; en las integrales son ~10 `SHOW GRANT` extra contra el warehouse serverless, tiempo aceptable) y el `Verificador` queda intacto; la memoización por objeto distinto queda como optimización futura si los lotes crecen. La resolución de privilegios del pre-flight sí se comparte por objeto distinto (`dict.fromkeys`).
- [El agregador con PySpark exige sesión Spark en el camino de lote] → sesión inyectada (D3); en producción la Databricks App la provee y en pruebas se usa la local ya establecida en C2; el camino 1 a 1 no la requiere.
- [Fixtures residuales si una integral aborta a mitad] → limpieza en `finally` con REVOKE + DROP, nombres únicos por corrida (precedente C4), y verificación final de ausencia de residuos.
- [Grants residuales del N a 1 sobre principals reales del workspace] → revocación explícita por principal en la limpieza y verificación con `SHOW GRANT` de que ningún grant de la prueba persiste.
- [TOCTOU entre pre-flight y ejecución, ahora por ítem del lote] → asumido desde C3; la verificación post-grant por ítem es la red de seguridad ya specada.

## Migration Plan

Solo aditivo: un modelo nuevo (`SolicitudLoteGrant`), métodos nuevos (`PlanificarLote`, `ProcesarLote`, `ProcesarLoteDesdeEntradas`), un agregador y un reporte nuevos, y pruebas; ningún contrato, tabla ni atributo de configuración cambia. El ajuste del mensaje de `CrearDesdeConjuntos` (D1) no altera su comportamiento de rechazo en la fábrica 1 a 1. Desplegar consiste en exponer el punto de entrada de lote a los consumidores (la UI de C9); el rollback es dejar de invocarlo (el camino 1 a 1 no se toca). Sin migración de datos.

## Open Questions

Ninguna pendiente: el orden de normalización (eje múltiple en orden de entrada, privilegios dentro), los principals del N a 1 integral (D5) y la distribución de pruebas por capa (D6) quedan decididos arriba.
