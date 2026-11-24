# Tasks

Cada tarea de implementación sigue TDD (red -> green -> refactor): primero la prueba que falla, luego la implementación mínima, luego refactor. Todo el código sigue el estándar del README (español, POO, `PascalCase` en clases/funciones/métodos, constantes en mayúsculas, `snake_case` en variables, SQL en mayúsculas, sin hardcodeo) y los comandos `python`/`pip`/`pytest` se ejecutan con el entorno virtual activado (`source ~/.venv/bin/activate`).

## 1. Configuración de la aplicación (capability `app-configuration`)

- [x] 1.1 Crear `config/app_properties.json` con el contenido `{"catalogo": "control"}` (única fuente de configuración, regla No HardCoded) y verificar con una prueba unitaria que el archivo existe, es JSON válido y define el atributo `catalogo` con valor `control`
- [x] 1.2 Implementar con TDD el subpaquete `control_accesos/configuracion/` con la clase cargadora de la configuración (ruta derivada de la raíz del proyecto vía `__file__`, carga única, atributos de solo lectura, excepciones propias con mensajes en español), y verificar que las pruebas unitarias cubren: carga exitosa con los valores del archivo, archivo inexistente rechazado con la ruta esperada, JSON inválido rechazado con error explícito, atributo `catalogo` ausente rechazado, e intento de modificación que deja la configuración inalterada

## 2. Dependencias Spark y fixture de sesión

- [x] 2.1 Declarar `pyspark` y `delta-spark` en `requirements.txt` con comentario de justificación (capa de persistencia y pruebas funcionales con Spark local, design.md D3/D8); solicitar al humano su instalación con justificación a detalle según la regla "Prohibición de instalación por la IA", y verificar con el venv activado que ambas bibliotecas importan correctamente
- [x] 2.2 Crear la fixture de sesión Spark local con Delta Lake en `conftest.py` (raíz o de `tests/funcionales/`) y actualizar el comentario de `pytest.ini` que postergaba las integrales a C4 (llegan en C2, marker `free` ya registrado); verificar con una prueba funcional de humo que la sesión crea y lee un DataFrame delta en un directorio temporal

## 3. Persistencia (capability `app-persistence`)

- [x] 3.1 Implementar con TDD el módulo DDL de `control_accesos/persistencia/`: plantillas SQL en mayúsculas con `CREATE SCHEMA IF NOT EXISTS` y `CREATE TABLE IF NOT EXISTS ... USING DELTA CLUSTER BY (...) TBLPROPERTIES ('delta.enableChangeDataFeed'='true', 'delta.autoOptimize.optimizeWrite'='true', 'delta.autoOptimize.autoCompact'='true')`, parametrizadas con el catálogo de la configuración y el esquema `control_acceso_app` (constantes del módulo, nada hardcodeado por sentencia), y verificar con pruebas unitarias que el DDL generado contiene `IF NOT EXISTS`, `CLUSTER BY`, las tres propiedades delta y el nombre calificado `<catalogo>.control_acceso_app`
- [x] 3.2 Implementar con TDD la clase inicializadora de persistencia que ejecuta el DDL del esquema y de las tablas registradas con la sesión Spark inyectada, y verificar con pruebas funcionales (Spark local) que: la primera ejecución crea esquema y tablas, la segunda ejecución es idempotente (sin error y con los datos previos intactos), y un fallo de catálogo/sesión se reporta como error explícito controlado
- [x] 3.3 Implementar con TDD la capa de persistencia POO con escritura masiva (append de DataFrame vía operaciones de PySpark, sin ciclos por fila), y verificar con pruebas funcionales que: un lote de varios registros se inserta en una sola operación masiva y queda consultable, y un fallo de escritura (tabla inexistente) se reporta como error explícito controlado
- [x] 3.4 Implementar con TDD los helpers de integridad (clase POO `VerificadorIntegridad` u homóloga): unicidad de PK dentro del lote y contra la tabla destino, y existencia de referencias FK, todo con operaciones masivas (groupBy/anti-join/semi-join), y verificar con pruebas funcionales que: PK duplicada en el lote o contra la tabla destino es rechazada con `ErrorIntegridad` y detalle de llaves, FK inexistente es rechazada con la referencia faltante, en toda violación no se escribe ningún registro del lote, y un lote íntegro se escribe completo

## 4. Bitácoras (capability `audit-logging`)

- [x] 4.1 Implementar con TDD el DDL y el escritor POO de `bitacora_eventos` (columnas mínimas `id_evento`, `marca_tiempo`, `usuario`, `accion`, `detalle`, `resultado`; `CLUSTER BY (marca_tiempo)`; escritura masiva vía la capa de persistencia) en `control_accesos/bitacora/`, y verificar con pruebas funcionales que: un evento con usuario registra todos sus campos, un evento sin identidad OBO se registra con el usuario explícitamente vacío (sin rechazo), varios eventos se escriben en lote y la consulta devuelve la actividad ordenable por `marca_tiempo`
- [x] 4.2 Implementar con TDD el DDL y el escritor POO de `bitacora_errores` (columnas mínimas `id_error`, `marca_tiempo`, `usuario`, `modulo`, `detalle STRUCT<tipo_excepcion STRING, mensaje STRING, traza STRING, contexto STRING>`; `CLUSTER BY (marca_tiempo)`), con extracción de tipo, mensaje, traza y contexto desde la excepción capturada, y verificar con pruebas funcionales que: un error provocado por una operación que falla queda registrado con el STRUCT completo y cada campo del STRUCT es consultable de forma independiente
- [x] 4.3 Implementar con TDD la degradación controlada de ambos escritores (design.md D7): try/except propio que ante el fallo de la escritura reporta en la salida local sin propagar excepción ni registrar recursivamente, y verificar con pruebas unitarias (sesión/destino simulado que falla) que la ejecución continúa sin excepción no controlada y el fallo queda visible en la salida local

## 5. Integrales contra andresFree

- [x] 5.1 Escribir las pruebas integrales con marker `@pytest.mark.free` que, usando la identidad del perfil CLI `andresFree`, ejecutan la inicialización real de la persistencia sobre el catálogo configurado y verifican: creación del esquema `control_acceso_app`, creación de `bitacora_eventos` y `bitacora_errores` con sus columnas (incluido el STRUCT del detalle), propiedades delta habilitadas (CDF, optimizeWrite, autoCompact) y liquid clustering declarados vía inspección de metadatos, e idempotencia de una segunda ejecución con datos previos intactos; ejecutarlas con el venv activado y verificar PASS (si el catálogo `control` no existe o faltan privilegios, documentar el error explícito reportado y coordinar con el humano la habilitación antes de reintentar — la app no crea catálogos)

## 6. Aceptación y cierre de la suite

- [x] 6.1 Escribir las pruebas de aceptación de `tests/aceptacion/` trazables 1:1 a los escenarios de los tres specs (`app-configuration`, `app-persistence`, `audit-logging`), y verificar que cada escenario del spec tiene su prueba nombrada y pasa
- [x] 6.2 Ejecutar, con el entorno virtual activado (`source ~/.venv/bin/activate`), la suite completa del change con `pytest --junitxml=results/persistencia-bitacora/junit.xml` (unitarias, funcionales, integrales `free` y aceptación), y verificar que el resultado queda PASS y conservado en `results/persistencia-bitacora/` para el informe retroactivo de C10

## Workflow follow-up

- Revisar los artefactos y la implementación; luego pedir el archivo del change (`openspec archive`) cuando la suite esté verde y la revisión esté aprobada.
- Los informes formales por change se generan en C10 de forma retroactiva; este change solo conserva `results/persistencia-bitacora/junit.xml`.
