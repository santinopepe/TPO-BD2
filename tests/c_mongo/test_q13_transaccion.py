from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
import os
import unittest
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from farmared.clock import FixedClock
from farmared.config import Config
from farmared.errores import ErrorDominio
from farmared.servicios.clientes import transaccion
from farmared.servicios.clientes.operaciones import preparar_alta
from farmared.servicios.clientes.transaccion import CambioCliente, ejecutar_cambio, preparar_evento_cliente


class TestUnidadTransaccionalClientes(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.sesion = object()
        self.documento = {"_id": "C-C1", "activo": True}
        self.reloj = FixedClock(datetime(2026, 11, 11, 15, 0, 0, 123456, tzinfo=UTC))

    def ejecutar(self, operacion):
        with patch.object(transaccion, "_ejecutar_transaccion", side_effect=lambda db, callback: callback(self.sesion)):
            return ejecutar_cambio(self.db, "C-C1", operacion, clock=self.reloj)

    def test_evento_respeta_contrato_utc_y_precision_bson(self):
        evento = preparar_evento_cliente("C-C1", self.reloj)
        self.assertEqual(UUID(evento["_id"]).version, 4)
        self.assertEqual(evento, {
            "_id": evento["_id"], "afectadas": [{"coleccion": "clientes", "id": "C-C1"}],
            "procesado": False, "creado_en": datetime(2026, 11, 11, 15, 0, 0, 123000, tzinfo=UTC),
        })

    def test_evento_normaliza_zona_sin_convertir_a_inicio_de_dia(self):
        reloj = MagicMock()
        reloj.now_utc.return_value = datetime(2026, 11, 11, 12, 30, tzinfo=timezone(timedelta(hours=-3)))
        self.assertEqual(preparar_evento_cliente("C-C1", reloj)["creado_en"],
                         datetime(2026, 11, 11, 15, 30, tzinfo=UTC))

    def test_rechaza_reloj_sin_zona_e_identidad_invalida(self):
        reloj = MagicMock()
        for instante in (datetime(2026, 11, 11), None, "2026-11-11"):
            with self.subTest(instante=instante), self.assertRaises(ErrorDominio) as error:
                reloj.now_utc.return_value = instante
                preparar_evento_cliente("C-C1", reloj)
            self.assertEqual(error.exception.codigo, "VALIDACION")
        with self.assertRaises(ErrorDominio) as error:
            preparar_evento_cliente(" ", self.reloj)
        self.assertEqual(error.exception.codigo, "VALIDACION")

    def test_cambio_emite_evento_con_la_misma_sesion(self):
        operacion = MagicMock(return_value=CambioCliente(self.documento, True))
        resultado = self.ejecutar(operacion)
        operacion.assert_called_once_with(self.sesion)
        evento = self.db.outbox.insert_one.call_args.args[0]
        self.db.outbox.insert_one.assert_called_once_with(evento, session=self.sesion)
        self.assertEqual(resultado, {"documento": self.documento, "eventos": [evento["_id"]], "reutilizada": False})
        self.db.client.close.assert_not_called()

    def test_sin_cambio_no_emite_evento(self):
        resultado = self.ejecutar(lambda sesion: CambioCliente(self.documento, False))
        self.assertEqual(resultado, {"documento": self.documento, "eventos": [], "reutilizada": True})
        self.assertEqual(self.db.mock_calls, [])

    def test_reintentos_conservan_uuid_e_instante(self):
        self.reloj = MagicMock()
        self.reloj.now_utc.return_value = datetime(2026, 11, 11, 15, 0, 0, 123456, tzinfo=UTC)
        sesiones = [object(), object()]

        def reintentar(db, callback):
            callback(sesiones[0])
            return callback(sesiones[1])

        with patch.object(transaccion, "_ejecutar_transaccion", side_effect=reintentar), \
             patch.object(transaccion, "uuid4", return_value=UUID("22222222-2222-4222-8222-222222222222")) as generar:
            resultado = ejecutar_cambio(self.db, "C-C1", lambda sesion: CambioCliente(self.documento, True), clock=self.reloj)
        llamadas = self.db.outbox.insert_one.call_args_list
        self.assertEqual(llamadas[0].args[0], llamadas[1].args[0])
        self.assertIs(llamadas[0].kwargs["session"], sesiones[0])
        self.assertIs(llamadas[1].kwargs["session"], sesiones[1])
        self.assertEqual(resultado["eventos"], ["22222222-2222-4222-8222-222222222222"])
        self.reloj.now_utc.assert_called_once_with()
        generar.assert_called_once_with()

    def test_error_del_callback_se_propaga_sin_evento(self):
        rechazo = ErrorDominio("VALIDACION", "Rechazo de prueba")
        with self.assertRaises(ErrorDominio) as error:
            self.ejecutar(MagicMock(side_effect=rechazo))
        self.assertIs(error.exception, rechazo)
        self.assertEqual(self.db.mock_calls, [])

    def test_resultado_incompatible_no_emite_evento(self):
        casos = [None, CambioCliente({"_id": "C-OTRO"}, True), CambioCliente(self.documento, 1)]
        for cambio in casos:
            with self.subTest(cambio=cambio), self.assertRaises(ErrorDominio) as error:
                self.ejecutar(lambda sesion: cambio)
            self.assertEqual(error.exception.codigo, "INTEGRIDAD")
        self.assertEqual(self.db.mock_calls, [])


@unittest.skipUnless(
    any(os.environ.get(k) == "1" for k in ("FARMARED_TEST_MONGO", "FARMARED_TEST_INTEGRACION")),
    "Activar FARMARED_TEST_MONGO=1 con MongoDB replica set de prueba.",
)
class TestTransaccionClientesMongo(unittest.TestCase):
    def setUp(self):
        from farmared.conexiones import obtener_mongo
        from farmared.esquema.base_mongo import preparar_mongo_base

        nombre = "farmared_test_c_q13_tx_" + uuid4().hex
        self.db = obtener_mongo(replace(Config.from_env(), mongo_db=nombre))
        self.addCleanup(self.db.client.close)
        self.addCleanup(self.db.client.drop_database, nombre)
        preparar_mongo_base(self.db)
        self.reloj = FixedClock(datetime(2026, 11, 11, 15, 0, 0, 123456, tzinfo=UTC))
        self.cliente = preparar_alta({"nombre": "Ana", "apellido": "Prueba", "dni": "95000001",
                                      "ciudad": "Rosario", "provincia": "Santa Fe", "obra_social": "Sin cobertura"})
        self.db.clientes.insert_one(deepcopy(self.cliente))

    def estado(self):
        return {coleccion: list(self.db[coleccion].find().sort("_id", 1))
                for coleccion in ("clientes", "outbox")}

    def cambiar_telefono(self, sesion):
        actual = self.db.clientes.find_one({"_id": self.cliente["_id"]}, session=sesion)
        self.db.clientes.update_one({"_id": actual["_id"]}, {"$set": {"telefono": "3411234567"}}, session=sesion)
        return CambioCliente({**actual, "telefono": "3411234567"}, True)

    def test_commit_confirma_cliente_y_evento(self):
        resultado = ejecutar_cambio(self.db, self.cliente["_id"], self.cambiar_telefono, clock=self.reloj)
        esperado = {**self.cliente, "telefono": "3411234567"}
        self.assertEqual(resultado["documento"], esperado)
        self.assertEqual(self.db.clientes.find_one({"_id": esperado["_id"]}), esperado)
        self.assertEqual(self.db.outbox.count_documents({}), 1)
        self.assertFalse(resultado["reutilizada"])
        self.assertEqual(self.db.outbox.find_one(), {
            "_id": resultado["eventos"][0], "afectadas": [{"coleccion": "clientes", "id": esperado["_id"]}],
            "procesado": False, "creado_en": datetime(2026, 11, 11, 15, 0, 0, 123000, tzinfo=UTC),
        })

    def test_fallo_de_outbox_revierte_cambio_del_cliente(self):
        from pymongo.errors import DuplicateKeyError

        evento = preparar_evento_cliente(self.cliente["_id"], self.reloj)
        self.db.outbox.insert_one(deepcopy(evento))
        antes = self.estado()
        with patch.object(transaccion, "uuid4", return_value=UUID(evento["_id"])), \
             self.assertRaises(DuplicateKeyError):
            ejecutar_cambio(self.db, self.cliente["_id"], self.cambiar_telefono, clock=self.reloj)
        self.assertEqual(self.estado(), antes)

    def test_error_de_dominio_revierte_todas_las_escrituras(self):
        antes = self.estado()
        evento = preparar_evento_cliente(self.cliente["_id"], self.reloj)

        def operacion(sesion):
            self.cambiar_telefono(sesion)
            self.db.outbox.insert_one(deepcopy(evento), session=sesion)
            raise ErrorDominio("VALIDACION", "Fallo después de ambas escrituras")

        with self.assertRaises(ErrorDominio) as error:
            ejecutar_cambio(self.db, self.cliente["_id"], operacion, clock=self.reloj)
        self.assertEqual(error.exception.codigo, "VALIDACION")
        self.assertEqual(self.estado(), antes)

    def test_fallo_del_cliente_revierte_evento_previo(self):
        from pymongo.errors import DuplicateKeyError

        antes = self.estado()
        evento = preparar_evento_cliente(self.cliente["_id"], self.reloj)
        duplicado = {**self.cliente, "_id": str(uuid4())}

        def operacion(sesion):
            self.db.outbox.insert_one(deepcopy(evento), session=sesion)
            self.db.clientes.insert_one(deepcopy(duplicado), session=sesion)
            return CambioCliente(self.cliente, True)

        with self.assertRaises(DuplicateKeyError):
            ejecutar_cambio(self.db, self.cliente["_id"], operacion, clock=self.reloj)
        self.assertEqual(self.estado(), antes)

    def test_sin_cambio_conserva_datos_y_no_crea_evento(self):
        antes = self.estado()

        def operacion(sesion):
            documento = self.db.clientes.find_one({"_id": self.cliente["_id"]}, session=sesion)
            return CambioCliente(documento, False)

        resultado = ejecutar_cambio(self.db, self.cliente["_id"], operacion, clock=self.reloj)
        self.assertEqual(resultado, {"documento": self.cliente, "eventos": [], "reutilizada": True})
        self.assertEqual(self.estado(), antes)

    def test_resultado_incompatible_aborta_cambio_del_cliente(self):
        antes = self.estado()

        def operacion(sesion):
            cambio = self.cambiar_telefono(sesion)
            return CambioCliente({**cambio.documento, "_id": "C-OTRO"}, True)

        with self.assertRaises(ErrorDominio) as error:
            ejecutar_cambio(self.db, self.cliente["_id"], operacion, clock=self.reloj)
        self.assertEqual(error.exception.codigo, "INTEGRIDAD")
        self.assertEqual(self.estado(), antes)
