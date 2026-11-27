"""Servicio de construcción y validación de solicitudes de grants de la UI.

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`, tarea 4.1.

Capa de aplicación entre la selección del usuario y el pipeline: valida la
cardinalidad y la forma de la solicitud y construye el modelo del dominio
(`SolicitudGrant` 1 a 1, o `SolicitudLoteGrant` 1 a N / N a 1), reutilizando
los modelos del dominio y la `ConsultoraMatrizPrivilegios` (sin regla de
autorización nueva). Valida, antes de invocar al pipeline y en este orden:

- conjuntos no vacíos (principal, privilegio, objeto), con mensaje por conjunto;
- principals y objetos con identificación de dominio válida (no vacía);
- un único `TipoObjeto` por solicitud (el filtrado de privilegios es inequívoco);
- cada privilegio es válido para el tipo elegido según la matriz;
- la cardinalidad N a M se rechaza explícitamente (fuera de alcance).
"""

from control_accesos.dominio.modelos import (
    NormalizarPrivilegio,
    ObjetoSecurable,
    Principal,
    SolicitudGrant,
    SolicitudLoteGrant,
)
from control_accesos.matriz.consultora import ConsultoraMatrizPrivilegios

# Identificador del módulo para trazas y mensajes (convención del proyecto).
MODULO_SOLICITUD_UI = "ui.servicio_solicitud"


class ErrorSolicitudUi(RuntimeError):
    """Solicitud de grants de la UI inválida en su forma o cardinalidad."""


class ServicioSolicitudGrantsUi:
    """Valida y construye la solicitud de grants a partir de la selección.

    Attributes:
        consultora (ConsultoraMatrizPrivilegios): consultora de la matriz para
            validar cada combinación privilegio x tipo de objeto.
    """

    def __init__(self, consultora=None):
        """Inicializa el servicio con la consultora inyectada.

        Args:
            consultora (ConsultoraMatrizPrivilegios | None): consultora a usar;
                None usa la matriz declarada del proyecto.
        """
        self._consultora = (
            ConsultoraMatrizPrivilegios() if consultora is None else consultora
        )

    def Construir(self, principales, privilegios, objetos):
        """Valida la selección y construye la solicitud del dominio.

        Args:
            principales (Iterable[Principal]): principals de la selección.
            privilegios (Iterable[str]): privilegios seleccionados.
            objetos (Iterable[ObjetoSecurable]): objetos seleccionados.

        Returns:
            SolicitudGrant | SolicitudLoteGrant: solicitud validada (1 a 1 para
                un principal y un objeto; lote para 1 a N o N a 1).

        Raises:
            ErrorSolicitudUi: si la forma es inválida (conjuntos vacíos,
                identificadores inválidos, tipos de objeto mezclados,
                privilegio fuera de la matriz o cardinalidad N a M).
        """
        lista_principales = tuple(principales or ())
        lista_privilegios = tuple(privilegios or ())
        lista_objetos = tuple(objetos or ())

        if not lista_principales:
            raise ErrorSolicitudUi(
                "La solicitud de grants requiere al menos un principal."
            )
        if not lista_privilegios:
            raise ErrorSolicitudUi(
                "La solicitud de grants requiere al menos un privilegio."
            )
        if not lista_objetos:
            raise ErrorSolicitudUi(
                "La solicitud de grants requiere al menos un objeto."
            )

        self._ValidarPrincipales(lista_principales)
        tipo_objeto = self._ValidarObjetos(lista_objetos)
        self._ValidarPrivilegios(lista_privilegios, tipo_objeto)

        varios_principales = len(lista_principales) > 1
        varios_objetos = len(lista_objetos) > 1
        if varios_principales and varios_objetos:
            raise ErrorSolicitudUi(
                "La cardinalidad N a M (varios principals y varios objetos a "
                "la vez) está fuera de alcance en esta versión. Procese cada "
                "combinación como una solicitud 1 a 1, 1 a N o N a 1."
            )

        privilegios_canonicos = tuple(
            NormalizarPrivilegio(privilegio) for privilegio in lista_privilegios
        )

        if not varios_principales and not varios_objetos:
            return SolicitudGrant.Crear(
                principal=lista_principales[0],
                privilegios=privilegios_canonicos,
                objeto=lista_objetos[0],
            )
        return SolicitudLoteGrant(
            principales=lista_principales,
            privilegios=privilegios_canonicos,
            objetos=lista_objetos,
        )

    @staticmethod
    def _ValidarPrincipales(principales):
        """Valida que cada principal sea un `Principal` con identificador.

        Raises:
            ErrorSolicitudUi: si algún principal no es de dominio o no tiene
                identificador.
        """
        for principal in principales:
            if not isinstance(principal, Principal) or not principal.identificador:
                raise ErrorSolicitudUi(
                    "Principal inválido: se requiere un principal del dominio "
                    "con identificador no vacío."
                )

    @staticmethod
    def _ValidarObjetos(objetos):
        """Valida los objetos y exige un único tipo para todos.

        Returns:
            TipoObjeto: el tipo único de los objetos.

        Raises:
            ErrorSolicitudUi: si algún objeto no es de dominio, no tiene
                identificador o los tipos no coinciden.
        """
        for objeto in objetos:
            if not isinstance(objeto, ObjetoSecurable) or not objeto.identificador:
                raise ErrorSolicitudUi(
                    "Objeto inválido: se requiere un objeto del dominio con "
                    "identificador no vacío."
                )

        tipos = {objeto.tipo for objeto in objetos}
        if len(tipos) != 1:
            raise ErrorSolicitudUi(
                "La solicitud debe usar un único tipo de objeto: el filtrado "
                "de privilegios por tipo es inequívoco (design.md D2)."
            )
        return next(iter(tipos))

    def _ValidarPrivilegios(self, privilegios, tipo_objeto):
        """Valida cada privilegio contra la matriz para el tipo de objeto.

        Raises:
            ErrorSolicitudUi: si algún privilegio no es válido para el tipo,
                con el mensaje preciso de la consultora.
        """
        for privilegio in privilegios:
            if not self._consultora.EsCombinacionValida(privilegio, tipo_objeto):
                raise ErrorSolicitudUi(
                    self._consultora.MensajeCombinacionInvalida(
                        privilegio, tipo_objeto
                    )
                )
