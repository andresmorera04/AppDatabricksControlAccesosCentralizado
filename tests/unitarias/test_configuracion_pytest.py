"""Prueba de humo de la configuración de pytest del proyecto.

Esta prueba verifica que pytest cargó la configuración declarada en
`pytest.ini` según el estándar de desarrollo del proyecto (README.md):

- `python_functions = Test*`: las funciones de prueba se nombran en
  PascalCase, convención exigida por el estándar.
- `python_classes = Test*`: las clases de prueba siguen la misma convención.
- markers `free` y `azure_approval` registrados desde ya para las pruebas
  integrales de C4 en adelante (perfiles `andresFree` y `andresAzureDev`).
- `--strict-markers` en `addopts`: cualquier marker no registrado falla la
  colección en lugar de pasar desapercibido.

El hecho de que esta función sea descubierta y ejecutada ya demuestra que la
configuración funciona: sin `python_functions = Test*`, pytest (que por
defecto solo recoge funciones `test*`) no la habría encontrado.
"""


def TestConfiguracionPytest(request):
    """Verifica que pytest aplicó la configuración del estándar del proyecto.

    Se usa el objeto `config` de pytest, que refleja la configuración ya
    cargada en tiempo de ejecución (no se relee el archivo a mano).

    Args:
        request: fixture de pytest que da acceso a la configuración cargada.
    """
    # Configuración cargada por pytest desde pytest.ini (rootdir del proyecto).
    config = request.config

    # Convención PascalCase para funciones y clases de prueba.
    funciones_de_prueba = config.getini("python_functions")
    clases_de_prueba = config.getini("python_classes")
    assert "Test*" in funciones_de_prueba, (
        "pytest.ini debe declarar python_functions = Test* (estándar del proyecto)"
    )
    assert "Test*" in clases_de_prueba, (
        "pytest.ini debe declarar python_classes = Test* (estándar del proyecto)"
    )

    # Markers de las pruebas integrales futuras (C4+), registrados desde ya.
    marcadores_declarados = config.getini("markers")
    nombres_de_marcadores = [
        marcador.split(":")[0].strip() for marcador in marcadores_declarados
    ]
    assert "free" in nombres_de_marcadores, (
        "El marker 'free' (perfil andresFree) debe estar registrado en pytest.ini"
    )
    assert "azure_approval" in nombres_de_marcadores, (
        "El marker 'azure_approval' (perfil andresAzureDev, con aprobación) "
        "debe estar registrado en pytest.ini"
    )

    # --strict-markers debe venir activo por defecto en addopts.
    opciones_adicionales = config.getini("addopts")
    assert "--strict-markers" in opciones_adicionales, (
        "pytest.ini debe activar --strict-markers en addopts"
    )
