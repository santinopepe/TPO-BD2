'use strict';
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const number = (value) => Number(value ?? 0).toLocaleString('es-AR');
const pretty = (value) => JSON.stringify(value, null, 2);
const state = {config:null, status:null, selected:'q01', mode:'saved', format:'table', rows:null, busy:false, collection:null, page:0, documents:null, detail:'documents', documentRequest:0, statusBusy:false,syncBusy:false};
const examples = {
  mongo: pretty({coleccion:'productos', filtro:{activo:true}, orden:{nombre:1}}),
  neo4j:'MATCH (c:Cliente)\nRETURN c.id AS id, c.nombre AS nombre,\n       c.apellido AS apellido\nORDER BY apellido\nLIMIT 100'
};
const editors = {...examples};
let currentEngine = 'mongo';
let toastTimer;
function toast(message) { $('#toast').textContent=message; $('#toast').classList.remove('hidden'); clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('#toast').classList.add('hidden'), 3500); }
function empty(title, text, icon='▤') { return `<div class="empty-state"><span class="empty-icon">${icon}</span><h3>${esc(title)}</h3><p>${esc(text)}</p></div>`; }
function loading() { return '<div class="loading-state"><span class="spinner" aria-hidden="true"></span>Consultando el motor…</div>'; }
async function api(path, options={}) {
  const response = await fetch(path, {...options, headers:{'Content-Type':'application/json', ...options.headers}});
  let data;
  try { data=await response.json(); } catch { throw new Error('El servidor no devolvió JSON. Comprobá que la consola siga en ejecución.'); }
  if (!response.ok) throw new Error(`${data.error || 'No se pudo completar la operación.'}${data.codigo ? ` (${data.codigo})` : ''}`);
  return data;
}
function table(rows) {
  if (!rows.length) return empty('La consulta no devolvió resultados', 'Probá otro filtro o comprobá que esta base tenga datos.');
  const normalized = rows.map(row => row !== null && typeof row === 'object' && !Array.isArray(row) ? row : {valor:row});
  const keys = [...new Set(normalized.flatMap(row=>Object.keys(row)))];
  function cell(value, index) {
    if (value === null || value === undefined) return '<span class="cell-null">null</span>';
    if (typeof value==='boolean') return `<span class="cell-bool ${value?'':'cell-false'}">${value}</span>`;
    if (typeof value==='object') return `<button class="cell-object" data-inspect="${index}" title="Ver documento completo">${esc(Array.isArray(value) ? `[${value.length} elementos]` : JSON.stringify(value))}</button>`;
    return `<span title="${esc(value)}">${esc(value)}</span>`;
  }
  return `<table><thead><tr><th class="row-number">#</th>${keys.map(key=>`<th scope="col">${esc(key)}</th>`).join('')}</tr></thead><tbody>${normalized.map((row,index)=>`<tr><td class="row-number">${index+1}</td>${keys.map(key=>`<td>${cell(row[key], index)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
}
function jsonView(data) { return `<pre class="json-result">${esc(pretty(data))}</pre>`; }
function navigate(page) {
  $$('.page').forEach(el=>el.classList.toggle('hidden',el.id!==`page-${page}`));
  $$('.nav-item').forEach(el=>el.classList.toggle('active',el.dataset.page===page));
  $('#breadcrumb').textContent={consultas:'Consultas',explorador:'Explorar datos',estado:'Estado de los motores',carga:'Cargar CSVs'}[page];
  if (page==='explorador' && !state.collection && state.status?.mongo?.colecciones?.length) selectCollection(state.status.mongo.colecciones[0].nombre);
}
function renderQueryList() {
  const query=$('#query-search').value.toLocaleLowerCase('es');
  const entries=state.config.consultas.filter(q=>`${q.id} ${q.titulo} ${q.descripcion}`.toLocaleLowerCase('es').includes(query));
  $('#query-count').textContent=entries.length;
  $('#query-list').innerHTML=entries.length ? entries.map(q=>`<button class="query-item ${q.id===state.selected?'active':''}" data-query="${q.id}" data-engine="${q.motor}" title="${esc(q.titulo)} · ${q.motor==='mongo'?'MongoDB':'Neo4j'}"><span class="query-code">${q.id.toUpperCase()}</span><span class="query-item-name">${esc(q.titulo)}</span><span class="query-engine"></span></button>`).join('') : '<p class="notice">Sin coincidencias.</p>';
}
function selectQuery(id) {
  const mode=state.mode;
  state.selected=id;
  const q=state.config.consultas.find(q=>q.id===id);
  $('#saved-select').value=id;
  $('#selected-id').textContent=id.toUpperCase();
  $('#query-title').textContent=q.titulo;
  $('#query-description').textContent=q.descripcion;
  $('#parameter-value').value='';
  $('#parameter-label').textContent=q.parametro==='id_cliente'?'ID del cliente':'ID de la sucursal';
  $('#query-parameter').classList.toggle('hidden', !q.parametro);
  $('#saved-write').classList.toggle('hidden', !q.escritura);
  $('#saved-payload').value=q.escritura?q.texto:'';
  if(mode==='custom') loadAssociated();
  setMode(mode, false); renderQueryList(); navigate('consultas');
}
function updateEngine() {
  const engine=state.mode==='saved'? state.config.consultas.find(q=>q.id===state.selected).motor:$('#engine').value;
  $('#engine-label').textContent=engine==='mongo'?'MongoDB':'Neo4j';
  $('#engine-label').classList.toggle('neo4j',engine==='neo4j');
  $('#cypher-parameters').classList.toggle('hidden',engine!=='neo4j');
  $('#editor-help').textContent=engine==='mongo'?'JSON: filtro, pipeline u operacion.':'Cypher de lectura o escritura; parámetros con $nombre.';
  updateAccess();
}
function loadAssociated() {
  const q=state.config.consultas.find(q=>q.id===state.selected);
  editors[currentEngine]=$('#query-text').value;
  currentEngine=q.motor; $('#engine').value=q.motor;
  $('#query-text').value=q.escritura?$('#saved-payload').value:q.texto;
  $('#parameters').value=pretty(q.parametro?{[q.parametro]:$('#parameter-value').value.trim()}:q.parametros);
  $('#example-kind').value='associated';
  $('#example-kind option[value=associated]').textContent=`${q.id.toUpperCase()} · Consulta seleccionada`;
  updateLines();
}
function updateAccess() {
  let writing=false;
  if(state.mode==='saved') writing=state.config.consultas.find(q=>q.id===state.selected).escritura;
  else if($('#engine').value==='mongo') { try { const q=JSON.parse($('#query-text').value); writing=!!q.operacion && !['find','aggregate'].includes(q.operacion); } catch {} }
  else writing=/\b(CREATE|MERGE|SET|DELETE|REMOVE|FOREACH)\b/i.test($('#query-text').value);
  $('#query-access').textContent=writing?'◈ Escritura':'◈ Lectura';
  $('#query-access').classList.toggle('writing',writing);
  $('#write-note').classList.toggle('hidden',!writing);
}
function setMode(mode, associated=true) {
  if(mode==='custom' && state.mode==='saved' && associated) loadAssociated();
  state.mode=mode;
  $$('[data-mode]').forEach(button=>button.classList.toggle('selected',button.dataset.mode===mode));
  $('#saved-query').classList.toggle('hidden',mode!=='saved');
  $('#custom-query').classList.toggle('hidden',mode!=='custom');
  updateEngine();
}
function updateLines() { $('#line-numbers').textContent=Array.from({length:$('#query-text').value.split('\n').length},(_,i)=>i+1).join('\n'); }
function renderResults() {
  if(state.rows===null) return;
  $('#results').innerHTML=state.format==='json'?jsonView(state.rows):table(state.rows);
}
async function runQuery() {
  if(state.busy || !state.config) return;
  const data={limite:Number($('#limit').value)};
  try {
    if(state.mode==='saved') { const q=state.config.consultas.find(q=>q.id===state.selected); if(q.escritura) { JSON.parse($('#saved-payload').value); data.motor='mongo'; data.texto=$('#saved-payload').value; } else data.consulta=state.selected; if(q.parametro) { const value=$('#parameter-value').value.trim(); if(!value) { $('#parameter-value').focus(); throw new Error('Completá el identificador para ejecutar esta consulta.'); } data.parametros={[q.parametro]:value}; } }
    else { data.motor=$('#engine').value; data.texto=$('#query-text').value; if(data.motor==='neo4j') data.parametros=JSON.parse($('#parameters').value); else JSON.parse(data.texto); }
  } catch(error) { $('#query-error').textContent=error instanceof SyntaxError?'El JSON no es válido. Revisá las comillas, llaves y comas.':error.message; $('#query-error').classList.remove('hidden'); return; }
  const resultName=data.consulta || (data.motor==='mongo'?JSON.parse(data.texto).operacion:null) || data.motor;
  $('#results-heading').textContent=`Resultados de ${/^q\d+$/.test(resultName)?resultName.toUpperCase():resultName==='mongo'?'MongoDB':resultName==='neo4j'?'Neo4j':resultName}`;
  state.busy=true; state.rows=null; $('#run-query').disabled=true; $('#run-query').textContent='Ejecutando…'; $('#export').disabled=true;
  $('#query-error').classList.add('hidden'); $('#results').innerHTML=loading(); $('#result-count').textContent='…'; $('#result-duration').textContent='';
  $('#result-footer').classList.remove('warning');
  try {
    const result=await api('/api/consulta',{method:'POST',body:JSON.stringify(data)});
    state.rows=result.resultados;
    state.resultName=resultName;
    $('#result-count').textContent=`${number(result.cantidad)} ${result.cantidad===1?'fila':'filas'}`;
    $('#result-duration').textContent=`${number(result.duracion_ms)} ms`;
    $('#export').disabled=false;
    const changeLabels={insertados:'insertados',modificados:'modificados',eliminados:'eliminados',coincidencias:'coincidencias',nodes_created:'nodos creados',nodes_deleted:'nodos eliminados',relationships_created:'relaciones creadas',relationships_deleted:'relaciones eliminadas',properties_set:'propiedades actualizadas',labels_added:'etiquetas agregadas',labels_removed:'etiquetas eliminadas'};
    const changes=Object.entries(result.cambios || {}).filter(([key,value])=>typeof value==='number' && changeLabels[key]).map(([key,value])=>`${number(value)} ${changeLabels[key]}`).join(' · ');
    $('#result-footer').innerHTML=`<span>${changes?esc(changes)+' · ':''}${result.truncado?`Se muestran las primeras ${number(result.cantidad)} filas. Aumentá el límite o ajustá el filtro.`:'Consulta completada.'}</span><span>${result.escritura?'Escritura ejecutada':'Lectura'}</span>`;
    $('#result-footer').classList.toggle('warning',result.truncado);
    renderResults();
    if(result.escritura) refreshStatus();
  } catch(error) {
    $('#query-error').textContent=error.message; $('#query-error').classList.remove('hidden'); $('#result-count').textContent='Error';
    $('#results').innerHTML=empty('No se pudo ejecutar la consulta','Revisá el mensaje y el estado de los motores.','!');
    $('#result-footer').innerHTML='<span>La consulta no se completó.</span>';
  } finally { state.busy=false; $('#run-query').disabled=false; $('#run-query').innerHTML='<span>▶</span> Ejecutar consulta'; }
}
function badge(engine, label) { const status=state.status?.[engine]; return `<span class="badge ${status?.estado==='listo'?'ok':'error'}">${status?.estado==='listo'?'●':'○'} ${label}</span>`; }
function renderStatus() {
  const {mongo,neo4j}=state.status;
  $('#mongo-badge').outerHTML=badge('mongo','MongoDB').replace('class=','id="mongo-badge" class=');
  $('#neo4j-badge').outerHTML=badge('neo4j','Neo4j').replace('class=','id="neo4j-badge" class=');
  const collections=mongo.colecciones || [];
  const total=collections.filter(c=>c.tipo!=='vista').reduce((sum,c)=>sum+c.documentos,0);
  const facts=(items)=>`<div class="engine-facts">${items.map(([value,label])=>`<div><strong>${value===null?'—':number(value)}</strong><span>${label}</span></div>`).join('')}</div>`;
  $('#engine-status').innerHTML=`<article class="engine-card"><div class="engine-card-header"><h2>MongoDB</h2>${badge('mongo','MongoDB')}</div>${mongo.estado==='listo'?`${facts([[collections.length,'colecciones y vistas'],[total,'documentos'],[mongo.pendientes,'eventos pendientes']])}<p>Base: <code>${esc(mongo.base)}</code></p><p>Los eventos pendientes pertenecen al outbox; el conteo no verifica la consistencia del grafo.</p>`:`<p>${esc(mongo.mensaje)}</p><p>Comprobá MongoDB, el replica set y MONGO_URI en .env.</p>`}</article><article class="engine-card"><div class="engine-card-header"><h2>Neo4j</h2>${badge('neo4j','Neo4j')}</div>${neo4j.estado==='listo'?`${facts([[(neo4j.etiquetas || []).length,'etiquetas'],[(neo4j.relaciones || []).reduce((sum,r)=>sum+r.cantidad,0),'relaciones']])}<p>Proyección del modelo de MongoDB.</p>`:`<p>${esc(neo4j.mensaje)}</p><p>Comprobá Neo4j y NEO4J_PASSWORD en .env.</p>`}</article>`;
  $('#status-collections').innerHTML=mongo.estado==='listo'?table(collections):'<p class="notice">MongoDB no está disponible.</p>';
  $('#collections-list').innerHTML=mongo.estado==='listo'?(collections.length?collections.map(c=>`<button class="collection-item ${state.collection===c.nombre?'active':''}" data-collection="${esc(c.nombre)}"><span>${c.tipo==='vista'?'◫':'▤'}</span><span>${esc(c.nombre)}</span><small>${number(c.documentos)}</small></button>`).join(''):'<p class="notice">La base está vacía. Cargá los datasets con farmared setup.</p>'):`<p class="notice">${esc(mongo.mensaje)}</p>`;
  $('#graph-counts').innerHTML=neo4j.estado==='listo'?`<div class="graph-grid"><div><h3>Etiquetas de nodos</h3>${table(neo4j.etiquetas)}</div><div><h3>Tipos de relación</h3>${table(neo4j.relaciones)}</div></div>`:'<p class="notice">Neo4j no está disponible.</p>';
}
async function refreshStatus() {
  if(state.statusBusy) return;
  state.statusBusy=true; $('#refresh').classList.add('busy'); $('#refresh').disabled=true;
  try { state.status=await api('/api/estado'); renderStatus(); $('#last-refresh').textContent=`Actualizado a las ${new Date().toLocaleTimeString('es-AR',{hour:'2-digit',minute:'2-digit'})}`; if(!$('#page-explorador').classList.contains('hidden') && !state.collection && state.status.mongo.colecciones?.length) selectCollection(state.status.mongo.colecciones[0].nombre); else if(state.collection) loadDocuments(); }
  catch(error) { toast(error.message); $('#mongo-badge').textContent='○ Sin conexión'; $('#neo4j-badge').textContent='○ Sin conexión'; $('#collections-list').innerHTML=`<p class="notice">${esc(error.message)}</p>`; }
  finally { state.statusBusy=false; $('#refresh').classList.remove('busy'); $('#refresh').disabled=false; }
}
function selectCollection(name) { state.collection=name; state.page=0; state.detail='documents'; state.documents=null; $('#collection-title').textContent=name; $('#query-collection').disabled=false; $$('[data-collection]').forEach(button=>button.classList.toggle('active',button.dataset.collection===name)); loadDocuments(); }
async function loadDocuments() {
  if(!state.collection) return;
  const request=++state.documentRequest;
  $('#collection-results').innerHTML=loading(); $('#previous').disabled=true; $('#next').disabled=true; $('#collection-total').textContent='Consultando…';
  try { const data=await api(`/api/documentos?coleccion=${encodeURIComponent(state.collection)}&pagina=${state.page}&limite=50`); if(request!==state.documentRequest) return; state.documents=data; $('#collection-total').textContent=`${number(data.total)} documentos`; renderDocuments(); }
  catch(error) { if(request!==state.documentRequest) return; state.documents=null; $('#collection-total').textContent='Error de lectura'; $('#collection-results').innerHTML=`<div class="error-banner" role="alert">${esc(error.message)}</div>`; }
}
function renderDocuments() {
  if(!state.documents) return;
  const data=state.documents;
  $$('[data-detail]').forEach(button=>button.classList.toggle('active',button.dataset.detail===state.detail));
  $('#collection-results').innerHTML=state.detail==='documents'?table(data.resultados):state.detail==='indexes'? (data.indices.length?table(data.indices):empty('Esta vista no tiene índices propios','Los índices pertenecen a las colecciones de origen.')):jsonView(data.opciones);
  $('#page-info').textContent=data.total?`${number(state.page*50+1)}–${number(Math.min((state.page+1)*50,data.total))} de ${number(data.total)}`:'Sin documentos';
  $('#previous').disabled=state.page===0; $('#next').disabled=(state.page+1)*50>=data.total;
}
function inspect(event,rows) { const button=event.target.closest('[data-inspect]'); if(!button || !rows) return; $('#document-content').textContent=pretty(rows[Number(button.dataset.inspect)]); $('#document-dialog').showModal(); }
function initEvents() {
  $$('.nav-item').forEach(button=>button.addEventListener('click',()=>navigate(button.dataset.page)));
  $('#query-search').addEventListener('input',renderQueryList);
  $('#query-list').addEventListener('click',event=>{ const button=event.target.closest('[data-query]'); if(button) selectQuery(button.dataset.query); });
  $('#saved-select').addEventListener('change',event=>selectQuery(event.target.value));
  $$('[data-mode]').forEach(button=>button.addEventListener('click',()=>setMode(button.dataset.mode)));
  $$('[data-format]').forEach(button=>button.addEventListener('click',()=>{ state.format=button.dataset.format; $$('[data-format]').forEach(b=>b.classList.toggle('selected',b===button)); renderResults(); }));
  $('#engine').addEventListener('change',()=>{ editors[currentEngine]=$('#query-text').value; currentEngine=$('#engine').value; $('#query-text').value=editors[currentEngine]; updateLines(); updateEngine(); });
  $('#query-text').addEventListener('input',()=>{updateLines();updateAccess();});
  $('#query-text').addEventListener('scroll',()=>{ $('#line-numbers').scrollTop=$('#query-text').scrollTop; });
  $('#query-text').addEventListener('keydown',event=>{ if(event.key==='Tab') { event.preventDefault(); const el=event.target; const start=el.selectionStart,end=el.selectionEnd; el.setRangeText('  ',start,end,'end'); updateLines(); } });
  $('#load-example').addEventListener('click',()=>{
    const kind=$('#example-kind').value;
    if(kind==='associated') loadAssociated();
    else {
      const samples=currentEngine==='mongo'?{
        read:examples.mongo,
        insert:pretty({coleccion:'pruebas_ui',operacion:'insertOne',documento:{_id:'UI-001',nombre:'Ejemplo',activo:true}}),
        update:pretty({coleccion:'pruebas_ui',operacion:'updateOne',filtro:{_id:'UI-001'},actualizacion:{$set:{nombre:'Actualizado'}}}),
        delete:pretty({coleccion:'pruebas_ui',operacion:'deleteOne',filtro:{_id:'UI-001'}})
      }:{read:examples.neo4j,insert:'CREATE (n:PruebaUI {id: $id, nombre: $nombre})\nRETURN n',update:'MATCH (n:PruebaUI {id: $id})\nSET n.nombre = $nombre\nRETURN n',delete:'MATCH (n:PruebaUI {id: $id})\nDETACH DELETE n'};
      $('#query-text').value=samples[kind];
      $('#parameters').value=currentEngine==='neo4j'?pretty({id:'UI-001',nombre:'Ejemplo'}):'{}';
    }
    updateLines();updateEngine();
  });
  $('#saved-payload').addEventListener('input',updateAccess);
  $('#run-query').addEventListener('click',runQuery);
  document.addEventListener('keydown',event=>{ if(event.key==='Enter' && (event.metaKey || event.ctrlKey) && !$('#page-consultas').classList.contains('hidden') && !$('#document-dialog').open) { event.preventDefault(); runQuery(); } });
  $('#refresh').addEventListener('click',refreshStatus);
  $('#export').addEventListener('click',()=>{ if(state.rows===null)return; const blob=new Blob([pretty(state.rows)],{type:'application/json'}); const url=URL.createObjectURL(blob); const link=document.createElement('a'); link.href=url; link.download=`farmared-${state.resultName}-${new Date().toISOString().slice(0,10)}.json`; link.click(); setTimeout(()=>URL.revokeObjectURL(url),1000); });
  $('#collections-list').addEventListener('click',event=>{ const button=event.target.closest('[data-collection]'); if(button) selectCollection(button.dataset.collection); });
  $$('[data-detail]').forEach(button=>button.addEventListener('click',()=>{ state.detail=button.dataset.detail; renderDocuments(); }));
  $('#previous').addEventListener('click',()=>{ state.page--;loadDocuments(); }); $('#next').addEventListener('click',()=>{ state.page++;loadDocuments(); });
  $('#query-collection').addEventListener('click',()=>{ $('#engine').value='mongo'; currentEngine='mongo'; $('#query-text').value=pretty({coleccion:state.collection,filtro:{}}); updateLines(); setMode('custom',false); navigate('consultas'); });
  $('#results').addEventListener('click',event=>inspect(event,state.rows));
  $('#collection-results').addEventListener('click',event=>inspect(event,state.detail==='indexes'?state.documents?.indices:state.documents?.resultados));
  $('#close-document').addEventListener('click',()=>$('#document-dialog').close());
}
async function init() {
  try {
    state.config=await api('/api/config');
    for(const id of ['base-sidebar','base-footer','collection-base','csv-base','csv-destination']) $(`#${id}`).textContent=state.config.base;
    $('#saved-select').innerHTML=state.config.consultas.map(q=>`<option value="${q.id}">${q.id.toUpperCase()} · ${esc(q.titulo)}</option>`).join('');
    $('#query-text').value=examples.mongo; updateLines(); initEvents(); initCsv(); selectQuery('q01');
    refreshStatus();
  } catch(error) { $('#query-error').textContent=error.message; $('#query-error').classList.remove('hidden'); $('#run-query').disabled=true; }
}

const csvState={files:[],payload:null,preview:null,busy:false};
function csvSource(){return $('input[name="csv-source"]:checked').value;}
function invalidateCsv(){
  csvState.payload=null;csvState.preview=null;
  $('#csv-import').disabled=true;$('#csv-error').classList.add('hidden');$('#csv-report').innerHTML='';
  $('#csv-progress').textContent='Validá los archivos para revisar los datos antes de importar.';
  $('#csv-validate').disabled=csvState.busy || (csvSource()==='archivos' && !csvState.files.length);
}
function renderCsvFiles(){
  const bytes=csvState.files.reduce((sum,file)=>sum+file.size,0);
  $('#csv-file-count').textContent=csvState.files.length?`${csvState.files.length} archivos · ${number(Math.ceil(bytes/1024))} KiB`:'Ningún archivo seleccionado';
  $('#csv-file-list').innerHTML=csvState.files.map(file=>`<div><span>${esc(file.webkitRelativePath || file.name)}</span><small>${number(file.size)} bytes</small></div>`).join('');
  $('#csv-clear').disabled=csvState.busy || !csvState.files.length;
}
function csvBusy(busy){
  csvState.busy=busy;
  $$('input[name="csv-source"],#csv-dataset,#csv-files,#csv-folder').forEach(input=>input.disabled=busy || state.syncBusy);
  $$('[data-sync]').forEach(button=>button.disabled=busy || state.syncBusy);
  $('#csv-validate').disabled=busy || state.syncBusy || (csvSource()==='archivos' && !csvState.files.length);
  $('#csv-import').disabled=busy || state.syncBusy || !csvState.preview?.valido || !!csvState.preview?.carga;
  $('#csv-clear').disabled=busy || !csvState.files.length;
}
async function csvPayload(){
  if(csvSource()==='proyecto') return {origen:'proyecto',conjunto:$('#csv-dataset').value};
  const files=csvState.files;
  if(!files.length) throw new Error('Seleccioná los nueve CSVs o una carpeta con el dataset.');
  if(files.length>100 || files.reduce((sum,file)=>sum+file.size,0)>10*1024*1024) throw new Error('Se admiten hasta 100 archivos y 10 MiB por carga.');
  const archivos=await Promise.all(files.map(async file=>{
    const bytes=new Uint8Array(await file.arrayBuffer());let binary='';
    for(let i=0;i<bytes.length;i+=32768) binary+=String.fromCharCode(...bytes.subarray(i,i+32768));
    return {nombre:file.webkitRelativePath || file.name,contenido_base64:btoa(binary)};
  }));
  return {origen:'archivos',archivos};
}
function renderCsvReport(data){
  const totals=data.conteos || {}, documents=data.conteos_documentos || {};
  const filas=Object.values(totals).reduce((sum,n)=>sum+n,0), docs=Object.values(documents).reduce((sum,n)=>sum+n,0);
  const carga=data.carga;
  const sync=data.sincronizacion;
  const synced=sync && sync.estado!=='error' && sync.pendientes_observados===0;
  const title=carga?(synced?(carga.reutilizada?'Carga existente verificada':'MongoDB y Neo4j cargados'):'MongoDB cargado; Neo4j pendiente'):data.valido?'Archivos válidos':'Revisá los archivos';
  const description=carga?`${number(carga.eventos_emitidos)} eventos nuevos en MongoDB. ${synced?`Neo4j: ${number(sync.procesados)} eventos procesados; sin pendientes observados.`:'La sincronización con Neo4j se puede reintentar con el botón de arriba.'}`:data.valido?`${number(filas)} filas CSV se transforman en ${number(docs)} documentos de negocio.`:`Se encontraron ${number(data.errores.length)} errores. Corregí los archivos y volvé a validar.`;
  let html=`<div class="csv-result-heading ${data.valido?'valid':'invalid'}"><div><h2>${esc(title)}</h2><p>${esc(description)}</p></div>${carga?'<button id="csv-explore" class="secondary-button">Explorar datos</button>':''}</div>`;
  if(data.valido) html+=`<div class="csv-counts">${table(Object.entries(totals).map(([archivo,filas])=>({Archivo:`${archivo}.csv`,'Filas CSV':filas,Documentos:documents[archivo] ?? 'Incluidos en ventas'})))}</div>`;
  if(data.preparacion_consultas?.estado==='error') html+=`<div class="error-banner">${esc(data.preparacion_consultas.mensaje)}</div>`;
  for(const [key,label] of [['errores','Errores que impiden cargar'],['avisos','Avisos del dataset']]){
    if(data[key]?.length) html+=`<details class="csv-diagnostics" ${key==='errores'?'open':''}><summary>${label} (${number(data[key].length)})</summary><div>${table(data[key].slice(0,200))}</div>${data[key].length>200?'<p class="muted">Se muestran los primeros 200 diagnósticos.</p>':''}</details>`;
  }
  if(data.huella) html+=`<div class="csv-fingerprint">Huella de los archivos <code>${esc(data.huella)}</code></div>`;
  $('#csv-report').innerHTML=html;
  $('#csv-explore')?.addEventListener('click',()=>navigate('explorador'));
}
async function processCsv(importar=false){
  if(csvState.busy || state.syncBusy) return;
  if(!importar){csvState.payload=null;csvState.preview=null;}
  csvBusy(true);$('#csv-error').classList.add('hidden');
  const button=importar?$('#csv-import'):$('#csv-validate');button.textContent=importar?'Importando…':'Validando…';
  $('#csv-progress').textContent=importar?'Cargando MongoDB y sincronizando Neo4j…':'Validando estructura, valores y referencias entre archivos…';
  try{
    const payload=importar?{...csvState.payload,huella_esperada:csvState.preview.huella}:await csvPayload();
    const result=await api(`/api/carga/${importar?'importar':'validar'}`,{method:'POST',body:JSON.stringify(payload)});
    csvState.payload=payload;csvState.preview=result;
    if(result.sincronizacion) result.sincronizacion=await syncNeo4j(result.sincronizacion);
    renderCsvReport(result);
    $('#csv-progress').textContent=result.carga?((result.sincronizacion?.estado==='error' || result.sincronizacion?.pendientes_observados!==0)?'MongoDB está cargado; reintentá la sincronización de Neo4j.':result.carga.reutilizada?'Carga existente verificada y sincronización completada.':'Importación y sincronización completadas.'):(result.valido?'Validación completada. Ya podés importar los datos.':'La validación encontró errores; no se puede importar.');
    if(result.carga && !result.sincronizacion) await refreshStatus();
  }catch(error){
    $('#csv-error').textContent=error.message;$('#csv-error').classList.remove('hidden');
    $('#csv-progress').textContent=importar?'No se pudo completar la importación.':'No se pudo validar la selección.';
    if(importar) refreshStatus();
  }finally{button.textContent=importar?'Importar datos':'Validar archivos';csvBusy(false);}
}
function initCsv(){
  const names=['clientes','sucursales','farmaceuticos','proveedores','productos','stock_lotes','recetas','ventas','detalle_ventas'];
  $('#csv-required-files').innerHTML=names.map(name=>`<code>${name}.csv</code>`).join('');
  $$('input[name="csv-source"]').forEach(input=>input.addEventListener('change',()=>{
    $('#csv-project').classList.toggle('hidden',csvSource()!=='proyecto');$('#csv-upload').classList.toggle('hidden',csvSource()!=='archivos');invalidateCsv();
  }));
  $('#csv-dataset').addEventListener('change',()=>{invalidateCsv();$('#csv-project-description').textContent=$('#csv-dataset').value==='completo'?'Carga los nueve CSVs originales, los nueve adicionales y su manifiesto.':'Carga únicamente los nueve CSVs originales del proyecto.';});
  for(const id of ['csv-files','csv-folder']) $(`#${id}`).addEventListener('change',event=>{
    invalidateCsv();
    const incoming=[...event.target.files].filter(file=>file.name.endsWith('.csv') || file.name==='manifiesto.json' || file.name==='.generacion_incompleta');
    const names=new Set(csvState.files.map(file=>file.webkitRelativePath || file.name));
    if(incoming.some(file=>names.has(file.webkitRelativePath || file.name))){$('#csv-error').textContent='Hay archivos repetidos. Quitá la selección actual o elegí la carpeta data completa para conservar las rutas de los conjuntos.';$('#csv-error').classList.remove('hidden');}
    else csvState.files.push(...incoming);
    event.target.value='';renderCsvFiles();$('#csv-validate').disabled=!csvState.files.length;
  });
  $('#csv-clear').addEventListener('click',()=>{csvState.files=[];invalidateCsv();renderCsvFiles();});
  $$('[data-sync]').forEach(button=>button.addEventListener('click',()=>syncNeo4j()));
  $('#csv-validate').addEventListener('click',()=>processCsv());$('#csv-import').addEventListener('click',()=>processCsv(true));
}
function showSync(result){
  const failed=result.estado==='error';
  const pending=result.pendientes_observados;
  const title=failed?'Sincronización pendiente':pending===0?'Sincronización completada':'Sincronización en curso';
  const detail=`${number(result.procesados)} eventos procesados. ${pending===null || pending===undefined?'No se pudo comprobar la cantidad pendiente.':`${number(pending)} eventos pendientes observados.`}`;
  const errors=(result.fallidos || []).map(error=>error.causa || error.mensaje || error.codigo).filter(Boolean).join(' ');
  $$('.sync-result').forEach(element=>{element.innerHTML=`<div class="sync-summary ${failed?'failed':''}"><strong>${esc(title)}</strong><p>${esc(detail)}</p>${errors?`<p>${esc(errors)}</p>`:''}</div>`;});
}
async function syncNeo4j(initial=null){
  if(state.syncBusy) return initial;
  state.syncBusy=true;let processed=0,result=initial;
  $$('[data-sync]').forEach(button=>{button.disabled=true;button.textContent='Sincronizando…';});
  csvBusy(csvState.busy);
  $$('.sync-result').forEach(element=>element.innerHTML='<div class="loading-state sync-loading"><span class="spinner" aria-hidden="true"></span>Sincronizando los eventos con Neo4j…</div>');
  try{
    while(true){
      if(!result) result=await api('/api/sincronizar',{method:'POST',body:'{}'});
      processed+=result.procesados || 0;
      showSync({...result,procesados:processed});
      if(result.estado==='error' || result.pendientes_observados===0 || !result.limite_alcanzado || !result.procesados) break;
      result=null;
    }
    result={...result,procesados:processed};
  }catch(error){
    result={estado:'error',procesados:processed,pendientes_observados:null,fallidos:[{causa:error.message}]};showSync(result);
  }finally{
    await refreshStatus();
    if(!csvState.busy && csvState.preview?.carga){
      csvState.preview.sincronizacion=result;renderCsvReport(csvState.preview);
      $('#csv-progress').textContent=result.estado==='error' || result.pendientes_observados!==0?'MongoDB está cargado; la sincronización de Neo4j sigue pendiente.':'MongoDB y Neo4j sincronizados; no se observaron eventos pendientes.';
    }
    state.syncBusy=false;$$('[data-sync]').forEach(button=>{button.disabled=false;button.textContent='Sincronizar Neo4j';});
    csvBusy(csvState.busy);
  }
  return result;
}
init();
