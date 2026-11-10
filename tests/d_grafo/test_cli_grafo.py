"""Adaptador y registro CLI sin motores; los dobles no son pruebas end-to-end."""

from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock

import pytest
from neo4j.exceptions import ServiceUnavailable, Neo4jError
from pymongo.errors import ConnectionFailure

from farmared.__main__ import COMANDOS, PENDIENTES, main
from farmared import cli_grafo
from farmared.config import Config
from farmared.errores import ErrorDominio


@pytest.fixture
def motores(monkeypatch, tmp_path):
    config = Config(neo4j_password='solo-fixture')
    monkeypatch.setattr(cli_grafo.Config, 'from_env', lambda: config)
    db, driver, contexto = MagicMock(), MagicMock(), MagicMock()
    contexto.__enter__.return_value = driver
    mongo, neo = MagicMock(return_value=db), MagicMock(return_value=contexto)
    monkeypatch.setattr(cli_grafo, 'obtener_mongo', mongo)
    monkeypatch.setattr(cli_grafo, 'obtener_neo4j', neo)
    monkeypatch.setattr(cli_grafo.Path, 'home', lambda: tmp_path)
    return db, driver, contexto, mongo, neo


def test_registro_y_ayuda_sin_importar_drivers():
    assert set(cli_grafo.COMANDOS_GRAFO) <= COMANDOS.keys()
    assert not set(cli_grafo.COMANDOS_GRAFO) & PENDIENTES.keys()
    script = '''
import importlib.abc, sys
class Bloquear(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'pymongo','neo4j'}: raise AssertionError(fullname)
sys.meta_path.insert(0,Bloquear())
from farmared.__main__ import main
main(['--help'])
'''
    r = subprocess.run([sys.executable, '-X', 'utf8', '-c', script], capture_output=True, text=True, encoding='utf-8')
    assert r.returncode == 0, r.stderr
    assert all(c in r.stdout for c in cli_grafo.COMANDOS_GRAFO)


@pytest.mark.parametrize('args', [
    ['q03'], ['q10'], ['sync'], ['grafo-verify'], ['grafo-rebuild'],
    ['q03','--id-cliente',' '], ['q10','--id-sucursal',''],
    ['sync','--base','x','--max-eventos','-1'], ['sync','--base','x','--max-eventos','a'],
    ['sync','--base','x','--max-eventos','1.2'], ['sync','--base','x','--lock-path',''],
])
def test_argumentos_requeridos_e_invalidos(args, motores):
    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 2
    motores[3].assert_not_called()
    motores[4].assert_not_called()


@pytest.mark.parametrize('consulta,id_arg,id_valor,nombre', [
    ('q03','--id-cliente','C1','q03_historial'), ('q04',None,None,'q04_clientes_con_recetas'),
    ('q10','--id-sucursal','S1','q10_clientes_sucursal'),
])
def test_consultas_delegacion_y_fechas_iso(consulta, id_arg, id_valor, nombre, motores, monkeypatch, capsys):
    from importlib import import_module
    filas = [dict(fecha=date(2026,1,2), detalle=dict(proxima_dispensa=date(2026,2,1)), opcional=None)]
    antes = deepcopy(filas)
    funcion = MagicMock(return_value=filas)
    monkeypatch.setattr(import_module('farmared.consultas.' + consulta), nombre, funcion)
    assert main([consulta] + ([id_arg,id_valor] if id_arg else [])) == 0
    resultado = json.loads(capsys.readouterr().out)
    assert resultado['resultados'] == [dict(fecha='2026-01-02', detalle=dict(proxima_dispensa='2026-02-01'), opcional=None)]
    assert resultado['proyeccion'] == 'eventualmente_consistente'
    assert filas == antes
    funcion.assert_called_once_with(motores[1], *([id_valor] if id_arg else []))
    motores[3].assert_not_called()
    motores[2].__exit__.assert_called_once()


def test_grafo_init_solo_neo4j(motores, monkeypatch, capsys):
    import farmared.grafo as grafo
    preparar = MagicMock()
    monkeypatch.setattr(grafo, 'preparar_grafo', preparar)
    assert main(['grafo-init']) == 0
    preparar.assert_called_once_with(motores[1])
    assert json.loads(capsys.readouterr().out) == dict(comando='grafo-init', esquema='listo')
    motores[3].assert_not_called()


@pytest.mark.parametrize('fallo', [False, True])
def test_sync_limite_resumen_codigo_y_cierre(motores, monkeypatch, capsys, tmp_path, fallo):
    import farmared.proyeccion as proyeccion
    resultado = dict(procesados=0, pendientes_observados=1,
                     fallidos=[dict(codigo='NEO4J_CONEXION')] if fallo else [],
                     estado='error' if fallo else 'limite_alcanzado', limite_alcanzado=True)
    funcion = MagicMock(return_value=resultado)
    monkeypatch.setattr(proyeccion, 'sincronizar', funcion)
    assert main(['sync','--base','farmared_test_cli','--max-eventos','0']) == (1 if fallo else 0)
    funcion.assert_called_once_with(motores[0], motores[1], tmp_path / '.farmared' / 'sync.lock', max_eventos=0)
    assert json.loads(capsys.readouterr().out)['pendientes_observados'] == 1
    assert motores[3].call_args.args[0].mongo_db == 'farmared_test_cli'
    motores[0].client.close.assert_called_once()


@pytest.mark.parametrize('equivalente,confirmado,codigo', [(True, True, 0), (True, False, 1), (False, True, 1)])
def test_verify_solo_exito_con_equivalencia_y_precondiciones(motores, monkeypatch, capsys, tmp_path,
                                                          equivalente, confirmado, codigo):
    import farmared.proyeccion as proyeccion
    funcion = MagicMock(return_value=dict(equivalente=equivalente, diferencias=[], alcance='estado_estable_declarado'))
    monkeypatch.setattr(proyeccion, 'verificar_proyeccion', funcion)
    args=['grafo-verify','--base','test','--lock-path',str(tmp_path/'compartido')]
    assert main(args + (['--confirmar-escrituras-pausadas'] if confirmado else [])) == codigo
    funcion.assert_called_once_with(motores[0], motores[1], tmp_path/'compartido',
                                    confirmar_escrituras_pausadas=confirmado)
    assert json.loads(capsys.readouterr().out)['equivalente'] is equivalente


@pytest.mark.parametrize('opciones', [[], ['--confirmar-entorno-aislado'],
    ['--confirmar-entorno-aislado','--confirmar-escrituras-pausadas']])
def test_rebuild_sin_todas_confirmaciones_no_conecta(motores, capsys, opciones):
    assert main(['grafo-rebuild','--base','test',*opciones]) == 1
    assert 'VALIDACION' in capsys.readouterr().err
    motores[3].assert_not_called()
    motores[4].assert_not_called()


@pytest.mark.parametrize('habilitable', [True, False])
def test_rebuild_delega_confirmaciones_y_no_activa_actualizacion_por_defecto(motores, monkeypatch, capsys,
                                                                         tmp_path, habilitable):
    import farmared.proyeccion as proyeccion
    funcion=MagicMock(return_value=dict(estado='verificada' if habilitable else 'error', habilitable=habilitable))
    monkeypatch.setattr(proyeccion,'reconstruir_grafo',funcion)
    assert main(['grafo-rebuild','--base','test','--confirmar-entorno-aislado',
                 '--confirmar-escrituras-pausadas','--confirmar-sincronizador-pausado']) == (0 if habilitable else 1)
    funcion.assert_called_once_with(motores[0], motores[1], tmp_path/'.farmared'/'sync.lock',
        confirmar_entorno_aislado=True, confirmar_escrituras_pausadas=True,
        confirmar_actualizacion_existente=False)
    assert json.loads(capsys.readouterr().out)['habilitable'] is habilitable


@pytest.mark.parametrize('error,codigo', [(ServiceUnavailable('SECRETO'), 'CONEXION'),
                                        (Neo4jError('SECRETO'), 'INTEGRIDAD')])
def test_errores_reales_no_son_exito_ni_exponen_credenciales(motores, monkeypatch, capsys, error, codigo):
    import farmared.consultas.q04 as modulo
    monkeypatch.setattr(modulo,'q04_clientes_con_recetas',MagicMock(side_effect=error))
    assert main(['q04']) == 1
    salida=capsys.readouterr()
    assert codigo in salida.err and 'SECRETO' not in salida.err
    assert salida.out == ''
    motores[2].__exit__.assert_called_once()


def test_cierra_mongo_si_neo4j_no_conecta(motores, capsys):
    motores[4].side_effect = ErrorDominio('CONEXION','Fallo controlado')
    assert main(['sync','--base','test']) == 1
    motores[0].client.close.assert_called_once()


@pytest.mark.parametrize('base', ['admin','config','local','base.invalida'])
def test_base_invalida_no_conecta(motores, capsys, base):
    assert main(['sync','--base',base]) == 1
    motores[3].assert_not_called()


def test_lock_por_defecto_no_depende_del_cwd(tmp_path, monkeypatch):
    from argparse import Namespace
    monkeypatch.setattr(cli_grafo.Path,'home',lambda:tmp_path)
    uno=cli_grafo._ruta_lock(Namespace(lock_path=None))
    otro=tmp_path/'otro'; otro.mkdir()
    monkeypatch.chdir(otro)
    assert cli_grafo._ruta_lock(Namespace(lock_path=None)) == uno


@pytest.mark.parametrize('consulta,args', [('q03',['--id-cliente','C']), ('q04',[]), ('q10',['--id-sucursal','S'])])
def test_consultas_no_cargan_modulos_pendientes(consulta,args):
    script='''
import sys
from unittest.mock import MagicMock
from farmared import cli_grafo
from farmared.__main__ import main
ctx=MagicMock(); ctx.__enter__.return_value.session.return_value.__enter__.return_value.execute_read.return_value=[]
cli_grafo.obtener_neo4j=lambda config:ctx
codigo=main(sys.argv[1:])
assert {n for n in sys.modules if n.startswith('farmared.consultas.q')} == {'farmared.consultas.'+sys.argv[1]}
raise SystemExit(codigo)
'''
    r=subprocess.run([sys.executable,'-X','utf8','-c',script,consulta,*args],capture_output=True,text=True,encoding='utf-8')
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)['resultados'] == []
