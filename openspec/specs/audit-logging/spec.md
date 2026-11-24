# audit-logging Specification

## Purpose

Registra en tablas delta toda la actividad de la aplicación (bitácora de eventos generales, con el usuario que provoca cada evento) y todo error controlado vía try/except (bitácora de errores, con el detalle del error en un campo estructurado tipo `STRUCT<...>`).

## Requirements

### Requirement: Registro de eventos generales con usuario

El sistema SHALL registrar en la tabla `bitacora_eventos` cada evento relevante de la aplicación, incluyendo como mínimo: identificador del evento, marca de tiempo, usuario que provoca el evento, acción realizada, detalle y resultado. El usuario SHALL provenir de la identidad on-behalf-of cuando esté disponible (change `auth-caller-obo`) y SHALL quedar explícitamente sin usuario cuando aún no lo esté.

#### Scenario: Evento con usuario identificado

- **WHEN** ocurre un evento de la aplicación provocado por un usuario cuya identidad on-behalf-of está disponible
- **THEN** el sistema registra el evento con ese usuario, la acción, el detalle, el resultado y su marca de tiempo

#### Scenario: Evento sin identidad de usuario disponible

- **WHEN** ocurre un evento de la aplicación antes de que exista identidad on-behalf-of
- **THEN** el sistema registra el evento con el campo de usuario explícitamente sin valor de usuario, sin rechazar el evento

#### Scenario: Actividad completa consultable

- **WHEN** se consulta la bitácora de eventos tras varias acciones de la aplicación
- **THEN** cada acción figura como un evento con su usuario, acción, detalle, resultado y marca de tiempo ordenables cronológicamente

### Requirement: Registro de errores con detalle estructurado

El sistema SHALL registrar en la tabla `bitacora_errores` todo error controlado mediante try/except, con el máximo detalle disponible; el detalle del error SHALL almacenarse en un campo de tipo `STRUCT<...>` que incluya al menos: tipo de excepción, mensaje, traza y contexto de la operación que falló.

#### Scenario: Error controlado registrado con detalle estructurado

- **WHEN** una operación de la aplicación falla y el error es capturado por try/except
- **THEN** el sistema registra el error en la bitácora de errores con el detalle STRUCT poblado con tipo de excepción, mensaje, traza y contexto

#### Scenario: Detalle del error consultable por campos

- **WHEN** se consulta el detalle de un error registrado
- **THEN** cada componente del STRUCT (tipo de excepción, mensaje, traza, contexto) es accesible de forma independiente

### Requirement: Bitácoras como tablas delta del esquema dedicado

Las bitácoras de eventos y de errores SHALL ser tablas delta del esquema dedicado `control_acceso_app`, creadas idempotentemente con liquid clustering, change data feed, optimizeWrite y autoCompact, y SHALL escribirse a través de la capa de persistencia con operaciones masivas de PySpark.

#### Scenario: Creación idempotente de las bitácoras

- **WHEN** se inicializa la persistencia y las tablas de bitácora ya existen
- **THEN** la inicialización completa sin error y los registros históricos permanecen intactos

#### Scenario: Escritura masiva de eventos

- **WHEN** se solicita registrar un lote de varios eventos
- **THEN** el sistema los escribe en una operación masiva, sin ciclos por fila

### Requirement: Degradación controlada ante fallo de la propia bitácora

Cuando la escritura de una bitácora falle por una causa externa, el sistema SHALL reportar el fallo de forma controlada y visible (salida local) sin propagar una excepción no controlada que interrumpa la operación principal ni provoque registros recursivos.

#### Scenario: Fallo al escribir la bitácora de errores

- **WHEN** el registro de un error en la bitácora de errores falla por causa externa
- **THEN** el sistema deja constancia visible del fallo en la salida local y la ejecución continúa sin excepción no controlada ni reintentos recursivos
