from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from farmared.clock import Clock
from farmared.contratos import EventoOutbox, ResultadoEscritura
from farmared.errores import CodigoError, ErrorDominio
from farmared.servicios.clientes.validacion import validar_id_cliente

if TYPE_CHECKING:
    from pymongo.client_session import ClientSession


@dataclass(frozen=True)
class CambioCliente:
    documento: dict
    modificado: bool


def preparar_evento_cliente(id_cliente: str, clock: Clock) -> EventoOutbox:
    validar_id_cliente(id_cliente)
    instante = clock.now_utc()
    if not isinstance(instante, datetime) or instante.tzinfo is None or instante.utcoffset() is None:
        raise ErrorDominio(CodigoError.VALIDACION, "El reloj debe devolver un instante con zona horaria.")
    instante = instante.astimezone(UTC)
    return {
        "_id": str(uuid4()),
        "afectadas": [{"coleccion": "clientes", "id": id_cliente}],
        "procesado": False,
        "creado_en": instante.replace(microsecond=instante.microsecond // 1000 * 1000),
    }


def _ejecutar_transaccion(db, operacion: Callable[["ClientSession"], ResultadoEscritura]) -> ResultadoEscritura:
    from pymongo import ReadPreference
    from pymongo.errors import ConnectionFailure, DuplicateKeyError, PyMongoError
    from pymongo.read_concern import ReadConcern
    from pymongo.write_concern import WriteConcern

    try:
        with db.client.start_session() as sesion:
            return sesion.with_transaction(
                operacion,
                read_concern=ReadConcern("snapshot"),
                write_concern=WriteConcern("majority"),
                read_preference=ReadPreference.PRIMARY,
            )
    except (ErrorDominio, DuplicateKeyError):
        raise
    except ConnectionFailure:
        raise ErrorDominio(
            CodigoError.CONEXION,
            "Se perdió la conexión con MongoDB; verificar el estado confirmado del cliente antes de reintentar.",
        ) from None
    except PyMongoError:
        raise ErrorDominio(
            CodigoError.INTEGRIDAD,
            "MongoDB no confirmó la operación del cliente; verificar su estado antes de reintentar.",
        ) from None


def ejecutar_cambio(
    db, id_cliente: str, operacion: Callable[["ClientSession"], CambioCliente], *, clock: Clock
) -> ResultadoEscritura:
    evento = preparar_evento_cliente(id_cliente, clock)

    def confirmar(sesion) -> ResultadoEscritura:
        cambio = operacion(sesion)
        if (
            not isinstance(cambio, CambioCliente)
            or not isinstance(cambio.documento, Mapping)
            or cambio.documento.get("_id") != id_cliente
            or type(cambio.modificado) is not bool
        ):
            raise ErrorDominio(CodigoError.INTEGRIDAD, "La operación devolvió un cambio de cliente incompatible.")
        eventos = []
        if cambio.modificado:
            db.outbox.insert_one(deepcopy(evento), session=sesion)
            eventos.append(evento["_id"])
        return {"documento": deepcopy(dict(cambio.documento)), "eventos": eventos,
                "reutilizada": not cambio.modificado}

    return _ejecutar_transaccion(db, confirmar)
