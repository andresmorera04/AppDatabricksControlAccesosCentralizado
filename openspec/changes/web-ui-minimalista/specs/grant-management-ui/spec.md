# Spec Delta

## Purpose

Proporciona una interfaz web minimalista para otorgar privilegios con la autorización del usuario llamante (identidad OBO y privilegios efectivos), ejecutando con su credencial OBO donde es viable y con la identidad de la App en modo broker donde OBO es inviable, guiando la selección de principals, objetos y privilegios, mostrando antes de ejecutar qué ítems están autorizados y presentando después un reporte completo por ítem.

## ADDED Requirements

### Requirement: Autenticación on-behalf-of y aislamiento del llamante

La Databricks App SHALL autenticar al usuario mediante su contexto on-behalf-of y SHALL evaluar toda autorización con su identidad y privilegios efectivos. La ejecución SHALL usar su credencial OBO donde es viable (grants UC vía SQL y ACL de Apps) y la identidad de la App en modo broker donde OBO es inviable (SCIM y ACL del plano de control), únicamente tras validar la autoridad del llamante conforme a `app-broker-grants`. SHALL NO compartir credenciales ni autorizaciones entre sesiones.

#### Scenario: Usuario autenticado correctamente

- **WHEN** un usuario accede con un contexto on-behalf-of válido
- **THEN** la interfaz muestra su identidad resuelta y habilita el flujo de selección usando sus privilegios

#### Scenario: Contexto o token no válido

- **WHEN** la invocación no incluye un contexto on-behalf-of válido o su token está expirado
- **THEN** la interfaz deshabilita previsualización y ejecución, muestra un mensaje controlado y registra el error sin realizar cambios

#### Scenario: Dos usuarios con privilegios distintos

- **WHEN** dos usuarios utilizan la App con privilegios efectivos diferentes
- **THEN** cada sesión autoriza exclusivamente con la identidad y privilegios de su propio llamante, y cualquier ejecución con la identidad de la App queda condicionada a esa autorización

#### Scenario: No herencia de credenciales de la App en runtime

- **WHEN** el runtime de la App expone en el entorno las credenciales OAuth de su propio service principal
- **THEN** la composición OBO fija el método de autenticación explícito al token del llamante, la identidad de la App jamás se usa para evaluar autorización ni se mezcla con el token OBO, y la ejecución con el SP solo ocurre en modo broker tras validar la autoridad del llamante

#### Scenario: Ejecución broker autorizada en el plano de control

- **WHEN** el llamante tiene validado el privilegio efectivo requerido sobre un warehouse, cluster, serverless compute object o los tokens
- **THEN** la operación sobre la ACL se ejecuta con la identidad de la App y el evento de bitácora registra el usuario OBO del llamante

#### Scenario: Bloqueo sin autoridad aunque el SP pueda ejecutar

- **WHEN** el llamante carece del privilegio efectivo requerido sobre un objeto del plano de control
- **THEN** el ítem queda bloqueado con su motivo y no se ejecuta con la identidad de la App, aunque el service principal tenga privilegios suficientes para realizarlo

### Requirement: Descubrimiento de principals y objetos

La interfaz SHALL ofrecer opciones de usuarios, grupos, service principals y objetos soportados obtenidas del workspace: con la credencial OBO del llamante para Unity Catalog, SQL warehouses y Databricks Apps, y con la identidad de la App (modo broker) para los listados SCIM y de cómputo, cuyos scopes OBO no existen. Un fallo de descubrimiento SHALL presentarse de forma controlada, sin elevar privilegios ni convertirlo en una lista aparentemente vacía.

#### Scenario: Opciones descubiertas para el tipo elegido

- **WHEN** el usuario selecciona un tipo de principal u objeto y el workspace permite listarlo
- **THEN** la interfaz presenta las entradas descubiertas con identificadores utilizables para construir la solicitud

#### Scenario: Listados SCIM y de cómputo con la identidad de la App

- **WHEN** la interfaz necesita opciones de usuarios, grupos, service principals, clusters o serverless compute objects
- **THEN** los listados se obtienen con la identidad de la App en modo broker y se presentan como opciones, sin que ello habilite ejecución alguna sin la autorización del llamante

#### Scenario: Descubrimiento denegado o no disponible

- **WHEN** el workspace deniega o falla el listado de un tipo de principal u objeto
- **THEN** la interfaz informa que no pudo descubrir esas opciones, registra el error y no habilita una ejecución basada en datos incompletos

### Requirement: Selección de privilegios guiada por la matriz

La interfaz SHALL presentar como seleccionables únicamente los privilegios válidos para el tipo de objeto elegido. Al cambiar el tipo, SHALL descartar selecciones incompatibles antes de permitir la previsualización.

#### Scenario: Privilegios filtrados por tipo

- **WHEN** el usuario selecciona un tipo de objeto
- **THEN** las opciones de privilegio contienen exactamente las combinaciones válidas declaradas para ese tipo y ninguna de otro tipo

#### Scenario: Cambio de tipo con selección previa

- **WHEN** el usuario cambia el tipo de objeto después de seleccionar privilegios
- **THEN** la interfaz elimina los privilegios incompatibles y exige una nueva previsualización antes de ejecutar

### Requirement: Disponibilidad según privilegios efectivos

Para las entradas descubiertas, la interfaz SHALL evaluar los privilegios efectivos del llamante y marcar como no disponibles, con su motivo, las combinaciones que no pueda otorgar. Una opción inhabilitada SHALL NO poder enviarse a ejecución desde la interfaz.

#### Scenario: Objeto sin autorización para el privilegio elegido

- **WHEN** un objeto descubierto no tiene el privilegio efectivo requerido para una selección del usuario
- **THEN** esa combinación aparece no disponible con el mensaje de privilegios insuficientes y no puede confirmarse para ejecución

#### Scenario: Selección con disponibilidad mixta

- **WHEN** en una selección 1 a N algunos objetos son autorizados y otros no para los privilegios elegidos
- **THEN** la interfaz distingue visualmente ambos grupos y conserva sus motivos para la previsualización

### Requirement: Cardinalidades admitidas por la interfaz

La interfaz SHALL admitir solicitudes 1 a 1, 1 a N y N a 1, con uno o varios privilegios, y SHALL rechazar N a M antes de consultar o ejecutar grants. Cada solicitud SHALL usar un único tipo de objeto para que el filtrado de privilegios sea inequívoco.

#### Scenario: Flujo 1 a 1

- **WHEN** el usuario selecciona un principal, uno o varios privilegios y un objeto
- **THEN** la interfaz admite la solicitud y genera un ítem por privilegio para su previsualización

#### Scenario: Flujo 1 a N

- **WHEN** el usuario selecciona un principal, uno o varios privilegios y varios objetos del mismo tipo
- **THEN** la interfaz admite la solicitud y genera ítems por cada combinación objeto-privilegio

#### Scenario: Flujo N a 1

- **WHEN** el usuario selecciona varios principals, uno o varios privilegios y un objeto
- **THEN** la interfaz admite la solicitud y genera ítems por cada combinación principal-privilegio

#### Scenario: Cardinalidad N a M rechazada

- **WHEN** el usuario intenta seleccionar varios principals y varios objetos simultáneamente
- **THEN** la interfaz muestra que N a M está fuera de alcance y no genera previsualización ni ejecuta operación alguna

### Requirement: Validación de la solicitud antes de previsualizar

La interfaz SHALL exigir al menos un principal, un privilegio y un objeto, además de identificadores válidos, antes de iniciar la previsualización. Una solicitud incompleta SHALL producir un mensaje específico sin invocar operaciones de grant.

#### Scenario: Conjunto obligatorio vacío

- **WHEN** el usuario solicita previsualizar sin seleccionar alguno de los conjuntos obligatorios
- **THEN** la interfaz identifica el conjunto faltante y no inicia pre-flight ni ejecución

#### Scenario: Identificador inválido

- **WHEN** una entrada contiene un identificador vacío o no válido para el dominio
- **THEN** la interfaz muestra el error de validación correspondiente sin ejecutar ningún cambio

### Requirement: Previsualización del split ejecutable y bloqueado

Antes de habilitar la ejecución, la interfaz SHALL mostrar todos los ítems planificados clasificados como ejecutables o bloqueados, con principal, privilegio, objeto, estado y motivo. La previsualización SHALL ser de solo lectura y SHALL NO otorgar, revocar ni modificar permisos.

#### Scenario: Previsualización con resultado mixto

- **WHEN** una solicitud contiene ítems ejecutables e ítems bloqueados por matriz o privilegios insuficientes
- **THEN** la previsualización incluye ambos grupos con su motivo y no modifica ningún grant

#### Scenario: Todos los ítems bloqueados

- **WHEN** ningún ítem supera la clasificación previa
- **THEN** la interfaz muestra todos los bloqueos y no habilita la ejecución

### Requirement: Confirmación explícita y revalidación al ejecutar

La interfaz SHALL exigir una confirmación posterior a una previsualización vigente antes de ejecutar. Al confirmar, SHALL repetir la clasificación de autorización; un cambio en el formulario o una previsualización ya consumida SHALL invalidar la confirmación anterior.

#### Scenario: Ejecución confirmada por el usuario

- **WHEN** el usuario confirma una previsualización vigente con al menos un ítem ejecutable
- **THEN** la interfaz procesa la solicitud una sola vez y presenta el reporte resultante

#### Scenario: Formulario modificado tras previsualizar

- **WHEN** el usuario cambia principals, privilegios u objetos después de previsualizar
- **THEN** la previsualización anterior queda invalidada y la ejecución exige una nueva revisión

#### Scenario: Privilegios modificados entre revisión y ejecución

- **WHEN** la autorización del llamante cambia después de la previsualización
- **THEN** la ejecución vuelve a clasificar los ítems y el reporte refleja la autorización vigente al confirmar

### Requirement: Resultados parciales y reporte final por ítem

Tras ejecutar, la interfaz SHALL presentar todos los ítems con estado `otorgado`, `fallido` o `privilegios_insuficientes` y su detalle, sin ocultar bloqueados ni detenerse por fallos parciales. Para lotes SHALL incluir totales por estado y conservar el orden de planificación.

#### Scenario: Reporte con resultados parciales

- **WHEN** una ejecución termina con ítems otorgados, fallidos y con privilegios insuficientes
- **THEN** el reporte muestra los tres estados, el detalle de cada ítem y los bloqueados que no llegaron a ejecución

#### Scenario: Totales de un lote

- **WHEN** finaliza una solicitud 1 a N o N a 1
- **THEN** la interfaz muestra el total de ítems y los totales por estado coherentes con el detalle presentado

### Requirement: Errores controlados, auditoría y protección de secretos

Los errores de interfaz, descubrimiento y ejecución SHALL capturarse y registrarse con el usuario llamante cuando esté disponible. Tokens, encabezados de autorización y secretos SHALL NO mostrarse ni registrarse; un fallo de bitácora SHALL NO ocultar el reporte ya obtenido.

#### Scenario: Error controlado con identidad conocida

- **WHEN** ocurre un error durante una acción de la interfaz con identidad OBO resuelta
- **THEN** el sistema muestra un mensaje comprensible, registra el error con ese usuario y evita una excepción no controlada

#### Scenario: Fallo de bitácora después de procesar

- **WHEN** el pipeline produjo un reporte pero la escritura de auditoría falla
- **THEN** la interfaz conserva y muestra el reporte y deja constancia del fallo sin exponer credenciales

### Requirement: Interfaz y mensajes en español

Todos los controles, estados, instrucciones y mensajes visibles de la interfaz SHALL presentarse en español y usar el vocabulario del dominio. Los mensajes de privilegios insuficientes SHALL identificar objeto, plano, privilegio requerido y privilegio faltante.

#### Scenario: Flujo completo comprensible en español

- **WHEN** un usuario recorre selección, previsualización, confirmación y reporte
- **THEN** encuentra instrucciones y estados en español sin necesidad de interpretar errores técnicos del transporte

#### Scenario: Mensaje de privilegios insuficientes

- **WHEN** la interfaz presenta un ítem bloqueado por falta de privilegios
- **THEN** el mensaje identifica el objeto, su plano, el privilegio requerido y el privilegio faltante
