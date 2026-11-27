# AppDatabricksControlAccesosCentralizado

Aplicación (Databricks App) que **centraliza el otorgamiento de privilegios** sobre los objetos de Databricks, tanto del **plano de datos** (Unity Catalog) como del **plano de control** (workspace), resolviendo el problema de la administración de accesos descentralizada.

## Problema

Hoy, dar acceso en Databricks es un proceso fragmentado: cada tipo de objeto se autoriza por un mecanismo distinto (instrucciones SQL `GRANT`, Databricks SDK, Databricks REST API) y desde superficies distintas. Esto complica y hace lento otorgar accesos a catálogos, esquemas, tablas, cómputo, aplicaciones, tokens, etc.

## Solución

Una app **minimalista e intuitiva** que permite otorgar privilegios de forma centralizada sobre todos los objetos soportados, **actuando con los privilegios del usuario que la usa** (autenticación *on-behalf-of*): si el usuario no puede autorizar objetos del plano de datos pero sí del plano de control, la app ejecuta lo del plano de control y reporta "privilegios insuficientes" para lo demás — nunca aborta toda la operación.

### Objetos soportados y canales

| Plano de datos — Unity Catalog (canal SQL `GRANT`/`REVOKE`) | Plano de control (canal SDK/REST — Permissions API) |
|---|---|
| Catálogo | Cómputo clásico all-purpose (cluster) |
| Esquema | Cómputo serverless (interactivo y automated, vía *serverless compute objects*) |
| Tabla delta | SQL warehouse |
| Streaming table | Databricks App |
| Vista materializada | Uso de personal access token (Token Permissions API) |
| Vista SQL | |
| Volumen | |
| Modelo de ML (registered model) | |
| External location | |
| Connection de Unity Catalog | |

### Cardinalidades soportadas

- **1 a 1**: un principal, uno o varios privilegios, un objeto.
- **1 a N**: un principal, uno o varios privilegios, N objetos.
- **N a 1**: N principals, uno o varios privilegios, un objeto.
- **N a M**: **fuera de alcance** en esta versión (la app lo rechaza con mensaje explícito).

Un *principal* es un usuario, grupo o service principal.

### Arquitectura (pipeline)

```
Usuario (UI) -> PLAN -> PRE-FLIGHT -> EJECUTAR -> VERIFICAR -> REPORTE
                |         |             |            |           |
         construir    split por      por canal:    SHOW GRANTS  resultado
         solicitud    privilegios    SQL / SDK /   o lectura    por item:
                      del llamante   REST          de ACLs      otorgado /
                      (ejecutable                                fallido /
                       vs bloqueado)                             privilegios
                                                                 insuficientes
```

El corazón del dominio es la **matriz de compatibilidad privilegio x tipo de objeto** (declarativa): valida solicitudes, filtra la UI y genera mensajes de error precisos.

## Decisiones aprobadas

| # | Decisión | Valor |
|---|----------|-------|
| D1 | Stack UI | Python + Streamlit/Gradio, desplegado como **Databricks App** |
| D2 | Identidad | **On-behalf-of** (OAuth del usuario): la app actúa con los privilegios del llamante |
| D3 | Serverless | Gestionado vía *serverless compute objects* (Permissions API, `CAN_USE`/`CAN_MANAGE`). La activación del feature es **manual** y está fuera de la app |
| D4 | PAT | Token Permissions API (`authorization/tokens`, `CAN_USE`) |
| D5 | Workspaces de prueba | Primario: **`andresFree`** (Free Edition, perfil CLI). Backup: **`andresAzureDev`** (Azure + Unity Catalog + Enterprise, cómputo híbrido) — pruebas mínimas necesarias **pre-aprobadas** por el usuario (p. ej. cómputo clásico, que exige Enterprise); todo lo posible se prueba en Free Edition |
| D6 | Cardinalidades | 1 a 1, 1 a N, N a 1. **N a M fuera de alcance** |

## Plan de desarrollo: 10 changes OpenSpec

El desarrollo sigue el ciclo completo de OpenSpec (proposal → specs → design → tasks → implementación → archivo), **un change a la vez, en este orden**:

| Orden | Change | Contenido | Depende de |
|-------|--------|-----------|------------|
| C1 | `core-domain` | Modelo de dominio (`Principal`, `ObjetoSecurable`, `Privilegio`, `SolicitudGrant`, `ResultadoGrant`), **matriz privilegio x objeto**, contratos de canales (SQL/SDK/REST), pipeline plan→pre-flight→ejecutar→verificar→reporte. Aquí nace la infraestructura pytest (TDD, `python_functions = Test*`) | — |
| C2 | `persistencia-bitacora` | Archivo de propiedades `config/app_properties.json` (regla No HardCoded; atributo `catalogo`, default `control`), esquema delta dedicado `control_acceso_app` (idempotente), tablas `bitacora_eventos` (con `usuario`) y `bitacora_errores` (detalle `STRUCT<...>`) con liquid clustering + CDF + optimizeWrite + autoCompact, capa de persistencia POO con PySpark, integridad PK/FK en código | C1 |
| C3 | `auth-caller-obo` | Autenticación on-behalf-of, resolución de privilegios efectivos del llamante, clasificación por plano, **split ejecutable/bloqueado** con mensajes de privilegios insuficientes; alimenta el campo `usuario` de la bitácora | C1, C2 |
| C4 | `grants-uc-datos` | Grants 1 a 1 por canal SQL sobre catálogos, esquemas, tablas delta, streaming tables, vistas materializadas, vistas SQL, volúmenes y modelos ML. Primera *vertical slice* de punta a punta | C1–C3 |
| C5 | `grants-batch` | Cardinalidades 1 a N y N a 1 con resultados parciales por ítem y reporte consolidado; rechazo explícito de N a M | C1, C3, C4 |
| C6 | `grants-uc-externos` | Grants sobre external locations y connections de Unity Catalog (canal SQL) | C1–C5 |
| C7 | `grants-compute` | Grants sobre clusters clásicos, serverless compute objects y SQL warehouses (Permissions API). Tests de cómputo clásico solo en `andresAzureDev` con aprobación (`@pytest.mark.azure_approval`) | C1–C3, C5 |
| C8 | `grants-apps-tokens` | Grants sobre Databricks Apps y uso de personal access tokens (Permissions API + Token Permissions API) | C1–C3, C5, C7 |
| C9 | `web-ui-minimalista` | Interfaz Streamlit/Gradio como Databricks App: selección de principal/privilegios/objetos, previsualización del split, reporte por ítem | C1–C8 |
| C10 | `test-suite-e-informes` | Suite de aceptación formal trazable a los criterios de cada proposal + generador de **informes por change** (Markdown/HTML) e informe consolidado | C1–C9 |

Los `proposal.md` de los 10 changes ya están capturados en `openspec/changes/`. Los specs, design y tasks de cada change se desarrollan al llegar su turno en el ciclo.

## Estándar de desarrollo

### Convención de nombres
- Todo el desarrollo se hace en idioma **español**.
- Constantes: `NOMBRE_CONSTANTE` (mayúsculas, sin underscore inicial).
- Variables y objetos declarados: `snake_case` en minúscula.
- Clases: `PascalCase`.
- Funciones y métodos: `PascalCase` (pytest se configura con
  `python_functions = Test*` para descubrir las pruebas).
- Instrucciones SQL inyectadas en código Python: completamente en MAYÚSCULAS.

### Reglas
- **Configuración no hardcodeada (regla estricta)**: ningún valor fijo embebido
  en el código; todo valor se toma del archivo de propiedades de la aplicación
  `config/app_properties.json`. De momento contiene solo el atributo
  `"catalogo"` (valor por defecto: `control`); crecerá con el proyecto.
- **Persistencia**: toda tabla que necesite la app es una **tabla delta** en el
  esquema dedicado `control_acceso_app` (creado idempotentemente por la app en
  el catálogo configurado), y toda tabla es **idempotente**.
- Toda tabla delta lleva: **liquid clustering** (`CLUSTER BY`),
  **change data feed** (`delta.enableChangeDataFeed`),
  **optimizeWrite** (`delta.autoOptimize.optimizeWrite`) y
  **autoCompact** (`delta.autoOptimize.autoCompact`).
- **Bitácora de eventos generales**: tabla delta que registra todo lo que hace
  la app, incluido el `usuario` que provoca el evento (identidad OBO).
- **Bitácora de errores**: todo error se controla con try/except y se registra
  con el máximo detalle; el campo de detalle del error es de tipo `STRUCT<...>`.
- **Prohibido Lakebase** en esta versión.
- Comentarios detallados en cada bloque, método, función y clase.
- **POO** como vía principal de desarrollo.
- **PySpark al máximo**; bibliotecas tradicionales solo como fallback; cálculos
  masivos con funciones masivas de PySpark (p. ej. `withColumn`); ciclos solo
  en casos puntuales no optimizables.
- La integridad de llave primaria, llaves foráneas e integridad referencial se
  garantiza **desde el código de la aplicación** (Delta no las enforce).
- **Activación del entorno Python**: las bibliotecas de Python se activan con el
  comando `source ~/.venv/bin/activate`. Todo comando `python`, `pip` o
  `pytest` se ejecuta con ese entorno virtual activado (Python 3.14); sin la
  activación, los comandos caen en el Python del sistema, que no tiene las
  dependencias del proyecto.
- **Prohibición de instalación por la IA** (regla estricta): queda
  terminantemente prohibido que la IA instale cualquier biblioteca, bash,
  aplicación o binario en la Mac. Si la instalación de algo es necesaria, la IA
  debe solicitarla al humano y justificarla a detalle (qué se instala, para qué
  y su impacto). Solamente el humano puede aplicar la instalación, o bien dar
  su aprobación y autorización explícita a la IA para que la realice.
- **Secretos y datos de entorno de pruebas (regla estricta)**: ninguna
  credencial se versiona. Los datos sensibles que requiera una prueba (p. ej. el
  SQL Server de pruebas de la fixture de connection de C6) se leen de
  **variables de entorno** con prefijo `CONTROL_ACCESOS_`; la plantilla sin
  secretos está en `.env.example` (versionada) y el archivo local `.env` queda
  gitignoreado. Si faltan las variables, la fixture no se crea y la prueba se
  **salta con el motivo documentado**, nunca falla. Además, todo texto de error
  que se registre o se publique en informes debe **redactar** los valores
  sensibles antes de guardarse: el motor SQL devuelve los fallos de DDL con la
  sentencia completa, y esos textos acaban en el motivo del skip y en los JUnit
  XML de `results/`, que sí se versionan.

## Metodología: TDD y suite de testing

- **Test-Driven Development (TDD)**: primero la prueba que falla, luego la implementación mínima, luego refactor (red → green → refactor). La infraestructura pytest se crea en C1 y **cada `proposal.md` de C2–C10 declara TDD explícitamente** como método de implementación del change.
- **Suite por change** (obligatoria para completarlo):
  - **Unitarias**: lógica pura (matriz, validaciones, split, cardinalidades, reportes) con canales simulados.
  - **Funcionales**: flujo completo con canales *fake* que imitan respuestas y errores reales (`PERMISSION_DENIED`, objeto inexistente, etc.).
  - **Integrales**: contra workspace real, marcadas por perfil: `@pytest.mark.free` (`andresFree`) y `@pytest.mark.azure_approval` (`andresAzureDev`, omitidas por defecto).
  - **Aceptación**: trazables 1:1 a los criterios de aceptación del `proposal.md` del change.
- **Informes por change** (C10): durante C1–C9 cada change ejecuta y conserva los resultados de sus cuatro capas con `pytest --junitxml`. C10 agrega el generador y produce **retroactivamente** `reports/<change>/report.md|html` para C1–C9, con cada prueba, su capa y su resultado PASS/FAIL, más el informe consolidado del sistema. La generación formal de informes no bloquea la implementación ni la finalización de C1–C9; los changes futuros sí deberán generar su informe formal para ser archivados.

## Notas y limitaciones conocidas

- El control de acceso serverless aplica a notebooks, Databricks Connect, jobs y pipelines; **no** cubre DBSQL, Model Serving ni Databricks Apps (cada uno tiene su propio ACL, cubierto en C7/C8).
- Los serverless compute objects *default* no se renombran ni eliminan; la app solo gestiona sus permisos.
- Free Edition no dispone de cómputo clásico: esas pruebas de integración viven en `andresAzureDev` bajo aprobación.
- **Distribución de pruebas por entorno**: `andresFree` es el entorno primario y donde corre todo lo posible; las pruebas integrales en `andresAzureDev` se limitan al mínimo necesario que Free Edition no puede cubrir (por ejemplo, permisos sobre cómputo clásico) y están **pre-aprobadas** por el humano. El marker `azure_approval` las excluye de la suite por defecto (`pytest -m "not azure_approval"`); se ejecutan explícitamente con `pytest -m azure_approval`.
- **Fixtures integrales de objetos externos (C6)**: la external location se crea contra `andresAzureDev` descubriendo por API el storage credential y la cuenta del workspace (nada hardcodeado) sobre el contenedor de pruebas `test`; la connection se crea contra `andresFree` con los datos del SQL Server de pruebas tomados de variables de entorno (`CONTROL_ACCESOS_SQLSERVER_*`, ver `.env.example`). Sin esas variables exportadas, las integrales de connection se saltan con motivo documentado y el resto de la suite sigue en verde.

## Privilegios del service principal del modo broker

El change `app-broker-identidad-ejecucion` introduce un **modelo broker**: la
autorización se evalúa siempre con la identidad del llamante (OBO), y la
ejecución de las superficies que el token del usuario no cubre (SCIM y ACLs del
plano de control) la realiza el service principal de la App.

Como **recurso de despliegue** (asignado por el humano, design.md D5), el
service principal de la Databricks App recibe:

| Concepto | Valor |
|---|---|
| Service principal | `app-62644q control-accesos-spike` (applicationId `8be05e5d-0808-4698-a26f-1a5f7a4b63a0`) |
| Rol de workspace | **Workspace admin** (pertenencia directa al grupo SCIM `admins`) |
| Entitlement | `databricks-sql-access` → **Databricks SQL Access** |
| Entitlement | `workspace-access` → **Workspace Access** |
| Entitlement | `workspace-consume` → **Consumer Access** |
| Rollback | Retirar el SP del grupo `admins` y quitar los tres entitlements |

Estos privilegios habilitan la EJECUCIÓN; **no** sustituyen la autorización del
llamante: toda escritura broker exige validación previa de los privilegios
efectivos del llamante y su revalidación al confirmar (design.md D2 del change).
Cualquier propuesta de reducirlos se gestiona como un change de OpenSpec
separado con evidencia (spec `app-broker-grants`).

## Licencia

Ver [LICENSE](LICENSE).
