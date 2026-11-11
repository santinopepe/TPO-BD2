"""Escrituras condicionales de la venta dentro de la transacción del llamador.

Ninguna función abre sesión, confirma ni aborta: solo escriben con `sesion`.
Cada update lleva en el filtro las condiciones que lo hacen válido y se
verifica que haya modificado exactamente un documento; si no, se lanza
ErrorDominio y el llamador aborta toda la transacción.

Bajo read concern snapshot, si otra transacción confirmó un cambio sobre el
mismo lote/receta después de nuestra lectura, el motor responde WriteConflict
(TransientTransactionError) y with_transaction reintenta todo con un snapshot
nuevo. Un filtro que no coincide indica entonces una incoherencia con nuestra
propia lectura, no una carrera: se trata como INTEGRIDAD.
"""

from collections.abc import Iterable, Mapping
from datetime import date, datetime
from uuid import uuid4

from farmared.clock import inicio_dia_utc
from farmared.contratos import EntidadAfectada
from farmared.errores import CodigoError, ErrorDominio
from farmared.servicios.ventas.fefo import ConsumoLote


def descontar_lotes(db, sesion, plan: Iterable[ConsumoLote], id_sucursal: str, hoy: date) -> None:
    """Descuenta cada consumo solo si el lote sigue siendo de esa sucursal/producto, vigente y con saldo."""
    vigente_desde = inicio_dia_utc(hoy)
    for consumo in plan:
        resultado = db.stock_lotes.update_one(
            {
                "_id": consumo.id_lote,
                "id_producto": consumo.id_producto,
                "id_sucursal": id_sucursal,
                "unidades": {"$gte": consumo.cantidad},
                "vencimiento": {"$gte": vigente_desde},
            },
            {"$inc": {"unidades": -consumo.cantidad}},
            session=sesion,
        )
        if resultado.modified_count != 1:
            raise ErrorDominio(CodigoError.INTEGRIDAD, f"El lote {consumo.id_lote} no admitió el descuento planificado; no se aplicó ningún cambio.")


def aplicar_dispensa(db, sesion, receta: Mapping, cambios: Mapping) -> None:
    """Aplica la transición de receta solo si sigue Vigente con el contador leído."""
    resultado = db.recetas.update_one(
        {"_id": receta["_id"], "estado": "Vigente", "dispensas_realizadas": receta["dispensas_realizadas"]},
        {"$set": dict(cambios)},
        session=sesion,
    )
    if resultado.modified_count != 1:
        raise ErrorDominio(CodigoError.INTEGRIDAD, f"La receta {receta['_id']} cambió durante la operación; no se aplicó ningún cambio.")


def registrar_evento(db, sesion, afectadas: Iterable[EntidadAfectada], instante: datetime) -> str:
    """Inserta el evento outbox (contrato §2.3) en la misma transacción; devuelve su id.

    El evento solo indica qué releer; el proyector de D toma el estado actual.
    """
    lista = [{"coleccion": a["coleccion"], "id": a["id"]} for a in afectadas]
    if not lista:
        raise ErrorDominio(CodigoError.INTEGRIDAD, "Un evento outbox requiere al menos una entidad afectada.")
    evento = {
        "_id": str(uuid4()),
        "afectadas": lista,
        "procesado": False,
        # BSON Date guarda milisegundos: se trunca para que el retorno coincida con lo persistido.
        "creado_en": instante.replace(microsecond=instante.microsecond // 1000 * 1000),
    }
    db.outbox.insert_one(evento, session=sesion)
    return evento["_id"]
