# Persona C: consultas MongoDB y clientes

## Avance

- [x] q01: función, comando CLI y tres pruebas agregadas; contrato documentado aquí.
- [x] q02: función, comando CLI y seis pruebas aprobadas con MongoDB real;
  [evidencia](../evidencias/c/q02.md).
- [x] q05: función, comando CLI, índice y seis pruebas agregadas; contrato documentado aquí.
- [x] q06: función, comando CLI y cinco pruebas agregadas; contrato documentado aquí.
- [x] q07: función, comando CLI y seis pruebas agregadas; contrato documentado aquí.
- [x] q08: función, comando CLI y tres pruebas agregadas; contrato documentado aquí.
- [x] q09: función documentada, comando CLI y pruebas agregadas.
- [x] q11: vista estándar, inicializador, comando CLI y seis pruebas agregadas.
- [x] q12: función, comando CLI, índice y seis pruebas agregadas; contrato documentado aquí.
- [x] q13: ABM, CLI, pruebas y evidencia de sincronización completadas.
- [x] q13, etapa 1: interfaces, DTOs y [contrato detallado](../contratos/q13_clientes.md).
- [x] q13, etapa 2: normalización y validación puras, preparación del documento de alta;
  22 pruebas nuevas y 4 de contrato aprobadas sin motores.
  Las operaciones completas de escritura se completaron en la etapa 4 y la CLI en la etapa 6.
- [x] q13, etapa 3: unidad transaccional y outbox implementados, con 8 pruebas
  unitarias nuevas y 6 integraciones reales; 40 pruebas de q13 aprobadas en total.
- [x] q13, cierre de etapa 3: commit/rollback verificados en MongoDB 8.0.15;
  [evidencia](../evidencias/c/q13_etapa3.md).
- [x] q13, etapa 4: alta, modificación y baja implementadas y verificadas;
  52 pruebas aprobadas en total, con 18 integraciones reales.
  [Evidencia](../evidencias/c/q13_etapa4.md).
- [x] q13, etapa 5: tres tests nuevos de concurrencia e independencia de Neo4j;
  55 pruebas aprobadas en total, con 21 integraciones reales.
  [Evidencia](../evidencias/c/q13_etapa5.md).
- [x] q13, etapa 6: CLI con alta/modificación/baja, archivo JSON o stdin, errores y cierre;
  61 pruebas aprobadas (22 integraciones reales) y regresiones con 93 aprobadas y 5 omitidas.
  [Evidencia](../evidencias/c/q13_etapa6.md).
- [x] q13, etapa 7: evidencia de antes/después, rechazo sin efectos y sync real
  con historial conservado. Cierre: 433 aprobadas, 0 fallidas, 0 omitidas
  (62 de q13 y 371 regresiones seleccionadas).
  [Evidencia](../evidencias/c/q13_etapa7.md).
- [x] Inicializador de índices y vista q11, integrado a `preparar-mongo`.
- [x] Ejecutar las pruebas de las diez consultas de C con motores reales y
  conservar el registro: **107 aprobadas, 0 fallidas y 0 omitidas**.
  [Verificación conjunta](../evidencias/c/pruebas_consultas_c.md): incluye las
  45 pruebas de lectura, las 61 de q13 y su recorrido con Neo4j.

## q01 — Productos activos con todos los datos de su proveedor

**Motor:** MongoDB. **Función:** `q01_productos_activos(db)` en
`src/farmared/consultas/q01.py`. Recibe un `Database` de PyMongo y devuelve una
lista de productos completos con el proveedor completo como objeto en `proveedor`.
No ordena, no modifica datos y no cierra el cliente del llamador.

El pipeline filtra `productos.activo = true`, relaciona `id_proveedor` con
`proveedores._id` mediante `$lookup` y convierte el arreglo en objeto con `$unwind`.
Se utiliza `preserveNullAndEmptyArrays: true`: si el id no corresponde a un
proveedor existente, el producto se conserva sin el campo `proveedor`.
No se filtra por actividad del proveedor. Sin productos activos devuelve `[]`.

```bash
uv run --locked --env-file .env farmared q01 --base farmared_demo_c
```

`tests/c_mongo/test_q01.py` contiene exactamente tres casos:

1. Productos inactivos: devuelve una lista vacía.
2. Producto activo con id de proveedor inexistente: devuelve el producto sin `proveedor`.
3. Producto activo con proveedor válido: devuelve ambos documentos completos;
   el proveedor del caso está inactivo para comprobar que se conserva igualmente.

Las pruebas usan bases aisladas `farmared_test_c_q01_<UUID>`, con limpieza al
finalizar. Los tres casos se aprobaron con MongoDB real en la
[verificación conjunta](../evidencias/c/pruebas_consultas_c.md). Para repetirlos:

```bash
FARMARED_TEST_MONGO=1 uv run --locked --env-file .env pytest tests/c_mongo/test_q01.py
```

## q02 — Ventas pendientes con farmacéutico y sucursal

**Motor:** MongoDB. **Función:** `q02_ventas_pendientes(db)` en
`src/farmared/consultas/q02.py`. Recibe un `Database` PyMongo y retorna una lista
de ventas completas en estado `Pendiente`, con los objetos completos
`farmaceutico` y `sucursal`. El profesional contiene nombre, apellido y matrícula;
`total` conserva el importe original de la venta. No ordena, no proyecta campos,
no escribe documentos ni cierra la conexión del llamador. Propaga errores del motor.

El pipeline aplica `$match` a `estado`, relaciona `ventas.id_farmaceutico` con
`farmaceuticos._id` y luego `farmaceutico.id_sucursal` con `sucursales._id`.
Ambos `$unwind` usan `preserveNullAndEmptyArrays: true`. Si falta el profesional,
la venta se conserva sin los dos objetos; si falta su sucursal, se conserva con
el profesional y sin el objeto `sucursal`. El campo `ventas.id_sucursal` permanece
intacto, mientras que el objeto agregado corresponde a la sucursal actual del
profesional asignado. No se filtra por actividad del profesional o la sucursal.
Sin ventas pendientes devuelve `[]`.

```bash
uv run --locked --env-file .env farmared q02 --base farmared_demo_c
FARMARED_TEST_MONGO=1 uv run --locked --env-file .env pytest tests/c_mongo/test_q02.py
```

La CLI presenta `consulta`, `base` y `resultados`, con fechas ISO 8601.
`tests/c_mongo/test_q02.py` contiene exactamente seis casos:

1. Venta pendiente con profesional, matrícula, sucursal y total correctos; ejecuta
   también la CLI real y comprueba que no hubo escrituras. La sucursal del
   profesional difiere del id de sucursal guardado en la venta.
2. Ventas completadas y anuladas excluidas.
3. Profesional y sucursal inactivos conservados.
4. Profesional inexistente: la venta se conserva sin objetos relacionados.
5. Sucursal del profesional inexistente: conserva la venta y el profesional.
6. Colección de ventas vacía: devuelve `[]`.

Se aprobaron los seis casos sobre MongoDB 8.0.15, en bases aisladas
`farmared_test_c_q02_<UUID>` eliminadas al finalizar. También pasaron las
40 regresiones seleccionadas de CLI/base y CLI de clientes. Ver la
[evidencia y el ejemplo comprobado](../evidencias/c/q02.md).

## q05 — Farmacéuticos activos y cantidad de ventas en los últimos 60 días

**Motor:** MongoDB. **Función:** `q05_ventas_por_farmaceutico(db, clock)` en
`src/farmared/consultas/q05.py`. Recibe un `Database` de PyMongo y el reloj común.
Devuelve los documentos completos de los profesionales activos con el campo
`cantidad_ventas`, incluido cero. No ordena, no modifica datos ni cierra la conexión.

Parte de `farmaceuticos` y relaciona `_id` con `ventas.id_farmaceutico`. El pipeline
del `$lookup` filtra fechas en `[inicio(hoy-59), inicio(mañana))` usando Buenos Aires
y excluye `Anulada`. Cuenta documentos de venta con `$count`, de modo que el arreglo
de resultados contiene como máximo un contador. Las pendientes cuentan; las unidades
de los ítems no intervienen. `$set` extrae el contador con `$arrayElemAt`, usa
`$ifNull` para el cero y `$unset` elimina el arreglo temporal.

El esquema base declara `ix_ventas_farmaceutico_fecha` en
`ventas(id_farmaceutico, fecha)`. Se asegura durante `preparar-mongo` y la carga,
aprovechando la preparación idempotente existente. q05 no crea índices al consultar.
Su utilización y rendimiento deben verificarse con `explain` sobre MongoDB real;
no se afirma un plan medido en esta ejecución.

```bash
uv run --locked --env-file .env farmared preparar-mongo --base farmared_demo_c
uv run --locked --env-file .env farmared q05 --base farmared_demo_c
```

La preparación requiere escritores pausados. Los tests utilizan `FixedClock` y
bases aisladas `farmared_test_c_q05_<UUID>`, que se eliminan al terminar.
`tests/c_mongo/test_q05.py` contiene seis casos:

1. Conteos correctos por profesional, sin sumar cantidades de productos; verifica el índice.
2. Profesional sin ventas propias: aparece con cero, aunque existan ventas de otro id.
3. Profesional inactivo con ventas: queda excluido.
4. Límites del período: incluye hoy-59 y hoy; excluye hoy-60 y mañana.
5. Incluye completadas y pendientes; excluye anuladas.
6. Usa el día de Buenos Aires cuando la fecha UTC ya pasó a mañana.

Los seis casos se aprobaron con MongoDB real en la
[verificación conjunta](../evidencias/c/pruebas_consultas_c.md).
La inspección de `explain` no forma parte de esas pruebas. Para repetirlas:

```bash
FARMARED_TEST_MONGO=1 uv run --locked --env-file .env pytest tests/c_mongo/test_q05.py
```

## q06 — Recetas prolongadas vigentes con dispensa anterior a hoy

**Motor:** MongoDB. **Función:** `q06_recetas_prolongadas(db, clock)` en
`src/farmared/consultas/q06.py`. Recibe un `Database` de PyMongo y un reloj del
contrato común. Retorna recetas completas con el cliente completo como objeto
en `cliente`, sin ordenamiento ni proyección de campos.

Filtra por `tipo = Tratamiento prolongado`, `estado = Vigente` y fecha de próxima
dispensa estrictamente anterior al inicio del día actual en Buenos Aires.
`$type: date` excluye valores nulos, ausentes o que no sean fechas BSON. La CLI
usa `SystemClock`; las pruebas usan `FixedClock` para reproducir las fronteras.

El `$lookup` relaciona `recetas.id_cliente` con `clientes._id`. El `$unwind` usa
`preserveNullAndEmptyArrays: true`: si no existe ese cliente, conserva la receta
sin el campo `cliente`. No filtra clientes por actividad. No modifica documentos
ni cierra la conexión recibida; sin coincidencias devuelve `[]`.

```bash
uv run --locked --env-file .env farmared q06 --base farmared_demo_c
```

`tests/c_mongo/test_q06.py` contiene cinco casos:

1. Devuelve la receta que cumple las condiciones con el cliente completo, incluso
   si está inactivo. Una segunda receta con próxima dispensa nula queda excluida.
2. Excluye una receta cuya próxima dispensa es el mismo día de la consulta.
3. Excluye una receta que no está vigente.
4. Conserva una receta con id de cliente inexistente sin el campo `cliente`.
5. Excluye una receta que no es de tratamiento prolongado.

Cada caso usa una base aislada `farmared_test_c_q06_<UUID>` que se elimina al
finalizar. Los cinco casos se aprobaron con MongoDB real en la
[verificación conjunta](../evidencias/c/pruebas_consultas_c.md). Para repetirlos:

```bash
FARMARED_TEST_MONGO=1 uv run --locked --env-file .env pytest tests/c_mongo/test_q06.py
```

## q07 — Top cinco productos por unidades vendidas

**Motor:** MongoDB. **Función:** `q07_top_productos(db)` en
`src/farmared/consultas/q07.py`. Recibe un `Database` de PyMongo y devuelve hasta
cinco documentos con `_id` (id del producto), `unidades_vendidas` y `producto`
(documento completo del catálogo). No modifica datos ni cierra la conexión.

Filtra ventas `Completada`, desarma `items` con `$unwind`, agrupa por
`items.id_producto` y suma `items.cantidad`. Ordena por unidades descendentes e id
ascendente para desempatar. Aplica `$limit: 5` antes del `$lookup` a `productos`,
evitando buscar datos del catálogo para todo el ranking. No utiliza `$project`.

Se incluyen productos actualmente inactivos. El `$unwind` final conserva el
resultado si falta el producto del catálogo, omitiendo el objeto `producto`.
Con menos de cinco productos devuelve los disponibles y sin ventas devuelve `[]`.

```bash
uv run --locked --env-file .env farmared q07 --base farmared_demo_c
```

`tests/c_mongo/test_q07.py` contiene seis pruebas:

1. Ranking correcto con más de cinco productos y datos completos; incluye uno inactivo.
2. Las ventas pendientes y anuladas no suman unidades.
3. Sin ventas, el resultado es una lista vacía aunque haya catálogo.
4. Las líneas repetidas del mismo producto y las distintas ventas suman cantidades.
5. Seis productos empatados se desempatan por id y solo se devuelven cinco.
6. Una venta cuyo producto no existe conserva el id y sus unidades.

Los casos que no cumplen filtros se excluyen; la consulta no los trata como errores
de escritura. Cada test usa una base aislada `farmared_test_c_q07_<UUID>` con limpieza
al finalizar. Los seis casos se aprobaron con MongoDB real en la
[verificación conjunta](../evidencias/c/pruebas_consultas_c.md). Para repetirlos:

```bash
FARMARED_TEST_MONGO=1 uv run --locked --env-file .env pytest tests/c_mongo/test_q07.py
```

## q08 — Lotes con menos de 50 unidades

**Motor:** MongoDB. **Función:** `q08_lotes_stock_bajo(db)` en
`src/farmared/consultas/q08.py`. Recibe un `Database` de PyMongo y retorna los
lotes completos con `producto`, `proveedor` y `sucursal` como objetos completos.
No ordena ni utiliza `$project`. No modifica documentos ni cierra la conexión.

El pipeline filtra `unidades < 50` y realiza tres `$lookup`: `id_producto` contra
`productos._id`, `producto.id_proveedor` contra `proveedores._id` e `id_sucursal`
contra `sucursales._id`. Cada relación usa `$unwind` con
`preserveNullAndEmptyArrays: true`, conservando el lote si faltan referencias y
omitiendo los objetos no encontrados. Incluye cero unidades, lotes vencidos y
entidades relacionadas inactivas. Sin coincidencias retorna `[]`.

```bash
uv run --locked --env-file .env farmared q08 --base farmared_demo_c
```

`tests/c_mongo/test_q08.py` contiene tres pruebas:

1. Excluye un lote de 60 unidades con referencias válidas.
2. Devuelve lotes de 49 y 0 unidades con sus tres documentos relacionados
   completos; los lotes están vencidos y las entidades relacionadas inactivas.
3. Conserva un lote con producto y sucursal inexistentes y otro cuyo producto
   existe pero apunta a un proveedor inexistente.

No se agrega el caso de −3 unidades: el esquema base define `unidades` como entero
con mínimo 0 y aplica validación `strict/error`, por lo que esa inserción se rechaza.

Cada prueba usa una base aislada `farmared_test_c_q08_<UUID>` que se elimina al
finalizar. Los tres casos se aprobaron con MongoDB real en la
[verificación conjunta](../evidencias/c/pruebas_consultas_c.md). Para repetirlos:

```bash
FARMARED_TEST_MONGO=1 uv run --locked --env-file .env pytest tests/c_mongo/test_q08.py
```

## q09 — Ventas libres menores a $5000, excepto anuladas

**Motor:** MongoDB. **Función:** `q09_ventas_libres(db)` en
`src/farmared/consultas/q09.py`.

Recibe un `Database` de PyMongo y retorna una lista de documentos de `ventas`
completos, sin orden garantizado. No modifica datos, no cierra el cliente
del llamador y propaga los errores del motor. Sin coincidencias devuelve `[]`.

```javascript
db.ventas.find({
  tipo: "Venta libre",
  total: { $lt: 5000 },
  estado: { $ne: "Anulada" }
})
```

El total es un entero ARS: 4999 entra y 5000 queda fuera. Se incluyen pendientes.
No se filtra por fecha ni por actividad actual del cliente o profesional. El
detalle ya está embebido; esta consulta no requiere relaciones ni `$lookup`.

La exclusión con `$ne` permite incorporar nuevos estados sin modificar el filtro.
Para admitirlos en producción será necesario migrar el enum del esquema común:
actualmente solo se aceptan `Completada`, `Pendiente` y `Anulada`. La presencia y
el tipo del campo `estado` también están exigidos por ese esquema.

### Ejecución

Los comandos de C se agrupan en `src/farmared/cli_mongo.py`, siguiendo el patrón
de `cli_ventas.py` y `cli_grafo.py`. El módulo expone `COMANDOS_MONGO`,
`registrar_comandos(subparsers)` y `ejecutar(args)`. `__main__.py` incorpora ese
grupo y delega el registro de argumentos; la lógica de q09 sigue en `consultas/q09.py`.

```bash
uv run --locked --env-file .env farmared q09 --base farmared_demo_c
```

La CLI muestra `{"consulta": "q09", "base": "farmared_demo_c", "resultados": [...]}`.
Las fechas BSON se presentan como texto ISO 8601 con zona horaria.

### Resultado esperado con originales y adicionales

Se calculó esta referencia desde los CSV validados, sin ejecutar la consulta
contra MongoDB. Corresponde al estado inicial de carga; operaciones posteriores
pueden modificarla. La función devuelve documentos completos; aquí se resumen
ordenados por id solo para facilitar la lectura de esta tabla:

| _id | total ARS | estado |
| --- | ---: | --- |
| A-V001 | 4999 | Completada |
| A-V003 | 4999 | Pendiente |
| A-V008 | 700 | Completada |
| A-V009 | 500 | Completada |
| A-V010 | 800 | Completada |
| V013 | 4400 | Completada |
| V014 | 4600 | Completada |

### Verificación

`tests/c_mongo/test_q09.py` contiene cuatro pruebas sobre MongoDB real:

1. Incluye ventas libres menores a $5000 no anuladas (completada y pendiente).
2. Excluye una venta de tipo `Con receta`, aunque cumpla las otras condiciones.
3. Excluye una venta con total exactamente igual a $5000.
4. Excluye una venta anulada, aunque cumpla las otras condiciones.

Se comparan los resultados sin exigir un orden: q09 no utiliza `sort`.

Resultado actualizado: **4 pruebas aprobadas con MongoDB real**, sin omisiones,
en la [verificación conjunta](../evidencias/c/pruebas_consultas_c.md).
Para repetir los cuatro casos con el entorno preparado:

```bash
FARMARED_TEST_MONGO=1 uv run --locked --env-file .env pytest tests/c_mongo/test_q09.py
```

Cada integración usa una base `farmared_test_c_q09_<UUID>` y elimina únicamente
esa base al finalizar; no utiliza el reset global ni requiere Neo4j.

## q12 — Clientes sin ventas registradas en el último año

**Motor:** MongoDB. **Función:** `q12_clientes_sin_ventas(db, clock)` en
`src/farmared/consultas/q12.py`. Recibe un `Database` de PyMongo y el reloj común.
Retorna documentos completos de clientes sin ventas dentro del período, sin
ordenamiento. Incluye clientes inactivos. No modifica datos ni cierra la conexión.

El período es `[inicio(día equivalente del año anterior), inicio(mañana))`, según
Buenos Aires. Si hoy es 29 de febrero, el inicio se ajusta al 28 de febrero del
año anterior. No equivale a restar siempre 365 días ni al año calendario actual.

El `$lookup` relaciona `clientes._id` con `ventas.id_cliente`, filtra por fecha y
limita el resultado a una coincidencia. Se incluyen todos los estados de venta:
una venta anulada reciente también excluye al cliente. El `$match` posterior
conserva arreglos sin primer elemento y `$unset` elimina el arreglo temporal.

El esquema base asegura `ix_ventas_cliente_fecha` en `ventas(id_cliente, fecha)`
durante la preparación y carga. La consulta no crea índices. Su plan de ejecución
debe verificarse con MongoDB real; no se midió con `explain` en esta ejecución.

```bash
uv run --locked --env-file .env farmared preparar-mongo --base farmared_demo_c
uv run --locked --env-file .env farmared q12 --base farmared_demo_c
```

La preparación requiere escritores pausados. `tests/c_mongo/test_q12.py` usa
`FixedClock` y bases aisladas `farmared_test_c_q12_<UUID>`, con seis casos:

1. Devuelve clientes sin ventas o con ventas antiguas, incluido un cliente inactivo,
   y excluye al cliente con venta reciente. También comprueba el índice.
2. Una venta exactamente al inicio anual cuenta; una del día anterior queda fuera.
3. Ventas de hoy cuentan y las de mañana no, usando el día de Buenos Aires cerca
   del cambio de fecha UTC.
4. Ventas completadas, pendientes y anuladas recientes excluyen a sus clientes.
5. Una venta de un id inexistente no excluye a otros clientes.
6. El 29/02/2024 toma 28/02/2023 como inicio, incluye ventas del 29/02/2024 y deja
   fuera las del 27/02/2023 y 01/03/2024.

Los seis casos se aprobaron con MongoDB real en la
[verificación conjunta](../evidencias/c/pruebas_consultas_c.md). Para repetirlos:

```bash
FARMARED_TEST_MONGO=1 uv run --locked --env-file .env pytest tests/c_mongo/test_q12.py
```

## q11 — Vista de ingresos mensuales por farmacéutico

**Motor:** MongoDB. **Función:** `q11_ingresos_mensuales(db)` en
`src/farmared/consultas/q11.py`. Recibe un `Database` de PyMongo y lee la vista
estándar `ingresos_mensuales_farmaceutico`. Retorna `_id` del profesional,
`ingresos_totales` y `farmaceutico` como objeto completo, sin ordenar. Si no se
encuentra la vista esperada, informa `INTEGRIDAD` e indica ejecutar la preparación.
No modifica documentos ni cierra la conexión del llamador.

`pipeline_ingresos_mensuales()` define la vista con `$$NOW`. El inicio mensual se
calcula con `$dateTrunc` y el siguiente mes con `$dateAdd`, ambos en Buenos Aires.
El filtro es `[inicio del mes, inicio del siguiente)`, solo para `Completada`.
Agrupa por `id_farmaceutico`, suma `total` una vez por venta y luego hace `$lookup`
a `farmaceuticos._id`. No desarma `items`, evitando duplicar los importes.
El `$unwind` conserva el ingreso si falta el profesional, sin el objeto relacionado.
Incluye profesionales inactivos y no agrega filas para quienes no tienen ventas
completadas del mes. Sin coincidencias devuelve `[]`.

`preparar_consultas_mongo(db)`, en `src/farmared/esquema/consultas_mongo.py`, asegura
el índice `ix_ventas_estado_fecha` y crea la vista. Repetirlo conserva una definición
idéntica; si cambia el pipeline de esa vista sobre `ventas`, lo actualiza con
`collMod`. Un nombre ocupado por una colección u otra vista de origen diferente
se rechaza sin reemplazarlo. La preparación requiere escritores pausados y no
forma parte de la lectura q11. El índice no implica que se haya medido su uso:
el plan debe comprobarse con `explain` sobre el motor real.

```bash
uv run --locked --env-file .env farmared preparar-mongo --base farmared_demo_c
uv run --locked --env-file .env farmared q11 --base farmared_demo_c
```

La integración completa del setup de A sigue pendiente: `setup --solo-mongo`
continúa siendo la carga de A y no inicializa esta vista. El comando explícito
`preparar-mongo` ya invoca el inicializador de C.

`tests/c_mongo/test_q11.py` contiene seis pruebas:

1. Vista estándar real, preparación repetida e índice: suma por profesional sin
   multiplicar totales de ventas con varios ítems. Usa el reloj del servidor.
2. Excluye ventas pendientes y anuladas.
3. Incluye el primer y último día del mes y excluye meses adyacentes, usando
   Buenos Aires cuando UTC ya está en el mes siguiente.
4. Respeta enero en un cambio de año y febrero de un año bisiesto.
5. Incluye profesionales inactivos con ingresos y omite profesionales sin ventas.
6. Sin completadas del mes devuelve una lista vacía.

Los casos 2 a 6 ejecutan el pipeline equivalente con un instante fijo en lugar de
`$$NOW`, sin alterar la definición de la vista. Son variantes de prueba, no una
vista que use fechas fijas. Cada test usa una base `farmared_test_c_q11_<UUID>`
con limpieza al finalizar. Los seis casos se aprobaron con MongoDB real en la
[verificación conjunta](../evidencias/c/pruebas_consultas_c.md).

```bash
FARMARED_TEST_MONGO=1 uv run --locked --env-file .env pytest tests/c_mongo/test_q11.py
```

## q13 — Alta, modificación y baja lógica de clientes

**Motor:** MongoDB, fuente de verdad. **Módulo:** `farmared.consultas.q13`.
Su propósito es administrar clientes conservando su identidad e historia,
con DNI único global incluso para clientes inactivos.

| Función | Parámetros de negocio | Efecto |
| --- | --- | --- |
| `q13_alta(db, datos, *, clock=None)` | Mapping con nombre, apellido, DNI, ciudad, provincia y cobertura; contacto opcional. | Genera UUID y crea el cliente con `activo=true`. |
| `q13_modificar(db, id_cliente, cambios, *, clock=None)` | Id string y parche de campos permitidos. | Cambia únicamente contacto, ubicación y cobertura. |
| `q13_baja(db, id_cliente, *, clock=None)` | Id string existente. | Cambia exclusivamente `activo=false`, sin borrar documentos ni historia. |

`db` es un `Database` PyMongo ya preparado en replica set; la API no crea índices
ni cierra la conexión del llamador. `clock` usa `SystemClock` por defecto y permite
inyectar `FixedClock` en pruebas. La CLI abre y cierra su conexión.

Las tres funciones devuelven `ResultadoEscritura`: documento completo confirmado,
lista de ids de eventos nuevos y `reutilizada`. Las modificaciones equivalentes y
bajas repetidas devuelven `eventos=[]` y `reutilizada=true`. Una nueva alta con un
DNI existente se rechaza, aunque se trate de un reintento del mismo pedido.

Se permiten parches de `email`, `telefono`, `ciudad`, `provincia`, `obra_social`
y `nro_afiliado`; se rechazan identidad, nombre, apellido, DNI, actividad,
metadatos y operadores MongoDB. Se permite modificar un cliente inactivo sin
reactivarlo. Los textos pierden espacios exteriores; los opcionales vacíos se
normalizan a `None`. Omitir un campo del parche lo conserva; enviarlo nulo pide
vaciarlo y solo se acepta si el campo permite nulos. El DNI es un string de
dígitos ASCII que conserva ceros iniciales. `Sin cobertura` exige afiliado nulo;
las demás obras sociales requieren afiliado no vacío. Se valida la combinación
resultante del parche, sin corregir silenciosamente el estado del cliente.

Cada cambio efectivo confirma cliente y evento outbox en una misma transacción
MongoDB, con lectura snapshot y escritura majority. El índice `uq_clientes_dni`
garantiza unicidad concurrente. UUID e instante del evento se mantienen estables
durante reintentos del driver; el callback vuelve a leer y validar el cliente.
Ante una conexión perdida puede haber commit incierto: se verifica el estado
confirmado antes de reenviar un alta. No se agregan claves de idempotencia.

Neo4j recibe la proyección después mediante `sync`. Un éxito del ABM no certifica
el grafo: la CLI indica `pendiente_sync` si emitió eventos y `no_comprobada` si
no hubo cambios. El consumidor relee el estado actual y proyecta los campos
definidos para `Cliente`: `id`, `nombre`, `apellido`, `activo`. Teléfono, email y
cobertura siguen en MongoDB. La baja conserva la venta, receta y sus relaciones.

Se usan los errores comunes `VALIDACION`, `DNI_DUPLICADO`, `NO_EXISTE`,
`CONFLICTO_ID`, `INTEGRIDAD` y `CONEXION`. Los rechazos probados no producen cambios;
un fallo de outbox revierte la escritura del cliente en la misma transacción.

La [evidencia de cierre](../evidencias/c/q13_etapa7.md) y sus
[capturas completas](../evidencias/c/q13_etapa7_recorrido.json) muestran alta,
modificación, rechazo por cobertura incoherente y baja, con antes/después en
MongoDB y proyección pendiente/verificada por separado. El historial q03 conserva
una receta y una venta tras la baja. Se usaron datos sintéticos en motores
temporales, sin sustituir la demostración del dataset completo del equipo.

Validación del cierre: **61 pruebas de q13 en MongoDB + 1 recorrido con Neo4j +
371 regresiones seleccionadas = 433 aprobadas, 0 fallidas y 0 omitidas**.
No se ejecutó toda la suite. q13 está terminada; q02 y el ensamblado del informe
general del equipo siguen fuera de este cierre. Ver el
[contrato detallado](../contratos/q13_clientes.md) y el README para reproducirlo.
