"""Única puerta transaccional de ventas: snapshot, majority y primario.

La operación recibe la sesión y debe hacer TODAS sus lecturas y escrituras con
ella. El driver puede reejecutarla ante errores transitorios (conflicto de
escritura, elección de primario) con un snapshot nuevo, por lo que no debe
tener efectos fuera de MongoDB. Un ErrorDominio dentro de la operación aborta
la transacción completa y se propaga tal cual.
"""

from collections.abc import Callable
from typing import TypeVar

from pymongo import ReadPreference
from pymongo.client_session import ClientSession
from pymongo.errors import ConnectionFailure, DuplicateKeyError, PyMongoError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from farmared.errores import CodigoError, ErrorDominio

T = TypeVar("T")


def ejecutar_transaccion(db, operacion: Callable[[ClientSession], T]) -> T:
    """Ejecuta `operacion(sesion)` en una transacción MongoDB y devuelve su resultado.

    DuplicateKeyError se propaga sin traducir para que el llamador resuelva
    carreras de identidad (idempotencia). Otros errores del motor se traducen a
    ErrorDominio: el resultado puede ser incierto y se recupera reintentando con
    el mismo id de operación, nunca generando uno nuevo.
    """
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
        raise ErrorDominio(CodigoError.CONEXION, "Se perdió la conexión con MongoDB; reintentar con el mismo id para conocer el resultado.") from None
    except PyMongoError:
        raise ErrorDominio(CodigoError.INTEGRIDAD, "MongoDB no confirmó la transacción; reintentar con el mismo id para conocer el resultado.") from None
