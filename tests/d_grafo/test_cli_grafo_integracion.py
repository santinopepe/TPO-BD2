"""CLI real y Compose de A, con fixture sintético explícito, nunca dataset oficial."""

from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from farmared.config import Config
from farmared.conexiones import obtener_mongo, obtener_neo4j

pytestmark = pytest.mark.skipif(os.environ.get('FARMARED_TEST_CLI') != '1',
                               reason='Activar FARMARED_TEST_CLI=1 para CLI y Compose aislado.')
RAIZ = Path(__file__).resolve().parents[2]


def ejecutar_proceso(args, *, env=None, timeout=180):
    return subprocess.run(args, cwd=RAIZ, env=env, capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=timeout)


@pytest.fixture(scope='module')
def entorno_cli(tmp_path_factory):
    temporal = tmp_path_factory.mktemp('compose_cli_d')
    proyecto = 'farmared_d_cli_' + uuid4().hex
    clave = uuid4().hex
    archivo = temporal / '.env'
    archivo.write_text('NEO4J_PASSWORD=' + clave + '\nMONGO_PORT=0\nNEO4J_HTTP_PORT=0\nNEO4J_BOLT_PORT=0\n', encoding='utf-8')
    base = ['docker','compose','--project-name',proyecto,'--env-file',str(archivo),
            '-f',str(RAIZ/'infra/docker-compose.yml')]
    def compose(*args, comprobar=True):
        env_compose={**os.environ,'NEO4J_PASSWORD':clave,'MONGO_PORT':'0',
                     'NEO4J_HTTP_PORT':'0','NEO4J_BOLT_PORT':'0'}
        r=ejecutar_proceso([*base,*args],env=env_compose)
        if comprobar:
            assert r.returncode == 0, r.stderr
        return r
    try:
        compose('up','-d','mongodb','neo4j')
        compose('run','--rm','mongodb-init')
        compose('up','-d','--wait','--wait-timeout','150','mongodb','neo4j')
        mongo_puerto=compose('port','mongodb','27017').stdout.strip().rsplit(':',1)[1]
        neo_puerto=compose('port','neo4j','7687').stdout.strip().rsplit(':',1)[1]
        env={**os.environ,'PYTHONUTF8':'1',
             'MONGO_URI':f'mongodb://127.0.0.1:{mongo_puerto}/?replicaSet=rs0&directConnection=true',
             'MONGO_DB':'farmared_test_d_cli','NEO4J_URI':f'bolt://127.0.0.1:{neo_puerto}',
             'NEO4J_USER':'neo4j','NEO4J_PASSWORD':clave,'DB_TIMEOUT_MS':'3000'}
        yield dict(env=env, base=env['MONGO_DB'], lock=temporal/'compartido.lock', proyecto=proyecto)
    finally:
        # Solo volúmenes del proyecto nuevo creado aquí; ningún nombre compartido.
        assert proyecto.startswith('farmared_d_cli_') and len(proyecto) == len('farmared_d_cli_') + 32
        volumenes=ejecutar_proceso(['docker','volume','ls','-q','--filter',f'label=com.docker.compose.project={proyecto}'])
        for volumen in volumenes.stdout.splitlines():
            inspeccion=ejecutar_proceso(['docker','volume','inspect',volumen])
            assert json.loads(inspeccion.stdout)[0]['Labels']['com.docker.compose.project'] == proyecto
        compose('down','--volumes','--remove-orphans')


def test_cli_real_compose_y_evidencia_fixture(entorno_cli, fuente):
    e=entorno_cli
    registros=[]
    def cli(*args, esperado=0, env=None):
        r=ejecutar_proceso([sys.executable,'-m','farmared',*args], env=env or e['env'])
        registro=dict(comando=['python','-m','farmared',*args], exit_code=r.returncode,
                      stdout=json.loads(r.stdout) if r.stdout.strip() else None, stderr=r.stderr.strip())
        # La ruta temporal concreta no es necesaria para reproducir la instrucción.
        registro['comando']=['<LOCK_COMPARTIDO>' if a == str(e['lock']) else a for a in registro['comando']]
        registros.append(registro)
        assert r.returncode == esperado, registro
        return registro['stdout']
    salud=cli('salud')
    assert salud['mongo']['primario'] is True and salud['neo4j']['estado'] == 'listo'
    cli('preparar-mongo','--base',e['base'])
    cli('grafo-init')
    config=Config.from_env(e['env'])
    db=obtener_mongo(config)
    try:
        prefijo=fuente['clientes']['_id'].rsplit('-',1)[0]
        def normalizar(v):
            if isinstance(v,dict): return {k:normalizar(x) for k,x in v.items()}
            if isinstance(v,list): return [normalizar(x) for x in v]
            return v.replace(prefijo,'CLI') if isinstance(v,str) else v
        docs=normalizar(deepcopy(fuente))
        segunda=dict(docs['recetas'],_id='CLI-R2')
        # Documentos válidos del fixture, insertados junto con sus eventos. No seed CSV.
        documentos=[('ventas',docs['ventas'])]+[(c,d) for c,d in docs.items() if c != 'ventas']+[('recetas',segunda)]
        with db.client.start_session() as sesion:
            with sesion.start_transaction():
                for i,(coleccion,doc) in enumerate(documentos):
                    db[coleccion].insert_one(doc,session=sesion)
                    db.outbox.insert_one(dict(_id=f'CLI-E{i:02}',procesado=False,
                        creado_en=datetime(2026,11,10,12,tzinfo=UTC),
                        afectadas=[dict(coleccion=coleccion,id=doc['_id'])]),session=sesion)
        fuente_antes={c:list(db[c].find({}).sort('_id',1)) for c in docs}
        parametros=['--base',e['base'],'--lock-path',str(e['lock'])]
        atrasada=cli('grafo-verify',*parametros,'--confirmar-escrituras-pausadas',esperado=1)
        assert not atrasada['equivalente'] and atrasada['diferencias']
        inicial=cli('sync',*parametros)
        assert inicial['procesados'] == 7 and inicial['pendientes_observados'] == 0 and not inicial['fallidos']
        verificacion=cli('grafo-verify',*parametros,'--confirmar-escrituras-pausadas')
        assert verificacion['equivalente'] and verificacion['diferencias'] == []
        assert verificacion['conteos'] == dict(nodos_esperados=7,nodos_observados=7,relaciones_esperadas=8,relaciones_observadas=8)
        puntual=cli('grafo-verify',*parametros,esperado=1)
        assert puntual['equivalente'] and puntual['alcance'] == 'diagnostico_puntual'
        q03=cli('q03','--id-cliente','CLI-C')
        q04=cli('q04')
        q10=cli('q10','--id-sucursal','CLI-S')
        assert [r['tipo_evento'] for r in q03['resultados']] == ['RECETA','RECETA','VENTA']
        assert [r['fecha'] for r in q03['resultados']] == ['2026-01-01','2026-01-01','2026-01-02']
        assert [i['precio_unit'] for i in q03['resultados'][-1]['detalle']['items']] == [100,120]
        assert q04['resultados'] == [dict(id_cliente='CLI-C',nombre='Ana',apellido='Prueba',cantidad=2)]
        assert q10['resultados'] == [dict(id_cliente='CLI-C',nombre='Ana',apellido='Prueba')]
        repetida=cli('sync',*parametros)
        assert repetida['procesados'] == 0
        assert cli('q03','--id-cliente','INEXISTENTE')['resultados'] == []
        assert cli('q10','--id-sucursal','INEXISTENTE')['resultados'] == []
        # Fallo de conectividad real antes de proyectar, con un evento reentregado.
        db.outbox.update_one({'_id':'CLI-E00'},{'$set':{'procesado':False}})
        with socket.socket() as reserva:
            reserva.bind(('127.0.0.1',0))
            env_fallo={**e['env'],'NEO4J_URI':f'bolt://127.0.0.1:{reserva.getsockname()[1]}','DB_TIMEOUT_MS':'500'}
            cli('sync',*parametros,esperado=1,env=env_fallo)
        assert db.outbox.find_one({'_id':'CLI-E00'})['procesado'] is False
        recuperada=cli('sync',*parametros)
        assert recuperada['procesados'] == 1
        assert cli('grafo-verify',*parametros,'--confirmar-escrituras-pausadas')['equivalente']
        outbox_antes=list(db.outbox.find({}).sort('_id',1))
        cli('grafo-rebuild',*parametros,esperado=1)
        confirmaciones=['--confirmar-entorno-aislado','--confirmar-escrituras-pausadas','--confirmar-sincronizador-pausado']
        rechazo=cli('grafo-rebuild',*parametros,*confirmaciones,esperado=1)
        assert rechazo['error']['codigo'] == 'ACTUALIZACION_NO_CONFIRMADA'
        reconstruida=cli('grafo-rebuild',*parametros,*confirmaciones,'--confirmar-actualizacion-existente')
        assert reconstruida['habilitable'] and reconstruida['verificacion']['equivalente']
        assert list(db.outbox.find({}).sort('_id',1)) == outbox_antes
        assert {c:list(db[c].find({}).sort('_id',1)) for c in docs} == fuente_antes
        with obtener_neo4j(config) as driver:
            with driver.session() as sesion:
                restricciones=sesion.run('SHOW CONSTRAINTS YIELD name, type, entityType, labelsOrTypes, properties '
                                          'RETURN name,type,entityType,labelsOrTypes,properties ORDER BY name').data()
                componentes=sesion.run('CALL dbms.components() YIELD name, versions, edition RETURN name,versions,edition').data()
        assert len(restricciones) == 6
        hello=db.client.admin.command('hello')
        evidencia=dict(fecha=datetime.now(ZoneInfo('America/Argentina/Buenos_Aires')).isoformat(),
            origen='fixture_sintetico_CLI_no_dataset_oficial',carga_csv_ejecutada=False,
            motivo='Union oficial/adicional bloqueada por hashes; esta prueba no sustituye esa demostracion.',
            compose='infra/docker-compose.yml',compose_sha256=hashlib.sha256((RAIZ/'infra/docker-compose.yml').read_bytes()).hexdigest(),
            proyecto_aislado=e['proyecto'],base=e['base'],
            mongodb=dict(version=db.client.server_info()['version'],replica_set=hello['setName'],primario=hello['isWritablePrimary']),
            neo4j=componentes,registros_mongo={c:db[c].count_documents({}) for c in docs},
            eventos_outbox=db.outbox.count_documents({}),comandos=registros)
        destino=os.environ.get('FARMARED_EVIDENCIAS_D')
        if destino:
            carpeta=Path(destino); carpeta.mkdir(parents=True,exist_ok=True)
            (carpeta/'cli_integracion_fixture.json').write_text(json.dumps(evidencia,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            (carpeta/'restricciones_fixture.json').write_text(json.dumps(dict(origen=evidencia['origen'],restricciones=restricciones),
                ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('\nCLI real Compose (fixture):',json.dumps(dict(procesados=inicial['procesados'],repetida=repetida['procesados'],
            recuperada=recuperada['procesados'],equivalente=verificacion['equivalente'],q04=q04['resultados'],q10=q10['resultados']),ensure_ascii=False))
    finally:
        db.client.close()
