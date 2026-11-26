"""Canal SDK/REST real del plano de control para cinco tipos de objetos
(capability `compute-grants` extendida por `grants-apps-tokens`).

Implementación de producción del contrato `CanalControl` para otorgar, revocar
y listar permisos sobre los tres tipos de cómputo del plano de control (cluster
clásico all-purpose, serverless compute objects interactivos y automated, y SQL
warehouse) y los dos tipos restantes (Databricks Apps y uso de personal access
tokens) mediante la Permissions API, y para consultar la ACL vigente de un
objeto (verificación posterior al otorgamiento, design D5).

El canal depende de un transporte de permisos inyectado (design D3): en
producción el adaptador SDK (`ClientePermisosSdk`), en las pruebas unitarias y
funcionales un transporte simulado, y en las integrales el mismo adaptador SDK
construido con el perfil CLI del workspace. Ningún valor de conexión, id de
objeto ni nivel de permiso vive en el código (regla "código NO hardcodeado"):
el transporte es la única ruta hacia el workspace.

El mapeo de recurso de la Permissions API por tipo de objeto es un dato
declarativo (design D2), con los cinco tipos del plano de control. Un tipo
ajeno —del plano de datos (catálogo, esquema, tabla, etc.) o cualquier otro no
declarado— se rechaza con `ErrorCanal` explícito antes de construir llamada
alguna (spec - "Tipo de objeto no soportado por el canal").

La escritura de la ACL es aditiva por otorgatario (design D4): nunca se
reemplaza la ACL completa sin antes leerla; la composición de entradas modifica
únicamente la entrada del otorgatario del ítem y conserva las demás. Ante un
conflicto de concurrencia del workspace se reintenta la lectura-modificación-
escritura un número acotado de veces.

La construcción de recursos y rutas se expone como métodos estáticos para que
las pruebas unitarias la verifiquen sin transporte alguno; la ejecución y la
traducción de errores operan sobre el puerto inyectado (`LeerAcl`/`EscribirAcl`).

Para `USO_TOKEN` el recurso es `authorization/tokens`, que opera como singleton
del workspace (sin identificador de objeto en la ruta de la Permissions API).
"""

import re

from control_accesos.canales.contratos import CanalControl
from control_accesos.canales.errores import (
    ErrorCanal,
    ErrorPrivilegiosInsuficientes,
)
from control_accesos.canales.reales.entrada_acl import EntradaAcl
from control_accesos.dominio.enumeraciones import TipoObjeto
from control_accesos.dominio.modelos import ItemGrant

# Identificador del módulo que se declara en la bitácora de errores cuando una
# operación falla (mismo criterio que `canal_sql` y los módulos de autenticación
# y resolución ya existentes).
MODULO_BITACORA_ERRORES = "canal_control"

# Recurso de la Permissions API por tipo de objeto del plano de control
# (design D2). Los valores son los literales que el SDK usa como
# `request_object_type` en `permissions.get`/`permissions.update`, y los
# confirmados contra el workspace en la capa integral de C3
# (`tests/integrales/adaptador_canales_reales.py`). Tras la extensión de C8
# (change `grants-apps-tokens`), el canal cubre los cinco tipos del plano de
# control: los tres de cómputo más Databricks Apps y uso de personal access
# tokens. Para USO_TOKEN el recurso es `authorization/tokens`, que opera como
# singleton del workspace (sin identificador de objeto en la ruta).
RECURSO_PERMISOS_POR_TIPO_OBJETO = {
    TipoObjeto.COMPUTO_CLASICO: "clusters",
    TipoObjeto.COMPUTO_SERVERLESS: "serverless-compute",
    TipoObjeto.SQL_WAREHOUSE: "sql/warehouses",
    TipoObjeto.DATABRICK_APP: "apps",
    TipoObjeto.USO_TOKEN: "authorization/tokens",
}

# Prefijo de la Permissions API usado en las rutas que reportan los mensajes y
# que verifican las pruebas unitarias (`RutaDePermisos`), sin participar en las
# llamadas del SDK (que trabaja con `request_object_type` + `request_object_id`).
PREFIJO_API_PERMISOS = "/api/2.0/permissions"

# Número de intentos de la escritura aditiva ante conflicto de concurrencia del
# workspace (design D4). El primer intento fallido por conflicto se repite una
# vez tras releer la ACL; un segundo conflicto se reporta como fallo.
NUM_REINTENTOS_CONFLICTO = 2

# Patrones de clasificación de errores del transporte, declarados como datos
# (design D6): se aplican sobre el texto del error para distinguir el permiso
# denegado, el objeto inexistente y el principal inexistente del resto de
# fallos. Se declaran compilados para no recompilarlos en cada ejecución y se
# ajustan sin tocar lógica (p. ej. al contrastarlos contra el workspace real en
# las integrales). La regla fail-safe se mantiene: solo el denegado explícito
# produce `ErrorPrivilegiosInsuficientes`; un patrón no reconocido cae en
# `fallido` genérico.
PATRONES_PERMISO_DENEGADO = (
    re.compile(r"PERMISSION_DENIED", re.IGNORECASE),
)

# Los errores de principal inexistente del workspace real llegan como
# `RESOURCE_DOES_NOT_EXIST` con el prefijo `Principal: GroupName(...)` /
# `Principal: UserName(...)`. Ese prefijo es lo que los distingue del objeto
# inexistente, que usa la misma clase de error sin el prefijo `Principal:`.
# Por eso el patrón `Principal:\s*...does not exist` se evalúa ANTES que el de
# objeto (design D6, contrastado contra el workspace).
PATRONES_PRINCIPAL_INEXISTENTE = (
    re.compile(
        r"Principal:\s*(?:GroupName|UserName|ServicePrincipalName)?[^\n]*does not exist",
        re.IGNORECASE,
    ),
    re.compile(r"PRINCIPAL_DOES_NOT_EXIST", re.IGNORECASE),
    re.compile(r"USER_NOT_FOUND", re.IGNORECASE),
    re.compile(r"GROUP_NOT_FOUND", re.IGNORECASE),
)

PATRONES_OBJETO_INEXISTENTE = (
    re.compile(r"RESOURCE_DOES_NOT_EXIST", re.IGNORECASE),
    re.compile(r"CLUSTER_DOES_NOT_EXIST", re.IGNORECASE),
    re.compile(r"WAREHOUSE_DOES_NOT_EXIST", re.IGNORECASE),
    re.compile(r"OBJECT_NOT_FOUND", re.IGNORECASE),
    # En Free Edition un SQL warehouse inexistente se reporta como id de
    # endpoint inválido (no como recurso inexistente).
    re.compile(r"not a valid endpoint id", re.IGNORECASE),
)

# Patrones que indican conflicto de concurrencia al escribir la ACL (design D4):
# un reintento acotado tras relectura es la mitigación aceptada, nunca el
# reemplazo total de la ACL sin control de concurrencia.
PATRONES_CONFLICTO_ESCRITURA = (
    re.compile(r"RESOURCE_CONFLICT", re.IGNORECASE),
    re.compile(r"CONCURRENT_MODIFICATION", re.IGNORECASE),
)

# Patrón para detectar que la Token Permissions API no está habilitada en el
# workspace (change grants-apps-tokens, C8). El workspace responde con un error
# que indica que la feature no está disponible; el canal lo clasifica como
# ErrorCanal con mensaje específico que identifica la feature no habilitada.
PATRONES_FEATURE_NO_HABILITADA = (
    re.compile(r"not\s+enabled", re.IGNORECASE),
    re.compile(r"feature\s+not\s+enabled", re.IGNORECASE),
    re.compile(r"FEATURE_NOT_ENABLED", re.IGNORECASE),
    re.compile(r"TOKEN_PERMISSIONS_API_NOT_ENABLED", re.IGNORECASE),
)


class CanalControlComputo(CanalControl):
    """Canal real del plano de control para permisos de cómputo.

    Otorga, revoca y lista permisos (niveles `CAN_*`) sobre clusters clásicos,
    serverless compute objects y SQL warehouses mediante la Permissions API, y
    consulta la ACL vigente para la verificación posterior al otorgamiento.
    No contiene configuración de conexión alguna: todo acceso al workspace
    ocurre por el transporte inyectado.

    Attributes:
        transporte: objeto con los puertos `LeerAcl(recurso, identificador)` y
            `EscribirAcl(recurso, identificador, entradas)` que ejecuta la
            lectura y escritura de la ACL (una sesión simulada o el adaptador
            SDK sobre `WorkspaceClient`).
        registrador_errores: escritor opcional de la bitácora de errores; si se
            aporta, cada fallo de ejecución se registra con su detalle.
    """

    def __init__(self, transporte, registrador_errores=None):
        """Inicializa el canal con el transporte de permisos inyectado.

        Args:
            transporte: objeto con los métodos `LeerAcl(recurso, identificador)`
                y `EscribirAcl(recurso, identificador, entradas)`. Es la única
                vía de acceso al workspace (design D3).
            registrador_errores (BitacoraErrores | None): escritor opcional de
                la bitácora de errores; sin él, los fallos solo se reportan
                como resultados por ítem, sin registrar auditoría.

        Raises:
            ValueError: si no se recibe un transporte con ambos puertos.
        """
        if transporte is None or not _TienePuertosDePermisos(transporte):
            raise ValueError(
                "Se requiere un transporte de permisos con los métodos "
                "'LeerAcl(recurso, identificador)' y "
                "'EscribirAcl(recurso, identificador, entradas)' para operar "
                "sobre la Permissions API."
            )
        self.transporte = transporte
        self._registrador_errores = registrador_errores

    @staticmethod
    def RecursoDeTipo(tipo):
        """Devuelve el recurso de la Permissions API del tipo, o rechaza el ajeno.

        Args:
            tipo (TipoObjeto): tipo del objeto securable.

        Returns:
            str: recurso de la Permissions API en su forma textual
                (`clusters`, `serverless-compute`, `sql/warehouses`,
                `apps` o `authorization/tokens`).

        Raises:
            ErrorCanal: si el tipo no pertenece al plano de control; el mensaje
                identifica el tipo recibido.
        """
        recurso = RECURSO_PERMISOS_POR_TIPO_OBJETO.get(tipo)
        if recurso is None:
            raise ErrorCanal(
                f"El tipo de objeto '{tipo.value}' no pertenece al plano de "
                "control: no tiene recurso en la Permissions API."
            )
        return recurso

    @staticmethod
    def RutaDePermisos(objeto):
        """Construye la ruta de la Permissions API del objeto (solo referencia).

        Sirve para los mensajes y para que las pruebas verifiquen el mapeo de
        recurso e id sin ejecutar llamadas. El id del objeto se conserva con su
        escritura original (los identificadores del plano de control no se
        normalizan a minúsculas, a diferencia del plano de datos). Para
        `USO_TOKEN` (singleton del workspace) la ruta omite el segmento de id.

        Args:
            objeto (ObjetoSecurable): objeto del plano de control.

        Returns:
            str: ruta `/api/2.0/permissions/<recurso>/<identificador>`, o
                `/api/2.0/permissions/authorization/tokens` para USO_TOKEN.

        Raises:
            ErrorCanal: si el tipo del objeto no está soportado por el canal.
        """
        recurso = CanalControlComputo.RecursoDeTipo(objeto.tipo)
        if objeto.tipo is TipoObjeto.USO_TOKEN:
            # authorization/tokens es singleton del workspace: sin segmento de id
            return f"{PREFIJO_API_PERMISOS}/{recurso}"
        return f"{PREFIJO_API_PERMISOS}/{recurso}/{objeto.identificador}"

    def EjecutarOtorgamiento(self, item):
        """Otorga el nivel de permiso del ítem con escritura aditiva.

        Lee la ACL del objeto, actualiza únicamente la entrada del principal del
        ítem al nivel solicitado (conservando las demás) y escribe la ACL
        resultante por el transporte (design D4).

        Args:
            item (ItemGrant): ítem validado a otorgar.
        """
        self._EjecutarEscritura(item, revocar=False)

    def EjecutarRevocacion(self, item):
        """Revoca el nivel de permiso del ítem con escritura aditiva.

        Lee la ACL del objeto, elimina la entrada del principal del ítem
        (conservando las demás) y escribe la ACL resultante (design D4). Una
        revocación sobre un permiso que no estaba vigente no altera otras
        entradas.

        Args:
            item (ItemGrant): ítem validado a revocar.
        """
        self._EjecutarEscritura(item, revocar=True)

    def ListarGrantsVigentes(self, objeto):
        """Lista los permisos vigentes del objeto leyendo su ACL.

        Cada entrada directa de la ACL se traduce a un `ItemGrant` con su
        principal, su nivel de permiso y el objeto consultado (design D5).

        Args:
            objeto (ObjetoSecurable): objeto del plano de control a consultar.

        Returns:
            list[ItemGrant]: permisos vigentes; lista vacía cuando la ACL no
                tiene entradas (vacío distinguible de un fallo de lectura).

        Raises:
            ErrorCanal: si el tipo del objeto no está soportado por el canal.
        """
        recurso = self.RecursoDeTipo(objeto.tipo)
        # authorization/tokens es singleton del workspace: sin identificador
        # de objeto (design D2).
        identificador = (
            "" if objeto.tipo is TipoObjeto.USO_TOKEN
            else objeto.identificador
        )
        try:
            entradas = self.transporte.LeerAcl(recurso, identificador)
        except Exception as error:  # noqa: BLE001 - se traduce a canal
            self._RegistrarError(error, objeto=objeto)
            self._TraducirError(error, objeto=objeto)

        return [
            ItemGrant(
                principal=entrada.principal,
                privilegio=entrada.nivel,
                objeto=objeto,
            )
            for entrada in entradas
        ]

    def _EjecutarEscritura(self, item, revocar):
        """Ejecuta la lectura-modificación-escritura de la ACL del ítem.

        Args:
            item (ItemGrant): ítem a otorgar o revocar.
            revocar (bool): True para revocar, False para otorgar.

        Raises:
            ErrorPrivilegiosInsuficientes: si el workspace responde permiso
                denegado al ejecutor.
            ErrorCanal: si el objeto o el principal no existen, o ante cualquier
                otro fallo o conflicto no resuelto dentro de los reintentos.
        """
        recurso = self.RecursoDeTipo(item.objeto.tipo)
        # authorization/tokens es singleton del workspace: sin identificador
        # de objeto (design D2).
        identificador = (
            "" if item.objeto.tipo is TipoObjeto.USO_TOKEN
            else item.objeto.identificador
        )

        for intento in range(NUM_REINTENTOS_CONFLICTO):
            try:
                entradas = self.transporte.LeerAcl(recurso, identificador)
            except Exception as error:  # noqa: BLE001 - se traduce a canal
                self._RegistrarError(error, item)
                self._TraducirError(error, item=item)

            entradas_nuevas = _ComponerEntradas(entradas, item, revocar)

            try:
                self.transporte.EscribirAcl(
                    recurso, identificador, entradas_nuevas
                )
                return
            except Exception as error:  # noqa: BLE001 - se traduce a canal
                if (
                    intento < NUM_REINTENTOS_CONFLICTO - 1
                    and _CoincideAlgunPatron(texto=str(error), patrones=PATRONES_CONFLICTO_ESCRITURA)
                ):
                    # Conflicto de concurrencia: se relee y se reintenta acotadamente.
                    continue
                self._RegistrarError(error, item)
                self._TraducirError(error, item=item)

    def _RegistrarError(self, excepcion, item=None, objeto=None):
        """Registra el fallo en la bitácora de errores, sin propagarlo.

        Esa auditoría es un efecto lateral que nunca debe convertirse en un
        punto de fallo en cascada (design D7): si no hay registrador o el propio
        registro falla, el error queda igual traducido a resultado por ítem.

        Args:
            excepcion (BaseException): excepción capturada del transporte.
            item (ItemGrant | None): ítem cuya ejecución falló, si aplica.
            objeto (ObjetoSecurable | None): objeto consultado, si no hay ítem.
        """
        if self._registrador_errores is None:
            return
        try:
            self._registrador_errores.Registrar(
                excepcion,
                modulo=MODULO_BITACORA_ERRORES,
                usuario=None,
                contexto=self._ContextoDe(item=item, objeto=objeto),
            )
        except Exception:  # noqa: BLE001 - la bitácora nunca propaga
            return

    def _TraducirError(self, error, item=None, objeto=None):
        """Traduce el error del transporte a la excepción de canal del caso.

        Args:
            error (BaseException): excepción capturada del transporte.
            item (ItemGrant | None): ítem en ejecución, para los mensajes.
            objeto (ObjetoSecurable | None): objeto consultado, si no hay ítem.

        Raises:
            ErrorPrivilegiosInsuficientes: si el error es permiso denegado.
            ErrorCanal: en cualquier otro caso, con mensaje específico (objeto o
                principal inexistente, feature no habilitada) o genérico.
        """
        texto = str(error)
        if _CoincideAlgunPatron(texto, PATRONES_PERMISO_DENEGADO):
            raise ErrorPrivilegiosInsuficientes(
                self._MensajePermisoDenegado(item=item, objeto=objeto)
            )
        # El principal inexistente se evalúa antes que el objeto: el workspace
        # usa la misma clase `RESOURCE_DOES_NOT_EXIST` para ambos, distinguidos
        # por el prefijo `Principal:` (design D6, contrastado en integrales).
        if item is not None and _CoincideAlgunPatron(texto, PATRONES_PRINCIPAL_INEXISTENTE):
            raise ErrorCanal(self._MensajePrincipalInexistente(item))
        if _CoincideAlgunPatron(texto, PATRONES_OBJETO_INEXISTENTE):
            raise ErrorCanal(self._MensajeObjetoInexistente(item=item, objeto=objeto))
        # Token Permissions API no habilitada en el workspace (C8, design D6).
        if _CoincideAlgunPatron(texto, PATRONES_FEATURE_NO_HABILITADA):
            raise ErrorCanal(self._MensajeFeatureNoHabilitada(item=item, objeto=objeto))
        raise ErrorCanal(texto)

    @staticmethod
    def _ContextoDe(item=None, objeto=None):
        """Construye el contexto textual para la bitácora de errores.

        Args:
            item (ItemGrant | None): ítem en proceso, si aplica.
            objeto (ObjetoSecurable | None): objeto consultado, si no hay ítem.

        Returns:
            str: contexto en español de la operación que falló.
        """
        if item is not None:
            return (
                f"operación sobre {item.objeto.tipo.value} "
                f"'{item.objeto.identificador}'"
            )
        return (
            f"lectura de ACL sobre {objeto.tipo.value} "
            f"'{objeto.identificador}'"
        )

    @staticmethod
    def _MensajePermisoDenegado(item=None, objeto=None):
        """Mensaje del caso permiso denegado, según haya ítem o solo objeto.

        Args:
            item (ItemGrant | None): ítem que el ejecutor no pudo operar.
            objeto (ObjetoSecurable | None): objeto consultado, si no hay ítem.

        Returns:
            str: texto explícito en español del permiso denegado.
        """
        if item is not None:
            return (
                f"El ejecutor no tiene privilegios para otorgar o revocar "
                f"{item.privilegio} sobre {item.objeto.tipo.value} "
                f"'{item.objeto.identificador}' (permiso denegado)."
            )
        return (
            f"El ejecutor no tiene privilegios para consultar la ACL de "
            f"{objeto.tipo.value} '{objeto.identificador}' (permiso denegado)."
        )

    @staticmethod
    def _MensajeObjetoInexistente(item=None, objeto=None):
        """Mensaje del caso objeto inexistente.

        Args:
            item (ItemGrant | None): ítem cuyo objeto no existe.
            objeto (ObjetoSecurable | None): objeto consultado, si no hay ítem.

        Returns:
            str: texto explícito en español del objeto inexistente.
        """
        destino = item.objeto if item is not None else objeto
        return (
            f"El objeto {destino.tipo.value} "
            f"'{destino.identificador}' no existe en el workspace."
        )

    @staticmethod
    def _MensajePrincipalInexistente(item):
        """Mensaje del caso principal inexistente, con el principal del ítem.

        Args:
            item (ItemGrant): ítem cuyo principal destinatario no existe.

        Returns:
            str: texto explícito en español del principal inexistente.
        """
        return (
            f"El principal '{item.principal.identificador}' no existe en el "
            "workspace."
        )

    @staticmethod
    def _MensajeFeatureNoHabilitada(item=None, objeto=None):
        """Mensaje del caso Token Permissions API no habilitada en el workspace.

        Args:
            item (ItemGrant | None): ítem cuya operación no pudo completarse.
            objeto (ObjetoSecurable | None): objeto consultado, si no hay ítem.

        Returns:
            str: texto explícito en español de la feature no habilitada.
        """
        if item is not None:
            return (
                f"El workspace no tiene habilitada la Token Permissions API; "
                f"no se puede gestionar {item.privilegio} sobre "
                f"{item.objeto.tipo.value} (feature no habilitada)."
            )
        return (
            f"El workspace no tiene habilitada la Token Permissions API; "
            f"no se puede consultar la ACL de {objeto.tipo.value} "
            f"(feature no habilitada)."
        )


def _ComponerEntradas(entradas, item, revocar):
    """Compone la ACL resultante modificando solo la entrada del ítem.

    Regla aditiva por otorgatario (design D4): al otorgar, la entrada del
    principal del ítem se fija al nivel solicitado (se agrega si no existía) y
    las demás entradas se conservan; al revocar, la entrada de ese principal se
    elimina y las demás se conservan. Nunca se reemplaza la ACL completa sin
    conservar las entradas ajenas al ítem.

    Args:
        entradas (list[EntradaAcl]): ACL vigente leída del transporte.
        item (ItemGrant): ítem a otorgar o revocar.
        revocar (bool): True para revocar, False para otorgar.

    Returns:
        list[EntradaAcl]: ACL resultante, conservando el orden de las entradas
            ajenas y agregando la del ítem al final cuando se otorga por primera
            vez.
    """
    resultado = []
    encontrado = False
    for entrada in entradas:
        if _EsMismoPrincipal(entrada.principal, item.principal):
            encontrado = True
            if not revocar:
                resultado.append(
                    EntradaAcl(principal=item.principal, nivel=item.privilegio)
                )
            # Al revocar, la entrada se omite: se quita el permiso del principal.
        else:
            resultado.append(entrada)

    if not revocar and not encontrado:
        resultado.append(
            EntradaAcl(principal=item.principal, nivel=item.privilegio)
        )
    return resultado


def _EsMismoPrincipal(principal_a, principal_b):
    """Devuelve True si ambos principals son el mismo (tipo e identificador).

    Args:
        principal_a (Principal): principal de una entrada de la ACL.
        principal_b (Principal): principal del ítem.

    Returns:
        bool: True si coinciden en tipo e identificador exacto.
    """
    return (
        principal_a.tipo is principal_b.tipo
        and principal_a.identificador == principal_b.identificador
    )


def _TienePuertosDePermisos(transporte):
    """Devuelve True si el transporte expone LeerAcl y EscribirAcl.

    Args:
        transporte: objeto a validar como transporte de permisos.

    Returns:
        bool: True si posee ambos puertos callables.
    """
    return (
        callable(getattr(transporte, "LeerAcl", None))
        and callable(getattr(transporte, "EscribirAcl", None))
    )


def _CoincideAlgunPatron(texto, patrones):
    """Devuelve True si el texto coincide con alguno de los patrones.

    Args:
        texto (str): texto donde buscar (el mensaje del error del transporte).
        patrones (tuple[re.Pattern, ...]): patrones compilados a probar.

    Returns:
        bool: True si al menos un patrón coincide con el texto.
    """
    return any(patron.search(texto) for patron in patrones)
