# Spec Delta

## Purpose

Garantiza la persistencia de la aplicación sobre tablas delta idempotentes en el esquema dedicado `control_acceso_app` — creado en el catálogo configurado — con liquid clustering, change data feed, optimizeWrite y autoCompact, y con la integridad de llave primaria, foránea y referencial garantizada desde el código.

## ADDED Requirements

### Requirement: Creación idempotente del esquema dedicado

El sistema SHALL crear el esquema dedicado `control_acceso_app` en el catálogo indicado por la configuración al inicializar la persistencia, de forma idempotente: re-ejecutar la creación SHALL completar sin error y sin alterar el esquema ni los datos existentes.

#### Scenario: Primera creación del esquema

- **WHEN** se inicializa la persistencia y el esquema `control_acceso_app` no existe en el catálogo configurado
- **THEN** el sistema crea el esquema y lo deja disponible para las tablas de la aplicación

#### Scenario: Esquema ya existente

- **WHEN** se inicializa la persistencia y el esquema `control_acceso_app` ya existe
- **THEN** la inicialización completa sin error y sin modificar el esquema ni sus contenidos

#### Scenario: Catálogo inaccesible o inexistente

- **WHEN** se inicializa la persistencia y el catálogo configurado no existe o la identidad no tiene privilegios sobre él
- **THEN** el sistema reporta un error explícito y controlado que indica el catálogo y la causa

### Requirement: Creación idempotente de tablas delta con propiedades del estándar

El sistema SHALL crear cada tabla de la aplicación como tabla delta idempotente (`IF NOT EXISTS`) en el esquema dedicado, con liquid clustering (`CLUSTER BY`), change data feed (`delta.enableChangeDataFeed`), optimizeWrite (`delta.autoOptimize.optimizeWrite`) y autoCompact (`delta.autoOptimize.autoCompact`) habilitados desde su creación.

#### Scenario: Creación inicial de una tabla

- **WHEN** se inicializa la persistencia y una tabla de la aplicación no existe
- **THEN** el sistema la crea como tabla delta con liquid clustering y las propiedades change data feed, optimizeWrite y autoCompact habilitadas

#### Scenario: Re-ejecución sobre tabla existente con datos

- **WHEN** se inicializa la persistencia y las tablas ya existen con datos registrados
- **THEN** la inicialización completa sin error y los datos previos permanecen intactos y consultables

#### Scenario: Verificación de propiedades delta

- **WHEN** se inspeccionan las propiedades de una tabla creada por la aplicación
- **THEN** change data feed, optimizeWrite y autoCompact figuran habilitadas y la tabla declara sus columnas de liquid clustering

### Requirement: Capa de persistencia con escritura masiva

El sistema SHALL ofrecer una capa de persistencia orientada a objetos que escribe en las tablas de la aplicación mediante operaciones masivas de PySpark sobre lotes de registros, sin recorrer filas con ciclos, y SHALL reportar cualquier fallo de escritura como error explícito y controlado.

#### Scenario: Inserción de un lote de registros

- **WHEN** se solicita persistir un lote de registros en una tabla de la aplicación
- **THEN** el sistema inserta el lote completo en una operación masiva y los registros quedan consultables

#### Scenario: Fallo controlado de escritura

- **WHEN** la operación de escritura falla por una causa externa (por ejemplo, tabla inaccesible)
- **THEN** el sistema reporta un error explícito y controlado con el detalle de la causa, sin dejar la operación a medias de forma silenciosa

### Requirement: Integridad de llaves garantizada desde el código

El sistema SHALL verificar desde el código, antes de escribir, la unicidad de la llave primaria dentro del lote y contra la tabla destino, y la existencia de cada referencia de llave foránea en su tabla padre. Toda violación SHALL ser rechazada con un error explícito y ningún registro del lote SHALL ser escrito.

#### Scenario: Llave primaria duplicada contra la tabla destino

- **WHEN** se solicita escribir un registro cuya llave primaria ya existe en la tabla destino
- **THEN** el sistema rechaza la escritura con un error explícito que identifica la llave duplicada y no escribe el lote

#### Scenario: Referencia foránea inexistente

- **WHEN** se solicita escribir un registro cuya llave foránea no existe en la tabla padre referenciada
- **THEN** el sistema rechaza la escritura con un error explícito que identifica la referencia faltante y no escribe el lote

#### Scenario: Lote íntegro

- **WHEN** se solicita escribir un lote que cumple la unicidad de llave primaria y todas sus referencias foráneas
- **THEN** el sistema escribe el lote completo y los registros quedan consultables
