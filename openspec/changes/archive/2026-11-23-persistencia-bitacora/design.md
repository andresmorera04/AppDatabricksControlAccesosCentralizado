# Design

## Context

C1 (`core-domain`) está archivado: existe el paquete `control_accesos` organizado en subpaquetes por capability (`dominio/`, `matriz/`, `canales/`, `pipeline/`), la infraestructura pytest (`pytest.ini` con `python_functions = Test*`, markers `free`/`azure_approval`, `--strict-markers`) y la suite por capas (`tests/unitarias|funcionales|aceptacion/`). Este change (C2) agrega la persistencia de la que dependen C3 en adelante (ver `proposal.md` - Why): configuración no hardcodeada, esquema delta dedicado, bitácoras y helpers de integridad.

Aún no existe nada de lo que este change introduce: no hay `config/app_properties.json`, ni módulo de configuración, ni sesión Spark, ni tablas delta. PySpark no se ha usado en el proyecto (C1 lo pospuso explícitamente a C2).

Restricciones del entorno (heredadas del estándar, ver README.md): (1) todo comando `python`/`pip`/`pytest` requiere activar primero el entorno virtual con `source ~/.venv/bin/activate` (Python 3.14); (2) regla estricta: la IA no instala bibliotecas por su cuenta — `pyspark` y `delta-spark` se declaran en `requirements.txt` y su instalación se solicita al humano con justificación a detalle; solo procede con su aprobación explícita o la ejecuta el propio humano; (3) las pruebas integrales corren contra el workspace `andresFree` (perfil CLI, marker `free`); `andresAzureDev` queda fuera de este change.

## Goals / Non-Goals

**Goals:**

- Archivo de propiedades `config/app_properties.json` con `{"catalogo": "control"}` y módulo de configuración POO con carga validada y acceso parametrizado de solo lectura (capability `app-configuration`).
- Inicialización idempotente del esquema `control_acceso_app` y de las tablas `bitacora_eventos` y `bitacora_errores` con liquid clustering, CDF, optimizeWrite y autoCompact (capabilities `app-persistence` y `audit-logging`).
- Capa de persistencia POO con escritura masiva vía PySpark y helpers de integridad PK/FK/referencial verificados en código antes de escribir (capability `app-persistence`).
- Escritores de bitácora de eventos (con `usuario` OBO opcional) y de errores (detalle `STRUCT<...>`), con degradación controlada ante el fallo de la propia bitácora (capability `audit-logging`).
- Suite completa del change bajo TDD: unitarias, funcionales con Spark local, integrales contra `andresFree` y aceptación trazable a los specs; resultados conservados con `pytest --junitxml` en `results/persistencia-bitacora/`.

**Non-Goals:**

- Identidad on-behalf-of real (C3): la bitácora de eventos define el campo `usuario` y acepta su ausencia; poblarlo con la identidad del llamante es de C3.
- Registro de eventos/errores desde el pipeline de C1 (plan, pre-flight, ejecutar, verificar, reporte): la instrumentación del pipeline llega cuando C3+ consuma la bitácora; C2 entrega el mecanismo de registro, no el cableado retroactivo de C1.
- Tablas de dominio distintas de las bitácoras: ningún change posterior requiere otra tabla todavía; se agregarán en su change correspondiente por este mismo mecanismo.
- Configuración dinámica o recarga en caliente del archivo de propiedades: la configuración se carga una vez y es de solo lectura.
- Generación de informes formales (C10): este change solo conserva su `junit.xml`.
- Uso de `andresAzureDev`: prohibido salvo aprobación expresa; las integrales de C2 corren solo en `andresFree`.

## Decisions

### D1. Layout: tres subpaquetes nuevos, uno por capability

```
control_accesos/
  configuracion/   -> app-configuration (cargador del archivo de propiedades)
  persistencia/    -> app-persistence (DDL, capa de persistencia, helpers de integridad)
  bitacora/        -> audit-logging (escritores de eventos y errores)
config/
  app_properties.json
tests/
  unitarias/  funcionales/  aceptacion/  (mismas capas de C1; integrales vía marker `free`)
```

Racional: replica el patrone aprobado en C1 (design.md D1 de core-domain: un subpaquete por capability, mapeo spec -> código trazable). Alternativa descartada: un solo subpaquete `infra/` para todo (rompería la trazabilidad spec -> código y mezclaría tres capabilities con dueños de cambio distintos).

### D2. Configuración: JSON en `config/app_properties.json` + clase cargadora de solo lectura

`config/app_properties.json` se distribuye con `{"catalogo": "control"}`. La clase cargadora (POO, en `configuracion/`) lee el archivo una vez, valida que exista, que sea JSON válido y que los atributos obligatorios estén presentes, y expone los atributos como propiedades de solo lectura (sin setters; cualquier intento de modificación no altera el estado). La ruta del archivo se deriva de la raíz del proyecto (a partir de `__file__`, como ya hace `conftest.py`), nunca como ruta absoluta embebida. Errores explícitos propios (jerarquía de excepciones del módulo, mensajes en español) para: archivo inexistente, JSON inválido y atributo obligatorio ausente.

Racional: JSON es el formato pedido por el estándar y suficiente para pares clave-valor planos; la validación fail-fast al cargar evita errores tardíos y crípticos en medio de una operación de grants. Alternativas descartadas: YAML/TOML (dependencia extra y no solicitado); lectura perezosa por atributo (reabriría el archivo en cada acceso y dificultaría la validación temprana).

### D3. Sesión Spark inyectada: local en pruebas, provista por el entorno en Databricks

La capa de persistencia recibe la `SparkSession` por inyección de dependencias (patrón ya usado en C1 con matriz y canales). En pruebas funcionales, una fixture de `conftest.py` construye una sesión Spark local con Delta Lake (`delta-spark`). En la Databricks App, la sesión la provee el entorno. Ninguna clase crea su propia sesión.

Racional: inyectar la sesión permite probar toda la capa en local sin workspace y sin Databricks Connect, y que el mismo código corra en la App. Alternativa descartada: Databricks Connect para las funcionales (volvería "integrales" a pruebas que deben ser rápidas y offline, y exigiría credenciales en cada corrida).

### D4. DDL como plantillas SQL idempotentes, ejecutadas con `spark.sql`

Cada objeto persistente (esquema, tabla) declara su DDL como plantilla SQL en mayúsculas con parámetros sustituidos desde la configuración (`CREATE SCHEMA IF NOT EXISTS <catalogo>.control_acceso_app`; `CREATE TABLE IF NOT EXISTS ... (...) USING DELTA CLUSTER BY (...) TBLPROPERTIES ('delta.enableChangeDataFeed'='true', 'delta.autoOptimize.optimizeWrite'='true', 'delta.autoOptimize.autoCompact'='true')`). Una clase inicializadora ejecuta el DDL del esquema y de todas las tablas registradas al arrancar; la idempotencia la garantiza `IF NOT EXISTS`, no lógica condicional propia.

Racional: `IF NOT EXISTS` es la primitiva idempotente nativa; declara el esquema como dato (DDL plantilla) en lugar de construirlo con API de DataFrame, que no expresa liquid clustering ni TBLPROPERTIES de forma directa. El catálogo y el esquema se inyectan desde la configuración/constantes del módulo DDL, nunca escritos a mano en cada sentencia (regla No HardCoded). Alternativa descartada: `CREATE TABLE` con `DeltaTable.createIfNotExists` (API programática verbosa para TBLPROPERTIES + CLUSTER BY y menos legible como contrato).

Nota de compatibilidad: liquid clustering exige Delta 3.x / DBR 13.3+. Las funcionales con Spark local usan la versión de `delta-spark` instalada; si la versión local no soporta `CLUSTER BY`, las funcionales verifican idempotencia y escritura, y la verificación de clustering y propiedades queda en las integrales contra `andresFree` (ver Risks).

### D5. Integridad PK/FK en código con operaciones masivas (anti-joins)

Los helpers de integridad (clase POO en `persistencia/`) validan el lote ANTES de escribir, con operaciones masivas de PySpark: unicidad de PK dentro del lote (`groupBy`+`count`) y contra la tabla destino (anti-join del lote con la tabla por PK), y existencia de cada FK (semi-join contra la tabla padre; los que no cruzan son violaciones). Una violación lanza una excepción propia `ErrorIntegridad` con el detalle de las llaves infractoras y NO se escribe nada del lote.

Racional: Delta no enforcea constraints PK/FK (el estándar lo reconoce y lo exige en código); hacerlo con joins masivos cumple la regla "PySpark al máximo, sin ciclos por fila". Alternativa descartada: constraints `PRIMARY KEY`/`FOREIGN KEY` declarativas de Databricks (informativas, no enforcean nada; darían falsa sensación de garantía).

### D6. Bitácoras: escritores POO con modelos de registro explícitos y STRUCT para errores

- `bitacora_eventos`: columnas mínimas `id_evento` (PK, UUID generado por registro), `marca_tiempo` (timestamp del evento), `usuario` (string; identidad OBO cuando exista — C3 —, vacío mientras tanto), `accion`, `detalle`, `resultado`. `CLUSTER BY (marca_tiempo)` (consulta cronológica dominante).
- `bitacora_errores`: columnas mínimas `id_error` (PK, UUID), `marca_tiempo`, `usuario`, `modulo`, `detalle STRUCT<tipo_excepcion STRING, mensaje STRING, traza STRING, contexto STRING>`. `CLUSTER BY (marca_tiempo)`.
- Escritores POO (`bitacora/`) con métodos `Registrar...` que construyen un DataFrame del lote y escriben en append vía la capa de persistencia (D4/D5), nunca fila a fila. El escritor de errores acepta la excepción capturada y extrae tipo, mensaje, traza (`traceback`) y contexto hacia el STRUCT.

Racional: modelos de registro explícitos (dataclasses) hacen el contrato de las bitácoras tipado y estable para C3+; el STRUCT satisface literalmente el estándar (detalle `STRUCT<...>`) y habilita consultas por campo. Alternativa descartada: detalle como STRING JSON (más simple pero sin tipado ni consulta por campo; el estándar pide STRUCT).

### D7. Anti-recursión: el fallo de la propia bitácora degrada a salida local

Si escribir en la bitácora de errores falla (tabla inaccesible, sesión caída), el escritor captura ese fallo en su propio try/except y lo reporta en la salida local (stderr/print con el detalle), sin propagar excepción ni intentar registrar ese fallo en la bitácora (evita recursión infinita). Lo mismo aplica a la bitácora de eventos: su fallo no interrumpe la operación principal.

Racional: la bitácora no puede ser un punto único de fallo en cascada; el estándar exige "error controlado vía try/except" también para la propia bitácora. Trade-off aceptado: un evento podría quedar solo en salida local si la tabla está caída.

### D8. Dependencias y TDD: declarar `pyspark` + `delta-spark`, instalación aprobada por el humano, red -> green -> refactor

Se agregan `pyspark` y `delta-spark` a `requirements.txt` (compatibles con Python 3.14 del venv) y su instalación se solicita al humano con justificación a detalle (regla "Prohibición de instalación por la IA", igual que C1 hizo con `databricks-sdk`). Cada tarea de implementación sigue TDD: primero la prueba que falla, luego implementación mínima, luego refactor. Las integrales contra `andresFree` usan el marker `free` ya registrado y crean/verifican esquema y tablas reales de forma idempotente con la identidad del perfil CLI; el comentario de `pytest.ini` que postergaba las integrales a C4 se actualiza (llegan en C2).

Racional: sin PySpark/Delta no hay capa de persistencia que probar; declarar + pedir aprobación mantiene la regla del proyecto sin bloquear el TDD una vez aprobada. Alternativa descartada: simular Spark en las funcionales (la propuesta exige "capa de persistencia con Spark local" en funcionales; simularlo vaciaría la capa de contenido).

## Risks / Trade-offs

- [La versión local de `delta-spark` compatible con Python 3.14 podría no soportar `CLUSTER BY`] → Las funcionales verifican idempotencia, escritura masiva e integridad; la verificación de liquid clustering y TBLPROPERTIES se hace en las integrales contra `andresFree` (via `DESCRIBE`/SHOW TBLPROPERTIES). Si la versión instalada sí lo soporta, las funcionales también lo verifican.
- [El catálogo `control` podría no existir en `andresFree` o el perfil CLI no tener privilegios para crear el esquema] → El error se reporta explícito y controlado (spec `app-persistence` - "Catálogo inaccesible"); la tarea integral documenta el fallo y la creación del catálogo se coordina con el humano antes de reintentar. No se crean catálogos desde la app (fuera de alcance).
- [Inyectar `usuario` antes de que exista OBO (C3) podría tentar a hardcodear un valor] → El spec fija el comportamiento: campo presente y explícitamente sin usuario cuando no hay identidad; ningún placeholder hardcodeado.
- [Verificar integridad con anti-joins agrega lecturas previas a cada escritura] → Costo aceptable: las bitácoras son de bajo volumen y escritura por lotes; la corrección prima sobre el micro-rendimiento. Si en el futuro una tabla de alta frecuencia lo requiriera, se haría opcional por tabla en su change.
- [La degradación a salida local (D7) puede perderse si nadie la observa] → Trade-off asumido conscientemente para evitar cascadas; la App (C9) podrá superficiar estos avisos.

## Open Questions

(ninguna)
