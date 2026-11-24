"""Enumeraciones de la resolución de privilegios efectivos.

Miembros en MAYÚSCULAS (constantes, estándar del proyecto) con valores en
español, igual que `dominio.enumeraciones`.
"""

from enum import Enum


class OrigenPrivilegio(Enum):
    """Cómo llegó un otorgamiento efectivo hasta el objeto consultado.

    - DIRECTO: el otorgamiento está declarado sobre el propio objeto.
    - HEREDADO: el canal lo reportó sobre un securable padre (así responde
      Unity Catalog un `SHOW GRANT ON SCHEMA`, que incluye los otorgamientos
      del catálogo contenedor).
    - NO_DETERMINADO: el canal no informa el origen del otorgamiento, así que
      no se supone ninguno (spec `caller-privilege-resolution`).
    """

    DIRECTO = "directo"
    HEREDADO = "heredado"
    NO_DETERMINADO = "no_determinado"
