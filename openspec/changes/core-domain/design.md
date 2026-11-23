# Design

## Context

Proyecto verde: el repositorio solo contiene `README.md`, `LICENSE` y la estructura `openspec/`; no existe código fuente ni infraestructura de pruebas. Este change (C1) crea el cimiento de dominio del que dependen C2 a C10 (ver `proposal.md` - Why). El estándar de desarrollo obligatorio (README.md - Estándar de desarrollo) aplica a todo el código: español, POO, nombres `PascalCase` para clases/funciones, constantes en mayúsculas, SQL en mayúsculas, sin hardcodeo, TDD con `python_functions = Test*`.

Las decisiones aprobadas D1-D6 del README delimitan este change: la UI (D1) y la identidad OBO (D2) llegan en changes posteriores; aquí solo se define el dominio, la matriz, los contratos de canales y el pipeline, ejecutados contra canales simulados (ver specs `channel-adapters` - "En este change no se ejecutan operaciones externas reales").

Restricciones del entorno de desarrollo: (1) todo uso de Python y sus bibliotecas (pip, pytest, la instalación de `requirements.txt`) requiere activar primero el entorno virtual del usuario con `source ~/.venv/bin/activate` (Python 3.14); sin esa activación, los comandos caen en el Python del sistema, que no tiene las dependencias del proyecto. (2) Regla estricta del proyecto: la IA no puede instalar por su cuenta ninguna biblioteca, bash, aplicación o binario en la Mac; toda instalación se solicita al humano con justificación a detalle y solo procede con su aprobación y autorización explícita (ver README.md - Estándar de desarrollo). Por ello, la instalación de `requirements.txt` en la tarea 1.2 se ejecuta con esa aprobación o directamente por el humano.

## Goals / Non-Goals

**Goals:**

- Paquete Python `control_accesos` con el modelo de dominio, la matriz de privilegios, los contratos de canales y el orquestador del pipeline, implementados con POO y TDD (red -> green -> refactor).
- Infraestructura pytest del proyecto (configurada con `python_functions = Test*`) y suite de C1: pruebas unitarias, funcionales (canales simulados) y de aceptación trazables a los specs.
- Resultados por ítem y reporte del pipeline como contratos estables para C4-C10.

**Non-Goals:**

- Implementaciones reales de los canales (SQL sobre workspace, SDK, REST): solo contratos y simulaciones; llegan en C4 en adelante.
- Autenticación OBO y split por privilegios del llamante (C3): el pre-flight de C1 valida contra la matriz, no contra privilegios efectivos.
- Persistencia (bitácoras delta, `config/app_properties.json` con esquema `control_acceso_app`): es C2. En C1 no hay valores configurables en tiempo de ejecución; la matriz es conocimiento del dominio, no configuración, por lo que la regla "no hardcodeado" no obliga a crear el archivo de propiedades todavía.
- PySpark: no hay procesamiento masivo en C1 (colecciones pequeñas de ítems); PySpark nace en C2 con la persistencia.
- Cardinalidades 1 a N y N a 1 (C5): `SolicitudGrant` queda definida para cardinalidad 1 a 1, que es la unidad atómica reutilizable por C5.
- Informes formales por change (C10): C1 conserva sus resultados con `pytest --junitxml` pero no genera `reports/`.

## Decisions

### D1. Layout: paquete `control_accesos` plano con subpaquetes por capability

```
control_accesos/
  __init__.py
  dominio/        -> enumeraciones, modelos, errores (grant-domain-model)
  matriz/         -> declaración de la matriz y clase consultora (privilege-matrix)
  canales/        -> contratos ABC + paquete simulados/ con los fakes (channel-adapters)
  pipeline/       -> orquestador y fases (grant-pipeline)
config/
pytest.ini
requirements.txt
tests/
  unitarias/      -> lógica pura con fakes
  funcionales/    -> flujo completo del pipeline con canales simulados
  aceptacion/     -> trazables 1:1 a los escenarios de los specs
```

Racional: un subpaquete por capability mantiene el mapeo spec -> código trazable para los changes posteriores. Alternativa descartada: un único módulo monolítico (dificulta que C4-C10 extiendan canales y matriz de forma aislada).

### D2. Modelo de dominio con dataclasses y enumeraciones tipadas

- Enumeraciones `enum.Enum` para `TipoPrincipal` (USUARIO, GRUPO, SERVICE_PRINCIPAL), `TipoObjeto` (CATALOGO, ESQUEMA, TABLA_DELTA, STREAMING_TABLE, VISTA_MATERIALIZADA, VISTA_SQL, VOLUMEN, MODELO_ML, EXTERNAL_LOCATION, CONNECTION, COMPUTO_CLASICO, COMPUTO_SERVERLESS, SQL_WAREHOUSE, DATABRICK_APP, USO_TOKEN) y `Plano` (DATOS, CONTROL); miembros en mayúsculas por ser constantes.
- Dataclasses para `Principal`, `ObjetoSecurable` (deriva su `Plano` del `TipoObjeto` en un mapa declarado, no por lógica if dispersa), `SolicitudGrant`, `ItemGrant` (unidad atómica principal-privilegio-objeto) y `ResultadoItem` (estado `EstadoItem`: OTORGADO, FALLIDO, PRIVILEGIOS_INSUFICIENTES + detalle).
- Validación en constructores / fábricas (`SolicitudGrant.Crear(...)`) que rechazan formas inválidas (N a M, listas vacías, tipos fuera de enumeración) con excepciones propias de dominio (`ErrorDominio`), mensajes explícitos en español.

Racional: dataclasses + enums mantienen el dominio inmutable y tipado sin acoplarse a frameworks. Alternativa descartada: pydantic (dependencia extra innecesaria en una capa pura).

### D3. Matriz declarada como dato en un módulo dedicado, consultable vía una clase

La matriz privilegio x tipo de objeto vive en `matriz/` como diccionario declarativo (`MATRIZ_PRIVILEGIOS: dict[TipoObjeto, frozenset[str]]`), consumido por una clase consultora POO que responde: privilegios válidos por tipo, validez de una combinación, mensajes de error con alternativas y opciones filtrables para UI. Agregar un tipo = agregar una entrada al diccionario, sin tocar lógica (ver spec `privilege-matrix` - "Declarativa y extensible").

Racional: conocimiento del dominio, no configuración de despliegue; por eso es un módulo de datos Python (tipado, navegable, versionado con el código) y no JSON en `config/`. Alternativa descartada: JSON externo (perdería tipado y validación estática; el archivo de propiedades nace en C2 para valores de entorno). Los conjuntos exactos de privilegios se toman de la documentación oficial de Databricks al implementar y quedan fijados por las pruebas de aceptación.

### D4. Contratos de canales como ABC propias del dominio, acoplamiento cero con SDK/REST

`canales/contratos.py` define `CanalDatos` (otorgar/revocar por SQL y listar grants vigentes) y `CanalControl` (otorgar/revocar vía Permissions API / Token Permissions API) como clases abstractas: reciben un `ItemGrant` validado y devuelven `ResultadoItem`, marcando distinguible el error de privilegios insuficientes (excepción/tipo propio `ErrorPrivilegiosInsuficientes` traducido por el canal desde la respuesta del sistema externo). El paquete `canales/simulados/` implementa los fakes configurables por escenario (éxito, permiso denegado, objeto inexistente).

Racional: los contratos usan tipos propios del dominio, no tipos del SDK, para que las pruebas funcionales y el pipeline no dependan de la versión del SDK; `databricks-sdk` se declara en `requirements.txt` y se consume desde C4, cuando existan implementaciones reales. Esto refina la dependencia mencionada en el proposal sin cambiar el comportamiento observable (ver spec `channel-adapters`). Alternativa descartada: interfaces anotadas con tipos SDK (forzaría a los fakes a construir objetos SDK y acoplaría el dominio a una versión externa).

### D5. Pipeline orquestado por una clase, una fase = una clase

`pipeline/pipeline_grants.py` con `PipelineGrants` como orquestador que inyecta la matriz y los canales, y ejecuta en orden las fases como colaboradores: `Planificador` (expande la solicitud en ítems atómicos), `PreFlight` (clasifica ejecutable/bloqueado contra la matriz), `Ejecutor` (enruta por plano: DATOS -> canal de datos, CONTROL -> canal de control; un fallo no interrumpe los demás ítems), `Verificador` (reconsulta grants vigentes post-grant y convierte discrepancias en FALLIDO) y `Reportador` (consolida resultados por ítem con la trazabilidad de fases). Todo el flujo con try/except que captura al nivel de ítem y enriquece el detalle del resultado.

Racional: inyección de dependencias hace que C3 (split por privilegios del llamante) y C4 (canales reales) sustituyan colaboradores sin tocar el orquestador. Alternativa descartada: funciones libres encadenadas (viola POO y dificulta la inyección de canales simulados).

### D6. TDD desde la primera tarea; pytest con `python_functions = Test*`

`pytest.ini` define `python_functions = Test*` (exigido por el estándar: funciones en PascalCase) y registra desde ya los markers futuros `free` y `azure_approval` (las integrales se usan desde C4; `--strict-markers` los valida). Cada tarea de `tasks.md` sigue red -> green -> refactor: primero la prueba que falla, luego la implementación mínima, luego refactor. La suite se organiza por capa (`tests/unitarias/`, `tests/funcionales/`, `tests/aceptacion/`) y las de aceptación se nombran para trazarse 1:1 con los escenarios de los specs.

Racional: la infraestructura de pruebas es entregable de C1 ("aquí nace la práctica TDD del proyecto"); definirla primero evita reorganizar la suite en C2. Alternativa descartada: `pyproject.toml` (equivalente, pero `pytest.ini` es explícito y no arrastra tooling de empaquetado que este change no necesita).

## Risks / Trade-offs

- [La matriz podría desviar de los privilegios reales que Databricks acepta por tipo de objeto] -> Los conjuntos se fijan desde la documentación oficial en la implementación, quedan congelados por pruebas de aceptación, y C4 (grants reales sobre `andresFree`) los contrasta; corregirlos es editar una entrada del diccionario, sin tocar lógica.
- [Contratos inventados podrían no encajar con la forma real del SDK/Permissions API en C4] -> Los contratos son mínimos (ítem -> resultado) y del dominio; si la API real exige más datos (p. ej. ACL del workspace), se extiende la ABC sin romper fakes ni pipeline.
- [Los fakes pueden falsear el comportamiento real (respuestas demasiado idealizadas)] -> Los fakes se configuran con respuestas documentadas de la API (`PERMISSION_DENIED`, objeto inexistente) y las integrales de C4+ son la capa que detecta la desviación.
- [`python_functions = Test*` es una convención no estándar de pytest] -> Configuración explícita en `pytest.ini` y una prueba unitaria de humo que garantiza el descubrimiento; cualquier colaborador ve la convención en el README y el pytest.ini.
- [Dominio tipado a mano puede desincronizarse de Databricks (nuevos tipos de objeto/privilegios)] -> Enumeraciones y matriz son los dos únicos puntos de extensión declarados; C7/C8 los extienden por diseño (ver spec `privilege-matrix` - escenario de extensión).

## Migration Plan

Código nuevo sin usuarios ni despliegue: no hay migración ni estrategia de rollback. El change se integra a `develop` por PR y los changes posteriores dependen de las ABC y dataclasses aquí definidas; cualquier cambio posterior al modelo se hace como MODIFIED requirement en su propio change.
