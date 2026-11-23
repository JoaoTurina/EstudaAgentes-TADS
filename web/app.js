'use strict';
const $ = id => document.getElementById(id);
const feedback = (message, bad=false) => { $('feedback').textContent=message; $('feedback').className=bad?'error':'success'; };
async function api(path, data) {
  const opts=data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)};
  const res=await fetch(path,opts); const obj=await res.json();
  if(!res.ok) throw new Error(obj.error || `HTTP ${res.status}`);
  return obj;
}
function node(tag,text,cls){const e=document.createElement(tag);e.textContent=text;if(cls)e.className=cls;return e;}
function clear(id){$(id).replaceChildren();}
async function refresh(){
  const {tasks}=await api('/api/tasks');clear('tasks');
  if(!tasks.length)$('tasks').append(node('p','Nenhuma tarefa cadastrada.'));
  for(const t of tasks){
    const wrap=node('div','', 'task');
    wrap.append(node('strong',`${t.title} ${t.done?'✓':''}`),node('p',`${t.subject} • Prazo: ${t.deadline} • ${t.minutes} min • Prioridade ${t.priority}`));
    const b=node('button', t.done?'Reabrir':'Concluir','secondary');
    b.onclick=async()=>{try{await api(`/api/tasks/${t.id}/done`,{done:!Boolean(t.done)});await refresh();}catch(e){feedback(e.message,true)}};
    wrap.append(b);$('tasks').append(wrap);
  }
}
$('taskForm').onsubmit=async event=>{
  event.preventDefault(); const form=new FormData(event.currentTarget);const data=Object.fromEntries(form);
  data.minutes=Number(data.minutes);data.priority=Number(data.priority);
  try{await api('/api/tasks',data);feedback('Tarefa cadastrada.');await refresh();event.currentTarget.reset();setTomorrow();}catch(e){feedback(e.message,true)}
};
$('seed').onclick=async()=>{try{const r=await api('/api/demo',{});feedback(`${r.created} tarefas de demonstração adicionadas.`);await refresh()}catch(e){feedback(e.message,true)}};
function setTomorrow(){const d=new Date();d.setDate(d.getDate()+1);$('taskForm').elements.deadline.value=`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;}
$('planForm').onsubmit=async event=>{
  event.preventDefault();const data=Object.fromEntries(new FormData(event.currentTarget));
  data.hours_per_day=Number(data.hours_per_day);data.days=Number(data.days);
  feedback('Processando a solicitação...');
  try{const response=await api('/api/plans',data);renderPlan(response);feedback('Proposta gerada com rastreabilidade.');}catch(e){feedback(e.message,true)}
};
function renderPlan({result:r,trace}){
  $('resultSection').hidden=false;clear('summary');clear('agenda');clear('review');clear('trace');
  $('summary').append(node('p',`ID: ${r.id} | Status: ${r.status} | Modo: ${r.mode}`),node('p',r.reason));
  for(const day of r.plan.days){const d=node('div','', 'day');d.append(node('strong',`${day.date} — saldo ${day.remaining} min`));
    if(!day.sessions.length)d.append(node('p','Sem sessões previstas.','muted'));
    const ul=node('ul','', 'sessions');for(const s of day.sessions)ul.append(node('li',`${s.title} (${s.subject}) — ${s.minutes} min`));d.append(ul);$('agenda').append(d);
  }
  $('review').append(node('p',`Guardrails: ${r.review.approved_by_rules?'aprovados':'violados'}. Pendências: ${r.plan.pending.length}.`));
  for(const p of r.plan.pending)$('review').append(node('p',`Pendente: ${p.title}, ${p.minutes_unallocated} minutos.`, 'error'));
  for(const s of [...r.plan.tips,...r.review.risks,...r.review.violations])$('review').append(node('p',`• ${s}`));
  for(const event of trace)$('trace').append(node('div',`${event.component} / ${event.action}: ${event.summary}`,'event'));
  $('approve').disabled=r.status!=='proposto';$('approve').onclick=async()=>{try{await api(`/api/plans/${r.id}/approve`,{});feedback('Aprovação humana registrada. Nenhum calendário foi alterado.');$('approve').disabled=true;}catch(e){feedback(e.message,true)}};
  $('resultSection').scrollIntoView({behavior:'smooth'});
}
setTomorrow();refresh().catch(e=>feedback(e.message,true));
