"""Escritores POO de las bitácoras (capability `audit-logging`).

Estructura (design.md D6):

- `EscritorBitacora`: base común con la mecánica de escritura masiva. Recibe
  la sesión Spark y la capa de persistencia por inyección, convierte los
  modelos de registro a un DataFrame con el esquema de la tabla destino (única
  fuente de verdad: el esquema se lee de la tabla creada por el inicializador)
  y delega la escritura en la capa, con verificación de llave primaria.
- `BitacoraEventos`: registra la actividad general de la aplicación.
- `BitacoraErrores`: registra los errores controlados vía try/except, con el
  detalle STRUCT extraído de la excepción capturada.

La escritura degrada de forma controlada (design.md D7): si falla, el escritor
NO propaga la excepción ni la re-registra en la propia bitácora; deja
constancia visible en stderr y continúa la operación principal.

Regla "PySpark al máximo": la conversión de modelos Python a filas es una
comprensión del lado del driver (inevitable: son objetos, no datos
distribuidos); TODO el procesamiento posterior (validación de integridad y
escritura) son operaciones masivas de la capa de persistencia, sin ciclos por
fila sobre el DataFrame.
"""

import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime

from control_accesos.bitacora.constructores import (
    ConstruirRegistroError,
    MARCA_TRAZA_NO_DISPONIBLE,
)
from control_accesos.bitacora.modelos import EventoBitacora
from control_accesos.persistencia.capa_persistencia import CapaPersistencia
from control_accesos.persistencia.ddl import (
    DEFINICION_BITACORA_ERRORES,
    DEFINICION_BITACORA_EVENTOS,
)


class EscritorBitacora:
    """Base común de los escritores de bitácora: escritura masiva vía la capa.

    Attributes:
        sesion: sesión Spark inyectada (local en pruebas, del entorno en la
            Databricks App).
        capa (CapaPersistencia): capa de persistencia que ejecuta la escritura
            masiva con verificación de integridad.
        definicion (DefinicionTabla): definición declarativa de la tabla de
            bitácora (nombre y llaves primarias), fijada por cada subclase.
    """

    # Cada subclase fija la definición de su tabla destino.
    definicion = None

    def __init__(self, sesion, capa=None, configuracion=None):
        """Inicializa el escritor con la sesión y la capa de persistencia.

        Args:
            sesion: sesión Spark inyectada.
            capa (CapaPersistencia | None): capa de persistencia a usar; si no
                se aporta, se construye una con la configuración recibida.
            configuracion (ConfiguracionApp | None): configuración de la
                aplicación; obligatoria cuando no se inyecta la capa.

        Raises:
            ValueError: si no se recibe sesión, o si no se recibe ni capa ni
                configuración (sin una de ellas no hay ruta de escritura).
        """
        if sesion is None:
            raise ValueError(
                "Se requiere una sesión Spark para escribir en la bitácora."
            )
        if capa is None and configuracion is None:
            raise ValueError(
                "Se requiere inyectar la capa de persistencia o la "
                "configuración de la aplicación para construirla."
            )

        self.sesion = sesion
        self.capa = (
            capa
            if capa is not None
            else CapaPersistencia(sesion=sesion, configuracion=configuracion)
        )
        self.definicion = type(self).definicion

    @property
    def nombre_tabla(self):
        """Nombre de la tabla delta destino dentro del esquema dedicado.

        Returns:
            str: nombre declarado en el registro de tablas (sin hardcodear).
        """
        return self.definicion.nombre

    def RegistrarLote(self, registros):
        """Escribe masivamente un lote de registros de bitácora.

        Convierte los modelos a un DataFrame con el esquema de la tabla destino
        y delega en la capa de persistencia, que verifica la llave primaria
        declarada y escribe el lote completo en una sola operación (append).

        Args:
            registros (Iterable): modelos de registro del escritor.

        Returns:
            tuple: los registros procesados (con sus identificadores
            generados). Se devuelven aunque la escritura haya fallado: la
            bitácora degrada de forma controlada (design.md D7) y no interrumpe
            la operación principal.
        """
        lote = tuple(registros)
        if not lote:
            # Lote vacío: nada que escribir; se devuelve sin tocar la tabla.
            return ()

        try:
            marco = self._ConstruirMarco(lote)
            self.capa.EscribirConIntegridad(
                marco,
                self.nombre_tabla,
                claves_primarias=self.definicion.claves_primarias,
            )
        except Exception as excepcion:
            # La bitácora no puede ser un punto único de fallo en cascada
            # (design.md D7): se captura el fallo, se deja constancia visible
            # en stderr y se continúa SIN propagar excepción y SIN reintentar
            # el registro en la propia bitácora (anti-recursión).
            self._ReportarFalloLocal(excepcion, len(lote))

        return lote

    def _ReportarFalloLocal(self, excepcion, cantidad_registros):
        """Deja constancia visible en stderr del fallo al escribir la bitácora.

        Es la válvula de degradación controlada (design.md D7): cuando no se
        puede persistir en la tabla delta, el fallo no se pierde en silencio ni
        se propaga; se reporta en la salida local con el detalle de la causa y
        la cantidad de registros afectados. Nunca escribe de nuevo en la
        bitácora, para no provocar recursión.

        Args:
            excepcion (BaseException): causa del fallo de escritura.
            cantidad_registros (int): registros del lote que no se persistieron.
        """
        print(
            f"[BITÁCORA] No se pudieron escribir {cantidad_registros} "
            f"registro(s) en '{self.nombre_tabla}': {excepcion}. La ejecución "
            f"continúa; el fallo queda reportado solo en la salida local.",
            file=sys.stderr,
        )

    def _ConstruirMarco(self, registros):
        """Convierte modelos de registro a un DataFrame del esquema destino.

        El esquema se lee de la tabla ya creada por el inicializador: es la
        única fuente de verdad de tipos (incluido el STRUCT del detalle de
        errores), de modo que los modelos no duplican la declaración de tipos.

        Args:
            registros (tuple): modelos de registro a convertir.

        Returns:
            pyspark.sql.DataFrame: lote listo para la escritura masiva.
        """
        nombre_calificado = self.capa.NombreTablaCalificado(self.nombre_tabla)
        esquema = self.sesion.table(nombre_calificado).schema

        # Conversión de objetos Python a filas: comprensión del lado del
        # driver (los modelos no son datos distribuidos). El orden de valores
        # de cada fila sigue el orden de columnas del esquema destino.
        filas = [
            self._FilaDeRegistro(registro, esquema) for registro in registros
        ]
        return self.sesion.createDataFrame(filas, esquema)

    @staticmethod
    def _FilaDeRegistro(registro, esquema):
        """Convierte un modelo de registro a una tupla de valores ordenada.

        Args:
            registro: modelo con campos del mismo nombre que las columnas.
            esquema (pyspark.sql.types.StructType): esquema de la tabla destino.

        Returns:
            tuple: valores del registro en el orden de columnas del esquema;
            los campos que son dataclasses (por ejemplo, un detalle STRUCT) se
            convierten a diccionario, que Spark materializa como STRUCT.
        """
        valores = []
        for campo in esquema.fields:
            valor = getattr(registro, campo.name)
            if is_dataclass(valor) and not isinstance(valor, type):
                # STRUCT declarado en el DDL <- dataclass de detalle.
                valor = asdict(valor)
            valores.append(valor)
        return tuple(valores)


class BitacoraEventos(EscritorBitacora):
    """Escritor de la bitácora de eventos generales (tabla `bitacora_eventos`).

    Registra toda la actividad de la aplicación con el usuario que provoca cada
    evento (identidad on-behalf-of cuando exista; nulo explícito mientras
    tanto, ver spec `audit-logging`).

    Example:
        >>> bitacora = BitacoraEventos(sesion=sesion, capa=capa)
        >>> evento = bitacora.Registrar(accion="otorgar_privilegios",
        ...                             usuario="demo", resultado="otorgado")
        >>> evento.id_evento  # UUID generado, consultable en la tabla
    """

    # Definición declarativa de la tabla destino (registro del módulo DDL).
    definicion = DEFINICION_BITACORA_EVENTOS

    def Registrar(
        self,
        accion,
        usuario=None,
        detalle=None,
        resultado=None,
        marca_tiempo=None,
    ):
        """Construye y registra un evento de la aplicación.

        Args:
            accion (str): acción realizada (obligatoria, no vacía).
            usuario (str | None): usuario que provoca el evento; `None` cuando
                no hay identidad disponible (el evento se registra igual).
            detalle (str | None): detalle libre del evento.
            resultado (str | None): resultado observable del evento.
            marca_tiempo (datetime | None): momento del evento; por defecto,
                el instante del registro.

        Returns:
            EventoBitacora: el evento registrado, con su `id_evento` generado.

        Raises:
            ValueError: si la acción está vacía (validación del modelo).
        """
        evento = EventoBitacora(
            accion=accion,
            usuario=usuario,
            detalle=detalle,
            resultado=resultado,
            marca_tiempo=marca_tiempo or datetime.now(),
        )
        self.RegistrarLote((evento,))
        return evento


class BitacoraErrores(EscritorBitacora):
    """Escritor de la bitácora de errores (tabla `bitacora_errores`).

    Registra todo error controlado vía try/except con el máximo detalle
    (estándar del proyecto): extrae de la excepción capturada el tipo, el
    mensaje y la traza, y los combina con el contexto aportado por el punto de
    captura en el campo STRUCT `detalle` (design.md D6).

    Example:
        >>> try:
        ...     operacion_riesgosa()
        ... except Exception as excepcion:
        ...     bitacora_errores.Registrar(excepcion, modulo="ejecutor",
        ...                                contexto="otorgando grant 1 a 1")
    """

    # Definición declarativa de la tabla destino (registro del módulo DDL).
    definicion = DEFINICION_BITACORA_ERRORES

    def Registrar(self, excepcion, modulo, usuario=None, contexto="",
                  marca_tiempo=None):
        """Construye y registra un error capturado por la aplicación.

        Args:
            excepcion (BaseException): excepción capturada por el try/except.
            modulo (str): módulo o componente donde se capturó (obligatorio).
            usuario (str | None): usuario que provocaba la operación fallida;
                `None` cuando no hay identidad disponible.
            contexto (str): descripción de la operación que falló y sus datos
                relevantes, aportada por el punto de captura.
            marca_tiempo (datetime | None): momento de la captura; por defecto,
                el instante del registro.

        Returns:
            RegistroError: el registro escrito, con su `id_error` generado.

        Raises:
            ValueError: si el módulo está vacío (validación del modelo).
        """
        registro = self.ConstruirRegistro(
            excepcion=excepcion,
            modulo=modulo,
            usuario=usuario,
            contexto=contexto,
            marca_tiempo=marca_tiempo,
        )
        self.RegistrarLote((registro,))
        return registro

    @staticmethod
    def ConstruirRegistro(excepcion, modulo, usuario=None, contexto="",
                          marca_tiempo=None):
        """Construye el modelo `RegistroError` desde la excepción capturada.

        Delega en el constructor compartido Spark-free
        (`bitacora.constructores.ConstruirRegistroError`), única fuente de la
        regla de extracción del detalle STRUCT (tipo, mensaje, traza y
        contexto), para no duplicarla entre el escritor Spark y el restaurante
        REST de la App (design.md D5/D10).

        Args:
            excepcion (BaseException): excepción capturada por el try/except.
            modulo (str): módulo o componente donde se capturó.
            usuario (str | None): usuario que provocaba la operación fallida.
            contexto (str): contexto de la operación que falló.
            marca_tiempo (datetime | None): momento de la captura; por defecto,
                el instante de la construcción.

        Returns:
            RegistroError: modelo listo para registrarse (no escribe nada).
        """
        return ConstruirRegistroError(
            excepcion=excepcion,
            modulo=modulo,
            usuario=usuario,
            contexto=contexto,
            marca_tiempo=marca_tiempo,
        )
