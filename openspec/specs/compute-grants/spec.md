# compute-grants Specification

## Purpose

Otorga, revoca y verifica permisos sobre los objetos de cómputo del plano de control (clusters clásicos all-purpose, serverless compute objects interactivos y automated, y SQL warehouses) mediante la Permissions API, completando el canal SDK/REST del plano de control sobre el pipeline ya existente.

## Requirements

### Requirement: Cobertura de los tipos de cómputo del plano de control

El canal del plano de control SHALL gestionar permisos sobre los clusters clásicos all-purpose, los serverless compute objects (interactivo y automated, tanto los objetos *default* como los objetos custom ya existentes) y los SQL warehouses. Cualquier tipo de objeto ajeno a esos tres SHALL rechazarse con un error explícito antes de enviar llamada alguna al workspace.

#### Scenario: Permiso sobre un cluster clásico

- **WHEN** un ítem otorga un permiso sobre un cluster clásico identificado por su id
- **THEN** el canal lo procesa por la Permissions API del recurso de clusters y devuelve su resultado por ítem

#### Scenario: Permiso sobre un serverless compute object

- **WHEN** un ítem otorga un permiso sobre un serverless compute object identificado por su id, ya sea un objeto *default* o uno custom existente
- **THEN** el canal lo procesa por la Permissions API del recurso de cómputo serverless

#### Scenario: Permiso sobre un SQL warehouse

- **WHEN** un ítem otorga un permiso sobre un SQL warehouse identificado por su id
- **THEN** el canal lo procesa por la Permissions API del recurso de SQL warehouses

#### Scenario: Tipo de objeto no soportado por el canal

- **WHEN** el canal recibe un ítem cuyo tipo de objeto no es ninguno de los tres tipos de cómputo soportados
- **THEN** el ítem se reporta `fallido` con un mensaje que identifica el tipo recibido y no se envía llamada alguna al workspace

### Requirement: Privilegios válidos por tipo de cómputo

La matriz de compatibilidad SHALL limitar los permisos otorgables a: `CAN_ATTACH_TO`, `CAN_RESTART` y `CAN_MANAGE` en clusters clásicos; `CAN_USE` y `CAN_MANAGE` en serverless compute objects; `CAN_USE`, `CAN_MONITOR` y `CAN_MANAGE` en SQL warehouses. Un permiso fuera de esa lista SHALL bloquearse antes de cualquier ejecución.

#### Scenario: Niveles de permiso de un cluster clásico

- **WHEN** un ítem otorga `CAN_ATTACH_TO`, `CAN_RESTART` o `CAN_MANAGE` sobre un cluster clásico
- **THEN** el ítem es válido para la matriz y llega a la fase de ejecución

#### Scenario: Niveles de permiso del cómputo serverless

- **WHEN** un ítem otorga `CAN_USE` o `CAN_MANAGE` sobre un serverless compute object
- **THEN** el ítem es válido para la matriz y llega a la fase de ejecución

#### Scenario: Niveles de permiso de un SQL warehouse

- **WHEN** un ítem otorga `CAN_USE`, `CAN_MONITOR` o `CAN_MANAGE` sobre un SQL warehouse
- **THEN** el ítem es válido para la matriz y llega a la fase de ejecución

#### Scenario: Privilegio incompatible con el tipo de objeto

- **WHEN** una solicitud incluye un privilegio inválido para el tipo de cómputo del objeto (por ejemplo `SELECT` sobre un cluster, o `CAN_RESTART` sobre un SQL warehouse)
- **THEN** el ítem se bloquea en pre-flight con el mensaje preciso de la matriz y no se envía llamada alguna al workspace

### Requirement: Otorgamiento de permiso mediante la Permissions API

El canal SHALL otorgar el nivel de permiso del ítem actualizando la ACL del objeto de forma aditiva: el otorgatario recibe el nivel solicitado y las entradas de los demás otorgatarios del objeto SHALL conservarse intactas. El resultado por ítem SHALL devolverse sin propagar excepciones al pipeline.

#### Scenario: Otorgamiento a un otorgatario sin entrada previa

- **WHEN** un ítem otorga un nivel de permiso a un principal que no figura en la ACL del objeto
- **THEN** la ACL queda actualizada con una entrada para ese principal con el nivel solicitado y las entradas preexistentes se conservan

#### Scenario: Otorgamiento sobre una entrada ya existente

- **WHEN** un ítem otorga un nivel de permiso a un principal que ya figura en la ACL del objeto
- **THEN** la entrada de ese principal queda actualizada al nivel solicitado sin alterar las entradas de otros otorgatarios

#### Scenario: Otorgamiento idempotente

- **WHEN** un ítem otorga a un principal el mismo nivel de permiso que ya tenía vigente sobre el objeto
- **THEN** el ítem se reporta `otorgado` y la ACL resultante es equivalente a la previa

### Requirement: Revocación de permiso mediante la Permissions API

El canal SHALL revocar el nivel de permiso del ítem sobre el objeto, eliminando ese permiso del otorgatario indicado y conservando intactas las entradas de los demás otorgatarios. Tras la revocación, la consulta de la ACL SHALL dejar de reportar ese permiso para ese principal.

#### Scenario: Revocación de un permiso vigente

- **WHEN** se revoca a un principal un nivel de permiso que figura vigente sobre un objeto de cómputo
- **THEN** la ACL resultante deja de incluir ese permiso para ese principal y conserva el resto de entradas

#### Scenario: Revocación de un permiso que no estaba vigente

- **WHEN** se revoca a un principal un nivel de permiso que no figura en la ACL del objeto
- **THEN** el ítem se reporta como procesado sin alterar las entradas de otros otorgatarios

### Requirement: Consulta de la ACL vigente del objeto

El canal SHALL leer la ACL vigente de un objeto de cómputo y devolverla como una lista de otorgamientos, cada uno con su principal y su nivel de permiso tal como el workspace los reporta. Una ACL sin entradas SHALL devolverse como lista vacía, distinguible de un fallo de lectura.

#### Scenario: Entradas de la ACL traducidas a otorgamientos

- **WHEN** la consulta de la ACL devuelve entradas de otorgatarios con sus niveles de permiso
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

El canal SHALL distinguir las respuestas de error del workspace: permiso denegado al ejecutor como `privilegios_insuficientes`; objeto inexistente, principal inexistente y cualquier otro fallo como `fallido`, cada uno con un mensaje en español que identifique el caso y los elementos involucrados, sin propagar excepciones al pipeline.

#### Scenario: Permiso denegado al ejecutor

- **WHEN** el workspace responde con permiso denegado al ejecutar la operación con la identidad del llamante
- **THEN** el ítem se reporta `privilegios_insuficientes` con un mensaje que identifica el privilegio y el objeto, dejando constancia de que el llamante no puede otorgarlo

#### Scenario: Objeto de cómputo inexistente

- **WHEN** la operación falla porque el objeto identificado por su id no existe en el workspace
- **THEN** el ítem se reporta `fallido` con un mensaje que identifica el objeto inexistente

#### Scenario: Principal inexistente

- **WHEN** la operación falla porque el principal destinatario no existe en el workspace
- **THEN** el ítem se reporta `fallido` con un mensaje que identifica el principal inexistente

#### Scenario: Cualquier otro fallo del canal

- **WHEN** la operación falla por una causa distinta (transporte, respuesta inesperada, permiso no reconocido)
- **THEN** el ítem se reporta `fallido` con el detalle del error y sin la marca de privilegios insuficientes

### Requirement: Identidad del llamante y trazabilidad de cada cambio

Cada operación sobre la ACL SHALL ejecutarse con la credencial del llamante que provoca la solicitud, y cada cambio de permiso SHALL quedar registrado en la bitácora de eventos con el usuario que lo provoca y su desglose por ítem. Los fallos de ejecución SHALL registrarse en la bitácora de errores con su detalle.

#### Scenario: Evento con el usuario del llamante

- **WHEN** un llamante con identidad resuelta procesa una solicitud sobre un objeto de cómputo
- **THEN** el evento queda registrado en la bitácora de eventos con el usuario del llamante y el resultado por ítem

#### Scenario: Fallo de ejecución registrado

- **WHEN** una operación del canal falla al ejecutarse contra el workspace
- **THEN** el fallo queda registrado en la bitácora de errores con el detalle del error y el contexto de la operación

#### Scenario: La auditoría no introduce fallos en cascada

- **WHEN** el registro en la bitácora de errores falla mientras se reporta un fallo de ejecución
- **THEN** el ítem conserva su resultado por ítem traducido y el pipeline no recibe excepción alguna del registro

### Requirement: Alcance del control del cómputo serverless

La gestión serverless SHALL limitarse a los permisos de los serverless compute objects ya existentes: la app no SHALL crear, renombrar ni eliminar los objetos *default*, ni activar el feature del workspace, cuya activación es manual y queda fuera de la app. El control serverless no SHALL cubrir DBSQL, Model Serving ni Databricks Apps.

#### Scenario: Objetos default tratados solo como objetivo de permisos

- **WHEN** se procesa una solicitud sobre un serverless compute object *default*
- **THEN** el canal modifica únicamente su ACL, sin intentar crear, renombrar ni eliminar el objeto

#### Scenario: Activación del feature fuera de la app

- **WHEN** el workspace no tiene habilitado el control de acceso del cómputo serverless
- **THEN** el canal reporta el fallo de la operación con su detalle, sin intentar habilitar el feature

### Requirement: Credenciales y destino inyectados, sin valores embebidos

El canal SHALL recibir por inyección el acceso al workspace (cliente o transporte y credencial del llamante), sin valores de conexión, identificadores de objeto ni niveles de permiso embebidos en el código. Con un transporte simulado, el canal SHALL poder ejercitarse por completo sin conexión externa.

#### Scenario: Canal ejercitado sin workspace alguno

- **WHEN** el canal se construye con un transporte simulado
- **THEN** el otorgamiento, la revocación y la lectura de la ACL se procesan y se reportan sin ninguna conexión externa

#### Scenario: Operación enviada al transporte inyectado

- **WHEN** el canal ejecuta el otorgamiento de un ítem
- **THEN** la operación se envía al transporte inyectado con el recurso, el objeto y el otorgatario derivados del ítem

### Requirement: Cardinalidades y resultados parciales sobre objetos de cómputo

El pipeline SHALL procesar sobre objetos de cómputo las cardinalidades 1 a 1, 1 a N y N a 1, reutilizando la normalización de lotes a ítems atómicos y el pre-flight ya existentes. Un fallo puntual SHALL quedar en el resultado de su ítem sin abortar los demás, y la cardinalidad N a M SHALL rechazarse antes de ejecutar.

#### Scenario: Lote 1 a N sobre varios objetos de cómputo

- **WHEN** un principal solicita permisos sobre varios objetos de cómputo en un solo lote
- **THEN** el lote se normaliza a ítems atómicos, cada uno se ejecuta y se verifica por separado y el reporte entrega un resultado por ítem

#### Scenario: Fallo puntual no aborta el lote

- **WHEN** de varios ítems ejecutables de un lote uno falla durante la ejecución real
- **THEN** los demás ítems se ejecutan y se reportan, y el fallo queda en su resultado por ítem sin cancelar el resto

#### Scenario: Cardinalidad N a M rechazada

- **WHEN** una solicitud incluye varios principals y varios objetos de cómputo a la vez
- **THEN** la solicitud se rechaza con un mensaje explícito de fuera de alcance y no se envía llamada alguna al workspace

### Requirement: Pruebas por entorno con restauración del estado original

Las pruebas integrales SHALL ejecutarse en `andresFree` para lo disponible en Free Edition (SQL warehouses y, si el feature está disponible, cómputo serverless) y en `andresAzureDev` bajo el marker `azure_approval` para los clusters clásicos. Toda prueba que toque una ACL SHALL restaurar el estado original del objeto y revocar lo otorgado.

#### Scenario: ACL restaurada tras la prueba

- **WHEN** una prueba integral otorga y revoca permisos sobre un objeto de cómputo
- **THEN** al finalizar, la ACL del objeto queda equivalente a la que tenía antes de la prueba y no quedan permisos residuales del otorgatario de pruebas

#### Scenario: Cómputo clásico fuera de Free Edition

- **WHEN** se ejecutan las pruebas integrales de clusters clásicos
- **THEN** esas pruebas se ejecutan únicamente contra `andresAzureDev` con el marker `azure_approval` y quedan excluidas de la suite por defecto

#### Scenario: Feature serverless no disponible en el workspace

- **WHEN** el workspace de pruebas no ofrece el control de acceso del cómputo serverless
- **THEN** las pruebas integrales de ese tipo se marcan con un skip explícito que documenta la limitación y el resto de la suite sigue ejecutándose

#### Scenario: Permiso denegado con identidad ejecutora restringida

- **WHEN** una integral ejecuta un otorgamiento contra `andresFree` autenticada como un service principal sin privilegios administrativos sobre el objeto
- **THEN** el ítem se reporta `privilegios_insuficientes` con el mensaje de permiso denegado, sin alterar la ACL del objeto
