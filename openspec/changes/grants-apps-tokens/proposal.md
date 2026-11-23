# Proposal

## Why

Quedan dos objetos del plano de control con autorización descentralizada: las Databricks Apps (con ACLs propios: `CAN_USE`, `CAN_MANAGE`) y el uso de personal access tokens, que se gobierna mediante la Token Permissions API (`authorization/tokens`, privilegio `CAN_USE`). Ambos usan el canal REST/SDK y completan el inventario de objetos que la aplicación debe centralizar.

## What Changes

- Otorgamiento de privilegios sobre Databricks Apps (`CAN_USE`, `CAN_MANAGE`) mediante la Permissions API, reutilizando el adaptador SDK/REST de C7.
- Otorgamiento del privilegio de uso de personal access tokens (`CAN_USE` sobre `authorization/tokens`) mediante la Token Permissions API (REST).
- Soporte de cardinalidades 1 a 1, 1 a N y N a 1 (vía C5), con split de pre-flight (C3) y verificación post-grant.
- Implementación guiada por **TDD** (red → green → refactor): toda funcionalidad de este change comienza con una prueba que falla antes de escribir el código que la satisface.
- Cobertura de testing: unitarias, funcionales (APIs simuladas), integrales contra `andresFree` (según disponibilidad del tipo de objeto en Free Edition; las que no apliquen se documentan y marcan con skip justificado), y de aceptación.
- Aplicación del **estándar de desarrollo del proyecto** (definido en README.md): código y comentarios detallados en español; constantes `NOMBRE_CONSTANTE` en mayúsculas; variables y objetos en `snake_case`; clases, funciones y métodos en `PascalCase`; instrucciones SQL en mayúsculas; POO como paradigma principal; control de errores con try/except y registro en la bitácora de errores; **código no hardcodeado (regla estricta: todo valor parametrizado o configurable)**; PySpark preferente para el procesamiento masivo. Cada cambio de permisos se registra en la bitácora de eventos con el usuario que lo provoca.

## Capabilities

### New Capabilities

- `app-token-grants`: Otorgamiento y verificación de privilegios sobre Databricks Apps y de uso de personal access tokens mediante los canales SDK/REST (Permissions API y Token Permissions API).

### Modified Capabilities

- (ninguna)

## Impact

- Nuevo código: soporte de los tipos de objeto Databricks App y token de acceso personal en el adaptador SDK/REST; cliente de la Token Permissions API.
- Depende de: `core-domain` (C1), `persistencia-bitacora` (C2), `auth-caller-obo` (C3), `grants-batch` (C5) y `grants-compute` (C7, por el adaptador SDK/REST).
- No requiere `andresAzureDev` salvo que una prueba concreta lo justifique (con aprobación expresa).
