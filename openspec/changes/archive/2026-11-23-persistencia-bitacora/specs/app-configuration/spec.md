# Spec Delta

## Purpose

Proporciona a la aplicación una fuente única de configuración no hardcodeada: el archivo de propiedades JSON `config/app_properties.json`, con carga validada, acceso parametrizado a sus atributos y errores explícitos ante cualquier defecto del archivo.

## ADDED Requirements

### Requirement: Carga validada del archivo de propiedades

El sistema SHALL cargar su configuración desde el archivo de propiedades JSON de la aplicación (`config/app_properties.json`) y exponer sus atributos de forma parametrizada. Un archivo inexistente o con JSON inválido SHALL ser rechazado con un error explícito antes de usar cualquier valor.

#### Scenario: Carga exitosa

- **WHEN** la aplicación solicita la configuración y el archivo de propiedades existe y es JSON válido
- **THEN** la configuración queda disponible con los atributos y valores definidos en el archivo

#### Scenario: Archivo de propiedades inexistente

- **WHEN** la aplicación solicita la configuración y el archivo de propiedades no existe
- **THEN** el sistema reporta un error explícito que indica la ruta esperada del archivo faltante

#### Scenario: Archivo con JSON inválido

- **WHEN** la aplicación solicita la configuración y el archivo no contiene JSON válido
- **THEN** el sistema reporta un error explícito que indica que el archivo no es JSON válido, sin usar valor alguno

### Requirement: Atributo catalogo

El sistema SHALL exponer el atributo `catalogo`, nombre del catálogo de Unity Catalog donde vive el esquema dedicado de la aplicación. El archivo distribuido con la aplicación SHALL definir `catalogo` con el valor por defecto `control`, y un `catalogo` ausente SHALL ser rechazado con un error explícito.

#### Scenario: Lectura del catálogo configurado

- **WHEN** un componente consulta el atributo `catalogo`
- **THEN** el sistema devuelve el valor definido en el archivo de propiedades

#### Scenario: Atributo catalogo ausente

- **WHEN** el archivo de propiedades no define el atributo `catalogo`
- **THEN** el sistema reporta un error explícito que indica el atributo obligatorio faltante

### Requirement: Fuente única de configuración de solo lectura

La configuración cargada SHALL ser la única fuente de valores configurables de la aplicación (regla No HardCoded) y SHALL comportarse como de solo lectura durante la ejecución: ningún componente podrá alterar sus atributos en tiempo de ejecución.

#### Scenario: Intento de modificación en tiempo de ejecución

- **WHEN** un componente intenta alterar un atributo de la configuración ya cargada
- **THEN** la configuración permanece inalterada con los valores originales del archivo

#### Scenario: Crecimiento del archivo de propiedades

- **WHEN** un change posterior agrega un nuevo atributo al archivo de propiedades
- **THEN** el sistema lo expone parametrizado por el mismo mecanismo, sin modificar los atributos existentes
