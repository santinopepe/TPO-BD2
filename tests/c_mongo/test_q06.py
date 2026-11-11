import os
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from farmared.clock import FixedClock, inicio_dia_utc
from farmared.config import Config
from farmared.consultas.q06 import q06_recetas_prolongadas


@unittest.skipUnless(
    any(os.environ.get(k) == "1" for k in ("FARMARED_TEST_MONGO", "FARMARED_TEST_INTEGRACION")),
    "Activar FARMARED_TEST_MONGO=1 con MongoDB replica set de prueba.",
)
class TestQ06Mongo(unittest.TestCase):
    def setUp(self):
        from farmared.conexiones import obtener_mongo
        from farmared.esquema.base_mongo import preparar_mongo_base

        nombre = "farmared_test_c_q06_" + uuid4().hex
        self.db = obtener_mongo(replace(Config.from_env(), mongo_db=nombre))
        self.addCleanup(self.db.client.close)
        self.addCleanup(self.db.client.drop_database, nombre)
        preparar_mongo_base(self.db)
        self.reloj = FixedClock(datetime(2026, 11, 11, 15, tzinfo=UTC))
        self.cliente = {"_id": "C-C1", "nombre": "Ana", "apellido": "Prueba", "dni": "90000001",
                        "email": None, "telefono": None, "ciudad": "Rosario", "provincia": "Santa Fe",
                        "obra_social": "Sin cobertura", "nro_afiliado": None, "activo": False}
        self.db.clientes.insert_one(self.cliente)

    def receta(self, **cambios):
        documento = {"_id": "C-R1", "id_cliente": "C-C1", "medico": "Médica de prueba",
                     "matricula_medico": "MP-1",
                     "fecha_emision": inicio_dia_utc(self.reloj.today() - timedelta(days=40)),
                     "tipo": "Tratamiento prolongado", "dispensas_autorizadas": 3,
                     "dispensas_realizadas": 1,
                     "proxima_dispensa": inicio_dia_utc(self.reloj.today() - timedelta(days=1)),
                     "estado": "Vigente"}
        documento.update(cambios)
        return documento

    def test_devuelve_receta_con_cliente_completo(self):
        receta = self.receta()
        self.db.recetas.insert_many([receta, self.receta(_id="C-R2", proxima_dispensa=None)])
        self.assertEqual(q06_recetas_prolongadas(self.db, self.reloj), [{**receta, "cliente": self.cliente}])

    def test_excluye_dispensa_del_dia_de_la_consulta(self):
        self.db.recetas.insert_one(self.receta(proxima_dispensa=inicio_dia_utc(self.reloj.today())))
        self.assertEqual(q06_recetas_prolongadas(self.db, self.reloj), [])

    def test_excluye_receta_no_vigente(self):
        self.db.recetas.insert_one(self.receta(estado="Vencida"))
        self.assertEqual(q06_recetas_prolongadas(self.db, self.reloj), [])

    def test_conserva_receta_con_id_cliente_inexistente(self):
        receta = self.receta(id_cliente="C-INEXISTENTE")
        self.db.recetas.insert_one(receta)
        self.assertEqual(q06_recetas_prolongadas(self.db, self.reloj), [receta])

    def test_excluye_receta_sin_tratamiento_prolongado(self):
        self.db.recetas.insert_one(self.receta(tipo="Simple", dispensas_autorizadas=1, dispensas_realizadas=0))
        self.assertEqual(q06_recetas_prolongadas(self.db, self.reloj), [])
