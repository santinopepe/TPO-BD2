import os
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from farmared.clock import FixedClock, inicio_dia_utc
from farmared.config import Config
from farmared.consultas.q05 import q05_ventas_por_farmaceutico


@unittest.skipUnless(
    any(os.environ.get(k) == "1" for k in ("FARMARED_TEST_MONGO", "FARMARED_TEST_INTEGRACION")),
    "Activar FARMARED_TEST_MONGO=1 con MongoDB replica set de prueba.",
)
class TestQ05Mongo(unittest.TestCase):
    def setUp(self):
        from farmared.conexiones import obtener_mongo
        from farmared.esquema.base_mongo import preparar_mongo_base

        nombre = "farmared_test_c_q05_" + uuid4().hex
        self.db = obtener_mongo(replace(Config.from_env(), mongo_db=nombre))
        self.addCleanup(self.db.client.close)
        self.addCleanup(self.db.client.drop_database, nombre)
        preparar_mongo_base(self.db)
        self.reloj = FixedClock(datetime(2026, 11, 11, 15, tzinfo=UTC))
        self.profesional = self.farmaceutico()
        self.db.farmaceuticos.insert_one(self.profesional)

    def farmaceutico(self, id="C-F1", activo=True):
        return {"_id": id, "nombre": "Nombre " + id, "apellido": "Prueba", "matricula": "MN-" + id,
                "cargo": "Farmacéutico", "id_sucursal": "C-S1", "activo": activo}

    def venta(self, id, id_farmaceutico="C-F1", dias=0, estado="Completada", cantidad=3):
        completada = estado == "Completada"
        total = cantidad * 1000
        return {"_id": id, "id_cliente": "C-C1", "id_farmaceutico": id_farmaceutico,
                "id_sucursal": "C-S1", "id_receta": None,
                "fecha": inicio_dia_utc(self.reloj.today() + timedelta(days=dias)),
                "tipo": "Venta libre", "medio_pago": "Efectivo", "estado": estado, "total": total,
                "items": [{"id_detalle": "D1", "id_producto": "C-P1", "cantidad": cantidad,
                           "precio_unit": 1000, "subtotal": total,
                           "asignaciones_lotes": None if completada else []}],
                "stock_aplicado": completada, "receta_aplicada": False, "origen": "csv",
                "trazabilidad_lotes": "desconocida" if completada else "no_aplicada"}

    def test_cuenta_ventas_por_farmaceutico(self):
        otro = self.farmaceutico("C-F2")
        self.db.farmaceuticos.insert_one(otro)
        self.db.ventas.insert_many([
            self.venta("C-V1", cantidad=10),
            self.venta("C-V2", dias=-10, cantidad=20),
            self.venta("C-V3", id_farmaceutico="C-F2", cantidad=7),
        ])
        self.assertCountEqual(q05_ventas_por_farmaceutico(self.db, self.reloj), [
            {**self.profesional, "cantidad_ventas": 2},
            {**otro, "cantidad_ventas": 1},
        ])
        self.assertEqual(self.db.ventas.index_information()["ix_ventas_farmaceutico_fecha"]["key"],
                         [("id_farmaceutico", 1), ("fecha", 1)])

    def test_incluye_profesional_sin_ventas_con_cero(self):
        self.db.ventas.insert_one(self.venta("C-V1", id_farmaceutico="C-INEXISTENTE"))
        self.assertEqual(q05_ventas_por_farmaceutico(self.db, self.reloj), [
            {**self.profesional, "cantidad_ventas": 0},
        ])

    def test_excluye_profesional_inactivo_aunque_tenga_ventas(self):
        self.db.farmaceuticos.insert_one(self.farmaceutico("C-F2", activo=False))
        self.db.ventas.insert_one(self.venta("C-V1", id_farmaceutico="C-F2"))
        self.assertEqual(q05_ventas_por_farmaceutico(self.db, self.reloj), [
            {**self.profesional, "cantidad_ventas": 0},
        ])

    def test_respeta_limites_de_los_sesenta_dias(self):
        self.db.ventas.insert_many([
            self.venta("C-V1", dias=-59),
            self.venta("C-V2", dias=-60),
            self.venta("C-V3", dias=0),
            self.venta("C-V4", dias=1),
        ])
        self.assertEqual(q05_ventas_por_farmaceutico(self.db, self.reloj), [
            {**self.profesional, "cantidad_ventas": 2},
        ])

    def test_cuenta_pendientes_y_completadas_pero_no_anuladas(self):
        self.db.ventas.insert_many([
            self.venta("C-V1", estado="Completada"),
            self.venta("C-V2", estado="Pendiente"),
            self.venta("C-V3", estado="Anulada"),
        ])
        self.assertEqual(q05_ventas_por_farmaceutico(self.db, self.reloj), [
            {**self.profesional, "cantidad_ventas": 2},
        ])

    def test_usa_dia_de_buenos_aires_cerca_de_medianoche_utc(self):
        self.reloj = FixedClock(datetime(2026, 11, 12, 2, 30, tzinfo=UTC))
        self.db.ventas.insert_many([
            self.venta("C-V1", dias=0),
            self.venta("C-V2", dias=1),
        ])
        self.assertEqual(q05_ventas_por_farmaceutico(self.db, self.reloj), [
            {**self.profesional, "cantidad_ventas": 1},
        ])
