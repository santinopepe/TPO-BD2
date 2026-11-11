"""q14 — Registro de una nueva venta 'Completada' (cabecera e ítems).

Propósito: registrar una venta validando cliente existente y activo;
farmacéutico existente, activo y de una sucursal tipo 'Farmacia'; productos
existentes y activos; y, si hay productos bajo receta, receta existente,
Vigente y del mismo cliente. El total se calcula con los precios vigentes del
catálogo y la receta se actualiza según las reglas de negocio.

Motor: MongoDB. Venta, descuento FEFO de todos los lotes (q15 integrada),
dispensa de receta y evento outbox se confirman en UNA transacción; si algo
falla no queda nada modificado. Neo4j no participa: se proyecta luego con sync.

Idempotencia: `id_venta` identifica la operación. Repetir el mismo pedido
devuelve la venta ya confirmada (`reutilizada=True`, sin eventos nuevos ni
nuevos descuentos); el mismo id con otro pedido es CONFLICTO_ID.
"""

from collections.abc import Mapping

from pymongo.errors import DuplicateKeyError

from farmared.clock import Clock
from farmared.contratos import ResultadoEscritura
from farmared.errores import CodigoError, ErrorDominio
from farmared.servicios.ventas.coordinador import finalizar_venta
from farmared.servicios.ventas.escritura import registrar_evento
from farmared.servicios.ventas.idempotencia import request_hash
from farmared.servicios.ventas.lectura import leer_venta
from farmared.servicios.ventas.pedido import normalizar_pedido
from farmared.servicios.ventas.transaccion import ejecutar_transaccion


def q14_registrar_venta(db, pedido: Mapping, clock: Clock) -> ResultadoEscritura:
    """Registra la venta Completada descrita por `pedido`.

    Parámetros:
        db: Database de PyMongo (replica set).
        pedido: {"id_venta", "id_cliente", "id_farmaceutico", "medio_pago",
                 "items": [{"id_producto", "cantidad", "id_detalle"?}], "id_receta"?}
        clock: reloj de negocio; el día comercial se captura una vez por llamada.

    Retorna {"documento": venta, "eventos": [id_evento], "reutilizada": bool}.
    Errores: ErrorDominio con VALIDACION, NO_EXISTE, RECETA_INVALIDA,
    STOCK_INSUFICIENTE, CONFLICTO_ID, INTEGRIDAD o CONEXION.
    """
    normalizado = normalizar_pedido(pedido)
    huella = request_hash(normalizado)
    hoy = clock.today()
    instante = clock.now_utc()

    def operacion(sesion) -> ResultadoEscritura:
        existente = leer_venta(db, sesion, normalizado.id_venta)
        if existente is not None:
            return _reutilizar(existente, huella)
        finalizada = finalizar_venta(db, sesion, normalizado, hoy)
        documento = {"_id": normalizado.id_venta, **finalizada.campos,
                     "origen": "servicio", "request_hash": huella}
        db.ventas.insert_one(documento, session=sesion)
        id_evento = registrar_evento(db, sesion, finalizada.afectadas, instante)
        return {"documento": documento, "eventos": [id_evento], "reutilizada": False}

    try:
        return ejecutar_transaccion(db, operacion)
    except DuplicateKeyError:
        # Otro intento con el mismo id confirmó entre nuestra lectura y el insert.
        confirmada = ejecutar_transaccion(db, lambda s: db.ventas.find_one({"_id": normalizado.id_venta}, session=s))
        if confirmada is None:
            raise ErrorDominio(CodigoError.INTEGRIDAD, "Colisión de identidad sin venta confirmada; reintentar con el mismo id_venta.") from None
        return _reutilizar(confirmada, huella)


def _reutilizar(existente: dict, huella: str) -> ResultadoEscritura:
    if existente.get("request_hash") != huella:
        raise ErrorDominio(
            CodigoError.CONFLICTO_ID,
            f"El id_venta {existente['_id']} ya corresponde a otra venta u otro pedido; usar un id nuevo.",
        )
    return {"documento": existente, "eventos": [], "reutilizada": True}
