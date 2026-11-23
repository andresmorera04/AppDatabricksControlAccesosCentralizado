# Proposal

## Why

Los objetos del plano de datos de Unity Catalog (catálogos, esquemas, tablas delta, streaming tables, vistas materializadas, vistas SQL, volúmenes y modelos de ML) son la familia más grande y más usada del problema de accesos descentralizados. Implementar esta familia como primera vertical slice de punta a punta (pre-flight + GRANT + verificación) valida la arquitectura del pipeline antes de replicarla al resto de familias, y entrega valor inmediato: un principal puede recibir privilegios sobre estos objetos desde un solo lugar.

## What Changes

- Implementación del canal SQL (GRANT/REVOKE) para objetos de Unity Catalog: catálogo, esquema, tabla delta, streaming table, vista materializada, vista SQL, volumen y modelo de ML (registered model).
- Otorgamiento 1 a 1: un principal (usuario, grupo o service principal) recibe uno o varios privilegios sobre un objeto, validados contra la matriz de privilegios (C1) y filtrados por el split de pre-flight (C3).
- Verificación post-grant con `SHOW GRANTS ON <objeto>` y registro del resultado por ítem.
- Mensajes de error específicos por caso: privilegio incompatible con el tipo de objeto, objeto inexistente, principal inexistente, privilegios insuficientes del llamante.
- Implementación guiada por **TDD** (red → green → refactor): toda funcionalidad de este change comienza con una prueba que falla antes de escribir el código que la satisface.
- Cobertura de testing: unitarias (generación de sentencias GRANT, validación contra matriz), funcionales (canal SQL simulado con respuestas y errores reales), integrales contra `andresFree` (fixtures de catálogo/esquema/objetos creados y destruidos por la propia prueba), y de aceptación.
- Aplicación del **estándar de desarrollo del proyecto** (definido en README.md): código y comentarios detallados en español; constantes `NOMBRE_CONSTANTE` en mayúsculas; variables y objetos en `snake_case`; clases, funciones y métodos en `PascalCase`; instrucciones SQL en mayúsculas; POO como paradigma principal; control de errores con try/except y registro en la bitácora de errores; **código no hardcodeado (regla estricta: todo valor parametrizado o configurable)**; PySpark preferente para el procesamiento masivo. Cada grant ejecutado se registra en la bitácora de eventos con el usuario que lo provoca.
- Aplicación de las **restricciones de entorno del proyecto** (regla estricta, definida en README.md): (1) las bibliotecas de Python se activan con el comando `source ~/.venv/bin/activate`, y todo comando `python`, `pip` o `pytest` de este change se ejecuta con ese entorno virtual activado (Python 3.14); sin la activación, los comandos caen en el Python del sistema, que no tiene las dependencias del proyecto; (2) **prohibición de instalación por la IA**: queda terminantemente prohibido que la IA instale cualquier biblioteca, bash, aplicación o binario en la Mac; si la instalación de algo es necesaria, la IA debe solicitarla al humano y justificarla a detalle (qué se instala, para qué y su impacto), y solamente el humano puede aplicar la instalación, o bien dar su aprobación y autorización explícita a la IA para que la realice.

## Capabilities

### New Capabilities

- `uc-data-object-grants`: Otorgamiento y verificación de privilegios 1 a 1 sobre objetos del plano de datos de Unity Catalog (catálogos, esquemas, tablas delta, streaming tables, vistas materializadas, vistas SQL, volúmenes, modelos ML) mediante el canal SQL GRANT/REVOKE.

### Modified Capabilities

- (ninguna)

## Impact

- Nuevo código: adaptador del canal SQL, ejecutor de GRANT/REVOKE, verificador post-grant para objetos UC de datos.
- Depende de: `core-domain` (C1), `persistencia-bitacora` (C2) y `auth-caller-obo` (C3).
- Ejecuta grants reales en el workspace `andresFree` durante las pruebas de integración (con fixtures controlados).
- No requiere `andresAzureDev`.
