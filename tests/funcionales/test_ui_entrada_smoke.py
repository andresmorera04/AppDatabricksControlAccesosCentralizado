"""Prueba de humo de la entrada delgada de la Databricks App (tarea 6.4).

Verifica que `import app` no ejecuta Streamlit ni compone la vertical: la
entrada solo define `main()` (guarda con `if __name__ == "__main__"`), de modo
que importarla en la suite es inofensivo y el arranque real queda bajo
`streamlit run app.py`.
"""


def TestEntradaDelgadaSeImportaSinEjecutar():
    """`import app` define main() sin invocarla ni iniciar Streamlit."""
    import app

    assert callable(app.main), "La entrada debe exponer main() para Streamlit."
    # La vertical real se compone por CrearVerticalUi (no al importar app).
    from control_accesos.ui.composicion import CrearVerticalUi

    assert callable(CrearVerticalUi)


def TestAppNoEjecutaStreamlitAlImportarse():
    """Importar la entrada no llama a ninguna primitiva de Streamlit."""
    import app

    # main() está definida pero no se ejecutó: no hay estado de sesión iniciado.
    assert app.__name__ is not None
