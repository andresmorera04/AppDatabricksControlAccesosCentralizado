"""Configuración de pytest para toda la suite del proyecto.

Este archivo vive en la raíz del proyecto y cumple dos funciones:

1. Garantizar que la raíz del proyecto esté en `sys.path`, de modo que las
   pruebas puedan importar el paquete `control_accesos` sin necesidad de
   instalarlo (el proyecto no usa `pip install -e`; ver la regla del README
   "Prohibición de instalación por la IA"). La ruta se deriva de `__file__`,
   no se escribe a mano (regla: nada hardcodeado).

2. Servir como punto único de configuración compartida de la suite cuando en
   changes posteriores (C2+) se necesiten fixtures comunes (por ejemplo, la
   sesión de PySpark o las propiedades de `config/app_properties.json`).
"""

import sys
from pathlib import Path

# Raíz del proyecto, derivada de la ubicación de este archivo (sin hardcodear).
RAIZ_PROYECTO = Path(__file__).resolve().parent

# Se agrega la raíz al sys.path solo si no está ya presente, para no duplicar
# entradas cuando pytest ya la insertó por su modo de importación.
if str(RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROYECTO))
