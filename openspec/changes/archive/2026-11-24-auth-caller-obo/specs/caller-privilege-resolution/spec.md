# Spec Delta

## Purpose

Resuelve los privilegios efectivos que el llamante tiene sobre cada objeto securable objetivo, leyendo los otorgamientos vigentes por el canal que corresponde al plano del objeto, y divide (split) una solicitud de grant en ítems ejecutables e ítems bloqueados con el mensaje explícito de privilegios insuficientes, sin abortar la operación completa.

## ADDED Requirements

### Requirement: Consulta de otorgamientos vigentes por el canal del plano del objeto

El sistema SHALL resolver los privilegios de un objeto objetivo consultando sus otorgamientos vigentes a través del contrato de canales existente, enrutando la consulta según el plano del objeto: canal SQL (`SHOW GRANT`) para el plano de datos y canal SDK/REST (lectura de ACL de la Permissions API) para el plano de control. El sistema SHALL NO implementar un mecanismo de consulta propio por plano ni duplicar el enrutamiento ya declarado por `channel-adapters` y `grant-pipeline`.

#### Scenario: Objeto del plano de datos

- **WHEN** se consultan los otorgamientos vigentes de un objeto del plano de datos
- **THEN** el sistema usa el canal del plano de datos y obtiene los otorgamientos que ese canal reporta para el objeto

#### Scenario: Objeto del plano de control

- **WHEN** se consultan los otorgamientos vigentes de un objeto del plano de control
- **THEN** el sistema usa el canal del plano de control y obtiene los permisos vigentes que ese canal reporta para el objeto

#### Scenario: Plano sin canal configurado

- **WHEN** el objeto objetivo pertenece a un plano sin canal configurado
- **THEN** el sistema reporta el fallo de forma controlada y no clasifica el ítem como ejecutable

### Requirement: Emparejamiento de otorgamientos contra las referencias del llamante

El sistema SHALL considerar privilegio efectivo del llamante todo otorgamiento vigente cuyo otorgatario coincida con alguna de las referencias de identidad de la identidad resuelta del llamante.

#### Scenario: Otorgamiento directo al usuario

- **WHEN** un otorgamiento vigente identifica al propio usuario llamante con el privilegio consultado
- **THEN** el sistema incluye ese privilegio entre los efectivos del llamante

#### Scenario: Otorgamiento a un grupo del llamante

- **WHEN** un otorgamiento vigente identifica a un grupo del que el llamante es miembro
- **THEN** el sistema incluye ese privilegio entre los efectivos del llamante

#### Scenario: Otorgamiento a un service principal distinto del llamante

- **WHEN** un otorgamiento vigente identifica a un service principal que no es el llamante y el llamante es un usuario
- **THEN** el sistema NO incluye ese privilegio entre los efectivos del llamante

#### Scenario: Otorgamiento al App Id del llamante service principal

- **WHEN** el llamante es un service principal y un otorgamiento vigente lo identifica por su App Id
- **THEN** el sistema incluye ese privilegio entre los efectivos del llamante

### Requirement: Compatibilidad de formatos de identificación entre planos

La coincidencia del emparejamiento SHALL resolverse entre los formatos de identificación que reporta cada plano (identificadores opacos en el plano de datos, nombres en el plano de control) y SHALL respetar la normalización de identificadores declarada por plano en el modelo de dominio.

#### Scenario: Otorgamiento identificado por referencias del llamante en ambos planos

- **WHEN** el llamante es un usuario miembro de grupos y un otorgamiento vigente lo referencia por nombre de grupo en el plano de control o por identificador en el plano de datos
- **THEN** el sistema empareja ambos casos mediante las referencias de identidad del llamante, sin exigir que los dos planos usen el mismo formato


### Requirement: Herencia de otorgamientos reportada por el sistema

El sistema SHALL considerar como efectivos los otorgamientos que el propio mecanismo de consulta reporte como heredados de un securable padre, sin reimplementar la jerarquía de heredamientos. La vista de privilegios efectivos SHALL permitir distinguir el origen de cada privilegio (directo o heredado) cuando el canal lo reporte.

#### Scenario: Privilegio heredado del padre

- **WHEN** la consulta del canal reporta un otorgamiento del llamante heredado de un securable padre
- **THEN** el sistema lo incluye entre los privilegios efectivos y deja constancia de su origen heredado

#### Scenario: Canal que no reporta el origen

- **WHEN** el canal consultado no informa si un otorgamiento es heredado
- **THEN** el sistema lo incluye entre los privilegios efectivos con el origen explícitamente no determinado, sin suponer que es directo

### Requirement: Resolución previa a la ejecución

El sistema SHALL resolver los privilegios efectivos del llamante sobre todos los objetos objetivo de una solicitud antes de que el pipeline intente cualquier otorgamiento, de modo que la clasificación no dependa de ejecuciones parciales.

#### Scenario: Solicitud con varios ítems

- **WHEN** una solicitud produce varios ítems sobre uno o varios objetos
- **THEN** el sistema resuelve los privilegios efectivos de todos los objetos involucrados antes de clasificar o ejecutar cualquier ítem

### Requirement: Vista unificada de privilegios efectivos por objeto

El sistema SHALL devolver, para cada objeto objetivo, una vista unificada con el objeto, su plano, el canal por el que se consultó y el conjunto de privilegios efectivos del llamante sobre él, ocultando las diferencias de formato entre canales.

#### Scenario: Objeto con privilegios efectivos

- **WHEN** la consulta devuelve otorgamientos del llamante sobre el objeto
- **THEN** la vista unificada expone el objeto, su plano, el canal usado y la lista de privilegios efectivos

#### Scenario: Objeto sin privilegios efectivos

- **WHEN** la consulta no devuelve ningún otorgamiento del llamante sobre el objeto
- **THEN** la vista unificada expone una lista de privilegios efectivos explícitamente vacía, distinguible de un fallo de consulta

### Requirement: División de la solicitud según los privilegios del llamante

El sistema SHALL añadir a la fase de pre-flight un segundo eje de clasificación, además del eje de la matriz de compatibilidad: cada ítem cuyo privilegio no figure entre los efectivos del llamante sobre su objeto SHALL quedar bloqueado con el estado `privilegios_insuficientes`. Los ítems bloqueados SHALL pasar directamente al reporte y el resto SHALL continuar su procesamiento; ningún bloqueo aborta la operación completa.

#### Scenario: Ítem con privilegio efectivo

- **WHEN** el privilegio de un ítem está declarado en la matriz y figura entre los efectivos del llamante sobre su objeto
- **THEN** el sistema clasifica el ítem como ejecutable y lo entrega a la fase de ejecución

#### Scenario: Ítem sin privilegio efectivo

- **WHEN** el privilegio de un ítem es válido para el tipo de objeto, pero no figura entre los efectivos del llamante
- **THEN** el sistema clasifica el ítem como bloqueado con estado `privilegios_insuficientes`, con su mensaje estructurado, y no lo envía a ejecución

#### Scenario: Solicitud mixta

- **WHEN** una solicitud contiene ítems sobre objetos en los que el llamante sí y no tiene el privilegio requerido
- **THEN** el sistema entrega ítems ejecutables e ítems bloqueados por separado, y la ejecución de los ejecutables no se interrumpe por los bloqueos

#### Scenario: Llamante sin identidad resuelta

- **WHEN** la identidad del llamante no pudo resolverse
- **THEN** el sistema no clasifica ningún ítem como ejecutable por este eje y reporta el motivo de forma controlada

### Requirement: Mensaje estructurado de privilegios insuficientes

El sistema SHALL representar el bloqueo por falta de privilegios como un dato con los campos `objeto`, `plano`, `privilegio_requerido` y `privilegio_faltante`, consultables de forma independiente por el reporte y por la interfaz, y SHALL además renderizar un texto legible que identifique esos cuatro elementos.

#### Scenario: Campos consultables por nombre

- **WHEN** un ítem queda bloqueado por privilegios insuficientes
- **THEN** el dato del bloqueo expone el objeto, su plano, el privilegio requerido y el privilegio faltante como campos independientes

#### Scenario: Texto legible del bloqueo

- **WHEN** el reporte presenta un ítem bloqueado por privilegios insuficientes
- **THEN** el texto identificado el objeto, el plano, el privilegio requerido y el privilegio faltante

### Requirement: Errores del resolutor controlados y trazables

Cuando la consulta de otorgamientos vigentes falle por una causa distinta de la falta de privilegios del llamante (objeto inexistente, error de transporte, respuesta inválida del servicio), el sistema SHALL capturar el error, registrarlo en la bitácora de errores con su detalle estructurado y clasificar los ítems afectados como `fallido` sin afectar a los demás ítems de la solicitud.

#### Scenario: Objeto inexistente

- **WHEN** la consulta del canal responde que el objeto objetivo no existe
- **THEN** el sistema registra el error controlado y clasifica los ítems de ese objeto como `fallido`, nunca como `privilegios_insuficientes`

#### Scenario: Fallo de transporte o respuesta inválida

- **WHEN** el canal no puede consultar los otorgamientos por un fallo de transporte o una respuesta malformada
- **THEN** el sistema registra el error controlado y clasifica los ítems afectados como `fallido`, continuando con los demás ítems

### Requirement: La resolución de este change es de solo lectura

En el alcance de este change, la autenticación y la resolución de privilegios SHALL limitarse a consultar identidad y otorgamientos vigentes; SHALL NO otorgar, revocar ni modificar permisos, y SHALL NO requerir implementaciones reales de canales ni credenciales adicionales.

#### Scenario: Solicitud completa procesada con canales simulados

- **WHEN** una solicitud se procesa con la identidad y los canales simulados de las pruebas
- **THEN** ningún otorgamiento, revocación ni escritura de permisos llega a un workspace real
