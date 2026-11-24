# Design

## Context

Ver la motivación en `proposal.md` (¿por qué?). Este documento explica el cómo, ajustado a la arquitectura real del repo: los canales ya se contratean en `control_accesos/canales/contratos.py`, el enrutamiento por plano ya existe en `control_accesos/pipeline/enrutador.py` (`EnrutadorCanales`), el pre-flight en `control_accesos/pipeline/pre_flight.py`, el dominio en `control_accesos/dominio/modelos.py`, la matriz en `control_accesos/matriz/consultora.py` y las bitácoras en `control_accesos/bitacora/`. El adaptador de pruebas integrales de `tests/integrales/adaptador_sql_databricks.py` prueba el transporte real por CLI sin instalar nada (regla "Prohibición de instalación por la IA").

## Goals / Non-Goals

**Goals:**
- Identidad del llamante como un principal (`usuario`, `grupo` o `service_principal`, con App Id) más sus grupos, detrás de un puerto inyectable.
- Resolución de privilegios efectivos leyendo otorgamientos vigentes por el canal que ya enruta por plano, emparejándolos con las referencias de identidad del llamante.
- Split como segundo eje del pre-flight existente, con mensaje estructurado de privilegios insuficientes.
- TDD con la suite organizada en las capas ya usadas por el proyecto (`tests/unitarias`, `tests/funcionales`, `tests/integrales`, `tests/aceptacion`).

**Non-Goals:**
- Otorgar, revocar o escribir permisos (solo lectura en este change).
- Implementar canales reales nuevos o instalar `databricks-sdk`.
- Heredar privilegios de un service principal a un usuario (principales distintos).

## Decisions

### D1 — Identidad detrás de un puerto (`ProveedorIdentidadLlamante`)
`IdentidadLlamante` (frozen dataclass en `control_accesos/autenticacion/`) guarda `principal: Principal`, `App Id` cuando aplica y `grupos: tuple[Grupo, ...]`, y expone `ReferenciasDeIdentidad()` (propio id + nombre/correo + id y nombre de cada grupo + App Id/nombre del service principal). `ServicioIdentidadLlamante` recibe un `ProveedorIdentidadLlamante` inyectable (cachea por invocación, decisions A y D) y una `BitacoraErrores` opcional para degradación controlada.
- *Alternativa:* leer el contexto OBO directamente. *Descartada:* acopla al runtime de Databricks Apps e impide pruebas simuladas (spec `channel-adapters` de solo lectura).

### D2 — Resolutor único apoyado en el canal existente
`ResolutorPrivilegiosEfectivos` (frozen dataclass `PrivilegiosEfectivosVista`) reutiliza `EnrutadorCanales` para consultar `ListarGrantsVigentes(objeto)` por el canal del plano del objeto, sin crear un mecanismo propio por plano (spec de consulta por canal). Empareja cada grant con `ReferenciasDeIdentidad()` respetando la normalización por plano del dominio, y distingue privilegios directos, heredados (flag `origen` con valor `directo`/`heredado`/`no_determinado`) y el origen cuando el canal no lo reporta.
- *Alternativa:* resolutores SQL y SDK independientes + fábrica. *Descartada:* duplicaría el enrutamiento y el contrato de canales, prohibido por el spec.

### D3 — Split como segundo eje del `PreFlight` existente
Se amplía `PreFlight.Clasificar(items)` con un eje opcional de privilegios del llamante, alimentado por la `IdentidadLlamante` y la vista efectiva de `D2`. Un ítem pasa a ejecutable solo si el privilegio es válido en la matriz Y figura entre los efectivos; si no, queda bloqueado con estado `privilegios_insuficientes`. `MensajePrivilegiosInsuficientes` (frozen dataclass) con `objeto`, `plano`, `privilegio_requerido`, `privilegio_faltante`, consultables por campo y con texto legible.
- *Alternativa:* fase nueva separada. *Descartada:* fragmentaría el pre-flight y rompería el flujo del pipeline (D3 del change C1).

### D4 — Errores controlados y campo `usuario` de la bitácora
Todos los fallos de autenticación/resolución se capturan con `try/except` y se registran en `bitacora_errores` con `DetalleError`; un fallo de transporte marca los ítems afectados como `fallido` sin abortar el resto. El pipeline alimenta `bitacora_eventos.usuario` con `IdentidadLlamante.principal.identificador` cuando existe identidad y con `None` explícito cuando no (spec `audit-logging` de C2). Sin identidad no se marca ningún ítem como ejecutable.

### D5 — Pruebas integrales reutilizando el transporte por CLI
Las integrales de solo lectura usan `databricks api` (CLI ya instalado) igual que C2, sin `databricks-sdk`: SCIM para identidad/grupos, `SHOW GRANTS` y lectura de ACL del plano de control. Perfil `andresFree` para todo lo posible.

## Risks / Trade-offs

- [SCIM puede no exponer grupos en Free Edition] → se comprueba contra el workspace real en las integrales `free`; si faltan, la resolución devuelve lista vacía explícita, no error.
- [El formato de identidad varía por canal (id opaco vs nombre)] → `ReferenciasDeIdentidad()` empareja contra ambos y la normalización por plano del dominio absorbe las diferencias.
- [TOCTOU entre pre-flight y ejecución] → asumido y aprobado (decisión A); se mitiga con la verificación posterior al grant ya existente.
- [Cómputo clásico no existe en `andresFree`] → esas dos integrales van con marker `azure_approval` y quedan omitidas por defecto hasta aprobación humana (decisión F).
- [Cachear identidad por invocación] → aprobado (decisión D); una misma corrida usa la misma identidad aunque cambie a mitad.

## Migration Plan

Solo se agregan módulos y se amplían datos con valores por defecto backwards-compatible (`PreFlight`, `MensajePrivilegiosInsuficientes`); no se cambian tablas ni datos. Desplegar junto a C4+; las Databricks Apps activan OBO en su configuración (fuera de la app). Rollback: retirar el eje de privilegios del `PreFlight` deja el split original de matriz intacto.

## Open Questions

Ninguna material: las APIs exactas por objeto del plano de control se fijan al implementar cada resolutor contra `andresFree`, sin afectar specs, enfoque ni tasks.
