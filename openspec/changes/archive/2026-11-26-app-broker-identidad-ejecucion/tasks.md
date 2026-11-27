# Tasks

> Convenciones obligatorias (README y `openspec/config.yaml`): código, comentarios, UI y mensajes en español; constantes `NOMBRE_CONSTANTE`, variables `snake_case`, clases/funciones/métodos `PascalCase`; POO con dependencias inyectadas; No HardCoded mediante `config/app_properties.json` y `app.yaml`; errores con `try/except` y bitácora; TDD red → green → refactor en cada tarea de implementación. Todo comando `python`/`pytest` se ejecuta tras `source ~/.venv/bin/activate`. La IA no instala bibliotecas, aplicaciones ni binarios sin autorización humana expresa. Los markers `free` y `azure_approval` están registrados en `pytest.ini`. Trazabilidad obligatoria: todo cambio de código figura como tarea aquí; los hallazgos y su corrección se documentan en el delta-spec cuando afecten comportamiento especificado.

## 1. Preparación del despliegue broker y revisión de specs

- [x] 1.1 Revisar con el humano los delta-specs MODIFIED (`compute-grants`, `app-token-grants`) y la nueva capability `app-broker-grants`, y verificar `openspec validate app-broker-identidad-ejecucion --strict` en verde; registrar la aprobación de la separación autorización/ejecución en el change
- [x] 1.2 (Acción humana) Asignar al service principal de la App `control-accesos-spike`, como recurso de despliegue del modo broker (design D5), el rol **Workspace admin** sobre el workspace objetivo y los entitlements **Databricks SQL Access**, **Workspace Access** y **Consumer Access**; verificar después con `databricks api get /api/2.0/apps/control-accesos-spike --profile andresFree` que la App sigue RUNNING; documentar en el change el procedimiento de asignación y el rollback (retirar los privilegios asignados), sin tocar la ruta CLI/lote

## 2. Transporte SQL remoto OBO (corrección F2 heredada de C9)

- [x] 2.1 Escribir `tests/unitarias/test_broker_sesion_sql_remota.py` con las pruebas rojas de `SesionSqlRemota` sobre Statement Execution API: SELECT, SHOW GRANTS y GRANT con transporte falso, sondeo de operación asíncrona, filas iterables compatibles con `CanalSqlDatos`, `auth_type='pat'` y errores controlados con redacción del token; implementar la sesión y verificar el verde con `python -m pytest tests/unitarias/test_broker_sesion_sql_remota.py -q`
- [x] 2.2 Recomponer el contexto OBO sin Spark en `FabricaContextoLlamante` (canal SQL con sesión remota, pipeline sin `sesion_spark`), implementar el agregador alternativo en Python para los totales de lote sobre el mismo puerto y retirar `databricks-connect` de `requirements.txt` ajustando las pruebas de consistencia D5 de C9; verificar con `python -m pytest tests/unitarias tests/funcionales -q` que las pruebas OBO y la regresión C1–C8 quedan en verde

## 3. Composición broker y aislamiento de autorización

- [x] 3.1 Escribir `tests/unitarias/test_broker_fabrica_contexto.py` con las pruebas rojas del `FabricaContextoBroker`: cliente del service principal obtenido de la autoconfiguración del entorno de la App (jamás usado para autorización ni para OBO), canales de lectura/escritura de ACL con SP por tipo (warehouses, clusters, serverless compute objects, Databricks Apps y tokens) y listados SCIM con SP; implementar y verificar el verde con `python -m pytest tests/unitarias/test_broker_fabrica_contexto.py -q`
- [x] 3.2 Escribir `tests/unitarias/test_broker_autorizacion.py` con las pruebas rojas del aislamiento D2: la lectura de ACLs con SP alimenta `ResolutorPrivilegiosEfectivos` evaluando identidad y grupos del llamante; la escritura broker queda bloqueada sin privilegio efectivo del llamante aunque el SP pueda ejecutarla, se ejecuta con privilegio validado y se revalida al confirmar; dos llamantes no comparten autorización. Implementar y verificar el verde con `python -m pytest tests/unitarias/test_broker_autorizacion.py -q`
- [x] 3.3 Escribir `tests/unitarias/test_broker_descubrimiento_principales.py` con las pruebas rojas del descubrimiento SCIM con SP (usuarios, grupos y service principals con App Id preservado, paginación, orden estable, error de listado distinguible de lista vacía) y de la bitácora con usuario OBO e identidad de ejecución App en el detalle del evento; implementar y verificar el verde con `python -m pytest tests/unitarias/test_broker_descubrimiento_principales.py -q`

## 4. Spike desplegado y gate broker

- [x] 4.1 Actualizar `app.py` con las sondas broker (SP: SCIM, listado de clusters, lectura y escritura restaurada de ACL de warehouse/clusters/tokens, resolución de privilegios efectivos del llamante leyendo ACLs con SP; OBO: SQL remoto con `SesionSqlRemota` y ACL de Apps) y crear `tests/integrales/test_broker_spike_andresfree.py` con el rojo pre-despliegue y el gate go/no-go por conjunto mínimo y completo; registrar el rojo en `results/app-broker-identidad-ejecucion/broker-free.xml`
- [x] 4.2 Redesplegar con `databricks bundle sync` y `databricks apps deploy control-accesos-spike --source-code-path ... --profile andresFree`, y con acción humana re-consentir si aplica, ejecutar las sondas y guardar la evidencia en `results/app-broker-identidad-ejecucion/broker_evidencia.json`; ejecutar el gate con `python -m pytest tests/integrales/test_broker_spike_andresfree.py -m free --junitxml=results/app-broker-identidad-ejecucion/broker-free.xml -q` y emitir el veredicto go/no-go, elevando cualquier NO-GO con evidencia sin reanudar C9
- [x] 4.3 Documentar en `config/app_properties.json`, `databricks.yml` y el README los privilegios del SP del modo broker como recurso de despliegue: rol **Workspace admin** y entitlements **Databricks SQL Access**, **Workspace Access** y **Consumer Access**; verificar con `databricks api` que el SP tiene efectivamente esos privilegios asignados y re-ejecutar el gate con la configuración documentada verificando que sigue en GO

## 5. Cierre y reanudación de C9

- [x] 5.1 Ejecutar la regresión completa unitaria y funcional de C1–C8 junto con las pruebas de este change con `python -m pytest tests/unitarias tests/funcionales --junitxml=results/app-broker-identidad-ejecucion/unitarias-funcionales.xml -q` y dejarla en verde, comprobando que la ruta CLI/lote conserva su comportamiento OBO
- [x] 5.2 Con el gate en GO, retirar el hold de C9 en `openspec/changes/web-ui-minimalista/tasks.md` y revisar sus artefactos con openspec-update-change (D3/D4/D6/D10 y grupos 3–8 a cobertura total de tipos, reubicando sus tareas 2.8–2.11 según lo implementado aquí); con NO-GO, dejar C9 en hold y elevar la limitación con evidencia

## Workflow follow-up

- Revisión humana de los privilegios finales del SP y de los delta MODIFIED antes de archivar; sin elevación silenciosa ni skips sin justificar.
- Archivar el change con el workflow explícito de OpenSpec propagando `app-broker-grants` a `openspec/specs/` y aplicando los MODIFIED a `compute-grants` y `app-token-grants`; verificar el resultado archivado.
