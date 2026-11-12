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
Se incluyen los drivers oficiales de MongoDB y Neo4j, pero la CLI solo
importa el handler seleccionado y no importa drivers ni abre conexiones al arrancar.
Las versiones se verificaron en [PyPI: PyMongo](https://pypi.org/project/pymongo/4.19.0/),
[Neo4j](https://pypi.org/project/neo4j/6.4.1/) y [pytest](https://pypi.org/project/pytest/9.2.0/).

`estado` informa versión y reloj, con motores/proyección **no comprobados**.
Las consultas `q01`, `q02`, `q05`, `q06`, `q07`, `q08`, `q09`, `q11` y `q12`
leen datos de MongoDB; `q13` administra clientes y `q14`/`q15` operan ventas,
recetas y stock. Las consultas `q03`, `q04` y `q10` leen el grafo Neo4j.
`sync` actualiza ese grafo desde los eventos outbox y `demo-transaccion`
ejecuta escenarios de ventas con sus estados antes y después.
Los códigos de salida son 0 (éxito), 1 (error de dominio), 2 (uso inválido) y
3 (comando pendiente). Las fallas internas no se convierten en éxitos ni se
disfrazan como módulos pendientes.

## Consultas y servicios MongoDB

Con los motores disponibles y `.env` preparado, ejecutar desde la raíz del
repositorio para cargar una demo e inicializar los índices y la vista mensual:

```bash
uv run --locked --env-file .env farmared setup --solo-mongo --base farmared_demo_consultas --directorio data/originales --directorio data/adicionales
uv run --locked --env-file .env farmared preparar-mongo --base farmared_demo_consultas
```

Ejecutar primero las lecturas y después las operaciones que modifican datos.
Las consultas temporales usan el reloj real; los adicionales tienen fecha base
10/11/2026, por lo que sus resultados pueden cambiar con el día de ejecución.

- **q01:** productos activos con todos los datos del proveedor como objeto.
- **q02:** ventas pendientes con farmacéutico, matrícula, sucursal y total.
- **q05:** farmacéuticos activos y cantidad de ventas no anuladas en los últimos 60 días, incluidos ceros.
- **q06:** recetas prolongadas vigentes con próxima dispensa anterior a hoy y datos del cliente.
- **q07:** top cinco productos por unidades vendidas, solo ventas completadas.
- **q08:** lotes con menos de 50 unidades y datos completos de producto, proveedor y sucursal.
- **q09:** ventas de tipo `Venta libre` con total menor a $5000, excepto `Anulada`.
- **q11:** vista estándar de ingresos del mes actual por farmacéutico.
- **q12:** clientes sin ventas registradas en el último año, de cualquier estado.
- **q13:** alta, modificación de contacto/cobertura y baja lógica de clientes, con eventos outbox en la misma transacción.

q01 se ejecuta con:

```bash
uv run --locked --env-file .env farmared q01 --base farmared_demo_consultas
```

Devuelve cada producto activo completo con `proveedor` como objeto, sin ordenar.
Si la referencia no encuentra proveedor, conserva el producto y omite ese campo.
No exige que el proveedor esté activo.

q02 se ejecuta con:

```bash
uv run --locked --env-file .env farmared q02 --base farmared_demo_consultas
```

Devuelve las ventas `Pendiente` completas con `farmaceutico` y `sucursal` como
objetos. La sucursal se obtiene desde `farmaceutico.id_sucursal`. Conserva el
total original y los profesionales/sucursales inactivos. Si falta alguna referencia,
conserva la venta y omite el objeto que no se pudo encontrar. No ordena ni modifica datos.
Sus seis casos de prueba están en [test_q02.py](tests/c_mongo/test_q02.py) e
incluyen la ejecución real del comando CLI.

q05 se ejecuta con:

```bash
uv run --locked --env-file .env farmared preparar-mongo --base farmared_demo_consultas
uv run --locked --env-file .env farmared q05 --base farmared_demo_consultas
```

Devuelve los datos del farmacéutico activo y `cantidad_ventas`, sin ordenar.
Incluye 60 días comerciales de Buenos Aires contando hoy, excluye anuladas e
incluye pendientes. Cuenta dentro del `$lookup` y devuelve cero si no hay ventas.
`preparar-mongo` asegura el índice `ix_ventas_farmaceutico_fecha` sobre
`ventas(id_farmaceutico, fecha)`; ejecutar la preparación con escritores pausados.
La carga también asegura ese índice. q05 solo realiza lecturas.

q06 se ejecuta con:

```bash
uv run --locked --env-file .env farmared q06 --base farmared_demo_consultas
```

Usa el día actual de Buenos Aires. Excluye próximas dispensas nulas o previstas
para hoy. Devuelve la receta completa con `cliente` como objeto, sin ordenar.
Si no encuentra el cliente, conserva la receta sin ese campo; no filtra clientes inactivos.

q07 se ejecuta con:

```bash
uv run --locked --env-file .env farmared q07 --base farmared_demo_consultas
```

Suma las cantidades de `ventas.items` para ventas completadas y devuelve hasta
cinco productos, con `_id`, `unidades_vendidas` y el objeto `producto` completo.
Ordena por unidades descendentes y desempata por id ascendente. Incluye productos
inactivos; si el producto no existe, conserva el id y las unidades sin ese objeto.

q08 se ejecuta con:

```bash
uv run --locked --env-file .env farmared q08 --base farmared_demo_consultas
```

Devuelve el lote completo con `producto`, `proveedor` y `sucursal` como objetos,
sin ordenar ni proyectar campos. Incluye lotes con cero unidades y vencidos;
conserva lotes con referencias inexistentes, omitiendo los objetos no encontrados.

Con MongoDB cargado, ejecutar:

```bash
uv run --locked --env-file .env farmared q09 --base farmared_demo_consultas
```

Devuelve JSON con `consulta`, `base` y `resultados`: documentos completos,
sin orden garantizado. Incluye pendientes; $5000 queda excluido. Usa
`estado: {"$ne": "Anulada"}` para admitir otros estados si el esquema se amplía.
El esquema actual sigue permitiendo solo `Completada`, `Pendiente` y `Anulada`.
No requiere Neo4j ni sincronización.

q11 se prepara y ejecuta con:

```bash
uv run --locked --env-file .env farmared preparar-mongo --base farmared_demo_consultas
uv run --locked --env-file .env farmared q11 --base farmared_demo_consultas
```

La preparación, con escritores pausados, asegura el índice `ix_ventas_estado_fecha`
y la vista `ingresos_mensuales_farmaceutico`. La vista calcula el mes en cada lectura
con `$$NOW` de MongoDB y la zona de Buenos Aires; suma `total` una vez por venta
completada. Devuelve `_id`, `ingresos_totales` y `farmaceutico` como objeto, sin
ordenar. Incluye profesionales inactivos con ventas y omite los que no tienen
ventas completadas del mes. Si falta la vista, q11 informa que debe prepararse.
`setup --solo-mongo` prepara el esquema base y carga los datos; ejecutar
`preparar-mongo` para inicializar también la vista de ingresos mensuales.

q12 se ejecuta con:

```bash
uv run --locked --env-file .env farmared preparar-mongo --base farmared_demo_consultas
uv run --locked --env-file .env farmared q12 --base farmared_demo_consultas
```

Devuelve los clientes completos sin ventas desde el inicio del día equivalente
del año anterior hasta el inicio de mañana, según Buenos Aires. El 29 de febrero
se ajusta al 28 de febrero del año anterior. Cualquier estado de venta cuenta,
incluido `Anulada`, y se consideran clientes activos e inactivos. Usa un `$lookup`
limitado a una coincidencia, sin ordenar. La preparación asegura el índice
`ix_ventas_cliente_fecha`; requiere escritores pausados. La consulta solo lee.

q13 se ejecuta con estas acciones, sobre una base preparada:

```bash
uv run --locked --env-file .env farmared q13 --base farmared_demo_consultas alta --datos docs/ejemplos/q13_alta_cliente.json
uv run --locked --env-file .env farmared q13 --base farmared_demo_consultas modificar --id-cliente ID --datos docs/ejemplos/q13_cambios_cliente.json
uv run --locked --env-file .env farmared q13 --base farmared_demo_consultas baja --id-cliente ID
```

Reemplazar `ID` por `documento._id` de la salida del alta. `--datos -` permite
leer el objeto JSON desde stdin en alta y modificación. `--base` va antes de la
acción. Los ejemplos son datos ficticios; repetir el alta con el mismo DNI se rechaza.

La salida contiene `operacion`, `accion`, `base`, `documento`, `eventos`,
`reutilizada` y `proyeccion`. Si hubo cambios, indica `pendiente_sync`; si no hubo
cambios, indica `no_comprobada`, sin afirmar que el grafo esté actualizado.
Las modificaciones equivalentes y bajas repetidas no generan eventos nuevos.
JSON inválido/ilegible produce código 1 antes de conectar; argumentos inválidos,
código 2. Los errores de negocio van a stderr con código 1; el éxito devuelve JSON
y código 0. El adaptador cierra la conexión incluso ante errores del servicio.

Pruebas de q13 con MongoDB preparado:

```bash
FARMARED_TEST_MONGO=1 uv run --locked --env-file .env pytest tests/c_mongo/test_q13*.py
```

El alta exige `nombre`, `apellido`, `dni`, `ciudad`, `provincia` y `obra_social`.
El servicio genera el UUID y establece `activo=true`. El DNI se recibe como string
de dígitos y es único incluso si el cliente existente está inactivo. `email` y
`telefono` son opcionales. `Sin cobertura` exige `nro_afiliado=null`; las demás
coberturas requieren un afiliado no vacío.

La modificación admite únicamente `email`, `telefono`, `ciudad`, `provincia`,
`obra_social` y `nro_afiliado`. Los campos omitidos se conservan y la cobertura
se valida sobre el documento resultante. La baja cambia únicamente `activo=false`
y preserva ventas y recetas. Cada cambio efectivo confirma el cliente y su
evento outbox en una misma transacción MongoDB; la proyección se actualiza luego
con `sync`.

Para comprobar q13 manualmente, revisar el cliente y sus eventos antes y después
de cada acción. Repetir el alta debe rechazar el DNI duplicado sin escrituras;
repetir la misma modificación o baja debe devolver reutilización sin evento nuevo.

Para repetir el recorrido completo de q13, Docker debe estar activo y las imágenes
fijadas en `infra/docker-compose.yml` deben estar descargadas. Esta prueba crea
sus propios contenedores MongoDB/Neo4j, bases y credenciales temporales; los elimina
al terminar y no utiliza los motores configurados en `.env`:

```bash
FARMARED_TEST_SYNC=1 FARMARED_EVIDENCIAS_C=/tmp/farmared-q13-evidencias uv run --locked pytest tests/d_grafo/test_q13_integracion.py -q
```

`FARMARED_EVIDENCIAS_C` es opcional: si se define, guarda el recorrido como JSON.

Pruebas de consultas MongoDB y clientes:

```bash
uv run --locked pytest tests/c_mongo
FARMARED_TEST_MONGO=1 uv run --locked --env-file .env pytest tests/c_mongo
```

La verificación conjunta ejecutó estas pruebas y el recorrido de q13 con Neo4j:
**107 aprobadas, 0 fallidas y
0 omitidas**, incluyendo 68 integraciones con motores reales. No fue necesario
modificar consultas ni tests. Esta selección no equivale a ejecutar toda la suite
del repositorio.

Los cuarenta y cinco casos de lectura requieren MongoDB real y se omiten si no se activa
una de las opciones de integración. q01 cubre productos inactivos, referencia a
proveedor inexistente y producto activo con proveedor completo. q02 cubre ventas
pendientes, otros estados, profesionales/sucursales inactivos, referencias
inexistentes y ausencia de ventas; también verifica la CLI real. q05 cubre conteos
por profesional, cero ventas, inactivos, fechas frontera, estados y cambio de día
en Buenos Aires. q06 cubre el caso
exitoso, dispensa prevista para hoy, estado no vigente, cliente inexistente y tipo
distinto de tratamiento prolongado. q07 cubre el ranking, estados excluidos,
ausencia de ventas, líneas repetidas, empates y productos inexistentes.
q08 cubre lotes de 60 unidades, resultados
completos y referencias inexistentes. El esquema impide insertar unidades negativas,
por lo que no se agrega un caso con −3 unidades. q09 cubre ventas
que cumplen las condiciones, ventas con receta, total igual a $5000 y ventas anuladas.
q11 cubre la vista real, totales sin duplicación por ítems, estados, límites del
mes, cambio de año, febrero bisiesto, profesionales inactivos y ausencia de ingresos.
Sus fronteras usan un pipeline equivalente con reloj fijo, sin cambiar la vista.
q12 cubre clientes sin ventas o con ventas antiguas, límites del período, todos
los estados, referencias inexistentes y el ajuste del 29 de febrero.

Ver el [informe de consultas y clientes](docs/informe/c_consultas_y_clientes.md)
para el contrato, casos de prueba y estado de verificación de las consultas.

## Configuración y contratos

Copiar `.env.example` a `.env` cuando se necesite configuración local. No contiene
credenciales reales; `NEO4J_PASSWORD` queda vacío hasta configurar el motor.
`Config.from_env()` lee `MONGO_URI`, `MONGO_DB`, `NEO4J_URI`, `NEO4J_USER`,
`NEO4J_PASSWORD` y `DB_TIMEOUT_MS` (1–300000, por defecto 10000).
Los nombres de base tienen un máximo de 63 bytes UTF-8. No abre conexiones ni
lee `.env` automáticamente. Para cargarlo con uv:

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
- `farmared.errores.ErrorDominio(codigo, mensaje)`: campos públicos y códigos de error de la aplicación.
- `farmared.contratos`: nombres de colecciones, enums literales y formas de outbox
  y retornos de escritura. `TypedDict` documenta estructura; no valida persistencia.
- `validar_importe_ars`: entero ARS entre 0 y `2**63-1`, rechaza floats y booleanos.
  Aplicar también a resultados de sumas/productos antes de persistir. No convierte CSV.
- IDs, DNI, CUIT y teléfonos permanecen strings; los detalles se almacenan en `ventas.items`.

`obtener_mongo(config)` devuelve un `Database` PyMongo después de verificar replica
set, sesiones y primario; usa fechas conscientes de zona UTC y write concern
`majority`. El llamador inicia sesiones con `db.client.start_session()` y cierra
`db.client.close()` al terminar. `obtener_neo4j(config)` devuelve un `Driver` con
autenticación y conectividad verificadas; el llamador lo cierra o usa `with`.
Ninguna función conecta al otro motor, crea esquema, carga datos o sincroniza.
Los errores de conexión usan `ErrorDominio("CONEXION", mensaje)` sin imprimir URI
ni credenciales. `preparar_mongo_base(db)` ya está disponible en
`farmared.esquema.base_mongo`. `cargar_mongo(db, rutas)` está disponible en
`farmared.carga.mongo`; devuelve manifiesto, eventos nuevos y marca de reutilización.

## Esquema MongoDB base

Con MongoDB listo y **escritores pausados**, preparar un destino explícito:

```bash
uv run --locked --env-file .env farmared preparar-mongo --base farmared
```

Se crean/aseguran ocho colecciones de negocio y `outbox`, validadores `strict/error`
e índices comunes: DNI y matrícula únicos globales, FEFO, cola outbox y consultas
por profesional/cliente y fecha. También se invoca `preparar_consultas_mongo(db)`
para el índice por estado/fecha y la vista mensual de q11. No carga CSV, ejecuta
servicios ni sincroniza. `setup` completo sigue pendiente de integración.
En bases existentes verifica documentos/índices antes del DDL, preserva datos y
rechaza definiciones incompatibles sin reemplazarlas. El DDL no es atómico entre
colecciones y requiere escritores pausados; ante una falla no se anuncia éxito.


## Validación de datasets sin motores

```bash
uv run --locked farmared validar-datasets --directorio data/originales
```

Valida los nueve CSV y devuelve JSON con conteos, errores, avisos y SHA-256 de
fuentes/conjunto. Código 0 significa sin errores bloqueantes; los avisos históricos
siguen visibles. Código 1 significa validación fallida, sin datos parciales para
cargar. No necesita `.env`, MongoDB ni Neo4j, y no realiza escrituras.

`--directorio` es repetible para validar originales y adicionales como una unión.

## Carga MongoDB idempotente

Con el replica set listo, desde la raíz y con escritores pausados en el bootstrap:

```bash
uv run --locked --env-file .env farmared seed --base farmared --directorio data/originales
```

La primera carga exige vacías las colecciones de negocio/outbox y confirma juntos
81 documentos, 58 eventos iniciales y un manifiesto técnico. Embebe detalles,
preserva precios/marcas históricas y no reproduce descuentos ni dispensas.
Repetir verifica huella e identidades sin restaurar stock, recetas o eventos ya
procesados. Fuente distinta, destino ajeno o carga dañada producen conflicto/error.

## Adicionales reproducibles y casos borde

`data/adicionales/` incluye los nueve CSV propios y un manifiesto con fecha base
**2026-11-10**, IDs `A-`, hashes y catorce escenarios. Verificar/reutilizar:

```bash
uv run --locked farmared generar-adicionales --directorio data/adicionales
uv run --locked farmared validar-datasets --directorio data/originales --directorio data/adicionales
uv run --locked --env-file .env farmared seed --base farmared_completo --directorio data/originales --directorio data/adicionales
```

La unión aporta **169 documentos de negocio, 120 eventos iniciales y un manifiesto**;
cada colección de negocio tiene al menos diez entidades nuevas. Los 38 detalles
se embeben en las 28 ventas. El seed usa la fecha persistida de generación aunque
se ejecute otro día; no mueve escenarios ni restaura valores operacionales.

Para generar casos relativos al día actual, elegir un **directorio nuevo**:
`uv run --locked farmared generar-adicionales --directorio data/adicionales_hoy`.
`--base-date YYYY-MM-DD` permite una fecha deliberada. No se sobrescribe un destino
existente ni se actualiza una base ya cargada con otras fuentes. La fecha del
manifiesto debe usarse con `FixedClock` al verificar estos casos en las pruebas
de ventas, consultas y proyección.

## Setup disponible y reset explícito de demo

`setup --solo-mongo` prepara la carga MongoDB: valida fuentes antes de conectar,
asegura esquema/índices mediante el loader y carga o reutiliza el manifiesto.
Devuelve `setup=mongo_listo`; no inicializa la vista q11 ni prepara o sincroniza
el grafo. Esos pasos se ejecutan con `preparar-mongo`, `grafo-init` y `sync`.
El setup completo, sin esa opción, termina con código 3 y lista esas
interfaces antes de abrir conexiones o escribir.

```bash
uv run --locked --env-file .env farmared setup --solo-mongo --base farmared_demo_equipo --directorio data/originales --directorio data/adicionales
uv run --locked --env-file .env farmared reset-demo --solo-mongo --base farmared_demo_equipo
uv run --locked --env-file .env farmared reset-demo --solo-mongo --base farmared_demo_equipo --confirmar-base farmared_demo_equipo
```

Reset admite únicamente `farmared_demo_` más un sufijo, exige coincidencia exacta
de la confirmación y anuncia el destino en stderr antes de borrar la base completa.
No regenera archivos, recarga datos ni elimina Neo4j o volúmenes. Después de un
reset, volver a ejecutar setup es una carga nueva; el grafo requiere reconstrucción
con `grafo-rebuild` antes de usarlo para lecturas exactas.



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
`farmared_test_a_esquema_<UUID>` y `farmared_test_a_loader_<UUID>`, y comprueba
commit/rollback, BSON Date, validadores, unicidad, carga repetible y conflictos de
fuente/manifiesto. Neo4j usa un nodo temporal
`AInfraPrueba` con ID aleatorio para verificar rollback. La limpieza se limita a
esas bases/IDs; no llama a reset de demo ni borra entidades de negocio.

Si se comparte un host, usar un `COMPOSE_PROJECT_NAME` distinto y otros
`MONGO_PORT`, `NEO4J_HTTP_PORT`, `NEO4J_BOLT_PORT`; actualizar también las URI del
host en `.env` para esos puertos. Los nombres de servicio y puertos internos no
cambian. No reutilizar volúmenes/bases de demo mutables entre entornos de prueba.

