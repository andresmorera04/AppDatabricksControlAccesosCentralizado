# Design

## Context

Ver la motivación en `proposal.md` y el contrato observable en `specs/grant-management-ui/spec.md`. C1–C8 ya proporcionan el modelo de dominio, la matriz, `Planificador`, `PreFlight`, `PipelineGrants`, los canales reales SQL/SDK, el resolutor de privilegios, los reportes y las bitácoras. `PipelineGrants.ProcesarDesdeEntradas` y `ProcesarLoteDesdeEntradas` están previstos explícitamente para esta UI.

El repositorio aún no tiene punto de entrada web, proveedor OBO de producción, fábrica de clientes/sesiones para la App ni servicio reusable de descubrimiento de principals y objetos. La identidad inyectada al pipeline no autentica por sí misma los canales: C9 debe construir el `WorkspaceClient` y la sesión Spark con la credencial del mismo llamante. Tampoco existe `app.yaml` y las dependencias de runtime y pruebas están mezcladas en `requirements.txt`.

La documentación vigente de Databricks Apps confirma el encabezado `x-forwarded-access-token` para Streamlit, el manifiesto `app.yaml` y que los scopes OAuth del usuario limitan las APIs utilizables. La imagen estándar usa Python 3.11, mientras el entorno local del proyecto usa Python 3.14; las versiones de Databricks Connect deben validarse contra el runtime serverless, no copiarse del `pyspark` local.

## Goals / Non-Goals

**Goals:**

- Una Databricks App Streamlit, en español, estructurada con controladores, servicios y presentadores POO; `app.py` queda como entrada delgada, no como script con la lógica.
- Autenticación OBO extremo a extremo y aislamiento entre usuarios para descubrimiento, resolución y otorgamiento.
- Selección guiada de principals y objetos reales del workspace, privilegios de la matriz, disponibilidad por privilegios efectivos, previsualización, confirmación y reporte por ítem.
- Reutilización del pipeline y de los canales existentes, sin duplicar planificación, pre-flight, ejecución, verificación ni agregación de lotes.
- Empaquetado reproducible con `app.yaml`, dependencias runtime separadas de las de desarrollo y suite TDD en las cuatro capas del proyecto.

**Non-Goals:**

- Cardinalidad N a M, revocación desde la UI, creación/eliminación de recursos, activación de features o administración de OAuth/scopes desde la propia App.
- Tipos de objeto, canales o privilegios nuevos; cambios al dominio, la matriz, el pipeline, el resolutor o los reportes salvo correcciones estrictamente necesarias de cableado, sin alterar sus contratos.
- Ejecutar grants con el service principal de la App como fallback NO autorizado (sin que medie la validación de la autoridad del llamante), captura libre de identificadores como sustituto del descubrimiento, o elevación cuando OBO falle. El modo broker (change `app-broker-identidad-ejecucion`) sí ejecuta ACLs del plano de control con el SP, pero solo tras la autorización del llamante.
- Generador formal de informes (C10), instalaciones locales sin autorización humana o persistencia de tokens/estado de autenticación.

## Decisions

### D1 — Streamlit como framework y `app.yaml` como manifiesto

Se elige **Streamlit** porque Databricks documenta específicamente `st.context.headers.get("x-forwarded-access-token")` y un comando `streamlit run app.py` para Databricks Apps. Sus formularios y estado de sesión cubren el flujo sin frontend propio. `app.yaml` declara el arranque, las variables de entorno no sensibles y un health check sobre el endpoint de salud de Streamlit.

- *Alternativa: Gradio.* Descartada: también aparece soportada, pero no aporta una ventaja para formularios y tablas y exigiría validar otro patrón de acceso al request.
- *Alternativa: Flask/FastAPI con frontend propio.* Descartada: aumenta superficie, dependencias y trabajo sin mejorar el objetivo minimalista.

### D2 — Capas POO entre la vista y el pipeline

Se crea `control_accesos/ui/` con cuatro responsabilidades: controlador de eventos de pantalla, servicios de aplicación para solicitud/previsualización/ejecución, presentador de modelos de vista y fábrica de dependencias del llamante. La entrada raíz `app.py` solo inicializa configuración y delega en el controlador.

- `ControladorGrantsUi`: coordina selección, previsualización, confirmación y errores.
- `ServicioSolicitudGrantsUi`: valida cardinalidad y construye los modelos del dominio; un único `TipoObjeto` por solicitud.
- `ServicioPrevisualizacionGrants`: usa `Planificador` + `PreFlight`, nunca un método `Procesar*`.
- `ServicioEjecucionGrantsUi`: usa `PipelineGrants.ProcesarDesdeEntradas` para 1:1 y `ProcesarLoteDesdeEntradas` para 1:N/N:1, con `AgregadorReporteLotePython` (D5) para conservar los totales del lote sin sesión Spark.
- `PresentadorGrantsUi`: transforma `ClasificacionPreFlight`, `LineaReporte` y `ReporteLoteGrant` en filas inmutables con campos del dominio; no parsea textos ni serializa enums/dataclasses directamente.

- *Alternativa: toda la lógica en `app.py`.* Descartada: viola POO, dificulta TDD y mezcla rerenders con operaciones de privilegios.

### D3 — Una composición OBO por acción y por llamante

Un `ProveedorIdentidadDatabricksApp` implementa `ProveedorIdentidadLlamante` y obtiene el token mediante un acceso inyectable a los headers, usando `x-forwarded-access-token` en producción y dobles en pruebas. Resuelve identidad y grupos mediante `current_user.me()` del `WorkspaceClient` OBO (endpoint `/Me`, cubierto por el scope por defecto `iam.current-user:read` y verificado GO en el spike; los listados SCIM de otros principals son superficie broker, D6), con el cliente construido explícitamente con host, token OBO y `auth_type='pat'` (hallazgo F1 del spike 2.4: el runtime de la App trae en el entorno credenciales OAuth de su propio service principal y, sin método explícito, el SDK aborta por combinación `oauth and pat` o podría preferir el OAuth de la App).

`FabricaContextoLlamante` crea, para cada acción, el proveedor, `ServicioIdentidadLlamante`, cliente SDK, sesión SQL remota (Statement Execution API, ver D5), canales, resolutor y pipeline. El SDK y la sesión SQL remota reciben el mismo token con `auth_type='pat'`; no se reutilizan singletons de módulo ni objetos entre sesiones de Streamlit. El estado de sesión guarda selecciones y modelos de vista, nunca tokens, headers, clientes OBO ni sesiones remotas.

El modo broker (change `app-broker-identidad-ejecucion`, GO) añade un segundo contexto: `FabricaContextoBroker` compone el cliente del service principal (autoconfiguración OAuth M2M del entorno de la App), el canal de ACL del plano de control y el descubrimiento SCIM. La ejecución con el SP solo ocurre tras validar la autoridad del llamante (cerrojo D2 del change broker); OBO sigue siendo la única vía para identidad, SQL UC y ACL de Databricks Apps.

- *Alternativa: un pipeline global al que solo se cambia `identidad_llamante`.* Descartada: esa identidad no autentica los canales y mezclaría credenciales entre usuarios.
- *Alternativa: heredar las credenciales de la App mediante autoconfiguración.* Descartada: podría seleccionar el service principal de la App; la credencial OBO se pasa explícitamente y no hay fallback de grants.

### D4 — Scopes y recursos de la App como precondición verificable

Antes de construir la vertical completa se despliega un spike mínimo que valida: lectura de identidad, listados necesarios, SQL/Spark remoto, lectura de ACL y una escritura controlada con restauración. La App debe tener habilitada autorización de usuario y los scopes mínimos efectivamente disponibles para identidad, descubrimiento, SQL y Permissions API; el consentimiento y la asignación de recursos se configuran fuera del código.

Si el workspace no ofrece un scope necesario para una operación del alcance, la implementación se detiene en ese gate y se eleva al humano la limitación concreta. No se sustituye por la identidad de la App **sin la validación de la autoridad del llamante** —el modo broker (D3/D10) sí la usa de forma explícita y condicionada para SCIM y el plano de control— ni se declara disponible una operación no verificada. Los recursos de cómputo y warehouse, cuando aplique, se inyectan por `app.yaml`/variables de entorno y se referencian desde `config/app_properties.json`, sin host, token, secretos ni ids embebidos en Python.

**Evidencia empírica (2026-11-27, change `app-broker-identidad-ejecucion`, gate GO):** el gate OBO estricto (2.4/2.6) dio NO-GO por scopes de Apps no otorgables (`scim`, `clusters`, `access-management`, `all-apis`) y por `databricks-connect` inviable en Python 3.11 (hallazgo F2). El modelo broker absorbe esas superficies: el spike broker desplegado en `andresFree` verifica GO para listados SCIM con el SP, ACL de warehouse y tokens (lectura y escritura restaurada), ACL de `serverless-compute` (la superficie de cómputo real de Free; clusters all-purpose = 0) y la resolución de los privilegios efectivos del llamante leyendo la ACL con el SP. Toda escritura con el SP es posterior a la autorización del llamante (change broker).

- *Alternativa: descubrir la limitación al final mediante las integrales.* Descartada: una carencia de scope cambia la viabilidad de OBO y debe detectarse antes de implementar toda la UI.

### D5 — Transporte SQL remoto en runtime y dos archivos de dependencias

La decisión original prescribía Databricks Connect en runtime. El spike (tareas 2.4/2.6, hallazgo F2) lo descartó empíricamente en la App: la imagen de Apps usa Python 3.11, que obliga a `databricks-connect` 15.4 (basado en Spark 3.5), cuyo `Builder` no tiene `create()` —método que solo existe en Connect ≥16, incompatible con Python 3.11—, y `getOrCreate()` es inadmisible porque reutiliza la sesión activa del proceso y rompería el aislamiento OBO por llamante (D3).

Transporte revisado: `SesionSqlRemota` sobre la SQL Statement Execution API del SDK (scope `sql`, verificado GO en el spike para listado de warehouses), construida por acción con host y token del llamante y `auth_type='pat'`. El encaje está verificado en el código existente: `CanalSqlDatos` solo exige `.sql()` a su sesión; los totales de lote se resuelven con un agregador alternativo en Python sobre el mismo puerto (el pipeline ya acepta `sesion_spark=None`); la escritura de bitácora usa INSERT vía REST (D10). La alternativa antes descartada (Statement Execution) se convierte en el único transporte viable en la App, con alcance acotado y probado.

`requirements.txt` contiene Streamlit y `databricks-sdk`; ya no contiene `databricks-connect`, y nunca `pytest`, `pyspark` ni `delta-spark`. `requirements-dev.txt` conserva las dependencias de suite (`pytest`, `pyspark`, `delta-spark`, necesarias para la regresión de C1–C8) y los pins compartidos SDK/Streamlit, sin `-r requirements.txt`. La duplicación de pins compartidos se mantiene igual mediante pruebas de consistencia.

- *Alternativa: un único archivo con todo.* Descartada: el contenedor cargaría dependencias de pruebas innecesarias y los pines locales de `pyspark` para la regresión C1–C8 no son compatibles con el runtime de la App.
- *Alternativa: Connect con `getOrCreate()`.* Descartada: compartiría una única sesión por proceso entre llamantes; un segundo usuario podría operar con la credencial del primero (violación OBO de D3).
- *Alternativa: Connect híbrido solo para auditoría.* Descartada de momento: añade una dependencia pesada al runtime para operaciones expresables como INSERT vía REST; se reconsiderará solo si el escritor REST resulta insuficiente.

### D6 — Descubrimiento OBO detrás de puertos, con errores explícitos

Un `ServicioDescubrimientoUi` consume puertos de listado de principals y objetos. Los listados de Unity Catalog, de SQL warehouses y de Databricks Apps usan el cliente OBO y APIs paginadas; los listados SCIM de usuarios/grupos/service principals y de cómputo (clusters all-purpose y serverless compute objects) se obtienen con el **service principal de la App** (contexto broker, change `app-broker-identidad-ejecucion`), porque el token OBO carece de los scopes `scim` y `clusters`. Los tipos de tabla se distinguen por sus metadatos, no por el texto introducido por el usuario.

Cada resultado se traduce a una `OpcionDescubierta` con principal/objeto del dominio, etiqueta y estado de descubrimiento. Paginación, límites de opciones y de ítems por lote son configurables. Un listado denegado produce un error de catálogo de opciones, nunca una lista vacía aparente. `USO_TOKEN`, al ser singleton, se representa con un identificador lógico configurable; el canal ya omite ese identificador en la ruta real.

- *Alternativa: campos de texto libre.* Descartados como mecanismo principal: no satisfacen el descubrimiento de la proposal y aumentan errores e inyección de identificadores SQL.
- *Listar SCIM con el service principal de la App.* Es la vía correcta para SCIM y cómputo (OBO no alcanza el scope); la autorización del llamante sigue aplicándose en la disponibilidad (D7), de modo que listar con SP no habilita escritura sin autoridad.

### D7 — Disponibilidad calculada con el resolutor existente

Tras seleccionar tipo y privilegios, el servicio de disponibilidad resuelve una vez cada objeto descubierto con `ResolutorPrivilegiosEfectivos` y cachea ese resultado solo dentro de la acción. Una combinación objeto-privilegio queda no disponible cuando el privilegio no figura entre los efectivos; se conserva el mensaje estructurado de C3. Un objeto puede seguir seleccionable si solo algunas combinaciones están bloqueadas: la previsualización muestra el detalle por ítem y el pipeline nunca ejecuta las bloqueadas.

La misma clasificación alimenta la previsualización, de modo que la UI no implementa otra regla de autorización. La semántica ya especificada por C3 —coincidencia del privilegio solicitado y herencia reportada por el canal— no se redefine en C9.

- *Alternativa: ocultar todos los objetos sin autorización antes de cualquier consulta.* Descartada: impediría explicar el motivo y mezclaría disponibilidad parcial con objetos totalmente no autorizados.
- *Alternativa: inferir autoridad por pertenencia a `admins` o por `CAN_MANAGE` en la UI.* Descartada: cambiaría el contrato de C3 y elevaría visualmente lo que el pipeline bloquearía.

### D8 — Previsualización independiente y ejecución con revalidación

`ServicioPrevisualizacionGrants` planifica ítems y llama a `PreFlight.Clasificar` con identidad y resolutor reales. No crea `Ejecutor` ni invoca canales de escritura. La previsualización conserva ejecutables y bloqueados en orden, y deshabilita confirmar cuando no hay ejecutables.

Al confirmar, `ServicioEjecucionGrantsUi` vuelve a construir el contexto OBO y deja que el pipeline repita pre-flight; no acepta una clasificación previa como prueba de autorización. Así se conserva la protección TOCTOU y la verificación posterior ya existentes. El reporte incluye también los ítems bloqueados.

- *Alternativa: ejecutar directamente los ítems marcados en la primera previsualización.* Descartada: omitiría la revalidación y podría usar autorización obsoleta.

### D9 — Estado de sesión con huella y confirmación de un solo uso

El controlador calcula una huella canónica de la solicitud con tipos e identificadores de principals, tipo e identificadores de objetos y privilegios ordenados. Guarda la previsualización asociada a esa huella y a la identidad del llamante, no al token. Cualquier cambio de formulario o de identidad la invalida.

La confirmación tiene un indicador de procesamiento y se consume antes de iniciar la ejecución; un rerender, doble clic o repetición del evento no vuelve a ejecutar. Después del reporte, repetir la operación exige una nueva previsualización y confirmación.

- *Alternativa: confiar en que Streamlit no repite callbacks.* Descartada: el modelo de rerender y los reintentos de red no constituyen una protección suficiente para operaciones de privilegios.

### D10 — Auditoría con identidad de App; autorización OBO y ejecución broker donde OBO es inviable

Se separan contextos sin mezclar autoridad: la resolución de privilegios, el SQL de grants (Unity Catalog) y la ACL de Databricks Apps usan OBO; la lectura/escritura de ACL del plano de control (warehouses, clusters, serverless compute objects, uso de tokens) se ejecuta con el service principal de la App (modo broker, change `app-broker-identidad-ejecucion`) **solo tras validar la autoridad del llamante**; la escritura de tablas compartidas de auditoría usa la identidad de la App con permisos mínimos sobre el esquema `control_acceso_app`. El campo `usuario` sigue siendo la identidad OBO resuelta.

La inicialización idempotente de persistencia y los escritores de bitácora operan en la App mediante un cliente REST con las credenciales de la App (sentencias DDL e INSERT INTO vía SQL Statement Execution API), sin sesión Spark, conforme a D5 revisado; en los contextos local/lote de C1–C8 los escritores Spark inyectados se conservan sin cambios. El `VerificadorIntegridad` basado en DataFrame queda fuera del camino crítico de la UI. Un agregador de reporte alternativo en Python no reutiliza el contexto de auditoría. Un fallo de bitácora degrada a logs sin ocultar el reporte.

- *Alternativa: escribir bitácoras con cada usuario OBO.* Descartada: obligaría a conceder DDL/escritura en el esquema operativo a todos los usuarios de la UI.
- *Alternativa: ejecutar grants con la App SIN la autorización del llamante.* Descartada: permitiría elevación de privilegios; el modo broker exige validar la autoridad del llamante antes de cada escritura con el SP (change `app-broker-identidad-ejecucion`).

### D11 — Errores seguros y configuración completa

Todos los límites de lote/opciones, nombres de atributos de entorno, identificador lógico de tokens y parámetros de despliegue variables se declaran en `config/app_properties.json` o en `app.yaml`, y se leen mediante `ConfiguracionApp`. Los secretos solo llegan por mecanismos de Databricks Apps.

Controlador y servicios capturan excepciones con `try/except`, registran módulo, contexto y usuario cuando exista, y muestran mensajes de dominio sin stack trace. Antes de visualizar o registrar errores se redactan tokens, headers `Authorization`, `x-forwarded-access-token`, `DATABRICKS_CLIENT_SECRET` y secretos con prefijo `CONTROL_ACCESOS_`. Nunca se serializa el contexto OBO completo.

### D12 — TDD por capas y despliegue progresivo

Las unitarias cubren presentación, huella/estado, cardinalidad, disponibilidad, traducción de descubrimiento, redacción y fábrica con dobles. Las funcionales usan el controlador y, cuando sea útil, `streamlit.testing.v1.AppTest`, con identidad/canales/servicios simulados para recorrer la UI sin workspace.

Las integrales `free` despliegan primero el spike y después la App en `andresFree`, verifican health check, OBO, descubrimiento, split y grants con restauración de ACL/estado. Solo los casos imposibles en Free usan `azure_approval`. Las pruebas de aceptación quedan trazadas 1:1 a los escenarios del delta, incluidos dos llamantes aislados, denegado parcial y N a M. Los resultados se conservan con `--junitxml` bajo `results/web-ui-minimalista/` para C10.

## Risks / Trade-offs

- [Un scope OBO necesario no está disponible para Permissions API, descubrimiento o Spark] → gate temprano D4; detener y elevar la limitación, jamás ejecución con el service principal sin autorización validada del llamante (la ejecución broker es explícita y condicionada, D3/D10).
- [La versión de Connect o Python de la imagen difiere del entorno local] → pin validado en despliegue y runtime sin PySpark local; la suite local conserva su entorno separado (D5).
- [Un usuario no puede listar principals u objetos aunque sí pueda administrar alguno] → error de descubrimiento explícito (D6); no se presenta como ausencia de recursos ni se eleva el listado.
- [La disponibilidad por objeto multiplica consultas y el pipeline vuelve a consultar en pre-flight/verificación] → cache por acción, paginación y límites configurables; se acepta la revalidación por seguridad y no se modifica el verificador de C5.
- [Un cambio de privilegios entre previsualización y confirmación] → revalidación obligatoria en ejecución y reporte de la autorización vigente (D8).
- [Rerender o doble clic repite grants] → huella, indicador de procesamiento y confirmación consumida (D9).
- [Fuga de credenciales entre sesiones o hacia logs] → composición OBO por acción, estado sin credenciales y redacción centralizada (D3/D11).
- [El pre-flight actual exige el privilegio solicitado exacto y puede bloquear a quien posee uno más amplio] → se conserva el contrato aprobado de C3 y se prueba la presentación fiel; cualquier cambio semántico requiere otro change, no una regla paralela en la UI.
- [Auditoría con identidad de App puede confundirse con ejecución elevada] → clientes y sesiones separados, permisos de App limitados a auditoría y `usuario` OBO obligatorio en eventos (D10).
- [Las integrales alteran ACLs compartidas o dejan recursos desplegados] → instantánea/restauración en `finally`, otorgatarios aprobados, limpieza de fixtures y retiro del despliegue de prueba al terminar cuando no sea el entorno persistente aprobado.

## Migration Plan

1. Solicitar al humano autorización e instalación de las nuevas dependencias locales estrictamente necesarias; declarar los archivos runtime/dev sin modificar el entorno mediante la IA.
2. Configurar manualmente la Databricks App, autorización de usuario, scopes, recursos de cómputo y permisos mínimos de auditoría, más el recurso broker ya documentado en el change `app-broker-identidad-ejecucion` (tarea 4.3: rol Workspace admin y entitlements Databricks SQL Access, Workspace Access y Consumer Access del SP); ejecutar el spike D4 y el gate broker.
3. Incorporar de forma aditiva `control_accesos/ui/`, `app.py`, `app.yaml`, configuración y pruebas. No se migran tablas ni se alteran contratos C1–C8.
4. Desplegar primero sin tráfico general, validar health check y un flujo permitido/denegado con restauración, y después habilitar a los usuarios aprobados.
5. Actualizar las instrucciones de ejecución local y despliegue del README con los dos archivos de dependencias, las precondiciones OBO (incluido CAN USE del llamante en un warehouse para el SQL remoto) y el recurso broker del SP.
6. Rollback: retirar `CAN_USE` de la App, detener el despliegue y revertir a la versión previa. Las tablas de auditoría permanecen intactas; los grants de prueba se revocan/restauran. No hay estado de UI persistente que migrar.

## Open Questions

Tras el GO del change broker no quedan preguntas diferibles que cambien specs, arquitectura o desglose. Pendientes ya registrados como tareas, no como preguntas: la verificación cross-cloud en `andresAzureDev` (tarea 2.11, `azure_approval`) y el escritor de bitácora REST (tarea 5.2, D10). Si una superficie adicional resultara inviable en las integrales, se eleva con evidencia en lugar de improvisar otro canal o elevar la identidad sin autorización.
