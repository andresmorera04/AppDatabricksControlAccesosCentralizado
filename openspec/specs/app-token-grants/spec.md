# app-token-grants Specification

## Purpose

Habilita el otorgamiento, revocación y verificación de privilegios sobre los dos objetos restantes del plano de control con autorización descentralizada —Databricks Apps (con ACL propio via Permissions API, niveles `CAN_USE` y `CAN_MANAGE`) y el uso de personal access tokens (Token Permissions API, recurso `authorization/tokens`, nivel `CAN_USE`)— completando el inventario de objetos Databricks que la aplicación debe centralizar y cerrando el canal SDK/REST del plano de control sobre el pipeline ya existente en C1–C7.

## Requirements

### Requirement: Cobertura de Databricks Apps y uso de personal access token

El canal SHALL gestionar permisos sobre Databricks Apps (Permissions API, recurso `apps`, niveles `CAN_USE` y `CAN_MANAGE`) y sobre uso de personal access tokens (Token Permissions API, recurso `authorization/tokens`, nivel `CAN_USE`, singleton de workspace). Cualquier tipo ajeno SHALL rechazarse con un error explícito antes de enviar llamada alguna.

#### Scenario: Permiso sobre una Databricks App existente

- **WHEN** un ítem otorga un permiso sobre una Databricks App identificada por su nombre o id con un nivel válido
- **THEN** el canal lo procesa por la Permissions API del recurso `apps` y devuelve su resultado por ítem

#### Scenario: Permiso de uso de personal access token sobre el workspace

- **WHEN** un ítem otorga `CAN_USE` sobre el objeto `USO_TOKEN` del workspace (identificador vacío, recurso singleton)
- **THEN** el canal lo procesa por la Token Permissions API (`authorization/tokens`) y devuelve su resultado por ítem

#### Scenario: Tipo de objeto no soportado por el canal

- **WHEN** el canal recibe un ítem cuyo tipo no es ninguno de `DATABRICK_APP` ni `USO_TOKEN`
- **THEN** el ítem se reporta `fallido` con un mensaje que identifica el tipo recibido y no se envía llamada alguna al workspace

### Requirement: Privilegios válidos por tipo

La matriz SHALL limitar los permisos otorgables a `CAN_USE` y `CAN_MANAGE` sobre Databricks Apps, y a `CAN_USE` sobre el uso de personal access tokens. Un permiso fuera de esa lista SHALL bloquearse antes de cualquier ejecución.

#### Scenario: Niveles de permiso de una Databricks App

- **WHEN** un ítem otorga `CAN_USE` o `CAN_MANAGE` sobre una Databricks App
- **THEN** el ítem es válido para la matriz y llega a la fase de ejecución

#### Scenario: Nivel de permiso del uso de personal access token

- **WHEN** un ítem otorga `CAN_USE` sobre el objeto de uso de tokens
- **THEN** el ítem es válido para la matriz y llega a la fase de ejecución

#### Scenario: Privilegio incompatible con el tipo de objeto

- **WHEN** una solicitud incluye un privilegio inválido para el tipo del objeto (por ejemplo `CAN_RESTART` sobre una Databricks App, o `CAN_MANAGE` sobre `USO_TOKEN`)
- **THEN** el ítem se bloquea en pre-flight con el mensaje preciso de la matriz y no se envía llamada alguna al workspace

### Requirement: Otorgamiento de permiso mediante la Permissions API

Para Databricks Apps el canal SHALL actualizar la ACL del objeto de forma aditiva: el otorgatario recibe el nivel solicitado y las entradas de los demás SHALL conservarse intactas. Para uso de tokens el canal SHALL actualizar la ACL del workspace de forma aditiva sobre el mismo recurso singleton.

#### Scenario: Otorgamiento a un otorgatario sin entrada previa

- **WHEN** un ítem otorga un nivel de permiso a un principal que no figura en la ACL del objeto
- **THEN** la ACL queda actualizada con una entrada para ese principal con el nivel solicitado y las entradas preexistentes se conservan

#### Scenario: Otorgamiento sobre una entrada ya existente

- **WHEN** un ítem otorga un nivel de permiso a un principal que ya figura en la ACL del objeto
- **THEN** la entrada de ese principal queda actualizada al nivel solicitado sin alterar las entradas de otros otorgatarios

#### Scenario: Otorgamiento idempotente

- **WHEN** un ítem otorga a un principal el mismo nivel de permiso que ya tenía vigente
- **THEN** el ítem se reporta `otorgado` y la ACL resultante es equivalente a la previa

### Requirement: Revocación de permiso mediante la Permissions API

Para ambos tipos SHALL revocarse el nivel de permiso del ítem eliminando la entrada del otorgatario indicado y conservando intactas las entradas restantes. Para uso de tokens la revocación opera sobre la ACL singleton del workspace.

#### Scenario: Revocación de un permiso vigente

- **WHEN** se revoca a un principal un nivel de permiso que figura vigente sobre el objeto
- **THEN** la ACL resultante deja de incluir ese permiso para ese principal y conserva el resto de entradas

#### Scenario: Revocación de un permiso que no estaba vigente

- **WHEN** se revoca a un principal un nivel de permiso que no figura en la ACL del objeto
- **THEN** el ítem se reporta como procesado sin alterar otras entradas

### Requirement: Consulta de la ACL vigente del objeto

El canal SHALL leer la ACL vigente y devolverla como una lista de otorgamientos, cada uno con su principal y su nivel tal como el workspace los reporta. Una ACL sin entradas SHALL devolverse como lista vacía, distinguible de un fallo de lectura. Para uso de tokens el identificador del objeto SHALL omitirse o pasarse vacío.

#### Scenario: Entradas de la ACL traducidas a otorgamientos

- **WHEN** la consulta de la ACL devuelve entradas de otorgatarios con sus niveles
- **THEN** cada nivel de cada otorgatario se traduce a un otorgamiento con su principal, su privilegio y el objeto consultado

#### Scenario: ACL sin entradas

- **WHEN** la consulta de la ACL de un objeto devuelve una lista de entradas vacía
- **THEN** el canal devuelve una lista vacía de otorgamientos, sin reportarla como fallo

### Requirement: Verificación posterior al otorgamiento leyendo la ACL

Tras un otorgamiento reportado como exitoso, el sistema SHALL volver a leer la ACL del objeto y confirmar que el nivel de permiso otorgado figura vigente para el principal. Toda discrepancia entre lo ejecutado y lo vigente SHALL reportarse como ítem `fallido` con su detalle.

#### Scenario: Permiso confirmado por la verificación

- **WHEN** la lectura posterior de la ACL reporta el permiso concedido al principal sobre el objeto
- **THEN** el ítem se reporta con estado `otorgado`

#### Scenario: Permiso no confirmado por la verificación

- **WHEN** un otorgamiento reportado como exitoso no aparece en la ACL vigente del objeto
- **THEN** el ítem se reporta `fallido` con un detalle que menciona el privilegio, el principal y el objeto

### Requirement: Errores del canal traducidos por caso

El canal SHALL distinguir las respuestas: permiso denegado al ejecutor como `privilegios_insuficientes`; objeto inexistente, principal inexistente, feature de token permissions no habilitada en el workspace, y cualquier otro fallo como `fallido`, cada uno con un mensaje en español que identifique el caso y los elementos involucrados, sin propagar excepciones al pipeline.

#### Scenario: Permiso denegado al ejecutor

- **WHEN** el workspace responde con permiso denegado al ejecutar la operación con la identidad del llamante
- **THEN** el ítem se reporta `privilegios_insuficientes` con un mensaje que identifica el privilegio y el objeto

#### Scenario: Objeto inexistente

- **WHEN** la operación falla porque el objeto (Databricks App) no existe en el workspace
- **THEN** el ítem se reporta `fallido` con un mensaje que identifica la App inexistente

#### Scenario: Principal inexistente

- **WHEN** la operación falla porque el principal destinatario no existe en el workspace
- **THEN** el ítem se reporta `fallido` con un mensaje que identifica el principal inexistente

#### Scenario: Token permissions no habilitada en el workspace

- **WHEN** el workspace no tiene habilitada la Token Permissions API y se intenta una operación sobre `authorization/tokens`
- **THEN** el ítem se reporta `fallido` con un mensaje específico que identifica la feature no habilitada, sin intentar habilitarla

#### Scenario: Cualquier otro fallo del canal

- **WHEN** la operación falla por una causa distinta (transporte, respuesta inesperada, nivel no reconocido)
- **THEN** el ítem se reporta `fallido` con el detalle del error y sin la marca de privilegios insuficientes

### Requirement: Identidad del llamante y trazabilidad de cada cambio

La autorización SHALL evaluarse siempre con la identidad del llamante y cada cambio SHALL registrarse en la bitácora de eventos con su usuario y desglose por ítem; los fallos SHALL registrarse en la bitácora de errores. La ejecución SHALL usar la credencial del llamante en CLI/lote; en la Databricks App en modo broker (`app-broker-grants`) SHALL poder usar la identidad de la App solo tras validar la autoridad del llamante en la misma acción.

#### Scenario: Evento con el usuario del llamante

- **WHEN** un llamante con identidad resuelta procesa una solicitud del scope de este change
- **THEN** el evento queda registrado en la bitácora de eventos con el usuario del llamante y el resultado por ítem

#### Scenario: Ejecución broker autorizada sobre ACLs y tokens

- **WHEN** la App opera en modo broker y el llamante tiene validada su autoridad sobre la Databricks App o sobre los tokens
- **THEN** la operación se ejecuta con la identidad de la App y el evento registra el usuario OBO del llamante

#### Scenario: Fallo de ejecución registrado

- **WHEN** una operación del canal falla al ejecutarse contra el workspace
- **THEN** el fallo queda registrado en la bitácora de errores con el detalle del error y el contexto de la operación

#### Scenario: La auditoría no introduce fallos en cascada

- **WHEN** el registro en la bitácora de errores falla mientras se reporta un fallo de ejecución
- **THEN** el ítem conserva su resultado por ítem traducido y el pipeline no recibe excepción alguna del registro

### Requirement: Alcance del canal: apps existentes y tokens del workspace

El canal SHALL limitarse a los permisos de Databricks Apps ya existentes y a los permisos de uso de tokens del workspace actual: la app no SHALL crear, renombrar ni eliminar Databricks Apps, ni activar features del workspace (la activación de Token Permissions API y de cualquier otra previa es manual y queda fuera de la app). Las pruebas integrales que no apliquen al workspace de Free Edition se SHALL marcar con skip justificado.

#### Scenario: Apps tratadas solo como objetivo de permisos

- **WHEN** se procesa una solicitud sobre una Databricks App
- **THEN** el canal modifica únicamente su ACL, sin intentar crear, renombrar ni eliminar la App

#### Scenario: Activación de features fuera de la app

- **WHEN** el workspace no tiene habilitada la Token Permissions API (o cualquier feature previa requerida)
- **THEN** el canal reporta el fallo de la operación con su detalle, sin intentar habilitar la feature

#### Scenario: Uso de tokens fuera de Free Edition

- **WHEN** las pruebas integrales de uso de tokens no pueden ejecutarse contra `andresFree`
- **THEN** esas pruebas se marcan con un skip explícito que documenta la limitación y el resto de la suite sigue ejecutándose

### Requirement: Credenciales y destino inyectados, sin valores embebidos

El canal SHALL recibir por inyección el acceso al workspace (cliente o transporte y credencial de ejecución), sin valores de conexión, identificadores ni niveles de permiso embebidos en el código. La credencial de ejecución SHALL ser la del llamante en la ruta CLI/lote y la de la App en el modo broker, siempre con la autorización del llamante validada previamente. Con un transporte simulado el canal SHALL poder ejercitarse por completo sin conexión externa.

#### Scenario: Canal ejercitado sin workspace alguno

- **WHEN** el canal se construye con un transporte simulado
- **THEN** el otorgamiento, la revocación y la lectura de la ACL se procesan y reportan sin ninguna conexión externa

#### Scenario: Operación enviada al transporte inyectado

- **WHEN** el canal ejecuta el otorgamiento de un ítem
- **THEN** la operación se envía al transporte inyectado con el recurso, el identificador del objeto y el nivel derivados del ítem (con identificador vacío para uso de tokens)

### Requirement: Cardinalidades y resultados parciales sobre estos objetos

El pipeline SHALL procesar sobre Databricks Apps y uso de tokens las cardinalidades 1 a 1, 1 a N y N a 1, reutilizando la normalización de lotes y el pre-flight ya existentes. Un fallo puntual SHALL quedar en el resultado de su ítem sin abortar los demás, y la cardinalidad N a M SHALL rechazarse antes de ejecutar.

#### Scenario: Lote 1 a N sobre varias Databricks Apps

- **WHEN** un principal solicita permisos sobre varias Databricks Apps en un solo lote
- **THEN** el lote se normaliza a ítems atómicos, cada uno se ejecuta y se verifica por separado y el reporte entrega un resultado por ítem

#### Scenario: Lote N a 1 sobre uso de tokens

- **WHEN** varios principals reciben `CAN_USE` sobre el objeto `USO_TOKEN` del workspace en un solo lote
- **THEN** el lote se normaliza a ítems atómicos, cada uno se ejecuta y se verifica por separado y el reporte entrega un resultado por ítem

#### Scenario: Fallo puntual no aborta el lote

- **WHEN** de varios ítems ejecutables de un lote uno falla durante la ejecución real
- **THEN** los demás ítems se ejecutan y se reportan, y el fallo queda en su resultado por ítem sin cancelar el resto

#### Scenario: Cardinalidad N a M rechazada

- **WHEN** una solicitud incluye varios principals y varias Databricks Apps a la vez
- **THEN** la solicitud se rechaza con un mensaje explícito de fuera de alcance y no se envía llamada alguna al workspace

### Requirement: Pruebas por entorno con restauración del estado original

Las pruebas integrales SHALL ejecutarse en `andresFree` para lo disponible (Databricks Apps si la edición la soporta; uso de tokens si la Token Permissions API está habilitada) y en `andresAzureDev` bajo el marker `azure_approval` para lo que Free Edition no permita. Toda prueba que toque una ACL SHALL restaurar el estado original del objeto y revocar lo otorgado.

#### Scenario: ACL restaurada tras la prueba

- **WHEN** una prueba integral otorga y revoca permisos sobre una Databricks App o sobre la ACL singleton del workspace
- **THEN** al finalizar, la ACL queda equivalente a la que tenía antes de la prueba y no quedan permisos residuales del otorgatario de pruebas

#### Scenario: Integrales en `andresAzureDev` con pre-aprobación

- **WHEN** se ejecutan las pruebas integrales que Free Edition no soporta
- **THEN** esas pruebas se ejecutan únicamente contra `andresAzureDev` con el marker `azure_approval` y quedan excluidas de la suite por defecto

#### Scenario: Feature no disponible en el workspace

- **WHEN** el workspace de pruebas no ofrece la Token Permissions API o no expone el control de acceso sobre el tipo probado
- **THEN** las integrales de ese tipo se marcan con skip explícito que documenta la limitación y el resto de la suite sigue ejecutándose
