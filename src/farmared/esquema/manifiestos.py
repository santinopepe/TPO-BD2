"""Colección técnica del loader; separada del contrato de las nueve colecciones base."""

from typing import get_args

from farmared.contratos import ColeccionNegocio
from farmared.errores import CodigoError, ErrorDominio

COLECCION_MANIFIESTOS = "manifiestos_carga"
ID_MANIFIESTO = "seed_csv"
_texto = {"bsonType": "string", "minLength": 1}
_contador = {"bsonType": ["int", "long"], "minimum": 0}
_identidades = {"bsonType": "array", "minItems": 1, "uniqueItems": True, "items": _texto}
_colecciones = list(get_args(ColeccionNegocio))
VALIDADOR_MANIFIESTOS = {"$jsonSchema": {
    "bsonType": "object",
    "required": ["_id", "version_carga", "version_validacion", "huella", "estado", "base_date",
                 "creado_en", "fuentes", "conteos", "identidades", "eventos_iniciales", "avisos"],
    "properties": {
        "_id": {"enum": [ID_MANIFIESTO]},
        "version_carga": {"bsonType": "int", "minimum": 1},
        "version_validacion": {"bsonType": "int", "minimum": 1},
        "huella": {"bsonType": "string", "pattern": "^[0-9a-f]{64}$"},
        "estado": {"enum": ["completa"]}, "base_date": {"bsonType": "date"},
        "creado_en": {"bsonType": "date"},
        "fuentes": {"bsonType": "array", "minItems": 9, "items": {
            "bsonType": "object", "required": ["tabla", "orden", "archivo", "sha256", "bytes", "filas_leidas"],
            "properties": {"tabla": _texto, "orden": _contador, "archivo": _texto,
                           "sha256": {"bsonType": "string", "pattern": "^[0-9a-f]{64}$"},
                           "bytes": _contador, "filas_leidas": _contador},
        }},
        "conteos": {"bsonType": "object", "required": _colecciones,
                    "properties": {c: _contador for c in _colecciones}},
        "identidades": {"bsonType": "object", "required": _colecciones,
                        "properties": {c: _identidades for c in _colecciones}},
        "eventos_iniciales": _identidades,
        "avisos": {"bsonType": "array", "items": {"bsonType": "object"}},
    },
}}


def preparar_manifiestos(db) -> None:
    info = next(db.list_collections(filter={"name": COLECCION_MANIFIESTOS}), None)
    if info is None:
        db.create_collection(COLECCION_MANIFIESTOS, validator=VALIDADOR_MANIFIESTOS,
                             validationLevel="strict", validationAction="error")
        return
    opciones = info.get("options", {})
    if (info["type"] != "collection" or opciones.get("validator") != VALIDADOR_MANIFIESTOS
            or opciones.get("validationLevel", "strict") != "strict"
            or opciones.get("validationAction", "error") != "error"):
        raise ErrorDominio(CodigoError.INTEGRIDAD, "manifiestos_carga tiene una definición distinta; requiere migración explícita.")
