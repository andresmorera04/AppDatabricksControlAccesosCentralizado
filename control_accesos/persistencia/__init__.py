"""Subpaquete de persistencia de la aplicación (capability `app-persistence`).

Contiene la capa de persistencia sobre tablas delta del esquema dedicado
`control_acceso_app` (creado idempotentemente en el catálogo configurado),
según el estándar del proyecto (README.md - Estándar de desarrollo): tablas
delta idempotentes con liquid clustering, change data feed, optimizeWrite y
autoCompact, escritura masiva vía PySpark e integridad de llaves garantizada
desde el código.

Módulos (se agregan a lo largo del change):

- `ddl.py`: definiciones declarativas de esquema y tablas y el constructor de
  sentencias SQL idempotentes (`CREATE ... IF NOT EXISTS`) con las propiedades
  delta del estándar (design.md D4).
- `inicializador.py`: ejecución idempotente del DDL contra la sesión Spark
  inyectada (tarea 3.2).
- `capa_persistencia.py`: escritura masiva en append vía PySpark (tarea 3.3).
- `integridad.py`: helpers de llave primaria/foránea con operaciones masivas
  (tarea 3.4).
- `errores.py`: excepciones propias de la capa de persistencia.

Ver openspec/changes/persistencia-bitacora/specs/app-persistence/spec.md y
openspec/changes/persistencia-bitacora/design.md.
"""
