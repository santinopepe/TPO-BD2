"""Coordinador único de q14/q15: valida, valoriza, aplica FEFO y receta en la sesión dada.

No abre ni confirma la transacción y no escribe la venta ni el outbox: devuelve
los campos de la venta completada para que q14 la inserte o q15 transicione la
pendiente. Así ambas rutas comparten exactamente las mismas reglas.

Orden de validación (el primer problema define el error):
cliente → farmacéutico → sucursal → productos → receta → precios → stock.
"""

from dataclasses import dataclass
from datetime import date

from farmared.clock import inicio_dia_utc
from farmared.servicios.ventas.escritura import aplicar_dispensa, descontar_lotes
from farmared.servicios.ventas.fefo import demanda_por_producto, distribuir_asignaciones, planificar_fefo
from farmared.servicios.ventas.habilitacion import (
    validar_cliente,
    validar_farmaceutico,
    validar_productos,
    validar_sucursal,
)
from farmared.servicios.ventas.lectura import leer_lotes_vigentes, leer_snapshot
from farmared.servicios.ventas.pedido import PedidoVenta
from farmared.servicios.ventas.precios import valorizar
from farmared.servicios.ventas.receta import requiere_receta, tipo_venta, transicion_receta, validar_receta

TRAZABILIDAD_REGISTRADA = "registrada"  # Pendiente de Literal común en contratos.py (Persona A).


@dataclass(frozen=True)
class VentaFinalizada:
    campos: dict          # Campos de la venta Completada, sin _id, origen ni request_hash.
    afectadas: list[dict]  # Entidades para el evento outbox.


def finalizar_venta(db, sesion, pedido: PedidoVenta, hoy: date) -> VentaFinalizada:
    """Aplica stock y receta de `pedido` en la transacción de `sesion` o lanza ErrorDominio."""
    ids_productos = [item.id_producto for item in pedido.items]
    snap = leer_snapshot(db, sesion, id_cliente=pedido.id_cliente, id_farmaceutico=pedido.id_farmaceutico,
                         ids_productos=ids_productos, id_receta=pedido.id_receta)

    validar_cliente(snap.cliente, pedido.id_cliente)
    id_sucursal = validar_farmaceutico(snap.farmaceutico, pedido.id_farmaceutico)
    validar_sucursal(snap.sucursal, id_sucursal)
    validar_productos(snap.productos, ids_productos)
    requiere = requiere_receta(snap.productos[i] for i in ids_productos)
    validar_receta(snap.receta, pedido.id_receta, pedido.id_cliente, requiere)
    lineas, total = valorizar(pedido.items, snap.productos)

    lotes = leer_lotes_vigentes(db, sesion, id_sucursal, ids_productos, hoy)
    plan = planificar_fefo(demanda_por_producto(pedido.items), lotes, hoy, id_sucursal)
    descontar_lotes(db, sesion, plan, id_sucursal, hoy)
    asignaciones = distribuir_asignaciones(pedido.items, plan)

    afectadas = [{"coleccion": "ventas", "id": pedido.id_venta}]
    if requiere:
        aplicar_dispensa(db, sesion, snap.receta, transicion_receta(snap.receta, hoy))
        afectadas.append({"coleccion": "recetas", "id": pedido.id_receta})

    campos = {
        "id_cliente": pedido.id_cliente,
        "id_farmaceutico": pedido.id_farmaceutico,
        "id_sucursal": id_sucursal,
        "id_receta": pedido.id_receta,
        "fecha": inicio_dia_utc(hoy),
        "tipo": tipo_venta(requiere),
        "medio_pago": pedido.medio_pago,
        "estado": "Completada",
        "total": total,
        "items": [
            {
                "id_detalle": linea.id_detalle,
                "id_producto": linea.id_producto,
                "cantidad": linea.cantidad,
                "precio_unit": linea.precio_unit,
                "subtotal": linea.subtotal,
                "asignaciones_lotes": [
                    {"id_lote": a.id_lote, "cantidad": a.cantidad} for a in asignaciones[linea.id_detalle]
                ],
            }
            for linea in lineas
        ],
        "stock_aplicado": True,
        "receta_aplicada": requiere,
        "trazabilidad_lotes": TRAZABILIDAD_REGISTRADA,
    }
    return VentaFinalizada(campos=campos, afectadas=afectadas)
