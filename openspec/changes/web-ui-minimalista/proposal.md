# Proposal

## Why

Toda la capacidad de grants construida en C1-C8 necesita una interfaz de usuario minimalista e intuitiva (decisión D1: Python con Streamlit/Gradio desplegado como Databricks App) que permita al usuario seleccionar principal(es), privilegio(s) y objeto(s), y que respete sus privilegios actuales: mostrar lo ejecutable, bloquear lo no autorizado con el mensaje de privilegios insuficientes, y presentar el reporte de resultados por ítem.

## What Changes

- Aplicación web (Streamlit/Gradio) desplegable como Databricks App con autenticación on-behalf-of del usuario (C3).
- Flujo de usuario: selección de principal (usuario, grupo o service principal), selección de tipo de objeto y objeto concreto, selección de privilegios filtrados por la matriz (C1), previsualización del split ejecutable/bloqueado antes de ejecutar, ejecución y pantalla de reporte por ítem.
- Soporte en UI de las cardinalidades 1 a 1, 1 a N y N a 1; N a M no disponible (fuera de alcance, D6).
- Separación de dependencias de despliegue y de pruebas: `requirements.txt` para el runtime de la Databricks App (`databricks-sdk` y/o `databricks-connect` según el canal elegido) y `requirements-dev.txt` para la suite (`pytest`, `pyspark`, `delta-spark`). Así el contenedor de la App no carga un Spark local innecesario ni entra en conflicto con Databricks Connect (que exige `pyspark` no instalado).
- Filtrado dinámico de opciones según los privilegios efectivos del usuario llamante (los objetos sobre los que no tiene autorización se muestran como no disponibles con su mensaje).
- Implementación guiada por **TDD** (red → green → refactor): toda funcionalidad de este change comienza con una prueba que falla antes de escribir el código que la satisface.
- Cobertura de testing: unitarias (lógica de presentación y filtrado), funcionales (flujo de UI con servicios simulados), integrales contra `andresFree` (despliegue de la app), y de aceptación (criterios de usabilidad y respeto de privilegios).
- Aplicación del **estándar de desarrollo del proyecto** (definido en README.md): código y comentarios detallados en español; constantes `NOMBRE_CONSTANTE` en mayúsculas; variables y objetos en `snake_case`; clases, funciones y métodos en `PascalCase`; instrucciones SQL en mayúsculas; POO como paradigma principal (la UI se estructura en clases de controladores/servicios, no en scripts sueltos); control de errores con try/except y registro en la bitácora de errores; **código no hardcodeado (regla estricta: todo valor parametrizado o configurable)**; PySpark preferente para el procesamiento masivo. Interfaz y mensajes al usuario en español.

## Capabilities

### New Capabilities

- `grant-management-ui`: Interfaz web minimalista para otorgar privilegios con cardinalidades 1 a 1, 1 a N y N a 1, que filtra opciones según la matriz de privilegios y los privilegios efectivos del usuario, previsualiza el split ejecutable/bloqueado y muestra el reporte de resultados por ítem.

### Modified Capabilities

- (ninguna)

## Impact

- Nuevo código: aplicación Streamlit/Gradio, configuración de despliegue como Databricks App (`app.yaml` o equivalente).
- Artefactos de dependencias separados: `requirements.txt` (runtime de la App) y `requirements-dev.txt` (pruebas), corrigiendo la mezcla heredada de C1/C2 donde `pyspark` y `delta-spark` viven en `requirements.txt` solo por la suite local.
- Depende de: todos los changes anteriores (C1-C8); en particular `auth-caller-obo` (C3), `grants-batch` (C5) y las familias de grants `grants-uc-datos` (C4), `grants-uc-externos` (C6), `grants-compute` (C7) y `grants-apps-tokens` (C8).
- No introduce canales nuevos; consume exclusivamente las capacidades ya construidas.
