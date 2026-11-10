"""Integridad byte a byte y política de checkout: sin motores ni carga seed."""

import csv
from datetime import date
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
from unittest.mock import MagicMock

import pytest

from farmared.carga.datos_adicionales import construir_archivos
from farmared.carga.formatos import CAMPOS
from farmared.carga.modelos import ErrorDatasets
from farmared.carga.validacion import rutas_desde_directorios, validar_datasets

RAIZ = Path(__file__).resolve().parents[2]
ORIGINALES = RAIZ / 'data/originales'
ADICIONALES = RAIZ / 'data/adicionales'
CONTEOS = dict(clientes=18, sucursales=15, farmaceuticos=17, proveedores=15,
               productos=23, stock_lotes=34, recetas=19, ventas=28, detalle_ventas=38)


def validar(originales=ORIGINALES, adicionales=ADICIONALES):
    return validar_datasets(rutas_desde_directorios(originales, adicionales))


def sha(b):
    return hashlib.sha256(b).hexdigest()


def test_union_versionada_valida_y_conserva_todos_los_registros():
    v = validar()
    assert v.resumen()['errores'] == []
    assert v.resumen()['conteos'] == CONTEOS
    assert sum(CONTEOS.values()) == 207
    assert len(v.fuentes) == 18 and len(v.generaciones) == 1
    assert sum(CONTEOS[c] for c in CONTEOS if c != 'detalle_ventas') == 169


def test_perfil_versionado_reproducible_sin_regenerar_archivos():
    original = validar_datasets(rutas_desde_directorios(ORIGINALES))
    m = json.loads((ADICIONALES / 'manifiesto.json').read_bytes())
    perfil = construir_archivos(date.fromisoformat(m['base_date']), original.huella)
    assert original.huella == m['huella_originales']
    assert perfil['manifiesto.json'] == (ADICIONALES / 'manifiesto.json').read_bytes()
    for nombre, contenido in perfil.items():
        assert contenido == (ADICIONALES / nombre).read_bytes()


@pytest.mark.parametrize('tabla', list(CAMPOS))
def test_hash_exacto_lf_y_minimo_diez_adicionales(tabla):
    datos = (ADICIONALES / f'{tabla}.csv').read_bytes()
    m = json.loads((ADICIONALES / 'manifiesto.json').read_bytes())
    assert b'\r' not in datos
    assert sha(datos) == m['archivos'][f'{tabla}.csv']['sha256']
    filas = list(csv.DictReader(io.StringIO(datos.decode('utf-8'), newline='')))
    assert len(filas) == m['archivos'][f'{tabla}.csv']['filas'] >= 10
    assert all(fila[next(iter(fila))].startswith('A-') for fila in filas)


@pytest.fixture
def copia(tmp_path):
    return shutil.copytree(ADICIONALES, tmp_path / 'adicionales')


@pytest.mark.parametrize('modo', ['un_byte', 'precio', 'id', 'fecha', 'crlf', 'mixto', 'linea_extra'])
def test_manipulaciones_se_rechazan_aunque_csv_pueda_leerse(copia, modo):
    nombre = 'ventas.csv' if modo == 'fecha' else 'detalle_ventas.csv' if modo == 'precio' else 'clientes.csv'
    p = copia / nombre
    previo = p.read_bytes()
    if modo == 'un_byte':
        nuevo = previo.replace(b'Ficticio', b'Ficticia', 1)
    elif modo == 'precio':
        nuevo = previo.replace(b',4999\n', b',4998\n', 1)
    elif modo == 'id':
        nuevo = previo.replace(b'A-C001', b'A-C999', 1)
    elif modo == 'fecha':
        nuevo = previo.replace(b'2026-11-10', b'2026-11-11', 1)
    elif modo == 'crlf':
        nuevo = previo.replace(b'\n', b'\r\n')
    elif modo == 'mixto':
        nuevo = previo.replace(b'\n', b'\r\n', 1)
    else:
        nuevo = previo + b'\n'
    assert nuevo != previo
    if modo in ('crlf', 'mixto'):
        def filas(datos):
            return list(csv.reader(io.StringIO(datos.decode('utf-8'), newline='')))
        assert filas(previo) == filas(nuevo)
    p.write_bytes(nuevo)
    with pytest.raises(ErrorDatasets) as error:
        validar(adicionales=copia)
    assert any(e.codigo == 'GENERACION' for e in error.value.errores)
    assert (copia / 'manifiesto.json').read_bytes() == (ADICIONALES / 'manifiesto.json').read_bytes()


def test_originales_crlf_no_se_aceptan_como_huella_equivalente(tmp_path):
    origen = shutil.copytree(ORIGINALES, tmp_path / 'originales')
    p = origen / 'clientes.csv'
    p.write_bytes(p.read_bytes().replace(b'\n', b'\r\n'))
    with pytest.raises(ErrorDatasets) as error:
        validar(originales=origen)
    assert {'huella_originales', 'perfil'} <= {e.campo for e in error.value.errores}


def test_loader_rechaza_fuente_alterada_antes_de_cualquier_escritura(copia):
    from farmared.carga.mongo import cargar_mongo
    p = copia / 'clientes.csv'
    p.write_bytes(p.read_bytes() + b'\n')
    db = MagicMock()
    with pytest.raises(ErrorDatasets):
        cargar_mongo(db, rutas_desde_directorios(ORIGINALES, copia))
    assert db.mock_calls == []  # Solo ruta de rechazo: no se ejecuta seed ni se abre un motor.


@pytest.mark.parametrize('autocrlf', ['true', 'false', 'input'])
def test_git_checkout_preserva_bytes_con_distintas_configuraciones(tmp_path, autocrlf):
    git = shutil.which('git')
    if git is None:
        pytest.skip('Git requerido solo para comprobar política real de checkout.')
    repo = tmp_path / 'repo'
    repo.mkdir()
    def comando(*args):
        return subprocess.run([git, '-C', str(repo), *args], capture_output=True, text=True, check=True).stdout
    comando('init','--quiet')
    comando('config','core.autocrlf',autocrlf)
    (repo / '.gitattributes').write_bytes((RAIZ / '.gitattributes').read_bytes())
    paths = list(ORIGINALES.glob('*.csv')) + list(ADICIONALES.glob('*.csv')) + [ADICIONALES / 'manifiesto.json']
    esperados = {}
    for p in paths:
        relativo = p.relative_to(RAIZ)
        destino = repo / relativo
        destino.parent.mkdir(parents=True,exist_ok=True)
        esperados[relativo.as_posix()] = p.read_bytes()
        destino.write_bytes(p.read_bytes())
    comando('add','.gitattributes','data')
    # Solo archivos copiados y controlados del repositorio temporal, sin descartar trabajo real.
    for nombre in esperados:
        (repo / nombre).unlink()
    comando('checkout-index','--all')
    for nombre, esperado in esperados.items():
        assert (repo / nombre).read_bytes() == esperado
    atributos = comando('check-attr','text','eol','--',*esperados.keys())
    assert atributos.count('eol: lf') == 19
    assert atributos.count('text: set') == 19
    assert validar(repo / 'data/originales', repo / 'data/adicionales').resumen()['conteos'] == CONTEOS
