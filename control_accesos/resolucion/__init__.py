"""Resolución de privilegios efectivos del llamante (capability `caller-privilege-resolution`).

Divide (split) una solicitud de grant entre ítems ejecutables e ítems
bloqueados según los privilegios que el llamante realmente tiene sobre cada
objetivo, respetando el requisito central del proyecto: **la app actúa con
los privilegios del usuario que la usa** y un ítem sin privilegios bloquea
solo a ese ítem, nunca a la operación completa (README.md, decisión D2).

Organización (design.md D2/D3):

- `enumeraciones`: `OrigenPrivilegio` (directo / heredado / no determinado).
- `modelos`: `OtorgamientoEfectivo`, `PrivilegiosEfectivosVista` (vista
  unificada por objeto) y `MensajePrivilegiosInsuficientes` (dato del bloqueo).
- `resolutor`: `ResolutorPrivilegiosEfectivos`, que consulta los otorgamientos
  vigentes **por el canal del plano del objeto** reutilizando
  `Canal.ListarGrantsVigentes` y `EnrutadorCanales`, sin implementar un
  mecanismo propio por plano.

El split se aplica en `control_accesos/pipeline/pre_flight.py` como segundo
eje de la clasificación, sobre la matriz de compatibilidad de C1.

En este change la resolución es de solo lectura: no otorga, revoca ni escribe
permisos (spec `caller-privilege-resolution`).
"""
