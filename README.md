# FarmaRed — TPO de Bases de Datos 2

MongoDB será la fuente de verdad y Neo4j una proyección eventualmente consistente.
Esta primera entrega proporciona el paquete Python, contratos comunes, configuración,
reloj y router CLI. Los motores, la carga y q01–q15 todavía no están implementados.

## Instalación y verificación de esta entrega

Desde la raíz del repositorio, con Python 3.11–3.14 y **uv 0.13.7** instalado:

```bash
uv sync --locked
uv run --locked farmared --help
uv run --locked python -m farmared estado
uv run --locked pytest
```

`uv.lock` fija dependencias transitivas y hashes; `pyproject.toml` fija versiones
directas y el backend de construcción. `uv sync --locked` instala el proyecto en
modo editable en `.venv`. No hace falta configurar motores para estos comandos.
Se incluyen los drivers oficiales para los siguientes frentes, pero la CLI solo
importa el handler seleccionado y no importa drivers ni abre conexiones al arrancar.
Las versiones se verificaron en [PyPI: PyMongo](https://pypi.org/project/pymongo/4.19.0/),
[Neo4j](https://pypi.org/project/neo4j/6.4.1/) y [pytest](https://pypi.org/project/pytest/9.2.0/).

`estado` informa versión y reloj, con motores/proyección **no comprobados**.
`q01`–`q15`, `seed`, `validar-datasets`, `setup`, `reset-demo`, `sync` y
`demo-transaccion` están anunciados como pendientes: invocarlos termina con código
3 y explica el responsable. Todavía no reciben parámetros de negocio.
Los códigos de salida son 0 (éxito), 1 (error de dominio), 2 (uso inválido) y
3 (comando pendiente). Las fallas internas no se convierten en éxitos ni se
disfrazan como módulos pendientes. No se creó lógica de otros integrantes.

## Configuración y contratos

Copiar `.env.example` a `.env` cuando se necesite configuración local. No contiene
credenciales reales; `NEO4J_PASSWORD` queda vacío hasta configurar el motor.
`Config.from_env()` lee `MONGO_URI`, `MONGO_DB`, `NEO4J_URI`, `NEO4J_USER`,
`NEO4J_PASSWORD` y `DB_TIMEOUT_MS` (1–300000, por defecto 10000).
No abre conexiones ni lee `.env` automáticamente. Para cargarlo con uv:

```bash
uv run --locked --env-file .env python -m farmared estado
```

El comando anterior solo comprueba el paquete/reloj. Las URI por defecto apuntan
al host local; los nombres de servicio y readiness vendrán con Compose.
Los secretos y URI se omiten de `repr(Config)`.

- `farmared.clock.Clock`: protocolo `today() -> date`, `now_utc() -> datetime`.
  `SystemClock` usa el reloj real; `FixedClock` exige un instante con zona explícita.
- `inicio_dia_utc(date)`: inicio del día en `America/Argentina/Buenos_Aires`,
  convertido a UTC para BSON Date. Los instantes outbox usan `now_utc()` directamente.
- `farmared.errores.ErrorDominio(codigo, mensaje)`: campos públicos y códigos del reparto.
- `farmared.contratos`: nombres de colecciones, enums literales y formas de outbox
  y retornos de escritura. `TypedDict` documenta estructura; no valida persistencia.
- `validar_importe_ars`: entero ARS entre 0 y `2**63-1`, rechaza floats y booleanos.
  Aplicar también a resultados de sumas/productos antes de persistir. No convierte CSV.
- IDs, DNI, CUIT y teléfonos permanecen strings; los detalles irán en `ventas.items`.

Las interfaces `obtener_mongo(config)`, `obtener_neo4j(config)`,
`preparar_mongo_base(db)` y `cargar_mongo(db, rutas)` se implementarán en las partes
2, 3 y 5 respectivamente. No se publican stubs que aparenten funcionar.

## Datos disponibles y secuencia de entregas

Se encontraron los nueve CSV en `datasets_farmared/`, directorio ignorado previamente.
Se inspeccionaron cabeceras, enums y conteos (8 clientes, 5 sucursales, 7 farmacéuticos,
5 proveedores, 13 productos, 18 lotes, 9 recetas, 16 ventas y 22 detalles).
Esto **no** constituye validación integral ni una carga. Los originales permanecen
intactos. Su incorporación versionada en `data/originales/` queda para la entrega
de datasets, junto con referencias, importes, totales y diagnósticos de filas.

1. Paquete, contratos, configuración, reloj y CLI mínima: esta entrega.
2. Compose/devcontainer, conexiones y readiness con primario real.
3. Colecciones, validadores e índices base MongoDB.
4. Lectura, conversión y validación integral de los nueve CSV.
5. Carga idempotente, manifiesto/huellas, historia y outbox transaccional.
6. Adicionales reproducibles con `base_date` persistida y casos borde.
7. Integración disponible de B/C/D, CI, evidencias, diagramas y ensamblado del informe.

Cada parte incluye sus pruebas y documentación, y se revisa antes de continuar.
El fragmento de A está en `docs/informe/a_infra_y_carga.md`; la evidencia de esta
entrega está en `docs/evidencias/a/parte_01.md`. Las pruebas propias van en
`tests/a_carga/`; no utilizan bases compartidas.
