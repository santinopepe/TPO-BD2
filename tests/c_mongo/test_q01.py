import os
import unittest
from dataclasses import replace
from uuid import uuid4

from farmared.config import Config
from farmared.consultas.q01 import q01_productos_activos


@unittest.skipUnless(
    any(os.environ.get(k) == "1" for k in ("FARMARED_TEST_MONGO", "FARMARED_TEST_INTEGRACION")),
    "Activar FARMARED_TEST_MONGO=1 con MongoDB replica set de prueba.",
)
class TestQ01Mongo(unittest.TestCase):
    def setUp(self):
        from farmared.conexiones import obtener_mongo
        from farmared.esquema.base_mongo import preparar_mongo_base

        nombre = "farmared_test_c_q01_" + uuid4().hex
        self.db = obtener_mongo(replace(Config.from_env(), mongo_db=nombre))
        self.addCleanup(self.db.client.close)
        self.addCleanup(self.db.client.drop_database, nombre)
        preparar_mongo_base(self.db)

    def producto(self, id="C-P1", activo=True, id_proveedor="C-PRV1"):
        return {"_id": id, "nombre": "Producto de prueba", "principio_activo": "Paracetamol",
                "categoria": "Analgésico", "presentacion": "Caja", "condicion_venta": "Venta libre",
                "precio_unit": 1000, "id_proveedor": id_proveedor, "activo": activo}

    def proveedor(self):
        return {"_id": "C-PRV1", "razon_social": "Laboratorio de prueba", "cuit": "30-00000000-1",
                "tipo": "Laboratorio", "ciudad": "Rosario", "provincia": "Santa Fe",
                "telefono": "3411234567", "activo": False}

    def test_excluye_productos_inactivos(self):
        self.db.proveedores.insert_one(self.proveedor())
        self.db.productos.insert_many([
            self.producto("C-P1", activo=False),
            self.producto("C-P2", activo=False),
        ])
        self.assertEqual(q01_productos_activos(self.db), [])

    def test_conserva_producto_con_id_proveedor_inexistente(self):
        self.db.proveedores.insert_one(self.proveedor())
        producto = self.producto(id_proveedor="C-PRV-INEXISTENTE")
        self.db.productos.insert_one(producto)
        self.assertEqual(q01_productos_activos(self.db), [producto])

    def test_devuelve_producto_activo_con_proveedor_completo(self):
        producto = self.producto()
        proveedor = self.proveedor()
        self.db.productos.insert_one(producto)
        self.db.proveedores.insert_one(proveedor)
        self.assertEqual(q01_productos_activos(self.db), [{**producto, "proveedor": proveedor}])
