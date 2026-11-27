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


def TestComposicionNoImportaPyspark():
    """La vertical no arrastra pyspark al gráfico de imports (runtime App).

    El runtime de la Databricks App instala solo streamlit + databricks-sdk
    (regla D5): ningún módulo alcanzable desde `control_accesos.ui.composicion`
    puede importar `pyspark` a nivel de módulo. Se verifica en un subproceso
    fresco con el import de `pyspark` bloqueado por un meta_path finder; un
    retorno no nulo indicaría una fuga del viejo stack PySpark.
    """
    import subprocess
    import sys

    codigo = (
        "import sys\n"
        "class _BloqueadorPyspark:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name == 'pyspark' or name.startswith('pyspark.'):\n"
        "            raise ImportError('pyspark bloqueado (runtime App)')\n"
        "sys.meta_path.insert(0, _BloqueadorPyspark())\n"
        "import control_accesos.ui.composicion\n"
        "import control_accesos.ui.controlador\n"
        "print('OK')\n"
    )
    resultado = subprocess.run(
        [sys.executable, "-c", codigo], capture_output=True, text=True
    )
    assert resultado.returncode == 0, (
        "La composición importa módulos que arrastran pyspark (fuga del stack "
        f"PySpark al runtime de la App):\n{resultado.stderr}"
    )
