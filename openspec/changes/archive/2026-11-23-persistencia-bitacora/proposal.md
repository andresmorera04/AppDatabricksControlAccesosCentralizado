# Proposal

## Why

El estándar de desarrollo del proyecto exige persistencia sobre tablas delta en un esquema dedicado, bitácora de eventos generales (con el usuario que provoca el evento) y bitácora de errores (con detalle tipo `STRUCT<...>`), además de la regla estricta de código no hardcodeado que requiere un archivo de propiedades como fuente única de configuración. Ningún change existente cubre esta persistencia ni estas bitácoras; sin ellas, los changes posteriores no pueden cumplir el estándar (registro de grants, errores y actividad de la app).

## What Changes

- Módulo de configuración: carga del archivo de propiedades de la aplicación `config/app_properties.json`, fuente única de configuración (regla estricta No HardCoded). De momento contiene solo el atributo `"catalogo"` (valor por defecto: `control`); crecerá con el proyecto.
- Creación idempotente del esquema dedicado `control_acceso_app` en el catálogo configurado, al arrancar la app.
- Tabla delta `bitacora_eventos`: registra todo lo que hace la app, incluido el campo `usuario` (alimentado por la identidad on-behalf-of del change `auth-caller-obo`).
- Tabla delta `bitacora_errores`: registra todo error controlado vía try/except con el máximo detalle; el campo de detalle del error es de tipo `STRUCT<...>`.
- Todas las tablas delta con liquid clustering (`CLUSTER BY`), change data feed (`delta.enableChangeDataFeed`), optimizeWrite (`delta.autoOptimize.optimizeWrite`) y autoCompact (`delta.autoOptimize.autoCompact`); creación idempotente (`CREATE TABLE IF NOT EXISTS`).
- Capa de persistencia POO con escritura vía PySpark (funciones masivas; sin ciclos por fila).
- Helpers de integridad en código: cumplimiento de llave primaria, llaves foráneas e integridad referencial desde la aplicación (Delta no las enforce).
- Implementación guiada por **TDD** (red → green → refactor): toda funcionalidad de este change comienza con una prueba que falla antes de escribir el código que la satisface.
- Cobertura de testing: unitarias (carga de configuración, DDL de tablas, helpers de integridad), funcionales (capa de persistencia con Spark local), integrales contra `andresFree` (creación real e idempotente del esquema y las tablas), y de aceptación.
- Aplicación del **estándar de desarrollo del proyecto** (definido en README.md): código y comentarios detallados en español; constantes `NOMBRE_CONSTANTE` en mayúsculas; variables y objetos en `snake_case`; clases, funciones y métodos en `PascalCase`; instrucciones SQL en mayúsculas; POO como paradigma principal; control de errores con try/except y registro en la bitácora de errores; **código no hardcodeado (regla estricta: todo valor parametrizado o configurable)**; PySpark preferente para el procesamiento masivo.

## Capabilities

### New Capabilities

- `app-configuration`: Archivo de propiedades JSON (`config/app_properties.json`) como fuente única de configuración de la aplicación; carga y acceso parametrizado a sus atributos (de momento `catalogo`, valor por defecto `control`).
- `app-persistence`: Esquema delta dedicado (`control_acceso_app`) y tablas delta de la aplicación, creadas idempotentemente con liquid clustering, change data feed, optimizeWrite y autoCompact, con integridad de llave primaria, foránea y referencial garantizada desde el código.
- `audit-logging`: Bitácora de eventos generales (registra toda la actividad de la app con el usuario que provoca cada evento) y bitácora de errores (detalle del error en campo tipo `STRUCT<...>`), alimentadas por el control de errores try/except de toda la aplicación.

### Modified Capabilities

- (ninguna)

## Impact

- Nuevo código: módulo de configuración, capa de persistencia, DDL de esquema y tablas, helpers de integridad, servicios de escritura de bitácoras.
- Nuevo artefacto: `config/app_properties.json` con `{"catalogo": "control"}`.
- Depende de: `core-domain` (C1).
- Prerrequisito de: `auth-caller-obo` (C3, campo `usuario` de la bitácora de eventos) y de todos los changes que registran actividad o errores (C4 en adelante).
- Las pruebas de integración crean el esquema y las tablas en `andresFree`; no requiere `andresAzureDev`.
