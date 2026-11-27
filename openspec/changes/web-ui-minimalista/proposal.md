# Proposal

## Why

Toda la capacidad de grants construida en C1-C8 necesita una interfaz de usuario minimalista e intuitiva (decisión D1: Python con Streamlit/Gradio desplegado como Databricks App) que permita al usuario seleccionar principal(es), privilegio(s) y objeto(s), y que respete sus privilegios actuales: mostrar lo ejecutable, bloquear lo no autorizado con el mensaje de privilegios insuficientes, y presentar el reporte de resultados por ítem.

## What Changes

- Aplicación web (Streamlit/Gradio) desplegable como Databricks App con autenticación on-behalf-of del usuario (C3).
- Flujo de usuario: selección de principal (usuario, grupo o service principal), selección de tipo de objeto y objeto concreto, selección de privilegios filtrados por la matriz (C1), previsualización del split ejecutable/bloqueado antes de ejecutar, ejecución y pantalla de reporte por ítem.
- Soporte en UI de las cardinalidades 1 a 1, 1 a N y N a 1; N a M no disponible (fuera de alcance, D6).
- Separación de dependencias de despliegue y de pruebas: `requirements.txt` para el runtime de la Databricks App (Streamlit y `databricks-sdk`; D5 revisado por el hallazgo F2: Connect es inviable en la imagen de la App y el SQL remoto usa Statement Execution API) y `requirements-dev.txt` para la suite (`pytest`, `pyspark`, `delta-spark`). Así el contenedor de la App no carga un Spark local innecesario.
- Filtrado dinámico de opciones según los privilegios efectivos del usuario llamante (los objetos sobre los que no tiene autorización se muestran como no disponibles con su mensaje).
- Modelo de identidad híbrido heredado del change archivado `app-broker-identidad-ejecucion` (GO): autorización siempre por llamante (OBO + pre-flight C3 + revalidación), ejecución con la credencial OBO para grants UC y ACL de Apps, y ejecución con la identidad de la App (modo broker) para SCIM y ACL del plano de control (warehouses, clusters, serverless, tokens) únicamente tras validar la autoridad del llamante. Cobertura total de tipos, sin recorte de alcance.
- App final **`SecurityManager`** (decisión humana 2026-11-27): dominio real Azure Databricks, ejecutable también en Free; `Workspace admin` del SP mantenido como configuración definitiva del broker; warehouse del SQL OBO resuelto desde la nueva propiedad **`IdWarehouse`** de `config/app_properties.json`, dinámica por entorno; en Azure la App permanece detenida fuera de las pruebas para evitar costos.
- Implementación guiada por **TDD** (red → green → refactor): toda funcionalidad de este change comienza con una prueba que falla antes de escribir el código que la satisface.
- Cobertura de testing: unitarias (lógica de presentación y filtrado), funcionales (flujo de UI con servicios simulados), integrales contra `andresFree` (despliegue de la app), y de aceptación (criterios de usabilidad y respeto de privilegios).
- Aplicación del **estándar de desarrollo del proyecto** (definido en README.md): código y comentarios detallados en español; constantes `NOMBRE_CONSTANTE` en mayúsculas; variables y objetos en `snake_case`; clases, funciones y métodos en `PascalCase`; instrucciones SQL en mayúsculas; POO como paradigma principal (la UI se estructura en clases de controladores/servicios, no en scripts sueltos); control de errores con try/except y registro en la bitácora de errores; **código no hardcodeado (regla estricta: todo valor parametrizado o configurable)**; PySpark preferente para el procesamiento masivo. Interfaz y mensajes al usuario en español.
- Aplicación de las **restricciones de entorno del proyecto** (regla estricta, definida en README.md): (1) las bibliotecas de Python se activan con el comando `source ~/.venv/bin/activate`, y todo comando `python`, `pip` o `pytest` de este change se ejecuta con ese entorno virtual activado (Python 3.14); sin la activación, los comandos caen en el Python del sistema, que no tiene las dependencias del proyecto; (2) **prohibición de instalación por la IA**: queda terminantemente prohibido que la IA instale cualquier biblioteca, bash, aplicación o binario en la Mac; si la instalación de algo es necesaria, la IA debe solicitarla al humano y justificarla a detalle (qué se instala, para qué y su impacto), y solamente el humano puede aplicar la instalación, o bien dar su aprobación y autorización explícita a la IA para que la realice.

## Capabilities

### New Capabilities

- `grant-management-ui`: Interfaz web minimalista para otorgar privilegios con cardinalidades 1 a 1, 1 a N y N a 1, que filtra opciones según la matriz de privilegios y los privilegios efectivos del usuario, previsualiza el split ejecutable/bloqueado y muestra el reporte de resultados por ítem.

### Modified Capabilities

- (ninguna)

## Impact

- Nuevo código: aplicación Streamlit/Gradio, configuración de despliegue como Databricks App (`app.yaml` o equivalente).
- Artefactos de dependencias separados: `requirements.txt` (runtime de la App) y `requirements-dev.txt` (pruebas), corrigiendo la mezcla heredada de C1/C2 donde `pyspark` y `delta-spark` viven en `requirements.txt` solo por la suite local.
- Depende de: todos los changes anteriores (C1-C8); en particular `auth-caller-obo` (C3), `grants-batch` (C5) y las familias de grants `grants-uc-datos` (C4), `grants-uc-externos` (C6), `grants-compute` (C7) y `grants-apps-tokens` (C8). Además depende del change archivado `app-broker-identidad-ejecucion`, que aporta la capability `app-broker-grants` (autorización por llamante con ejecución elevada condicionada), `FabricaContextoBroker`, `SesionSqlRemota` y `AgregadorReporteLotePython` ya implementados y verificados con gate GO.
- No introduce canales nuevos; consume exclusivamente las capacidades ya construidas.
