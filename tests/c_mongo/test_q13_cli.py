from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import UTC, datetime
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from farmared import cli_mongo
from farmared.__main__ import main
from farmared.clock import FixedClock
from farmared.config import Config
from farmared.errores import ErrorDominio


class TestCliClientes(unittest.TestCase):
    def llamar(self, argumentos):
        salida = io.StringIO()
        errores = io.StringIO()
        with patch("farmared.__main__.version", return_value="0.1.0"), \
             redirect_stdout(salida), redirect_stderr(errores):
            codigo = main(argumentos)
        return codigo, salida.getvalue(), errores.getvalue()

    def test_argumentos_obligatorios_e_invalidos_no_conectan(self):
        casos = [[], ["--base", "b"], ["alta", "--datos", "-"],
                 ["--base", "b", "alta"], ["--base", "b", "modificar", "--datos", "-"],
                 ["--base", "b", "baja"], ["--base", "b", "otra"],
                 ["--base", " ", "baja", "--id-cliente", "C1"],
                 ["--base", "b", "baja", "--id-cliente", " C1"],
                 ["--base", "b", "baja", "--id-cliente", "C1", "--datos", "-"]]
        with patch.object(cli_mongo, "obtener_mongo") as conectar:
            for argumentos in casos:
                with self.subTest(argumentos=argumentos), self.assertRaises(SystemExit) as error:
                    self.llamar(["q13", *argumentos])
                self.assertEqual(error.exception.code, 2)
        conectar.assert_not_called()

    def test_json_invalido_o_ilegible_no_conecta(self):
        with TemporaryDirectory() as temporal, patch.object(cli_mongo, "obtener_mongo") as conectar:
            archivo = Path(temporal) / "datos.json"
            for contenido in (b"{", b"[]", b"null", b"\xff"):
                archivo.write_bytes(contenido)
                with self.subTest(contenido=contenido):
                    codigo, salida, errores = self.llamar(["q13", "--base", "b", "alta", "--datos", str(archivo)])
                    self.assertEqual((codigo, salida), (1, ""))
                    self.assertTrue(errores.startswith("VALIDACION:"))
            codigo, salida, errores = self.llamar(["q13", "--base", "b", "modificar", "--id-cliente", "C1",
                                                  "--datos", str(Path(temporal) / "inexistente.json")])
            self.assertEqual((codigo, salida), (1, ""))
            self.assertTrue(errores.startswith("VALIDACION:"))
        conectar.assert_not_called()

    def test_delega_acciones_serializa_salida_y_cierra_cliente(self):
        reloj = FixedClock(datetime(2026, 11, 11, 15, tzinfo=UTC))
        casos = [("alta", [], "q13_alta"), ("modificar", ["--id-cliente", "C1"], "q13_modificar"),
                 ("baja", ["--id-cliente", "C1"], "q13_baja")]
        for accion, argumentos, nombre in casos:
            for reutilizada in (False, True):
                if accion == "alta" and reutilizada:
                    continue
                with self.subTest(accion=accion, reutilizada=reutilizada):
                    db = MagicMock()
                    db.name = "farmared_demo_c"
                    datos = {"telefono": None}
                    resultado = {"documento": {"_id": "C1", "metadata": {"fecha": reloj.now_utc()}},
                                 "eventos": [] if reutilizada else ["E1"], "reutilizada": reutilizada}
                    opciones = [*argumentos, "--datos", "-"] if accion != "baja" else argumentos
                    with patch.object(cli_mongo, "obtener_mongo", return_value=db) as conectar, \
                         patch.object(cli_mongo, "SystemClock", return_value=reloj), \
                         patch("sys.stdin", io.StringIO(json.dumps(datos))), \
                         patch("farmared.consultas.q13." + nombre, return_value=resultado) as servicio:
                        codigo, salida, errores = self.llamar(["q13", "--base", db.name, accion, *opciones])
                    esperado = [db, datos] if accion == "alta" else [db, "C1", datos] if accion == "modificar" else [db, "C1"]
                    servicio.assert_called_once_with(*esperado, clock=reloj)
                    self.assertEqual(conectar.call_args.args[0].mongo_db, db.name)
                    db.client.close.assert_called_once_with()
                    self.assertEqual((codigo, errores), (0, ""))
                    self.assertEqual(json.loads(salida), {
                        "operacion": "q13", "accion": accion, "base": db.name,
                        "documento": {"_id": "C1", "metadata": {"fecha": reloj.now_utc().isoformat()}},
                        "eventos": resultado["eventos"], "reutilizada": reutilizada,
                        "proyeccion": "no_comprobada" if reutilizada else "pendiente_sync",
                    })

    def test_error_del_servicio_se_traduce_y_cierra_cliente(self):
        db = MagicMock()
        with patch.object(cli_mongo, "obtener_mongo", return_value=db), \
             patch("farmared.consultas.q13.q13_baja", side_effect=ErrorDominio("NO_EXISTE", "Cliente inexistente")):
            codigo, salida, errores = self.llamar(["q13", "--base", "b", "baja", "--id-cliente", "C1"])
        self.assertEqual((codigo, salida), (1, ""))
        self.assertEqual(errores, "NO_EXISTE: Cliente inexistente\n")
        db.client.close.assert_called_once_with()

    def test_ayuda_y_comandos_previos_no_importan_drivers(self):
        codigo = '''
import io, sys
from contextlib import redirect_stdout
from farmared.__main__ import COMANDOS, PENDIENTES, main
import farmared.__main__ as router
router.version = lambda nombre: '0.1.0'
assert 'q13' in COMANDOS and 'q13' not in PENDIENTES
assert 'q02' in COMANDOS and 'q02' not in PENDIENTES
for comando in ('q01', 'q02', 'q05', 'q06', 'q07', 'q08', 'q09', 'q11', 'q12', 'q13',
                'q03', 'q04', 'q10', 'q14', 'q15', 'sync', 'grafo-init'):
    with redirect_stdout(io.StringIO()):
        try:
            main([comando, '--help'])
        except SystemExit as error:
            assert error.code == 0
assert 'pymongo' not in sys.modules and 'neo4j' not in sys.modules
assert 'farmared.consultas.q13' not in sys.modules
'''
        resultado = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, timeout=15)
        self.assertEqual(resultado.returncode, 0, resultado.stderr)


@unittest.skipUnless(
    any(os.environ.get(k) == "1" for k in ("FARMARED_TEST_MONGO", "FARMARED_TEST_INTEGRACION")),
    "Activar FARMARED_TEST_MONGO=1 con MongoDB replica set de prueba y paquete instalado.",
)
class TestCliClientesMongo(unittest.TestCase):
    def test_recorrido_real_por_terminal_con_archivo_y_stdin(self):
        from farmared.conexiones import obtener_mongo
        from farmared.esquema.base_mongo import preparar_mongo_base

        nombre = "farmared_test_c_q13_cli_" + uuid4().hex
        db = obtener_mongo(replace(Config.from_env(), mongo_db=nombre))
        self.addCleanup(db.client.close)
        self.addCleanup(db.client.drop_database, nombre)
        preparar_mongo_base(db)

        def llamar(accion, *opciones, datos=None):
            return subprocess.run([sys.executable, "-m", "farmared", "q13", "--base", nombre, accion, *opciones],
                                  input=json.dumps(datos) if datos is not None else None,
                                  capture_output=True, text=True, timeout=30)

        with TemporaryDirectory() as temporal:
            datos = {"nombre": "Ana", "apellido": "Prueba", "dni": "95000001", "ciudad": "Rosario",
                     "provincia": "Santa Fe", "obra_social": "Sin cobertura"}
            archivo = Path(temporal) / "alta.json"
            archivo.write_text(json.dumps(datos), encoding="utf-8")
            alta = llamar("alta", "--datos", str(archivo))
            self.assertEqual(alta.returncode, 0, alta.stderr)
            cliente = json.loads(alta.stdout)["documento"]
            id_cliente = cliente["_id"]
            duplicado = llamar("alta", "--datos", "-", datos=datos)
            self.assertEqual(duplicado.returncode, 1)
            self.assertEqual(duplicado.stdout, "")
            self.assertTrue(duplicado.stderr.startswith("DNI_DUPLICADO:"))
            self.assertEqual(db.clientes.count_documents({}), 1)
            self.assertEqual(db.outbox.count_documents({}), 1)
            for repeticion in (False, True):
                modificacion = llamar("modificar", "--id-cliente", id_cliente, "--datos", "-",
                                      datos={"telefono": "3411234567"})
                self.assertEqual(modificacion.returncode, 0, modificacion.stderr)
                salida = json.loads(modificacion.stdout)
                self.assertEqual(salida["documento"]["telefono"], "3411234567")
                self.assertEqual(salida["reutilizada"], repeticion)
                self.assertEqual(salida["proyeccion"], "no_comprobada" if repeticion else "pendiente_sync")
                self.assertEqual(db.outbox.count_documents({}), 2)
            for repeticion in (False, True):
                baja = llamar("baja", "--id-cliente", id_cliente)
                self.assertEqual(baja.returncode, 0, baja.stderr)
                salida = json.loads(baja.stdout)
                self.assertFalse(salida["documento"]["activo"])
                self.assertEqual(salida["reutilizada"], repeticion)
                self.assertEqual(salida["proyeccion"], "no_comprobada" if repeticion else "pendiente_sync")
                self.assertEqual(db.outbox.count_documents({}), 3)
            self.assertEqual(db.clientes.find_one({"_id": id_cliente}), salida["documento"])
            self.assertEqual(db.outbox.count_documents({"procesado": False}), 3)
