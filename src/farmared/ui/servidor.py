"""Servidor HTTP ligado exclusivamente a loopback."""

import json
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from neo4j.exceptions import DriverError, Neo4jError
from pymongo.errors import OperationFailure, PyMongoError

from farmared.config import Config
from farmared.errores import ErrorDominio
from farmared.ui.servicio import Consola, serializable
from farmared.ui.importacion import MAX_CUERPO

ESTATICOS = Path(__file__).with_name("static")


def crear_servidor(config, puerto=8000):
    consola = Consola(config)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, formato, *args):
            # Evita volcar consultas o datos personales en el log HTTP.
            pass

        def responder(self, estado, contenido, tipo="application/json; charset=utf-8"):
            cuerpo = json.dumps(serializable(contenido), ensure_ascii=False, allow_nan=False).encode() if tipo.startswith("application/json") else contenido
            self.send_response(estado)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(cuerpo)

        def local(self):
            hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            host = self.headers.get("Host", "")
            origen = self.headers.get("Origin")
            if host not in hosts or (origen is not None and origen not in {f"http://{h}" for h in hosts}):
                self.responder(403, {"error": "Acceso permitido únicamente desde la consola local."})
                return False
            return True

        def manejar(self, post=False):
            if not self.local():
                return
            ruta = urlsplit(self.path)
            try:
                if post:
                    if ruta.path not in {"/api/consulta", "/api/carga/validar", "/api/carga/importar", "/api/sincronizar"}:
                        self.responder(404, {"error": "Ruta no encontrada."})
                        return
                    if self.headers.get_content_type() != "application/json":
                        self.responder(415, {"error": "Se requiere application/json."})
                        return
                    longitud = int(self.headers.get("Content-Length", "0"))
                    limite = MAX_CUERPO if ruta.path.startswith("/api/carga/") else 65536
                    if not 0 < longitud <= limite:
                        self.responder(413, {"error": f"El cuerpo debe tener entre 1 y {limite} bytes."})
                        return
                    datos = json.loads(self.rfile.read(longitud))
                    if not isinstance(datos, dict) or not isinstance(datos.get("parametros", {}), dict):
                        raise ValueError("Se esperaba un objeto JSON y parámetros de tipo objeto.")
                    if ruta.path == "/api/consulta":
                        self.responder(200, consola.consulta(datos))
                    elif ruta.path == "/api/sincronizar":
                        self.responder(200, consola.sincronizar_neo4j())
                    else:
                        self.responder(200, consola.cargar_csv(datos, importar=ruta.path.endswith("/importar")))
                elif ruta.path == "/api/config":
                    self.responder(200, consola.configuracion())
                elif ruta.path == "/api/estado":
                    self.responder(200, consola.estado())
                elif ruta.path == "/api/documentos":
                    params = parse_qs(ruta.query)
                    self.responder(200, consola.documentos(params.get("coleccion", [""])[0],
                        int(params.get("pagina", ["0"])[0]), int(params.get("limite", ["50"])[0])))
                elif ruta.path in {"/", "/app.js", "/styles.css"}:
                    nombre, tipo = {"/": ("index.html", "text/html; charset=utf-8"),
                        "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                        "/styles.css": ("styles.css", "text/css; charset=utf-8")}[ruta.path]
                    self.responder(200, (ESTATICOS / nombre).read_bytes(), tipo)
                else:
                    self.responder(404, {"error": "Ruta no encontrada."})
            except ErrorDominio as error:
                self.responder(400, {"error": error.mensaje, "codigo": error.codigo})
            except (ValueError, TypeError, OverflowError, RecursionError):
                self.responder(400, {"error": "Revisá el JSON, los parámetros y los números de página o límite."})
            except (OperationFailure, Neo4jError) as error:
                detalle = error.details.get("errmsg", "") if isinstance(error, OperationFailure) and error.details else getattr(error, "message", "")
                self.responder(422, {"error": str(detalle)[:1500] or "El motor rechazó la consulta. Revisá su sintaxis y los permisos.",
                    "codigo": type(error).__name__})
            except (PyMongoError, DriverError) as error:
                self.responder(422, {"error": "El motor rechazó la consulta. Revisá su sintaxis, los campos y la conexión.",
                    "codigo": type(error).__name__})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                self.responder(500, {"error": "No se pudo completar la operación. Revisá el estado de los motores."})

        def do_GET(self):
            self.manejar()

        def do_POST(self):
            self.manejar(post=True)

    servidor = ThreadingHTTPServer(("127.0.0.1", puerto), Handler)
    servidor.daemon_threads = True
    return servidor


def ejecutar(args):
    if not 1 <= args.puerto <= 65535:
        raise ErrorDominio("VALIDACION", "El puerto debe estar entre 1 y 65535.")
    config = Config.from_env()
    if args.base:
        config = replace(config, mongo_db=args.base)
    try:
        servidor = crear_servidor(config, args.puerto)
    except OSError:
        raise ErrorDominio("CONEXION", "No se pudo abrir el puerto local; probá --puerto con otro número.") from None
    print(f"FarmaRed UI: http://127.0.0.1:{args.puerto} (MongoDB: {config.mongo_db})", flush=True)
    print("Ctrl+C para cerrar la consola.", flush=True)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()
    return 0
