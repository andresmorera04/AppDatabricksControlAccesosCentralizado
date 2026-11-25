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
- Las pruebas de integración de clusters clásicos requieren `andresAzureDev` (Free Edition no tiene cómputo clásico) y se marcan con `pytest.mark.azure_approval`: excluidas por defecto de la suite (`-m "not azure_approval"`) y ejecutables explícitamente (`-m azure_approval`). **Autorización vigente (decisión del humano):** se aprueban de antemano las pruebas en Azure que sean estrictamente necesarias e imposibles en Free Edition —por ejemplo, permisos sobre cómputo clásico, que exige Databricks Enterprise—; todo lo demás se prueba en `andresFree`, que sigue siendo el entorno primario. Se incluye un spike para verificar disponibilidad del feature serverless en Free Edition.
- Aplicación de las **restricciones de entorno del proyecto** (regla estricta, definida en README.md): (1) las bibliotecas de Python se activan con el comando `source ~/.venv/bin/activate`, y todo comando `python`, `pip` o `pytest` de este change se ejecuta con ese entorno virtual activado (Python 3.14); sin la activación, los comandos caen en el Python del sistema, que no tiene las dependencias del proyecto; (2) **prohibición de instalación por la IA**: queda terminantemente prohibido que la IA instale cualquier biblioteca, bash, aplicación o binario en la Mac; si la instalación de algo es necesaria, la IA debe solicitarla al humano y justificarla a detalle (qué se instala, para qué y su impacto), y solamente el humano puede aplicar la instalación, o bien dar su aprobación y autorización explícita a la IA para que la realice.

## Capabilities

### New Capabilities

- `compute-grants`: Otorgamiento y verificación de privilegios sobre objetos de cómputo (clusters clásicos, serverless compute objects interactivos y automated, SQL warehouses) mediante la Permissions API (SDK/REST).

### Modified Capabilities

- (ninguna)

## Impact

- Nuevo código: adaptador del canal SDK/REST para Permissions API, soporte de los tipos de objeto de cómputo.
- Depende de: `core-domain` (C1), `persistencia-bitacora` (C2), `auth-caller-obo` (C3) y `grants-batch` (C5).
- Uso del workspace `andresAzureDev` limitado al mínimo necesario y pre-aprobado por el humano (decisión D5 actualizada); todo lo posible se prueba en `andresFree`.
