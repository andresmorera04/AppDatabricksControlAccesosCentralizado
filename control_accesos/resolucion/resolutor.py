"""Resolutor de privilegios efectivos del llamante.

Componente central de `caller-privilege-resolution` (design.md D2). Lee los
otorgamientos vigentes del objeto objetivo **a través del contrato de canales
de C1** y decide cuáles pertenecen al llamante, de modo que la fase de
pre-flight pueda dividir la solicitud en ejecutables y bloqueados.

Qué hace y qué NO hace:

- **No** implementa un mecanismo de consulta propio por plano: reutiliza
  `Canal.ListarGrantsVigentes(objeto)` y `EnrutadorCanales`, que ya declaran
  el enrutamiento declarativo `Plano -> canal` (spec `channel-adapters` y
  `grant-pipeline`). Crear clases hermanas por canal habría duplicado ese
  contrato.
- **No** reimplementa la jerarquía de securables de Unity Catalog: los
  otorgamientos que el canal reporta sobre un contenedor padre se exponen con
  origen `HEREDADO`, tal como el propio sistema los informa.
- **No** otorga, revoca ni escribe permisos: es de solo lectura (spec).

Emparejamiento (design.md D2): un otorgamiento es del llamante si la
identificación de su otorgatario coincide con alguna referencia de
`IdentidadLlamante.ReferenciasDeIdentidad()` — el propio llamante, sus grupos
y, si es un service principal, su App Id — aplicando la política declarada de
normalización por plano (`NORMALIZAR_A_MINUSCULAS_POR_PLANO`): Unity Catalog
no distingue mayúsculas; el plano de control sí. Los service principals son
principales independientes: un usuario nunca hereda otorgamientos de uno.

Fail-safe: si el canal **deniega la lectura** de los otorgamientos, no se
afirma ningún privilegio (vista vacía con `FueConsultaExitosa` en False); la
ausencia de evidencia nunca se interpreta como autorización. Cualquier otro
fallo de consulta (`ErrorObjetivoInaccesible`) se propaga para que el split
clasifique los ítems afectados como `fallido`, no como
`privilegios_insuficientes`.
"""

import sys

from control_accesos.autenticacion.modelos import IdentidadLlamante
from control_accesos.canales.errores import ErrorPrivilegiosInsuficientes
from control_accesos.dominio.enumeraciones import Plano
from control_accesos.dominio.errores import ErrorDominio
from control_accesos.dominio.modelos import (
    NORMALIZAR_A_MINUSCULAS_POR_PLANO,
    ObjetoSecurable,
)
from control_accesos.pipeline.enrutador import EnrutadorCanales
from control_accesos.resolucion.enumeraciones import OrigenPrivilegio
from control_accesos.resolucion.errores import (
    ErrorIdentidadNoResuelta,
    ErrorObjetivoInaccesible,
)
from control_accesos.resolucion.modelos import (
    OtorgamientoEfectivo,
    PrivilegiosEfectivosVista,
)

# Módulo que se reporta en la bitácora de errores cuando esta capa falla.
MODULO_BITACORA_ERRORES = "resolucion"

# Nombre del canal que se expone en la vista unificada, por plano. Se declara
# como dato (no se infiere con if dispersos) y coincide con los valores de la
# enumeración `Plano`, de modo que reporte y bitácora hablen el mismo idioma.
NOMBRE_CANAL_POR_PLANO = {
    Plano.DATOS: Plano.DATOS.value,
    Plano.CONTROL: Plano.CONTROL.value,
}

# Centinela para distinguir "el canal no informa el origen" de "lo informa
# como None", sin usar None como señal ambigua.
_CANAL_NO_INFORMA_ORIGEN = object()


class ResolutorPrivilegiosEfectivos:
    """Resuelve qué privilegios efectivos tiene el llamante sobre un objeto."""

    def __init__(
        self,
        canal_datos=None,
        canal_control=None,
        enrutador=None,
        registrador_errores=None,
    ):
        """Inicializa el resolutor con los canales de cada plano.

        Args:
            canal_datos (Canal | None): canal del plano de datos (SHOW GRANTS
                en producción; simulado en las pruebas de C1-C3).
            canal_control (Canal | None): canal del plano de control (lectura
                de ACL de la Permissions API).
            enrutador (EnrutadorCanales | None): enrutador a usar; si es None
                se construye con los canales recibidos. Permite inyectar un
                doble que reproduzca un plano sin canal configurado.
            registrador_errores (BitacoraErrores | None): escritor de la
                bitácora de errores, opcional, con el contrato
                `Registrar(excepcion, modulo=..., usuario=..., contexto=...)`.

        Raises:
            ErrorDominio: si no se aporta enrutador ni canales válidos.
        """
        if enrutador is not None:
            self._enrutador = enrutador
        else:
            # El enrutador de C1 valida que ambos canales implementen `Canal`.
            self._enrutador = EnrutadorCanales(
                canal_datos=canal_datos, canal_control=canal_control
            )
        self._registrador_errores = registrador_errores

    def ResolverPrivilegiosEfectivos(self, identidad_llamante, objeto):
        """Resuelve los privilegios efectivos del llamante sobre un objeto.

        Args:
            identidad_llamante (IdentidadLlamante | None): identidad resuelta
                por `caller-identity`; None cuando no pudo resolverse.
            objeto (ObjetoSecurable): objeto securable objetivo.

        Returns:
            PrivilegiosEfectivosVista: vista unificada con los privilegios
                efectivos del llamante sobre el objeto.

        Raises:
            ErrorIdentidadNoResuelta: si no se dispone de identidad del
                llamante: sin a quién mirar, no puede afirmarse ningún
                privilegio (spec `caller-privilege-resolution`).
            ErrorObjetivoInaccesible: si los otorgamientos del objeto no
                pudieron consultarse (objeto inexistente, fallo de transporte,
                respuesta inválida o plano sin canal configurado).
        """
        if not isinstance(identidad_llamante, IdentidadLlamante):
            self._RegistrarFallo(
                ErrorIdentidadNoResuelta(
                    "No se dispone de la identidad del llamante: sin "
                    "identidad resuelta no pueden afirmarse privilegios "
                    "efectivos."
                ),
                usuario=None,
                contexto=f"resolviendo privilegios sobre '{_NombreObjeto(objeto)}'",
            )
            raise ErrorIdentidadNoResuelta(
                "No se dispone de la identidad del llamante: sin identidad "
                "resuelta no pueden afirmarse privilegios efectivos."
            )

        if not isinstance(objeto, ObjetoSecurable):
            raise ErrorDominio(
                "La resolución de privilegios requiere un ObjetoSecurable; "
                f"se recibió {type(objeto).__name__}."
            )

        otorgamientos = self._ConsultarOtorgamientosVigentes(
            identidad_llamante, objeto
        )

        # Caso fail-safe: lectura denegada, cero privilegios afirmados.
        if otorgamientos is None:
            return PrivilegiosEfectivosVista(
                objeto=objeto,
                plano=objeto.plano,
                canal_consultado=NOMBRE_CANAL_POR_PLANO[objeto.plano],
                otorgamientos=(),
                fue_consulta_exitosa=False,
            )

        return PrivilegiosEfectivosVista(
            objeto=objeto,
            plano=objeto.plano,
            canal_consultado=NOMBRE_CANAL_POR_PLANO[objeto.plano],
            otorgamientos=self._EmparejarConIdentidad(
                identidad_llamante, objeto, otorgamientos
            ),
        )

    def _ConsultarOtorgamientosVigentes(self, identidad_llamante, objeto):
        """Lee los otorgamientos vigentes del objeto por su canal de plano.

        Args:
            identidad_llamante (IdentidadLlamante): identidad del llamante,
                usada como `usuario` en el registro de errores.
            objeto (ObjetoSecurable): objeto a consultar.

        Returns:
            list[ItemGrant] | None: otorgamientos reportados por el canal, o
                None cuando la lectura fue denegada (fail-safe).

        Raises:
            ErrorObjetivoInaccesible: si la consulta falló por cualquier otra
                causa; el split reporta los ítems afectados como `fallido`.
        """
        try:
            canal = self._enrutador.CanalParaObjeto(objeto)
        except Exception as excepcion:
            raise self._FalloDeConsulta(
                excepcion, objeto, "no hay canal de consulta para el plano"
            ) from excepcion

        try:
            return list(canal.ListarGrantsVigentes(objeto))
        except ErrorPrivilegiosInsuficientes as error_denegado:
            # El ejecutor no puede leer los otorgamientos: no se afirma ningún
            # privilegio (fail-safe), pero el hecho queda registrado.
            self._RegistrarFallo(
                error_denegado,
                usuario=identidad_llamante.principal.identificador,
                contexto=(
                    f"lectura de otorgamientos denegada sobre "
                    f"'{_NombreObjeto(objeto)}'"
                ),
            )
            return None
        except Exception as excepcion:
            raise self._FalloDeConsulta(
                excepcion, objeto, "no se pudieron leer los otorgamientos"
            ) from excepcion

    def _FalloDeConsulta(self, excepcion, objeto, motivo):
        """Traduce un fallo de consulta a `ErrorObjetivoInaccesible` registrado.

        Args:
            excepcion (BaseException): excepción capturada del canal o del
                enrutador.
            objeto (ObjetoSecurable): objeto cuya consulta falló.
            motivo (str): descripción corta del motivo, para el registro.

        Returns:
            ErrorObjetivoInaccesible: error controlado listo para lanzar.
        """
        error = ErrorObjetivoInaccesible(
            f"No se pudieron consultar los otorgamientos de "
            f"'{_NombreObjeto(objeto)}': {motivo}. Causa: {excepcion}",
            objeto=objeto,
        )
        self._RegistrarFallo(
            excepcion,
            usuario=None,
            contexto=f"consulta de otorgamientos de '{_NombreObjeto(objeto)}'",
        )
        return error

    def _EmparejarConIdentidad(self, identidad_llamante, objeto, otorgamientos):
        """Deja solo los otorgamientos que corresponden al llamante.

        Args:
            identidad_llamante (IdentidadLlamante): identidad con sus
                referencias de emparejamiento.
            objeto (ObjetoSecurable): objeto consultado, para decidir si un
                otorgamiento es directo o heredado de un contenedor padre.
            otorgamientos (list[ItemGrant]): otorgamientos reportados por el
                canal, en su formato original.

        Returns:
            tuple[OtorgamientoEfectivo, ...]: otorgamientos efectivos, sin
                duplicar un privilegio ya obtenido por otra referencia; un
                otorgatario que no coincide con ninguna referencia se descarta
                (así un otorgamiento a otro service principal no se atribuye
                al usuario llamante).
        """
        referencias = self._ReferenciasNormalizadas(
            identidad_llamante, objeto.plano
        )

        efectivos = []
        privilegios_vistos = set()
        for otorgamiento in otorgamientos:
            otorgatario = getattr(otorgamiento.principal, "identificador", None)
            if otorgatario is None:
                # Un reporte sin otorgatario no puede atribuirse a nadie.
                continue

            clave = _NormalizarReferencia(otorgatario, objeto.plano)
            if clave not in referencias:
                continue

            privilegio = otorgamiento.privilegio
            if privilegio in privilegios_vistos:
                # El mismo privilegio puede llegar por el usuario y por un
                # grupo; se conserva la primera coincidencia.
                continue
            privilegios_vistos.add(privilegio)

            origen, padre = self._DeterminarOrigen(otorgamiento, objeto)
            efectivos.append(
                OtorgamientoEfectivo(
                    privilegio=privilegio,
                    origen=origen,
                    otorgatario=str(otorgatario),
                    referencia_coincidente=referencias[clave],
                    heredado_de=padre,
                )
            )

        return tuple(efectivos)

    def _ReferenciasNormalizadas(self, identidad_llamante, plano):
        """Normaliza las referencias de identidad para el plano consultado.

        Args:
            identidad_llamante (IdentidadLlamante): identidad del llamante.
            plano (Plano): plano del objeto consultado, que fija la política
                de normalización aplicable.

        Returns:
            dict[str, str]: referencia normalizada -> referencia original,
                para poder reportar con qué coincidencia se atribuyó un
                otorgamiento.
        """
        normalizadas = {}
        for referencia in identidad_llamante.ReferenciasDeIdentidad():
            clave = _NormalizarReferencia(referencia, plano)
            normalizadas.setdefault(clave, referencia)
        return normalizadas

    @staticmethod
    def _DeterminarOrigen(otorgamiento, objeto):
        """Decide si un otorgamiento es directo, heredado o no determinado.

        Prioridad (design.md D2): si el canal informa el origen explícitamente
        se respeta su palabra, incluido el securable padre que reporte
        (`heredado_de`, que la Permissions API entrega en
        `inherited_from_object`); si no, se deriva comparando el objeto del
        otorgamiento con el consultado, que es exactamente como Unity Catalog
        reporta la herencia (`SHOW GRANT ON SCHEMA` devuelve filas cuyo tipo y
        nombre de objeto son los del catálogo padre).

        Args:
            otorgamiento (ItemGrant): otorgamiento reportado por el canal.
            objeto (ObjetoSecurable): objeto consultado.

        Returns:
            tuple[OrigenPrivilegio, str | None]: origen y, si es heredado, la
                identificación del securable de origen; None en cualquier otro
                caso.
        """
        origen_informado = getattr(otorgamiento, "origen", _CANAL_NO_INFORMA_ORIGEN)

        if origen_informado is not _CANAL_NO_INFORMA_ORIGEN:
            # El canal informa el origen (o declara expresamente no saberlo).
            if origen_informado is None:
                return OrigenPrivilegio.NO_DETERMINADO, None
            try:
                origen = OrigenPrivilegio(origen_informado)
            except ValueError:
                # El canal informó un origen que no pertenece a la
                # enumeración: no se supone nada, queda no determinado.
                return OrigenPrivilegio.NO_DETERMINADO, None

            # Quien informa el origen puede informar también de dónde viene:
            # la Permissions API lo hace con `inherited_from_object`. Se
            # conserva ese dato (campo `heredado_de` de `OtorgamientoEfectivo`)
            # para que el reporte pueda explicar el securable padre; en los
            # demás orígenes no hay padre que reportar.
            if origen is OrigenPrivilegio.HEREDADO:
                return origen, getattr(otorgamiento, "heredado_de", None)
            return origen, None

        otorgado_sobre = getattr(otorgamiento, "objeto", None)
        if otorgado_sobre is None:
            return OrigenPrivilegio.NO_DETERMINADO, None

        if otorgado_sobre == objeto:
            return OrigenPrivilegio.DIRECTO, None

        # Otorgamiento sobre otro securable: el propio sistema lo está
        # reportando como vigente para el objeto consultado, luego es heredado.
        return OrigenPrivilegio.HEREDADO, getattr(
            otorgado_sobre, "identificador", None
        )

    def _RegistrarFallo(self, excepcion, usuario, contexto):
        """Registra un fallo en la bitácora de errores sin propagarlo.

        Args:
            excepcion (BaseException): excepción capturada.
            usuario (str | None): identidad del llamante, si se conoce.
            contexto (str): operación que falló, para el STRUCT.
        """
        if self._registrador_errores is None:
            print(
                f"[RESOLUCIÓN] No se pudieron resolver privilegios efectivos: "
                f"{excepcion}",
                file=sys.stderr,
            )
            return

        try:
            self._registrador_errores.Registrar(
                excepcion,
                modulo=MODULO_BITACORA_ERRORES,
                usuario=usuario,
                contexto=contexto,
            )
        except Exception as excepcion_registro:  # noqa: BLE001
            # La bitácora nunca es un punto de fallo en cascada (design.md D7).
            print(
                f"[RESOLUCIÓN] El fallo no pudo escribirse en la bitácora de "
                f"errores: {excepcion_registro}. Fallo original: {excepcion}",
                file=sys.stderr,
            )


def _NormalizarReferencia(valor, plano):
    """Aplica la política declarada de normalización del plano a la referencia.

    Args:
        valor (str): referencia o identificación reportada.
        plano (Plano): plano cuyo criterio de escritura se aplica
            (`NORMALIZAR_A_MINUSCULAS_POR_PLANO`).

    Returns:
        str: referencia lista para comparar.
    """
    texto = str(valor).strip()
    if NORMALIZAR_A_MINUSCULAS_POR_PLANO.get(plano, False):
        return texto.lower()
    return texto


def _NombreObjeto(objeto):
    """Devuelve una identificación legible del objeto para mensajes.

    Args:
        objeto (ObjetoSecurable | None): objeto a describir.

    Returns:
        str: `tipo 'identificador'`, o la descripción del objeto ausente.
    """
    if objeto is None:
        return "(objeto no informado)"
    tipo = getattr(objeto, "tipo", None)
    nombre_tipo = getattr(tipo, "value", str(tipo) if tipo else "objeto")
    return f"{nombre_tipo} '{getattr(objeto, 'identificador', objeto)}'"
