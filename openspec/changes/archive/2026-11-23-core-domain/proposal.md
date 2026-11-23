# Proposal

## Why

El control de accesos en Databricks está descentralizado: cada tipo de objeto (catálogos, esquemas, tablas, volúmenes, modelos, external locations, connections, cómputo clásico y serverless, SQL warehouses, Databricks Apps, tokens de acceso personal) se autoriza por mecanismos distintos (SQL GRANT, SDK, REST API). Para construir una aplicación que centralice el otorgamiento de privilegios, primero se necesita un modelo de dominio único y coherente que abstraiga principals, objetos securables, privilegios y solicitudes de grant, junto con la matriz que define qué privilegios son válidos para cada tipo de objeto. Sin este cimiento, cualquier funcionalidad posterior sería inconsistente e imposible de probar con TDD.

## What Changes

- Definición del modelo de dominio: `Principal` (usuario, grupo o service principal), `ObjetoSecurable` (objeto tipado con su plano: datos o control), `Privilegio`, `SolicitudGrant` (principal + privilegios + objetos) y `ResultadoGrant` (resultado por ítem: otorgado, fallido, privilegios insuficientes).
- Matriz declarativa de compatibilidad `privilegio x tipo de objeto`, consultable para validación, filtrado de UI y mensajes de error precisos.
- Contratos (interfaces) de los tres canales de ejecución: SQL (GRANT/REVOKE), Databricks SDK y Databricks REST API.
- Pipeline de otorgamiento: `plan -> pre-flight -> ejecutar -> verificar -> reporte`, con verificación posterior al grant.
- Infraestructura base de testing con pytest (aquí nace la práctica TDD del proyecto).
- Cobertura de testing: unitarias (modelo de dominio, matriz y pipeline), funcionales (flujo del pipeline con canales simulados) y de aceptación. Las pruebas integrales con grants reales quedan diferidas a C4 en adelante porque este change no ejecuta operaciones externas.
- Aplicación del **estándar de desarrollo del proyecto** (definido en README.md): código y comentarios detallados en español; constantes `NOMBRE_CONSTANTE` en mayúsculas; variables y objetos en `snake_case`; clases, funciones y métodos en `PascalCase`; instrucciones SQL en mayúsculas; POO como paradigma principal; control de errores con try/except (registro en bitácora de errores cuando exista la infraestructura de persistencia); **código no hardcodeado (regla estricta: todo valor parametrizado o configurable)**; PySpark preferente para el procesamiento masivo.
- Configuración de pytest para descubrir funciones de prueba en `PascalCase` (`python_functions = Test*`), requerida por el estándar de nombres.

## Capabilities

### New Capabilities

- `grant-domain-model`: Modelo de dominio del sistema de grants: principals, objetos securables tipados por plano (datos/control), privilegios, solicitudes de grant con cardinalidad 1 a 1, y resultados por ítem.
- `privilege-matrix`: Matriz declarativa que define qué privilegios son válidos para cada tipo de objeto securable, usada para validar solicitudes, filtrar opciones en la UI y generar mensajes de error específicos.
- `channel-adapters`: Contratos de los canales de ejecución de grants (SQL GRANT, Databricks SDK, REST API), desacoplados del dominio para permitir implementaciones reales y simuladas (testing).
- `grant-pipeline`: Flujo de procesamiento de solicitudes de grant en fases (planificación, pre-flight, ejecución, verificación, reporte), con reporte detallado por ítem.

### Modified Capabilities

- (ninguna)

## Impact

- Nuevo código: paquete de dominio, módulo de matriz de privilegios, interfaces de canales, orquestador del pipeline.
- Nuevas dependencias: `pytest` (y estructura `tests/`), `databricks-sdk` (solo para tipos/contratos en esta fase).
- No afecta sistemas externos; no ejecuta grants reales todavía.
- Es prerrequisito de TODOS los changes posteriores (C2 a C10).
