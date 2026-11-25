# Spec Delta

## Purpose

Otorga y verifica privilegios sobre external locations y connections de Unity Catalog mediante el canal SQL GRANT/REVOKE, completando la cobertura del plano de datos del sistema en las cardinalidades 1 a 1, 1 a N y N a 1.

## ADDED Requirements

### Requirement: Instrucción de otorgamiento para objetos externos

Para cada ítem cuyo objeto sea una external location o una connection de Unity Catalog, el sistema SHALL construir una instrucción `GRANT` completamente en mayúsculas que otorgue el privilegio del ítem al principal sobre el objeto, usando la palabra clave SQL que corresponde al tipo (`EXTERNAL LOCATION` o `CONNECTION`) e identificando al principal por su identificador.

#### Scenario: Grant sobre una external location

- **WHEN** un ítem otorga un privilegio sobre una external location identificada por su nombre
- **THEN** la instrucción construida usa la palabra clave `EXTERNAL LOCATION` con ese nombre

#### Scenario: Grant sobre una connection

- **WHEN** un ítem otorga un privilegio sobre una connection de Unity Catalog
- **THEN** la instrucción construida usa la palabra clave `CONNECTION`

#### Scenario: Privilegios según la matriz

- **WHEN** un ítem otorga un privilegio válido según la matriz de compatibilidad (p. ej. `READ FILES` en external location, `USE CONNECTION` en connection)
- **THEN** la instrucción construida incluye ese privilegio en mayúsculas y el principal identificado por su identificador

### Requirement: Instrucción de revocación para objetos externos

El sistema SHALL construir la instrucción `REVOKE` en mayúsculas equivalente a la de otorgamiento, con el mismo mapeo de palabra clave SQL por tipo de objeto externo, para quitar a un principal un privilegio sobre una external location o una connection.

#### Scenario: Revocación sobre una external location

- **WHEN** se revoca a un principal un privilegio sobre una external location
- **THEN** la instrucción construida revoca el privilegio con la palabra clave `EXTERNAL LOCATION`, el nombre de la location y el principal indicado

#### Scenario: Revocación sobre una connection

- **WHEN** se revoca a un principal un privilegio sobre una connection
- **THEN** la instrucción construida usa la palabra clave `CONNECTION`

### Requirement: Ejecución de instrucciones por una sesión SQL inyectada

El canal SQL SHALL ejecutar cada instrucción de objetos externos a través de la sesión SQL inyectada, sin valores de conexión embebidos en el código. El canal SHALL devolver siempre un resultado por ítem, sin propagar excepciones al pipeline.

#### Scenario: Instrucción enviada a la sesión inyectada

- **WHEN** el canal ejecuta el otorgamiento de un ítem sobre una external location o una connection
- **THEN** la instrucción construida se envía tal cual a la sesión inyectada

#### Scenario: Canal ejercitado sin workspace alguno

- **WHEN** el canal se construye con una sesión simulada
- **THEN** el otorgamiento y la revocación sobre objetos externos se procesan y se reportan sin ninguna conexión externa

### Requirement: Errores del workspace traducidos a mensajes específicos por caso

El canal SQL SHALL distinguir los fallos del workspace al operar sobre objetos externos y reportarlos con mensaje específico en español: permiso denegado al ejecutor como `privilegios_insuficientes`; objeto inexistente, principal inexistente y cualquier otro fallo de la sesión como `fallido`, cada uno con un mensaje que identifica el caso y los elementos involucrados.

#### Scenario: Permiso denegado al otorgar

- **WHEN** el workspace responde con permiso denegado al ejecutar la instrucción del llamante sobre un objeto externo
- **THEN** el ítem se reporta con estado `privilegios_insuficientes` y un mensaje que identifica el privilegio y el objeto, y deja constancia de que el llamante no puede otorgarlo

#### Scenario: External location o connection inexistente

- **WHEN** la instrucción falla porque la external location o la connection no existe en el metastore
- **THEN** el ítem se reporta `fallido` con un mensaje que identifica el objeto inexistente

#### Scenario: Principal inexistente

- **WHEN** la instrucción falla porque el principal no existe en el workspace
- **THEN** el ítem se reporta `fallido` con un mensaje que identifica el principal inexistente

#### Scenario: Cualquier otro fallo de la sesión

- **WHEN** la sesión falla por una causa distinta (transporte, sentencia rechazada)
- **THEN** el ítem se reporta `fallido` con el detalle del error y sin la marca de privilegios insuficientes

### Requirement: Verificación posterior al grant con SHOW GRANTS

Tras un otorgamiento exitoso sobre un objeto externo, el sistema SHALL consultar los grants vigentes del objeto con `SHOW GRANT` (misma palabra clave por tipo) y confirmar que el privilegio otorgado aparece concedido al principal. Toda discrepancia SHALL reportarse como ítem `fallido` con su detalle.

#### Scenario: Grant confirmado por la verificación

- **WHEN** un otorgamiento exitoso sobre una external location o una connection se verifica y la consulta reporta el privilegio concedido al principal
- **THEN** el ítem se reporta con estado `otorgado`

#### Scenario: Grant no confirmado por la verificación

- **WHEN** un otorgamiento reportado como exitoso no aparece en los grants vigentes del objeto externo
- **THEN** el ítem se reporta `fallido` con un detalle que menciona el privilegio, el principal y el objeto

#### Scenario: Filas propias conservan el tipo consultado

- **WHEN** la consulta de grants vigentes devuelve la fila del propio objeto consultado
- **THEN** esa fila se traduce a un otorgamiento con el tipo consultado (`external_location` o `connection`), y cualquier fila con palabra no mapeable (p. ej. un contenedor padre como `METASTORE`) se omite sin inventar objeto

### Requirement: Cardinalidades 1 a 1, 1 a N y N a 1

El sistema SHALL procesar solicitudes sobre objetos externos en las cardinalidades 1 a 1, 1 a N (un principal, N objetos) y N a 1 (N principals, un objeto), normalizadas a ítems atómicos con resultados parciales independientes y reporte consolidado del lote, rechazando explícitamente la cardinalidad N a M.

#### Scenario: Lote 1 a N sobre external locations

- **WHEN** un principal recibe privilegios sobre varias external locations en un lote
- **THEN** cada combinación privilegio-objeto se procesa como ítem atómico con su resultado parcial, y el lote se consolida en el reporte

#### Scenario: Lote N a 1 sobre una connection

- **WHEN** varios principals reciben privilegios sobre una misma connection en un lote
- **THEN** cada combinación principal-privilegio se procesa como ítem atómico con su resultado parcial

#### Scenario: Lote N a M rechazado

- **WHEN** una solicitud sobre objetos externos declara varios principals y varios objetos
- **THEN** se rechaza con el mensaje explícito de cardinalidad N a M no soportada, sin ejecutar instrucción alguna

### Requirement: Cobertura completa del plano de datos

El canal SQL SHALL soportar los diez tipos de objeto del plano de datos: los ocho ya cubiertos (catálogo, esquema, tabla delta, streaming table, vista materializada, vista SQL, volumen y modelo ML) más external location y connection. Un ítem del plano de control que llegue al canal SHALL reportarse como `fallido` controlado con mensaje explícito de tipo no soportado, sin ejecutar instrucción alguna.

#### Scenario: Objeto del plano de control fuera del canal

- **WHEN** llega al canal SQL un ítem cuyo objeto pertenece al plano de control
- **THEN** el ítem se reporta `fallido` con el mensaje explícito de tipo no soportado por este canal y no se ejecuta ninguna instrucción SQL

### Requirement: Pruebas integrales autocontenidas con perfil por tipo de objeto

Las pruebas integrales de este change SHALL ejecutar grants reales con perfil asignado por tipo de objeto: la external location contra `andresAzureDev` y la connection contra `andresFree` con fallback autorizado a `andresAzureDev` (ambas pre-aprobadas por el humano), creando y destruyendo sus propias fixtures y revocando lo otorgado.

#### Scenario: Fixtures creadas y destruidas por la propia prueba

- **WHEN** corre una prueba integral de otorgamiento y verificación sobre objetos externos
- **THEN** la prueba crea su external location (perfil `andresAzureDev`) o su connection (perfil `andresFree`), ejecuta el grant, lo verifica y destruye todo lo creado, sin dejar grants ni objetos residuales

#### Scenario: Connection con fallback autorizado

- **WHEN** el perfil `andresFree` presenta un problema para crear la fixture de connection
- **THEN** la fixture se intenta contra `andresAzureDev`, autorización otorgada por el humano

#### Scenario: Tipo no creable en ningún perfil

- **WHEN** ni `andresFree` ni `andresAzureDev` permiten crear la fixture de un tipo externo
- **THEN** la prueba integral de ese tipo queda marcada con skip explícito que documenta la limitación, y el comportamiento se cubre en las capas unitaria y funcional
