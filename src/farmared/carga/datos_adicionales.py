"""Perfil determinista de datos propios, sin I/O ni lógica de consultas/servicios."""

import csv
import hashlib
import io
import json
from datetime import timedelta

from farmared.carga.formatos import CAMPOS

VERSION_GENERADOR = 1
NOMBRE_MANIFIESTO = "manifiesto.json"


def _datos(base):
    tablas = {nombre: [] for nombre in CAMPOS}

    def agregar(tabla, *valores):
        assert len(valores) == len(CAMPOS[tabla]), tabla
        tablas[tabla].append(dict(zip(CAMPOS[tabla], valores)))

    def fecha(dias):
        return (base + timedelta(days=dias)).isoformat()

    for n in range(1, 11):
        cobertura = "PAMI" if n % 2 else "Sin cobertura"
        agregar("clientes", f"A-C{n:03}", f"Cliente adicional {n}", "Ficticio", f"{90000000+n}",
                f"cliente{n}@example.test", f"110000{n:04}", "Buenos Aires", "Buenos Aires",
                cobertura, f"A-AF{n:03}" if n % 2 else "", n != 9)
        agregar("sucursales", f"A-S{n:03}", f"Sucursal adicional {n}", "Droguería" if n == 10 else "Farmacia",
                f"Calle ficticia {n}", "Buenos Aires", "Buenos Aires", f"110100{n:04}", n != 9)
        sucursal = 1 if n == 3 else n
        agregar("farmaceuticos", f"A-F{n:03}", f"Profesional adicional {n}", "Ficticio", f"A-MN{n:03}",
                "Farmacéutico", f"A-S{sucursal:03}", n != 2)
        agregar("proveedores", f"A-PRV{n:03}", f"Proveedor ficticio {n}", f"30-{90000000+n:08}-1",
                "Laboratorio" if n % 2 else "Droguería", "Buenos Aires", "Buenos Aires", f"110200{n:04}", n != 10)
        precios = [4999, 5000, 1000, 2000, 1500, 100, 1000, 2000, 500, 700]
        condiciones = ["Venta libre", "Venta libre", "Bajo receta", "Bajo receta", "Bajo receta archivada"] + ["Venta libre"] * 5
        agregar("productos", f"A-PRD{n:03}", f"Producto adicional {n}", f"Principio ficticio {n}",
                "Higiene" if condiciones[n-1] == "Venta libre" else "Medicamento", "Unidad",
                condiciones[n-1], precios[n-1], f"A-PRV{n:03}", n != 9)

    lotes = [
        (3, 1, 100, -1), (3, 1, 4, 0), (3, 1, 10, 30), (3, 1, 20, 60),
        (6, 1, 0, 90), (1, 1, 49, 60), (2, 1, 50, 60), (4, 1, 50, 40),
        (5, 1, 10, 50), (7, 1, 10, 60), (8, 1, 1, 60), (9, 2, 15, 60),
        (10, 1, 20, 60), (1, 2, 100, 120), (3, 10, 1000, 120), (1, 1, 10, -30),
    ]
    for n, (producto, sucursal, unidades, dias) in enumerate(lotes, 1):
        nro = "A-NRO-P001" if n in (6, 14) else f"A-NRO{n:03}"
        agregar("stock_lotes", f"A-L{n:03}", f"A-PRD{producto:03}", f"A-S{sucursal:03}", nro, unidades, fecha(dias))

    recetas = [
        (1, "Tratamiento prolongado", 3, 1, -1, "Vigente"),
        (1, "Tratamiento prolongado", 3, 0, 0, "Vigente"),
        (3, "Tratamiento prolongado", 3, 0, 1, "Vigente"),
        (4, "Tratamiento prolongado", 3, 3, None, "Completada"),
        (5, "Simple", 1, 0, None, "Vigente"), (6, "Archivada", 1, 0, None, "Vigente"),
        (7, "Simple", 1, 0, None, "Vencida"), (8, "Simple", 1, 0, None, "Vigente"),
        (9, "Simple", 1, 0, None, "Vigente"), (8, "Simple", 1, 0, None, "Vigente"),
    ]
    for n, (cliente, tipo, autorizadas, realizadas, dias, estado) in enumerate(recetas, 1):
        agregar("recetas", f"A-RC{n:03}", f"A-C{cliente:03}", "Médico ficticio", f"A-MP{n:03}", fecha(-40),
                tipo, autorizadas, realizadas, "" if dias is None else fecha(dias), estado)

    # Venta, cliente, profesional, receta, día, estado y líneas (producto, cantidad, precio).
    ventas = [
        (1, 1, 1, None, fecha(0), "Completada", [(1, 1, 4999)]),
        (2, 2, 2, None, fecha(0), "Completada", [(2, 1, 5000)]),
        (3, 3, 2, None, fecha(0), "Pendiente", [(1, 1, 4999)]),
        (4, 1, 1, 1, fecha(-31), "Completada", [(3, 1, 1000)]),
        (5, 1, 1, 1, fecha(0), "Pendiente", [(3, 6, 1000)]),
        (6, 6, 1, None, fecha(0), "Pendiente", [(7, 2, 1000), (8, 2, 2000)]),
        (7, 7, 1, None, fecha(-1), "Anulada", [(10, 1, 700)]),
        (8, 8, 3, None, fecha(-400), "Completada", [(10, 1, 700)]),
        (9, 9, 2, None, fecha(-10), "Completada", [(9, 1, 500)]),
        (10, 2, 1, None, fecha(-59), "Completada", [(10, 1, 700), (6, 1, 100)]),
        (11, 3, 1, None, fecha(-60), "Completada", [(10, 2, 700), (2, 1, 5000)]),
        (12, 4, 1, None, base.replace(day=1).isoformat(), "Completada", [(1, 2, 4999), (10, 1, 700)]),
    ]
    detalle = 0
    for n, cliente, profesional, receta, dia, estado, items in ventas:
        agregar("ventas", f"A-V{n:03}", f"A-C{cliente:03}", f"A-F{profesional:03}",
                "" if receta is None else f"A-RC{receta:03}", dia,
                "Venta libre" if receta is None else "Con receta", "Efectivo",
                sum(cantidad * precio for _, cantidad, precio in items), estado)
        for producto, cantidad, precio in items:
            detalle += 1
            agregar("detalle_ventas", f"A-D{detalle:03}", f"A-V{n:03}", f"A-PRD{producto:03}", cantidad, precio)
    return tablas


def _casos():
    return [
        {"caso": "sin_historial", "ids": ["A-C010"], "ejercita": "q03/q12"},
        {"caso": "multiples_recetas", "ids": ["A-C001", "A-RC001", "A-RC002"], "ejercita": "q04"},
        {"caso": "activo_sin_ventas", "ids": ["A-F010"], "ejercita": "q05; q14 rechaza droguería"},
        {"caso": "historico_inactivo", "ids": ["A-F002", "A-V002", "A-V003"], "ejercita": "q02/q10/q11 sin borrar historia; q15 rechaza profesional inactivo"},
        {"caso": "producto_activo_proveedor_inactivo", "ids": ["A-PRD010", "A-PRV010"], "ejercita": "q01"},
        {"caso": "cliente_producto_inactivos", "ids": ["A-C009", "A-PRD009", "A-V009"], "ejercita": "historia y rechazo operacional q14"},
        {"caso": "stock_0_49_50", "ids": ["A-L005", "A-L006", "A-L007", "A-L016"], "ejercita": "q08; incluir cero/vencidos, excluir 50"},
        {"caso": "fefo_dos_lotes", "ids": ["A-V005", "A-L001", "A-L002", "A-L003", "A-L015"], "ejercita": "q15; vencido/hoy/futuro y sucursal"},
        {"caso": "proximas_ayer_hoy_manana", "ids": ["A-RC001", "A-RC002", "A-RC003"], "ejercita": "q06"},
        {"caso": "agotada_y_vencida", "ids": ["A-RC004", "A-RC007"], "ejercita": "rechazos q14/q15"},
        {"caso": "4999_5000_y_pendiente", "ids": ["A-V001", "A-V002", "A-V003", "A-V007"], "ejercita": "q09; excluir anulada"},
        {"caso": "rollback_multiproducto", "ids": ["A-V006", "A-L010", "A-L011"], "ejercita": "q14/q15; un producto insuficiente"},
        {"caso": "frontera_60_dias", "ids": ["A-V010", "A-V011"], "ejercita": "q05; -59 incluido, -60 excluido"},
        {"caso": "mes_actual_y_compra_antigua", "ids": ["A-V012", "A-V008", "A-C008"], "ejercita": "q11/q12"},
    ]


def _csv_bytes(tabla, filas):
    salida = io.StringIO(newline="")
    writer = csv.DictWriter(salida, fieldnames=CAMPOS[tabla], lineterminator="\n")
    writer.writeheader()
    writer.writerows(filas)
    return salida.getvalue().encode("utf-8")


def construir_archivos(base, huella_originales):
    filas = _datos(base)
    contenidos = {f"{tabla}.csv": _csv_bytes(tabla, rows) for tabla, rows in filas.items()}
    manifiesto = {
        "tipo": "farmared_adicionales", "version_generador": VERSION_GENERADOR, "base_date": base.isoformat(),
        "huella_originales": huella_originales,
        "archivos": {f"{tabla}.csv": {"sha256": hashlib.sha256(contenidos[f"{tabla}.csv"]).hexdigest(), "filas": len(rows)} for tabla, rows in filas.items()},
        "casos": _casos(),
    }
    contenidos[NOMBRE_MANIFIESTO] = (json.dumps(manifiesto, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    return contenidos
