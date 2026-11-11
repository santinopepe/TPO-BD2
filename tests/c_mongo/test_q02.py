from dataclasses import replace
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from uuid import uuid4

from farmared.config import Config
from farmared.consultas.q02 import q02_ventas_pendientes


@unittest.skipUnless(
    any(os.environ.get(k) == "1" for k in ("FARMARED_TEST_MONGO", "FARMARED_TEST_INTEGRACION")),
    "Activar FARMARED_TEST_MONGO=1 con MongoDB replica set de prueba.",
)
class TestQ02Mongo(unittest.TestCase):
    def setUp(self):
        from farmared.conexiones import obtener_mongo
        from farmared.esquema.base_mongo import preparar_mongo_base

        nombre = "farmared_test_c_q02_" + uuid4().hex
        self.db = obtener_mongo(replace(Config.from_env(), mongo_db=nombre))
        self.addCleanup(self.db.client.close)
        self.addCleanup(self.db.client.drop_database, nombre)
        preparar_mongo_base(self.db)
        self.sucursal = {"_id": "C-S1", "nombre": "Sucursal de prueba", "tipo": "Farmacia",
                         "direccion": "Calle 123", "ciudad": "Rosario", "provincia": "Santa Fe",
                         "telefono": None, "activo": True}
        self.farmaceutico = {"_id": "C-F1", "nombre": "Luis", "apellido": "Prueba",
                             "matricula": "MN-C1", "cargo": "Farmacéutico",
                             "id_sucursal": "C-S1", "activo": True}
        self.db.sucursales.insert_one(self.sucursal)
        self.db.farmaceuticos.insert_one(self.farmaceutico)

    def venta(self, **cambios):
        documento = {"_id": "C-V1", "id_cliente": "C-C1", "id_farmaceutico": "C-F1",
                     "id_sucursal": "C-S1", "id_receta": None,
                     "fecha": datetime(2026, 11, 1, 3, tzinfo=UTC), "tipo": "Venta libre",
                     "medio_pago": "Efectivo", "estado": "Pendiente", "total": 1000,
                     "items": [{"id_detalle": "C-D1", "id_producto": "C-P1", "cantidad": 2,
                                "precio_unit": 500, "subtotal": 1000, "asignaciones_lotes": []}],
                     "stock_aplicado": False, "receta_aplicada": False,
                     "origen": "csv", "trazabilidad_lotes": "no_aplicada"}
        documento.update(cambios)
        return documento

    def test_devuelve_venta_pendiente_con_profesional_sucursal_y_total(self):
        anterior = {**self.sucursal, "_id": "C-S-ANTERIOR", "nombre": "Sucursal anterior"}
        self.db.sucursales.insert_one(anterior)
        venta = self.venta(id_sucursal=anterior["_id"])
        self.db.ventas.insert_one(venta)
        esperado = [{**venta, "farmaceutico": self.farmaceutico, "sucursal": self.sucursal}]
        antes = {c: list(self.db[c].find().sort("_id", 1))
                 for c in ("ventas", "farmaceuticos", "sucursales", "outbox")}
        self.assertEqual(q02_ventas_pendientes(self.db), esperado)
        resultado = subprocess.run(
            [sys.executable, "-m", "farmared", "q02", "--base", self.db.name],
            cwd=Path(__file__).resolve().parents[2], env=os.environ.copy(),
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertEqual(resultado.stderr, "")
        self.assertEqual(json.loads(resultado.stdout), {
            "consulta": "q02", "base": self.db.name,
            "resultados": json.loads(json.dumps(esperado, default=lambda valor: valor.isoformat())),
        })
        self.assertEqual({c: list(self.db[c].find().sort("_id", 1)) for c in antes}, antes)

    def test_excluye_ventas_completadas_y_anuladas(self):
        self.db.ventas.insert_many([
            self.venta(estado="Completada"),
            self.venta(_id="C-V2", estado="Anulada"),
        ])
        self.assertEqual(q02_ventas_pendientes(self.db), [])

    def test_conserva_venta_con_farmaceutico_y_sucursal_inactivos(self):
        self.db.farmaceuticos.update_one({"_id": self.farmaceutico["_id"]}, {"$set": {"activo": False}})
        self.db.sucursales.update_one({"_id": self.sucursal["_id"]}, {"$set": {"activo": False}})
        venta = self.venta()
        self.db.ventas.insert_one(venta)
        self.assertEqual(q02_ventas_pendientes(self.db), [{
            **venta, "farmaceutico": {**self.farmaceutico, "activo": False},
            "sucursal": {**self.sucursal, "activo": False},
        }])

    def test_conserva_venta_con_farmaceutico_inexistente(self):
        venta = self.venta(id_farmaceutico="C-F-INEXISTENTE")
        self.db.ventas.insert_one(venta)
        self.assertEqual(q02_ventas_pendientes(self.db), [venta])

    def test_conserva_venta_con_sucursal_del_farmaceutico_inexistente(self):
        self.db.farmaceuticos.update_one({"_id": self.farmaceutico["_id"]},
                                        {"$set": {"id_sucursal": "C-S-INEXISTENTE"}})
        venta = self.venta()
        self.db.ventas.insert_one(venta)
        self.assertEqual(q02_ventas_pendientes(self.db), [{
            **venta, "farmaceutico": {**self.farmaceutico, "id_sucursal": "C-S-INEXISTENTE"},
        }])

    def test_sin_ventas_devuelve_lista_vacia(self):
        self.assertEqual(q02_ventas_pendientes(self.db), [])
