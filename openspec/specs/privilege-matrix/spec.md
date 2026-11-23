# privilege-matrix Specification

## Purpose

Matriz declarativa de compatibilidad privilegio x tipo de objeto securable. Es el corazón del dominio: valida solicitudes de grant, filtra las opciones de la UI y genera mensajes de error precisos sobre qué privilegios aplican a cada tipo de objeto.

## Requirements

### Requirement: Cobertura de tipos de objeto soportados

La matriz SHALL declarar, para cada tipo de objeto securable soportado por el sistema, el conjunto de privilegios válidos. Los tipos cubiertos son como mínimo los del plano de datos: catálogo, esquema, tabla delta, streaming table, vista materializada, vista SQL, volumen, modelo de ML, external location y connection; y los del plano de control: cómputo clásico, cómputo serverless, SQL warehouse, Databricks App y uso de personal access token.

#### Scenario: Consulta de privilegios de un tipo de datos

- **WHEN** se consulta la matriz por el tipo `catalogo`
- **THEN** la matriz devuelve el conjunto de privilegios válidos para catálogos (incluyendo al menos `SELECT` y `USE CATALOG`)

#### Scenario: Consulta de privilegios de un tipo de control

- **WHEN** se consulta la matriz por el tipo `sql_warehouse`
- **THEN** la matriz devuelve el conjunto de privilegios válidos para SQL warehouses (incluyendo al menos `CAN_USE`)

#### Scenario: Consulta de un tipo de objeto inexistente en la matriz

- **WHEN** se consulta la matriz por un tipo de objeto que no está declarado
- **THEN** la matriz responde que el tipo no tiene privilegios declarados, sin causar un error del sistema

### Requirement: Validación de compatibilidad privilegio-objeto

Dado un privilegio y un tipo de objeto, la matriz SHALL responder si esa combinación es válida o no. Toda solicitud de grant será validada contra la matriz antes de cualquier ejecución.

#### Scenario: Combinación válida

- **WHEN** se valida el privilegio `SELECT` contra el tipo `tabla_delta`
- **THEN** la matriz responde que la combinación es válida

#### Scenario: Combinación inválida

- **WHEN** se valida el privilegio `CAN_USE` contra el tipo `catalogo`
- **THEN** la matriz responde que la combinación es inválida

### Requirement: Mensajes de error precisos

Cuando una combinación privilegio-tipo de objeto sea inválida, el sistema SHALL generar un mensaje que identifique: el privilegio solicitado, el tipo de objeto y los privilegios válidos alternativos para ese tipo. El mensaje será específico por combinación, no un error genérico de validación.

#### Scenario: Mensaje con alternativas

- **WHEN** se valida el privilegio `CAN_USE` contra el tipo `catalogo` y la combinación es inválida
- **THEN** el mensaje de error menciona el privilegio `CAN_USE`, el tipo `catalogo` y lista los privilegios válidos para catálogos

### Requirement: Filtrado de opciones para la UI

La matriz SHALL poder devolver, para un tipo de objeto dado, la lista de privilegios válidos que una interfaz de usuario puede presentar como opciones seleccionables.

#### Scenario: Obtención de opciones para un tipo

- **WHEN** se solicita la lista de privilegios seleccionables para el tipo `volumen`
- **THEN** la matriz devuelve exactamente los privilegios válidos para volúmenes, sin privilegios de otros tipos

### Requirement: Declarativa y extensible sin modificar el comportamiento

La matriz SHALL estar declarada como dato (no como lógica dispersa en el código), de forma que agregar un nuevo tipo de objeto o privilegio en cambios posteriores no altere el comportamiento de consulta, validación y mensajes descrito en esta capacidad.

#### Scenario: Extensión con un nuevo tipo

- **WHEN** se agrega una nueva entrada tipo de objeto -> privilegios a la declaración de la matriz
- **THEN** las consultas y validaciones existentes siguen comportándose igual y el nuevo tipo responde a consultas y validaciones sin cambios adicionales en la lógica
