"""Autenticación on-behalf-of del llamante (capability `caller-identity`).

Resuelve, a partir del contexto OAuth on-behalf-of que la plataforma de
Databricks Apps entrega en cada invocación, **quién es el llamante**: un
principal del dominio (`usuario`, `grupo` o `service_principal`, este último
identificado por su App Id) y los grupos de los que es miembro.

Ver `openspec/changes/auth-caller-obo/specs/caller-identity/spec.md` y su
design.md (D1). La obtención del contexto queda detrás del puerto
`ProveedorIdentidadLlamante`, de modo que producción use el contexto real de
la app y las pruebas uno simulado.
"""
