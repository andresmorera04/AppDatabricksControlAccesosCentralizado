"""Subpaquete de implementaciones reales de los canales (capability `channel-adapters`).

Contiene las implementaciones de producción del contrato `Canal`: en el change
`grants-uc-datos` (C4) nace aquí el canal SQL del plano de datos
(`CanalSqlDatos`); los canales SDK y REST del plano de control llegarán en
C7/C8. Ver openspec/specs/channel-adapters/spec.md.
"""

from control_accesos.canales.reales.canal_sql_datos import (
    CanalSqlDatos,
    SesionSparkSql,
)

__all__ = ["CanalSqlDatos", "SesionSparkSql"]
