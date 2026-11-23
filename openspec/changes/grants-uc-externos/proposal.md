# Proposal

## Why

Las external locations y las connections de Unity Catalog gobiernan el acceso a almacenamiento externo y a sistemas remotos; son objetos del plano de datos con privilegios propios (p. ej. `CREATE EXTERNAL TABLE`, `USE CONNECTION`) que hoy también se otorgan de forma descentralizada. Centralizarlos completa la cobertura del plano de datos de Unity Catalog.

## What Changes

- Extensión del canal SQL (GRANT/REVOKE) para external locations y connections de Unity Catalog, reutilizando el adaptador creado en C4.
- Soporte de los privilegios aplicables según la matriz (C1), en cardinalidades 1 a 1, 1 a N y N a 1 (vía C5).
- Verificación post-grant con `SHOW GRANTS` y registro del resultado por ítem.
- Implementación guiada por **TDD** (red → green → refactor): toda funcionalidad de este change comienza con una prueba que falla antes de escribir el código que la satisface.
- Cobertura de testing: unitarias, funcionales (canal simulado), integrales contra `andresFree` (fixtures de external location sobre almacenamiento accesible y connection si el workspace lo permite), y de aceptación.
- Aplicación del **estándar de desarrollo del proyecto** (definido en README.md): código y comentarios detallados en español; constantes `NOMBRE_CONSTANTE` en mayúsculas; variables y objetos en `snake_case`; clases, funciones y métodos en `PascalCase`; instrucciones SQL en mayúsculas; POO como paradigma principal; control de errores con try/except y registro en la bitácora de errores; **código no hardcodeado (regla estricta: todo valor parametrizado o configurable)**; PySpark preferente para el procesamiento masivo. Cada grant ejecutado se registra en la bitácora de eventos con el usuario que lo provoca.

## Capabilities

### New Capabilities

- `uc-external-object-grants`: Otorgamiento y verificación de privilegios sobre external locations y connections de Unity Catalog mediante el canal SQL GRANT/REVOKE.

### Modified Capabilities

- (ninguna)

## Impact

- Nuevo código: soporte de dos tipos de objeto adicionales en el adaptador del canal SQL.
- Depende de: `core-domain` (C1), `persistencia-bitacora` (C2), `auth-caller-obo` (C3), `grants-uc-datos` (C4) y `grants-batch` (C5).
- Las pruebas de integración pueden requerir configuración de almacenamiento externo accesible desde `andresFree`; si un tipo de objeto no es creable en ese workspace, su prueba integral se documenta y se marca con skip justificado.
