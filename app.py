"""Entrada delgada de la Databricks App `SecurityManager` (design.md D1/D2).

Carga la configuración y delega TODA la lógica en el controlador de la vertical
(`CrearVerticalUi`); aquí solo se renderizan las tres pantallas en español con
Streamlit. Sin contexto OBO (fuera de la App), la composición falla de forma
controlada y se muestra el mensaje sin desplegar credenciales.

No se ejecuta al importarse (el smoke test hace `import app`): `main()` corre
solo bajo `streamlit run app.py`, que ejecuta el archivo como `__main__`.
"""

import streamlit as st

from control_accesos.configuracion.configuracion_app import ConfiguracionApp
from control_accesos.ui.composicion import CrearVerticalUi

# Título y descripción de la aplicación (interfaz en español, spec).
TITULO_APP = "SecurityManager — Control centralizado de accesos"
DESCRIPCION_APP = (
    "Otorga privilegios sobre objetos del plano de datos (Unity Catalog) "
    "y del plano de control (workspace) actuando, en cada escritura, con la "
    "autorización del usuario llamante."
)


def _FilasADicts(filas):
    """Convierte las filas del presentador a diccionarios para `st.dataframe`."""
    from dataclasses import asdict

    return [asdict(fila) for fila in filas]


def main():
    """Componer la vertical y renderizar selección → previsualización → reporte."""
    st.set_page_config(page_title="SecurityManager", layout="wide")
    st.title(TITULO_APP)
    st.caption(DESCRIPCION_APP)

    configuracion = ConfiguracionApp.Cargar()
    try:
        vertical = CrearVerticalUi(configuracion)
    except Exception as excepcion:  # noqa: BLE001 - error controlado sin secretos
        st.error(
            "No se pudo componer la aplicación con el contexto on-behalf-of "
            f"actual: {type(excepcion).__name__}."
        )
        return

    controlador = vertical.controlador
    identidad = vertical.identidad

    usuario = controlador.IdentidadVisible(identidad)
    st.caption(f"Identidad: {usuario or 'sin identidad OBO disponible'}")

    _PantallaSeleccion(controlador, identidad)
    _PantallaPrevisualizacionYEjecucion(controlador, identidad)


def _PantallaSeleccion(controlador, identidad):
    """Pantalla 1: selección de principal, tipo, objeto y privilegios."""
    st.subheader("Selección")

    principales = controlador.ListarPrincipales()
    tipo_principal = st.selectbox(
        "Tipo de principal",
        ("usuario", "grupo", "service_principal"),
        key="tipo_principal",
    )
    principal_elegido = st.selectbox(
        "Principal",
        [p.identificador for p in principales] or ["— sin opciones —"],
        key="principal",
    )

    tipos_objeto = [
        "catalogo", "esquema", "tabla_delta", "streaming_table",
        "vista_materializada", "vista_sql", "volumen", "modelo_ml",
        "external_location", "connection", "computo_clasico",
        "computo_serverless", "sql_warehouse", "databricks_app", "uso_token",
    ]
    tipo_objeto = st.selectbox("Tipo de objeto", tipos_objeto, key="tipo_objeto")

    from control_accesos.dominio.enumeraciones import TipoObjeto as _TipoObjeto
    from control_accesos.dominio.modelos import Principal as _Principal
    from control_accesos.dominio.enumeraciones import TipoPrincipal as _TipoPrincipal

    controlador.SeleccionarTipo(_TipoObjeto(tipo_objeto))

    if tipo_objeto in ("esquema", "tabla_delta", "streaming_table",
                       "vista_materializada", "vista_sql", "volumen", "modelo_ml"):
        catalogo = st.text_input("Catálogo contenedor", key="catalogo")
        controlador.SeleccionarCatalogo(catalogo or None)
        if tipo_objeto in ("tabla_delta", "streaming_table", "vista_materializada",
                           "vista_sql", "volumen", "modelo_ml"):
            esquema = st.text_input("Esquema contenedor", key="esquema")
            controlador.SeleccionarEsquema(esquema or None)

    objetos = controlador.ListarObjetos(_TipoObjeto(tipo_objeto))
    objeto_elegido = st.multiselect(
        "Objeto(s)",
        [o.identificador for o in objetos] or ["— sin opciones —"],
        key="objetos",
    )
    controlador.SeleccionarObjetos(
        [o for o in objetos if o.identificador in objeto_elegido]
    )

    privilegios_disponibles = controlador.ListarPrivilegios(_TipoObjeto(tipo_objeto))
    privilegios_elegidos = st.multiselect(
        "Privilegios", privilegios_disponibles, key="privilegios"
    )
    controlador.SeleccionarPrivilegios(privilegios_elegidos)

    if tipo_principal == "principal":
        principal_obj = next(
            (p for p in principales if p.identificador == principal_elegido),
            None,
        )
    else:
        principal_obj = next(
            (p for p in principales if p.tipo.value == tipo_principal),
            None,
        )
    controlador.SeleccionarPrincipales([principal_obj] if principal_obj else [])

    if controlador.ErrorDescubrimiento():
        st.error(
            f"No se pudieron descubrir las opciones: "
            f"{controlador.ErrorDescubrimiento()}"
        )

    if st.button("Previsualizar autorización", disabled=not controlador.PuedeEjecutar()):
        try:
            filas = controlador.Previsualizar(identidad)
            st.session_state["filas_previsualizacion"] = filas
        except Exception as excepcion:  # noqa: BLE001 - selección incompleta
            st.warning(type(excepcion).__name__)


def _PantallaPrevisualizacionYEjecucion(controlador, identidad):
    """Pantallas 2 y 3: previsualización del split y confirmación/reporte."""
    st.subheader("Previsualización y ejecución")

    if "filas_previsualizacion" not in st.session_state:
        st.info("Seleccione principal, objeto y privilegios, y previsualice la autorización.")
        return

    filas = st.session_state["filas_previsualizacion"]
    st.dataframe(_FilasADicts(filas))

    if st.button("Confirmar y ejecutar", disabled=not controlador.PuedeEjecutar()):
        reporte = controlador.ConfirmarYEejecutar(identidad)
        if reporte is None:
            st.warning("Sin confirmación vigente: revise la previsualización.")
            return
        st.subheader("Reporte por ítem")
        st.dataframe(_FilasADicts(reporte))
        totales = controlador.TotalesDelUltimoReporte()
        if totales is not None:
            st.caption(
                f"Total de ítems: {totales['total_items']} — "
                f"{totales['totales_por_estado']}"
            )


if __name__ == "__main__":
    main()
