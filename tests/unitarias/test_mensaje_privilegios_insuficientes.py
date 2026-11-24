"""Pruebas unitarias del mensaje estructurado de privilegios insuficientes.

Cubren el escenario "Mensaje estructurado de privilegios insuficientes" del
spec `caller-privilege-resolution` (change `auth-caller-obo`): el bloqueo se
representa como un dato con los cuatro campos que la app debe exponer por
separado (objeto, plano, privilegio requerido y privilegio faltante), y no
como una cadena concatenada que la UI y el reporte tendrían que adivinar.
"""

import pytest

from control_accesos.dominio.enumeraciones import Plano, TipoObjeto
from control_accesos.dominio.errores import ErrorDominio
from control_accesos.dominio.modelos import ObjetoSecurable
from control_accesos.resolucion.modelos import MensajePrivilegiosInsuficientes


def CrearMensaje(
    tipo=TipoObjeto.SQL_WAREHOUSE,
    identificador="a1b2c3d4e5",
    plano=Plano.CONTROL,
    requerido="CAN_MANAGE",
    faltante="CAN_MANAGE",
):
    """Construye un mensaje de bloqueo con valores de prueba.

    Args:
        tipo (TipoObjeto): tipo del objeto objetivo.
        identificador (str): identificación del objeto objetivo.
        plano (Plano): plano que se reporta en el mensaje.
        requerido (str): privilegio que la solicitud pretendía otorgar.
        faltante (str): privilegio que al llamante le hace falta.

    Returns:
        MensajePrivilegiosInsuficientes: mensaje listo para revisar.
    """
    return MensajePrivilegiosInsuficientes(
        objeto=ObjetoSecurable(identificador=identificador, tipo=tipo),
        plano=plano,
        privilegio_requerido=requerido,
        privilegio_faltante=faltante,
    )


def TestCamposConsultablesPorNombre():
    """Escenario 'Campos consultables por nombre': acceso directo a los cuatro."""
    mensaje = CrearMensaje()

    assert mensaje.objeto.identificador == "a1b2c3d4e5"
    assert mensaje.objeto.tipo is TipoObjeto.SQL_WAREHOUSE
    assert mensaje.plano is Plano.CONTROL
    assert mensaje.privilegio_requerido == "CAN_MANAGE"
    assert mensaje.privilegio_faltante == "CAN_MANAGE"


def TestEsInmutable():
    """El mensaje es dato inmutable: la UI no puede deformarlo en ejecución."""
    mensaje = CrearMensaje()

    with pytest.raises(Exception):
        mensaje.privilegio_faltante = "otro"


def TestTextoIdentificaLosCuatroElementos():
    """Escenario 'Texto legible del bloqueo' del spec."""
    mensaje = CrearMensaje(
        tipo=TipoObjeto.CATALOGO,
        identificador="control",
        plano=Plano.DATOS,
        requerido="SELECT",
        faltante="MANAGE",
    )

    texto = mensaje.ComoTexto()

    assert "control" in texto
    assert Plano.DATOS.value in texto
    assert "SELECT" in texto
    assert "MANAGE" in texto
    assert "privilegios insuficientes" in texto.lower()


def TestPrivilegiosDiferentesCuandoSeRequiereVarios():
    """Requerido y faltante son distintos cuando el llamante tiene otros permisos.

    El escenario del README: el llamante puede leer el objeto pero no
    administralo, así que requiere `SELECT` y le falta `MANAGE`.
    """
    mensaje = CrearMensaje(requerido="SELECT", faltante="MANAGE")

    assert mensaje.privilegio_requerido != mensaje.privilegio_faltante
    assert "SELECT" in mensaje.ComoTexto()
    assert "MANAGE" in mensaje.ComoTexto()


def TestObjetoObligatorio():
    """Sin objeto no hay a qué referirse: la construcción falla."""
    with pytest.raises(ErrorDominio):
        MensajePrivilegiosInsuficientes(
            objeto=None,
            plano=Plano.DATOS,
            privilegio_requerido="SELECT",
            privilegio_faltante="SELECT",
        )


def TestPrivilegiosVaciosSeRechazan():
    """Los privilegios son obligatorios: vacío o nulo se rechaza."""
    with pytest.raises(ErrorDominio):
        CrearMensaje(requerido="   ")

    with pytest.raises(ErrorDominio):
        CrearMensaje(faltante=None)


def TestPlanoObligatorio():
    """El plano debe informarse: sin él el mensaje sería ambiguo."""
    with pytest.raises(ErrorDominio):
        CrearMensaje(plano=None)


def TestPlanoAceptaSuValorEnTexto():
    """El plano se normaliza desde su valor en texto (misma convención que el dominio)."""
    mensaje = CrearMensaje(plano=Plano.DATOS.value)

    assert mensaje.plano is Plano.DATOS


def TestPlanoInvalidoSeRechaza():
    """Un plano fuera de la enumeración se rechaza con error explícito."""
    with pytest.raises(ErrorDominio):
        CrearMensaje(plano="galaxia")
