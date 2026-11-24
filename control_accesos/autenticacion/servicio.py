"""Servicio de identidad del llamante (capability `caller-identity`).

`ServicioIdentidadLlamante` es el punto único por donde el resto de la
aplicación pregunta *quién me está invocando* (design.md D1). Compone:

- el puerto `ProveedorIdentidadLlamante`, origen del contexto OAuth
  on-behalf-of de la Databricks App;
- la conversión validada de ese dictado a `IdentidadLlamante`;
- el registro controlado de cualquier fallo en la bitácora de errores, con
  degradación explícita: el fallo **nunca** se propaga como excepción no
  controlada (spec `caller-identity` - "Errores de autenticación visibles y
  controlados").

Cachea el resultado por invocación: la identidad se consulta al proveedor una
sola vez por instancia del servicio, que corresponde a una corrida del
pipeline (decisión del humano: "cache de la identidad OBO por invocación").
Un mismo pipeline ve, por tanto, la misma identidad, aunque el workspace la
cambie a mitad de la corrida.

Example:
    >>> servicio = ServicioIdentidadLlamante(proveedor=proveedor_app)
    >>> identidad = servicio.ObtenerIdentidadLlamante()
    >>> identidad.ReferenciasDeIdentidad() if identidad else None
"""

import sys

from control_accesos.autenticacion.errores import (
    ErrorAutenticacionLlamante,
    ErrorContextoLlamanteAusente,
)
from control_accesos.autenticacion.modelos import IdentidadLlamante
from control_accesos.autenticacion.proveedores import ProveedorIdentidadLlamante
from control_accesos.dominio.enumeraciones import TipoPrincipal

# Módulo que se reporta en la bitácora de errores cuando esta capa falla.
MODULO_BITACORA_ERRORES = "autenticacion"

# Marca interna que distingue "aún no consultado" de "consultado y sin
# identidad": sin ella, None como valor cacheado volvería a consultar el
# proveedor en cada acceso.
_SIN_RESOLVER = object()


class ServicioIdentidadLlamante:
    """Resuelve y expone la identidad on-behalf-of del llamante."""

    def __init__(self, proveedor, registrador_errores=None):
        """Inicializa el servicio con su proveedor de contexto.

        Args:
            proveedor (ProveedorIdentidadLlamante): puerto del contexto real
                o simulado de la Databricks App.
            registrador_errores (BitacoraErrores | None): escritor de la
                bitácora de errores, opcional; debe exponer
                `Registrar(excepcion, modulo=..., usuario=..., contexto=...)`.
                Sin él, los fallos siguen degradando de forma controlada y
                quedan constancia visible en la salida local.

        Raises:
            ErrorAutenticacionLlamante: si el proveedor no implementa el
                contrato `ProveedorIdentidadLlamante`.
        """
        if not isinstance(proveedor, ProveedorIdentidadLlamante):
            raise ErrorAutenticacionLlamante(
                "El proveedor de identidad debe implementar el contrato "
                f"ProveedorIdentidadLlamante; se recibió "
                f"{type(proveedor).__name__}."
            )

        self._proveedor = proveedor
        self._registrador_errores = registrador_errores
        self._cache_identidad = _SIN_RESOLVER

    @property
    def IdentidadResuelta(self):
        """Indica si la identidad del llamante se resolvió correctamente.

        Permite distinguir la ausencia de grupos (identidad resuelta con lista
        vacía) de un fallo de resolución (identidad sin resolver), que el spec
        exige separar.

        Returns:
            bool: True si existe `IdentidadLlamante` resuelta.
        """
        return self.ObtenerIdentidadLlamante() is not None

    def ObtenerIdentidadLlamante(self):
        """Devuelve la identidad del llamante, o None si no se resolvió.

        Returns:
            IdentidadLlamante | None: identidad resuelta del principal que
                invoca la app; None cuando el contexto está ausente, el token
                no es verificable o la identidad es inconsistente.
        """
        if self._cache_identidad is not _SIN_RESOLVER:
            return self._cache_identidad

        identidad = self._ResolverIdentidad()
        self._cache_identidad = identidad
        return identidad

    def ObtenerGruposLlamante(self):
        """Devuelve los grupos del llamante, o una colección vacía.

        La ausencia de grupos (identidad resuelta sin membresías) se reporta
        igual que un fallo de resolución con una tupla vacía: lo que las
        distingue es `IdentidadResuelta` (spec `caller-identity` - "Resolución
        de grupos del llamante").

        Returns:
            tuple[Grupo, ...]: grupos del llamante.
        """
        # `ObtenerIdentidadLlamante` sirve desde el caché, así que esta ruta
        # no vuelve a consultar al proveedor (caché por invocación, D1).
        identidad = self.ObtenerIdentidadLlamante()
        if identidad is None:
            return ()
        return identidad.grupos

    def _ResolverIdentidad(self):
        """Consulta el contexto al proveedor y lo convierte en identidad.

        Todo fallo queda capturado aquí: se registra y se devuelve None, sin
        propagar la excepción al pipeline.

        Returns:
            IdentidadLlamante | None: identidad válida, o None si el contexto
                falta o no pudo convertirse.
        """
        try:
            contexto = self._proveedor.ObtenerContexto()
            if contexto is None:
                # La plataforma no reportó contexto: es el escenario
                # 'Contexto de llamante ausente'.
                raise ErrorContextoLlamanteAusente(
                    "La invocación no trae contexto de usuario on-behalf-of."
                )
            return self._ConstruirIdentidad(contexto)
        except Exception as excepcion:  # noqa: BLE001 - degradación controlada
            self._RegistrarFallo(excepcion)
            return None

    def _ConstruirIdentidad(self, contexto):
        """Convierte el dictado del contexto en una identidad validada.

        Args:
            contexto (ContextoLlamante): contexto reportado por el proveedor.

        Returns:
            IdentidadLlamante: identidad validada.

        Raises:
            ErrorContextoLlamanteAusente: si el identificador está vacío o es
                nulo, porque sin él no hay a quién atribuir privilegios.
            ErrorAutenticacionLlamante: si el tipo de principal no pertenece a
                la enumeración del dominio.
            ErrorIdentidadLlamanteInvalida: si la identidad resulta
                inconsistente (App Id ausente en un service principal, etc.).
        """
        identificador = contexto.identificador
        if identificador is None or not str(identificador).strip():
            raise ErrorContextoLlamanteAusente(
                "El contexto on-behalf-of reportado no incluye un "
                "identificador de principal: no se puede establecer quién "
                "es el llamante."
            )

        # El dominio normaliza y valida el tipo; si viene como texto, se
        # convierte a su miembro de la enumeración.
        from control_accesos.dominio.modelos import Principal

        try:
            principal = Principal(
                identificador=identificador,
                tipo=TipoPrincipal(contexto.tipo)
                if not isinstance(contexto.tipo, TipoPrincipal)
                else contexto.tipo,
            )
        except Exception as excepcion:
            raise ErrorAutenticacionLlamante(
                f"El contexto on-behalf-of describe un principal inválido: "
                f"{excepcion}"
            ) from excepcion

        return IdentidadLlamante(
            principal=principal,
            grupos=contexto.grupos,
            nombre_mostrable=contexto.nombre_mostrable,
            app_id=contexto.app_id,
        )

    def _RegistrarFallo(self, excepcion):
        """Registra el fallo en la bitácora de errores sin propagarlo.

        Args:
            excepcion (BaseException): excepción capturada al resolver.
        """
        if self._registrador_errores is None:
            # Sin bitácora, el fallo no se pierde en silencio: queda visible
            # en la salida local (degradación controlada, design.md D4).
            print(
                f"[AUTENTICACIÓN] No se pudo resolver la identidad del "
                f"llamante: {excepcion}",
                file=sys.stderr,
            )
            return

        try:
            self._registrador_errores.Registrar(
                excepcion,
                modulo=MODULO_BITACORA_ERRORES,
                usuario=None,
                contexto=(
                    "resolución de la identidad on-behalf-of del llamante "
                    "en la Databricks App"
                ),
            )
        except Exception as excepcion_registro:  # noqa: BLE001
            # La bitácora no puede convertirse en un punto de fallo en
            # cascada (design.md D7 de C2): se reporta en la salida local.
            print(
                f"[AUTENTICACIÓN] El fallo de identidad no pudo escribirse "
                f"en la bitácora de errores: {excepcion_registro}. "
                f"Fallo original: {excepcion}",
                file=sys.stderr,
            )
