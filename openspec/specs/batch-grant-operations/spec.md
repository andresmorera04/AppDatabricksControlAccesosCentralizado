# batch-grant-operations Specification

## Purpose

Otorga privilegios por lote con cardinalidades 1 a N (un principal sobre N objetos) y N a 1 (N principals sobre un objeto), normalizando cada lote a ítems atómicos (principal, privilegio, objeto) que se procesan con resultados parciales independientes, produciendo un reporte consolidado del lote y rechazando explícitamente la cardinalidad N a M.

## Requirements

### Requirement: Normalización de lotes a ítems atómicos

El sistema SHALL normalizar toda solicitud por lote a una lista de ítems atómicos (principal, privilegio, objeto): en la cardinalidad 1 a N un ítem por cada combinación privilegio-objeto del único principal; en la cardinalidad N a 1 un ítem por cada combinación principal-privilegio del único objeto. El orden de los ítems SHALL seguir el orden de entrada de los objetos o de los principals y, dentro de cada uno, el orden de entrada de los privilegios.

#### Scenario: Lote 1 a N normalizado por objeto y privilegio

- **WHEN** se normaliza un lote 1 a N con un principal, dos privilegios y tres objetos
- **THEN** produce seis ítems atómicos, recorriendo los objetos en su orden de entrada y, dentro de cada objeto, los privilegios en su orden de entrada

#### Scenario: Lote N a 1 normalizado por principal y privilegio

- **WHEN** se normaliza un lote N a 1 con tres principals, dos privilegios y un objeto
- **THEN** produce seis ítems atómicos, recorriendo los principals en su orden de entrada y, dentro de cada principal, los privilegios en su orden de entrada

#### Scenario: Lote degenerado equivalente a una solicitud 1 a 1

- **WHEN** se normaliza un lote con un solo principal y un solo objeto
- **THEN** produce los mismos ítems atómicos que la solicitud 1 a 1 equivalente

### Requirement: Validación de la solicitud por lote

El sistema SHALL rechazar, antes de cualquier ejecución, toda solicitud por lote sin principals, sin objetos o sin privilegios, con un error explícito que identifica el conjunto vacío.

#### Scenario: Lote sin principals

- **WHEN** llega una solicitud por lote cuya lista de principals está vacía
- **THEN** el sistema la rechaza con un error explícito que indica que falta al menos un principal, sin generar ítems ni ejecutar fase alguna

#### Scenario: Lote sin objetos

- **WHEN** llega una solicitud por lote cuya lista de objetos está vacía
- **THEN** el sistema la rechaza con un error explícito que indica que falta al menos un objeto, sin generar ítems ni ejecutar fase alguna

#### Scenario: Lote sin privilegios

- **WHEN** llega una solicitud por lote cuya lista de privilegios está vacía
- **THEN** el sistema la rechaza con un error explícito que indica que falta al menos un privilegio, sin generar ítems ni ejecutar fase alguna

### Requirement: Rechazo explícito de cardinalidad N a M

La entrada por lote SHALL rechazar toda solicitud con varios principals y varios objetos a la vez, con un mensaje explícito que declara la cardinalidad N a M fuera de alcance en esta versión, sin generar ítems ni ejecutar fase alguna.

#### Scenario: Solicitud N a M rechazada con mensaje de alcance

- **WHEN** llega a la entrada por lote una solicitud con dos principals y dos objetos
- **THEN** el sistema la rechaza con un mensaje explícito que declara la cardinalidad N a M fuera de alcance y no se genera ningún ítem

### Requirement: Orquestación por lote sobre el pipeline

El lote SHALL procesarse sobre las fases del pipeline existente por ítem: pre-flight con clasificación por ítem (matriz de compatibilidad y privilegios efectivos del llamante), ejecución ítem a ítem por el canal que corresponda al plano de cada objeto, verificación por ítem y reporte. El lote puede mezclar objetos de distintos tipos y de distintos planos.

#### Scenario: Lote con objetos de distinto tipo

- **WHEN** un lote 1 a N incluye un catálogo y una tabla delta
- **THEN** cada ítem se clasifica contra la matriz según su propio tipo de objeto y se ejecuta con la instrucción que le corresponde

#### Scenario: Lote con objetos de distinto plano

- **WHEN** un lote incluye objetos del plano de datos y del plano de control
- **THEN** cada ítem se ejecuta por el canal del plano de su objeto

#### Scenario: Ítem bloqueado en pre-flight dentro de un lote

- **WHEN** en un lote un ítem tiene un privilegio inválido para el tipo de su objeto, o el llamante carece del privilegio autorizador sobre ese objeto
- **THEN** ese ítem se excluye de la ejecución con su motivo y los demás ítems del lote continúan su procesamiento

### Requirement: Resultados parciales por ítem

El sistema SHALL continuar procesando el resto del lote cuando un ítem falla durante la ejecución, es bloqueado en pre-flight o queda sin privilegios suficientes: cada ítem del lote produce su propio resultado final (otorgado, fallido o privilegios_insuficientes) con su detalle, y el lote completo siempre produce su reporte.

#### Scenario: Fallo puntual en un lote 1 a N

- **WHEN** en un lote 1 a N el segundo objeto no existe y los demás sí existen
- **THEN** los ítems de los demás objetos se ejecutan y se reportan, y los ítems del segundo objeto quedan `fallido` con su detalle, sin cancelar el resto del lote

#### Scenario: Bloqueo parcial por privilegios insuficientes

- **WHEN** el llamante puede otorgar sobre un objeto del lote pero no sobre otro
- **THEN** los ítems del primer objeto se procesan y los del segundo se reportan `privilegios_insuficientes`, todos en el mismo reporte del lote

### Requirement: Reporte consolidado del lote

El sistema SHALL producir un reporte consolidado del lote con: el total de ítems del lote, los totales por estado final (otorgado, fallido, privilegios_insuficientes) y el detalle por ítem (principal, privilegio, objeto, estado final y detalle), en el orden de la planificación.

#### Scenario: Totales por estado de un lote mixto

- **WHEN** un lote termina con tres ítems otorgados, dos fallidos y uno con privilegios insuficientes
- **THEN** el reporte consolidado expone un total de seis ítems, los totales por estado tres otorgados, dos fallidos y uno con privilegios insuficientes, y el detalle de cada ítem

#### Scenario: Lote totalmente otorgado

- **WHEN** todos los ítems del lote quedan otorgados
- **THEN** el reporte consolidado expone el total de otorgados igual al total de ítems y cero en los demás estados

### Requirement: Registro en bitácora de cada ítem del lote

Cada ítem del lote SHALL registrarse en la bitácora de eventos con el usuario que lo provoca (identidad on-behalf-of del llamante), su estado final y su detalle cuando aplique, además del evento consolidado del lote.

#### Scenario: Ítems registrados individualmente

- **WHEN** se procesa un lote de cuatro ítems con el llamante autenticado
- **THEN** la bitácora de eventos registra un evento por ítem con el usuario del llamante y el estado final de cada uno, además del evento consolidado del lote

#### Scenario: Ítems registrados sin identidad de llamante

- **WHEN** se procesa un lote sin identidad del llamante
- **THEN** los eventos por ítem se registran igualmente, con el usuario explícitamente sin valor

### Requirement: Pruebas integrales de lotes sobre andresFree

Las pruebas integrales de este change SHALL ejecutar lotes reales únicamente contra el workspace primario `andresFree`, con fixtures autocontenidas (creadas y destruidas por la propia prueba) y revocando todo lo otorgado, de modo que ninguna prueba deje estado residual en el workspace.

#### Scenario: Lote 1 a N real con resultados parciales

- **WHEN** corre la integral de un lote 1 a N que mezcla objetos reales con un objeto inexistente
- **THEN** los grants sobre los objetos existentes quedan vigentes, los ítems del objeto inexistente se reportan `fallido` y la prueba limpia todo lo creado

#### Scenario: Lote N a 1 real con principals existentes

- **WHEN** corre la integral de un lote N a 1 con principals reales del workspace sobre un objeto de prueba
- **THEN** cada grant queda vigente para su principal, la prueba revoca todo lo otorgado y destruye lo creado

#### Scenario: Sin estado residual tras la suite integral

- **WHEN** termina la suite integral de este change
- **THEN** no quedan grants ni objetos residuales en el workspace
