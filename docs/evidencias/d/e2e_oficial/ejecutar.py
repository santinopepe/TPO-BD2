"""Evidencia administrativa reproducible. Solo Compose UUID propios; no cambia fuentes."""

from collections import Counter
from datetime import UTC, date, datetime
import hashlib
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from uuid import uuid4
from zoneinfo import ZoneInfo

from farmared.carga.validacion import rutas_desde_directorios, validar_datasets
from farmared.clock import ZONA_COMERCIAL
from farmared.config import Config
from farmared.conexiones import obtener_mongo, obtener_neo4j

RAIZ = Path(__file__).resolve().parents[4]
EVIDENCIAS = Path(__file__).resolve().parent / ('ejecucion_' + datetime.now(UTC).strftime('%Y%m%dT%H%M%S') + '_' + uuid4().hex[:8])
EVIDENCIAS.mkdir()
PROYECTABLES = ('clientes','sucursales','farmaceuticos','productos','recetas','ventas')
BITACORA = []


def serializar(valor):
    if isinstance(valor, (datetime,date)):
        return valor.isoformat()
    if hasattr(valor,'to_native'):
        return valor.to_native().isoformat()
    raise TypeError(type(valor).__name__)


def guardar(nombre, dato):
    (EVIDENCIAS / (nombre + '.json')).write_text(json.dumps(dato,ensure_ascii=False,indent=2,default=serializar)+'\n',encoding='utf-8')


def huella(datos):
    return hashlib.sha256(json.dumps(datos,ensure_ascii=False,sort_keys=True,default=serializar).encode('utf-8')).hexdigest()


def proceso(args, *, env=None, timeout=900):
    return subprocess.run(args,cwd=RAIZ,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)


def cli(nombre, argumentos, env):
    inicio=time.monotonic()
    r=proceso([sys.executable,'-m','farmared',*argumentos],env=env)
    dato=json.loads(r.stdout) if r.stdout.strip() else None
    registro=dict(comando=['python','-m','farmared',*argumentos],exit_code=r.returncode,
                  segundos_observados=round(time.monotonic()-inicio,3),stdout=dato,stderr=r.stderr.strip())
    registro['comando']=['<LOCK_COMPARTIDO>' if a==env.get('LOCK_D') else a for a in registro['comando']]
    guardar(nombre,registro)
    BITACORA.append(dict(paso=nombre,**registro)); guardar('comandos',BITACORA)
    assert r.returncode==0, f'{nombre}: exit={r.returncode}; {r.stderr.strip()}'
    print(nombre, 'exit=0',flush=True)
    return dato


def crear_proyecto(temporal, nombre, proyectos):
    assert not proceso(['docker','ps','-aq','--filter','label=com.docker.compose.project='+nombre]).stdout.strip()
    assert not proceso(['docker','volume','ls','-q','--filter','label=com.docker.compose.project='+nombre]).stdout.strip()
    directorio=temporal/nombre; directorio.mkdir()
    (directorio/'.env.example').write_bytes((RAIZ/'.env.example').read_bytes())
    spec=spec_from_file_location('preparar_env_a',RAIZ/'infra/preparar_env.py')
    modulo=module_from_spec(spec); spec.loader.exec_module(modulo)
    assert modulo.preparar_env(directorio) is True  # Mecanismo de credenciales existente de A.
    archivo=directorio/'.env'
    variables=dict(linea.split('=',1) for linea in archivo.read_text(encoding='utf-8').splitlines()
                   if linea and not linea.startswith('#') and '=' in linea)
    clave=variables['NEO4J_PASSWORD']; assert len(clave)>=8
    entorno={**os.environ,'PYTHONUTF8':'1','NEO4J_PASSWORD':clave,
             'MONGO_PORT':'0','NEO4J_HTTP_PORT':'0','NEO4J_BOLT_PORT':'0'}
    base=['docker','compose','--project-name',nombre,'--env-file',str(archivo),'-f',str(RAIZ/'infra/docker-compose.yml')]
    proyecto=dict(nombre=nombre,base=base,env=entorno)
    proyectos.append(proyecto)
    return proyecto


def compose(proyecto,*args):
    r=proceso([*proyecto['base'],*args],env=proyecto['env'],timeout=240)
    comando=['docker','compose','--project-name',proyecto['nombre'],'--env-file','<ENV_TEMPORAL>',
             '-f','infra/docker-compose.yml',*args]
    BITACORA.append(dict(paso='compose',comando=comando,exit_code=r.returncode,
                        stdout=r.stdout.strip(),stderr=r.stderr.strip()))
    guardar('comandos',BITACORA)
    assert r.returncode==0, f'Compose {args}: {r.stderr}'
    return r.stdout.strip()


def entorno_host(proyecto,base,lock,mongo_uri=None):
    neo_port=compose(proyecto,'port','neo4j','7687').rsplit(':',1)[1]
    if mongo_uri is None:
        mongo_port=compose(proyecto,'port','mongodb','27017').rsplit(':',1)[1]
        mongo_uri=f'mongodb://127.0.0.1:{mongo_port}/?replicaSet=rs0&directConnection=true'
    return {**proyecto['env'],'MONGO_URI':mongo_uri,'MONGO_DB':base,'NEO4J_URI':f'bolt://127.0.0.1:{neo_port}',
            'NEO4J_USER':'neo4j','DB_TIMEOUT_MS':'30000','LOCK_D':str(lock)}


def snapshot_mongo(db, *, incluir_outbox=True):
    return {c:list(db[c].find({}).sort('_id',1)) for c in sorted(db.list_collection_names())
            if incluir_outbox or c!='outbox'}


def snapshot_neo(env):
    with obtener_neo4j(Config.from_env(env)) as driver:
        with driver.session() as s:
            nodos=s.run('MATCH (n) RETURN labels(n) AS etiquetas, n.id AS id, properties(n) AS propiedades ORDER BY id').data()
            relaciones=s.run('MATCH (a)-[r]->(b) RETURN a.id AS origen,b.id AS destino,type(r) AS tipo,properties(r) AS propiedades '
                            'ORDER BY origen,destino,tipo,r.id_detalle').data()
            restricciones=s.run('SHOW CONSTRAINTS YIELD name,type,entityType,labelsOrTypes,properties '
                                 'RETURN name,type,entityType,labelsOrTypes,properties ORDER BY name').data()
            versiones=s.run('CALL dbms.components() YIELD name,versions,edition RETURN name,versions,edition').data()
    return dict(nodos=nodos,relaciones=relaciones,restricciones=restricciones,versiones=versiones)


def dia(valor):
    return valor.astimezone(ZONA_COMERCIAL).date().isoformat() if valor else None


def referencia_q03(db,id_cliente):
    eventos=[]
    for r in db.recetas.find({'id_cliente':id_cliente}):
        eventos.append(dict(fecha=dia(r['fecha_emision']),tipo_evento='RECETA',id_registro=r['_id'],estado=r['estado'],
            detalle=dict(tipo=r['tipo'],medico=r['medico'],dispensas_realizadas=r['dispensas_realizadas'],
                         dispensas_autorizadas=r['dispensas_autorizadas'],proxima_dispensa=dia(r.get('proxima_dispensa')))))
    for v in db.ventas.find({'id_cliente':id_cliente}):
        items=[dict(id_detalle=i['id_detalle'],orden=orden,id_producto=i['id_producto'],nombre_al_vender=i.get('nombre_al_vender'),
                    cantidad=i['cantidad'],precio_unit=i['precio_unit'],subtotal=i['subtotal']) for orden,i in enumerate(v['items'])]
        eventos.append(dict(fecha=dia(v['fecha']),tipo_evento='VENTA',id_registro=v['_id'],estado=v['estado'],
            detalle=dict(tipo=v['tipo'],total=v['total'],medio_pago=v['medio_pago'],id_receta=v.get('id_receta'),items=items)))
    return sorted(eventos,key=lambda e:(e['fecha'],e['tipo_evento'],e['id_registro']))


def referencia_q04(db):
    pipeline=[{'$group':{'_id':'$id_cliente','cantidad':{'$sum':1}}},{'$match':{'cantidad':{'$gt':1}}},
              {'$lookup':{'from':'clientes','localField':'_id','foreignField':'_id','as':'cliente'}},{'$unwind':'$cliente'},
              {'$project':{'_id':0,'id_cliente':'$_id','nombre':'$cliente.nombre','apellido':'$cliente.apellido','cantidad':1}},
              {'$sort':{'cantidad':-1,'id_cliente':1}}]
    return pipeline,list(db.recetas.aggregate(pipeline))


def referencia_q10(db,id_sucursal):
    pipeline=[{'$lookup':{'from':'farmaceuticos','localField':'id_farmaceutico','foreignField':'_id','as':'f'}},
              {'$unwind':'$f'},{'$match':{'f.id_sucursal':id_sucursal}},
              {'$group':{'_id':'$id_cliente'}},
              {'$lookup':{'from':'clientes','localField':'_id','foreignField':'_id','as':'c'}},{'$unwind':'$c'},
              {'$project':{'_id':0,'id_cliente':'$_id','nombre':'$c.nombre','apellido':'$c.apellido'}},{'$sort':{'id_cliente':1}}]
    return pipeline,list(db.ventas.aggregate(pipeline))


def seleccionar(db):
    candidatos=[dict(id=c['_id'],ventas=db.ventas.count_documents({'id_cliente':c['_id']}),
                     recetas=db.recetas.count_documents({'id_cliente':c['_id']})) for c in db.clientes.find({}, {'_id':1})]
    candidatos=[c for c in candidatos if c['ventas'] and c['recetas']]
    candidatos.sort(key=lambda c:(-min(c['ventas'],c['recetas']),-c['ventas']-c['recetas'],c['id']))
    assert candidatos
    sucursales=[]
    for s in db.sucursales.find({}, {'_id':1}):
        fs=list(db.farmaceuticos.find({'id_sucursal':s['_id']}))
        ventas=list(db.ventas.find({'id_farmaceutico':{'$in':[f['_id'] for f in fs]}}))
        inactivos={f['_id'] for f in fs if f['activo'] is False}
        if ventas:
            sucursales.append(dict(id=s['_id'],ventas=len(ventas),ventas_profesional_inactivo=sum(v['id_farmaceutico'] in inactivos for v in ventas),
                                   estados=dict(Counter(v['estado'] for v in ventas))))
    sucursales.sort(key=lambda s:(-s['ventas_profesional_inactivo'],-s['estados'].get('Pendiente',0),-s['ventas'],s['id']))
    assert sucursales
    return candidatos,sucursales


def limpiar(proyecto):
    nombre=proyecto['nombre']
    assert nombre.startswith(('farmared_d_oficial_','farmared_d_recuperacion_'))
    volumenes=proceso(['docker','volume','ls','-q','--filter','label=com.docker.compose.project='+nombre]).stdout.splitlines()
    contenedores=proceso(['docker','ps','-aq','--filter','label=com.docker.compose.project='+nombre]).stdout.splitlines()
    for volumen in volumenes:
        dato=json.loads(proceso(['docker','volume','inspect',volumen]).stdout)[0]
        assert dato['Labels']['com.docker.compose.project']==nombre
    for contenedor in contenedores:
        dato=json.loads(proceso(['docker','inspect',contenedor]).stdout)[0]
        assert dato['Config']['Labels']['com.docker.compose.project']==nombre
    compose(proyecto,'down','--volumes','--remove-orphans')
    assert not proceso(['docker','ps','-aq','--filter','label=com.docker.compose.project='+nombre]).stdout.strip()
    assert not proceso(['docker','volume','ls','-q','--filter','label=com.docker.compose.project='+nombre]).stdout.strip()
    return dict(proyecto=nombre,volumenes_propios_eliminados=volumenes,contenedores_propios_retirados=contenedores)


def main():
    proyectos=[]; db=None; resumen=dict(estado='iniciada',origen='datasets_oficiales_mas_adicionales_versionados',
        fecha=datetime.now(ZoneInfo('America/Argentina/Buenos_Aires')).isoformat())
    previos=dict(contenedores=proceso(['docker','ps','-aq']).stdout.splitlines(),volumenes=proceso(['docker','volume','ls','-q']).stdout.splitlines())
    fuentes=sorted((RAIZ/'data/originales').glob('*.csv'))+sorted((RAIZ/'data/adicionales').glob('*.csv'))+[RAIZ/'data/adicionales/manifiesto.json']
    hashes={p.relative_to(RAIZ).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in fuentes}
    guardar('fuentes',dict(hashes_sha256=hashes,compose_sha256=hashlib.sha256((RAIZ/'infra/docker-compose.yml').read_bytes()).hexdigest(),recursos_previos=previos))
    try:
        validacion=cli('01_validacion',['validar-datasets','--directorio','data/originales','--directorio','data/adicionales'],{**os.environ,'PYTHONUTF8':'1'})
        assert validacion['errores']==[] and sum(validacion['conteos'].values())==207
        validado=validar_datasets(rutas_desde_directorios(RAIZ/'data/originales',RAIZ/'data/adicionales'))
        with TemporaryDirectory(prefix='farmared_e2e_oficial_') as tmp:
            temporal=Path(tmp); lock=temporal/'entorno.lock'
            principal=crear_proyecto(temporal,'farmared_d_oficial_'+uuid4().hex,proyectos)
            compose(principal,'up','-d','mongodb','neo4j')
            compose(principal,'run','--rm','mongodb-init')
            compose(principal,'up','-d','--wait','--wait-timeout','180','mongodb','neo4j')
            base='farmared_demo_d_oficial_'+uuid4().hex[:8]
            env=entorno_host(principal,base,lock)
            cli('02_salud',['salud'],env)
            cli('03_preparar_mongo',['preparar-mongo','--base',base],env)
            seed=cli('04_seed',['seed','--base',base,'--directorio','data/originales','--directorio','data/adicionales'],env)
            assert seed['carga']=='completa' and not seed['reutilizada']
            assert sum(seed['conteos_iniciales'].values())==169 and seed['eventos_emitidos']==120
            db=obtener_mongo(Config.from_env(env))
            assert all(db[c].count_documents({})==n for c,n in seed['conteos_iniciales'].items())
            pendientes=db.outbox.count_documents({'procesado':False}); assert pendientes==120
            stock_csv={f.datos['id_lote']:f.datos['unidades'] for f in validado.filas['stock_lotes']}
            assert stock_csv=={d['_id']:d['unidades'] for d in db.stock_lotes.find({})}
            referencias_detalle={(f.datos['id_venta'],f.datos['id_detalle']):(f.datos['cantidad'],f.datos['precio_unit']) for f in validado.filas['detalle_ventas']}
            assert referencias_detalle=={(v['_id'],i['id_detalle']):(i['cantidad'],i['precio_unit']) for v in db.ventas.find({}) for i in v['items']}
            mongo_sin_outbox=huella(snapshot_mongo(db,incluir_outbox=False))
            cli('05_grafo_init',['grafo-init'],env)
            vacio=snapshot_neo(env);assert not vacio['nodos'] and not vacio['relaciones'] and len(vacio['restricciones'])==6
            guardar('06_restricciones',vacio['restricciones'])
            parametros=['--base',base,'--lock-path',str(lock)]
            sync=cli('07_sync_inicial',['sync',*parametros,'--max-eventos','1000'],env)
            assert sync['procesados']==120 and sync['pendientes_observados']==0 and sync['fallidos']==[]
            assert db.outbox.count_documents({'procesado':True})==120
            assert huella(snapshot_mongo(db,incluir_outbox=False))==mongo_sin_outbox
            verificacion=cli('08_verificacion',['grafo-verify',*parametros,'--confirmar-escrituras-pausadas'],env)
            assert verificacion['equivalente'] and not verificacion['diferencias']
            grafo=snapshot_neo(env)
            guardar('09_estado_neo4j',dict(conteos_etiquetas=dict(Counter(e for n in grafo['nodos'] for e in n['etiquetas'])),
                    conteos_relaciones=dict(Counter(r['tipo'] for r in grafo['relaciones'])),versiones=grafo['versiones']))
            candidatos,sucursales=seleccionar(db);cid=candidatos[0]['id'];sid=sucursales[0]['id']
            guardar('10_seleccion_identificadores',dict(clientes=candidatos,sucursales=sucursales,elegidos=dict(id_cliente=cid,id_sucursal=sid)))
            q03=cli('11_q03',['q03','--id-cliente',cid],env)
            q04=cli('12_q04',['q04'],env)
            q10=cli('13_q10',['q10','--id-sucursal',sid],env)
            r03=referencia_q03(db,cid);p04,r04=referencia_q04(db);p10,r10=referencia_q10(db,sid)
            assert q03['resultados']==r03
            assert q04['resultados']==r04 and len(r04)==len({r['id_cliente'] for r in r04})
            assert q10['resultados']==r10 and len(r10)==len({r['id_cliente'] for r in r10})
            guardar('14_referencias_mongo',dict(q03=dict(filtro=dict(id_cliente=cid),resultado=r03),
                    q04=dict(pipeline=p04,resultado=r04),q10=dict(pipeline=p10,resultado=r10),comparacion_exacta=True))
            # Audita todas las sucursales; incluye estados e inactivos sin alterar la semántica.
            auditoria=[]
            for s in db.sucursales.find({}, {'_id':1}).sort('_id',1):
                salida=cli('q10_sucursal_'+s['_id'],['q10','--id-sucursal',s['_id']],env)
                _,ref=referencia_q10(db,s['_id']);assert salida['resultados']==ref
                auditoria.append(dict(id_sucursal=s['_id'],clientes=len(ref),coincide=True))
            guardar('15_auditoria_q10',auditoria)
            sin_historial=next((c['_id'] for c in db.clientes.find({}, {'_id':1})
                               if not db.ventas.count_documents({'id_cliente':c['_id']}) and not db.recetas.count_documents({'id_cliente':c['_id']})),None)
            if sin_historial:
                assert cli('16_q03_sin_historial',['q03','--id-cliente',sin_historial],env)['resultados']==[]
            repetida=cli('17_sync_repetida',['sync',*parametros],env)
            assert repetida['procesados']==0 and not repetida['fallidos'] and repetida['pendientes_observados']==0
            assert huella(snapshot_neo(env))==huella(grafo)
            assert cli('18_q03_repetida',['q03','--id-cliente',cid],env)['resultados']==r03
            assert cli('19_q04_repetida',['q04'],env)['resultados']==r04
            assert cli('20_q10_repetida',['q10','--id-sucursal',sid],env)['resultados']==r10
            assert cli('21_verificacion_repetida',['grafo-verify',*parametros,'--confirmar-escrituras-pausadas'],env)['equivalente']
            mongo_completo=huella(snapshot_mongo(db));grafo_original=huella(snapshot_neo(env))
            recuperacion=crear_proyecto(temporal,'farmared_d_recuperacion_'+uuid4().hex,proyectos)
            compose(recuperacion,'up','-d','--wait','--wait-timeout','180','neo4j')
            env_rec=entorno_host(recuperacion,base,lock,mongo_uri=env['MONGO_URI'])
            assert env_rec['NEO4J_URI']!=env['NEO4J_URI']
            rec_vacio=snapshot_neo(env_rec);assert not rec_vacio['nodos'] and not rec_vacio['relaciones']
            reconstruccion=cli('22_reconstruccion',['grafo-rebuild',*parametros,'--confirmar-entorno-aislado',
                '--confirmar-escrituras-pausadas','--confirmar-sincronizador-pausado'],env_rec)
            assert reconstruccion['habilitable'] and reconstruccion['estado']=='verificada'
            assert cli('23_verificacion_recuperada',['grafo-verify',*parametros,'--confirmar-escrituras-pausadas'],env_rec)['equivalente']
            assert cli('24_q03_recuperada',['q03','--id-cliente',cid],env_rec)['resultados']==r03
            assert cli('25_q04_recuperada',['q04'],env_rec)['resultados']==r04
            assert cli('26_q10_recuperada',['q10','--id-sucursal',sid],env_rec)['resultados']==r10
            assert huella(snapshot_mongo(db))==mongo_completo
            assert huella(snapshot_neo(env))==grafo_original
            assert huella(snapshot_neo(env_rec))==grafo_original
            resumen.update(estado='verificada',validacion_huella=validacion['huella'],base=base,
                documentos_por_coleccion=seed['conteos_iniciales'],documentos_negocio=169,pendientes_iniciales=pendientes,
                procesados_iniciales=sync['procesados'],pendientes_finales=0,nodos=len(grafo['nodos']),relaciones=len(grafo['relaciones']),
                versiones=dict(mongodb=db.client.server_info()['version'],replica_set=db.client.admin.command('hello')['setName'],neo4j=grafo['versiones']),
                consultas=dict(id_cliente=cid,eventos_q03=len(r03),clientes_q04=len(r04),id_sucursal=sid,clientes_q10=len(r10),cliente_sin_historial=sin_historial),
                referencias_mongo_coinciden=True,segunda_sync_procesados=0,reconstruccion_habilitable=True,
                source_mongo_y_outbox_intactos_tras_reconstruccion=True,grafo_original_intacto=True,
                stock_y_precios_historicos_conservados=True)
            db.client.close();db=None
            # Limpiar mientras siguen disponibles los archivos temporales de configuración.
            resumen['limpieza']=[limpiar(p) for p in reversed(proyectos)];proyectos.clear()
    except Exception as error:
        resumen.update(estado='error',tipo_error=type(error).__name__,causa=str(error))
        raise
    finally:
        if db is not None:db.client.close()
        # En un fallo, el env temporal pudo desaparecer: las variables siguen en memoria.
        for p in reversed(proyectos):
            try:
                with TemporaryDirectory(prefix='farmared_limpieza_') as tmp:
                    archivo=Path(tmp)/'.env'
                    archivo.write_text('NEO4J_PASSWORD='+p['env']['NEO4J_PASSWORD']+'\n',encoding='utf-8')
                    copia={**p,'base':list(p['base'])}
                    copia['base'][copia['base'].index('--env-file')+1]=str(archivo)
                    resumen.setdefault('limpieza',[]).append(limpiar(copia))
            except Exception as error:
                resumen.setdefault('errores_limpieza',[]).append(type(error).__name__)
        resumen['fuentes_intactas']=all(hashlib.sha256((RAIZ/p).read_bytes()).hexdigest()==h for p,h in hashes.items())
        resumen['recursos_previos_conservados']=(set(previos['contenedores'])<=set(proceso(['docker','ps','-aq']).stdout.splitlines())
            and set(previos['volumenes'])<=set(proceso(['docker','volume','ls','-q']).stdout.splitlines()))
        guardar('resumen',resumen)
        print('Evidencia:',EVIDENCIAS.relative_to(RAIZ),flush=True)
        print(json.dumps(resumen,ensure_ascii=False,default=serializar),flush=True)


if __name__=='__main__':main()
