"""Huella del pedido de q14 para distinguir un reintento de un conflicto de id."""

import hashlib
import json

from farmared.servicios.ventas.pedido import PedidoVenta

VERSION_HASH = 1


def request_hash(pedido: PedidoVenta) -> str:
    """SHA-256 hex del pedido normalizado, en JSON canónico.

    Incluye todos los campos del pedido y el orden de las líneas: el mismo
    `id_venta` con otro contenido u otro orden es un pedido distinto. Cambiar
    la forma canónica exige subir VERSION_HASH.
    """
    canonico = {
        "version": VERSION_HASH,
        "id_venta": pedido.id_venta,
        "id_cliente": pedido.id_cliente,
        "id_farmaceutico": pedido.id_farmaceutico,
        "id_receta": pedido.id_receta,
        "medio_pago": pedido.medio_pago,
        "items": [
            {"id_detalle": i.id_detalle, "id_producto": i.id_producto, "cantidad": i.cantidad}
            for i in pedido.items
        ],
    }
    texto = json.dumps(canonico, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()
