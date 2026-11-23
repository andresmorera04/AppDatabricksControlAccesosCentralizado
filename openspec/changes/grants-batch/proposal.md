# Proposal

## Why

El requisito del proyecto incluye cardinalidades más allá del 1 a 1: 1 a N (un principal con uno o varios privilegios sobre N objetos) y N a 1 (N principals sobre un objeto). Estas operaciones por lote deben ejecutarse con resultados parciales por ítem — un fallo o una falta de privilegios en un ítem no aborta el lote — y producir un reporte consolidado. La cardinalidad N a M queda explícitamente fuera de esta versión (decisión D6).

## What Changes

- Extensión del modelo de solicitud para soportar cardinalidades 1 a N y N a 1, normalizándolas internamente a una lista de ítems (principal, privilegio, objeto).
- Orquestación por lote sobre el pipeline de C1: pre-flight con split por ítem (C3), ejecución ítem a ítem por el canal que corresponda a cada objeto, y verificación por ítem.
- Reporte consolidado del lote: totales por estado (otorgado, fallido, privilegios insuficientes) y detalle por ítem.
- Validación explícita que rechaza solicitudes N a M con mensaje de funcionalidad fuera de alcance.
- Implementación guiada por **TDD** (red → green → refactor): toda funcionalidad de este change comienza con una prueba que falla antes de escribir el código que la satisface.
- Cobertura de testing: unitarias (normalización, orquestación con canales simulados, reporte), funcionales (lotes con fallos parciales simulados), integrales contra `andresFree`, y de aceptación.
- Aplicación del **estándar de desarrollo del proyecto** (definido en README.md): código y comentarios detallados en español; constantes `NOMBRE_CONSTANTE` en mayúsculas; variables y objetos en `snake_case`; clases, funciones y métodos en `PascalCase`; instrucciones SQL en mayúsculas; POO como paradigma principal; control de errores con try/except y registro en la bitácora de errores; **código no hardcodeado (regla estricta: todo valor parametrizado o configurable)**; PySpark preferente para el procesamiento masivo. La agregación del reporte consolidado del lote usa funciones masivas de PySpark (sin ciclos por fila); cada ítem del lote se registra en la bitácora de eventos.
- Aplicación de las **restricciones de entorno del proyecto** (regla estricta, definida en README.md): (1) las bibliotecas de Python se activan con el comando `source ~/.venv/bin/activate`, y todo comando `python`, `pip` o `pytest` de este change se ejecuta con ese entorno virtual activado (Python 3.14); sin la activación, los comandos caen en el Python del sistema, que no tiene las dependencias del proyecto; (2) **prohibición de instalación por la IA**: queda terminantemente prohibido que la IA instale cualquier biblioteca, bash, aplicación o binario en la Mac; si la instalación de algo es necesaria, la IA debe solicitarla al humano y justificarla a detalle (qué se instala, para qué y su impacto), y solamente el humano puede aplicar la instalación, o bien dar su aprobación y autorización explícita a la IA para que la realice.

## Capabilities

### New Capabilities

- `batch-grant-operations`: Otorgamiento de privilegios por lote con cardinalidades 1 a N y N a 1, con resultados parciales por ítem, reporte consolidado y rechazo explícito de cardinalidad N a M.

### Modified Capabilities

- `grant-domain-model`: La solicitud de grant se extiende para representar lotes 1 a N y N a 1 (lista de principals o lista de objetos), manteniendo el ítem 1 a 1 como unidad interna de ejecución.

## Impact

- Nuevo código: normalizador de solicitudes por lote, orquestador de lotes, agregador de reportes.
- Depende de: `core-domain` (C1), `auth-caller-obo` (C3) y `grants-uc-datos` (C4) como primera familia ejecutable en lote.
- Habilita el modo por lote para todas las familias posteriores (C6-C8) sin cambios adicionales en ellas.
