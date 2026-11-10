"""Seed autoritativo de una sola transacción; no importa servicios B/C/D ni Neo4j."""

import json
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
from typing import get_args
from uuid import NAMESPACE_URL, uuid5

from pymongo import ReadPreference
from pymongo.errors import DuplicateKeyError, PyMongoError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from farmared.carga.modelos import VERSION_VALIDACION
from farmared.carga.transformacion import transformar_mongo
from farmared.carga.validacion import validar_datasets
from farmared.clock import SystemClock, ZONA_COMERCIAL, inicio_dia_utc
from farmared.contratos import ColeccionProyectada
from farmared.errores import CodigoError, ErrorDominio
from farmared.esquema.base_mongo import preparar_mongo_base
from farmared.esquema.manifiestos import COLECCION_MANIFIESTOS, ID_MANIFIESTO, VALIDADOR_MANIFIESTOS, preparar_manifiestos

VERSION_CARGA = 1


def _eventos(documentos, huella, instante):
    eventos = []
    for coleccion in get_args(ColeccionProyectada):
        for doc in documentos[coleccion]:
            identidad = json.dumps(["farmared", "seed", VERSION_CARGA, huella, coleccion, doc["_id"]], separators=(",", ":"))
            eventos.append({
                "_id": str(uuid5(NAMESPACE_URL, identidad)),
                "afectadas": [{"coleccion": coleccion, "id": doc["_id"]}],
                "procesado": False, "creado_en": instante,
            })
    return eventos


def _buscar_manifiesto(db, sesion):
    return db[COLECCION_MANIFIESTOS].find_one({"_id": ID_MANIFIESTO}, session=sesion)


def _verificar(db, sesion, manifiesto, esperado):
    for campo in ("version_carga", "version_validacion", "huella"):
        if manifiesto.get(campo) != esperado[campo]:
            raise ErrorDominio(CodigoError.CONFLICTO_ID, "La fuente o versión de carga cambió; usar otra base o una migración deliberada.")
    invalido = db[COLECCION_MANIFIESTOS].find_one(
        {"_id": ID_MANIFIESTO, "$nor": [VALIDADOR_MANIFIESTOS]}, {"_id": 1}, session=sesion,
    )
    if invalido is not None:
        raise ErrorDominio(CodigoError.INTEGRIDAD, "El manifiesto almacenado incumple su esquema; no se declara la carga completa.")
    for campo in ("estado", "conteos", "identidades", "eventos_iniciales"):
        if manifiesto.get(campo) != esperado[campo]:
            raise ErrorDominio(CodigoError.INTEGRIDAD, "El manifiesto está incompleto o no corresponde a las identidades de las fuentes.")
    campos_fuente = ("tabla", "orden", "sha256", "bytes", "filas_leidas")
    fuentes = manifiesto.get("fuentes")
    if not isinstance(fuentes, list) or not all(isinstance(f, dict) for f in fuentes):
        raise ErrorDominio(CodigoError.INTEGRIDAD, "El manifiesto no conserva sus fuentes.")
    if ([{k: f.get(k) for k in campos_fuente} for f in fuentes]
            != [{k: f[k] for k in campos_fuente} for f in esperado["fuentes"]]):
        raise ErrorDominio(CodigoError.INTEGRIDAD, "Las huellas individuales del manifiesto son inconsistentes.")
    base = manifiesto.get("base_date")
    if not isinstance(base, datetime) or not isinstance(manifiesto.get("creado_en"), datetime):
        raise ErrorDominio(CodigoError.INTEGRIDAD, "El manifiesto no conserva sus fechas.")
    base_utc = base.replace(tzinfo=UTC) if base.tzinfo is None else base.astimezone(UTC)
    if base_utc != inicio_dia_utc(base_utc.astimezone(ZONA_COMERCIAL).date()):
        raise ErrorDominio(CodigoError.INTEGRIDAD, "base_date no representa un inicio de día comercial.")
    generaciones = manifiesto.get("generaciones", [])
    esperadas = esperado.get("generaciones", [])
    if not isinstance(generaciones, list) or len(generaciones) != len(esperadas):
        raise ErrorDominio(CodigoError.INTEGRIDAD, "El manifiesto no conserva las generaciones de las fuentes.")
    for actual, origen in zip(generaciones, esperadas):
        if not isinstance(actual, dict) or any(actual.get(k) != origen[k] for k in ("orden", "sha256", "version_generador")):
            raise ErrorDominio(CodigoError.INTEGRIDAD, "El manifiesto de generación fue alterado.")
        fecha = actual.get("base_date")
        if not isinstance(fecha, datetime):
            raise ErrorDominio(CodigoError.INTEGRIDAD, "Falta la fecha BSON de generación.")
        fecha_utc = fecha.replace(tzinfo=UTC) if fecha.tzinfo is None else fecha.astimezone(UTC)
        if fecha_utc != origen["base_date"]:
            raise ErrorDominio(CodigoError.INTEGRIDAD, "La fecha de generación no coincide con las fuentes.")
    if esperadas:
        if base_utc != esperado["base_date"]:
            raise ErrorDominio(CodigoError.INTEGRIDAD, "base_date no coincide con la generación persistida.")
    else:
        creado = manifiesto["creado_en"]
        creado_utc = creado.replace(tzinfo=UTC) if creado.tzinfo is None else creado.astimezone(UTC)
        if base_utc != inicio_dia_utc(creado_utc.astimezone(ZONA_COMERCIAL).date()):
            raise ErrorDominio(CodigoError.INTEGRIDAD, "base_date no corresponde al día comercial de esta carga inicial.")
    for coleccion, ids in manifiesto["identidades"].items():
        if db[coleccion].count_documents({"_id": {"$in": ids}}, session=sesion) != len(ids):
            raise ErrorDominio(CodigoError.INTEGRIDAD, f"Faltan identidades importadas en {coleccion}; no se restauran desde CSV.")
    ids_eventos = manifiesto["eventos_iniciales"]
    if db.outbox.count_documents({"_id": {"$in": ids_eventos}}, session=sesion) != len(ids_eventos):
        raise ErrorDominio(CodigoError.INTEGRIDAD, "Faltan eventos iniciales; no se recrean ni se reinicia la proyección.")


def _transaccion(db, callback):
    with db.client.start_session() as sesion:
        return sesion.with_transaction(
            callback, read_concern=ReadConcern("snapshot"),
            write_concern=WriteConcern("majority"), read_preference=ReadPreference.PRIMARY,
            max_commit_time_ms=10000,
        )


def cargar_mongo(db, rutas):
    """Valida, prepara esquema y carga fuentes en una base vacía o reutiliza su seed.

    Retorna {documento: manifiesto, eventos: ids nuevos, reutilizada: bool}.
    Requiere escritores pausados durante el bootstrap/DDL; no hace reset ni sync.
    El llamador conserva y cierra db.client. La firma pública usa los dos argumentos
    acordados; el reloj real se captura una vez antes de cualquier reintento.
    """
    validado = validar_datasets(rutas)
    documentos = transformar_mongo(validado)
    instante = SystemClock().now_utc()
    # BSON Date conserva milisegundos; usar la misma precisión en el retorno y el motor.
    instante = instante.replace(microsecond=instante.microsecond // 1000 * 1000)
    eventos = _eventos(documentos, validado.huella, instante)
    base = validado.generaciones[0].base_date if validado.generaciones else instante.astimezone(ZONA_COMERCIAL).date()
    manifiesto = {
        "_id": ID_MANIFIESTO, "version_carga": VERSION_CARGA,
        "version_validacion": VERSION_VALIDACION, "huella": validado.huella,
        "estado": "completa", "base_date": inicio_dia_utc(base),
        "creado_en": instante, "fuentes": [asdict(f) for f in validado.fuentes],
        "conteos": {c: len(docs) for c, docs in documentos.items()},
        "identidades": {c: [d["_id"] for d in docs] for c, docs in documentos.items()},
        "eventos_iniciales": [e["_id"] for e in eventos], "avisos": [asdict(a) for a in validado.avisos],
    }
    if validado.generaciones:
        manifiesto["generaciones"] = [{**g.documento(), "base_date": inicio_dia_utc(g.base_date)} for g in validado.generaciones]

    def ejecutar(sesion):
        existente = _buscar_manifiesto(db, sesion)
        if existente is not None:
            _verificar(db, sesion, existente, manifiesto)
            return {"documento": existente, "eventos": [], "reutilizada": True}
        for coleccion in (*documentos, "outbox", COLECCION_MANIFIESTOS):
            if db[coleccion].find_one({}, {"_id": 1}, session=sesion) is not None:
                raise ErrorDominio(CodigoError.CONFLICTO_ID, f"{coleccion} no está vacía y no hay manifiesto propio; no se adopta ni sobrescribe.")
        db[COLECCION_MANIFIESTOS].insert_one(deepcopy(manifiesto), session=sesion)
        for coleccion, docs in documentos.items():
            db[coleccion].insert_many(deepcopy(docs), ordered=True, session=sesion)
        db.outbox.insert_many(deepcopy(eventos), ordered=True, session=sesion)
        _verificar(db, sesion, manifiesto, manifiesto)
        return {"documento": deepcopy(manifiesto), "eventos": list(manifiesto["eventos_iniciales"]), "reutilizada": False}

    try:
        preparar_mongo_base(db)
        preparar_manifiestos(db)
        try:
            return _transaccion(db, ejecutar)
        except DuplicateKeyError:
            # Un seed competidor puede haber confirmado entre la lectura y el insert.
            def recuperar(sesion):
                existente = _buscar_manifiesto(db, sesion)
                if existente is None:
                    raise ErrorDominio(CodigoError.CONFLICTO_ID, "Colisión con datos existentes sin manifiesto confirmado; no se sobrescriben.")
                _verificar(db, sesion, existente, manifiesto)
                return {"documento": existente, "eventos": [], "reutilizada": True}
            return _transaccion(db, recuperar)
    except PyMongoError:
        raise ErrorDominio(CodigoError.INTEGRIDAD, "No se pudo confirmar la carga. Reintentar con las mismas fuentes para verificar su estado; no se declara éxito ni se hace reset.") from None
