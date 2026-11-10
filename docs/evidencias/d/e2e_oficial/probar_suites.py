"""Suites D y general con todos los motores sobre otro Compose UUID exclusivo."""

import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

p=Path(__file__).with_name('ejecutar.py')
spec=importlib.util.spec_from_file_location('evidencia_e2e',p)
e=importlib.util.module_from_spec(spec);spec.loader.exec_module(e)


def main():
    proyectos=[];resultados=[]
    previos=dict(contenedores=e.proceso(['docker','ps','-aq']).stdout.splitlines(),
                 volumenes=e.proceso(['docker','volume','ls','-q']).stdout.splitlines())
    fuentes={p.relative_to(e.RAIZ).as_posix():e.hashlib.sha256(p.read_bytes()).hexdigest()
             for p in list((e.RAIZ/'data/originales').glob('*.csv'))+list((e.RAIZ/'data/adicionales').glob('*.csv'))+
                      [e.RAIZ/'data/adicionales/manifiesto.json']}
    resumen=dict(origen='pruebas_automatizadas_con_fixtures_en_entorno_exclusivo',ejecuciones=resultados)
    try:
        with TemporaryDirectory(prefix='farmared_suites_d_') as tmp:
            t=Path(tmp)
            proyecto=e.crear_proyecto(t,'farmared_d_oficial_pruebas_'+uuid4().hex,proyectos)
            e.compose(proyecto,'up','-d','mongodb','neo4j')
            e.compose(proyecto,'run','--rm','mongodb-init')
            e.compose(proyecto,'up','-d','--wait','--wait-timeout','180','mongodb','neo4j')
            env=e.entorno_host(proyecto,'farmared_test_suite_d',t/'suite.lock')
            env.update({k:'1' for k in ('FARMARED_TEST_GRAFO','FARMARED_TEST_SYNC','FARMARED_TEST_CLI',
                                       'FARMARED_TEST_MONGO','FARMARED_TEST_INTEGRACION')})
            env.pop('FARMARED_EVIDENCIAS_D',None)
            git=shutil.which('git')
            if not git and os.name=='nt':
                opciones=sorted((Path(os.environ['LOCALAPPDATA'])/'GitHubDesktop').glob('app-*/resources/app/git/cmd/git.exe'))
                if opciones:git=str(opciones[-1])
            if git:env['PATH']=str(Path(git).parent)+os.pathsep+env['PATH']
            e.cli('salud_suites',['salud'],env)
            for nombre,seleccion in [('persona_d',['tests/d_grafo']),('general',[])]:
                args=[sys.executable,'-m','pytest',*seleccion,'-q']
                print('Iniciando suite',nombre,flush=True)
                r=subprocess.run(args,cwd=e.RAIZ,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=1200)
                def seguro(texto):
                    texto=texto.replace(env['NEO4J_PASSWORD'],'<SECRETO_REDACTADO>')
                    return re.sub(r'NEO4J_AUTH=neo4j/[^\s\x27\x22,]+','NEO4J_AUTH=neo4j/<REDACTADO>',texto)
                registro=dict(suite=nombre,comando=['python','-m','pytest',*seleccion,'-q'],exit_code=r.returncode,
                              stdout=seguro(r.stdout),stderr=seguro(r.stderr))
                resultados.append(registro);e.guardar('pruebas',resumen)
                print(nombre,r.returncode,r.stdout.splitlines()[-1],flush=True)
            resumen['limpieza']=[e.limpiar(p) for p in reversed(proyectos)];proyectos.clear()
    finally:
        for p in reversed(proyectos):
            # Limpieza mediante las variables ya presentes; no reconstruir secretos fuera de un temporal.
            with TemporaryDirectory(prefix='farmared_limpieza_') as tmp:
                archivo=Path(tmp)/'.env';archivo.write_text('NEO4J_PASSWORD='+p['env']['NEO4J_PASSWORD']+'\n',encoding='utf-8')
                copia={**p,'base':list(p['base'])};copia['base'][copia['base'].index('--env-file')+1]=str(archivo)
                resumen.setdefault('limpieza',[]).append(e.limpiar(copia))
        resumen['fuentes_intactas']=all(e.hashlib.sha256((e.RAIZ/p).read_bytes()).hexdigest()==h for p,h in fuentes.items())
        resumen['recursos_previos_conservados']=(set(previos['contenedores'])<=set(e.proceso(['docker','ps','-aq']).stdout.splitlines())
            and set(previos['volumenes'])<=set(e.proceso(['docker','volume','ls','-q']).stdout.splitlines()))
        e.guardar('pruebas',resumen)
        print('Evidencias de pruebas:',e.EVIDENCIAS.relative_to(e.RAIZ),flush=True)
    return int(any(r['exit_code'] for r in resultados) or len(resultados)!=2)


if __name__=='__main__':raise SystemExit(main())
