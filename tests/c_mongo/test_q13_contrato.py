import unittest
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from farmared.clock import FixedClock, SystemClock
from farmared.consultas.q13 import q13_alta, q13_baja, q13_modificar
from farmared.servicios.clientes import operaciones


class TestContratoQ13(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.datos = {"nombre": "Ana", "apellido": "Prueba", "dni": "95000001",
                      "ciudad": "Rosario", "provincia": "Santa Fe", "obra_social": "Sin cobertura"}
        self.cambios = {"telefono": "3411234567"}
        self.casos = [
            (q13_alta, "alta", (self.db, self.datos)),
            (q13_modificar, "modificar", (self.db, "C-C1", self.cambios)),
            (q13_baja, "baja", (self.db, "C-C1")),
        ]

    def test_entrega_reloj_del_sistema_por_defecto(self):
        for funcion, nombre, argumentos in self.casos:
            with self.subTest(operacion=nombre), patch.object(operaciones, nombre) as servicio:
                resultado = funcion(*argumentos)
                self.assertIs(resultado, servicio.return_value)
                self.assertEqual(servicio.call_args.args, argumentos)
                self.assertIsInstance(servicio.call_args.kwargs["clock"], SystemClock)
                servicio.assert_called_once()
        self.assertEqual(self.db.mock_calls, [])

    def test_conserva_reloj_fijo_y_parametros(self):
        reloj = FixedClock(datetime(2026, 11, 11, 15, tzinfo=UTC))
        datos_antes = self.datos.copy()
        cambios_antes = self.cambios.copy()
        for funcion, nombre, argumentos in self.casos:
            with self.subTest(operacion=nombre), patch.object(operaciones, nombre) as servicio:
                resultado = funcion(*argumentos, clock=reloj)
                servicio.assert_called_once_with(*argumentos, clock=reloj)
                self.assertIs(resultado, servicio.return_value)
        self.assertEqual(self.datos, datos_antes)
        self.assertEqual(self.cambios, cambios_antes)
        self.assertEqual(self.db.mock_calls, [])

    def test_clock_solo_admite_argumento_nombrado(self):
        reloj = FixedClock(datetime(2026, 11, 11, 15, tzinfo=UTC))
        for funcion, nombre, argumentos in self.casos:
            with self.subTest(operacion=nombre), self.assertRaises(TypeError):
                funcion(*argumentos, reloj)
        self.assertEqual(self.db.mock_calls, [])

    def test_operaciones_pendientes_no_simulan_exito_ni_acceden_a_la_base(self):
        for funcion, nombre, argumentos in self.casos:
            with self.subTest(operacion=nombre), self.assertRaisesRegex(NotImplementedError, "q13"):
                funcion(*argumentos)
        self.assertEqual(self.db.mock_calls, [])
