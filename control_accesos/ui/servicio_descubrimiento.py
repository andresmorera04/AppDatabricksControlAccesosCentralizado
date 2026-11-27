"""Servicio de descubrimiento de opciones de la UI (design.md D6, tarea 3.1).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`.

Capa de aplicación entre el descubrimiento real (SCIM con el service principal,
`DescubridorPrincipales` del change broker) y la vista: traduce los principals
descubiertos a `Principal` del dominio, preserva el App Id de los service
principals como su identificador, y conserva sin alterar el orden, el límite y
la distinción entre fallo y lista vacía que ya aporta el adaptador.

Un fallo del listado se traduce a `ErrorDescubrimientoOpciones` (error de
catálogo de opciones): la UI lo distingue de una lista auténticamente vacía y
no habilita ejecución sobre datos incompletos (spec `grant-management-ui`).
"""

from control_accesos.canales.reales.descubrimiento_principales import (
    ErrorListadoPrincipales,
)
from control_accesos.dominio.modelos import Principal

# Identificador del módulo para trazas y mensajes (convención del proyecto).
MODULO_DESCUBRIMIENTO_UI = "ui.servicio_descubrimiento"


class ErrorDescubrimientoOpciones(RuntimeError):
    """Fallo del descubrimiento de opciones, distinguible de una lista vacía.

    Representa "no pude listar", nunca "no hay opciones": la vista trata este
    error de forma controlada y no habilita ejecución sobre datos incompletos.
    """


class ServicioDescubrimientoUi:
    """Traduce las opciones descubiertas a los modelos del dominio.

    Delegado por acción sobre el descubridor SCIM del service principal
    (contexto broker, design.md D6): la UI lista principals con el SP porque el
    token OBO del llamante carece de los scopes SCIM. El servicio NO valida
    autoridad (eso lo hace la disponibilidad, design.md D7): solo descubrir.

    Attributes:
        descubridor_principales (DescubridorPrincipales): adaptador SCIM-SP
            inyectado, con `ListarUsuarios`, `ListarGrupos`,
            `ListarServicePrincipals` y `ListarPrincipales`.
    """

    def __init__(self, descubridor_principales):
        """Inicializa el servicio con el descubridor inyectado.

        Args:
            descubridor_principales (DescubridorPrincipales): adaptador real o
                doble en pruebas.

        Raises:
            ValueError: si el descubridor es nulo (fail-fast de cableado).
        """
        if descubridor_principales is None:
            raise ValueError(
                "Se requiere un descubridor de principals (service principal) "
                "para el servicio de descubrimiento de la UI."
            )
        self._descubridor_principales = descubridor_principales

    def DescubrirUsuarios(self):
        """Lista los usuarios del workspace como `Principal` del dominio.

        Returns:
            tuple[Principal, ...]: usuarios, en el orden del servicio.
        """
        return self._Traducir(self._descubridor_principales.ListarUsuarios)

    def DescubrirGrupos(self):
        """Lista los grupos del workspace como `Principal` del dominio.

        Returns:
            tuple[Principal, ...]: grupos, en el orden del servicio.
        """
        return self._Traducir(self._descubridor_principales.ListarGrupos)

    def DescubrirServicePrincipals(self):
        """Lista los service principals como `Principal` (App Id preservado).

        Returns:
            tuple[Principal, ...]: service principals cuyo identificador es su
                App Id (design.md D4), en el orden del servicio.
        """
        return self._Traducir(
            self._descubridor_principales.ListarServicePrincipals
        )

    def DescubrirPrincipales(self):
        """Lista los tres tipos de principal en un solo agregado estable.

        Returns:
            tuple[Principal, ...]: usuarios, luego grupos y luego service
                principals, en el orden del servicio de cada tipo.
        """
        return self._Traducir(self._descubridor_principales.ListarPrincipales)

    def _Traducir(self, operacion):
        """Ejecuta el listado y traduce el resultado, tipificando el fallo.

        Args:
            operacion (callable): método `Listar*` del descubridor inyectado.

        Returns:
            tuple[Principal, ...]: opciones traducidas, o tupla vacía.

        Raises:
            ErrorDescubrimientoOpciones: si el listado falla (no si está vacío),
                con la causa encadenada y sin credenciales.
        """
        try:
            descubiertos = operacion()
        except ErrorListadoPrincipales as excepcion:
            raise ErrorDescubrimientoOpciones(
                f"[{MODULO_DESCUBRIMIENTO_UI}] No se pudieron descubrir los "
                f"principals del workspace: {excepcion}"
            ) from excepcion

        return tuple(
            Principal(identificador=principal.identificador, tipo=principal.tipo)
            for principal in descubiertos
        )
