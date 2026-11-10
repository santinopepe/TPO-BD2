# FarmaRed — TPO de Bases de Datos 2


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
al host local; dentro del devcontainer se usan los servicios `mongodb` y `neo4j`.
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

`obtener_mongo(config)` devuelve un `Database` PyMongo después de verificar replica
set, sesiones y primario; usa fechas conscientes de zona UTC y write concern
`majority`. El llamador inicia sesiones con `db.client.start_session()` y cierra
`db.client.close()` al terminar. `obtener_neo4j(config)` devuelve un `Driver` con
autenticación y conectividad verificadas; el llamador lo cierra o usa `with`.
Ninguna función conecta al otro motor, crea esquema, carga datos o sincroniza.
Los errores de conexión usan `ErrorDominio("CONEXION", mensaje)` sin imprimir URI
ni credenciales. `preparar_mongo_base(db)` ya está disponible en
`farmared.esquema.base_mongo`. `cargar_mongo(db, rutas)` sigue pendiente para la
parte 5; no se publican stubs que aparenten funcionar.

## Esquema MongoDB base

Con MongoDB listo y **escritores pausados**, preparar un destino explícito:

```bash
uv run --locked --env-file .env farmared preparar-mongo --base farmared
```

Se crean/aseguran ocho colecciones de negocio y `outbox`, validadores `strict/error`
e índices comunes: DNI y matrícula únicos globales, FEFO y cola outbox. No carga
CSV, ejecuta servicios ni sincroniza. `setup` completo sigue pendiente.
En bases existentes verifica documentos/índices antes del DDL, preserva datos y
rechaza definiciones incompatibles sin reemplazarlas. El DDL no es atómico entre
colecciones y requiere escritores pausados; ante una falla no se anuncia éxito.


## Entorno local: Docker Compose

Requisitos: Docker con Compose v2.24 o posterior, daemon encendido, Python/uv según
la instalación anterior y puertos disponibles. Ejecutar **desde la raíz**:

```bash
python3 infra/preparar_env.py
docker compose --env-file .env -f infra/docker-compose.yml up -d mongodb neo4j
docker compose --env-file .env -f infra/docker-compose.yml run --rm mongodb-init
docker compose --env-file .env -f infra/docker-compose.yml up -d --wait --wait-timeout 180 mongodb neo4j
uv run --locked --env-file .env farmared salud
```

`preparar_env.py` crea `.env` con permisos 0600 y contraseña Neo4j aleatoria, y
`infra/.env` como enlace al mismo archivo para Dev Containers. Ambos están ignorados.
Conserva cualquier `.env` existente: si se copió el ejemplo con contraseña vacía,
completarla (mínimo 8 caracteres) antes de iniciar. No versionar estos archivos.

El inicializador espera conexión, inicia `rs0` solo si falta y espera un primario
real. En un volumen existente verifica la configuración; no ejecuta `reconfig`,
reset ni carga. Los healthchecks solo observan: Mongo exige `isWritablePrimary`
y `setName=rs0`; Neo4j ejecuta `RETURN 1` autenticado por Bolt. El orden explícito
evita depender de una pausa fija o esperar el healthcheck antes de inicializar.

Las imágenes MongoDB **8.0.15**, Neo4j Community **5.26.12**, Python **3.12.12** y
uv **0.13.7** tienen tag y digest fijados. Los paquetes de sistema del Dockerfile
se instalan desde los repositorios Debian; su resolución no está congelada.
MongoDB y Neo4j tienen volúmenes persistentes por proyecto. Los límites son 1 GiB
y 1.5 GiB respectivamente, más el proceso de desarrollo y el sistema anfitrión.
Un solo miembro permite transacciones; no proporciona alta disponibilidad.

Los puertos se publican solo en `127.0.0.1`. MongoDB no tiene autenticación en este
entorno de desarrollo; Neo4j sí. Browser está en `http://localhost:7474`, con usuario
`neo4j` y el secreto local de `.env`. Cambiar ese archivo no rota la contraseña de
un volumen Neo4j existente. No exponer MongoDB mediante un puerto público.

Desde el host, `MONGO_URI` incluye `directConnection=true`: el miembro anuncia
`mongodb:27017`, nombre que solo resuelve dentro de la red Compose. Dentro del
devcontainer se usa `mongodb://mongodb:27017/?replicaSet=rs0` con descubrimiento.

```bash
# Comprobaciones independientes; MongoDB no requiere credenciales de Neo4j.
uv run --locked --env-file .env farmared salud --motor mongo
uv run --locked --env-file .env farmared salud --motor neo4j
# Detener conservando los volúmenes:
docker compose --env-file .env -f infra/docker-compose.yml down
```

`salud` devuelve JSON y código 0 solo si están listos los motores seleccionados;
si alguno falla, informa cada resultado y devuelve 1. Siempre declara la proyección
`no_comprobada`: disponibilidad no implica sincronización del grafo.

## Codespaces y Dev Containers

Crear el Codespace desde esta rama o usar **Reopen in Container**. La configuración
`.devcontainer/devcontainer.json` ejecuta el preparador local, construye el servicio
`dev`, espera inicializador exitoso y ambos motores saludables, y ejecuta
`uv sync --locked` seguido de `farmared salud`. Dentro, trabajar en
`/workspaces/farmared` y ejecutar `uv run --locked pytest` o `uv run --locked farmared salud`.
No hace falta cargar `.env` otra vez: el servicio recibe las URI internas.

El entorno Python vive en el volumen `/opt/farmared-venv`, separado de `.venv` del
host para evitar mezclar binarios macOS/Linux. Cerrar el devcontainer detiene Compose
conservando volúmenes. Solo se solicita reenviar Browser; conservar su visibilidad
privada. La validación local con la CLI oficial está en la evidencia de la parte 2;
la ejecución alojada en GitHub Codespaces debe comprobarse allí por separado.

## Pruebas de infraestructura y aislamiento

```bash
# Sin requerir motores: omite explícitamente las pruebas de integración.
uv run --locked pytest
# Solo MongoDB: esquema real, sin requerir Neo4j.
FARMARED_TEST_MONGO=1 uv run --locked --env-file .env pytest
# Con los motores seleccionados en .env:
FARMARED_TEST_INTEGRACION=1 uv run --locked --env-file .env pytest
```

La integración usa MongoDB real con bases `farmared_test_a_infra_<UUID>` y
`farmared_test_a_esquema_<UUID>`, y comprueba commit/rollback, BSON Date, validadores,
unicidad, idempotencia del esquema y rechazo de conflictos. Neo4j usa un nodo temporal
`AInfraPrueba` con ID aleatorio para verificar rollback. La limpieza se limita a
esas bases/IDs; no llama a reset de demo ni borra entidades de negocio.

Si se comparte un host, usar un `COMPOSE_PROJECT_NAME` distinto y otros
`MONGO_PORT`, `NEO4J_HTTP_PORT`, `NEO4J_BOLT_PORT`; actualizar también las URI del
host en `.env` para esos puertos. Los nombres de servicio y puertos internos no
cambian. No reutilizar volúmenes/bases de demo mutables entre integrantes.

## Datos disponibles y secuencia de entregas

Se encontraron los nueve CSV en `datasets_farmared/`, directorio ignorado previamente.
Se inspeccionaron cabeceras, enums y conteos (8 clientes, 5 sucursales, 7 farmacéuticos,
5 proveedores, 13 productos, 18 lotes, 9 recetas, 16 ventas y 22 detalles).
Esto **no** constituye validación integral ni una carga. Los originales permanecen
intactos. Su incorporación versionada en `data/originales/` queda para la entrega
de datasets, junto con referencias, importes, totales y diagnósticos de filas.

1. Paquete, contratos, configuración, reloj y CLI mínima: implementado.
2. Compose/devcontainer, conexiones y readiness con primario real: implementado.
3. Colecciones, validadores e índices base MongoDB: implementado.
4. Lectura, conversión y validación integral de los nueve CSV.
5. Carga idempotente, manifiesto/huellas, historia y outbox transaccional.
6. Adicionales reproducibles con `base_date` persistida y casos borde.
7. Integración disponible de B/C/D, CI, evidencias, diagramas y ensamblado del informe.
