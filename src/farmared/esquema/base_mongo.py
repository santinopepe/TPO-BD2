"""Esquema documental común. No valida referencias ni ejecuta reglas de dispensación."""

from copy import deepcopy
from typing import get_args

from pymongo import ASCENDING, IndexModel
from pymongo.errors import PyMongoError

from farmared import contratos as c
from farmared.errores import CodigoError, ErrorDominio


def _texto(nulo=False):
    return {"bsonType": ["string", "null"] if nulo else "string", "minLength": 1}


def _entero(minimo=0, maximo=c.MAX_IMPORTE_ARS):
    return {"bsonType": ["int", "long"], "minimum": minimo, "maximum": maximo}


def _enum(tipo):
    return {"bsonType": "string", "enum": list(get_args(tipo))}


def _objeto(propiedades, opcionales=()):
    return {
        "bsonType": "object",
        "required": [k for k in propiedades if k not in opcionales],
        "properties": propiedades,
        "additionalProperties": True,
    }


def _definiciones():
    fecha = {"bsonType": "date"}
    fecha_nula = {"bsonType": ["date", "null"]}
    booleano = {"bsonType": "bool"}
    asignacion = _objeto({"id_lote": _texto(), "cantidad": _entero(1)})
    item = _objeto({
        "id_detalle": _texto(), "id_producto": _texto(), "cantidad": _entero(1),
        "precio_unit": _entero(), "subtotal": _entero(),
        "asignaciones_lotes": {"bsonType": ["array", "null"], "items": asignacion},
    })
    esquemas = {
        "clientes": _objeto({
            "_id": _texto(), "nombre": _texto(), "apellido": _texto(), "dni": _texto(),
            "email": _texto(True), "telefono": _texto(True), "ciudad": _texto(),
            "provincia": _texto(), "obra_social": _enum(c.ObraSocial),
            "nro_afiliado": _texto(True), "activo": booleano,
        }),
        "sucursales": _objeto({
            "_id": _texto(), "nombre": _texto(), "tipo": _enum(c.TipoSucursal),
            "direccion": _texto(), "ciudad": _texto(), "provincia": _texto(),
            "telefono": _texto(True), "activo": booleano,
        }),
        "farmaceuticos": _objeto({
            "_id": _texto(), "nombre": _texto(), "apellido": _texto(),
            "matricula": _texto(), "cargo": _enum(c.CargoFarmaceutico),
            "id_sucursal": _texto(), "activo": booleano,
        }),
        "proveedores": _objeto({
            "_id": _texto(), "razon_social": _texto(), "cuit": _texto(),
            "tipo": _enum(c.TipoProveedor), "ciudad": _texto(), "provincia": _texto(),
            "telefono": _texto(True), "activo": booleano,
        }),
        "productos": _objeto({
            "_id": _texto(), "nombre": _texto(), "principio_activo": _texto(True),
            "categoria": _texto(), "presentacion": _texto(),
            "condicion_venta": _enum(c.CondicionVenta), "precio_unit": _entero(),
            "id_proveedor": _texto(), "activo": booleano,
        }),
        "stock_lotes": _objeto({
            "_id": _texto(), "id_producto": _texto(), "id_sucursal": _texto(),
            "nro_lote": _texto(), "unidades": _entero(), "vencimiento": fecha,
        }),
        "recetas": _objeto({
            "_id": _texto(), "id_cliente": _texto(), "medico": _texto(),
            "matricula_medico": _texto(), "fecha_emision": fecha,
            "tipo": _enum(c.TipoReceta), "dispensas_autorizadas": _entero(1, 3),
            "dispensas_realizadas": _entero(0, 3), "proxima_dispensa": fecha_nula,
            "estado": _enum(c.EstadoReceta),
        }),
        "ventas": _objeto({
            "_id": _texto(), "id_cliente": _texto(), "id_farmaceutico": _texto(),
            "id_sucursal": _texto(), "id_receta": _texto(True), "fecha": fecha,
            "tipo": _enum(c.TipoVenta), "medio_pago": _enum(c.MedioPago),
            "estado": _enum(c.EstadoVenta), "total": _entero(),
            "items": {"bsonType": "array", "minItems": 1, "items": item},
            "stock_aplicado": booleano, "receta_aplicada": booleano,
            "origen": _enum(c.OrigenVenta), "trazabilidad_lotes": _texto(),
            "request_hash": _texto(), "fecha_creacion_pendiente": fecha,
        }, opcionales=("request_hash", "fecha_creacion_pendiente")),
        "outbox": _objeto({
            "_id": _texto(), "afectadas": {
                "bsonType": "array", "minItems": 1, "uniqueItems": True,
                "items": _objeto({"coleccion": _enum(c.ColeccionProyectada), "id": _texto()}),
            },
            "procesado": booleano, "creado_en": fecha,
        }),
    }
    validadores = {nombre: {"$jsonSchema": esquema} for nombre, esquema in esquemas.items()}
    validadores["ventas"] = {"$and": [validadores["ventas"], {"$expr": {"$cond": [
        {"$isArray": "$items"},
        {"$eq": [
            {"$size": "$items"},
            {"$size": {"$setUnion": [
                {"$map": {"input": "$items", "as": "item", "in": "$$item.id_detalle"}}, []
            ]}},
        ]},
        False,
    ]}}]}
    return validadores


VALIDADORES = _definiciones()
INDICES = {
    "clientes": [IndexModel([("dni", ASCENDING)], name="uq_clientes_dni", unique=True)],
    "farmaceuticos": [IndexModel([("matricula", ASCENDING)], name="uq_farmaceuticos_matricula", unique=True)],
    "ventas": [IndexModel([
        ("id_farmaceutico", ASCENDING), ("fecha", ASCENDING),
    ], name="ix_ventas_farmaceutico_fecha"), IndexModel([
        ("id_cliente", ASCENDING), ("fecha", ASCENDING),
    ], name="ix_ventas_cliente_fecha")],
    "stock_lotes": [IndexModel([
        ("id_sucursal", ASCENDING), ("id_producto", ASCENDING),
        ("vencimiento", ASCENDING), ("_id", ASCENDING),
    ], name="ix_stock_lotes_fefo")],
    "outbox": [IndexModel([
        ("procesado", ASCENDING), ("creado_en", ASCENDING), ("_id", ASCENDING),
    ], name="ix_outbox_pendientes")],
}


def _conflicto(nombre, motivo):
    return ErrorDominio(CodigoError.INTEGRIDAD, f"{nombre}: {motivo}; requiere una migración explícita.")


def _indice_compatible(actual, esperado):
    return (
        list(actual["key"]) == list(esperado["key"].items())
        and bool(actual.get("unique")) == bool(esperado.get("unique"))
        and not actual.get("sparse", False)
        and "partialFilterExpression" not in actual
        and "expireAfterSeconds" not in actual
        and not actual.get("hidden", False)
        and actual.get("collation", {"locale": "simple"}) == {"locale": "simple"}
    )


def preparar_mongo_base(db) -> None:
    """Crea/asegura nueve colecciones y seis índices comunes, sin tocar documentos.

    Requiere escritores pausados. Hace preflight global de documentos y definiciones
    existentes. No reemplaza validadores distintos ni borra índices. El DDL no es
    atómico: ante una falla de motor puede quedar incompleto y debe repetirse.
    """
    if db.name in {"admin", "config", "local"}:
        raise ErrorDominio(CodigoError.VALIDACION, "Elegir una base de aplicación, no una base interna MongoDB.")
    try:
        _preparar(db)
    except PyMongoError:
        raise ErrorDominio(CodigoError.INTEGRIDAD, "MongoDB no pudo completar el esquema base; revisar permisos, concurrencia y definiciones. No se declara listo.") from None


def _preparar(db):
    existentes = {info["name"]: info for info in db.list_collections()}
    pendientes = {}
    for nombre, validador in VALIDADORES.items():
        modelos = INDICES.get(nombre, [])
        if nombre not in existentes:
            pendientes[nombre] = modelos
            continue
        info = existentes[nombre]
        opciones = info.get("options", {})
        if info["type"] != "collection" or opciones.get("capped") or "timeseries" in opciones:
            raise _conflicto(nombre, "se esperaba una colección normal")
        if opciones.get("collation", {"locale": "simple"}) != {"locale": "simple"}:
            raise _conflicto(nombre, "collation de colección incompatible")
        actual = opciones.get("validator", {})
        if actual and (
            actual != validador or opciones.get("validationLevel", "strict") != "strict"
            or opciones.get("validationAction", "error") != "error"
        ):
            raise _conflicto(nombre, "validador existente diferente")
        if db[nombre].find_one({"$nor": [validador]}, {"_id": 1}) is not None:
            raise _conflicto(nombre, "hay documentos que incumplen el esquema")
        indices = db[nombre].index_information()
        pendientes[nombre] = []
        for modelo in modelos:
            esperado = modelo.document
            if esperado["name"] in indices:
                if not _indice_compatible(indices[esperado["name"]], esperado):
                    raise _conflicto(nombre, f"índice incompatible para {esperado['name']}")
                continue
            candidatos = [indice for indice in indices.values()
                          if list(indice["key"]) == list(esperado["key"].items())]
            if candidatos:
                if not any(_indice_compatible(indice, esperado) for indice in candidatos):
                    raise _conflicto(nombre, f"índice incompatible para {esperado['name']}")
                continue
            if esperado.get("unique"):
                campo = next(iter(esperado["key"]))
                duplicados = list(db[nombre].aggregate([
                    {"$group": {"_id": f"${campo}", "cantidad": {"$sum": 1}}},
                    {"$match": {"cantidad": {"$gt": 1}}}, {"$limit": 1},
                ]))
                if duplicados:
                    raise _conflicto(nombre, f"hay valores duplicados en {campo}")
            pendientes[nombre].append(modelo)
    for nombre, validador in VALIDADORES.items():
        if nombre not in existentes:
            db.create_collection(nombre, validator=deepcopy(validador), validationLevel="strict", validationAction="error")
        elif not existentes[nombre].get("options", {}).get("validator"):
            db.command("collMod", nombre, validator=deepcopy(validador), validationLevel="strict", validationAction="error")
        if pendientes[nombre]:
            db[nombre].create_indexes(pendientes[nombre])
