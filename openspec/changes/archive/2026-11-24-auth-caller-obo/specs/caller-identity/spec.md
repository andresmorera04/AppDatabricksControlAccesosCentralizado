# Spec Delta

## Purpose

Resuelve, a partir del contexto on-behalf-of de la Databricks App, quién es el llamante que invoca la aplicación: un principal del dominio (usuario, grupo o service principal identificado por su App Id) y los grupos de los que es miembro, para que la resolución de privilegios y la bitácora de eventos consuman una única identidad.

## ADDED Requirements

### Requirement: Identificación del llamante vía on-behalf-of

La Databricks App SHALL autenticar al llamante mediante el flujo OAuth on-behalf-of de Databricks Apps y SHALL obtener su identidad a partir del contexto de usuario que la plataforma entrega en cada invocación. El mecanismo concreto de obtención de la identidad SHALL quedar detrás de un puerto inyectable, de modo que la app pueda usar el contexto real en producción y uno simulado en las pruebas.

#### Scenario: Llamante autenticado

- **WHEN** la app recibe una invocación con un contexto de usuario on-behalf-of válido
- **THEN** el sistema resuelve y expone la identidad del llamante correspondiente a ese contexto

#### Scenario: Contexto de llamante ausente

- **WHEN** la app recibe una invocación sin contexto de usuario válido (por ejemplo, una llamada de servicio no autenticada)
- **THEN** el sistema deja la identidad del llamante explícitamente sin resolver y registra el fallo de forma controlada, sin propagar una excepción no controlada

### Requirement: El llamante se representa como un principal del dominio

El sistema SHALL representar la identidad del llamante como un principal del dominio, con un tipo tomado de la enumeración de principales (`usuario`, `grupo` o `service_principal`) y su correspondiente identificador. Cuando el llamante sea un service principal, su identificación SHALL incluir el App Id con el que el sistema de governance reporta sus otorgamientos.

#### Scenario: Llamante usuario

- **WHEN** el contexto on-behalf-of corresponde a un usuario de Databricks
- **THEN** el sistema expone la identidad con tipo `usuario` y su identificador de usuario

#### Scenario: Llamante service principal con App Id

- **WHEN** la app se ejecuta con la identidad de su propio service principal
- **THEN** el sistema expone la identidad con tipo `service_principal`, su App Id y su nombre

#### Scenario: Llamante grupo

- **WHEN** el llamante autenticado corresponde a un grupo
- **THEN** el sistema expone la identidad con tipo `grupo` y su identificador

### Requirement: Los service principals son principales independientes

Un service principal SHALL tratarse como un principal distinto de usuarios y grupos: el sistema SHALL NO atribuir a un usuario la identidad ni los privilegios de un service principal, ni viceversa.

#### Scenario: Service principal distinto del usuario llamante

- **WHEN** el llamante autenticado es un usuario y el workspace tiene service principals registrados con otorgamientos propios
- **THEN** el sistema no atribuye al usuario la identidad ni los privilegios de ninguno de esos service principals

### Requirement: Resolución de grupos del llamante

El sistema SHALL resolver, a partir de la identidad del llamante, los grupos de los que es miembro directo. La ausencia de grupos SHALL ser distinguible de un fallo en su resolución.

#### Scenario: Llamante con grupos

- **WHEN** se resuelven los grupos de un llamante con varios grupos asociados
- **THEN** el sistema devuelve la lista completa de grupos, cada uno con su nombre y su identificador

#### Scenario: Llamante sin grupos

- **WHEN** se resuelven los grupos de un llamante sin membresías
- **THEN** el sistema devuelve una lista explícitamente vacía, distinguible de un fallo de resolución

### Requirement: Referencias de identidad para el emparejamiento de otorgamientos

El sistema SHALL exponer, para la identidad resuelta, el conjunto completo de referencias con las que el sistema de governance identifica a un otorgatario: el propio identificador del llamante, su nombre o correo cuando exista, los identificadores y nombres de sus grupos y, tratándose de un service principal, su App Id y su nombre. Estas referencias SHALL ser el insumo único para decidir si un otorgamiento vigente corresponde al llamante.

#### Scenario: Referencias de un usuario con grupos

- **WHEN** se solicitan las referencias de identidad de un usuario miembro de dos grupos
- **THEN** el sistema devuelve el identificador y el nombre del usuario junto con el identificador y el nombre de cada uno de sus grupos

#### Scenario: Referencias de un service principal

- **WHEN** se solicitan las referencias de identidad de un service principal
- **THEN** el sistema incluye su App Id y su nombre, además de los identificadores y nombres de sus grupos

### Requirement: Identidad del llamante disponible para la bitácora de eventos

El sistema SHALL exponer la identidad resuelta a través de una única interfaz, de modo que la bitácora de eventos alimente su campo `usuario` con esa identidad y, cuando no exista llamante autenticado, registre el evento con el campo `usuario` explícitamente sin valor sin rechazarlo.

#### Scenario: Bitácora registra usuario del llamante

- **WHEN** ocurre un evento de la aplicación con una identidad OBO resuelta
- **THEN** la bitácora registra el evento con el identificador del llamante en el campo `usuario`

#### Scenario: Bitácora registra evento sin usuario

- **WHEN** ocurre un evento de la aplicación sin identidad OBO resuelta
- **THEN** la bitácora registra el evento con el campo `usuario` explícitamente sin valor, sin rechazarlo

### Requirement: Errores de autenticación visibles y controlados

Cuando la autenticación o la resolución de identidad fallen por una causa externa (token inválido o expirado, identificador vacío, servicio no disponible), el sistema SHALL capturar el error, registrarlo en la bitácora de errores con el detalle estructurado correspondiente y continuar sin propagar una excepción no controlada que interrumpa la operación principal.

#### Scenario: Token de usuario inválido o ausente

- **WHEN** la app recibe una invocación con un token de usuario ausente, expirado o no verificable
- **THEN** el sistema registra el error en la bitácora de errores y deja la identidad del llamante sin resolver

#### Scenario: Identificador del llamante vacío

- **WHEN** el contexto on-behalf-of devuelve un identificador de usuario vacío o nulo
- **THEN** el sistema registra el error en la bitácora de errores y deja la identidad del llamante explícitamente sin resolver
