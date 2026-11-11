"""FEFO puro (First Expired, First Out): demanda, plan de consumo y asignación a líneas.

No accede a motores. Recibe los lotes leídos en el snapshot de la operación y
decide el plan completo antes de modificar nada: o alcanza para todos los
productos, o se rechaza la venta entera. Aplicar el plan (decrementos
condicionales dentro de la transacción) corresponde a otro módulo.
"""

from collections import defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

from farmared.clock import ZONA_COMERCIAL
from farmared.contratos import MAX_IMPORTE_ARS
from farmared.errores import CodigoError, ErrorDominio
from farmared.servicios.ventas.pedido import ItemPedido


@dataclass(frozen=True)
class ConsumoLote:
    """Unidades a descontar de un lote concreto."""

    id_lote: str
    id_producto: str
    cantidad: int


@dataclass(frozen=True)
class Asignacion:
    """Parte de una línea de venta abastecida por un lote; va a `items[].asignaciones_lotes`."""

    id_lote: str
    cantidad: int


def demanda_por_producto(items: Iterable[ItemPedido]) -> dict[str, int]:
    """Suma las cantidades de todas las líneas de cada producto.

    Dos líneas del mismo producto generan una sola demanda, para no planificar
    dos veces sobre el mismo saldo de lote.
    """
    demanda: dict[str, int] = defaultdict(int)
    for item in items:
        demanda[item.id_producto] += item.cantidad
        if demanda[item.id_producto] > MAX_IMPORTE_ARS:
            raise ErrorDominio(CodigoError.VALIDACION, f"La demanda de {item.id_producto} excede el rango int64.")
    return dict(demanda)


def dia_comercial(instante: datetime) -> date:
    """BSON Date de MongoDB → día comercial de Buenos Aires. Naive se interpreta UTC."""
    if not isinstance(instante, datetime):
        raise ErrorDominio(CodigoError.INTEGRIDAD, "El vencimiento del lote debe ser una fecha BSON.")
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=UTC)
    return instante.astimezone(ZONA_COMERCIAL).date()


def _lotes_elegibles(lotes: Iterable[Mapping], id_sucursal: str, productos: set[str], hoy: date):
    """Lotes de la sucursal y productos pedidos, con unidades y no vencidos, en orden FEFO."""
    vistos: set[str] = set()
    elegibles = []
    for lote in lotes:
        id_lote = lote.get("_id")
        if id_lote in vistos:
            raise ErrorDominio(CodigoError.INTEGRIDAD, f"Lote repetido en el snapshot: {id_lote}.")
        vistos.add(id_lote)
        unidades = lote.get("unidades")
        # BSON Int64 es subclase de int (el validador de A admite long); bool no es un saldo.
        if isinstance(unidades, bool) or not isinstance(unidades, int) or unidades < 0:
            raise ErrorDominio(CodigoError.INTEGRIDAD, f"El lote {id_lote} tiene unidades inválidas.")
        unidades = int(unidades)
        if lote.get("id_sucursal") != id_sucursal or lote.get("id_producto") not in productos:
            continue
        vence = dia_comercial(lote.get("vencimiento"))
        # Supuesto declarado: el día de vencimiento todavía se puede dispensar.
        if unidades == 0 or vence < hoy:
            continue
        elegibles.append((vence, id_lote, lote["id_producto"], unidades))
    elegibles.sort(key=lambda e: (e[0], e[1]))
    return elegibles


def planificar_fefo(demanda: Mapping[str, int], lotes: Iterable[Mapping], hoy: date,
                    id_sucursal: str) -> tuple[ConsumoLote, ...]:
    """Plan de consumo por FEFO para toda la venta, o STOCK_INSUFICIENTE sin plan parcial.

    Por producto (en orden de id), toma lotes de `id_sucursal` por vencimiento
    ascendente y luego id de lote, omitiendo vencidos (`vencimiento < hoy`) y
    vacíos. Si algún producto no alcanza, el error detalla todos los faltantes.
    """
    elegibles = _lotes_elegibles(lotes, id_sucursal, set(demanda), hoy)
    plan: list[ConsumoLote] = []
    faltantes: list[str] = []
    for id_producto in sorted(demanda):
        pendiente = demanda[id_producto]
        disponible = 0
        for _, id_lote, producto, unidades in elegibles:
            if producto != id_producto:
                continue
            disponible += unidades
            if pendiente > 0:
                toma = min(unidades, pendiente)
                plan.append(ConsumoLote(id_lote, id_producto, toma))
                pendiente -= toma
        if pendiente > 0:
            faltantes.append(f"{id_producto}: pedido {demanda[id_producto]}, vigente {disponible}")
    if faltantes:
        raise ErrorDominio(
            CodigoError.STOCK_INSUFICIENTE,
            f"Stock vigente insuficiente en {id_sucursal}; no se modificó ningún lote. " + "; ".join(faltantes) + ".",
        )
    return tuple(plan)


def distribuir_asignaciones(items: Sequence[ItemPedido],
                            plan: Iterable[ConsumoLote]) -> dict[str, tuple[Asignacion, ...]]:
    """Reparte el plan entre las líneas, en orden de línea y de plan.

    Cada línea recibe asignaciones que suman exactamente su cantidad. El plan
    debe cubrir la demanda exacta de cada producto; si no, es un error interno.
    """
    colas: dict[str, deque[list]] = defaultdict(deque)
    for consumo in plan:
        colas[consumo.id_producto].append([consumo.id_lote, consumo.cantidad])
    resultado: dict[str, tuple[Asignacion, ...]] = {}
    for item in items:
        cola = colas[item.id_producto]
        restante = item.cantidad
        asignaciones: list[Asignacion] = []
        while restante > 0:
            if not cola:
                raise ErrorDominio(CodigoError.INTEGRIDAD, f"El plan FEFO no cubre la línea {item.id_detalle}.")
            id_lote, saldo = cola[0]
            toma = min(saldo, restante)
            asignaciones.append(Asignacion(id_lote, toma))
            restante -= toma
            if toma == saldo:
                cola.popleft()
            else:
                cola[0][1] = saldo - toma
        resultado[item.id_detalle] = tuple(asignaciones)
    if any(colas.values()):
        raise ErrorDominio(CodigoError.INTEGRIDAD, "El plan FEFO consume más unidades que las líneas de la venta.")
    return resultado
