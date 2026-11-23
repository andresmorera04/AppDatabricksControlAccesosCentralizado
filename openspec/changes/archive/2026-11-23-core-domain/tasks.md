# Tasks

Cada tarea de implementación sigue TDD (red -> green -> refactor): primero la prueba que falla, luego la implementación mínima, luego refactor. Todas las pruebas se descubren con la convención del proyecto (`python_functions = Test*`) y el código sigue el estándar del README (español, POO, `PascalCase`, constantes en mayúsculas, sin hardcodeo).

## 1. Infraestructura de pruebas y esqueleto del paquete

- [x] 1.1 Crear `pytest.ini` con `python_functions = Test*`, los markers `free` y `azure_approval` y `--strict-markers`, y verificar con el entorno virtual activado (`source ~/.venv/bin/activate`) que una prueba de humo (`TestConfiguracionPytest`) es descubierta y ejecutada por pytest en `tests/unitarias/`
- [x] 1.2 Crear `requirements.txt` con `pytest` y `databricks-sdk` (declarado, sin uso en C1); solicitar al humano la instalación de ambas dependencias con justificación a detalle (pytest para la suite TDD; databricks-sdk declarado para C4) — **decisión del humano: diferir la instalación de `databricks-sdk` a C4**, cuando se consuma de verdad; `pytest` ya está presente en `~/.venv` (9.2.0) y no requirió instalación. Verificado: pytest importable en el venv activado, `databricks-sdk` ausente por decisión explícita
- [x] 1.3 Crear el esqueleto del paquete `control_accesos` con los subpaquetes `dominio/`, `matriz/`, `canales/` (con `simulados/`) y `pipeline/`, más `tests/unitarias/`, `tests/funcionales/` y `tests/aceptacion/`, y verificar con una prueba unitaria que el paquete importa desde la raíz del proyecto

## 2. Modelo de dominio (capability `grant-domain-model`)

- [x] 2.1 Implementar con TDD las enumeraciones `TipoPrincipal`, `TipoObjeto`, `Plano` y `EstadoItem`, y la clase `Principal` con validación de tipo e identificador, y verificar que las pruebas unitarias de `tests/unitarias/` cubren: principal válido de cada tipo, tipo no soportado rechazado con mensaje explícito, identificador vacío rechazado
- [x] 2.2 Implementar con TDD la clase `ObjetoSecurable` con derivación del plano desde un mapa declarativo `TipoObjeto -> Plano` y normalización de la identificación del objeto, y verificar que las pruebas unitarias cubren: objeto de plano datos, objeto de plano control, tipo no soportado rechazado, y que dos referencias con distinta escritura resuelven al mismo objeto
- [x] 2.3 Implementar con TDD la clase `SolicitudGrant` con fábrica de validación (cardinalidad 1 a 1) y la clase `ItemGrant` como unidad atómica, y verificar que las pruebas unitarias cubren: solicitud válida con varios privilegios, rechazo de lista de privilegios vacía, rechazo explícito de N a M con mensaje de fuera de alcance
- [x] 2.4 Implementar con TDD la clase `ResultadoItem` con los estados OTORGADO, FALLIDO y PRIVILEGIOS_INSUFICIENTES, y las excepciones de dominio (`ErrorDominio`) con mensajes en español, y verificar que las pruebas unitarias cubren: construcción de resultado por estado, detalle de error presente en FALLIDO y causa en PRIVILEGIOS_INSUFICIENTES

## 3. Matriz de privilegios (capability `privilege-matrix`)

- [x] 3.1 Declarar con TDD el diccionario `MATRIZ_PRIVILEGIOS` con los 15 tipos de objeto soportados y sus privilegios válidos tomados de la documentación oficial de Databricks, y verificar que las pruebas unitarias cubren: `catalogo` incluye al menos `SELECT` y `USE CATALOG`, `sql_warehouse` incluye al menos `CAN_USE`, y los 15 tipos están declarados
- [x] 3.2 Implementar con TDD la clase consultora de la matriz con las operaciones: consulta de privilegios por tipo, validación de combinación privilegio-tipo, mensaje de error con privilegios alternativos y listado de opciones filtrables para UI, y verificar que las pruebas unitarias cubren: combinación válida e inválida, consulta de tipo sin declaración sin error del sistema, mensaje que menciona privilegio-tipo y alternativas, y filtrado de opciones para un tipo

## 4. Contratos de canales y simulados (capability `channel-adapters`)

- [x] 4.1 Implementar con TDD las clases abstractas `CanalDatos` (otorgar, revocar, listar grants vigentes) y `CanalControl` (otorgar, revocar) que reciben `ItemGrant` y devuelven `ResultadoItem` sin propagar excepciones, con la marca distinguible `ErrorPrivilegiosInsuficientes`, y verificar que las pruebas unitarias de un canal de prueba cubren: resultado OTORGADO por contrato, resultado FALLIDO con detalle por contrato, y permiso denegado distinguible de fallo genérico
- [x] 4.2 Implementar con TDD los canales simulados en `canales/simulados/` configurables por escenario (éxito, permiso denegado, objeto inexistente, grants vigentes configurables), y verificar que las pruebas unitarias cubren cada escenario configurado sin conexión externa alguna

## 5. Pipeline de otorgamiento (capability `grant-pipeline`)

- [x] 5.1 Implementar con TDD la fase `Planificador` que valida la forma de la solicitud y la expande en ítems atómicos, y verificar que las pruebas unitarias cubren: expansión de un principal con dos privilegios en dos ítems, y rechazo de solicitud inválida sin generar ítems
- [x] 5.2 Implementar con TDD la fase `PreFlight` que clasifica cada ítem como ejecutable o bloqueado contra la matriz, y verificar que las pruebas unitarias cubren: ítem compatible pasa a ejecutable, ítem incompatible queda bloqueado con el mensaje preciso de la matriz y no llega a ejecución
- [x] 5.3 Implementar con TDD la fase `Ejecutor` que enruta cada ítem por el plano de su objeto (DATOS -> canal de datos, CONTROL -> canal de control) sin abortar ante fallos puntuales, y verificar que las pruebas unitarias con canales simulados cubren: fallo del segundo de tres ítems no cancela los demás, y enrutamiento correcto por plano
- [x] 5.4 Implementar con TDD la fase `Verificador` que reconsulta los grants vigentes tras cada otorgamiento y convierte discrepancias en FALLIDO con detalle, y verificar que las pruebas unitarias con canal simulado cubren: otorgado verificado se mantiene OTORGADO, y discrepancia se reporta FALLIDO con el detalle de la verificación
- [x] 5.5 Implementar con TDD la fase `Reportador` que consolida el resultado por ítem con estado final, motivo y trazabilidad de fases (planificado, pre-flight, ejecutado o bloqueado, verificado), y verificar que las pruebas unitarias cubren: reporte que incluye ítems bloqueados con su motivo y ítems en los tres estados con su detalle
- [x] 5.6 Implementar con TDD el orquestador `PipelineGrants` con inyección de matriz y canales que ejecuta plan -> pre-flight -> ejecutar -> verificar -> reporte, y verificar que las pruebas funcionales de `tests/funcionales/` con canales simulados cubren el flujo completo: solicitud mixta con ítem bloqueado, ítem otorgado, ítem fallido e ítem con privilegios insuficientes reportados sin abortar la operación

## 6. Aceptación y cierre de la suite

- [x] 6.1 Escribir las pruebas de aceptación de `tests/aceptacion/` trazables 1:1 a los escenarios de los cuatro specs (`grant-domain-model`, `privilege-matrix`, `channel-adapters`, `grant-pipeline`), y verificar que cada escenario del spec tiene su prueba nombrada y pasa
- [x] 6.2 Ejecutar, con el entorno virtual activado (`source ~/.venv/bin/activate`), la suite completa del change con `pytest --junitxml=results/core-domain/junit.xml` (unitarias, funcionales y aceptación; sin capa integrales, diferidas a C4), y verificar que el resultado queda PASS y conservado en `results/core-domain/` para el informe retroactivo de C10

## Workflow follow-up

- Revisar los artefactos y la implementación; luego pedir el archivo del change (`openspec archive`) cuando la suite esté verde y la revisión esté aprobada.
- Los informes formales por change se generan en C10 de forma retroactiva; este change solo conserva `results/core-domain/junit.xml`.
