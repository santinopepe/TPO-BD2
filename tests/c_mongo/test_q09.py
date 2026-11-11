import os
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from farmared.config import Config
from farmared.consultas.q09 import q09_ventas_libres


@unittest.skipUnless(
    any(os.environ.get(k) == "1" for k in ("FARMARED_TEST_MONGO", "FARMARED_TEST_INTEGRACION")),
    "Activar FARMARED_TEST_MONGO=1 con MongoDB replica set de prueba.",
)
class TestQ09Mongo(unittest.TestCase):
    def setUp(self):
        from farmared.conexiones import obtener_mongo
        from farmared.esquema.base_mongo import preparar_mongo_base

        nombre = "farmared_test_c_q09_" + uuid4().hex
        self.db = obtener_mongo(replace(Config.from_env(), mongo_db=nombre))
        self.addCleanup(self.db.client.close)
        self.addCleanup(self.db.client.drop_database, nombre)
        preparar_mongo_base(self.db)

    def venta(self, id="C-V1", total=4999, estado="Completada", tipo="Venta libre"):
        completada = estado == "Completada"
        return {"_id": id, "id_cliente": "C-C1", "id_farmaceutico": "C-F1",
                "id_sucursal": "C-S1", "id_receta": "C-R1" if tipo == "Con receta" else None, "fecha": datetime(2026, 11, 11, 3, tzinfo=UTC),
                "tipo": tipo, "medio_pago": "Efectivo", "estado": estado, "total": total,
                "items": [{"id_detalle": "D1", "id_producto": "C-P1", "cantidad": 1,
                           "precio_unit": total, "subtotal": total,
                           "asignaciones_lotes": None if completada else []}],
                "stock_aplicado": completada, "receta_aplicada": completada and tipo == "Con receta", "origen": "csv",
                "trazabilidad_lotes": "desconocida" if completada else "no_aplicada"}

    def test_incluye_ventas_que_cumplen_todas_las_condiciones(self):
        ventas = [self.venta("C-V1"), self.venta("C-V2", estado="Pendiente")]
        self.db.ventas.insert_many(ventas)
        self.assertCountEqual(q09_ventas_libres(self.db), ventas)

    def test_excluye_venta_que_no_es_libre(self):
        self.db.ventas.insert_one(self.venta(tipo="Con receta"))
        self.assertEqual(q09_ventas_libres(self.db), [])

    def test_excluye_total_igual_a_5000(self):
        self.db.ventas.insert_one(self.venta(total=5000))
        self.assertEqual(q09_ventas_libres(self.db), [])

    def test_excluye_venta_anulada(self):
        self.db.ventas.insert_one(self.venta(estado="Anulada"))
        self.assertEqual(q09_ventas_libres(self.db), [])
