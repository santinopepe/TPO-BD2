import os
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from farmared.config import Config
from farmared.consultas.q08 import q08_lotes_stock_bajo


@unittest.skipUnless(
    any(os.environ.get(k) == "1" for k in ("FARMARED_TEST_MONGO", "FARMARED_TEST_INTEGRACION")),
    "Activar FARMARED_TEST_MONGO=1 con MongoDB replica set de prueba.",
)
class TestQ08Mongo(unittest.TestCase):
    def setUp(self):
        from farmared.conexiones import obtener_mongo
        from farmared.esquema.base_mongo import preparar_mongo_base

        nombre = "farmared_test_c_q08_" + uuid4().hex
        self.db = obtener_mongo(replace(Config.from_env(), mongo_db=nombre))
        self.addCleanup(self.db.client.close)
        self.addCleanup(self.db.client.drop_database, nombre)
        preparar_mongo_base(self.db)
        self.producto = {"_id": "C-P1", "nombre": "Producto de prueba", "principio_activo": None,
                         "categoria": "Higiene", "presentacion": "Caja", "condicion_venta": "Venta libre",
                         "precio_unit": 1000, "id_proveedor": "C-PRV1", "activo": False}
        self.proveedor = {"_id": "C-PRV1", "razon_social": "Laboratorio de prueba", "cuit": "30-00000000-1",
                          "tipo": "Laboratorio", "ciudad": "Rosario", "provincia": "Santa Fe",
                          "telefono": None, "activo": False}
        self.sucursal = {"_id": "C-S1", "nombre": "Sucursal de prueba", "tipo": "Farmacia",
                         "direccion": "Calle 123", "ciudad": "Rosario", "provincia": "Santa Fe",
                         "telefono": None, "activo": False}
        self.db.productos.insert_one(self.producto)
        self.db.proveedores.insert_one(self.proveedor)
        self.db.sucursales.insert_one(self.sucursal)

    def lote(self, **cambios):
        documento = {"_id": "C-L1", "id_producto": "C-P1", "id_sucursal": "C-S1",
                     "nro_lote": "N-1", "unidades": 49, "vencimiento": datetime(2020, 1, 1, 3, tzinfo=UTC)}
        documento.update(cambios)
        return documento

    def test_excluye_lotes_de_60_unidades(self):
        self.db.stock_lotes.insert_one(self.lote(unidades=60))
        self.assertEqual(q08_lotes_stock_bajo(self.db), [])

    def test_devuelve_lotes_con_producto_proveedor_y_sucursal(self):
        lotes = [self.lote(), self.lote(_id="C-L2", unidades=0)]
        self.db.stock_lotes.insert_many(lotes)
        esperado = [{**lote, "producto": self.producto, "proveedor": self.proveedor,
                     "sucursal": self.sucursal} for lote in lotes]
        self.assertCountEqual(q08_lotes_stock_bajo(self.db), esperado)

    def test_conserva_lotes_con_referencias_inexistentes(self):
        producto = {**self.producto, "_id": "C-P2", "id_proveedor": "C-PRV-INEXISTENTE"}
        self.db.productos.insert_one(producto)
        sin_referencias = self.lote(id_producto="C-P-INEXISTENTE", id_sucursal="C-S-INEXISTENTE")
        sin_proveedor = self.lote(_id="C-L2", id_producto="C-P2")
        self.db.stock_lotes.insert_many([sin_referencias, sin_proveedor])
        self.assertCountEqual(q08_lotes_stock_bajo(self.db), [
            sin_referencias,
            {**sin_proveedor, "producto": producto, "sucursal": self.sucursal},
        ])
