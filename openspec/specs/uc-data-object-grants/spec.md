# uc-data-object-grants Specification

## Purpose

Otorga y verifica privilegios 1 a 1 sobre los objetos del plano de datos de Unity Catalog (catálogos, esquemas, tablas delta, streaming tables, vistas materializadas, vistas SQL, volúmenes y modelos ML) mediante el canal SQL GRANT/REVOKE, completando la primera vertical slice de punta a punta del pipeline sobre un workspace real.

## Requirements

### Requirement: Instrucción de otorgamiento por tipo de objeto

Para cada ítem cuyo objeto pertenezca al plano de datos y esté soportado en este change, el sistema SHALL construir una instrucción `GRANT` completamente en mayúsculas que otorgue el privilegio del ítem al principal sobre el objeto, usando la palabra clave SQL que corresponde al tipo de objeto (`CATALOG`, `SCHEMA`, `TABLE`, `VOLUME`, `MODEL`) e identificando al principal por su identificador.

#### Scenario: Grant sobre un catálogo

- **WHEN** un ítem otorga un privilegio sobre un catálogo identificado por su nombre simple
- **THEN** la instrucción construida usa la palabra clave `CATALOG` con ese nombre simple

#### Scenario: Grant sobre un esquema calificado

- **WHEN** un ítem otorga un privilegio sobre un esquema identificado como `catalogo.esquema`
- **THEN** la instrucción construida usa la palabra clave `SCHEMA` y conserva las dos partes del nombre calificado

#### Scenario: Grant sobre una tabla delta calificada

- **WHEN** un ítem otorga un privilegio sobre una tabla delta identificada como `catalogo.esquema.tabla`
- **THEN** la instrucción construida usa la palabra clave `TABLE` y conserva las tres partes del nombre calificado

#### Scenario: Grant sobre un volumen

- **WHEN** un ítem otorga un privilegio sobre un volumen
- **THEN** la instrucción construida usa la palabra clave `VOLUME`

#### Scenario: Grant sobre un modelo de ML

- **WHEN** un ítem otorga un privilegio sobre un modelo de ML (registered model)
- **THEN** la instrucción construida usa la palabra clave `MODEL`

#### Scenario: Streaming table, vista materializada y vista SQL comparten la palabra clave de tabla

- **WHEN** un ítem otorga un privilegio sobre una streaming table, una vista materializada o una vista SQL
- **THEN** la instrucción construida usa la misma palabra clave `TABLE` que una tabla delta

### Requirement: Instrucción de revocación por tipo de objeto

El sistema SHALL construir la instrucción `REVOKE` en mayúsculas equivalente a la de otorgamiento, con el mismo mapeo de palabra clave SQL por tipo de objeto, para quitar a un principal un privilegio sobre un objeto del plano de datos soportado.

#### Scenario: Revocación sobre una tabla delta

- **WHEN** se revoca a un principal un privilegio sobre una tabla delta
- **THEN** la instrucción construida revoca el privilegio con la palabra clave `TABLE`, el nombre calificado de la tabla y el principal indicado

### Requirement: Ejecución de instrucciones por una sesión SQL inyectada

El canal SQL SHALL ejecutar cada instrucción construida a través de una sesión SQL inyectada, sin valores de conexión embebidos en el código: la sesión del entorno en producción y una sesión simulada en las pruebas funcionales. El canal SHALL devolver siempre un resultado por ítem, sin propagar excepciones al pipeline.

#### Scenario: Instrucción enviada a la sesión inyectada

- **WHEN** el canal ejecuta el otorgamiento de un ítem
- **THEN** la instrucción construida se envía tal cual a la sesión inyectada

#### Scenario: Canal ejercitado sin workspace alguno

- **WHEN** el canal se construye con una sesión simulada
- **THEN** el otorgamiento y la revocación se procesan y se reportan sin ninguna conexión externa

### Requirement: Errores del workspace traducidos a mensajes específicos por caso

El canal SQL SHALL distinguir los fallos del workspace y reportarlos con mensaje específico en español: permiso denegado al ejecutor como `privilegios_insuficientes`; objeto inexistente, principal inexistente y cualquier otro fallo de la sesión como `fallido`, cada uno con un mensaje que identifica el caso y los elementos involucrados.

#### Scenario: Permiso denegado al otorgar

- **WHEN** el workspace responde con permiso denegado al ejecutar la instrucción del llamante
- **THEN** el ítem se reporta con estado `privilegios_insuficientes` y un mensaje que identifica el privilegio y el objeto, y deja constancia de que el llamante no puede otorgarlo

#### Scenario: Objeto inexistente

- **WHEN** la instrucción falla porque el objeto no existe en el metastore
- **THEN** el ítem se reporta `fallido` con un mensaje que identifica el objeto inexistente

#### Scenario: Principal inexistente

- **WHEN** la instrucción falla porque el principal no existe en el workspace
- **THEN** el ítem se reporta `fallido` con un mensaje que identifica el principal inexistente

#### Scenario: Cualquier otro fallo de la sesión

- **WHEN** la sesión falla por una causa distinta (transporte, sentencia rechazada)
- **THEN** el ítem se reporta `fallido` con el detalle del error y sin la marca de privilegios insuficientes

### Requirement: Verificación posterior al grant con SHOW GRANTS

Tras un otorgamiento exitoso, el sistema SHALL consultar los grants vigentes del objeto con `SHOW GRANT` (misma palabra clave por tipo de objeto) y confirmar que el privilegio otorgado aparece concedido al principal. Toda discrepancia entre lo ejecutado y lo vigente SHALL reportarse como ítem `fallido` con su detalle.

#### Scenario: Grant confirmado por la verificación

- **WHEN** un otorgamiento exitoso se verifica y la consulta reporta el privilegio concedido al principal
- **THEN** el ítem se reporta con estado `otorgado`

#### Scenario: Grant no confirmado por la verificación

- **WHEN** un otorgamiento reportado como exitoso no aparece en los grants vigentes del objeto
- **THEN** el ítem se reporta `fallido` con un detalle que menciona el privilegio, el principal y el objeto

#### Scenario: Filas de SHOW GRANTS traducidas a otorgamientos

- **WHEN** la consulta de grants vigentes devuelve una fila por otorgamiento
- **THEN** cada fila se traduce a un otorgamiento con el otorgatario y el privilegio tal como el metastore los reporta

### Requirement: Vertical slice de punta a punta con el canal SQL real

El pipeline SHALL procesar una solicitud 1 a 1 de punta a punta con el canal SQL real: planificación en ítems, pre-flight contra la matriz de compatibilidad y contra los privilegios efectivos del llamante, ejecución del GRANT, verificación y reporte por ítem, registrando el evento en la bitácora de eventos con el usuario que lo provoca.

#### Scenario: Solicitud otorgada de punta a punta

- **WHEN** un llamante con privilegios suficientes procesa una solicitud válida 1 a 1 sobre un objeto del plano de datos
- **THEN** el reporte entrega cada ítem otorgado y verificado, y el evento queda registrado en la bitácora de eventos con el usuario del llamante

#### Scenario: Ítem incompatible bloqueado antes de ejecutar

- **WHEN** la solicitud incluye un privilegio inválido para el tipo de su objeto
- **THEN** el ítem se bloquea en pre-flight con el mensaje preciso de la matriz y no se ejecuta ninguna instrucción SQL para él

#### Scenario: Ítem sin privilegio efectivo del llamante

- **WHEN** el llamante no tiene el privilegio autorizador sobre el objeto de un ítem válido en la matriz
- **THEN** el ítem se bloquea con estado `privilegios_insuficientes` y no se ejecuta ninguna instrucción SQL

#### Scenario: Fallo puntual no aborta la solicitud

- **WHEN** de varios ítems ejecutables uno falla durante la ejecución real
- **THEN** los demás ítems se ejecutan y se reportan, y el fallo del primero queda en su resultado por ítem sin cancelar el resto

### Requirement: Pruebas integrales autocontenidas sobre andresFree

Las pruebas integrales de este change SHALL ejecutar grants reales únicamente contra el workspace primario `andresFree`, creando y destruyendo sus propias fixtures (catálogo, esquema y objetos de cada tipo soportado) y revocando lo otorgado, de modo que ninguna prueba deje estado residual en el workspace.

#### Scenario: Fixtures creadas y destruidas por la propia prueba

- **WHEN** corre una prueba integral de otorgamiento y verificación
- **THEN** la prueba crea sus objetos de prueba, ejecuta el grant, lo verifica y destruye todo lo creado, sin dejar grants ni objetos residuales

#### Scenario: Sin dependencia del workspace de respaldo

- **WHEN** corre la suite integral de este change
- **THEN** ninguna prueba requiere el workspace `andresAzureDev`
