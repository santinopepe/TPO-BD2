import os
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import uuid4

from farmared.clock import FixedClock, inicio_dia_utc
from farmared.config import Config
from farmared.consultas.q12 import q12_clientes_sin_ventas


@unittest.skipUnless(
    any(os.environ.get(k) == "1" for k in ("FARMARED_TEST_MONGO", "FARMARED_TEST_INTEGRACION")),
    "Activar FARMARED_TEST_MONGO=1 con MongoDB replica set de prueba.",
)
class TestQ12Mongo(unittest.TestCase):
    def setUp(self):
        from farmared.conexiones import obtener_mongo
        from farmared.esquema.base_mongo import preparar_mongo_base

        nombre = "farmared_test_c_q12_" + uuid4().hex
        self.db = obtener_mongo(replace(Config.from_env(), mongo_db=nombre))
        self.addCleanup(self.db.client.close)
        self.addCleanup(self.db.client.drop_database, nombre)
        preparar_mongo_base(self.db)
        self.reloj = FixedClock(datetime(2026, 11, 11, 15, tzinfo=UTC))
        self.cliente = self.crear_cliente()
        self.db.clientes.insert_one(self.cliente)

    def crear_cliente(self, numero=1, activo=True):
        return {"_id": f"C-C{numero}", "nombre": "Nombre", "apellido": f"Cliente {numero}",
                "dni": str(90000000 + numero), "email": None, "telefono": None,
                "ciudad": "Rosario", "provincia": "Santa Fe", "obra_social": "Sin cobertura",
                "nro_afiliado": None, "activo": activo}

    def venta(self, id, id_cliente="C-C1", fecha=None, estado="Completada"):
        completada = estado == "Completada"
        return {"_id": id, "id_cliente": id_cliente, "id_farmaceutico": "C-F1", "id_sucursal": "C-S1",
                "id_receta": None, "fecha": inicio_dia_utc(fecha or self.reloj.today()),
                "tipo": "Venta libre", "medio_pago": "Efectivo", "estado": estado, "total": 1000,
                "items": [{"id_detalle": "D1", "id_producto": "C-P1", "cantidad": 1,
                           "precio_unit": 1000, "subtotal": 1000,
                           "asignaciones_lotes": None if completada else []}],
                "stock_aplicado": completada, "receta_aplicada": False, "origen": "csv",
                "trazabilidad_lotes": "desconocida" if completada else "no_aplicada"}

    def test_devuelve_clientes_sin_ventas_o_con_ventas_antiguas(self):
        antiguo = self.crear_cliente(2)
        inactivo = self.crear_cliente(3, activo=False)
        reciente = self.crear_cliente(4)
        self.db.clientes.insert_many([antiguo, inactivo, reciente])
        self.db.ventas.insert_many([
            self.venta("C-V1", id_cliente=antiguo["_id"], fecha=date(2025, 11, 10)),
            self.venta("C-V2", id_cliente=reciente["_id"]),
        ])
        self.assertCountEqual(q12_clientes_sin_ventas(self.db, self.reloj), [self.cliente, antiguo, inactivo])
        self.assertEqual(self.db.ventas.index_information()["ix_ventas_cliente_fecha"]["key"],
                         [("id_cliente", 1), ("fecha", 1)])

    def test_venta_en_inicio_del_periodo_cuenta_como_registrada(self):
        anterior = self.crear_cliente(2)
        self.db.clientes.insert_one(anterior)
        self.db.ventas.insert_many([
            self.venta("C-V1", fecha=date(2025, 11, 11)),
            self.venta("C-V2", id_cliente=anterior["_id"], fecha=date(2025, 11, 10)),
        ])
        self.assertEqual(q12_clientes_sin_ventas(self.db, self.reloj), [anterior])

    def test_cuenta_hoy_y_excluye_manana_segun_buenos_aires(self):
        self.reloj = FixedClock(datetime(2026, 11, 12, 2, 30, tzinfo=UTC))
        futuro = self.crear_cliente(2)
        self.db.clientes.insert_one(futuro)
        self.db.ventas.insert_many([
            self.venta("C-V1", fecha=date(2026, 11, 11)),
            self.venta("C-V2", id_cliente=futuro["_id"], fecha=date(2026, 11, 12)),
        ])
        self.assertEqual(q12_clientes_sin_ventas(self.db, self.reloj), [futuro])

    def test_cualquier_estado_de_venta_reciente_excluye_al_cliente(self):
        pendiente = self.crear_cliente(2)
        anulada = self.crear_cliente(3)
        self.db.clientes.insert_many([pendiente, anulada])
        self.db.ventas.insert_many([
            self.venta("C-V1"),
            self.venta("C-V2", id_cliente=pendiente["_id"], estado="Pendiente"),
            self.venta("C-V3", id_cliente=anulada["_id"], estado="Anulada"),
        ])
        self.assertEqual(q12_clientes_sin_ventas(self.db, self.reloj), [])

    def test_venta_de_cliente_inexistente_no_excluye_otros_clientes(self):
        self.db.ventas.insert_one(self.venta("C-V1", id_cliente="C-INEXISTENTE"))
        self.assertEqual(q12_clientes_sin_ventas(self.db, self.reloj), [self.cliente])

    def test_29_de_febrero_ajusta_inicio_al_28_del_anio_anterior(self):
        self.reloj = FixedClock(datetime(2024, 2, 29, 15, tzinfo=UTC))
        anterior = self.crear_cliente(2)
        hoy = self.crear_cliente(3)
        futuro = self.crear_cliente(4)
        self.db.clientes.insert_many([anterior, hoy, futuro])
        self.db.ventas.insert_many([
            self.venta("C-V1", fecha=date(2023, 2, 28)),
            self.venta("C-V2", id_cliente=anterior["_id"], fecha=date(2023, 2, 27)),
            self.venta("C-V3", id_cliente=hoy["_id"], fecha=date(2024, 2, 29)),
            self.venta("C-V4", id_cliente=futuro["_id"], fecha=date(2024, 3, 1)),
        ])
        self.assertCountEqual(q12_clientes_sin_ventas(self.db, self.reloj), [anterior, futuro])
