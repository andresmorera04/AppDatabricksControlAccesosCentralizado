"""Prueba unitaria del manifiesto de despliegue y la configuración de la UI.

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`.

Fija dos contratos del empaquetado de la Databricks App (design.md D1/D11):

1. **Manifiesto ``app.yaml``** (documentación oficial de Databricks Apps,
   "Configure app execution"): declara el comando de arranque con Streamlit
   (el comando por defecto de la plataforma es ``python app.py``, que NO
   sirve para Streamlit), un health check sobre la ruta real de salud del
   servidor Streamlit instalado (``ROUTE_HEALTH`` = ``_stcore/health`` en
   ``streamlit.web.server.starlette.starlette_routes``, servida como
   ``/_stcore/health``) y únicamente variables de entorno no sensibles.

2. **Configuración ``config/app_properties.json``**: la regla estricta "código
   NO hardcodeado" extiende a la UI sus valores parametrizables — nombres de
   atributos de entorno y del header OBO (protocolo de Databricks Apps),
   límites de descubrimiento/lote e identificador lógico del singleton
   ``USO_TOKEN`` —, leídos mediante ``ConfiguracionApp.Cargar()`` y
   ``ObtenerAtributo(nombre)`` sin modificar el cargador de C2.

Ninguno de los dos artefactos puede incrustar hosts, tokens, secretos ni ids
de recurso: el host llega por la variable de entorno que inyecta la
plataforma, los secretos por los mecanismos de Databricks Apps y los ids de
recurso por ``resources``/``valueFrom`` cuando el gate OBO (tarea 2.4) los
valide.
"""

from pathlib import Path

import yaml

from control_accesos.configuracion.configuracion_app import ConfiguracionApp

# Raíz del proyecto, derivada de la ubicación de este archivo de pruebas
# (tests/unitarias/ -> raíz), sin escribir rutas absolutas a mano.
RAIZ_PROYECTO = Path(__file__).resolve().parents[2]

# Manifiesto de la Databricks App: nombre, ruta y contrato de arranque.
NOMBRE_ARCHIVO_MANIFIESTO = "app.yaml"
RUTA_ARCHIVO_MANIFIESTO = RAIZ_PROYECTO / NOMBRE_ARCHIVO_MANIFIESTO

# Nombre del punto de entrada delgado de la UI (design.md D2): el manifiesto
# debe arrancar exactamente este archivo con Streamlit.
NOMBRE_ARCHIVO_ENTRADA = "app.py"

# Comando de arranque exigido: `streamlit run app.py` como secuencia (la
# plataforma no lo ejecuta en un shell; documentación oficial de app.yaml).
COMANDO_ESPERADO_MANIFIESTO = ["streamlit", "run", NOMBRE_ARCHIVO_ENTRADA]

# Ruta del health check: la ruta real de salud del servidor Streamlit
# (ROUTE_HEALTH = "_stcore/health"), con la barra inicial que exige el
# manifiesto. Se fija como constante del contrato, no se importa del
# internals de Streamlit en tiempo de prueba.
RUTA_HEALTH_CHECK_ESPERADA = "/_stcore/health"

# Patrones prohibidos en ambos artefactos: prefijo de personal access token
# de Databricks (`dapi...`) y URLs absolutas (el host del workspace lo inyecta
# la plataforma vía variable de entorno, nunca se incrusta).
PATRONES_SENSIBLES_PROHIBIDOS = ("dapi", "https://", "http://")

# Atributos de la UI en config/app_properties.json y sus valores de protocolo
# esperados (contratos de la plataforma Databricks Apps, no preferencias):
# - header del token OBO documentado para apps Streamlit;
# - variable de entorno del host del workspace inyectada por el runtime;
# - variable de entorno del cómputo serverless para Databricks Connect.
NOMBRE_ATRIBUTO_ENCABEZADO_TOKEN_OBO = "nombre_encabezado_token_obo"
VALOR_ESPERADO_ENCABEZADO_TOKEN_OBO = "x-forwarded-access-token"

NOMBRE_ATRIBUTO_VARIABLE_ENTORNO_HOST = "variable_entorno_host_workspace"
VALOR_ESPERADO_VARIABLE_ENTORNO_HOST = "DATABRICKS_HOST"

NOMBRE_ATRIBUTO_VARIABLE_ENTORNO_COMPUTE = (
    "variable_entorno_compute_serverless"
)
VALOR_ESPERADO_VARIABLE_ENTORNO_COMPUTE = "DATABRICKS_SERVERLESS_COMPUTE_ID"

# Atributos numéricos de la UI: límites de descubrimiento y de lote
# (design.md D6/D7). Sus valores concretos son política del proyecto y viven
# en el archivo de propiedades; aquí se exige tipo y coherencia, no un número.
NOMBRE_ATRIBUTO_LIMITE_OPCIONES = "limite_opciones_descubrimiento"
NOMBRE_ATRIBUTO_TAMANO_PAGINA = "tamano_pagina_descubrimiento"
NOMBRE_ATRIBUTO_LIMITE_ITEMS_LOTE = "limite_items_por_lote"

# Identificador lógico del singleton USO_TOKEN: el dominio rechaza
# identificadores vacíos y el canal real ya omite el segmento de id en la
# ruta `authorization/tokens` (C8), así que la UI necesita un valor lógico
# configurable y no vacío.
NOMBRE_ATRIBUTO_IDENTIFICADOR_TOKEN = "identificador_logico_uso_token"

# Warehouse del SQL OBO (decisión humana 2026-11-27, design.md D13):
# `IdWarehouse` es una cadena dinámica por entorno (vacía por defecto; cada
# despliegue Free/Azure la fija) y el nombre de su variable de entorno.
NOMBRE_ATRIBUTO_ID_WAREHOUSE = "id_warehouse"
NOMBRE_ATRIBUTO_VARIABLE_ENTORNO_ID_WAREHOUSE = "variable_entorno_id_warehouse"
VALOR_ESPERADO_VARIABLE_ENTORNO_ID_WAREHOUSE = "CONTROL_ACCESOS_ID_WAREHOUSE"

# Mapa atributo -> valor de protocolo esperado (aserción exacta).
ATRIBUTOS_CON_VALOR_DE_PROTOCOLO = {
    NOMBRE_ATRIBUTO_ENCABEZADO_TOKEN_OBO: VALOR_ESPERADO_ENCABEZADO_TOKEN_OBO,
    NOMBRE_ATRIBUTO_VARIABLE_ENTORNO_HOST: VALOR_ESPERADO_VARIABLE_ENTORNO_HOST,
    NOMBRE_ATRIBUTO_VARIABLE_ENTORNO_COMPUTE: (
        VALOR_ESPERADO_VARIABLE_ENTORNO_COMPUTE
    ),
    NOMBRE_ATRIBUTO_VARIABLE_ENTORNO_ID_WAREHOUSE: (
        VALOR_ESPERADO_VARIABLE_ENTORNO_ID_WAREHOUSE
    ),
}

# Atributos que deben ser cadenas no vacías (sin valor exacto exigido).
ATRIBUTOS_CADENA_NO_VACIA = (NOMBRE_ATRIBUTO_IDENTIFICADOR_TOKEN,)

# Atributos que deben ser enteros positivos.
ATRIBUTOS_ENTERO_POSITIVO = (
    NOMBRE_ATRIBUTO_LIMITE_OPCIONES,
    NOMBRE_ATRIBUTO_TAMANO_PAGINA,
    NOMBRE_ATRIBUTO_LIMITE_ITEMS_LOTE,
)


def _LeerTextoManifiesto():
    """Lee el texto crudo del manifiesto, exigiendo su existencia.

    Returns:
        str: contenido de app.yaml.

    Raises:
        AssertionError: si el manifiesto no existe en la raíz del proyecto.
    """
    assert RUTA_ARCHIVO_MANIFIESTO.is_file(), (
        f"El manifiesto {NOMBRE_ARCHIVO_MANIFIESTO} no existe en la raíz del "
        f"proyecto. Es obligatorio para desplegar la UI como Databricks App "
        f"(design.md D1)."
    )
    return RUTA_ARCHIVO_MANIFIESTO.read_text(encoding="utf-8")


def _CargarManifiesto():
    """Parsea el manifiesto con PyYAML y exige un mapeo raíz.

    Returns:
        dict: estructura del manifiesto.
    """
    datos = yaml.safe_load(_LeerTextoManifiesto())
    assert isinstance(datos, dict), (
        f"{NOMBRE_ARCHIVO_MANIFIESTO} debe contener un mapeo YAML de "
        f"configuración de la App; se encontró: {type(datos).__name__}"
    )
    return datos


def TestManifiestoArrancaStreamlitConEntradaDelgada():
    """app.yaml debe declarar `streamlit run app.py` como secuencia."""
    datos = _CargarManifiesto()

    assert "command" in datos, (
        f"{NOMBRE_ARCHIVO_MANIFIESTO} debe declarar la clave 'command': el "
        f"comando por defecto de la plataforma es 'python app.py', que no "
        f"arranca un servidor Streamlit (design.md D1)."
    )
    assert datos["command"] == COMANDO_ESPERADO_MANIFIESTO, (
        f"El comando del manifiesto debe ser {COMANDO_ESPERADO_MANIFIESTO}; "
        f"se encontró: {datos['command']!r}"
    )


def TestManifiestoDeclaraHealthCheckDeStreamlit():
    """app.yaml debe apuntar el health check a la ruta real de Streamlit."""
    datos = _CargarManifiesto()

    assert "health_check" in datos, (
        f"{NOMBRE_ARCHIVO_MANIFIESTO} debe declarar 'health_check' para que "
        f"la plataforma verifique el arranque antes de marcar el despliegue "
        f"como exitoso (documentación oficial de app.yaml)."
    )
    health_check = datos["health_check"]
    assert isinstance(health_check, dict), (
        f"'health_check' debe ser un mapeo con 'path'; se encontró: "
        f"{type(health_check).__name__}"
    )
    ruta = health_check.get("path")
    assert ruta == RUTA_HEALTH_CHECK_ESPERADA, (
        f"El health check debe usar la ruta de salud real del servidor "
        f"Streamlit ({RUTA_HEALTH_CHECK_ESPERADA}); se encontró: {ruta!r}"
    )
    assert str(ruta).startswith("/"), (
        "La documentación oficial exige que 'health_check.path' empiece "
        f"con '/'; se encontró: {ruta!r}"
    )


def TestManifiestoSoloVariablesNoSensibles():
    """Las variables de entorno del manifiesto deben ser no sensibles."""
    datos = _CargarManifiesto()
    entradas = datos.get("env", []) or []

    assert isinstance(entradas, list), (
        f"La clave 'env' del manifiesto debe ser una lista de entradas "
        f"nombre/valor; se encontró: {type(entradas).__name__}"
    )
    for entrada in entradas:
        assert isinstance(entrada, dict) and "name" in entrada, (
            f"Cada entrada de 'env' debe ser un mapeo con 'name'; se "
            f"encontró: {entrada!r}"
        )

    # Ningún valor del manifiesto puede parecer un secreto o un host: ni
    # prefijo de PAT (`dapi`), ni URLs absolutas.
    texto_crudo = _LeerTextoManifiesto().lower()
    lineas_sin_comentario = "\n".join(
        linea
        for linea in texto_crudo.splitlines()
        if not linea.strip().startswith("#")
    )
    for patron in PATRONES_SENSIBLES_PROHIBIDOS:
        assert patron not in lineas_sin_comentario, (
            f"{NOMBRE_ARCHIVO_MANIFIESTO} no debe incrustar secretos ni "
            f"hosts: se encontró el patrón prohibido '{patron}' fuera de "
            f"comentarios. El host llega por variable de entorno inyectada y "
            f"los secretos por los mecanismos de Databricks Apps "
            f"(design.md D4/D11)."
        )


def TestConfiguracionExponeAtributosDeLaUi():
    """config/app_properties.json declara los atributos de la UI (D11)."""
    configuracion = ConfiguracionApp.Cargar()

    # Valores de protocolo: aserción exacta (contratos de la plataforma).
    for nombre, esperado in ATRIBUTOS_CON_VALOR_DE_PROTOCOLO.items():
        obtenido = configuracion.ObtenerAtributo(nombre)
        assert obtenido == esperado, (
            f"El atributo '{nombre}' debe valer '{esperado}' (contrato de la "
            f"plataforma Databricks Apps); se encontró: {obtenido!r}"
        )

    # Cadenas no vacías: el identificador lógico del singleton USO_TOKEN.
    for nombre in ATRIBUTOS_CADENA_NO_VACIA:
        obtenido = configuracion.ObtenerAtributo(nombre)
        assert isinstance(obtenido, str) and obtenido.strip(), (
            f"El atributo '{nombre}' debe ser una cadena no vacía; se "
            f"encontró: {obtenido!r}"
        )

    # Enteros positivos: límites de descubrimiento y de lote.
    for nombre in ATRIBUTOS_ENTERO_POSITIVO:
        obtenido = configuracion.ObtenerAtributo(nombre)
        assert isinstance(obtenido, int) and obtenido > 0, (
            f"El atributo '{nombre}' debe ser un entero positivo; se "
            f"encontró: {obtenido!r}"
        )

    # Coherencia entre límites: la página de descubrimiento no puede superar
    # el límite total de opciones.
    limite_opciones = configuracion.ObtenerAtributo(
        NOMBRE_ATRIBUTO_LIMITE_OPCIONES
    )
    tamano_pagina = configuracion.ObtenerAtributo(
        NOMBRE_ATRIBUTO_TAMANO_PAGINA
    )
    assert tamano_pagina <= limite_opciones, (
        f"'{NOMBRE_ATRIBUTO_TAMANO_PAGINA}' ({tamano_pagina}) no puede "
        f"superar '{NOMBRE_ATRIBUTO_LIMITE_OPCIONES}' ({limite_opciones})."
    )


def TestConfiguracionDeclaraIdWarehouseDinamico():
    """IdWarehouse es una cadena dinámica por entorno (vacía por defecto)."""
    configuracion = ConfiguracionApp.Cargar()

    id_warehouse = configuracion.ObtenerAtributo(NOMBRE_ATRIBUTO_ID_WAREHOUSE)
    assert isinstance(id_warehouse, str), (
        f"'{NOMBRE_ATRIBUTO_ID_WAREHOUSE}' debe ser una cadena (vacía por "
        f"defecto; el valor real lo fija cada entorno Free/Azure); se "
        f"encontró: {id_warehouse!r}"
    )


def TestConfiguracionNoIncrustaSecretosNiHosts():
    """Ningún atributo de configuración incrusta secretos o hosts."""
    configuracion = ConfiguracionApp.Cargar()

    for nombre, valor in configuracion.atributos.items():
        if not isinstance(valor, str):
            continue
        valor_minusculas = valor.lower()
        for patron in PATRONES_SENSIBLES_PROHIBIDOS:
            assert patron not in valor_minusculas, (
                f"El atributo '{nombre}' contiene el patrón prohibido "
                f"'{patron}': la configuración declara nombres de variables "
                f"y límites, nunca valores sensibles ni hosts "
                f"(design.md D11)."
            )
