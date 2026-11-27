# Design

## Context

Evidencia empírica de C9 (`results/web-ui-minimalista/`): el catálogo de `user_api_scopes` de Databricks Apps está cerrado (`scim`, `clusters`, `access-management` rechazados server-side; `all-apis` inexistente), por lo que el modelo OBO estricto no cubre SCIM ni las ACLs de warehouses/clusters/tokens —ni siquiera en lectura, necesaria para la autorización—. Además (hallazgo F2), `databricks-connect` es inviable en la imagen de la App (Python 3.11, sin `Builder.create()`; `getOrCreate()` rompería el aislamiento). La App `control-accesos-spike` ya existe con su propio service principal y credenciales OAuth M2M inyectadas en el entorno del runtime. La ruta CLI/lote de C1–C8 permanece OBO pura y no se toca.

## Goals / Non-Goals

**Goals:**

- Cobertura total de tipos en la Databricks App mediante el modelo broker, con la autorización por llamante intacta (C3) y verificada con un spike desplegado (gate go/no-go) antes de reanudar C9.
- Preservar OBO donde es viable (grants UC vía SQL, ACL de Databricks Apps) y corregir F2 con `SesionSqlRemota` sobre Statement Execution API.
- Privilegios del service principal de la App documentados como recurso de despliegue del modo broker: rol **Workspace admin** y entitlements **Databricks SQL Access**, **Workspace Access** y **Consumer Access**.

**Non-Goals:**

- No construir la UI final (C9 permanece en hold hasta el GO).
- No cambiar comportamiento ni contratos de la ruta CLI/lote.
- No relajar el pre-flight ni la revalidación al confirmar; cualquier propuesta de reducir los privilegios documentados del SP (rol Workspace admin o alguno de los entitlements Databricks SQL Access, Workspace Access o Consumer Access) se gestiona en un nuevo change de OpenSpec con evidencia, no como ajuste silencioso.

## Decisions

### D1 — Separación autorización/ejecución (broker híbrido)

La autorización se evalúa siempre con la identidad OBO y los privilegios efectivos del llamante (algoritmo C3); la ejecución usa la identidad del service principal de la App únicamente para SCIM y el plano de control, tras validar la autoridad del llamante en la misma acción. El catálogo de scopes limita el token del usuario, no al SP.

- *Alternativa: OBO estricto para todo.* Descartada: NO-GO verificado empíricamente (gate D4 de C9 + prueba 2.7).
- *Alternativa: UI fuera de Databricks Apps con credenciales completas del usuario.* Descartada: el objetivo exige una sola Databricks App.

### D2 — Autorización leyendo ACLs con el SP y evaluando al llamante

El canal de lectura de ACLs/grants usa la identidad de la App; el resolutor filtra las entradas por identidad y grupos del llamante (semántica C3 sin cambios). Toda escritura broker exige validación previa en la misma acción y revalidación al confirmar (TOCTOU ya cubierto por el pipeline). La operación sin autoridad queda bloqueada y reportada aunque el SP pueda ejecutarla.

- *Alternativa: confiar en el filtrado de la UI sin revalidar en ejecución.* Descartada: la UI no es barrera de seguridad; la autorización se valida en el pipeline.

### D3 — OBO preservado para UC y Apps

Grants UC con la credencial OBO del llamante mediante `SesionSqlRemota` (Statement Execution API, scope `sql`, verificado GO); ACL de Databricks Apps con OBO cuando el scope `apps` lo permite (lectura y escritura verificadas en el spike de C9). Precondición operativa: el llamante necesita CAN USE en algún warehouse para el SQL OBO; los warehouses se descubren con OBO (scope `sql`).

- *Alternativa: ejecutar también UC y Apps con el SP.* Descartada: superficie elevada innecesaria y pérdida de trazabilidad por usuario en el historial de consultas UC.

### D4 — Dos contextos compuestos sin mezclar autoridad

`FabricaContextoLlamante` (OBO: identidad, UC SQL, ACL Apps) y `FabricaContextoBroker` (SP: SCIM, lectura de ACLs para autorización, escritura de ACLs del plano de control). El pipeline recibe los canales de cada contexto según el tipo de objeto; la autorización nunca usa singletons compartidos entre llamantes. OBO fija `auth_type='pat'` (hallazgo F1); el SP se obtiene de la autoconfiguración del entorno de la App (OAuth M2M) y jamás se usa para evaluar autorización ni para la ruta CLI.

- *Alternativa: un único contexto con dos clientes intercambiables.* Descartada: facilitaría ejecutar con SP sin pasar por la validación OBO; los contextos separados hacen explícita la frontera.

### D5 — Privilegios del SP de la App como recurso de despliegue documentado

El service principal de la Databricks App, en modo broker, recibe por asignación humana como recurso de despliegue el rol **Workspace admin** sobre el workspace objetivo y los entitlements **Databricks SQL Access**, **Workspace Access** y **Consumer Access**. La configuración queda documentada en `config/app_properties.json`, `databricks.yml` y el README. La autorización por llamante (D2) sigue siendo el único mecanismo que permite ejecutar acciones con esa identidad elevada: aunque el SP pueda hacerlo, nada se ejecuta sin validar la autoridad del llamante.

Cualquier intento de endurecer por superficie (por ejemplo, retirar Workspace admin para casos puntuales, suprimir un entitlement o cambiar a un SCIM con permisos menores) requiere un nuevo change de OpenSpec con evidencia; no se aplica como ajuste directo sobre el despliegue documentado.

- *Alternativa: endurecimiento por superficie desde el primer despliegue.* Descartada: el humano ha decidido fijar como configuración documentada del modo broker la del SP con Workspace admin y los tres entitlements indicados; cualquier reducción posterior se trata como un change independiente.
- *Alternativa: privilegios inferiores con elevación ad-hoc en tiempo de ejecución.* Descartada: introduce elevation paths no auditables y rompe la trazabilidad del SP como recurso de despliegue.

### D6 — Spike y gate propios antes de reanudar C9

Se reutiliza `control-accesos-spike` con nuevas sondas: con SP, listados SCIM, listado de clusters, lectura y escritura restaurada de ACL de warehouse/clusters/tokens y resolución de privilegios efectivos del llamante leyendo ACLs con SP; con OBO, SQL vía `SesionSqlRemota` (SELECT/SHOW GRANTS/GRANT) y ACL de Apps. Gate en `tests/integrales/test_broker_spike_andresfree.py` con JUnit en `results/app-broker-identidad-ejecucion/`; evidencia JSON descargable desde la propia App.

### D7 — Reanudación de C9 condicionada al GO

Con GO, C9 retira el hold y revisa D3/D4/D6/D10 y los grupos 3–8 a cobertura total de tipos; con NO-GO se eleva la limitación concreta con evidencia, sin fallback ni recorte silencioso.

## Risks / Trade-offs

- **Bug de autorización con SP admin → elevación total del workspace.** Mitigación: D2, pruebas de aislamiento duras (sin autoridad = bloqueo siempre), revisión humana de los delta MODIFIED y endurecimiento D5.
- **Lectura de ACLs con SP expone a la App permisos de todos los principals.** Mitigación: la UI solo presenta lo necesario para autorización y descubrimiento; bitácora y reportes sin secretos ni tokens (D11 de C9).
- **El SQL OBO exige CAN USE del llamante en un warehouse.** Mitigación: precondición documentada y selección del warehouse entre los descubiertos con OBO, sin ids embebidos.
- **El comportamiento puede divergir entre CLI (OBO) y App (broker).** Mitigación: misma semántica de autorización C3 en ambos; D1/D4 acotan el broker al despliegue App y la spec `app-broker-grants` fija la ruta CLI sin cambios.

## Migration Plan

1. El humano asigna al SP de la App el rol Workspace admin y los entitlements Databricks SQL Access, Workspace Access y Consumer Access (recurso de despliegue del modo broker), y registra el procedimiento y el rollback (retirar los privilegios asignados) en este change. **(Hecho, 1.2 — ver registro abajo.)**
2. Implementación TDD: `SesionSqlRemota`, composición broker y aislamiento.
3. Redespliegue del spike y ejecución del gate con evidencia descargable.
4. Verificación de la configuración documentada del SP (rol y entitlements efectivos) y re-ejecución del gate.
5. GO → reanudación de C9 con cobertura total. Rollback: retirar el rol y los entitlements asignados al SP y conservar la evidencia; la ruta CLI/lote nunca se ve afectada.

## Registro de la asignación del SP (tarea 1.2, acción humana)

Ejecutada el 2026-11-26 por `andresmorera04@gmail.com` sobre la Databricks App `control-accesos-spike`:

- Service principal identificado: `app-62644q control-accesos-spike`, id `71438630368150`, client_id `8be05e5d-0808-4698-a26f-1a5f7a4b63a0`.
- Privilegios asignados (recurso de despliegue del modo broker, design D5): rol **Workspace admin** sobre el workspace objetivo y entitlements **Databricks SQL Access**, **Workspace Access** y **Consumer Access**.
- Verificación posterior a la asignación: `databricks api get /api/2.0/apps/control-accesos-spike --profile andresFree` devuelve `app_status.state = RUNNING` ("App is running"), `compute_status.state = ACTIVE` y el último despliegue `SUCCEEDED`; la App quedó operativa tras la asignación.
- **Rollback**: retirar del SP `app-62644q control-accesos-spike` el rol Workspace admin y los tres entitlements indicados (devolverlo a su estado previo al modo broker). La ruta CLI/lote no dependió nunca de estos privilegios, por lo que no se ve afectada.

## Open Questions

- ¿La Token Permissions API exige admin de cuenta además del Workspace admin del workspace? Se verifica en el spike; si exige cuenta, se eleva antes de reanudar C9 como acción humana documentada y, si corresponde, como nuevo change de OpenSpec.
- ¿Alguno de los entitlements documentados (Databricks SQL Access, Workspace Access o Consumer Access) resulta redundante o insuficiente para alguna superficie? Se verifica en el spike; cualquier ajuste se gestiona como nuevo change de OpenSpec con evidencia, sin modificación silenciosa.
- **Hallazgo del gate broker (tarea 4.2) — "cluster" vs "compute" (RESUELTO)**: la API clásica `clusters.list()` solo devuelve cómputo all-purpose; en `andresFree` devuelve **0** (no hay clusters clásicos), por lo que las sondas `broker_*_cluster` quedan `no_disponible` (aceptable: no hay objeto que sondar). La superficie de cómputo real del workspace es `serverless-compute` (`TipoObjeto.COMPUTO_SERVERLESS`), que se añadió al spike y al conjunto completo del gate: `broker_serverless` lista 1 objeto (`2619240e-...`) y su ACL se lee (2 entradas) y escribe con restauración (`PUT` re-aplicado, `coincide=True`). Vocabulario a alinear en la UI: en Databricks "Compute" es el término paraguas de "Clusters (all-purpose)" y "Serverless compute"; en el código el dominio ya los distingue (`COMPUTO_CLASICO` → recurso `clusters`, `COMPUTO_SERVERLESS` → recurso `serverless-compute`).
