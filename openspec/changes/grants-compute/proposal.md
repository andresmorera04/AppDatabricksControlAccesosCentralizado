# Proposal

## Why

El cómputo es la segunda gran familia de objetos con accesos descentralizados: clusters clásicos all-purpose, cómputo serverless (interactivo y automated, gobernado por los serverless compute objects con privilegios `CAN_USE`/`CAN_MANAGE` vía Permissions API) y SQL warehouses. Todos se autorizan por el canal SDK/REST (Permissions API), no por SQL GRANT, lo que exige un adaptador de canal distinto al del plano de datos.

## What Changes

- Implementación del adaptador de canal SDK/REST basado en la Permissions API de Databricks.
- Otorgamiento de privilegios sobre: clusters clásicos all-purpose (`CAN_ATTACH_TO`, `CAN_RESTART`, `CAN_MANAGE`), serverless compute objects — Default Interactive Compute y Default Automated Compute, más objetos custom existentes — (`CAN_USE`, `CAN_MANAGE`), y SQL warehouses (`CAN_USE`, `CAN_MONITOR`, `CAN_MANAGE`).
- Soporte de cardinalidades 1 a 1, 1 a N y N a 1 (vía C5), con split de pre-flight (C3) y verificación post-grant leyendo los ACLs resultantes.
- Alcance documentado: la gestión se limita a permisos de los serverless compute objects existentes (los objetos default no se renombran ni eliminan; la activación del feature es manual y está fuera de la app); el control serverless no cubre DBSQL, Model Serving ni Databricks Apps.
- Implementación guiada por **TDD** (red → green → refactor): toda funcionalidad de este change comienza con una prueba que falla antes de escribir el código que la satisface.
- Cobertura de testing: unitarias, funcionales (Permissions API simulada), integrales contra `andresFree` para lo disponible en Free Edition, y de aceptación.
- Aplicación del **estándar de desarrollo del proyecto** (definido en README.md): código y comentarios detallados en español; constantes `NOMBRE_CONSTANTE` en mayúsculas; variables y objetos en `snake_case`; clases, funciones y métodos en `PascalCase`; instrucciones SQL en mayúsculas; POO como paradigma principal; control de errores con try/except y registro en la bitácora de errores; **código no hardcodeado (regla estricta: todo valor parametrizado o configurable)**; PySpark preferente para el procesamiento masivo. Cada cambio de ACL se registra en la bitácora de eventos con el usuario que lo provoca.
- Las pruebas de integración de clusters clásicos requieren `andresAzureDev` (Free Edition no tiene cómputo clásico) y se marcan con `pytest.mark.azure_approval`: omitidas por defecto y ejecutadas solo con aprobación expresa del usuario. Se incluye un spike para verificar disponibilidad del feature serverless en Free Edition.

## Capabilities

### New Capabilities

- `compute-grants`: Otorgamiento y verificación de privilegios sobre objetos de cómputo (clusters clásicos, serverless compute objects interactivos y automated, SQL warehouses) mediante la Permissions API (SDK/REST).

### Modified Capabilities

- (ninguna)

## Impact

- Nuevo código: adaptador del canal SDK/REST para Permissions API, soporte de los tipos de objeto de cómputo.
- Depende de: `core-domain` (C1), `persistencia-bitacora` (C2), `auth-caller-obo` (C3) y `grants-batch` (C5).
- Uso del workspace `andresAzureDev` solo con aprobación expresa del usuario (decisión D5).
