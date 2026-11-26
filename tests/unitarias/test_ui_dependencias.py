"""Prueba unitaria de la separación de dependencias runtime/desarrollo.

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`.

El proposal.md y el design.md (decisión D5) exigen separar las dependencias en
dos artefactos:

- ``requirements.txt``: runtime de la Databricks App (Streamlit,
  ``databricks-sdk`` y, desde la tarea 2.3, ``databricks-connect``). NO debe
  contener las dependencias de la suite local (``pytest``, ``pyspark``,
  ``delta-spark``): el contenedor de la App no necesita un Spark local y
  Databricks Connect entra en conflicto con el paquete ``pyspark`` instalado.
- ``requirements-dev.txt``: suite de pruebas (``pytest``, ``pyspark``,
  ``delta-spark``, ``PyYAML``) más los pins compartidos que las pruebas
  necesitan para importar el código de runtime (``databricks-sdk``,
  ``streamlit``). NO debe incluir ``databricks-connect`` (incompatible con el
  ``pyspark`` local de la suite) ni una referencia ``-r requirements.txt``
  (arrastraría Connect al entorno de desarrollo).

La duplicación deliberada de los pins compartidos se controla aquí: ambos
archivos deben declarar exactamente la misma versión para cada paquete común,
de modo que lo que se prueba localmente sea lo que se despliega.

El parsing es propio y mínimo (sin dependencia de terceros): líneas de
comentario y vacías fuera, nombres normalizados según PEP 503 (minúsculas y
``_`` -> ``-``) para que ``delta-spark`` y ``delta_spark`` comparen igual.
"""

from pathlib import Path

# Raíz del proyecto, derivada de la ubicación de este archivo de pruebas
# (tests/unitarias/ -> raíz). Se calcula, no se escribe a mano, para cumplir la
# regla de no hardcodear rutas.
RAIZ_PROYECTO = Path(__file__).resolve().parents[2]

# Nombres de los dos artefactos de dependencias (proposal.md - What Changes).
NOMBRE_ARCHIVO_RUNTIME = "requirements.txt"
NOMBRE_ARCHIVO_DESARROLLO = "requirements-dev.txt"
RUTA_ARCHIVO_RUNTIME = RAIZ_PROYECTO / NOMBRE_ARCHIVO_RUNTIME
RUTA_ARCHIVO_DESARROLLO = RAIZ_PROYECTO / NOMBRE_ARCHIVO_DESARROLLO

# Paquetes prohibidos en el runtime de la App: la suite local y el Spark local
# no se despliegan en el contenedor (design.md D5).
PAQUETES_PROHIBIDOS_RUNTIME = ("pytest", "pyspark", "delta-spark")

# Paquetes prohibidos en el entorno de desarrollo: Databricks Connect exige
# que el paquete `pyspark` NO esté instalado y la suite local lo necesita
# (design.md D5).
PAQUETES_PROHIBIDOS_DESARROLLO = ("databricks-connect",)

# Paquetes que el runtime debe declarar con pin exacto (`==`) para que el
# despliegue sea reproducible.
PAQUETES_OBLIGATORIOS_RUNTIME_CON_PIN = ("databricks-sdk", "streamlit")

# Databricks Connect: dependencia exclusiva del runtime (tarea 2.3 de C9).
# Pin 15.4.x: la imagen de la App usa Python 3.11 y las líneas 16+ de Connect
# exigen Python ==3.12.*; el soporte de cómputo serverless comienza en
# 15.4.10 y las versiones de Connect menores o iguales que el runtime
# serverless son plenamente compatibles (documentación oficial).
NOMBRE_PAQUETE_CONNECT = "databricks-connect"

# Dependencias de la suite que deben conservarse en el archivo de desarrollo
# (heredadas de C1/C2 más PyYAML para las pruebas del manifiesto app.yaml).
PAQUETES_SUITE_DESARROLLO = ("pytest", "pyspark", "delta-spark", "pyyaml")

# Paquetes compartidos entre runtime y desarrollo: las pruebas importan el
# código de la App (SDK, Streamlit/AppTest), por lo que el entorno local debe
# tener exactamente los mismos pins que el contenedor.
PAQUETES_COMPARTIDOS = ("databricks-sdk", "streamlit")

# Separador de pin exacto exigido para reproducibilidad.
SEPARADOR_PIN_EXACTO = "=="

# Prefijos de línea que declaran una referencia a otro archivo de requisitos;
# prohibidos en el archivo de desarrollo para no arrastrar Connect (D5).
PREFIJO_REFERENCIA_REQUISITOS_CORTA = "-r"
PREFIJO_REFERENCIA_REQUISITOS_LARGA = "--requirement"


def _NormalizarNombrePaquete(nombre):
    """Normaliza un nombre de distribución según PEP 503 (minúsculas, guiones).

    Args:
        nombre (str): nombre tal como aparece en el archivo de requisitos.

    Returns:
        str: nombre normalizado; ``delta_spark`` y ``Delta-Spark`` comparan
            igual que ``delta-spark``.
    """
    return nombre.strip().lower().replace("_", "-")


def _ParsearArchivoRequisitos(ruta):
    """Parsea un archivo de requisitos a un dict nombre normalizado -> pin.

    Ignora comentarios y líneas vacías. Acepta ``nombre==pin`` (devuelve el
    pin) y ``nombre`` sin pin (devuelve ``None``). Las opciones de pip
    (líneas que empiezan por ``-``) se registran con su texto crudo como clave
    para que las pruebas puedan inspeccionarlas.

    Args:
        ruta (Path): archivo de requisitos a leer.

    Returns:
        dict[str, str | None]: paquetes declarados y sus pins.

    Raises:
        AssertionError: si el archivo no existe (el contrato de C9 exige los
            dos artefactos separados).
    """
    assert ruta.is_file(), (
        f"El artefacto de dependencias {ruta.name} no existe en la raíz del "
        f"proyecto. El change C9 exige separar runtime ({NOMBRE_ARCHIVO_RUNTIME}) "
        f"y desarrollo ({NOMBRE_ARCHIVO_DESARROLLO})."
    )

    paquetes = {}
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        if linea.startswith(PREFIJO_REFERENCIA_REQUISITOS_CORTA):
            # Opción de pip (-r/--requirement/-e/...): se conserva cruda.
            paquetes[linea] = None
            continue
        if SEPARADOR_PIN_EXACTO in linea:
            nombre, pin = linea.split(SEPARADOR_PIN_EXACTO, maxsplit=1)
            paquetes[_NormalizarNombrePaquete(nombre)] = pin.strip()
        else:
            paquetes[_NormalizarNombrePaquete(linea)] = None
    return paquetes


def _ObtenerPin(paquetes, nombre):
    """Devuelve el pin exacto declarado para un paquete normalizado.

    Args:
        paquetes (dict): resultado de ``_ParsearArchivoRequisitos``.
        nombre (str): nombre del paquete en cualquier forma (se normaliza).

    Returns:
        str | None: pin declarado, o ``None`` si el paquete no está o no tiene
            pin exacto.
    """
    return paquetes.get(_NormalizarNombrePaquete(nombre))


def TestRuntimeNoContieneDependenciasDeSuite():
    """requirements.txt no debe declarar pytest, pyspark ni delta-spark."""
    paquetes = _ParsearArchivoRequisitos(RUTA_ARCHIVO_RUNTIME)

    for prohibido in PAQUETES_PROHIBIDOS_RUNTIME:
        assert _NormalizarNombrePaquete(prohibido) not in paquetes, (
            f"El runtime de la Databricks App ({NOMBRE_ARCHIVO_RUNTIME}) no "
            f"debe contener '{prohibido}': es una dependencia de la suite "
            f"local y corresponde a {NOMBRE_ARCHIVO_DESARROLLO} (design.md D5)."
        )


def TestRuntimeDeclaraSdkYStreamlitConPinExacto():
    """requirements.txt debe declarar databricks-sdk y streamlit con pin ==."""
    paquetes = _ParsearArchivoRequisitos(RUTA_ARCHIVO_RUNTIME)

    for obligatorio in PAQUETES_OBLIGATORIOS_RUNTIME_CON_PIN:
        nombre = _NormalizarNombrePaquete(obligatorio)
        assert nombre in paquetes, (
            f"El runtime de la App debe declarar '{obligatorio}' en "
            f"{NOMBRE_ARCHIVO_RUNTIME} (design.md D1/D5)."
        )
        assert paquetes[nombre] is not None, (
            f"El runtime debe fijar '{obligatorio}' con pin exacto "
            f"'{SEPARADOR_PIN_EXACTO}' para un despliegue reproducible; se "
            f"declaró sin versión."
        )


def TestRuntimeDeclaraDatabricksConnectConPinExacto():
    """requirements.txt debe declarar databricks-connect con pin exacto.

    Connect es la vía del runtime de la App al SQL/Spark remoto (canal del
    plano de datos, persistencia de auditoría y agregación de lotes) sin
    instalar un Spark local en el contenedor (design.md D5, tarea 2.3).
    """
    paquetes = _ParsearArchivoRequisitos(RUTA_ARCHIVO_RUNTIME)

    nombre = _NormalizarNombrePaquete(NOMBRE_PAQUETE_CONNECT)
    assert nombre in paquetes, (
        f"El runtime de la App debe declarar '{NOMBRE_PAQUETE_CONNECT}' en "
        f"{NOMBRE_ARCHIVO_RUNTIME}: es la sesión Spark remota de la "
        f"aplicación desplegada (design.md D5)."
    )
    assert paquetes[nombre] is not None, (
        f"El runtime debe fijar '{NOMBRE_PAQUETE_CONNECT}' con pin exacto "
        f"'{SEPARADOR_PIN_EXACTO}' validado contra la imagen de la App y el "
        f"cómputo serverless; se declaró sin versión."
    )


def TestArchivoDesarrolloExiste():
    """requirements-dev.txt debe existir en la raíz del proyecto."""
    assert RUTA_ARCHIVO_DESARROLLO.is_file(), (
        f"El artefacto de dependencias de desarrollo "
        f"({NOMBRE_ARCHIVO_DESARROLLO}) no existe. El change C9 exige separar "
        f"la suite del runtime de la App (proposal.md - What Changes)."
    )


def TestDesarrolloNoContieneDatabricksConnect():
    """requirements-dev.txt no debe declarar databricks-connect."""
    paquetes = _ParsearArchivoRequisitos(RUTA_ARCHIVO_DESARROLLO)

    for prohibido in PAQUETES_PROHIBIDOS_DESARROLLO:
        assert _NormalizarNombrePaquete(prohibido) not in paquetes, (
            f"El entorno de desarrollo no debe contener '{prohibido}': "
            f"Databricks Connect exige que el paquete pyspark NO esté "
            f"instalado y la suite local lo necesita (design.md D5). Connect "
            f"se valida en el entorno desplegado, no en ~/.venv."
        )


def TestDesarrolloNoReferenciaArchivoRuntime():
    """requirements-dev.txt no debe incluir -r/--requirement requirements.txt.

    Una referencia arrastraría databricks-connect (declarado en el runtime
    desde la tarea 2.3) al entorno local y rompería la suite con pyspark.
    """
    paquetes = _ParsearArchivoRequisitos(RUTA_ARCHIVO_DESARROLLO)

    referencias = [
        clave
        for clave in paquetes
        if clave.startswith(PREFIJO_REFERENCIA_REQUISITOS_CORTA)
        or clave.startswith(PREFIJO_REFERENCIA_REQUISITOS_LARGA)
    ]
    assert not referencias, (
        f"{NOMBRE_ARCHIVO_DESARROLLO} no debe referenciar otros archivos de "
        f"requisitos (líneas '-r'/'--requirement'); se encontraron: "
        f"{referencias}. La duplicación deliberada de pins compartidos se "
        f"controla con la prueba de coincidencia (design.md D5)."
    )


def TestDesarrolloConservaSuiteYPinsCompartidos():
    """requirements-dev.txt conserva la suite y los pins SDK/Streamlit."""
    paquetes = _ParsearArchivoRequisitos(RUTA_ARCHIVO_DESARROLLO)

    for esperado in PAQUETES_SUITE_DESARROLLO + PAQUETES_COMPARTIDOS:
        assert _NormalizarNombrePaquete(esperado) in paquetes, (
            f"El archivo de desarrollo debe declarar '{esperado}': la suite "
            f"local necesita las dependencias de pruebas (pytest, pyspark, "
            f"delta-spark, PyYAML) y los mismos pins de runtime que importan "
            f"las pruebas (databricks-sdk, streamlit) (design.md D5)."
        )


def TestPinsCompartidosCoincidenEntreAmbosArchivos():
    """Los paquetes comunes deben tener exactamente el mismo pin.

    Lo que la suite prueba localmente debe ser lo que el contenedor de la App
    despliega; una divergencia silenciosa invalidaría las pruebas.
    """
    runtime = _ParsearArchivoRequisitos(RUTA_ARCHIVO_RUNTIME)
    desarrollo = _ParsearArchivoRequisitos(RUTA_ARCHIVO_DESARROLLO)

    for compartido in PAQUETES_COMPARTIDOS:
        pin_runtime = _ObtenerPin(runtime, compartido)
        pin_desarrollo = _ObtenerPin(desarrollo, compartido)
        assert pin_runtime is not None and pin_runtime == pin_desarrollo, (
            f"El pin compartido de '{compartido}' difiere entre runtime y "
            f"desarrollo: {NOMBRE_ARCHIVO_RUNTIME} declara "
            f"{pin_runtime!r} y {NOMBRE_ARCHIVO_DESARROLLO} declara "
            f"{pin_desarrollo!r}. Deben coincidir exactamente (design.md D5)."
        )
