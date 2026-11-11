from collections.abc import Mapping
from copy import deepcopy
from typing import Any
from uuid import uuid4

from farmared.clock import Clock
from farmared.contratos import ResultadoEscritura
from farmared.errores import CodigoError, ErrorDominio
from farmared.servicios.clientes.transaccion import CambioCliente, ejecutar_cambio
from farmared.servicios.clientes.validacion import (
    combinar_cambios,
    normalizar_alta,
    normalizar_cambios,
    validar_id_cliente,
)


def preparar_alta(datos: Mapping[str, Any]) -> dict:
    normalizados = normalizar_alta(datos)
    return {"_id": str(uuid4()), **normalizados, "activo": True}


def alta(db, datos: Mapping[str, Any], *, clock: Clock) -> ResultadoEscritura:
    documento = preparar_alta(datos)
    from pymongo.errors import DuplicateKeyError

    colision_cliente = None

    def operacion(sesion):
        nonlocal colision_cliente
        try:
            db.clientes.insert_one(deepcopy(documento), session=sesion)
        except DuplicateKeyError as error:
            colision_cliente = error
            raise
        return CambioCliente(documento, True)

    try:
        return ejecutar_cambio(db, documento["_id"], operacion, clock=clock)
    except DuplicateKeyError as error:
        if error is colision_cliente:
            patron = (error.details or {}).get("keyPattern")
            if patron == {"dni": 1}:
                raise ErrorDominio(CodigoError.DNI_DUPLICADO, "El DNI ya está registrado, incluso si el cliente está inactivo.") from None
            if patron == {"_id": 1}:
                raise ErrorDominio(CodigoError.CONFLICTO_ID, "La identidad generada ya pertenece a otro cliente.") from None
        raise ErrorDominio(CodigoError.INTEGRIDAD, "Una restricción de unicidad rechazó la operación o su evento.") from None


def _leer_cliente(db, id_cliente: str, sesion) -> dict:
    documento = db.clientes.find_one({"_id": id_cliente}, session=sesion)
    if documento is None:
        raise ErrorDominio(CodigoError.NO_EXISTE, f"No existe el cliente {id_cliente}.")
    if type(documento.get("activo")) is not bool:
        raise ErrorDominio(CodigoError.INTEGRIDAD, "El cliente tiene un estado de actividad inválido.")
    return documento


def _comprobar_actualizacion(resultado) -> None:
    if resultado.matched_count != 1 or resultado.modified_count != 1:
        raise ErrorDominio(CodigoError.INTEGRIDAD, "No se pudo aplicar el cambio esperado al cliente.")


def _ejecutar_actualizacion(db, id_cliente: str, operacion, clock: Clock) -> ResultadoEscritura:
    from pymongo.errors import DuplicateKeyError

    try:
        return ejecutar_cambio(db, id_cliente, operacion, clock=clock)
    except DuplicateKeyError:
        raise ErrorDominio(CodigoError.INTEGRIDAD, "Una restricción de unicidad rechazó la actualización o su evento.") from None


def modificar(db, id_cliente: str, cambios: Mapping[str, Any], *, clock: Clock) -> ResultadoEscritura:
    validar_id_cliente(id_cliente)
    normalizados = normalizar_cambios(cambios)

    def operacion(sesion):
        actual = _leer_cliente(db, id_cliente, sesion)
        actualizado = combinar_cambios(actual, normalizados)
        efectivos = {campo: actualizado[campo] for campo in normalizados
                     if campo not in actual or actual[campo] != actualizado[campo]}
        if not efectivos:
            return CambioCliente(actual, False)
        resultado = db.clientes.update_one({"_id": id_cliente}, {"$set": efectivos}, session=sesion)
        _comprobar_actualizacion(resultado)
        return CambioCliente(actualizado, True)

    return _ejecutar_actualizacion(db, id_cliente, operacion, clock)


def baja(db, id_cliente: str, *, clock: Clock) -> ResultadoEscritura:
    validar_id_cliente(id_cliente)

    def operacion(sesion):
        actual = _leer_cliente(db, id_cliente, sesion)
        if not actual["activo"]:
            return CambioCliente(actual, False)
        resultado = db.clientes.update_one(
            {"_id": id_cliente, "activo": True}, {"$set": {"activo": False}}, session=sesion,
        )
        _comprobar_actualizacion(resultado)
        return CambioCliente({**actual, "activo": False}, True)

    return _ejecutar_actualizacion(db, id_cliente, operacion, clock)
