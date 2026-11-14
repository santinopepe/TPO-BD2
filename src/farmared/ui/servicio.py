"""Consultas y operaciones de la consola web; nunca evalúa código del usuario."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from importlib import import_module
from itertools import islice
from time import perf_counter
from threading import RLock
from pathlib import Path

from bson import json_util
from neo4j import READ_ACCESS, WRITE_ACCESS
from neo4j.exceptions import DriverError, Neo4jError
from pymongo import timeout
from pymongo.errors import PyMongoError

from farmared.clock import SystemClock
from farmared.config import Config
from farmared.conexiones import obtener_mongo, obtener_neo4j
from farmared.errores import ErrorDominio
from farmared.ui.plantillas import catalogo

CONSULTAS = [
    ("q01", "Productos activos", "Productos y datos completos del proveedor.", "mongo", "q01_productos_activos", None),
    ("q02", "Ventas pendientes", "Ventas con farmacéutico, sucursal y total.", "mongo", "q02_ventas_pendientes", None),
    ("q03", "Historial de un cliente", "Ventas y recetas en orden cronológico.", "neo4j", "q03_historial", "id_cliente"),
    ("q04", "Clientes con varias recetas", "Clientes con más de una receta registrada.", "neo4j", "q04_clientes_con_recetas", None),
    ("q05", "Ventas por farmacéutico", "Ventas no anuladas de los últimos 60 días.", "mongo", "q05_ventas_por_farmaceutico", "reloj"),
    ("q06", "Dispensas pendientes", "Recetas prolongadas vigentes con dispensa atrasada.", "mongo", "q06_recetas_prolongadas", "reloj"),
    ("q07", "Productos más vendidos", "Los cinco productos con más unidades vendidas.", "mongo", "q07_top_productos", None),
    ("q08", "Stock bajo", "Lotes con menos de 50 unidades disponibles.", "mongo", "q08_lotes_stock_bajo", None),
    ("q09", "Ventas libres menores a $5000", "Ventas libres pendientes o completadas.", "mongo", "q09_ventas_libres", None),
    ("q10", "Clientes de una sucursal", "Clientes atendidos por profesionales de la sucursal.", "neo4j", "q10_clientes_sucursal", "id_sucursal"),
    ("q11", "Ingresos del mes", "Ingresos por farmacéutico del mes actual.", "mongo", "q11_ingresos_mensuales", None),
    ("q12", "Clientes sin ventas recientes", "Clientes sin ventas registradas en el último año.", "mongo", "q12_clientes_sin_ventas", "reloj"),
]
def invalido(mensaje):
    raise ErrorDominio("VALIDACION", mensaje)


def entero(valor, nombre, minimo, maximo):
    if type(valor) is not int or not minimo <= valor <= maximo:
        invalido(f"{nombre} debe ser un entero entre {minimo} y {maximo}.")
    return valor


def serializable(valor):
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if hasattr(valor, "to_native"):
        return serializable(valor.to_native())
    if isinstance(valor, dict):
        return {str(k): serializable(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [serializable(v) for v in valor]
    if isinstance(valor, int) and abs(valor) > 2**53 - 1:
        return {"$numberLong": str(valor)}
    if valor is None or isinstance(valor, (str, int, float, bool)):
        return valor
    if hasattr(valor, "items"):
        return {str(k): serializable(v) for k, v in valor.items()}
    import json
    return json.loads(json_util.dumps(valor))


def _validar_lectura_mongo(valor):
    if isinstance(valor, dict):
        for clave, contenido in valor.items():
            if clave in {"$out", "$merge", "$where", "$function", "$accumulator"}:
                invalido(f"{clave} no está habilitado en la consola de lectura.")
            _validar_lectura_mongo(contenido)
    elif isinstance(valor, list):
        for contenido in valor:
            _validar_lectura_mongo(contenido)


class Consola:
    def __init__(self, config: Config, *, lock_path=None):
        self.config = config
        self._operaciones = RLock()
        self.lock_path = Path(lock_path) if lock_path is not None else Path.home() / ".farmared" / "sync.lock"

    def sincronizar_neo4j(self):
        from farmared.ui.sincronizacion import sincronizar_consola
        with self._operaciones:
            return sincronizar_consola(self)

    def cargar_csv(self, datos, *, importar=False):
        from farmared.ui.importacion import procesar_csv
        with self._operaciones:
            return procesar_csv(self, datos, importar=importar)

    def configuracion(self):
        return {"base": self.config.mongo_db, "consultas": catalogo(CONSULTAS), "limite": 500}

    def _mongo(self):
        return obtener_mongo(self.config)

    def estado_mongo(self):
        db = self._mongo()
        try:
            with timeout(self.config.db_timeout_ms / 1000):
                colecciones = []
                for info in db.list_collections():
                    nombre = info["name"]
                    if nombre.startswith("system."):
                        continue
                    vista = info.get("type") == "view"
                    colecciones.append({"nombre": nombre, "tipo": "vista" if vista else "colección",
                        "documentos": db[nombre].count_documents({}),
                        "indices": 0 if vista else len(db[nombre].index_information())})
                pendientes = db.outbox.count_documents({"procesado": False}) if "outbox" in {c["nombre"] for c in colecciones} else None
                return {"estado": "listo", "base": db.name,
                        "colecciones": sorted(colecciones, key=lambda c: c["nombre"]),
                        "pendientes": pendientes}
        finally:
            db.client.close()

    def _cypher(self, consulta, parametros, limite):
        with obtener_neo4j(self.config) as driver:
            with driver.session(default_access_mode=READ_ACCESS) as session:
                with session.begin_transaction(timeout=self.config.db_timeout_ms / 1000) as tx:
                    plan = tx.run("EXPLAIN " + consulta, parametros).consume()
                    if plan.query_type != "r":
                        invalido("La consola admite únicamente consultas Cypher de lectura.")
                    resultado = tx.run(consulta, parametros)
                    filas = [registro.data() for registro in islice(resultado, limite + 1)]
                    # No drenar un resultado potencialmente ilimitado.
                    return filas

    def estado_neo4j(self):
        filas = self._cypher("MATCH (n) UNWIND labels(n) AS etiqueta RETURN etiqueta, count(*) AS cantidad ORDER BY etiqueta", {}, 100)
        relaciones = self._cypher("MATCH ()-[r]->() RETURN type(r) AS tipo, count(*) AS cantidad ORDER BY tipo", {}, 100)
        return {"estado": "listo", "etiquetas": filas, "relaciones": relaciones}

    def _cypher_libre(self, consulta, parametros, limite):
        with obtener_neo4j(self.config) as driver:
            with driver.session(default_access_mode=WRITE_ACCESS) as session:
                with session.begin_transaction(timeout=self.config.db_timeout_ms / 1000) as tx:
                    plan = tx.run("EXPLAIN " + consulta, parametros).consume()
                    if plan.query_type not in {"r", "w", "rw"}:
                        invalido("Usá consultas de lectura o escritura de datos Cypher.")
                    resultado = tx.run(consulta, parametros)
                    filas = [r.data() for r in islice(resultado, limite + 1)]
                    resumen = resultado.consume()
                    escritura = plan.query_type != "r"
                    cambios = {k: v for k, v in vars(resumen.counters).items()
                               if not k.startswith("_") and v}
                    tx.commit()
                    return filas or ([cambios] if escritura else []), escritura, cambios

    def _escritura_mongo(self, db, consulta):
        operacion = consulta.get("operacion")
        if operacion in {"q13", "q14", "q15"}:
            modulo = import_module(f"farmared.consultas.{operacion}")
            reloj = SystemClock()
            if operacion == "q13":
                accion = consulta.get("accion")
                if accion == "alta":
                    resultado = modulo.q13_alta(db, consulta.get("datos"), clock=reloj)
                elif accion == "modificar":
                    resultado = modulo.q13_modificar(db, consulta.get("id_cliente"), consulta.get("datos"), clock=reloj)
                elif accion == "baja":
                    resultado = modulo.q13_baja(db, consulta.get("id_cliente"), clock=reloj)
                else:
                    invalido("Q13 admite accion: alta, modificar o baja.")
            elif operacion == "q14":
                resultado = modulo.q14_registrar_venta(db, consulta.get("pedido"), reloj)
            else:
                resultado = modulo.q15_actualizar_stock(db, consulta.get("id_venta"), reloj)
            return {**resultado, "proyeccion": "pendiente_sync" if resultado["eventos"] else "no_comprobada"}
        nombre = consulta.get("coleccion")
        if not isinstance(nombre, str) or not nombre or nombre.startswith("system."):
            invalido("Indicá una colección válida.")
        coleccion = db[nombre]
        if operacion == "insertOne":
            documento = consulta.get("documento")
            if not isinstance(documento, dict) or not documento:
                invalido("documento debe ser un objeto JSON no vacío.")
            return {"insertados": 1, "id_insertado": coleccion.insert_one(documento).inserted_id}
        if operacion == "insertMany":
            documentos = consulta.get("documentos")
            if not isinstance(documentos, list) or not 1 <= len(documentos) <= 500 or not all(isinstance(d, dict) for d in documentos):
                invalido("documentos debe contener entre 1 y 500 objetos JSON.")
            resultado = coleccion.insert_many(documentos)
            return {"insertados": len(resultado.inserted_ids), "ids_insertados": resultado.inserted_ids}
        if operacion not in {"updateOne", "updateMany", "replaceOne", "deleteOne", "deleteMany"}:
            invalido("Operación desconocida. Usá find, aggregate, insertOne, insertMany, updateOne, updateMany, replaceOne, deleteOne, deleteMany o q13–q15.")
        filtro = consulta.get("filtro")
        if not isinstance(filtro, dict):
            invalido("Indicá filtro como objeto JSON; {} selecciona todos los documentos.")
        if operacion.startswith("delete"):
            metodo = coleccion.delete_one if operacion == "deleteOne" else coleccion.delete_many
            return {"eliminados": metodo(filtro).deleted_count}
        upsert = consulta.get("upsert", False)
        if type(upsert) is not bool:
            invalido("upsert debe ser true o false.")
        if operacion == "replaceOne":
            documento = consulta.get("documento")
            if not isinstance(documento, dict):
                invalido("documento debe ser un objeto JSON.")
            resultado = coleccion.replace_one(filtro, documento, upsert=upsert)
        else:
            cambios = consulta.get("actualizacion")
            if not isinstance(cambios, (dict, list)) or not cambios:
                invalido("actualizacion debe contener operadores como $set o un pipeline.")
            metodo = coleccion.update_one if operacion == "updateOne" else coleccion.update_many
            resultado = metodo(filtro, cambios, upsert=upsert)
        return {"coincidencias": resultado.matched_count, "modificados": resultado.modified_count,
                "id_upsert": resultado.upserted_id}

    def estado(self):
        def comprobar(funcion):
            try:
                return funcion()
            except ErrorDominio as error:
                return {"estado": "error", "mensaje": error.mensaje}
            except (PyMongoError, Neo4jError, DriverError):
                return {"estado": "error", "mensaje": "No se pudo leer el motor. Revisá la conexión y los permisos."}
        with ThreadPoolExecutor(max_workers=2) as pool:
            mongo = pool.submit(comprobar, self.estado_mongo)
            neo4j = pool.submit(comprobar, self.estado_neo4j)
            return {"mongo": mongo.result(), "neo4j": neo4j.result()}

    def documentos(self, nombre, pagina=0, limite=50):
        entero(pagina, "Página", 0, 100000)
        entero(limite, "Límite", 1, 500)
        db = self._mongo()
        try:
            with timeout(self.config.db_timeout_ms / 1000):
                info = next(db.list_collections(filter={"name": nombre}), None)
                if info is None or nombre.startswith("system."):
                    raise ErrorDominio("NO_EXISTE", "La colección no existe en esta base.")
                filas = list(db[nombre].find().sort("_id", 1).skip(pagina * limite).limit(limite))
                indices = [] if info.get("type") == "view" else list(db[nombre].list_indexes())
                return {"resultados": filas, "total": db[nombre].count_documents({}),
                        "indices": indices, "opciones": info.get("options", {}), "pagina": pagina}
        finally:
            db.client.close()

    def consulta(self, datos):
        with self._operaciones:
            return self._consulta(datos)

    def _consulta(self, datos):
        limite = entero(datos.get("limite", 100), "Límite", 1, 500)
        if not isinstance(datos.get("parametros", {}), dict):
            invalido("Los parámetros deben ser un objeto JSON.")
        inicio = perf_counter()
        escritura, cambios = False, None
        codigo = datos.get("consulta")
        if codigo:
            entrada = next((q for q in CONSULTAS if q[0] == codigo), None)
            if entrada is None:
                invalido("Consulta predefinida desconocida.")
            _, _, _, motor, funcion, parametro = entrada
            args = []
            if parametro == "reloj":
                args.append(SystemClock())
            elif parametro:
                valor = datos.get("parametros", {}).get(parametro)
                if not isinstance(valor, str) or not valor.strip():
                    invalido(f"Completá {parametro}.")
                args.append(valor)
            consultar = getattr(import_module(f"farmared.consultas.{codigo}"), funcion)
            if motor == "mongo":
                db = self._mongo()
                try:
                    with timeout(self.config.db_timeout_ms / 1000):
                        filas = consultar(db, *args)
                finally:
                    db.client.close()
            else:
                with obtener_neo4j(self.config) as driver:
                    filas = consultar(driver, *args)
        elif datos.get("motor") == "neo4j":
            consulta = datos.get("texto", "")
            parametros = datos.get("parametros", {})
            if not isinstance(consulta, str) or not consulta.strip() or len(consulta) > 50000:
                invalido("Ingresá una consulta Cypher de hasta 50000 caracteres.")
            if not isinstance(parametros, dict):
                invalido("Los parámetros deben ser un objeto JSON.")
            # CALL puede invocar procedimientos con efectos externos al grafo.
            import re
            procedimiento = re.search(r"\bCALL\b(?!\s*(?:\{|\([^)]*\)\s*\{))", consulta, re.I)
            if procedimiento or re.search(r"\b(LOAD|CSV|EXPLAIN|PROFILE)\b", consulta, re.I):
                invalido("Los procedimientos CALL, LOAD CSV y planes no están habilitados. Sí se admiten subconsultas CALL { … } o CALL (variables) { … }.")
            filas, escritura, cambios = self._cypher_libre(consulta, parametros, limite)
        elif datos.get("motor") == "mongo":
            texto = datos.get("texto", "")
            if not isinstance(texto, str):
                invalido("La consulta MongoDB debe ser JSON.")
            try:
                consulta = json_util.loads(texto)
            except (ValueError, TypeError):
                invalido("La consulta MongoDB no es JSON válido.")
            if not isinstance(consulta, dict):
                invalido("La consulta MongoDB debe ser un objeto JSON.")
            _validar_lectura_mongo(consulta)
            operacion = consulta.get("operacion", "aggregate" if "pipeline" in consulta else "find")
            if operacion not in {"find", "aggregate"}:
                db = self._mongo()
                try:
                    with timeout(self.config.db_timeout_ms / 1000):
                        cambios = self._escritura_mongo(db, consulta)
                    filas, escritura = [cambios], True
                finally:
                    db.client.close()
                return {"resultados": filas, "cantidad": 1, "truncado": False, "escritura": True,
                        "cambios": cambios, "duracion_ms": round((perf_counter() - inicio) * 1000, 1)}
            nombre = consulta.get("coleccion")
            if not isinstance(nombre, str) or not nombre or nombre.startswith("system."):
                invalido("Indicá una colección válida.")
            db = self._mongo()
            try:
                with timeout(self.config.db_timeout_ms / 1000):
                    if nombre not in db.list_collection_names():
                        raise ErrorDominio("NO_EXISTE", "La colección no existe en esta base.")
                    if "pipeline" in consulta:
                        pipeline = consulta["pipeline"]
                        if not isinstance(pipeline, list):
                            invalido("pipeline debe ser un array de etapas.")
                        cursor = db[nombre].aggregate([*pipeline, {"$limit": limite + 1}], maxTimeMS=self.config.db_timeout_ms)
                    else:
                        filtro, orden = consulta.get("filtro", {}), consulta.get("orden", {})
                        proyeccion = consulta.get("proyeccion")
                        if not isinstance(filtro, dict) or not isinstance(orden, dict) or (proyeccion is not None and not isinstance(proyeccion, dict)):
                            invalido("filtro, orden y proyeccion deben ser objetos JSON.")
                        cursor = db[nombre].find(filtro, proyeccion).limit(limite + 1).max_time_ms(self.config.db_timeout_ms)
                        if orden:
                            cursor = cursor.sort(list(orden.items()))
                    with cursor:
                        filas = list(islice(cursor, limite + 1))
            finally:
                db.client.close()
        else:
            invalido("Elegí MongoDB o Neo4j.")
        return {"resultados": filas[:limite], "cantidad": min(len(filas), limite), "escritura": escritura, "cambios": cambios,
                "truncado": len(filas) > limite, "duracion_ms": round((perf_counter() - inicio) * 1000, 1)}
