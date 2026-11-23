"""Orquestração, ferramentas e limites do EstudaAgentes (stdlib Python)."""
import json
import os
import re
import sqlite3
from contextlib import contextmanager
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

DB_PATH = Path(os.getenv('ESTUDA_DB', str(Path(__file__).resolve().parent.parent / 'estuda.db')))
MAX_TASKS = 25


def _open_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, title TEXT NOT NULL, subject TEXT NOT NULL, deadline TEXT NOT NULL, minutes INTEGER NOT NULL CHECK(minutes BETWEEN 15 AND 600), priority INTEGER NOT NULL CHECK(priority BETWEEN 1 AND 5), done INTEGER NOT NULL DEFAULT 0 CHECK(done IN (0,1)))')
    conn.execute('CREATE TABLE IF NOT EXISTS plans(id TEXT PRIMARY KEY, created_at TEXT NOT NULL, mode TEXT NOT NULL, status TEXT NOT NULL, input_json TEXT NOT NULL, plan_json TEXT NOT NULL, trace_json TEXT NOT NULL)')
    conn.commit()
    return conn


@contextmanager
def connection():
    conn = _open_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def iso_day(value):
    try:
        return date.fromisoformat(value).isoformat()
    except (ValueError, TypeError):
        raise ValueError('Data deve estar no formato AAAA-MM-DD.')


def validate_task(payload):
    if not isinstance(payload, dict):
        raise ValueError('A tarefa deve ser um objeto JSON.')
    title = str(payload.get('title', '')).strip()
    subject = str(payload.get('subject', '')).strip()
    if not 3 <= len(title) <= 120 or not 2 <= len(subject) <= 60:
        raise ValueError('Título deve ter 3–120 caracteres e disciplina 2–60.')
    try:
        minutes, priority = int(payload.get('minutes')), int(payload.get('priority'))
    except (ValueError, TypeError):
        raise ValueError('Duração e prioridade devem ser números inteiros.')
    if not 15 <= minutes <= 600 or not 1 <= priority <= 5:
        raise ValueError('Duração: 15–600 minutos; prioridade: 1–5.')
    deadline = iso_day(payload.get('deadline'))
    if date.fromisoformat(deadline) < date.today():
        raise ValueError('O prazo da tarefa não pode estar no passado.')
    return {'title': title, 'subject': subject, 'deadline': deadline, 'minutes': minutes, 'priority': priority}


def add_task(payload):
    task = validate_task(payload)
    with connection() as conn:
        cur = conn.execute('INSERT INTO tasks(title,subject,deadline,minutes,priority) VALUES (:title,:subject,:deadline,:minutes,:priority)', task)
        return {'id': cur.lastrowid, **task, 'done': False}


def list_tasks(only_open=False):
    with connection() as conn:
        rows = conn.execute('SELECT * FROM tasks WHERE done=0 ORDER BY deadline, priority DESC, id' if only_open else 'SELECT * FROM tasks ORDER BY done, deadline, priority DESC, id').fetchall()
        return [dict(row) for row in rows]


def set_done(task_id, done):
    if type(task_id) is not int or type(done) is not bool:
        raise ValueError('Identificador inteiro e done booleano são obrigatórios.')
    with connection() as conn:
        cur = conn.execute('UPDATE tasks SET done=? WHERE id=?', (int(done), task_id))
        if cur.rowcount != 1:
            raise ValueError('Tarefa não encontrada.')
    return {'id': task_id, 'done': done}


def tools_get_tasks():
    """Ferramenta somente leitura: o modelo não recebe acesso livre ao banco."""
    return list_tasks(only_open=True)[:MAX_TASKS]


def tools_calculate_capacity(hours_per_day, days):
    return {'total_minutes': hours_per_day * 60 * days, 'daily_minutes': hours_per_day * 60}


def ask_model(system, payload, schema=None):
    """Acesso estrito a Ollama local; sem envio de dados a nuvens por padrão."""
    host = os.getenv('OLLAMA_URL', 'http://127.0.0.1:11434').rstrip('/')
    if not re.fullmatch(r'http://(localhost|127\.0\.0\.1)(:\d+)?', host):
        raise RuntimeError('Por segurança, OLLAMA_URL deve apontar para localhost.')
    model = os.getenv('OLLAMA_MODEL', 'llama3.2:3b')
    body = {
        'model': model, 'system': system + '\nResponda SOMENTE JSON válido, sem markdown. Respeite o esquema fornecido.',
        'prompt': json.dumps(payload, ensure_ascii=False), 'stream': False,
        'format': schema if schema is not None else 'json',
        'options': {'temperature': 0}
    }
    request = urllib.request.Request(host + '/api/generate', data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            obj = json.loads(response.read(1024 * 1024))
        result = json.loads(obj['response'])
        if not isinstance(result, dict):
            raise ValueError('O modelo não retornou um objeto JSON.')
        return result
    except Exception as exc:
        raise RuntimeError('Modelo local indisponível ou resposta inválida; verifique Ollama e o modelo.') from exc


def trace_event(trace, component, action, summary):
    trace.append({'time': datetime.now(timezone.utc).isoformat(), 'component': component, 'action': action, 'summary': summary})


def prioritize_agent(tasks, today, mode, trace):
    """Classifica contexto e sugere ordem; não altera tarefas."""
    annotated = [{**t, 'days_left': (date.fromisoformat(t['deadline']) - today).days} for t in tasks]
    deterministic = sorted(annotated, key=lambda t: (t['days_left'], -t['priority'], t['minutes'], t['id']))
    if mode == 'ollama':
        result = ask_model('Você é agente de triagem acadêmica. Avalie urgência, prioridade e esforço. Devolva {"ordered_ids":[inteiros],"reason":"texto curto"}. Use SOMENTE IDs recebidos; não invente tarefas.', {'tasks': annotated}, {
            'type': 'object', 'properties': {'ordered_ids': {'type': 'array', 'items': {'type': 'integer'}}, 'reason': {'type': 'string'}}, 'required': ['ordered_ids', 'reason']})
        ids = result.get('ordered_ids')
        expected = {t['id'] for t in annotated}
        if not isinstance(ids, list) or len(ids) != len(expected) or any(type(i) is not int for i in ids) or set(ids) != expected:
            raise ValueError('Triagem produziu IDs incorretos.')
        mapping = {t['id']: t for t in annotated}
        ordered = [mapping[i] for i in ids]
        reason = str(result.get('reason', ''))[:350]
    else:
        ordered, reason = deterministic, 'Simulação determinística: prazo mais próximo, maior prioridade e menor duração.'
    trace_event(trace, 'triagem', 'ordenar', f'{len(ordered)} tarefas priorizadas; {reason}')
    return ordered, reason


def allocate(ordered, hours_per_day, days, today):
    """Alocação segura: nenhuma sessão ultrapassa orçamento diário ou prazo."""
    capacity = hours_per_day * 60
    schedule = [{'date': (today + timedelta(days=i)).isoformat(), 'sessions': [], 'remaining': capacity} for i in range(days)]
    pending = []
    for task in ordered:
        remaining = task['minutes']
        for day in schedule:
            if remaining <= 0:
                break
            if day['date'] > task['deadline']:
                continue
            chunk = min(remaining, day['remaining'], 60)
            if chunk < 15:
                continue
            day['sessions'].append({'task_id': task['id'], 'title': task['title'], 'subject': task['subject'], 'minutes': chunk})
            day['remaining'] -= chunk
            remaining -= chunk
        if remaining:
            pending.append({'task_id': task['id'], 'title': task['title'], 'minutes_unallocated': remaining, 'reason': 'Capacidade insuficiente antes do prazo ou dentro do horizonte.'})
    return {'days': schedule, 'pending': pending}


def planning_agent(ordered, hours_per_day, days, today, mode, trace):
    base = allocate(ordered, hours_per_day, days, today)
    if mode == 'ollama':
        result = ask_model('Você é agente planejador. Recebe plano já validado. Sugira APENAS dicas de execução em {"tips":["...","..."]}. Não altere agenda, datas, capacidades ou prazos.', {'plan': base, 'hours_per_day': hours_per_day}, {
            'type': 'object', 'properties': {'tips': {'type': 'array', 'items': {'type': 'string'}}}, 'required': ['tips']})
        tips = result.get('tips', [])
        if isinstance(tips, str):
            tips = [tips]
        if not isinstance(tips, list) or any(not isinstance(t, str) for t in tips):
            raise ValueError('O agente planejador não retornou dicas de texto válidas (campo tips).')
        base['tips'] = [t.strip()[:200] for t in tips[:3] if t.strip()]
    else:
        base['tips'] = ['Comece pelas tarefas com prazo próximo.', 'Revise o progresso ao fim de cada dia.']
    trace_event(trace, 'planejamento', 'alocar', f'{sum(len(x["sessions"]) for x in base["days"])} sessões; {len(base["pending"])} pendências.')
    return base


def review_agent(plan, tasks, hours_per_day, mode, trace):
    catalog = {t['id']: t for t in tasks}
    used = {}
    violations = []
    for day in plan['days']:
        total = sum(s['minutes'] for s in day['sessions'])
        if total > hours_per_day * 60:
            violations.append(f'Excesso de capacidade em {day["date"]}.')
        for s in day['sessions']:
            t = catalog.get(s['task_id'])
            if not t or day['date'] > t['deadline'] or s['minutes'] <= 0:
                violations.append(f'Sessão inválida: {s["task_id"]}.')
            used[s['task_id']] = used.get(s['task_id'], 0) + s['minutes']
    for task in tasks:
        if used.get(task['id'], 0) > task['minutes']:
            violations.append(f'Tempo excedido na tarefa {task["id"]}.')
    notes = []
    if mode == 'ollama':
        result = ask_model('Você é agente revisor. Identifique riscos de execução, sem autorizar mudanças. Retorne {"risks":["..."]}. Não alegue que a agenda é válida: isso é verificado por código.', {'pending': plan['pending'], 'number_days': len(plan['days'])}, {
            'type': 'object', 'properties': {'risks': {'type': 'array', 'items': {'type': 'string'}}}, 'required': ['risks']})
        risks = result.get('risks', [])
        if isinstance(risks, str):
            risks = [risks]
        if not isinstance(risks, list) or any(not isinstance(r, str) for r in risks):
            raise ValueError('O agente revisor não retornou riscos de texto válidos (campo risks).')
        notes = [r.strip()[:200] for r in risks[:3] if r.strip()]
    if plan['pending']:
        notes.append('Há tarefas sem tempo suficiente; o usuário deve rever capacidade, horizonte ou prazos.')
    trace_event(trace, 'revisao', 'verificar', f'{len(violations)} violações, {len(plan["pending"])} pendências.')
    return {'approved_by_rules': not violations, 'violations': violations, 'risks': notes}


def run_workflow(payload):
    if not isinstance(payload, dict):
        raise ValueError('Envie um objeto JSON.')
    try:
        hours = int(payload.get('hours_per_day'))
        days = int(payload.get('days'))
    except (ValueError, TypeError):
        raise ValueError('Informe horas por dia e quantidade de dias como inteiros.')
    if not (1 <= hours <= 8 and 1 <= days <= 14):
        raise ValueError('Limites: 1–8 horas/dia e horizonte de 1–14 dias.')
    mode = payload.get('mode', 'demo')
    if mode not in ('demo', 'ollama'):
        raise ValueError('Modo deve ser demo ou ollama.')
    trace, today = [], date.today()
    tasks = tools_get_tasks()
    if not tasks:
        raise ValueError('Cadastre pelo menos uma tarefa não concluída.')
    trace_event(trace, 'orquestrador', 'inicio', f'Modo={mode}; tarefas={len(tasks)}; horizonte={days} dias.')
    ordered, reason = prioritize_agent(tasks, today, mode, trace)
    plan = planning_agent(ordered, hours, days, today, mode, trace)
    review = review_agent(plan, tasks, hours, mode, trace)
    status = 'proposto' if review['approved_by_rules'] else 'rejeitado'
    # Aprovação humana é necessária para efetivar; gerar plano nunca altera tarefas.
    output = {'id': uuid4().hex, 'status': status, 'mode': mode, 'reason': reason, 'plan': plan, 'review': review, 'requires_human_approval': True}
    trace_event(trace, 'orquestrador', 'fim', f'Plano {status}; ainda sem aprovação humana.')
    with connection() as conn:
        conn.execute('INSERT INTO plans VALUES(?,?,?,?,?,?,?)', (output['id'], datetime.now(timezone.utc).isoformat(), mode, status, json.dumps(payload, ensure_ascii=False), json.dumps(output, ensure_ascii=False), json.dumps(trace, ensure_ascii=False)))
    return {'result': output, 'trace': trace}


def get_plan(plan_id):
    with connection() as conn:
        row = conn.execute('SELECT * FROM plans WHERE id=?', (plan_id,)).fetchone()
        if not row:
            raise ValueError('Plano não encontrado.')
        return {'result': json.loads(row['plan_json']), 'trace': json.loads(row['trace_json']), 'status': row['status']}


def approve_plan(plan_id):
    with connection() as conn:
        row = conn.execute('SELECT status FROM plans WHERE id=?', (plan_id,)).fetchone()
        if not row:
            raise ValueError('Plano não encontrado.')
        if row['status'] != 'proposto':
            raise ValueError('Somente planos propostos podem ser aprovados uma vez.')
        conn.execute('UPDATE plans SET status=? WHERE id=? AND status=?', ('aprovado', plan_id, 'proposto'))
    return {'id': plan_id, 'status': 'aprovado', 'notice': 'Aprovação registrada; não modifica tarefas nem calendários externos.'}


def seed_demo():
    if list_tasks():
        return {'created': 0, 'message': 'Banco já possui tarefas; não foram duplicadas.'}
    today = date.today()
    examples = [
        ('Revisar algoritmos e estruturas', 'Algoritmos', 2, 120, 5),
        ('Resolver exercícios de banco de dados', 'Banco de Dados', 4, 180, 4),
        ('Preparar apresentação do seminário', 'TADS', 3, 90, 5),
        ('Estudar fundamentos de redes', 'Redes', 6, 120, 3),
    ]
    for title, subject, offset, minutes, priority in examples:
        add_task({'title': title, 'subject': subject, 'deadline': (today + timedelta(days=offset)).isoformat(), 'minutes': minutes, 'priority': priority})
    return {'created': len(examples)}
