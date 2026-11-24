"""Pruebas unitarias de la lectura de grants vigentes vía SHOW GRANT.

Cubren el requirement "Verificación posterior al grant con SHOW GRANTS" del spec
`uc-data-object-grants`: `ListarGrantsVigentes` construye `SHOW GRANT ON
<palabra clave> <identificador>` y traduce cada fila a un otorgamiento con la
regla fila propia / fila padre (design D4) — la fila del objeto consultado
conserva su tipo; la de un contenedor padre se mapea a `CATALOGO`/`ESQUEMA`; una
palabra no mapeable se omite sin inventar objeto; un objeto sin grants devuelve
lista vacía distinguible de un fallo.
"""

from control_accesos.canales.reales.canal_sql_datos import CanalSqlDatos
from control_accesos.dominio.enumeraciones import TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import ObjetoSecurable


class SesionDoble:
    """Doble de sesión SQL que registra la sentencia y devuelve filas fijas."""

    def __init__(self, filas=None):
        self.filas = filas or []
        self.sentencias_ejecutadas = []

    def sql(self, sentencia):
        """Registra la sentencia y devuelve las filas configuradas."""
        self.sentencias_ejecutadas.append(sentencia)
        return list(self.filas)


def CrearObjeto(tipo, identificador):
    """Construye un objeto securable del plano de datos."""
    return ObjetoSecurable(identificador=identificador, tipo=tipo)


def TestConstruyeLaSentenciaShowGrant():
    """ListarGrantsVigentes consulta con la sentencia SHOW GRANT del objeto."""
    sesion = SesionDoble()
    canal = CanalSqlDatos(sesion)
    objeto = CrearObjeto(TipoObjeto.TABLA_DELTA, "control.finanzas.ventas")

    canal.ListarGrantsVigentes(objeto)

    assert sesion.sentencias_ejecutadas == [CanalSqlDatos.ConstruirShowGrant(objeto)]


def TestFilaPropiaConservaElTipoConsultado():
    """Una vista SQL consultada sigue siendo vista SQL, no colapsa a tabla."""
    sesion = SesionDoble(
        filas=[
            ["usuario@correo.com", "SELECT", "TABLE", "control.prod.v_ventas"],
        ]
    )
    canal = CanalSqlDatos(sesion)
    objeto = CrearObjeto(TipoObjeto.VISTA_SQL, "control.prod.v_ventas")

    grants = canal.ListarGrantsVigentes(objeto)

    assert len(grants) == 1
    assert grants[0].objeto.tipo is TipoObjeto.VISTA_SQL
    assert grants[0].objeto.identificador == "control.prod.v_ventas"
    assert grants[0].privilegio == "SELECT"
    assert grants[0].principal.identificador == "usuario@correo.com"
    assert grants[0].principal.tipo is TipoPrincipal.USUARIO


def TestFilaPadreSeMapeaAlContenedor():
    """Las filas de catálogo y esquema padres se mapean a contenedores."""
    sesion = SesionDoble(
        filas=[
            ["usuario@correo.com", "SELECT", "TABLE", "control.finanzas.ventas"],
            ["grupo_analistas", "USE SCHEMA", "SCHEMA", "control.finanzas"],
            ["grupo_analistas", "USE CATALOG", "CATALOG", "control"],
        ]
    )
    canal = CanalSqlDatos(sesion)
    objeto = CrearObjeto(TipoObjeto.TABLA_DELTA, "control.finanzas.ventas")

    grants = canal.ListarGrantsVigentes(objeto)

    assert len(grants) == 3
    tipos = [grant.objeto.tipo for grant in grants]
    assert tipos[0] is TipoObjeto.TABLA_DELTA
    assert tipos[1] is TipoObjeto.ESQUEMA
    assert tipos[2] is TipoObjeto.CATALOGO
    assert grants[1].objeto.identificador == "control.finanzas"
    assert grants[2].objeto.identificador == "control"


def TestPrincipalServicePrincipalPorUuid():
    """Una referencia con forma de App Id se infiere como service principal."""
    sesion = SesionDoble(
        filas=[
            ["12345678-1234-1234-1234-123456789012", "SELECT", "TABLE",
             "control.finanzas.ventas"],
        ]
    )
    canal = CanalSqlDatos(sesion)
    objeto = CrearObjeto(TipoObjeto.TABLA_DELTA, "control.finanzas.ventas")

    grants = canal.ListarGrantsVigentes(objeto)

    assert grants[0].principal.tipo is TipoPrincipal.SERVICE_PRINCIPAL


def TestPalabraNoMapeableSeOmite():
    """Una fila con palabra clave no mapeable se descarta sin inventar objeto."""
    sesion = SesionDoble(
        filas=[
            ["usuario@correo.com", "SELECT", "TABLE", "control.finanzas.ventas"],
            ["propietario", "OWN", "METASTORE", "metastore_root"],
        ]
    )
    canal = CanalSqlDatos(sesion)
    objeto = CrearObjeto(TipoObjeto.TABLA_DELTA, "control.finanzas.ventas")

    grants = canal.ListarGrantsVigentes(objeto)

    assert len(grants) == 1
    assert grants[0].objeto.tipo is TipoObjeto.TABLA_DELTA


def TestObjetoSinGrantsDevuelveListaVacia():
    """Un objeto sin otorgamientos devuelve lista vacía, no un fallo."""
    sesion = SesionDoble(filas=[])
    canal = CanalSqlDatos(sesion)
    objeto = CrearObjeto(TipoObjeto.TABLA_DELTA, "control.finanzas.ventas")

    grants = canal.ListarGrantsVigentes(objeto)

    assert grants == []
