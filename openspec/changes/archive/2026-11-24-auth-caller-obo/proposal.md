# Proposal

## Why

La aplicación debe actuar con los privilegios del usuario que la usa (decisión D2: autenticación on-behalf-of), no con los de un service principal con permisos elevados. Esto exige dos cosas: (1) autenticar al llamante vía OAuth on-behalf-of en la Databricks App, y (2) resolver los privilegios efectivos de ese llamante sobre cada objeto objetivo ANTES de ejecutar, para dividir la solicitud en ítems ejecutables e ítems bloqueados con el mensaje "privilegios insuficientes" — en lugar de abortar toda la operación. Este comportamiento de respeto parcial de privilegios es un requisito central del proyecto.

## What Changes

- Autenticación on-behalf-of (user authorization) del usuario llamante en el contexto de Databricks Apps; obtención de la identidad del llamante (usuario y sus grupos).
- Resolución de privilegios efectivos del llamante sobre cada objeto securable objetivo (vía `SHOW GRANTS`, effective-permissions API y Permissions API según el canal del objeto).
- Uso de la clasificación por plano (datos/control) definida en C1 para clasificar cada ítem de la solicitud como ejecutable o bloqueado (split), con mensaje explícito de privilegios insuficientes que indica objeto, privilegio requerido y privilegio faltante.
- Integración del split como fase de pre-flight del pipeline definido en C1 (`core-domain`).
- Implementación guiada por **TDD** (red → green → refactor): toda funcionalidad de este change comienza con una prueba que falla antes de escribir el código que la satisface.
- Cobertura de testing: unitarias (lógica de split con resolutores simulados), funcionales (respuestas y errores reales simulados de las APIs), integrales contra el workspace `andresFree`, y de aceptación.
- Aplicación del **estándar de desarrollo del proyecto** (definido en README.md): código y comentarios detallados en español; constantes `NOMBRE_CONSTANTE` en mayúsculas; variables y objetos en `snake_case`; clases, funciones y métodos en `PascalCase`; instrucciones SQL en mayúsculas; POO como paradigma principal; control de errores con try/except y registro en la bitácora de errores; **código no hardcodeado (regla estricta: todo valor parametrizado o configurable)**; PySpark preferente para el procesamiento masivo. La identidad on-behalf-of del llamante alimenta el campo `usuario` de la bitácora de eventos.
- Aplicación de las **restricciones de entorno del proyecto** (regla estricta, definida en README.md): (1) las bibliotecas de Python se activan con el comando `source ~/.venv/bin/activate`, y todo comando `python`, `pip` o `pytest` de este change se ejecuta con ese entorno virtual activado (Python 3.14); sin la activación, los comandos caen en el Python del sistema, que no tiene las dependencias del proyecto; (2) **prohibición de instalación por la IA**: queda terminantemente prohibido que la IA instale cualquier biblioteca, bash, aplicación o binario en la Mac; si la instalación de algo es necesaria, la IA debe solicitarla al humano y justificarla a detalle (qué se instala, para qué y su impacto), y solamente el humano puede aplicar la instalación, o bien dar su aprobación y autorización explícita a la IA para que la realice.

## Capabilities

### New Capabilities

- `caller-identity`: Autenticación on-behalf-of del usuario llamante y resolución de su identidad dentro de la Databricks App. La identidad resuelta es un principal de la enumeración del dominio (usuario, grupo o service principal — este último identificado por su App Id) junto con los grupos de los que es miembro.
- `caller-privilege-resolution`: Resolución de los privilegios efectivos del llamante sobre objetos de ambos planos y división (split) de una solicitud de grant en ítems ejecutables e ítems bloqueados con mensajes de privilegios insuficientes.

### Modified Capabilities

- (ninguna)

## Impact

- Nuevo código: módulo de autenticación OBO, resolutor de privilegios efectivos por canal, fase de split en el pipeline.
- Depende de: `core-domain` (C1) y `persistencia-bitacora` (C2), que aporta las bitácoras cuyo campo `usuario` alimenta este change.
- Afecta a todos los changes de grants (C4-C8): ninguno ejecuta sin pasar por el split de pre-flight.
- Integración verificable en el workspace `andresFree`; no requiere `andresAzureDev`.
