# Proposal

## Why

El proyecto exige una suite completa de testing —unitarias, funcionales, integrales y de aceptación— cuyos resultados generen informes por change con el detalle de cada prueba y su resultado (PASS/FAIL). Aunque la infraestructura de pytest nace en C1 (TDD), falta la consolidación formal: la suite de aceptación trazable 1:1 a los criterios de aceptación de cada proposal y el generador de informes por change en Markdown/HTML. Para evitar una dependencia circular, C1–C9 entregan y conservan los resultados JUnit XML de sus cuatro capas; C10 genera retroactivamente los informes formales de C1–C9 y deja el generador disponible para los changes futuros, sin que la generación de esos informes formales bloquee la implementación de C1–C9.

## What Changes

- Suite de aceptación formal: pruebas derivadas 1:1 de los criterios de aceptación de los `proposal.md` de todos los changes anteriores (C1-C9), trazables al criterio que verifican.
- Generador de informes por change: agrega los resultados JUnit XML conservados por C1–C9 (`pytest --junitxml`) y produce, retroactivamente para esos changes, `reports/<change>/report.md` y `report.html` con cada prueba, su capa (unitaria, funcional, integral, aceptación), su descripción y su resultado PASS/FAIL.
- Organización de marcadores de pytest: `unit`, `functional`, `integration`, `acceptance`, `free` (workspace `andresFree`) y `azure_approval` (requieren aprobación expresa para usar `andresAzureDev`, omitidas por defecto).
- Verificación de la suite completa sobre todos los changes anteriores (C1-C9): el informe consolidado certifica el estado del sistema. La generación formal de informes en C10 no es un prerrequisito para implementar o completar C1-C9.
- Implementación guiada por **TDD** (red → green → refactor): toda funcionalidad de este change comienza con una prueba que falla antes de escribir el código que la satisface.
- Cobertura de testing: unitarias (generación y agregación del informe), funcionales (formato Markdown/HTML a partir de resultados controlados), integrales (ejecución real de pytest y lectura de sus archivos JUnit XML), y de aceptación (cada informe incluye prueba, capa, descripción y PASS/FAIL, y la aceptación es trazable a los criterios de C1-C9).
- Aplicación del **estándar de desarrollo del proyecto** (definido en README.md): código y comentarios detallados en español; constantes `NOMBRE_CONSTANTE` en mayúsculas; variables y objetos en `snake_case`; clases, funciones y métodos en `PascalCase` (las pruebas se descubren con la configuración pytest `python_functions = Test*` definida en C1); instrucciones SQL en mayúsculas; POO como paradigma principal; control de errores con try/except y registro en la bitácora de errores; **código no hardcodeado (regla estricta: todo valor parametrizado o configurable)**; PySpark preferente para el procesamiento masivo.

## Capabilities

### New Capabilities

- `test-reporting`: Generación de informes de pruebas por change (Markdown/HTML) con detalle de cada prueba, su capa y su resultado, a partir de los resultados JUnit XML conservados por cada change, incluidos los informes retroactivos de C1–C9 y el informe consolidado del sistema.

### Modified Capabilities

- (ninguna)

## Impact

- Nuevo código: generador de informes, configuración de marcadores pytest, suite de aceptación formal.
- Depende de: todos los changes anteriores (C1-C9), cuyos criterios de aceptación y resultados JUnit XML alimentan la suite y los informes.
- Artefacto generado: `reports/` (no código de producción); los informes históricos de C1–C9 se generan cuando se implementa C10.
- Cierra el ciclo de desarrollo del proyecto; tras este change, cada change futuro debe generar su informe formal para ser archivado.
