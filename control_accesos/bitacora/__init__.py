"""Subpaquete de bitácoras de la aplicación (capability `audit-logging`).

Registra toda la actividad de la aplicación y sus errores controlados en las
tablas delta `bitacora_eventos` y `bitacora_errores` del esquema dedicado
`control_acceso_app` (ver spec `audit-logging` y design.md D6/D7).

Módulos:

- `modelos.py`: modelos de registro explícitos (dataclasses inmutables) que
  fijan el contrato tipado de cada fila de bitácora: `EventoBitacora` y, para
  los errores, `DetalleError` (el STRUCT) y `RegistroError`.
- `escritores.py`: escritores POO (`BitacoraEventos`, `BitacoraErrores`) sobre
  la base común `EscritorBitacora`, que construye el DataFrame del lote y lo
  escribe masivamente vía la capa de persistencia, con verificación de llave
  primaria y degradación controlada ante el fallo de la propia bitácora.

Convenciones del proyecto (README.md - Estándar de desarrollo): código y
comentarios en español; clases, funciones y métodos en PascalCase; constantes
en MAYÚSCULAS; variables en snake_case; POO como paradigma principal.
"""
