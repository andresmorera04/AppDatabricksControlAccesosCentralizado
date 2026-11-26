# Design

## Context

Evidencia empírica de C9 (`results/web-ui-minimalista/`): el catálogo de `user_api_scopes` de Databricks Apps está cerrado (`scim`, `clusters`, `access-management` rechazados server-side; `all-apis` inexistente), por lo que el modelo OBO estricto no cubre SCIM ni las ACLs de warehouses/clusters/tokens —ni siquiera en lectura, necesaria para la autorización—. Además (hallazgo F2), `databricks-connect` es inviable en la imagen de la App (Python 3.11, sin `Builder.create()`; `getOrCreate()` rompería el aislamiento). La App `control-accesos-spike` ya existe con su propio service principal y credenciales OAuth M2M inyectadas en el entorno del runtime. La ruta CLI/lote de C1–C8 permanece OBO pura y no se toca.

## Goals / Non-Goals

**Goals:**

- Cobertura total de tipos en la Databricks App mediante el modelo broker, con la autorización por llamante intacta (C3) y verificada con un spike desplegado (gate go/no-go) antes de reanudar C9.
- Preservar OBO donde es viable (grants UC vía SQL, ACL de Databricks Apps) y corregir F2 con `SesionSqlRemota` sobre Statement Execution API.
- Privilegios del service principal de la App mínimos y documentados por superficie.

**Non-Goals:**

- No construir la UI final (C9 permanece en hold hasta el GO).
- No cambiar comportamiento ni contratos de la ruta CLI/lote.
- No relajar el pre-flight ni la revalidación al confirmar; no conceder `workspace admin` al SP como configuración definitiva sin evaluar endurecimiento.

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

### D5 — Privilegios del SP como recurso de despliegue endurecible

El spike se verifica con `workspace admin` asignado por el humano al SP de la App (vía rápida de cobertura total). Después se endurece por superficie y se documenta en `config/app_properties.json`/README: lectura SCIM, CAN_MANAGE por objeto de cómputo, y admin solo donde la plataforma lo exija (tokens, pendiente de verificación).

- *Alternativa: admin permanente sin evaluar.* Descartada: maximiza el radio de impacto de cualquier bug de autorización.

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

1. El humano asigna `workspace admin` al SP de la App (recurso de despliegue del spike).
2. Implementación TDD: `SesionSqlRemota`, composición broker y aislamiento.
3. Redespliegue del spike y ejecución del gate con evidencia descargable.
4. Endurecimiento de privilegios del SP y re-ejecución del gate.
5. GO → reanudación de C9 con cobertura total. Rollback: retirar el admin al SP y conservar la evidencia; la ruta CLI/lote nunca se ve afectada.

## Open Questions

- ¿El listado SCIM del workspace funciona con el SP sin admin (solo lectura)? Se mide en el endurecimiento D5.
- ¿La Token Permissions API exige admin de workspace o de cuenta? Se verifica en el spike; si exige cuenta, se eleva antes de reanudar C9.
