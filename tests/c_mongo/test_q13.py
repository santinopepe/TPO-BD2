from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
import os
import unittest
from threading import Barrier, Lock, local
from unittest.mock import patch
from uuid import UUID, uuid4

from farmared.clock import FixedClock
from farmared.config import Config
from farmared.consultas.q13 import q13_alta, q13_baja, q13_modificar
from farmared.errores import ErrorDominio
from farmared.servicios.clientes import operaciones, transaccion
from farmared.servicios.clientes.operaciones import preparar_alta
from farmared.servicios.clientes.transaccion import preparar_evento_cliente


@unittest.skipUnless(
    any(os.environ.get(k) == "1" for k in ("FARMARED_TEST_MONGO", "FARMARED_TEST_INTEGRACION")),
    "Activar FARMARED_TEST_MONGO=1 con MongoDB replica set de prueba.",
)
class TestOperacionesClientesMongo(unittest.TestCase):
    def setUp(self):
        from farmared.conexiones import obtener_mongo
        from farmared.esquema.base_mongo import preparar_mongo_base

        nombre = "farmared_test_c_q13_" + uuid4().hex
        self.db = obtener_mongo(replace(Config.from_env(), mongo_db=nombre))
        self.addCleanup(self.db.client.close)
        self.addCleanup(self.db.client.drop_database, nombre)
        preparar_mongo_base(self.db)
        self.reloj = FixedClock(datetime(2026, 11, 11, 15, 0, 0, 123456, tzinfo=UTC))
        self.datos = {"nombre": "Ana", "apellido": "Prueba", "dni": "95000001",
                      "ciudad": "Rosario", "provincia": "Santa Fe", "obra_social": "Sin cobertura"}
        self.cliente = {**preparar_alta(self.datos), "importacion": {"archivo": "fixture"}}
        self.id = self.cliente["_id"]
        self.db.clientes.insert_one(deepcopy(self.cliente))

    def estado(self):
        return {nombre: list(self.db[nombre].find().sort("_id", 1))
                for nombre in ("clientes", "outbox", "ventas", "recetas")}

    def assert_rechazo_sin_cambios(self, codigo, funcion, *argumentos):
        antes = self.estado()
        with self.assertRaises(ErrorDominio) as error:
            funcion(self.db, *argumentos, clock=self.reloj)
        self.assertEqual(error.exception.codigo, codigo)
        self.assertEqual(self.estado(), antes)

    def test_alta_confirma_documento_completo_y_evento(self):
        datos = {**self.datos, "dni": " 001234 ", "obra_social": "OSDE", "nro_afiliado": " AF-1 "}
        antes = deepcopy(datos)
        resultado = q13_alta(self.db, datos, clock=self.reloj)
        documento = resultado["documento"]
        self.assertEqual(UUID(documento["_id"]).version, 4)
        self.assertEqual(documento, {"_id": documento["_id"], **self.datos, "dni": "001234",
                                     "obra_social": "OSDE", "nro_afiliado": "AF-1",
                                     "email": None, "telefono": None, "activo": True})
        self.assertEqual(self.db.clientes.find_one({"_id": documento["_id"]}), documento)
        self.assertFalse(resultado["reutilizada"])
        self.assertEqual(len(resultado["eventos"]), 1)
        self.assertEqual(self.db.outbox.find_one({"_id": resultado["eventos"][0]}), {
            "_id": resultado["eventos"][0], "afectadas": [{"coleccion": "clientes", "id": documento["_id"]}],
            "procesado": False, "creado_en": datetime(2026, 11, 11, 15, 0, 0, 123000, tzinfo=UTC),
        })
        self.assertEqual(datos, antes)

    def test_dni_duplicado_de_activo_e_inactivo(self):
        for activo in (True, False):
            with self.subTest(activo=activo):
                if not activo:
                    q13_baja(self.db, self.id, clock=self.reloj)
                self.assert_rechazo_sin_cambios(
                    "DNI_DUPLICADO", q13_alta, {**self.datos, "dni": " 95000001 "},
                )

    def test_colision_de_identidad_se_distingue_del_dni(self):
        with patch.object(operaciones, "uuid4", return_value=UUID(self.id)):
            self.assert_rechazo_sin_cambios("CONFLICTO_ID", q13_alta, {**self.datos, "dni": "95000002"})

    def test_fallo_de_outbox_revierte_las_tres_operaciones(self):
        evento = preparar_evento_cliente(self.id, self.reloj)
        self.db.outbox.insert_one(deepcopy(evento))
        casos = [
            (q13_alta, ({**self.datos, "dni": "95000002"},)),
            (q13_modificar, (self.id, {"telefono": "3411234567"})),
            (q13_baja, (self.id,)),
        ]
        for funcion, argumentos in casos:
            with self.subTest(operacion=funcion.__name__), \
                 patch.object(transaccion, "uuid4", return_value=UUID(evento["_id"])):
                self.assert_rechazo_sin_cambios("INTEGRIDAD", funcion, *argumentos)

    def test_modificacion_conserva_identidad_actividad_y_metadatos(self):
        cambios = {"email": " ana@ejemplo.test ", "ciudad": " Córdoba ",
                   "obra_social": "OSDE", "nro_afiliado": " AF-1 "}
        antes = deepcopy(cambios)
        resultado = q13_modificar(self.db, self.id, cambios, clock=self.reloj)
        esperado = {**self.cliente, "email": "ana@ejemplo.test", "ciudad": "Córdoba",
                    "obra_social": "OSDE", "nro_afiliado": "AF-1"}
        self.assertEqual(resultado["documento"], esperado)
        self.assertEqual(self.db.clientes.find_one({"_id": self.id}), esperado)
        self.assertEqual(cambios, antes)
        self.assertEqual(self.cliente["ciudad"], "Rosario")
        self.assertEqual(len(resultado["eventos"]), 1)
        self.assertFalse(resultado["reutilizada"])
        sin_cobertura = q13_modificar(self.db, self.id, {
            "obra_social": "Sin cobertura", "nro_afiliado": None,
        }, clock=self.reloj)
        self.assertEqual(sin_cobertura["documento"], {
            **esperado, "obra_social": "Sin cobertura", "nro_afiliado": None,
        })
        self.assertEqual(self.db.outbox.count_documents({}), 2)

    def test_modificaciones_sin_efecto_no_crean_eventos(self):
        antes = self.estado()
        resultado = q13_modificar(self.db, self.id, {"telefono": " "}, clock=self.reloj)
        self.assertEqual(resultado, {"documento": self.cliente, "eventos": [], "reutilizada": True})
        self.assertEqual(self.estado(), antes)
        primero = q13_modificar(self.db, self.id, {"telefono": "3411234567"}, clock=self.reloj)
        antes = self.estado()
        segundo = q13_modificar(self.db, self.id, {"telefono": " 3411234567 "}, clock=self.reloj)
        self.assertEqual(segundo, {"documento": primero["documento"], "eventos": [], "reutilizada": True})
        self.assertEqual(self.estado(), antes)

    def test_modificar_inactivo_no_lo_reactiva(self):
        baja = q13_baja(self.db, self.id, clock=self.reloj)
        resultado = q13_modificar(self.db, self.id, {"telefono": "3411234567"}, clock=self.reloj)
        self.assertEqual(resultado["documento"], {**baja["documento"], "telefono": "3411234567"})
        self.assertFalse(resultado["documento"]["activo"])
        self.assertEqual(self.db.outbox.count_documents({}), 2)

    def test_modificacion_invalida_rechaza_cobertura_y_campos_prohibidos(self):
        for cambios in ({"obra_social": "OSDE"}, {"dni": "95000002"}, {"activo": False}, {}):
            with self.subTest(cambios=cambios):
                self.assert_rechazo_sin_cambios("VALIDACION", q13_modificar, self.id, cambios)

    def test_baja_preserva_historia_y_repeticion_no_emite_evento(self):
        fecha = datetime(2026, 11, 1, 3, tzinfo=UTC)
        self.db.recetas.insert_one({"_id": "C-R1", "id_cliente": self.id, "medico": "Médica",
                                   "matricula_medico": "MP-1", "fecha_emision": fecha, "tipo": "Simple",
                                   "dispensas_autorizadas": 1, "dispensas_realizadas": 0,
                                   "proxima_dispensa": None, "estado": "Vigente"})
        self.db.ventas.insert_one({"_id": "C-V1", "id_cliente": self.id, "id_farmaceutico": "C-F1",
                                  "id_sucursal": "C-S1", "id_receta": None, "fecha": fecha, "tipo": "Venta libre",
                                  "medio_pago": "Efectivo", "estado": "Pendiente", "total": 1000,
                                  "items": [{"id_detalle": "D1", "id_producto": "C-P1", "cantidad": 1,
                                             "precio_unit": 1000, "subtotal": 1000, "asignaciones_lotes": []}],
                                  "stock_aplicado": False, "receta_aplicada": False,
                                  "origen": "csv", "trazabilidad_lotes": "no_aplicada"})
        antes = self.estado()
        resultado = q13_baja(self.db, self.id, clock=self.reloj)
        despues = self.estado()
        self.assertEqual(resultado["documento"], {**self.cliente, "activo": False})
        self.assertEqual(despues["clientes"], [resultado["documento"]])
        self.assertEqual(despues["ventas"], antes["ventas"])
        self.assertEqual(despues["recetas"], antes["recetas"])
        self.assertEqual(len(resultado["eventos"]), 1)
        self.assertEqual(q13_baja(self.db, self.id, clock=self.reloj), {
            "documento": resultado["documento"], "eventos": [], "reutilizada": True,
        })
        self.assertEqual(self.estado(), despues)

    def test_cliente_inexistente_no_produce_efectos(self):
        for funcion, argumentos in ((q13_modificar, ("C-INEXISTENTE", {"telefono": None})),
                                    (q13_baja, ("C-INEXISTENTE",))):
            with self.subTest(operacion=funcion.__name__):
                self.assert_rechazo_sin_cambios("NO_EXISTE", funcion, *argumentos)

    def test_otro_indice_unico_en_alta_no_se_informa_como_dni_duplicado(self):
        self.db.clientes.create_index("ciudad", unique=True)
        self.assert_rechazo_sin_cambios("INTEGRIDAD", q13_alta, {**self.datos, "dni": "95000002"})

    def test_otro_indice_unico_en_modificacion_no_deja_cambios(self):
        otro = {**preparar_alta({**self.datos, "dni": "95000002"}), "telefono": "3411234567"}
        self.db.clientes.insert_one(otro)
        self.db.clientes.create_index("telefono", unique=True)
        self.assert_rechazo_sin_cambios("INTEGRIDAD", q13_modificar, self.id, {"telefono": "3411234567"})

    def test_altas_simultaneas_del_mismo_dni_confirman_una_sola(self):
        barrera = Barrier(2)
        bloqueo = Lock()
        contexto = local()
        sesiones = []
        clase = type(self.db.clientes)
        insertar_original = clase.insert_one
        nombre = self.db.clientes.full_name
        dni = "95000002"

        def insertar(coleccion, documento, *args, **kwargs):
            if (coleccion.full_name == nombre and documento.get("dni") == dni
                    and not getattr(contexto, "sincronizado", False)):
                contexto.sincronizado = True
                with bloqueo:
                    sesiones.append(kwargs["session"])
                barrera.wait(timeout=10)
            return insertar_original(coleccion, documento, *args, **kwargs)

        def registrar():
            try:
                return q13_alta(self.db, {**self.datos, "dni": dni}, clock=self.reloj)
            except ErrorDominio as error:
                return error

        with patch.object(clase, "insert_one", new=insertar), ThreadPoolExecutor(max_workers=2) as executor:
            futuros = [executor.submit(registrar) for _ in range(2)]
            resultados = [futuro.result(timeout=20) for futuro in futuros]
        exitos = [r for r in resultados if isinstance(r, dict)]
        errores = [r for r in resultados if isinstance(r, ErrorDominio)]
        self.assertEqual(len(exitos), 1)
        self.assertEqual([error.codigo for error in errores], ["DNI_DUPLICADO"])
        self.assertEqual(self.db.clientes.count_documents({"dni": dni}), 1)
        self.assertEqual(self.db.clientes.count_documents({}), 2)
        self.assertEqual(self.db.outbox.count_documents({}), 1)
        self.assertEqual(self.db.clientes.find_one({"dni": dni}), exitos[0]["documento"])
        self.assertEqual(self.db.outbox.find_one()["_id"], exitos[0]["eventos"][0])
        self.assertEqual(len(sesiones), 2)
        self.assertIsNot(sesiones[0], sesiones[1])
        self.assertTrue(all(sesion.has_ended for sesion in sesiones))

    def test_modificaciones_simultaneas_conservan_ambos_campos(self):
        barrera = Barrier(2)
        bloqueo = Lock()
        contexto = local()
        lecturas = []
        clase = type(self.db.clientes)
        leer_original = clase.find_one
        nombre = self.db.clientes.full_name

        def leer(coleccion, *args, **kwargs):
            documento = leer_original(coleccion, *args, **kwargs)
            if (coleccion.full_name == nombre and documento is not None and documento["_id"] == self.id
                    and kwargs.get("session") is not None and not getattr(contexto, "sincronizado", False)):
                contexto.sincronizado = True
                with bloqueo:
                    lecturas.append(deepcopy(documento))
                barrera.wait(timeout=10)
            return documento

        cambios = [{"telefono": "3411234567"}, {"email": "ana@ejemplo.test"}]
        with patch.object(clase, "find_one", new=leer), ThreadPoolExecutor(max_workers=2) as executor:
            futuros = [executor.submit(q13_modificar, self.db, self.id, cambio, clock=self.reloj)
                       for cambio in cambios]
            resultados = [futuro.result(timeout=20) for futuro in futuros]
        self.assertEqual(lecturas, [self.cliente, self.cliente])
        self.assertEqual(self.db.clientes.find_one({"_id": self.id}), {
            **self.cliente, "telefono": "3411234567", "email": "ana@ejemplo.test",
        })
        self.assertTrue(all(not resultado["reutilizada"] for resultado in resultados))
        eventos = [evento for resultado in resultados for evento in resultado["eventos"]]
        self.assertEqual(len(set(eventos)), 2)
        self.assertEqual(self.db.outbox.count_documents({}), 2)
        self.assertCountEqual([evento["_id"] for evento in self.db.outbox.find()], eventos)

    def test_abm_sin_neo4j_deja_eventos_pendientes_y_ventas_rechaza_inactivo(self):
        from farmared.servicios.ventas.habilitacion import validar_cliente

        with patch.dict(os.environ, {"NEO4J_PASSWORD": "", "NEO4J_URI": "bolt://127.0.0.1:1"}), \
             patch("farmared.conexiones.obtener_neo4j", side_effect=AssertionError("No debe conectar a Neo4j")) as conectar:
            alta = q13_alta(self.db, {**self.datos, "dni": "95000002"}, clock=self.reloj)
            id_cliente = alta["documento"]["_id"]
            self.assertIsNone(validar_cliente(alta["documento"], id_cliente))
            modificacion = q13_modificar(self.db, id_cliente, {"telefono": "3411234567"}, clock=self.reloj)
            baja = q13_baja(self.db, id_cliente, clock=self.reloj)
        conectar.assert_not_called()
        confirmado = self.db.clientes.find_one({"_id": id_cliente})
        self.assertEqual(confirmado, {**modificacion["documento"], "activo": False})
        with self.assertRaises(ErrorDominio) as error:
            validar_cliente(confirmado, id_cliente)
        self.assertEqual(error.exception.codigo, "VALIDACION")
        eventos = [evento for resultado in (alta, modificacion, baja) for evento in resultado["eventos"]]
        persistidos = list(self.db.outbox.find())
        self.assertCountEqual([evento["_id"] for evento in persistidos], eventos)
        self.assertTrue(all(evento["procesado"] is False for evento in persistidos))
        self.assertTrue(all(evento["afectadas"] == [{"coleccion": "clientes", "id": id_cliente}]
                            for evento in persistidos))
