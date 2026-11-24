"""Prueba unitaria del esqueleto del paquete `control_accesos`.

Verifica que el paquete y sus subpaquetes (uno por capability del change
core-domain, ver design.md D1) son importables desde la raíz del proyecto:

- `control_accesos`             -> paquete raíz
- `control_accesos.dominio`     -> grant-domain-model
- `control_accesos.matriz`      -> privilege-matrix
- `control_accesos.canales`     -> channel-adapters (contratos)
- `control_accesos.canales.simulados` -> channel-adapters (fakes)
- `control_accesos.pipeline`    -> grant-pipeline
- `control_accesos.autenticacion` -> caller-identity (change auth-caller-obo)
- `control_accesos.resolucion`  -> caller-privilege-resolution (mismo change)
"""

import importlib


def TestImportarPaqueteControlAccesos():
    """El paquete raíz `control_accesos` debe ser importable desde la raíz."""
    paquete = importlib.import_module("control_accesos")
    assert paquete is not None, "El paquete control_accesos debe ser importable"


def TestImportarSubpaquetesPorCapability():
    """Cada subpaquete por capability debe ser importable desde la raíz."""
    # Subpaquetes esperados según el layout del design.md (D1).
    subpaquetes_esperados = [
        "control_accesos.dominio",
        "control_accesos.matriz",
        "control_accesos.canales",
        "control_accesos.canales.simulados",
        "control_accesos.pipeline",
        "control_accesos.autenticacion",
        "control_accesos.resolucion",
    ]

    for nombre_subpaquete in subpaquetes_esperados:
        modulo = importlib.import_module(nombre_subpaquete)
        assert modulo is not None, (
            f"El subpaquete {nombre_subpaquete} debe ser importable"
        )
