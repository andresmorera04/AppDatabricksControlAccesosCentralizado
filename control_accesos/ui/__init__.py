"""Interfaz web de la aplicación de control de accesos (C9).

Paquete de la capability `grant-management-ui` (change `web-ui-minimalista`):
capas POO entre la vista Streamlit y el pipeline de grants ya existente
(design.md D2) — proveedor de identidad OBO, fábrica del contexto del
llamante, descubrimiento de opciones, servicios de solicitud,
previsualización y ejecución, presentador y controlador de pantalla.

Reglas transversales del paquete:

- autenticación on-behalf-of: descubrimiento, resolución y ejecución usan la
  credencial del usuario llamante; la identidad propia de la App queda
  reservada para la auditoría compartida (design.md D3/D10);
- nada hardcodeado: nombres de atributos de entorno, límites e
  identificadores lógicos se leen de `config/app_properties.json` vía
  `ConfiguracionApp`;
- ningún token, header de autorización o secreto se almacena en el estado de
  sesión, se muestra ni se registra (design.md D11).
"""
