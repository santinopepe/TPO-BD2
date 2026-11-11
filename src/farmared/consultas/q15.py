"""q15 — Actualización de stock FEFO de una venta registrada.

Propósito: dada una venta registrada, decrementar las unidades de cada producto
del detalle en los lotes de la sucursal del farmacéutico, aplicando FEFO y
omitiendo lotes vencidos. Si el stock vigente no alcanza para algún ítem, la
operación completa se rechaza sin modificar ningún lote.

Interpretación (decisión de diseño documentada): q14 ya ejecuta este mismo
descuento dentro de su transacción. Como función autónoma, q15 completa una
venta 'Pendiente', que existe sin haber afectado stock. Para eso revalida
cliente, farmacéutico, sucursal, productos y receta con el mismo coordinador
que q14, captura los precios vigentes, consume la dispensa si corresponde y
pasa la venta a 'Completada' con fecha de hoy, conservando la original en
`fecha_creacion_pendiente`. Ante cualquier rechazo, la pendiente queda
exactamente igual (fecha, precios, receta y lotes).

Motor: MongoDB, una transacción (venta + lotes + receta + outbox).

Estados de la venta:
- Pendiente: se completa (o se rechaza sin cambios).
- Completada con stock aplicado: éxito previo, sin volver a descontar.
- Completada sin stock aplicado: INTEGRIDAD (no repara ventas corruptas).
- Anulada: VALIDACION (no tiene efecto económico).
"""

from farmared.clock import Clock
from farmared.contratos import ResultadoEscritura
from farmared.errores import CodigoError, ErrorDominio
from farmared.servicios.ventas.coordinador import finalizar_venta
from farmared.servicios.ventas.escritura import registrar_evento
from farmared.servicios.ventas.lectura import leer_venta
from farmared.servicios.ventas.pedido import PedidoVenta, normalizar_pedido
from farmared.servicios.ventas.transaccion import ejecutar_transaccion


def q15_actualizar_stock(db, id_venta: str, clock: Clock) -> ResultadoEscritura:
    """Aplica FEFO (y receta) a la venta `id_venta` y la deja Completada.

    Parámetros:
        db: Database de PyMongo (replica set).
        id_venta: venta registrada a procesar.
        clock: reloj de negocio; el día comercial se captura una vez por llamada.

    Retorna {"documento": venta, "eventos": [id_evento], "reutilizada": bool}.
    Errores: ErrorDominio con NO_EXISTE, VALIDACION, RECETA_INVALIDA,
    STOCK_INSUFICIENTE, INTEGRIDAD o CONEXION.
    """
    if type(id_venta) is not str or not id_venta.strip() or id_venta != id_venta.strip():
        raise ErrorDominio(CodigoError.VALIDACION, "id_venta debe ser un string no vacío, sin espacios al inicio/final.")
    hoy = clock.today()
    instante = clock.now_utc()

    def operacion(sesion) -> ResultadoEscritura:
        venta = leer_venta(db, sesion, id_venta)
        if venta is None:
            raise ErrorDominio(CodigoError.NO_EXISTE, f"No existe la venta {id_venta}.")
        estado = venta.get("estado")
        if estado == "Completada":
            if venta.get("stock_aplicado") is True:
                return {"documento": venta, "eventos": [], "reutilizada": True}
            raise ErrorDominio(CodigoError.INTEGRIDAD, f"La venta {id_venta} figura Completada sin stock aplicado; requiere revisión manual.")
        if estado == "Anulada":
            raise ErrorDominio(CodigoError.VALIDACION, f"La venta {id_venta} está Anulada; no descuenta stock.")
        if estado != "Pendiente" or venta.get("stock_aplicado") is not False or venta.get("receta_aplicada") is not False:
            raise ErrorDominio(CodigoError.INTEGRIDAD, f"La venta {id_venta} tiene estado o marcas de efectos incoherentes.")

        finalizada = finalizar_venta(db, sesion, _pedido_de_pendiente(venta), hoy)
        cambios = {
            **finalizada.campos,
            "items": _fusionar_items(venta["items"], finalizada.campos["items"]),
            "fecha_creacion_pendiente": venta.get("fecha_creacion_pendiente", venta["fecha"]),
        }
        resultado = db.ventas.update_one(
            {"_id": id_venta, "estado": "Pendiente", "stock_aplicado": False, "receta_aplicada": False},
            {"$set": cambios},
            session=sesion,
        )
        if resultado.modified_count != 1:
            raise ErrorDominio(CodigoError.INTEGRIDAD, f"La venta {id_venta} cambió durante la operación; no se aplicó ningún cambio.")
        id_evento = registrar_evento(db, sesion, finalizada.afectadas, instante)
        return {"documento": {**venta, **cambios}, "eventos": [id_evento], "reutilizada": False}

    return ejecutar_transaccion(db, operacion)


def _pedido_de_pendiente(venta: dict) -> PedidoVenta:
    """Reutiliza la normalización de q14 sobre los datos persistidos de la pendiente."""
    try:
        return normalizar_pedido({
            "id_venta": venta["_id"],
            "id_cliente": venta.get("id_cliente"),
            "id_farmaceutico": venta.get("id_farmaceutico"),
            "medio_pago": venta.get("medio_pago"),
            "id_receta": venta.get("id_receta"),
            "items": [{"id_detalle": i.get("id_detalle"), "id_producto": i.get("id_producto"),
                       "cantidad": i.get("cantidad")} for i in venta.get("items") or []],
        })
    except ErrorDominio as error:
        raise ErrorDominio(CodigoError.INTEGRIDAD, f"La venta pendiente {venta['_id']} está mal formada: {error.mensaje}") from None


def _fusionar_items(originales: list[dict], nuevos: list[dict]) -> list[dict]:
    """Aplica precio, subtotal y asignaciones nuevas conservando campos extra (p. ej. traza de importación)."""
    por_detalle = {item["id_detalle"]: item for item in originales}
    return [{**por_detalle.get(nuevo["id_detalle"], {}), **nuevo} for nuevo in nuevos]
