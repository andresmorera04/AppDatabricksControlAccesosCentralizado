"""Subpaquete de los canales de ejecución (capability `channel-adapters`).

Contiene los contratos (clases abstractas) de los canales de otorgamiento de
grants: `CanalDatos` (SQL GRANT/REVOKE + SHOW GRANTS) y `CanalControl`
(Permissions API / Token Permissions API), desacoplados del dominio para
permitir implementaciones reales (C4+) y simuladas (testing).
Ver openspec/specs/channel-adapters/spec.md.
"""
