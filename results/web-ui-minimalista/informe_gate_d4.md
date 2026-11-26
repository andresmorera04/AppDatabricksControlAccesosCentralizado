# Informe del gate D4 (spike OBO) y resolución de arquitectura

- **Change:** `web-ui-minimalista` (C9) — rama `feature/web-ui-minimalista`
- **Fecha:** 2026-11-26 — **Entorno:** `andresFree` (AWS Free Edition)
- **Spike desplegado:** App `control-accesos-spike` con autorización de usuario
  (OBO) y 7 `user_api_scopes` aprobados.

## Gate ejecutado

24 sondas desplegadas con la credencial del llamante: identidad, SCIM,
Unity Catalog, SQL remoto, Permissions API y escrituras controladas con
instantánea/restauración. Resultado: **9 ok / 13 fallo / 2 no disponibles**.

## Hallazgos

1. **F1 — Conflicto `oauth and pat` en el runtime de la App.** El entorno
   inyecta las credenciales OAuth del service principal propio y el SDK
   rechazaba la combinación al construir los clientes OBO.
   *Resolución aplicada:* fijar `auth_type='pat'` en los constructores OBO
   para usar exclusivamente el token del llamante (commit `bacd82c`, con
   dos pruebas de regresión).
2. **F2 — `databricks-connect` es inviable en la imagen de la App.** La
   imagen usa Python 3.11 → Connect 15.4 sin `Builder.create()` (solo existe
   en Connect ≥16, que exige Python 3.12); `getOrCreate()` reutilizaría la
   sesión de otro usuario y rompe el aislamiento OBO.
   *Resolución a aplicar:* `SesionSqlRemota` sobre la SQL Statement Execution
   API (scope `sql`, verificado GO).
3. **Catálogo de scopes de Apps cerrado (verificado server-side).** La prueba
   `apps create-update` con `scim`, `clusters` y `access-management` fue
   rechazada con "is not a valid scope"; `all-apis` (tokens) no existe.
   Consecuencias: sin listado SCIM de principals, sin ACL de warehouses
   (`access-management`), sin clusters, sin tokens.
   *Verificado GO:* identidad OBO, descubrimiento UC (`catalog.*` incluida
   la conexión), listado de warehouses (`sql`) y ACL de Apps (`apps`,
   lectura y escritura).
4. **Veredicto formal:** gate mínimo NO-GO y gate completo NO-GO bajo el
   modelo OBO estricto.

## Decisión del humano

El objetivo de C9 se cumple **a cabalidad**: centralizar en una sola
Databricks App la gestión de accesos para todos los tipos indicados.
El modelo OBO estricto queda descartado como único mecanismo y el recorte
de alcance (pasada 2) queda **descartado**.

## Resolución a aplicar: modelo broker (change fundacional)

Se crea el change `app-broker-identidad-ejecucion`:

- **Autorización SIEMPRE por llamante:** identidad OBO + pre-flight de
  privilegios efectivos (C3) + revalidación al confirmar. Sin autoridad
  del llamante no hay ejecución, aunque el SP pueda realizarla.
- **Ejecución con la identidad de la App SOLO** donde OBO es inviable:
  SCIM y plano de control (ACL de warehouses, clusters, serverless,
  tokens), tras validar la autoridad del llamante en la misma acción.
- **OBO preservado donde es viable:** grants UC vía SQL (Statement
  Execution API) y ACL de Databricks Apps.
- **Service principal de la App con privilegios mínimos:** `workspace
  admin` solo para el spike (asignación humana), endurecimiento por
  superficie y documentación del mínimo real (tokens pendiente de
  verificar).
- **Ruta CLI/lote sin cambios:** sigue siendo OBO pura.
- **Gate propio antes de reanudar la UI:** spike con SP + aislamiento
  entre llamantes, go/no-go con evidencia versionada.

## Estado

- C9 `web-ui-minimalista`: **EN HOLD** hasta el GO del change broker
  (registrado en su `tasks.md`); la tarea 2.4 permanece sin marcar.
- Evidencia: `spike_obo_evidencia.json`, `spike_scopes_evidencia.json`,
  `spike-free.xml` (en este directorio).

## Trazabilidad de commits

- `bacd82c` fix auth_type='pat' (F1) · `8187007` evidencia NO-GO del gate
- `7760cc9` pasada 1 de trazabilidad · `a200182` evidencia prueba 2.7
- `ebef38d` change broker + hold de C9
