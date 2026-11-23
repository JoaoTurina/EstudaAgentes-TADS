"""Servidor web local da demonstração. Sem dependências de terceiros."""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from . import core

ROOT = Path(__file__).resolve().parent.parent

class Handler(BaseHTTPRequestHandler):
    def respond(self, status, obj):
        data = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ('/', '/index.html'):
            data = (ROOT / 'web' / 'index.html').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'unsafe-inline' 'self'; script-src 'self'; connect-src 'self'")
            self.end_headers()
            self.wfile.write(data)
        elif path == '/app.js':
            data = (ROOT / 'web' / 'app.js').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'application/javascript; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif path == '/api/tasks':
            self.respond(200, {'tasks': core.list_tasks()})
        elif path.startswith('/api/plans/') and len(path.split('/')) == 4:
            try:
                self.respond(200, core.get_plan(path.split('/')[-1]))
            except ValueError as exc:
                self.respond(404, {'error': str(exc)})
        elif path == '/health':
            self.respond(200, {'ok': True})
        else:
            self.respond(404, {'error': 'Rota não encontrada.'})

    def do_POST(self):
        path = urlsplit(self.path).path
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 10000:
                self.respond(413, {'error': 'Corpo JSON vazio ou maior que 10 KB.'})
                return
            body = json.loads(self.rfile.read(size))
            if path == '/api/tasks':
                result = core.add_task(body)
            elif path == '/api/demo':
                result = core.seed_demo()
            elif path == '/api/plans':
                result = core.run_workflow(body)
            elif path.startswith('/api/tasks/') and path.endswith('/done'):
                task_id = int(path.split('/')[3])
                result = core.set_done(task_id, body.get('done'))
            elif path.startswith('/api/plans/') and path.endswith('/approve'):
                result = core.approve_plan(path.split('/')[3])
            else:
                self.respond(404, {'error': 'Rota não encontrada.'})
                return
            self.respond(200, result)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.respond(400, {'error': str(exc)})
        except RuntimeError as exc:
            self.respond(503, {'error': str(exc)})
        except Exception:
            self.respond(500, {'error': 'Erro interno. Consulte os logs do servidor.'})


def main():
    # Bind intencional apenas à interface local.
    port = int(os.getenv('PORT', '8000'))
    print(f'EstudaAgentes: http://127.0.0.1:{port}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()

if __name__ == '__main__':
    main()
