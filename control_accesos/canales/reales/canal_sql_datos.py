"""Canal SQL real del plano de datos (capability `uc-data-object-grants`).

Implementación de producción del contrato `CanalDatos` para otorgar y revocar
privilegios sobre los objetos del plano de datos de Unity Catalog (catálogo,
esquema, tabla delta, streaming table, vista materializada, vista SQL, volumen
y modelo ML) mediante instrucciones SQL `GRANT`/`REVOKE`, y para consultar los
grants vigentes con `SHOW GRANT` (verificación posterior al otorgamiento).

El canal consume una sesión SQL inyectada (design D2): en producción la del
entorno de la Databricks App (adaptada por `SesionSparkSql`); en las pruebas
integrales el transporte por CLI ya existente; en las pruebas unitarias y
funcionales una sesión simulada. Ningún valor de conexión vive en el código
(regla "código NO hardcodeado"): la sesión es la única ruta hacia el workspace.

El mapeo de palabra clave SQL por tipo de objeto es un dato declarativo,
acotado a los ocho tipos de este change (design D1): un tipo fuera de alcance
se rechaza con `ErrorCanal` explícito (spec - "Objetos fuera del alcance de
este change").

La construcción de sentencias se expone como métodos estáticos para que las
pruebas unitarias la verifiquen sin sesión alguna; la ejecución y la traducción
de errores operan sobre el puerto `sql(sentencia)` de la sesión inyectada.
"""

import re

from control_accesos.canales.contratos import CanalDatos
from control_accesos.canales.errores import (
    ErrorCanal,
    ErrorPrivilegiosInsuficientes,
)
from control_accesos.dominio.enumeraciones import TipoObjeto, TipoPrincipal
from control_accesos.dominio.errores import ErrorDominio
from control_accesos.dominio.modelos import ItemGrant, ObjetoSecurable, Principal

# Identificador del módulo que se declara en la bitácora de errores cuando la
# ejecución de una instrucción falla (mismo criterio que los módulos de
# autenticación [caller-identity] y resolución [caller-privilege-resolution]).
MODULO_BITACORA_ERRORES = "canal_sql"

# Mapa declarativo de palabra clave SQL por tipo de objeto del plano de datos,
# acotado a los ocho tipos de este change. No se incluyen external location ni
# connection (change `grants-uc-externos`, C6): un tipo ajeno al mapa se rechaza
# con error controlado (design D1). La palabra clave es el literal que envía la
# instrucción SQL (en mayúsculas, estándar del proyecto).
PALABRA_CLAVE_SQL_POR_TIPO_OBJETO = {
    TipoObjeto.CATALOGO: "CATALOG",
    TipoObjeto.ESQUEMA: "SCHEMA",
    TipoObjeto.TABLA_DELTA: "TABLE",
    TipoObjeto.STREAMING_TABLE: "TABLE",
    TipoObjeto.VISTA_MATERIALIZADA: "TABLE",
    TipoObjeto.VISTA_SQL: "TABLE",
    TipoObjeto.VOLUMEN: "VOLUME",
    TipoObjeto.MODELO_ML: "MODEL",
}

# Plantillas de las instrucciones SQL, completamente en mayúsculas (estándar).
PLANTILLA_GRANT = (
    "GRANT {privilegio} ON {palabra_clave} {identificador} TO {principal}"
)
PLANTILLA_REVOKE = (
    "REVOKE {privilegio} ON {palabra_clave} {identificador} FROM {principal}"
)
PLANTILLA_SHOW_GRANT = "SHOW GRANT ON {palabra_clave} {identificador}"

# Patrones de clasificación de errores del motor SQL, declarados como datos
# (design D3): se aplican sobre el texto del error reportado por la sesión para
# distinguir el permiso denegado, el objeto inexistente y el principal
# inexistente del resto de fallos. Se declaran compilados para no recompilarlos
# en cada ejecución y se ajustan sin tocar lógica (p. ej. al contrastarlos contra
# el workspace real en las integrales).
PATRONES_PERMISO_DENEGADO = (
    re.compile(r"PERMISSION_DENIED", re.IGNORECASE),
)

PATRONES_OBJETO_INEXISTENTE = (
    re.compile(r"SCHEMA_OR_OBJECT_NOT_FOUND", re.IGNORECASE),
    re.compile(r"TABLE_OR_VIEW_NOT_FOUND", re.IGNORECASE),
    re.compile(r"CATALOG_NOT_FOUND", re.IGNORECASE),
    re.compile(r"SCHEMA_NOT_FOUND", re.IGNORECASE),
    re.compile(r"VOLUME_NOT_FOUND", re.IGNORECASE),
    re.compile(r"MODEL_NOT_FOUND", re.IGNORECASE),
    re.compile(r"OBJECT_NOT_FOUND", re.IGNORECASE),
)

PATRONES_PRINCIPAL_INEXISTENTE = (
    re.compile(r"PRINCIPAL_NOT_FOUND", re.IGNORECASE),
    re.compile(r"USER_OR_GROUP_NOT_FOUND", re.IGNORECASE),
    # Código real contrastado contra el workspace `andresFree`: Databricks
    # responde al otorgar a un principal inexistente con
    # `PRINCIPAL_DOES_NOT_EXIST` (no `PRINCIPAL_NOT_FOUND`).
    re.compile(r"PRINCIPAL_DOES_NOT_EXIST", re.IGNORECASE),
)

# Columnas que devuelve `SHOW GRANT` en Unity Catalog: otorgatario, acción
# (privilegio), tipo de securable y clave del securable sobre el que nació el
# otorgamiento. Se declaran como datos para no indexar con literales dispersos.
COLUMNA_PRINCIPAL = 0
COLUMNA_ACCION = 1
COLUMNA_TIPO_OBJETO = 2
COLUMNA_CLAVE_OBJETO = 3

# Mapeo de la palabra clave de un contenedor padre a su tipo de objeto del
# dominio (design D4). Las filas de `SHOW GRANT` que describen un securable
# padre del objeto consultado se mapean aquí: CATALOG -> CATALOGO, SCHEMA ->
# ESQUEMA. Cualquier otra palabra (p. ej. METASTORE) queda fuera del mapa y la
# fila se omite sin inventar un objeto.
PALABRA_CLAVE_CONTENEDORA_A_TIPO = {
    "CATALOG": TipoObjeto.CATALOGO,
    "SCHEMA": TipoObjeto.ESQUEMA,
}

# Formas con las que Unity Catalog reporta al otorgatario: un App Id (UUID) de
# service principal y un correo de usuario. Ambas se usan para inferir el tipo
# de principal de la referencia textual de cada fila (el plano de datos solo
# entrega texto, sin campo de tipo).
EXPRESION_APP_ID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
EXPRESION_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class CanalSqlDatos(CanalDatos):
    """Canal SQL real para otorgar y revocar privilegios de Unity Catalog.

    Construye y ejecuta instrucciones GRANT/REVOKE (y consulta SHOW GRANT) para
    los ocho tipos del plano de datos soportados en este change, a través de
    una sesión SQL inyectada. No contiene configuración de conexión alguna.

    Attributes:
        sesion_sql: objeto con el puerto `sql(sentencia) -> filas` que ejecuta
            las instrucciones contra el workspace (o una sesión simulada).
        registrador_errores: escritor opcional de la bitácora de errores; si se
            aporta, cada fallo de ejecución se registra con su detalle.
    """

    def __init__(self, sesion_sql, registrador_errores=None):
        """Inicializa el canal con la sesión SQL inyectada.

        Args:
            sesion_sql: objeto con el método `sql(sentencia)` que devuelve las
                filas del resultado (listas de textos). Es la única vía de
                acceso al workspace (design D2).
            registrador_errores (BitacoraErrores | None): escritor opcional de
                la bitácora de errores; sin él, los fallos de ejecución solo se
                reportan como resultados por ítem, sin registrar auditoría.

        Raises:
            ValueError: si no se recibe una sesión con el puerto `sql`.
        """
        if sesion_sql is None or not hasattr(sesion_sql, "sql"):
            raise ValueError(
                "Se requiere una sesión SQL con el método 'sql(sentencia)' "
                "para ejecutar instrucciones contra el workspace."
            )
        self.sesion_sql = sesion_sql
        self._registrador_errores = registrador_errores

    @staticmethod
    def ConstruirSentenciaOtorgamiento(item):
        """Construye la instrucción `GRANT` en mayúsculas del ítem.

        Args:
            item (ItemGrant): ítem validado (principal, privilegio, objeto).

        Returns:
            str: instrucción `GRANT <privilegio> ON <palabra clave>
                <identificador> TO <principal>`, con el nombre calificado entre
                comillas invertidas parte por parte.

        Raises:
            ErrorCanal: si el tipo de objeto no está soportado por este canal.
        """
        return PLANTILLA_GRANT.format(
            privilegio=item.privilegio,
            palabra_clave=_PalabraClaveSql(item.objeto.tipo),
            identificador=_IdentificadorSql(item.objeto.identificador),
            principal=_IdentificadorPrincipal(item.principal.identificador),
        )

    @staticmethod
    def ConstruirSentenciaRevocacion(item):
        """Construye la instrucción `REVOKE` en mayúsculas del ítem.

        Args:
            item (ItemGrant): ítem validado a revocar.

        Returns:
            str: instrucción `REVOKE <privilegio> ON <palabra clave>
                <identificador> FROM <principal>`, con la misma palabra clave
                por tipo de objeto que el otorgamiento.

        Raises:
            ErrorCanal: si el tipo de objeto no está soportado por este canal.
        """
        return PLANTILLA_REVOKE.format(
            privilegio=item.privilegio,
            palabra_clave=_PalabraClaveSql(item.objeto.tipo),
            identificador=_IdentificadorSql(item.objeto.identificador),
            principal=_IdentificadorPrincipal(item.principal.identificador),
        )

    @staticmethod
    def ConstruirShowGrant(objeto):
        """Construye la sentencia `SHOW GRANT` del objeto.

        Args:
            objeto (ObjetoSecurable): objeto del plano de datos a consultar.

        Returns:
            str: sentencia `SHOW GRANT ON <palabra clave> <identificador>`.

        Raises:
            ErrorCanal: si el tipo de objeto no está soportado por este canal.
        """
        return PLANTILLA_SHOW_GRANT.format(
            palabra_clave=_PalabraClaveSql(objeto.tipo),
            identificador=_IdentificadorSql(objeto.identificador),
        )

    def EjecutarOtorgamiento(self, item):
        """Ejecuta la instrucción GRANT del ítem en la sesión SQL.

        Args:
            item (ItemGrant): ítem validado a otorgar.
        """
        self._Ejecutar(item, self.ConstruirSentenciaOtorgamiento(item))

    def EjecutarRevocacion(self, item):
        """Ejecuta la instrucción REVOKE del ítem en la sesión SQL.

        Args:
            item (ItemGrant): ítem validado a revocar.
        """
        self._Ejecutar(item, self.ConstruirSentenciaRevocacion(item))

    def ListarGrantsVigentes(self, objeto):
        """Lista los otorgamientos vigentes del objeto vía SHOW GRANT.

        Construye la sentencia `SHOW GRANT`, la ejecuta por la sesión y traduce
        cada fila a un `ItemGrant` con la regla fila propia / fila padre
        (design D4): la fila del objeto consultado conserva el tipo consultado,
        la de un contenedor padre se mapea a `CATALOGO`/`ESQUEMA` y una palabra
        no mapeable se omite.

        Args:
            objeto (ObjetoSecurable): objeto del plano de datos a consultar.

        Returns:
            list[ItemGrant]: otorgamientos vigentes; lista vacía cuando el
                objeto no tiene ninguno (vacío distinguible de un fallo).

        Raises:
            ErrorCanal: si el tipo de objeto no está soportado por este canal.
        """
        sentencia = self.ConstruirShowGrant(objeto)
        filas = self.sesion_sql.sql(sentencia)
        return self._ParsearFilas(objeto, filas)

    def _ParsearFilas(self, objeto, filas):
        """Traduce las filas de SHOW GRANT a otorgamientos, omitiendo lo inválido.

        Args:
            objeto (ObjetoSecurable): objeto consultado.
            filas (list): filas devueltas por la sesión.

        Returns:
            list[ItemGrant]: otorgamientos válidos en el orden devuelto.
        """
        grants = []
        for fila in filas:
            grant = self._GrantDesdeFila(objeto, fila)
            if grant is not None:
                grants.append(grant)
        return grants

    def _GrantDesdeFila(self, objeto, fila):
        """Traduce una fila de SHOW GRANT a un ItemGrant (o None si es inválida).

        Args:
            objeto (ObjetoSecurable): objeto consultado.
            fila (list[str]): fila con columnas Principal, ActionType,
                ObjectType, ObjectKey.

        Returns:
            ItemGrant | None: otorgamiento vigente, o None si la fila no
                permite construir un otorgamiento válido (palabra no mapeable o
                fila malformada).
        """
        try:
            referencia = str(fila[COLUMNA_PRINCIPAL]).strip()
            privilegio = str(fila[COLUMNA_ACCION]).strip()
            tipo_palabra = _NormalizarPalabra(str(fila[COLUMNA_TIPO_OBJETO]))
            clave = _NormalizarClave(str(fila[COLUMNA_CLAVE_OBJETO]))

            objeto_del_grant = self._ObjetoDeFila(objeto, tipo_palabra, clave)
            if objeto_del_grant is None:
                return None

            return ItemGrant(
                principal=Principal(
                    identificador=referencia,
                    tipo=InferirTipoPrincipal(referencia),
                ),
                privilegio=privilegio,
                objeto=objeto_del_grant,
            )
        except (ErrorDominio, IndexError):
            # Fila malformada (sin columnas, principal vacío): se omite sin
            # abortar la lectura de los demás otorgamientos.
            return None

    @staticmethod
    def _ObjetoDeFila(objeto, tipo_palabra, clave):
        """Resuelve el securable sobre el que nació el otorgamiento de la fila.

        Regla (design D4): si la fila describe el propio objeto consultado (misma
        palabra clave que su tipo e igual clave), se conserva el tipo consultado;
        si describe un contenedor padre (`CATALOG`/`SCHEMA`), se mapea al tipo
        contenedor; en cualquier otro caso devuelve None (sin inventar objeto).

        Args:
            objeto (ObjetoSecurable): objeto consultado.
            tipo_palabra (str): palabra clave SQL de la fila, en mayúsculas.
            clave (str): clave del securable de la fila, normalizada.

        Returns:
            ObjetoSecurable | None: securable del otorgamiento, o None.
        """
        palabra_del_consultado = PALABRA_CLAVE_SQL_POR_TIPO_OBJETO[objeto.tipo]
        if tipo_palabra == palabra_del_consultado and clave == objeto.identificador:
            return objeto

        tipo_contenedor = PALABRA_CLAVE_CONTENEDORA_A_TIPO.get(tipo_palabra)
        if tipo_contenedor is None:
            return None
        return ObjetoSecurable(identificador=clave, tipo=tipo_contenedor)

    def _Ejecutar(self, item, sentencia):
        """Ejecuta la sentencia en la sesión inyectada y traduce sus errores.

        Traduce el error del workspace a la excepción de canal que corresponde
        al caso (design D3): solo el permiso denegado explícito se convierte en
        `ErrorPrivilegiosInsuficientes`; el objeto inexistente y el principal
        inexistente en `ErrorCanal` con mensaje específico, y el resto en
        `ErrorCanal` genérico. El contrato base convierte estas excepciones en
        el resultado por ítem, sin propagarlas al llamador.

        Args:
            item (ItemGrant): ítem en ejecución, para los mensajes del caso.
            sentencia (str): sentencia SQL a ejecutar.
        """
        try:
            self.sesion_sql.sql(sentencia)
        except ErrorPrivilegiosInsuficientes as excepcion:
            raise excepcion
        except ErrorCanal as excepcion:
            raise excepcion
        except Exception as excepcion:  # noqa: BLE001 - se traduce a canal
            self._RegistrarErrorEjecucion(excepcion, item)
            self._TraducirError(item, excepcion)

    def _RegistrarErrorEjecucion(self, excepcion, item):
        """Registra en la bitácora de errores el fallo de ejecución, sin propagarlo.

        Esa auditoría es un efecto lateral que nunca debe convertirse en un punto
        de fallo en cascada (design D6): si no hay registrador o el propio
        registro falla, el error queda igual traducido a resultado por ítem.

        Args:
            excepcion (BaseException): excepción capturada de la sesión SQL.
            item (ItemGrant): ítem cuya ejecución falló.
        """
        if self._registrador_errores is None:
            return
        try:
            self._registrador_errores.Registrar(
                excepcion,
                modulo=MODULO_BITACORA_ERRORES,
                usuario=None,
                contexto=(
                    f"ejecución de instrucción sobre "
                    f"{item.objeto.tipo.value} '{item.objeto.identificador}'"
                ),
            )
        except Exception:  # noqa: BLE001 - la bitácora nunca propaga
            return

    def _TraducirError(self, item, error):
        """Traduce el error del motor SQL a la excepción de canal del caso.

        Args:
            item (ItemGrant): ítem en ejecución, para los mensajes del caso.
            error (BaseException): excepción capturada de la sesión SQL.

        Raises:
            ErrorPrivilegiosInsuficientes: si el error es permiso denegado.
            ErrorCanal: en cualquier otro caso, con mensaje específico (objeto o
                principal inexistente) o genérico.
        """
        texto = str(error)
        if _CoincideAlgunPatron(texto, PATRONES_PERMISO_DENEGADO):
            raise ErrorPrivilegiosInsuficientes(self._MensajePermisoDenegado(item))
        if _CoincideAlgunPatron(texto, PATRONES_OBJETO_INEXISTENTE):
            raise ErrorCanal(self._MensajeObjetoInexistente(item))
        if _CoincideAlgunPatron(texto, PATRONES_PRINCIPAL_INEXISTENTE):
            raise ErrorCanal(self._MensajePrincipalInexistente(item))
        raise ErrorCanal(texto)

    @staticmethod
    def _MensajePermisoDenegado(item):
        """Mensaje del caso permiso denegado, con privilegio y objeto.

        Args:
            item (ItemGrant): ítem que el ejecutor no pudo otorgar/revocar.

        Returns:
            str: texto explícito en español del permiso denegado.
        """
        return (
            f"El ejecutor no tiene privilegios para otorgar o revocar "
            f"{item.privilegio} sobre {item.objeto.tipo.value} "
            f"'{item.objeto.identificador}' (permiso denegado)."
        )

    @staticmethod
    def _MensajeObjetoInexistente(item):
        """Mensaje del caso objeto inexistente, con el objeto del ítem.

        Args:
            item (ItemGrant): ítem cuyo objeto no existe.

        Returns:
            str: texto explícito en español del objeto inexistente.
        """
        return (
            f"El objeto {item.objeto.tipo.value} "
            f"'{item.objeto.identificador}' no existe en el metastore."
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


class SesionSparkSql:
    """Adapta una `SparkSession` al puerto de sesión del canal (`sql -> filas`).

    En la Databricks App la sesión real es una `SparkSession` cuyo `sql()`
    devuelve un `DataFrame`; este adaptador lo normaliza a filas de texto
    (listas de listas), el mismo contrato que entrega el transporte por CLI de
    las pruebas integrales y que consume `CanalSqlDatos`.

    Attributes:
        sesion_spark: `SparkSession` del entorno de ejecución.
    """

    def __init__(self, sesion_spark):
        """Inicializa el adaptador con la SparkSession del entorno.

        Args:
            sesion_spark: SparkSession cuyo `sql()` ejecuta las instrucciones.

        Raises:
            ValueError: si no se recibe una SparkSession con `sql`.
        """
        if sesion_spark is None or not hasattr(sesion_spark, "sql"):
            raise ValueError(
                "Se requiere una SparkSession con el método 'sql()'."
            )
        self.sesion_spark = sesion_spark

    def sql(self, sentencia):
        """Ejecuta la sentencia y devuelve sus filas normalizadas a texto.

        Args:
            sentencia (str): sentencia SQL a ejecutar.

        Returns:
            list[list[str]]: filas del resultado (`collect()` del DataFrame)
                convertidas a listas de textos; `None`/vacío se representa como
                texto vacío para no perder la posición de la columna.
        """
        marco = self.sesion_spark.sql(sentencia)
        return [_FilaATexto(fila) for fila in marco.collect()]


def _FilaATexto(fila):
    """Normaliza una fila (Row o secuencia) a una lista de textos.

    Args:
        fila: fila de Spark (Row) o secuencia de valores.

    Returns:
        list[str]: valores de la fila como textos; un valor ausente se
            representa como cadena vacía.
    """
    return [str(valor) if valor is not None else "" for valor in fila]


def _PalabraClaveSql(tipo):
    """Devuelve la palabra clave SQL del tipo, o rechaza el tipo fuera de alcance.

    Args:
        tipo (TipoObjeto): tipo del objeto securable.

    Returns:
        str: palabra clave SQL en mayúsculas del tipo.

    Raises:
        ErrorCanal: si el tipo no pertenece a los ocho soportados por este canal.
    """
    palabra_clave = PALABRA_CLAVE_SQL_POR_TIPO_OBJETO.get(tipo)
    if palabra_clave is None:
        raise ErrorCanal(
            f"El tipo de objeto '{tipo.value}' no está soportado por el "
            "canal SQL del plano de datos (change grants-uc-datos)."
        )
    return palabra_clave


def _IdentificadorSql(identificador):
    """Encierra cada parte del identificador entre comillas invertidas.

    El nombre calificado de Unity Catalog (`catalogo.esquema.tabla`) se escribe
    parte por parte, de modo que cada componente quede protegido sin romper la
    calificación.

    Args:
        identificador (str): nombre simple o calificado del securable.

    Returns:
        str: identificador seguro para la instrucción SQL.
    """
    partes = [parte for parte in str(identificador).split(".") if parte]
    return ".".join(f"`{parte}`" for parte in partes)


def _IdentificadorPrincipal(identificador):
    """Encierra el identificador del principal entre comillas invertidas.

    A diferencia del nombre del objeto, el identificador de un principal (correo
    del usuario, nombre del grupo o App Id del service principal) es una única
    referencia y no se divide por puntos.

    Args:
        identificador (str): identificación del principal.

    Returns:
        str: referencia del principal protegida para la instrucción SQL.
    """
    return f"`{identificador}`"


def _CoincideAlgunPatron(texto, patrones):
    """Devuelve True si el texto coincide con alguno de los patrones.

    Args:
        texto (str): texto donde buscar (el mensaje del error del workspace).
        patrones (tuple[re.Pattern, ...]): patrones compilados a probar.

    Returns:
        bool: True si al menos un patrón coincide con el texto.
    """
    return any(patron.search(texto) for patron in patrones)


def InferirTipoPrincipal(referencia):
    """Deduce el tipo de principal desde la forma de la referencia textual.

    Unity Catalog reporta el otorgatario solo como texto: el correo del usuario,
    el nombre del grupo o el App Id (UUID) del service principal. La regla es
    declarada y coincide con la usada en la capa integral del proyecto:

    - forma de App Id (UUID) -> `service_principal`;
    - forma de correo -> `usuario`;
    - cualquier otro texto -> `grupo`.

    Args:
        referencia (str): texto del otorgatario reportado por el workspace.

    Returns:
        TipoPrincipal: tipo deducido de la referencia.
    """
    if EXPRESION_APP_ID.match(referencia):
        return TipoPrincipal.SERVICE_PRINCIPAL
    if EXPRESION_CORREO.match(referencia):
        return TipoPrincipal.USUARIO
    return TipoPrincipal.GRUPO


def _NormalizarPalabra(texto):
    """Normaliza una palabra clave SQL de una fila (recorta y a mayúsculas).

    Args:
        texto (str): palabra clave reportada por SHOW GRANT.

    Returns:
        str: palabra recortada y en mayúsculas.
    """
    return texto.strip().upper()


def _NormalizarClave(texto):
    """Normaliza la clave de un securable reportada por SHOW GRANT.

    Recorta espacios, quita las comillas invertidas que el motor pueda incluir y
    convierte a minúsculas (los identificadores del plano de datos no distinguen
    mayúsculas, igual que la normalización del dominio).

    Args:
        texto (str): clave del securable (simple o calificada).

    Returns:
        str: clave lista para comparar con el identificador normalizado.
    """
    return texto.strip().replace("`", "").lower()
