"""Subpaquete de configuración de la aplicación (capability `app-configuration`).

Contiene la fuente única de configuración del proyecto (regla estricta "código
NO hardcodeado" del README.md - Estándar de desarrollo): el archivo de
propiedades `config/app_properties.json` y su clase cargadora
(`ConfiguracionApp`), que lo lee una sola vez, lo valida y expone sus
atributos de forma parametrizada y de solo lectura.

Contenido:

- `errores.py`: jerarquía de excepciones propias de la configuración
  (`ErrorConfiguracion` y sus casos: archivo inexistente, JSON inválido y
  atributo obligatorio ausente).
- `configuracion_app.py`: clase `ConfiguracionApp` con la carga validada y el
  acceso a atributos (de momento `catalogo`; crecerá con el proyecto).

Ver openspec/changes/persistencia-bitacora/specs/app-configuration/spec.md y
openspec/changes/persistencia-bitacora/design.md (D2).
"""

from control_accesos.configuracion.configuracion_app import ConfiguracionApp
from control_accesos.configuracion.errores import (
    ErrorArchivoPropiedadesInexistente,
    ErrorArchivoPropiedadesInvalido,
    ErrorAtributoConfiguracionAusente,
    ErrorConfiguracion,
)

__all__ = [
    "ConfiguracionApp",
    "ErrorConfiguracion",
    "ErrorArchivoPropiedadesInexistente",
    "ErrorArchivoPropiedadesInvalido",
    "ErrorAtributoConfiguracionAusente",
]
