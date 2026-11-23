# Spec Delta

## Purpose

Contratos (interfaces) de los tres canales de ejecución de grants: SQL (GRANT/REVOKE), Databricks SDK y Databricks REST API. Desacoplan el dominio de los mecanismos concretos de ejecución, de modo que la app pueda usar implementaciones reales o simuladas (para testing) sin cambiar el pipeline.

## ADDED Requirements

### Requirement: Contrato unificado de ejecución por canal

Cada canal SHALL exponer una operación de otorgamiento que: reciba un ítem de solicitud ya validado (principal, privilegio, objeto), y devuelva un resultado por ítem con estado otorgado o fallido y el detalle del error cuando ocurra. Los tres canales (SQL, SDK, REST) responden al mismo contrato, de modo que el pipeline puede seleccionar el canal según el plano del objeto sin conocer su mecánica interna.

#### Scenario: Otorgamiento exitoso por contrato

- **WHEN** un canal recibe un ítem válido y lo otorga sin errores
- **THEN** el canal devuelve un resultado por ítem con estado `otorgado`

#### Scenario: Fallo reportado por contrato

- **WHEN** un canal recibe un ítem válido pero la ejecución falla (por ejemplo, el objeto no existe)
- **THEN** el canal devuelve un resultado por ítem con estado `fallido` y el detalle del error, sin propagar la excepción al llamador

### Requirement: Canal SQL para el plano de datos

El canal SQL SHALL otorgar y revocar privilegios sobre objetos del plano de datos (Unity Catalog) mediante instrucciones GRANT/REVOKE, y SHALL además poder consultar los grants vigentes de un objeto (SHOW GRANTS) para su uso en la verificación posterior al grant.

#### Scenario: Instrucción de otorgamiento SQL

- **WHEN** el canal SQL recibe un ítem cuyo objeto pertenece al plano de datos
- **THEN** el canal construye una instrucción de otorgamiento para ese objeto y la ejecuta por su mecanismo SQL

#### Scenario: Consulta de grants vigentes

- **WHEN** se solicita al canal SQL los grants vigentes de un objeto
- **THEN** el canal devuelve la lista de grants vigentes del objeto tal como el sistema los reporta

### Requirement: Canal SDK/REST para el plano de control

El canal SDK y el canal REST SHALL otorgar y revocar permisos sobre objetos del plano de control (Permissions API) y, para el caso de uso de personal access tokens, sobre el Token Permissions API, siguiendo el mismo contrato unificado de resultado por ítem.

#### Scenario: Permiso sobre objeto del plano de control

- **WHEN** el canal SDK o REST recibe un ítem cuyo objeto pertenece al plano de control
- **THEN** el canal otorga el permiso mediante la Permissions API y devuelve el resultado por ítem correspondiente

### Requirement: Errores de privilegios insuficientes identificables

Cada canal SHALL identificar, dentro de los errores que reporta, aquellos causados por privilegios insuficientes del ejecutor, y marcarlos de forma distinguible de otros errores (por ejemplo, permiso denegado del sistema externo), de modo que el pipeline pueda reportar el estado `privilegios_insuficientes` del ítem.

#### Scenario: Permiso denegado del sistema externo

- **WHEN** un canal ejecuta un otorgamiento y el sistema externo responde con un error de permiso denegado para el ejecutor
- **THEN** el canal devuelve el resultado del ítem con la marca de privilegios insuficientes, distinguible de un fallo genérico

#### Scenario: Error no relacionado con privilegios

- **WHEN** un canal ejecuta un otorgamiento y ocurre un error distinto a permiso denegado (por ejemplo, objeto inexistente)
- **THEN** el canal devuelve el resultado del ítem como `fallido`, sin la marca de privilegios insuficientes

### Requirement: Implementaciones simulables para testing

Los contratos SHALL permitir implementaciones simuladas (fake) de cada canal que reproduzcan respuestas exitosas y de error (incluido permiso denegado) sin interactuar con ningún sistema externo, de modo que las pruebas funcionales del pipeline se ejecuten sin conexiones reales.

#### Scenario: Canal simulado que responde éxito

- **WHEN** el pipeline ejecuta un ítem contra una implementación simulada configurada para éxito
- **THEN** el ítem se procesa y reporta `otorgado` sin que exista conexión a sistema externo alguno

#### Scenario: Canal simulado que responde permiso denegado

- **WHEN** el pipeline ejecuta un ítem contra una implementación simulada configurada para responder permiso denegado
- **THEN** el ítem se procesa y reporta `privilegios_insuficientes` sin conexión a sistema externo alguno

### Requirement: En este change no se ejecutan operaciones externas reales

En el alcance de este change, los canales solo definirán sus contratos y sus implementaciones simuladas; ninguna operación de otorgamiento real SHALL ejecutarse contra workspaces externos (las implementaciones reales y pruebas integrales llegan en C4 en adelante).

#### Scenario: Ejecución de grant real fuera de alcance

- **WHEN** se procesa una solicitud completa del pipeline con canales simulados
- **THEN** ninguna instrucción SQL, llamada SDK ni llamada REST es enviada a un workspace real
