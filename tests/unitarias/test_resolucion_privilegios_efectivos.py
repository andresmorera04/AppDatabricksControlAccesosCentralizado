"""Pruebas unitarias de la resolución de privilegios efectivos.

Cubren los escenarios de `caller-privilege-resolution` (change
`auth-caller-obo`) que no requieren workspace:

- "Consulta de otorgamientos vigentes por el canal del plano del objeto": la
  consulta se enruta al canal del plano, sin mecanismo propio por plano.
- "Emparejamiento de otorgamientos contra las referencias del llamante": el
  otorgamiento es efectivo solo si su otorgatario coincide con una referencia
  de la identidad del llamante (directo, por grupo, por App Id).
- "Los service principals son principales independientes": los otorgamientos
  de otro service principal NO son efectivos para un usuario.
- "Herencia de otorgamientos reportada por el sistema": se distingue directo,
  heredado y origen no determinado.
- "Vista unificada de privilegios efectivos por objeto".
- "Compatibilidad de formatos de identificación entre planos".

No hay conexión externa: los canales son los simulados de `channel-adapters`
o dobles locales, y la identidad viene de `ProveedorIdentidadSimulado`.
"""

import pytest

from control_accesos.autenticacion.servicio import ServicioIdentidadLlamante
from control_accesos.autenticacion.simulados import (
    APP_ID_DEMO,
    ID_GRUPO_ADMINS_DEMO,
    IDENTIFICADOR_USUARIO_DEMO,
    NOMBRE_GRUPO_ADMINS_DEMO,
    IdentidadServicePrincipal,
    IdentidadUsuarioConGrupos,
    ProveedorIdentidadSimulado,
)
from control_accesos.canales.errores import (
    ErrorCanal,
    ErrorPrivilegiosInsuficientes,
)
from control_accesos.canales.simulados.canales_simulados import (
    CanalControlSimulado,
    CanalDatosSimulado,
)
from control_accesos.dominio.enumeraciones import Plano, TipoObjeto
from control_accesos.dominio.errores import ErrorDominio
from control_accesos.dominio.modelos import (
    ItemGrant,
    ObjetoSecurable,
    Principal,
)
from control_accesos.resolucion.enumeraciones import OrigenPrivilegio
from control_accesos.resolucion.resolutor import ResolutorPrivilegiosEfectivos

# Identificadores de un service principal AJENO al llamante, para comprobar
# que sus otorgamientos no se le atribuyen.
OTRO_SERVICE_PRINCIPAL = "sp-workflows-ajeno"
APP_ID_OTRO_SERVICE_PRINCIPAL = "11111111-1111-1111-1111-111111111111"


def IdentidadUsuario():
    """Devuelve la identidad resuelta de un usuario con grupos.

    Returns:
        IdentidadLlamante: identidad del usuario de prueba.
    """
    return ServicioIdentidadLlamante(
        proveedor=ProveedorIdentidadSimulado(contexto=IdentidadUsuarioConGrupos())
    ).ObtenerIdentidadLlamante()


def IdentidadAppServicePrincipal():
    """Devuelve la identidad resuelta del service principal de la app.

    Returns:
        IdentidadLlamante: identidad de service principal con App Id.
    """
    return ServicioIdentidadLlamante(
        proveedor=ProveedorIdentidadSimulado(contexto=IdentidadServicePrincipal())
    ).ObtenerIdentidadLlamante()


def CrearObjeto(tipo=TipoObjeto.CATALOGO, identificador="control"):
    """Construye un objeto securable del plano indicado.

    Args:
        tipo (TipoObjeto): tipo del objeto.
        identificador (str): identificación del objeto.

    Returns:
        ObjetoSecurable: objeto listo para consultar sus otorgamientos.
    """
    return ObjetoSecurable(identificador=identificador, tipo=tipo)


def Otorgamiento(principal, privilegio, objeto):
    """Construye un otorgamiento vigente como lo devuelve el contrato `Canal`.

    Args:
        principal (str): otorgatario reportado por el canal.
        privilegio (str): privilegio otorgado.
        objeto (ObjetoSecurable): objeto sobre el que se otorga (puede ser un
            padre del consultado, para simular herencia).

    Returns:
        ItemGrant: otorgamiento vigente.
    """
    return ItemGrant(
        principal=Principal(identificador=principal, tipo="usuario"),
        privilegio=privilegio,
        objeto=objeto,
    )


def CrearResolutor(canal_datos=None, canal_control=None, enrutador=None,
                   registrador_errores=None):
    """Construye el resolutor con los canales de prueba por defecto.

    Args:
        canal_datos (Canal | None): canal del plano de datos; por defecto uno
            simulado nuevo.
        canal_control (Canal | None): canal del plano de control; por defecto
            uno simulado nuevo.
        enrutador (object | None): enrutador inyectado, para probar el caso
            "plano sin canal configurado".
        registrador_errores (object | None): escritor de bitácora de errores.

    Returns:
        ResolutorPrivilegiosEfectivos: resolutor listo para resolver.
    """
    return ResolutorPrivilegiosEfectivos(
        canal_datos=canal_datos or CanalDatosSimulado(),
        canal_control=canal_control or CanalControlSimulado(),
        enrutador=enrutador,
        registrador_errores=registrador_errores,
    )


class CanalQueRegistraConsultas(CanalDatosSimulado):
    """Canal de prueba que recuerda qué objetos se le consultaron."""

    def __init__(self):
        """Inicializa el canal simulado y la bitácora de consultas."""
        super().__init__()
        self.consultas = []

    def ListarGrantsVigentes(self, objeto):
        """Registra la consulta y delega en el canal simulado.

        Args:
            objeto (ObjetoSecurable): objeto consultado.

        Returns:
            list[ItemGrant]: otorgamientos vigentes reportados.
        """
        self.consultas.append(objeto)
        return super().ListarGrantsVigentes(objeto)


class EnrutadorSinCanalParaElPlano:
    """Doble de enrutador que falla como un plano sin canal configurado."""

    def CanalParaObjeto(self, objeto):
        """Lanza siempre: no hay canal para ese plano.

        Args:
            objeto (ObjetoSecurable): objeto a enrutar (no se usa).

        Returns:
            nunca retorna.

        Raises:
            ErrorDominio: plano sin canal de ejecución configurado.
        """
        raise ErrorDominio(
            f"El plano {objeto.plano.value} no tiene canal configurado."
        )


def TestObjetoDelPlanoDeDatosUsaElCanalDeDatos():
    """Escenario 'Objeto del plano de datos': consulta por el canal SQL."""
    canal_datos = CanalQueRegistraConsultas()
    objeto = CrearObjeto(TipoObjeto.CATALOGO, "control")
    resolutor = CrearResolutor(canal_datos=canal_datos)

    resolutor.ResolverPrivilegiosEfectivos(IdentidadUsuario(), objeto)

    assert canal_datos.consultas == [objeto], (
        "La consulta del plano de datos debe ir al canal de datos"
    )


def TestObjetoDelPlanoDeControlUsaElCanalDeControl():
    """Escenario 'Objeto del plano de control': consulta por SDK/REST."""
    canal_datos = CanalQueRegistraConsultas()
    canal_control = CanalControlSimulado()
    objeto = CrearObjeto(TipoObjeto.SQL_WAREHOUSE, "a1b2c3d4")
    canal_control.ConfigurarGrantsVigentes(objeto, [])
    resolutor = CrearResolutor(
        canal_datos=canal_datos, canal_control=canal_control
    )

    vista = resolutor.ResolverPrivilegiosEfectivos(IdentidadUsuario(), objeto)

    assert canal_datos.consultas == [], "No debe consultarse el canal de datos"
    assert vista.plano is Plano.CONTROL
    assert vista.canal_consultado == "control"


def TestOtorgamientoDirectoAlUsuarioEsEfectivo():
    """Escenario 'Otorgamiento directo al usuario' del spec."""
    objeto = CrearObjeto()
    canal_datos = CanalDatosSimulado()
    canal_datos.ConfigurarGrantsVigentes(
        objeto, [Otorgamiento(IDENTIFICADOR_USUARIO_DEMO, "USE CATALOG", objeto)]
    )
    resolutor = CrearResolutor(canal_datos=canal_datos)

    vista = resolutor.ResolverPrivilegiosEfectivos(IdentidadUsuario(), objeto)

    assert vista.TieneElPrivilegio("USE CATALOG")
    assert vista.ObtenerOrigenDelPrivilegio("USE CATALOG") is OrigenPrivilegio.DIRECTO


def TestOtorgamientoALosGruposDelLlamanteEsEfectivo():
    """Escenario 'Otorgamiento a un grupo del llamante' (dos formatos)."""
    objeto = CrearObjeto()
    canal_datos = CanalDatosSimulado()
    canal_datos.ConfigurarGrantsVigentes(
        objeto,
        [
            # Unity Catalog reporta al grupo por su identificador opaco.
            Otorgamiento(ID_GRUPO_ADMINS_DEMO, "SELECT", objeto),
        ],
    )
    canal_control = CanalControlSimulado()
    objeto_warehouse = CrearObjeto(TipoObjeto.SQL_WAREHOUSE, "wh1")
    # La Permissions API reporta al grupo por su nombre.
    canal_control.ConfigurarGrantsVigentes(
        objeto_warehouse,
        [Otorgamiento(NOMBRE_GRUPO_ADMINS_DEMO, "CAN_USE", objeto_warehouse)],
    )
    resolutor = CrearResolutor(
        canal_datos=canal_datos, canal_control=canal_control
    )

    vista_datos = resolutor.ResolverPrivilegiosEfectivos(
        IdentidadUsuario(), objeto
    )
    vista_control = resolutor.ResolverPrivilegiosEfectivos(
        IdentidadUsuario(), objeto_warehouse
    )

    assert vista_datos.TieneElPrivilegio("SELECT")
    assert vista_control.TieneElPrivilegio("CAN_USE")


def TestOtorgamientoAServicePrincipalAjenoNoEsEfectivo():
    """Escenario 'Otorgamiento a un service principal distinto del llamante'.

    La coincidencia por formato de id NO debe abrir la puerta: un otorgamiento
    hecho a otro principal no es efectivo para un usuario, aunque ambos estén
    en el workspace.
    """
    objeto = CrearObjeto()
    canal_datos = CanalDatosSimulado()
    canal_datos.ConfigurarGrantsVigentes(
        objeto,
        [
            Otorgamiento(OTRO_SERVICE_PRINCIPAL, "MANAGE", objeto),
            Otorgamiento(APP_ID_OTRO_SERVICE_PRINCIPAL, "SELECT", objeto),
        ],
    )
    resolutor = CrearResolutor(canal_datos=canal_datos)

    vista = resolutor.ResolverPrivilegiosEfectivos(IdentidadUsuario(), objeto)

    assert vista.TieneElPrivilegio("MANAGE") is False
    assert vista.TieneElPrivilegio("SELECT") is False
    assert vista.privilegios_efectivos == frozenset()


def TestOtorgamientoAlAppIdDelLlamanteServicePrincipalEsEfectivo():
    """Escenario 'Otorgamiento al App Id del llamante service principal'."""
    objeto = CrearObjeto()
    canal_datos = CanalDatosSimulado()
    canal_datos.ConfigurarGrantsVigentes(
        objeto, [Otorgamiento(APP_ID_DEMO, "USE CATALOG", objeto)]
    )
    resolutor = CrearResolutor(canal_datos=canal_datos)

    vista = resolutor.ResolverPrivilegiosEfectivos(
        IdentidadAppServicePrincipal(), objeto
    )

    assert vista.TieneElPrivilegio("USE CATALOG")


def TestOtorgamientoDelPadreSeMarcaComoHeredado():
    """Escenario 'Privilegio heredado del padre' del spec.

    Unity Catalog reporta en `SHOW GRANT ON <objeto>` los otorgamientos del
    contenedor padre; el resolutor debe exponerlos como efectivos de origen
    heredado, con la referencia del objeto de origen.
    """
    hijo = CrearObjeto(TipoObjeto.ESQUEMA, "control.finance")
    padre = CrearObjeto(TipoObjeto.CATALOGO, "control")
    canal_datos = CanalDatosSimulado()
    canal_datos.ConfigurarGrantsVigentes(
        hijo, [Otorgamiento(IDENTIFICADOR_USUARIO_DEMO, "SELECT", padre)]
    )
    resolutor = CrearResolutor(canal_datos=canal_datos)

    vista = resolutor.ResolverPrivilegiosEfectivos(IdentidadUsuario(), hijo)

    assert vista.TieneElPrivilegio("SELECT")
    assert (
        vista.ObtenerOrigenDelPrivilegio("SELECT") is OrigenPrivilegio.HEREDADO
    )
    otorgamiento = vista.ObtenerOtorgamientoDelPrivilegio("SELECT")
    assert otorgamiento.heredado_de == "control"


def TestCanalQueNoReportaOrigenQuedaNoDeterminado():
    """Escenario 'Canal que no reporta el origen' del spec."""

    class OtorgamientoSinOrigen(ItemGrant):
        """Otorgamiento que informa su origen como no determinado."""

        # El contrato `Canal` admite que el reporte traiga `origen` explícito.
        @property
        def origen(self):
            """Origen declarado por el canal: no determinado.

            Returns:
                None: el canal no distingue entre directo y heredado.
            """
            return None

    objeto = CrearObjeto()
    otorgamiento = OtorgamientoSinOrigen(
        principal=Principal(
            identificador=IDENTIFICADOR_USUARIO_DEMO, tipo="usuario"
        ),
        privilegio="SELECT",
        objeto=objeto,
    )
    canal_datos = CanalDatosSimulado()
    canal_datos.ConfigurarGrantsVigentes(objeto, [otorgamiento])
    resolutor = CrearResolutor(canal_datos=canal_datos)

    vista = resolutor.ResolverPrivilegiosEfectivos(IdentidadUsuario(), objeto)

    assert vista.TieneElPrivilegio("SELECT")
    assert (
        vista.ObtenerOrigenDelPrivilegio("SELECT")
        is OrigenPrivilegio.NO_DETERMINADO
    )


def TestCanalQueInformaOrigenHeredadoConservaElSecurablePadre():
    """El canal que informa el origen también informa de dónde se hereda.

    La Permissions API marca cada nivel de permiso con `inherited` y con la
    lista `inherited_from_object` (verificado contra el workspace real en la
    capa integral). `OtorgamientoEfectivo` declara el campo `heredado_de` para
    conservar ese dato, así que el resolutor debe propagarlo en lugar de
    descartarlo: sin él, el reporte no puede explicar de qué securable padre
    viene el privilegio del llamante.
    """

    # Identificación del padre tal como la reporta el canal (no se hardcodea
    # un objeto del dominio: es el texto que devuelve el sistema externo).
    padre_reportado = "/sql/warehouses/"

    class OtorgamientoHeredadoInformado(ItemGrant):
        """Otorgamiento cuyo origen y padre declara explícitamente el canal."""

        @property
        def origen(self):
            """Origen declarado por el canal: heredado.

            Returns:
                str: valor canónico de `OrigenPrivilegio.HEREDADO`.
            """
            return OrigenPrivilegio.HEREDADO.value

        @property
        def heredado_de(self):
            """Securable padre del que viene el permiso, según el canal.

            Returns:
                str: identificación del padre reportada por el workspace.
            """
            return padre_reportado

    objeto = CrearObjeto(TipoObjeto.SQL_WAREHOUSE, "warehouse_demo")
    otorgamiento = OtorgamientoHeredadoInformado(
        principal=Principal(
            identificador=NOMBRE_GRUPO_ADMINS_DEMO, tipo="grupo"
        ),
        privilegio="CAN_MANAGE",
        objeto=objeto,
    )
    canal_control = CanalControlSimulado()
    canal_control.ConfigurarGrantsVigentes(objeto, [otorgamiento])
    resolutor = CrearResolutor(canal_control=canal_control)

    vista = resolutor.ResolverPrivilegiosEfectivos(IdentidadUsuario(), objeto)

    assert vista.TieneElPrivilegio("CAN_MANAGE")
    assert (
        vista.ObtenerOrigenDelPrivilegio("CAN_MANAGE")
        is OrigenPrivilegio.HEREDADO
    ), "Se respeta el origen que informa el canal"
    assert (
        vista.ObtenerOtorgamientoDelPrivilegio("CAN_MANAGE").heredado_de
        == padre_reportado
    ), "La vista conserva el securable padre que informó el canal"


def TestObjetoSinOtorgamientosDevuelveVistaVaciaDistinguibleDeFallo():
    """Escenario 'Objeto sin privilegios efectivos': vacío explícito, sin error."""
    objeto = CrearObjeto()
    canal_datos = CanalDatosSimulado()
    canal_datos.ConfigurarGrantsVigentes(objeto, [])
    resolutor = CrearResolutor(canal_datos=canal_datos)

    vista = resolutor.ResolverPrivilegiosEfectivos(IdentidadUsuario(), objeto)

    assert vista.privilegios_efectivos == frozenset()
    assert vista.FueConsultaExitosa is True


def TestVistaUnificadaExponeObjetoPlanoCanalYPriorilegios():
    """Escenario 'Objeto con privilegios efectivos' de la vista unificada."""
    objeto = CrearObjeto(TipoObjeto.VOLUMEN, "control.finance.docs")
    canal_datos = CanalDatosSimulado()
    canal_datos.ConfigurarGrantsVigentes(
        objeto,
        [
            Otorgamiento(IDENTIFICADOR_USUARIO_DEMO, "READ VOLUME", objeto),
            Otorgamiento(ID_GRUPO_ADMINS_DEMO, "WRITE VOLUME", objeto),
        ],
    )
    resolutor = CrearResolutor(canal_datos=canal_datos)

    vista = resolutor.ResolverPrivilegiosEfectivos(IdentidadUsuario(), objeto)

    assert vista.objeto is objeto
    assert vista.plano is Plano.DATOS
    assert vista.canal_consultado == "datos"
    assert vista.privilegios_efectivos == frozenset(
        {"READ VOLUME", "WRITE VOLUME"}
    )


def TestEmparejamientoEsInsensibleAMayusculasEnPlanoDeDatos():
    """Escenario de formatos: Unity Catalog no distingue mayúsculas."""
    objeto = CrearObjeto(TipoObjeto.CATALOGO, "CONTROL")
    canal_datos = CanalDatosSimulado()
    canal_datos.ConfigurarGrantsVigentes(
        objeto,
        [Otorgamiento(IDENTIFICADOR_USUARIO_DEMO.upper(), "USE CATALOG", objeto)],
    )
    resolutor = CrearResolutor(canal_datos=canal_datos)

    vista = resolutor.ResolverPrivilegiosEfectivos(IdentidadUsuario(), objeto)

    assert vista.TieneElPrivilegio("USE CATALOG")


def TestEmparejamientoEsSensibleAMayusculasEnPlanoDeControl():
    """Escenario de formatos: el plano de control distingue la escritura.

    `NORMALIZAR_A_MINUSCULAS_POR_PLANO` declara CONTROL como sensible a
    mayúsculas, así que una referencia con otra escritura NO coincide.
    """
    objeto = CrearObjeto(TipoObjeto.SQL_WAREHOUSE, "WH1")
    canal_control = CanalControlSimulado()
    canal_control.ConfigurarGrantsVigentes(
        objeto, [Otorgamiento("ADMINS", "CAN_USE", objeto)]
    )
    resolutor = CrearResolutor(canal_control=canal_control)

    vista = resolutor.ResolverPrivilegiosEfectivos(IdentidadUsuario(), objeto)

    assert vista.TieneElPrivilegio("CAN_USE") is False


def TestPlanoSinCanalConfiguradoFalladeFormaControlada():
    """Escenario 'Plano sin canal configurado': nada queda ejecutable."""
    resolutor = CrearResolutor(
        enrutador=EnrutadorSinCanalParaElPlano(),
        registrador_errores=None,
    )

    with pytest.raises(ErrorDominio):
        resolutor.ResolverPrivilegiosEfectivos(
            IdentidadUsuario(), CrearObjeto()
        )


def TestIdentidadNoResueltaSeRechazaExplicitamente():
    """Sin identidad del llamante no hay de quién resolver privilegios."""
    resolutor = CrearResolutor()

    with pytest.raises(ErrorDominio):
        resolutor.ResolverPrivilegiosEfectivos(None, CrearObjeto())


def TestLecturaDenegadaEsFailSafeSinPrivilegios():
    """Si el canal no permite leer los otorgamientos, nada es efectivo.

    El fallo de lectura del otorgatario NO es un error del sistema: se trata
    como cero privilegios efectivos (fail-safe: no se autoriza a ciegas).
    """
    from control_accesos.resolucion.resolutor import ResolutorPrivilegiosEfectivos

    class CanalQueNiegaLectura(CanalDatosSimulado):
        """Canal que responde permiso denegado al listar otorgamientos."""

        def ListarGrantsVigentes(self, objeto):
            """Niega la lectura de otorgamientos del objeto.

            Args:
                objeto (ObjetoSecurable): objeto consultado (no se usa).

            Raises:
                ErrorPrivilegiosInsuficientes: lectura de ACL denegada.
            """
            raise ErrorPrivilegiosInsuficientes(
                "[PERMISSION_DENIED] lectura de otorgamientos denegada"
            )

    resolutor = ResolutorPrivilegiosEfectivos(
        canal_datos=CanalQueNiegaLectura(), canal_control=CanalControlSimulado()
    )

    vista = resolutor.ResolverPrivilegiosEfectivos(
        IdentidadUsuario(), CrearObjeto()
    )

    assert vista.privilegios_efectivos == frozenset()
    assert vista.FueConsultaExitosa is False
