from collections.abc import Mapping
from typing import Any

from farmared.clock import Clock, SystemClock
from farmared.contratos import ResultadoEscritura
from farmared.servicios.clientes import operaciones


def q13_alta(db, datos: Mapping[str, Any], *, clock: Clock | None = None) -> ResultadoEscritura:
    return operaciones.alta(db, datos, clock=SystemClock() if clock is None else clock)


def q13_modificar(
    db, id_cliente: str, cambios: Mapping[str, Any], *, clock: Clock | None = None
) -> ResultadoEscritura:
    return operaciones.modificar(db, id_cliente, cambios, clock=SystemClock() if clock is None else clock)


def q13_baja(db, id_cliente: str, *, clock: Clock | None = None) -> ResultadoEscritura:
    return operaciones.baja(db, id_cliente, clock=SystemClock() if clock is None else clock)
