"""Prueba unitaria de la redacción de secretos y manejo controlado (design.md D11).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`, tarea 5.3.

Contrato que fija esta prueba, sobre `RedactorSecretos`:

- tokens con prefijo `dapi...` se redactan;
- headers `Authorization` (y valores `Bearer`) se redactan;
- el header `x-forwarded-access-token` se redacta;
- `DATABRICKS_CLIENT_SECRET`/`client_secret` se redactan;
- cualquier valor con prefijo `CONTROL_ACCESOS_` se redacta;
- el manejo controlado de errores devuelve solo el mensaje redactado, sin
  stack trace (ni `Traceback` ni rutas).

El texto inocuo queda intacto.
"""

from control_accesos.ui.redaccion import RedactorSecretos

TOKEN_EJEMPLO = "dapi9f3a2b7c8d4e5f60718293a4b5c6d7"
SECRETO_EJEMPLO = "dose4f91c0104879bf8913d68ebb01a28"


def _Redactar(texto):
    return RedactorSecretos().Redactar(texto)


def TestTokenDapiSeRedacta():
    """Un token con prefijo dapi se sustituye por la marca."""
    texto = f"el token {TOKEN_EJEMPLO} falló"

    redactado = _Redactar(texto)

    assert TOKEN_EJEMPLO not in redactado
    assert "token_redactado" in redactado


def TestHeaderAuthorizationSeRedacta():
    """El header Authorization (y su Bearer) se sustituye íntegro."""
    texto = f"Authorization: Bearer {TOKEN_EJEMPLO}"

    redactado = _Redactar(texto)

    assert TOKEN_EJEMPLO not in redactado
    assert "authorization_redactado" in redactado


def TestHeaderOBORedactado():
    """El header x-forwarded-access-token se redacta."""
    texto = f"x-forwarded-access-token: {TOKEN_EJEMPLO}"

    redactado = _Redactar(texto)

    assert TOKEN_EJEMPLO not in redactado
    assert "secreto_redactado" in redactado


def TestClientSecretSeRedacta():
    """DATABRICKS_CLIENT_SECRET y client_secret se redactan."""
    redactado = _Redactar(
        f"client_secret={SECRETO_EJEMPLO} y "
        f"DATABRICKS_CLIENT_SECRET={SECRETO_EJEMPLO}"
    )

    assert SECRETO_EJEMPLO not in redactado
    assert redactado.count("secreto_redactado") >= 2


def TestVariablesControlAccesosSeRedactan():
    """Los valores con prefijo CONTROL_ACCESOS_ se redactan."""
    texto = f"CONTROL_ACCESOS_DB_TOKEN={SECRETO_EJEMPLO}"

    redactado = _Redactar(texto)

    assert SECRETO_EJEMPLO not in redactado
    assert "secreto_redactado" in redactado


def TestManejoControladoSinStackTrace():
    """El manejo controlado devuelve el mensaje redactado, sin traza."""
    excepcion = RuntimeError(f"fallo con token {TOKEN_EJEMPLO}")

    mensaje = RedactorSecretos().MensajeDeErrorControlado(excepcion)

    assert TOKEN_EJEMPLO not in mensaje
    assert "Traceback" not in mensaje
    assert "File \"" not in mensaje
    assert "fallo con token" in mensaje


def TestTextoInocuoIntacto():
    """El texto sin secretos permanece inalterado."""
    texto = "SELECT * FROM ventas WHERE id = 42"

    assert _Redactar(texto) == texto
