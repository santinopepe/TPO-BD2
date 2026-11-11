from copy import deepcopy
from types import MappingProxyType
import unittest
from uuid import UUID

from farmared.errores import ErrorDominio
from farmared.servicios.clientes.operaciones import preparar_alta
from farmared.servicios.clientes.validacion import (
    combinar_cambios,
    normalizar_alta,
    normalizar_cambios,
    validar_cobertura,
    validar_id_cliente,
)


class TestValidacionClientes(unittest.TestCase):
    def setUp(self):
        self.datos = {"nombre": "Ana", "apellido": "Prueba", "dni": "95000001",
                      "ciudad": "Rosario", "provincia": "Santa Fe", "obra_social": "Sin cobertura"}
        self.cliente = {"_id": "C-C1", **self.datos, "email": "ana@ejemplo.test", "telefono": "3411234567",
                        "nro_afiliado": None, "activo": False, "importacion": {"archivo": "clientes.csv"}}

    def assert_validacion(self, funcion, *argumentos):
        with self.assertRaises(ErrorDominio) as error:
            funcion(*argumentos)
        self.assertEqual(error.exception.codigo, "VALIDACION")

    def test_alta_sin_cobertura_completa_los_nulos(self):
        self.assertEqual(normalizar_alta(self.datos), {
            **self.datos, "email": None, "telefono": None, "nro_afiliado": None,
        })

    def test_acepta_todas_las_obras_sociales_acordadas(self):
        for obra in ("OSDE", "Swiss Medical", "PAMI", "IOMA", "Galeno"):
            with self.subTest(obra=obra):
                datos = {**self.datos, "obra_social": obra, "nro_afiliado": " AF-123 "}
                self.assertEqual(normalizar_alta(datos), {
                    **datos, "nro_afiliado": "AF-123", "email": None, "telefono": None,
                })

    def test_normaliza_textos_sin_mutar_el_mapping_original(self):
        datos = {campo: f"  {valor}  " for campo, valor in self.datos.items()}
        datos.update(email="  ana@ejemplo.test ", telefono="  +54 341-123 ", nro_afiliado="   ")
        antes = deepcopy(datos)
        self.assertEqual(normalizar_alta(MappingProxyType(datos)), {
            **self.datos, "email": "ana@ejemplo.test", "telefono": "+54 341-123", "nro_afiliado": None,
        })
        self.assertEqual(datos, antes)

    def test_rechaza_campos_obligatorios_omitidos(self):
        for campo in self.datos:
            with self.subTest(campo=campo):
                datos = self.datos.copy()
                datos.pop(campo)
                self.assert_validacion(normalizar_alta, datos)

    def test_rechaza_entradas_que_no_son_mappings(self):
        for datos in (None, True, 42, "cliente", [], [("nombre", "Ana")]):
            for funcion in (normalizar_alta, normalizar_cambios):
                with self.subTest(datos=datos, funcion=funcion.__name__):
                    self.assert_validacion(funcion, datos)

    def test_rechaza_textos_obligatorios_vacios_o_de_otro_tipo(self):
        for campo in ("nombre", "apellido", "ciudad", "provincia"):
            for valor in (None, True, 42, [], {}, "", " \t\n "):
                with self.subTest(campo=campo, valor=valor):
                    self.assert_validacion(normalizar_alta, {**self.datos, campo: valor})

    def test_dni_preserva_ceros_y_no_exige_longitud_fija(self):
        for dni, esperado in ((" 001234 ", "001234"), ("1", "1"), ("123456789012", "123456789012")):
            with self.subTest(dni=dni):
                self.assertEqual(normalizar_alta({**self.datos, "dni": dni})["dni"], esperado)

    def test_dni_rechaza_numeros_booleanos_separadores_y_digitos_no_ascii(self):
        for dni in (None, 95000001, True, "", " ", "95.000.001", "95-000001", "95 000001",
                    "95A00001", "１２３４", "١٢٣٤", "95\n000001", [], {}):
            with self.subTest(dni=dni):
                self.assert_validacion(normalizar_alta, {**self.datos, "dni": dni})

    def test_opcionales_vacios_se_convierten_en_nulos(self):
        for campo in ("email", "telefono", "nro_afiliado"):
            for valor in (None, "", " \t "):
                with self.subTest(campo=campo, valor=valor):
                    self.assertIsNone(normalizar_alta({**self.datos, campo: valor})[campo])

    def test_opcionales_rechazan_tipos_que_no_son_texto_o_nulo(self):
        for campo in ("email", "telefono", "nro_afiliado"):
            for valor in (True, 123, [], {}):
                with self.subTest(campo=campo, valor=valor):
                    self.assert_validacion(normalizar_alta, {**self.datos, campo: valor})
                    self.assert_validacion(normalizar_cambios, {campo: valor})

    def test_alta_rechaza_identidad_actividad_metadatos_y_operadores(self):
        for campo in ("_id", "id_cliente", "activo", "importacion", "otro", "$set", "email.valor", 1):
            with self.subTest(campo=campo):
                self.assert_validacion(normalizar_alta, {**self.datos, campo: "valor"})

    def test_rechaza_coberturas_invalidas(self):
        casos = [
            {"obra_social": "Sin cobertura", "nro_afiliado": "AF-1"},
            {"obra_social": "OSDE"},
            {"obra_social": "OSDE", "nro_afiliado": None},
            {"obra_social": "OSDE", "nro_afiliado": ""},
            {"obra_social": "OSDE", "nro_afiliado": "   "},
            {"obra_social": "Otra", "nro_afiliado": "AF-1"},
            {"obra_social": "osde", "nro_afiliado": "AF-1"},
            {"obra_social": None}, {"obra_social": []}, {"obra_social": {}},
        ]
        for caso in casos:
            with self.subTest(caso=caso):
                self.assert_validacion(normalizar_alta, {**self.datos, **caso})

    def test_validacion_de_cobertura_no_normaliza_ni_corrige_datos(self):
        datos = {"obra_social": "Sin cobertura", "nro_afiliado": ""}
        antes = datos.copy()
        self.assert_validacion(validar_cobertura, datos)
        self.assertEqual(datos, antes)
        for datos in (None, [], {"obra_social": []}, {"obra_social": "OSDE", "nro_afiliado": False}):
            with self.subTest(datos=datos):
                self.assert_validacion(validar_cobertura, datos)

    def test_modificacion_normaliza_solo_los_campos_presentes(self):
        self.assertEqual(normalizar_cambios({"telefono": "  "}), {"telefono": None})
        self.assertEqual(normalizar_cambios({"email": None, "ciudad": " Córdoba "}),
                         {"email": None, "ciudad": "Córdoba"})
        for campo in ("ciudad", "provincia"):
            for valor in (None, "", " "):
                with self.subTest(campo=campo, valor=valor):
                    self.assert_validacion(normalizar_cambios, {campo: valor})

    def test_modificacion_rechaza_dto_vacio_y_campos_prohibidos(self):
        self.assert_validacion(normalizar_cambios, {})
        for campo in ("_id", "id_cliente", "dni", "nombre", "apellido", "activo", "importacion",
                      "otro", "$unset", "obra_social.nombre", 1):
            with self.subTest(campo=campo):
                self.assert_validacion(normalizar_cambios, {campo: "valor"})

    def test_combinar_conserva_campos_omitidos_actividad_y_metadatos(self):
        antes = deepcopy(self.cliente)
        cambios = {"telefono": " 3417654321 "}
        resultado = combinar_cambios(MappingProxyType(self.cliente), cambios)
        self.assertEqual(resultado, {**self.cliente, "telefono": "3417654321"})
        self.assertEqual(self.cliente, antes)
        self.assertEqual(cambios, {"telefono": " 3417654321 "})
        resultado["importacion"]["archivo"] = "otro.csv"
        self.assertEqual(self.cliente, antes)

    def test_transicion_a_obra_social_exige_afiliado_en_estado_resultante(self):
        self.assert_validacion(combinar_cambios, self.cliente, {"obra_social": "OSDE"})
        resultado = combinar_cambios(self.cliente, {"obra_social": "OSDE", "nro_afiliado": " AF-1 "})
        self.assertEqual(resultado, {**self.cliente, "obra_social": "OSDE", "nro_afiliado": "AF-1"})

    def test_transicion_a_sin_cobertura_exige_anular_afiliado(self):
        cliente = {**self.cliente, "obra_social": "OSDE", "nro_afiliado": "AF-1"}
        self.assert_validacion(combinar_cambios, cliente, {"obra_social": "Sin cobertura"})
        resultado = combinar_cambios(cliente, {"obra_social": "Sin cobertura", "nro_afiliado": None})
        self.assertEqual(resultado, {**cliente, "obra_social": "Sin cobertura", "nro_afiliado": None})

    def test_combinar_usa_la_cobertura_actual_y_no_repara_incoherencias(self):
        cliente = {**self.cliente, "obra_social": "OSDE", "nro_afiliado": "AF-1"}
        self.assert_validacion(combinar_cambios, cliente, {"nro_afiliado": None})
        self.assertEqual(combinar_cambios(cliente, {"obra_social": "PAMI"}), {**cliente, "obra_social": "PAMI"})
        incoherente = {**self.cliente, "nro_afiliado": "AF-1"}
        self.assert_validacion(combinar_cambios, incoherente, {"telefono": None})

    def test_cliente_actual_invalido_es_error_de_integridad(self):
        with self.assertRaises(ErrorDominio) as error:
            combinar_cambios(None, {"telefono": None})
        self.assertEqual(error.exception.codigo, "INTEGRIDAD")

    def test_preparar_alta_genera_uuid_y_documento_activo_completo(self):
        primero = preparar_alta(self.datos)
        segundo = preparar_alta(self.datos)
        self.assertEqual(UUID(primero["_id"]).version, 4)
        self.assertEqual(UUID(segundo["_id"]).version, 4)
        self.assertNotEqual(primero["_id"], segundo["_id"])
        self.assertEqual(primero, {"_id": primero["_id"], **self.datos, "email": None,
                                   "telefono": None, "nro_afiliado": None, "activo": True})
        self.assertEqual(self.datos["dni"], "95000001")

    def test_identificador_admite_ids_originales_y_uuid_sin_normalizarlos(self):
        for identificador in ("C001", "11111111-1111-4111-8111-111111111111"):
            with self.subTest(identificador=identificador):
                self.assertEqual(validar_id_cliente(identificador), identificador)
        for identificador in (None, True, 1, "", " ", " C001", "C001 ", [], {}):
            with self.subTest(identificador=identificador):
                self.assert_validacion(validar_id_cliente, identificador)
