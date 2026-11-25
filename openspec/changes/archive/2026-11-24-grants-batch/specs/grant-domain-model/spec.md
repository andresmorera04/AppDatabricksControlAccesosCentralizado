# Spec Delta

## MODIFIED Requirements

### Requirement: Solicitud de grant cardinalidad 1 a 1

El sistema SHALL aceptar una solicitud de grant compuesta exactamente por: un principal, uno o más privilegios y un objeto (cardinalidad 1 a 1), unidad interna de ejecución de todo grant. Las cardinalidades 1 a N (un principal y N objetos) y N a 1 (N principals y un objeto) se aceptan como solicitudes por lote (capability `batch-grant-operations`) normalizadas a ítems atómicos 1 a 1. La cardinalidad N a M está fuera de alcance y se rechaza con mensaje explícito antes de cualquier ejecución.

#### Scenario: Solicitud válida

- **WHEN** se crea una solicitud con un principal, dos privilegios y un objeto
- **THEN** el sistema acepta la solicitud y la deja lista para su procesamiento

#### Scenario: Solicitud sin privilegios

- **WHEN** se crea una solicitud cuya lista de privilegios está vacía
- **THEN** el sistema rechaza la solicitud con un error explícito antes de ejecutar cualquier operación

#### Scenario: Solicitud con cardinalidad 1 a N

- **WHEN** se crea una solicitud con un principal, uno o más privilegios y varios objetos
- **THEN** el sistema la acepta como solicitud por lote, lista para su normalización en ítems atómicos 1 a 1

#### Scenario: Solicitud con cardinalidad N a 1

- **WHEN** se crea una solicitud con varios principals, uno o más privilegios y un objeto
- **THEN** el sistema la acepta como solicitud por lote, lista para su normalización en ítems atómicos 1 a 1

#### Scenario: Solicitud con cardinalidad N a M

- **WHEN** se crea una solicitud que involucra varios principals y varios objetos simultáneamente
- **THEN** el sistema rechaza la solicitud con un mensaje explícito que indica que la cardinalidad N a M está fuera de alcance
