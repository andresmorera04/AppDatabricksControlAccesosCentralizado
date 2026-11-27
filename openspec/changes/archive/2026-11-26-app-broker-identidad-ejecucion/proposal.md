# Proposal

## Why

El spike del gate D4 de `web-ui-minimalista` (2026-11-26) demostró empíricamente que el catálogo de `user_api_scopes` de Databricks Apps está cerrado: `scim`, `clusters` y `access-management` fueron rechazados server-side como valores no válidos, y `all-apis` no existe (evidencia en `results/web-ui-minimalista/`). Con el modelo "toda operación se ejecuta con la credencial OBO del llamante", la Databricks App no puede cubrir el objetivo completo del proyecto: listar principals (SCIM), gestionar ACLs de SQL warehouses, clusters/serverless y tokens. El humano ha decidido que el objetivo se cumple **a cabalidad**: se requiere un modelo de identidad distinto que separe la **autorización** (siempre evaluada por llamante) de la **ejecución** (identidad de la App donde OBO es inviable).

## What Changes

- Nuevo modelo **broker**: autorización por llamante (identidad OBO + pre-flight de privilegios efectivos de C3) y ejecución con la identidad del service principal de la App, únicamente tras validar la autoridad del llamante en la misma acción y con revalidación al confirmar.
- **BREAKING (acotado al despliegue como Databricks App)**: las operaciones sobre ACLs de cómputo (C7) y de Apps/tokens (C8) dejan de exigir ejecución con la credencial del llamante cuando se ejecutan dentro de la Databricks App en modo broker; la autorización sigue exigiéndose por llamante en todos los casos. La ruta CLI/lote no cambia (OBO puro).
- OBO se conserva como transporte de ejecución donde es viable: grants UC vía SQL (scope `sql`, con transporte Statement Execution API por el hallazgo F2 de C9) y ACL de Databricks Apps (scope `apps`). Superficie elevada mínima.
- El service principal de la App se configura en modo broker como recurso de despliegue documentado con el rol **Workspace admin** sobre el workspace objetivo y los entitlements **Databricks SQL Access**, **Workspace Access** y **Consumer Access**; el spike se ejecuta contra esa configuración y cualquier propuesta de reducirla se gestiona en un change de OpenSpec separado con evidencia.
- Nuevo spike del plano de control con identidad de App: listados SCIM, lectura/escritura de ACL de warehouse/clusters/tokens con instantánea y restauración, y resolución de los privilegios efectivos del llamante leyendo ACLs con el SP. Gate go/no-go propio antes de reanudar la UI.
- `web-ui-minimalista` (C9) queda **en hold** hasta el GO de este change; después se reanuda con cobertura total de tipos (sin el recorte de alcance antes propuesto, descartado por el humano).

## Capabilities

### New Capabilities

- `app-broker-grants`: autorización por llamante con ejecución elevada controlada en la Databricks App — validación de autoridad previa a toda escritura, mínimo privilegio del service principal, preservación de OBO donde es viable, aislamiento entre llamantes y auditoría con usuario OBO.

### Modified Capabilities

- `compute-grants`: los requirements "Identidad del llamante y trazabilidad de cada cambio" y "Credenciales y destino inyectados, sin valores embebidos" se revisan para admitir ejecución con la identidad de la App en el despliegue App modo broker, manteniendo la autorización por llamante y la ruta CLI sin cambios.
- `app-token-grants`: mismo ajuste para las ACLs en modo broker (tokens incluidos, donde OBO no es viable en absoluto por requerir `all-apis`).

## Impact

- Nuevo código: composición broker (cliente con credenciales de la App + evaluación de autorización del llamante), `SesionSqlRemota` sobre Statement Execution API para UC-OBO (corrección F2 heredada de C9), sondas del plano de control con SP y pruebas de aislamiento.
- Specs: MODIFIED `compute-grants` y `app-token-grants`; nuevo `app-broker-grants`.
- Despliegue: asignación de privilegios al SP de la App como recurso humano documentado; evidencia en `results/app-broker-identidad-ejecucion/`.
- C9 `web-ui-minimalista` en hold hasta el GO; C1–C8 (CLI/lote) sin cambios de comportamiento ni de contrato en su ruta.
