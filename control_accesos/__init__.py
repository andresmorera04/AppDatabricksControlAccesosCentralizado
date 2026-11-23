"""Paquete raíz de la aplicación de control de accesos centralizado de Databricks.

Organización por capability (ver openspec/changes/core-domain/design.md, D1):

- `dominio`: modelo de dominio (capability `grant-domain-model`).
- `matriz`: matriz de compatibilidad privilegio x tipo de objeto (capability
  `privilege-matrix`).
- `canales`: contratos de los canales de ejecución y sus implementaciones
  simuladas (capability `channel-adapters`).
- `pipeline`: orquestador y fases del flujo de otorgamiento (capability
  `grant-pipeline`).

Convenciones del proyecto (README.md - Estándar de desarrollo): código y
comentarios en español; clases, funciones y métodos en PascalCase; constantes
en MAYÚSCULAS; variables en snake_case; POO como paradigma principal.
"""
