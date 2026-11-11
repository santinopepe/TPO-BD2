import os
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from farmared.config import Config
from farmared.consultas.q07 import q07_top_productos


@unittest.skipUnless(
    any(os.environ.get(k) == "1" for k in ("FARMARED_TEST_MONGO", "FARMARED_TEST_INTEGRACION")),
    "Activar FARMARED_TEST_MONGO=1 con MongoDB replica set de prueba.",
)
class TestQ07Mongo(unittest.TestCase):
    def setUp(self):
        from farmared.conexiones import obtener_mongo
        from farmared.esquema.base_mongo import preparar_mongo_base

        nombre = "farmared_test_c_q07_" + uuid4().hex
        self.db = obtener_mongo(replace(Config.from_env(), mongo_db=nombre))
        self.addCleanup(self.db.client.close)
        self.addCleanup(self.db.client.drop_database, nombre)
        preparar_mongo_base(self.db)

    def producto(self, id="C-P1", activo=True):
        return {"_id": id, "nombre": "Producto " + id, "principio_activo": None,
                "categoria": "Higiene", "presentacion": "Caja", "condicion_venta": "Venta libre",
                "precio_unit": 1000, "id_proveedor": "C-PRV1", "activo": activo}

    def venta(self, id, productos, estado="Completada"):
        completada = estado == "Completada"
        items = [{"id_detalle": f"D{i}", "id_producto": producto, "cantidad": cantidad,
                  "precio_unit": 1000, "subtotal": cantidad * 1000,
                  "asignaciones_lotes": None if completada else []}
                 for i, (producto, cantidad) in enumerate(productos, start=1)]
        return {"_id": id, "id_cliente": "C-C1", "id_farmaceutico": "C-F1", "id_sucursal": "C-S1",
                "id_receta": None, "fecha": datetime(2026, 11, 11, 3, tzinfo=UTC),
                "tipo": "Venta libre", "medio_pago": "Efectivo", "estado": estado,
                "total": sum(item["subtotal"] for item in items), "items": items,
                "stock_aplicado": completada, "receta_aplicada": False, "origen": "csv",
                "trazabilidad_lotes": "desconocida" if completada else "no_aplicada"}

    def test_devuelve_top_cinco_con_productos_completos(self):
        productos = [self.producto(f"C-P{i}", activo=i != 6) for i in range(1, 7)]
        self.db.productos.insert_many(productos)
        self.db.ventas.insert_one(self.venta("C-V1", [(f"C-P{i}", i) for i in range(1, 7)]))
        esperado = [{"_id": f"C-P{i}", "unidades_vendidas": i, "producto": productos[i - 1]}
                    for i in range(6, 1, -1)]
        self.assertEqual(q07_top_productos(self.db), esperado)

    def test_excluye_ventas_pendientes_y_anuladas(self):
        producto = self.producto()
        self.db.productos.insert_one(producto)
        self.db.ventas.insert_many([
            self.venta("C-V1", [("C-P1", 2)]),
            self.venta("C-V2", [("C-P1", 100)], estado="Pendiente"),
            self.venta("C-V3", [("C-P1", 200)], estado="Anulada"),
        ])
        self.assertEqual(q07_top_productos(self.db), [
            {"_id": "C-P1", "unidades_vendidas": 2, "producto": producto},
        ])

    def test_sin_ventas_devuelve_lista_vacia(self):
        self.db.productos.insert_one(self.producto())
        self.assertEqual(q07_top_productos(self.db), [])

    def test_suma_lineas_repetidas_y_distintas_ventas(self):
        productos = [self.producto("C-P1"), self.producto("C-P2")]
        self.db.productos.insert_many(productos)
        self.db.ventas.insert_many([
            self.venta("C-V1", [("C-P1", 2), ("C-P1", 3), ("C-P2", 8)]),
            self.venta("C-V2", [("C-P1", 4)]),
        ])
        self.assertEqual(q07_top_productos(self.db), [
            {"_id": "C-P1", "unidades_vendidas": 9, "producto": productos[0]},
            {"_id": "C-P2", "unidades_vendidas": 8, "producto": productos[1]},
        ])

    def test_desempata_por_id_al_limitar_a_cinco(self):
        productos = [self.producto(f"C-P{i}") for i in range(6, 0, -1)]
        self.db.productos.insert_many(productos)
        self.db.ventas.insert_one(self.venta("C-V1", [(p["_id"], 1) for p in productos]))
        esperado = [{"_id": p["_id"], "unidades_vendidas": 1, "producto": p}
                    for p in sorted(productos, key=lambda p: p["_id"])[:5]]
        self.assertEqual(q07_top_productos(self.db), esperado)

    def test_conserva_unidades_de_producto_inexistente(self):
        self.db.ventas.insert_one(self.venta("C-V1", [("C-INEXISTENTE", 3)]))
        self.assertEqual(q07_top_productos(self.db), [
            {"_id": "C-INEXISTENTE", "unidades_vendidas": 3},
        ])
