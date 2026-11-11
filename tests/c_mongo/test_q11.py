import os
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import uuid4

from farmared.clock import FixedClock, inicio_dia_utc
from farmared.config import Config
from farmared.consultas.q11 import (
    VISTA_INGRESOS_MENSUALES,
    pipeline_ingresos_mensuales,
    q11_ingresos_mensuales,
)


@unittest.skipUnless(
    any(os.environ.get(k) == "1" for k in ("FARMARED_TEST_MONGO", "FARMARED_TEST_INTEGRACION")),
    "Activar FARMARED_TEST_MONGO=1 con MongoDB replica set de prueba.",
)
class TestQ11Mongo(unittest.TestCase):
    def setUp(self):
        from farmared.conexiones import obtener_mongo
        from farmared.esquema.base_mongo import preparar_mongo_base
        from farmared.esquema.consultas_mongo import preparar_consultas_mongo

        nombre = "farmared_test_c_q11_" + uuid4().hex
        self.db = obtener_mongo(replace(Config.from_env(), mongo_db=nombre))
        self.addCleanup(self.db.client.close)
        self.addCleanup(self.db.client.drop_database, nombre)
        preparar_mongo_base(self.db)
        preparar_consultas_mongo(self.db)
        self.reloj = FixedClock(datetime(2026, 11, 11, 15, tzinfo=UTC))
        self.profesional = self.farmaceutico()
        self.db.farmaceuticos.insert_one(self.profesional)

    def farmaceutico(self, id="C-F1", activo=True):
        return {"_id": id, "nombre": "Nombre " + id, "apellido": "Prueba", "matricula": "MN-" + id,
                "cargo": "Farmacéutico", "id_sucursal": "C-S1", "activo": activo}

    def venta(self, id, fecha=None, estado="Completada", id_farmaceutico="C-F1", cantidades=(1,)):
        completada = estado == "Completada"
        items = [{"id_detalle": f"D{i}", "id_producto": "C-P1", "cantidad": cantidad,
                  "precio_unit": 1000, "subtotal": cantidad * 1000,
                  "asignaciones_lotes": None if completada else []}
                 for i, cantidad in enumerate(cantidades, start=1)]
        return {"_id": id, "id_cliente": "C-C1", "id_farmaceutico": id_farmaceutico,
                "id_sucursal": "C-S1", "id_receta": None,
                "fecha": inicio_dia_utc(fecha or self.reloj.today()),
                "tipo": "Venta libre", "medio_pago": "Efectivo", "estado": estado,
                "total": sum(item["subtotal"] for item in items), "items": items,
                "stock_aplicado": completada, "receta_aplicada": False, "origen": "csv",
                "trazabilidad_lotes": "desconocida" if completada else "no_aplicada"}

    def consultar_con_reloj_fijo(self):
        return list(self.db.ventas.aggregate(pipeline_ingresos_mensuales(self.reloj.now_utc())))

    def test_vista_estandar_suma_totales_una_vez_por_venta(self):
        from farmared.esquema.consultas_mongo import preparar_consultas_mongo

        self.reloj = FixedClock(self.db.command("hello")["localTime"].replace(tzinfo=UTC))
        primero = self.reloj.today().replace(day=1)
        otro = self.farmaceutico("C-F2")
        self.db.farmaceuticos.insert_one(otro)
        self.db.ventas.insert_many([
            self.venta("C-V1", fecha=primero, cantidades=(1, 2)),
            self.venta("C-V2", fecha=primero),
            self.venta("C-V3", fecha=primero, id_farmaceutico="C-F2"),
        ])
        preparar_consultas_mongo(self.db)
        vista = next(self.db.list_collections(filter={"name": VISTA_INGRESOS_MENSUALES}))
        self.assertEqual(vista["type"], "view")
        self.assertEqual(vista["options"]["viewOn"], "ventas")
        self.assertEqual(vista["options"]["pipeline"], pipeline_ingresos_mensuales())
        self.assertEqual(self.db.ventas.index_information()["ix_ventas_estado_fecha"]["key"],
                         [("estado", 1), ("fecha", 1)])
        self.assertCountEqual(q11_ingresos_mensuales(self.db), [
            {"_id": "C-F1", "ingresos_totales": 4000, "farmaceutico": self.profesional},
            {"_id": "C-F2", "ingresos_totales": 1000, "farmaceutico": otro},
        ])

    def test_excluye_ventas_pendientes_y_anuladas(self):
        self.db.ventas.insert_many([
            self.venta("C-V1"),
            self.venta("C-V2", estado="Pendiente", cantidades=(10,)),
            self.venta("C-V3", estado="Anulada", cantidades=(20,)),
        ])
        self.assertEqual(self.consultar_con_reloj_fijo(), [
            {"_id": "C-F1", "ingresos_totales": 1000, "farmaceutico": self.profesional},
        ])

    def test_limites_del_mes_segun_buenos_aires(self):
        self.reloj = FixedClock(datetime(2026, 12, 1, 2, 30, tzinfo=UTC))
        self.db.ventas.insert_many([
            self.venta("C-V1", fecha=date(2026, 10, 31)),
            self.venta("C-V2", fecha=date(2026, 11, 1)),
            self.venta("C-V3", fecha=date(2026, 11, 30)),
            self.venta("C-V4", fecha=date(2026, 12, 1)),
        ])
        self.assertEqual(self.consultar_con_reloj_fijo(), [
            {"_id": "C-F1", "ingresos_totales": 2000, "farmaceutico": self.profesional},
        ])

    def test_cambio_de_anio_y_febrero_bisiesto(self):
        casos = [
            (datetime(2027, 1, 15, 15, tzinfo=UTC),
             [date(2026, 12, 31), date(2027, 1, 1), date(2027, 1, 31), date(2027, 2, 1)]),
            (datetime(2024, 2, 29, 15, tzinfo=UTC),
             [date(2024, 1, 31), date(2024, 2, 1), date(2024, 2, 29), date(2024, 3, 1)]),
        ]
        for instante, fechas in casos:
            with self.subTest(instante=instante):
                self.reloj = FixedClock(instante)
                self.db.ventas.delete_many({})
                self.db.ventas.insert_many([self.venta(f"C-V{i}", fecha=fecha)
                                           for i, fecha in enumerate(fechas)])
                self.assertEqual(self.consultar_con_reloj_fijo(), [
                    {"_id": "C-F1", "ingresos_totales": 2000, "farmaceutico": self.profesional},
                ])

    def test_incluye_inactivos_con_ingresos_y_omite_profesionales_sin_ventas(self):
        inactivo = self.farmaceutico("C-F2", activo=False)
        self.db.farmaceuticos.insert_one(inactivo)
        self.db.ventas.insert_one(self.venta("C-V1", id_farmaceutico="C-F2"))
        self.assertEqual(self.consultar_con_reloj_fijo(), [
            {"_id": "C-F2", "ingresos_totales": 1000, "farmaceutico": inactivo},
        ])

    def test_sin_completadas_del_mes_devuelve_lista_vacia(self):
        self.db.ventas.insert_many([
            self.venta("C-V1", fecha=date(2026, 10, 31)),
            self.venta("C-V2", estado="Pendiente"),
        ])
        self.assertEqual(self.consultar_con_reloj_fijo(), [])
