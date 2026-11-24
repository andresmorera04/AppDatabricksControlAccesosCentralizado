"""Pruebas unitarias de la autenticación on-behalf-of del llamante.

Cubren los escenarios del spec `caller-identity` (change `auth-caller-obo`):

- "Identificación del llamante vía on-behalf-of": llamante autenticado y
  contexto ausente sin excepción no controlada.
- "El llamante se representa como un principal del dominio": usuario, grupo y
  service principal (con App Id).
- "Los service principals son principales independientes": a un usuario no se
  le atribuyen service principals del workspace.
- "Resolución de grupos del llamante": con grupos, y sin grupos de forma
  distinguible de un fallo de resolución.
- "Referencias de identidad para el emparejamiento de otorgamientos".
- "Errores de autenticación visibles y controlados".

No hay conexión alguna: el contexto on-behalf-of llega por el puerto
`ProveedorIdentidadLlamante` con dobles definidos en este mismo archivo
(design.md D1), y la bitácora de errores se sustituye por un espía.
"""

import pytest

from control_accesos.autenticacion.errores import (
    ErrorAutenticacionLlamante,
    ErrorContextoLlamanteAusente,
)
from control_accesos.autenticacion.modelos import ContextoLlamante, Grupo
from control_accesos.autenticacion.proveedores import ProveedorIdentidadLlamante
from control_accesos.autenticacion.servicio import ServicioIdentidadLlamante
from control_accesos.dominio.enumeraciones import TipoPrincipal


class ProveedorFijo(ProveedorIdentidadLlamante):
    """Doble de prueba: devuelve el contexto recibido, o lanza lo configurado.

    Args:
        contexto (ContextoLlamante | None): contexto on-behalf-of a devolver.
        excepcion (BaseException | None): excepción a lanzar en su lugar.
    """

    def __init__(self, contexto=None, excepcion=None):
        """Guarda el contexto y la excepción configurados, y cuenta llamadas."""
        self._contexto = contexto
        self._excepcion = excepcion
        # Trazabilidad para la prueba de caché por invocación.
        self.llamadas_recibidas = 0

    def ObtenerContexto(self):
        """Devuelve el contexto configurado o lanza la excepción configurada.

        Returns:
            ContextoLlamante | None: el contexto programado para la prueba.

        Raises:
            BaseException: la excepción programada, si aplica.
        """
        self.llamadas_recibidas += 1
        if self._excepcion is not None:
            raise self._excepcion
        return self._contexto


class RegistradorErroresEspia:
    """Espía del contrato de `BitacoraErrores.Registrar`.

    Attributes:
        registrados (list[dict]): llamadas recibidas, con excepción, módulo,
            usuario y contexto.
    """

    def __init__(self):
        """Inicializa la lista de registros recibidos."""
        self.registrados = []

    def Registrar(self, excepcion, modulo, usuario=None, contexto=""):
        """Guarda la llamada en lugar de escribirla en una tabla delta.

        Args:
            excepcion (BaseException): excepción capturada reportada.
            modulo (str): módulo que reportó el fallo.
            usuario (str | None): usuario de la operación fallida.
            contexto (str): contexto de la operación que falló.

        Returns:
            dict: la llamada registrada por este espía.
        """
        llamado = {
            "excepcion": excepcion,
            "modulo": modulo,
            "usuario": usuario,
            "contexto": contexto,
        }
        self.registrados.append(llamado)
        return llamado


def ContextoUsuario(con_grupos=True):
    """Construye el contexto de un usuario llamante con o sin grupos.

    Args:
        con_grupos (bool): si True, el usuario pertenece a dos grupos.

    Returns:
        ContextoLlamante: contexto de usuario listo para el proveedor.
    """
    grupos = (
        (
            Grupo(identificador="81065872484794", nombre="admins"),
            Grupo(identificador="83195513137921", nombre="users"),
        )
        if con_grupos
        else ()
    )
    return ContextoLlamante(
        tipo=TipoPrincipal.USUARIO,
        identificador="andres@ejemplo.com",
        nombre_mostrable="Andrés Morea",
        grupos=grupos,
    )


def TestLlamanteAutenticadoExponeIdentidad():
    """Escenario 'Llamante autenticado': el contexto válido resuelve identidad."""
    servicio = ServicioIdentidadLlamante(
        proveedor=ProveedorFijo(contexto=ContextoUsuario())
    )

    identidad = servicio.ObtenerIdentidadLlamante()

    assert identidad is not None, "Un contexto válido debe resolver identidad."
    assert identidad.principal.identificador == "andres@ejemplo.com"
    assert servicio.IdentidadResuelta is True


def TestContextoAusenteDejaIdentidadSinResolver():
    """Escenario 'Contexto de llamante ausente': sin excepción no controlada."""
    servicio = ServicioIdentidadLlamante(
        proveedor=ProveedorFijo(
            excepcion=ErrorContextoLlamanteAusente(
                "La invocación no trae contexto de usuario."
            )
        )
    )

    identidad = servicio.ObtenerIdentidadLlamante()

    assert identidad is None, "El contexto ausente deja la identidad sin resolver."
    assert servicio.IdentidadResuelta is False


def TestProveedorQueDevuelveNoneSeTrataComoContextoAusente():
    """Un proveedor sin contexto (None) es el mismo caso de contexto ausente."""
    servicio = ServicioIdentidadLlamante(proveedor=ProveedorFijo(contexto=None))

    assert servicio.ObtenerIdentidadLlamante() is None


def TestLlamanteUsuarioTipoUsuario():
    """Escenario 'Llamante usuario': el principal lleva tipo `usuario`."""
    servicio = ServicioIdentidadLlamante(
        proveedor=ProveedorFijo(contexto=ContextoUsuario())
    )

    identidad = servicio.ObtenerIdentidadLlamante()

    assert identidad.principal.tipo is TipoPrincipal.USUARIO


def TestLlamanteGrupoTipoGrupo():
    """Escenario 'Llamante grupo': el principal lleva tipo `grupo`."""
    contexto = ContextoLlamante(
        tipo=TipoPrincipal.GRUPO, identificador="users", nombre_mostrable="users"
    )
    servicio = ServicioIdentidadLlamante(proveedor=ProveedorFijo(contexto=contexto))

    identidad = servicio.ObtenerIdentidadLlamante()

    assert identidad.principal.tipo is TipoPrincipal.GRUPO


def TestLlamanteServicePrincipalExponeAppId():
    """Escenario 'Llamante service principal con App Id' del spec."""
    contexto = ContextoLlamante(
        tipo=TipoPrincipal.SERVICE_PRINCIPAL,
        identificador="app-62644q prueba-app-control",
        nombre_mostrable="app-62644q prueba-app-control",
        app_id="6a20388a-9db2-45a2-9c9b-a7b385e730ba",
        grupos=(Grupo(identificador="2127785295117792", nombre="users"),),
    )
    servicio = ServicioIdentidadLlamante(proveedor=ProveedorFijo(contexto=contexto))

    identidad = servicio.ObtenerIdentidadLlamante()

    assert identidad.principal.tipo is TipoPrincipal.SERVICE_PRINCIPAL
    assert identidad.app_id == "6a20388a-9db2-45a2-9c9b-a7b385e730ba"


def TestServicePrincipalSinAppIdSeRechaza():
    """La identidad de un service principal exige su App Id (fail-fast)."""
    from control_accesos.autenticacion.modelos import IdentidadLlamante

    principal = _PrincipalUsuario(TipoPrincipal.SERVICE_PRINCIPAL)

    with pytest.raises(ErrorAutenticacionLlamante):
        IdentidadLlamante(principal=principal, grupos=())


def TestAppIdEnUnUsuarioSeRechaza():
    """El App Id solo aplica a service principals: en un usuario se rechaza."""
    from control_accesos.autenticacion.modelos import IdentidadLlamante

    principal = _PrincipalUsuario(TipoPrincipal.USUARIO)

    with pytest.raises(ErrorAutenticacionLlamante):
        IdentidadLlamante(
            principal=principal, grupos=(), app_id="6a20388a-9db2-45a2"
        )


def _PrincipalUsuario(tipo):
    """Construye un `Principal` del dominio con el tipo indicado.

    Args:
        tipo (TipoPrincipal): tipo del principal.

    Returns:
        Principal: principal del dominio para probar la identidad.
    """
    from control_accesos.dominio.modelos import Principal

    return Principal(identificador="llamante@ejemplo.com", tipo=tipo)


def TestReferenciasDeIdentidadDeUnUsuarioConGrupos():
    """Escenario 'Referencias de un usuario con grupos' del spec."""
    servicio = ServicioIdentidadLlamante(
        proveedor=ProveedorFijo(contexto=ContextoUsuario())
    )

    referencias = servicio.ObtenerIdentidadLlamante().ReferenciasDeIdentidad()

    # Usuario (identificador y nombre mostrable) y ambos grupos (id y nombre).
    assert "andres@ejemplo.com" in referencias
    assert "Andrés Morea" in referencias
    assert "81065872484794" in referencias
    assert "admins" in referencias
    assert "83195513137921" in referencias
    assert "users" in referencias


def TestReferenciasNoIncluyenServicePrincipalsDelWorkspace():
    """Escenario 'Service principal distinto del llamante': no se le atribuyen.

    El workspace tiene service principals con otorgamientos propios, pero a un
    usuario llamante no entran en sus referencias: solo su identidad y grupos.
    """
    servicio = ServicioIdentidadLlamante(
        proveedor=ProveedorFijo(contexto=ContextoUsuario())
    )

    identidad = servicio.ObtenerIdentidadLlamante()
    referencias = identidad.ReferenciasDeIdentidad()

    assert identidad.app_id is None
    assert "app-62644q prueba-app-control" not in referencias
    assert "6a20388a-9db2-45a2-9c9b-a7b385e730ba" not in referencias


def TestReferenciasDeUnServicePrincipalIncluyenAppIdYNombre():
    """Escenario 'Referencias de un service principal' del spec."""
    contexto = ContextoLlamante(
        tipo=TipoPrincipal.SERVICE_PRINCIPAL,
        identificador="app-62644q prueba-app-control",
        app_id="6a20388a-9db2-45a2-9c9b-a7b385e730ba",
        grupos=(Grupo(identificador="2127785295117792", nombre="users"),),
    )
    servicio = ServicioIdentidadLlamante(proveedor=ProveedorFijo(contexto=contexto))

    referencias = servicio.ObtenerIdentidadLlamante().ReferenciasDeIdentidad()

    assert "6a20388a-9db2-45a2-9c9b-a7b385e730ba" in referencias
    assert "app-62644q prueba-app-control" in referencias
    assert "users" in referencias


def TestObtenerGruposDelLlamanteConGrupos():
    """Escenario 'Llamante con grupos': devuelve todos, sin omitir ninguno."""
    servicio = ServicioIdentidadLlamante(
        proveedor=ProveedorFijo(contexto=ContextoUsuario())
    )

    grupos = servicio.ObtenerGruposLlamante()

    assert len(grupos) == 2
    assert {grupo.nombre for grupo in grupos} == {"admins", "users"}


def TestObtenerGruposVaciosDistinguibleDeFallo():
    """Escenario 'Llamante sin grupos': vacío explícito, no un fallo."""
    servicio_resuelto = ServicioIdentidadLlamante(
        proveedor=ProveedorFijo(contexto=ContextoUsuario(con_grupos=False))
    )
    servicio_fallido = ServicioIdentidadLlamante(
        proveedor=ProveedorFijo(
            excepcion=ErrorContextoLlamanteAusente("sin contexto")
        )
    )

    # Ausencia de grupos: identidad resuelta y lista vacía.
    assert servicio_resuelto.ObtenerGruposLlamante() == ()
    assert servicio_resuelto.IdentidadResuelta is True

    # Fallo de resolución: la identidad no quedó resuelta.
    assert servicio_fallido.ObtenerGruposLlamante() == ()
    assert servicio_fallido.IdentidadResuelta is False


def TestIdentidadSeResuelveUnaSolaVezPorInvocacion():
    """Caché por invocación (design.md D1): el proveedor se consulta una vez."""
    proveedor = ProveedorFijo(contexto=ContextoUsuario())
    servicio = ServicioIdentidadLlamante(proveedor=proveedor)

    primera = servicio.ObtenerIdentidadLlamante()
    segunda = servicio.ObtenerIdentidadLlamante()
    servicio.ObtenerGruposLlamante()

    assert primera is segunda
    assert proveedor.llamadas_recibidas == 1


def TestFalloDelProveedorSeRegistraEnBitacoraYContinua():
    """Escenario 'Token de usuario inválido o ausente': error controlado.

    El fallo se captura, se registra en la bitácora de errores y la identidad
    queda sin resolver, sin propagar la excepción al llamador.
    """
    excepcion = ValueError("token expirado")
    registrador = RegistradorErroresEspia()
    servicio = ServicioIdentidadLlamante(
        proveedor=ProveedorFijo(excepcion=excepcion),
        registrador_errores=registrador,
    )

    assert servicio.ObtenerIdentidadLlamante() is None

    assert len(registrador.registrados) == 1
    registro = registrador.registrados[0]
    assert registro["excepcion"] is excepcion
    assert registro["modulo"], "El registro debe identificar el módulo"


def TestIdentificadorVacioSeRegistraComoFalloControlado():
    """Escenario 'Identificador del llamante vacío': error registrado."""
    contexto = ContextoLlamante(
        tipo=TipoPrincipal.USUARIO, identificador="   ", nombre_mostrable="x"
    )
    registrador = RegistradorErroresEspia()
    servicio = ServicioIdentidadLlamante(
        proveedor=ProveedorFijo(contexto=contexto),
        registrador_errores=registrador,
    )

    assert servicio.ObtenerIdentidadLlamante() is None
    assert len(registrador.registrados) == 1


def TestSinRegistradorNoHayErrorPropagado():
    """La bitácora es opcional: sin registrador, el fallo sigue controlado."""
    servicio = ServicioIdentidadLlamante(
        proveedor=ProveedorFijo(excepcion=RuntimeError("servicio no disponible"))
    )

    assert servicio.ObtenerIdentidadLlamante() is None


def TestProveedorInvalidoSeRechaza():
    """El puerto es obligatorio: un proveedor que no lo implementa se rechaza."""
    with pytest.raises(ErrorAutenticacionLlamante):
        ServicioIdentidadLlamante(proveedor=object())


# ---------------------------------------------------------------------------
# ProveedorIdentidadSimulado (tarea 1.4): identidades configurables sin
# conexión, una por escenario del spec `caller-identity`.
# ---------------------------------------------------------------------------


def TestSimuladoResuelveUsuarioConGrupos():
    """El simulado de usuario con grupos resuelve identidad y sus grupos."""
    from control_accesos.autenticacion.simulados import (
        ProveedorIdentidadSimulado,
        IdentidadUsuarioConGrupos,
    )

    proveedor = ProveedorIdentidadSimulado(contexto=IdentidadUsuarioConGrupos())
    servicio = ServicioIdentidadLlamante(proveedor=proveedor)

    identidad = servicio.ObtenerIdentidadLlamante()

    assert identidad.principal.tipo is TipoPrincipal.USUARIO
    assert len(servicio.ObtenerGruposLlamante()) == 2


def TestSimuladoResuelveServicePrincipalConAppId():
    """El simulado de service principal expone identidad con App Id."""
    from control_accesos.autenticacion.simulados import (
        APP_ID_DEMO,
        IdentidadServicePrincipal,
        ProveedorIdentidadSimulado,
    )

    servicio = ServicioIdentidadLlamante(
        proveedor=ProveedorIdentidadSimulado(
            contexto=IdentidadServicePrincipal()
        )
    )

    identidad = servicio.ObtenerIdentidadLlamante()

    assert identidad.app_id == APP_ID_DEMO
    assert APP_ID_DEMO in identidad.ReferenciasDeIdentidad()


def TestSimuladoDeContextoAusenteNoPropagaExcepcion():
    """`ContextoAusente()` deja la identidad sin resolver, sin excepción."""
    from control_accesos.autenticacion.simulados import ContextoAusente

    servicio = ServicioIdentidadLlamante(proveedor=ContextoAusente())

    assert servicio.ObtenerIdentidadLlamante() is None
    assert servicio.IdentidadResuelta is False


def TestSimuladoFallidoRegistraSinRomperConteo():
    """`ContextoConFallo()` registra y deja identidad sin resolver."""
    from control_accesos.autenticacion.simulados import ContextoConFallo

    proveedor = ContextoConFallo()
    registrador = RegistradorErroresEspia()
    servicio = ServicioIdentidadLlamante(
        proveedor=proveedor, registrador_errores=registrador
    )

    assert servicio.ObtenerIdentidadLlamante() is None
    assert len(registrador.registrados) == 1
    assert proveedor.llamadas_recibidas == 1


def TestSimuladoRechazaConfiguracionAmbigua():
    """Contexto y excepción a la vez es ambiguo y se rechaza al construirlo."""
    from control_accesos.autenticacion.simulados import (
        IdentidadUsuarioConGrupos,
        ProveedorIdentidadSimulado,
    )

    with pytest.raises(ErrorAutenticacionLlamante):
        ProveedorIdentidadSimulado(
            contexto=IdentidadUsuarioConGrupos(),
            excepcion=RuntimeError("ambiguo"),
        )
