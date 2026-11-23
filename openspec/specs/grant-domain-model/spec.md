# grant-domain-model Specification

## Purpose

Define el vocabulario único del sistema de grants: principals, objetos securables tipados por plano (datos/control), privilegios, solicitudes de grant con cardinalidad 1 a 1 y resultados por ítem. Todos los cambios posteriores (C2 a C10) construyen sobre este modelo.

## Requirements

### Requirement: Representación de principals

El sistema SHALL representar a todo principal (entidad que recibe o pierde privilegios) con un identificador único y un tipo que será uno de: usuario, grupo o service principal. Un valor de tipo fuera de esa enumeración será rechazado.

#### Scenario: Principal de usuario válido

- **WHEN** se registra el principal `usuario_demo` con tipo `usuario`
- **THEN** el sistema acepta el principal y lo identifica por su identificador y su tipo

#### Scenario: Tipo de principal no soportado

- **WHEN** se registra un principal con tipo no perteneciente a la enumeración (usuario, grupo, service principal)
- **THEN** el sistema rechaza el principal con un error explícito que indica el tipo recibido y los tipos válidos

#### Scenario: Principal sin identificador

- **WHEN** se registra un principal cuyo identificador está vacío o es nulo
- **THEN** el sistema rechaza el principal con un error explícito

### Requirement: Representación de objetos securables tipados

El sistema SHALL representar a todo objeto securable con: un tipo de objeto de la enumeración soportada por el sistema, su plano (datos o control) derivado del tipo, y su identificación completa (por ejemplo, nombre calificado del objeto). Un tipo de objeto no soportado será rechazado.

#### Scenario: Objeto del plano de datos

- **WHEN** se registra un objeto de tipo `catalogo` (perteneciente al plano de datos)
- **THEN** el sistema acepta el objeto y lo clasifica automáticamente en el plano de datos

#### Scenario: Objeto del plano de control

- **WHEN** se registra un objeto de tipo `sql_warehouse` (perteneciente al plano de control)
- **THEN** el sistema acepta el objeto y lo clasifica automáticamente en el plano de control

#### Scenario: Tipo de objeto no soportado

- **WHEN** se registra un objeto cuyo tipo no pertenece a la enumeración de tipos soportados
- **THEN** el sistema rechaza el objeto con un error explícito que indica el tipo recibido y la lista de tipos soportados

### Requirement: Solicitud de grant cardinalidad 1 a 1

El sistema SHALL aceptar una solicitud de grant compuesta exactamente por: un principal, uno o más privilegios y un objeto. Toda solicitud que no cumpla esa forma (por ejemplo, varios principals y varios objetos a la vez, cardinalidad N a M) será rechazada con un mensaje explícito antes de cualquier ejecución.

#### Scenario: Solicitud válida

- **WHEN** se crea una solicitud con un principal, dos privilegios y un objeto
- **THEN** el sistema acepta la solicitud y la deja lista para su procesamiento

#### Scenario: Solicitud sin privilegios

- **WHEN** se crea una solicitud cuya lista de privilegios está vacía
- **THEN** el sistema rechaza la solicitud con un error explícito antes de ejecutar cualquier operación

#### Scenario: Solicitud con cardinalidad N a M

- **WHEN** se crea una solicitud que involucra varios principals y varios objetos simultáneamente
- **THEN** el sistema rechaza la solicitud con un mensaje explícito que indica que la cardinalidad N a M está fuera de alcance

### Requirement: Resultado por ítem

El sistema SHALL producir un resultado por cada ítem de grant procesado (par principal-privilegio-objeto), con un estado final que será uno de: otorgado, fallido o privilegios insuficientes, junto con el detalle del ítem procesado y, cuando aplique, el detalle del error ocurrido.

#### Scenario: Ítem otorgado

- **WHEN** un ítem de grant se procesa y el canal de ejecución confirma el otorgamiento
- **THEN** el resultado del ítem registra el estado `otorgado` con la referencia completa al principal, privilegio y objeto

#### Scenario: Ítem fallido

- **WHEN** un ítem de grant se procesa y el canal de ejecución reporta un error
- **THEN** el resultado del ítem registra el estado `fallido` con el detalle del error ocurrido

#### Scenario: Ítem con privilegios insuficientes

- **WHEN** un ítem de grant se procesa y el ejecutor carece de privilegios para otorgarlo
- **THEN** el resultado del ítem registra el estado `privilegios_insuficientes` con el detalle de la causa

### Requirement: Normalización de identificadores de objetos

El sistema SHALL normalizar la identificación de un objeto securable de forma que dos referencias al mismo objeto con distinta escritura (por ejemplo, mayúsculas/minúsculas en componentes del nombre calificado) se resuelvan al mismo objeto dentro de una misma solicitud y de sus resultados.

#### Scenario: Dos referencias al mismo catálogo

- **WHEN** una referencia usa `Control` y otra usa `control` para el mismo catálogo dentro del procesamiento de una solicitud
- **THEN** el sistema las trata como el mismo objeto securable en la validación y en el reporte
