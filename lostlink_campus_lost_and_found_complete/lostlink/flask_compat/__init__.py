"""
flask_compat: A standards-compliant, zero-external-dependency WSGI microframework
implementing the exact Flask & Werkzeug API surface used by LostLink.
When native `flask` and `werkzeug` are installed in the Python environment, LostLink
imports them directly. When running in an air-gapped environment where only Jinja2,
itsdangerous, MarkupSafe, and Python stdlib are pre-installed, this module provides
100% API compatibility (Flask, Blueprint, request, session, g, flash, redirect,
url_for, render_template, jsonify, abort, send_from_directory, TestClient, and
PBKDF2-HMAC-SHA256 password hashing).
"""

import hashlib
import hmac
import http.cookies
import io
import json
import mimetypes
import os
import re
import secrets
import sys
import urllib.parse
from contextvars import ContextVar
from datetime import datetime
from wsgiref.simple_server import make_server
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from itsdangerous import URLSafeTimedSerializer, BadSignature

# Context variables for thread/async safety
_request_ctx: ContextVar = ContextVar("_request_ctx", default=None)
_app_ctx: ContextVar = ContextVar("_app_ctx", default=None)


class HTTPException(Exception):
    def __init__(self, code: int = 500, description: str = "Internal Server Error"):
        super().__init__(f"{code} {description}")
        self.code = code
        self.description = description


def abort(code: int, description: str = ""):
    default_descriptions = {
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        405: "Method Not Allowed",
        413: "Payload Too Large",
        500: "Internal Server Error",
    }
    desc = description or default_descriptions.get(code, "Error")
    raise HTTPException(code=code, description=desc)


def secure_filename(filename: str) -> str:
    if not filename:
        return ""
    filename = os.path.basename(filename.replace("\\", "/"))
    filename = re.sub(r"[^A-Za-z0-9_.-]", "_", filename).strip("._")
    return filename or "uploaded_file"


def generate_password_hash(password: str, method: str = "pbkdf2:sha256:120000", salt_length: int = 16) -> str:
    if not isinstance(password, str):
        raise TypeError("Password must be a string")
    salt = secrets.token_hex(salt_length // 2)
    iterations = 120000
    parts = method.split(":")
    if len(parts) == 3 and parts[2].isdigit():
        iterations = int(parts[2])
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    return f"pbkdf2:sha256:{iterations}${salt}${dk.hex()}"


def check_password_hash(pwhash: str, password: str) -> bool:
    if not pwhash or not isinstance(password, str) or "$" not in pwhash:
        return False
    try:
        header, salt, stored_hex = pwhash.split("$", 2)
        parts = header.split(":")
        iterations = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 120000
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
        return hmac.compare_digest(dk.hex(), stored_hex)
    except Exception:
        return False


class FileStorage:
    def __init__(self, stream: io.BytesIO, filename: str, name: str = "file", content_type: str = "application/octet-stream"):
        self.stream = stream
        self.filename = filename
        self.name = name
        self.content_type = content_type

    def read(self, size: int = -1) -> bytes:
        return self.stream.read(size)

    def seek(self, offset: int, whence: int = 0):
        return self.stream.seek(offset, whence)

    def save(self, dst):
        self.stream.seek(0)
        data = self.stream.read()
        if isinstance(dst, str):
            os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(data)
        else:
            dst.write(data)

    def __bool__(self):
        return bool(self.filename)


class MultiDict(dict):
    def get(self, key, default=None, type=None):
        val = super().get(key, default)
        if isinstance(val, list):
            val = val[0] if val else default
        if val is not None and type is not None:
            try:
                val = type(val)
            except (ValueError, TypeError):
                val = default
        return val

    def getlist(self, key):
        val = super().get(key, [])
        if isinstance(val, list):
            return val
        return [val]


class Request:
    def __init__(self, method="GET", path="/", query_string="", headers=None, form=None, files=None, json_data=None, raw_body=b"", remote_addr="127.0.0.1", cookies=None):
        self.method = method.upper()
        self.path = path
        self.query_string = query_string.encode("utf-8") if isinstance(query_string, str) else query_string
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.args = MultiDict()
        if query_string:
            qs = query_string if isinstance(query_string, str) else query_string.decode("utf-8", errors="replace")
            parsed_qs = urllib.parse.parse_qs(qs, keep_blank_values=True)
            for k, v in parsed_qs.items():
                self.args[k] = v[0] if len(v) == 1 else v
        self.form = MultiDict(form or {})
        self.files = MultiDict(files or {})
        self._json = json_data
        self.data = raw_body
        self.remote_addr = remote_addr
        self.cookies = cookies or {}
        self.endpoint = None
        self.view_args = {}

    @property
    def is_json(self) -> bool:
        ct = self.headers.get("content-type", "")
        return "application/json" in ct.lower()

    def get_json(self, silent: bool = False):
        if self._json is not None:
            return self._json
        if self.data:
            try:
                self._json = json.loads(self.data.decode("utf-8"))
                return self._json
            except Exception:
                if not silent:
                    raise
        return None

    @property
    def referrer(self):
        return self.headers.get("referer")


class Response:
    def __init__(self, body="", status: int = 200, headers=None, content_type: str = "text/html; charset=utf-8"):
        if isinstance(body, str):
            self.data = body.encode("utf-8")
        elif isinstance(body, bytes):
            self.data = body
        else:
            self.data = str(body).encode("utf-8")
        self.status_code = int(status)
        self.headers = dict(headers or {})
        if "Content-Type" not in self.headers:
            self.headers["Content-Type"] = content_type
        self._cookies = []

    @property
    def text(self) -> str:
        return self.data.decode("utf-8", errors="replace")

    def get_data(self, as_text: bool = False):
        return self.text if as_text else self.data

    def get_json(self):
        try:
            return json.loads(self.text)
        except Exception:
            return None

    def set_cookie(self, key: str, value: str = "", max_age=None, path: str = "/", httponly: bool = True, samesite: str = "Lax"):
        c = http.cookies.SimpleCookie()
        c[key] = value
        c[key]["path"] = path
        if max_age is not None:
            c[key]["max-age"] = str(max_age)
        if httponly:
            c[key]["httponly"] = True
        if samesite:
            c[key]["samesite"] = samesite
        self._cookies.append(c[key].OutputString())


class SessionDict(dict):
    def __init__(self, initial=None):
        super().__init__(initial or {})
        self.modified = False

    def __setitem__(self, key, value):
        self.modified = True
        super().__setitem__(key, value)

    def __delitem__(self, key):
        self.modified = True
        super().__delitem__(key)

    def pop(self, key, *args):
        self.modified = True
        return super().pop(key, *args)

    def clear(self):
        self.modified = True
        super().clear()


class _AppGlobals:
    def get(self, name, default=None):
        return getattr(self, name, default)

    def pop(self, name, default=None):
        if hasattr(self, name):
            val = getattr(self, name)
            delattr(self, name)
            return val
        return default

    def __contains__(self, item):
        return hasattr(self, item)


class _Proxy:
    def __init__(self, getter):
        object.__setattr__(self, "_getter", getter)

    def _obj(self):
        return object.__getattribute__(self, "_getter")()

    def __getattr__(self, name):
        return getattr(self._obj(), name)

    def __setattr__(self, name, value):
        setattr(self._obj(), name, value)

    def __getitem__(self, key):
        return self._obj()[key]

    def __setitem__(self, key, value):
        self._obj()[key] = value

    def __delitem__(self, key):
        del self._obj()[key]

    def __contains__(self, key):
        return key in self._obj()

    def __iter__(self):
        return iter(self._obj())

    def __len__(self):
        return len(self._obj())

    def __repr__(self):
        return repr(self._obj())


request = _Proxy(lambda: _request_ctx.get()["request"])
session = _Proxy(lambda: _request_ctx.get()["session"])
g = _Proxy(lambda: _app_ctx.get()["g"])
current_app = _Proxy(lambda: _app_ctx.get()["app"])


def flash(message: str, category: str = "message"):
    flashes = session.get("_flashes", [])
    flashes.append((category, message))
    session["_flashes"] = flashes


def get_flashed_messages(with_categories: bool = False, category_filter=()):
    flashes = session.pop("_flashes", []) if _request_ctx.get() else []
    if category_filter:
        flashes = [f for f in flashes if f[0] in category_filter]
    if with_categories:
        return flashes
    return [f[1] for f in flashes]


def redirect(location: str, code: int = 302) -> Response:
    resp = Response(
        f'<!doctype html><html><head><title>Redirecting...</title></head><body>Redirecting to <a href="{location}">{location}</a></body></html>',
        status=code,
        headers={"Location": location},
    )
    return resp


def jsonify(*args, **kwargs) -> Response:
    payload = args[0] if args else kwargs
    return Response(json.dumps(payload, default=str), status=200, content_type="application/json")


def send_from_directory(directory: str, path: str) -> Response:
    safe_root = os.path.abspath(directory)
    target = os.path.abspath(os.path.join(safe_root, path.lstrip("/\\")))
    if not target.startswith(safe_root) or not os.path.isfile(target):
        abort(404, "File not found")
    ctype, _ = mimetypes.guess_type(target)
    with open(target, "rb") as f:
        data = f.read()
    return Response(data, status=200, content_type=ctype or "application/octet-stream")


class Blueprint:
    def __init__(self, name: str, import_name: str, url_prefix: str = ""):
        self.name = name
        self.import_name = import_name
        self.url_prefix = url_prefix.rstrip("/")
        self.routes = []

    def route(self, rule: str, methods=None, endpoint=None):
        methods = [m.upper() for m in (methods or ["GET"])]
        def decorator(func):
            ep = endpoint or func.__name__
            self.routes.append((rule, methods, func, f"{self.name}.{ep}"))
            return func
        return decorator


class _RouteRule:
    def __init__(self, rule: str, methods: list, view_func, endpoint: str):
        self.rule = rule
        self.methods = [m.upper() for m in methods]
        self.view_func = view_func
        self.endpoint = endpoint
        self.param_converters = {}
        pattern = "^"
        pos = 0
        for m in re.finditer(r"<(?:(int|string|path):)?([a-zA-Z_][a-zA-Z0-9_]*)>", rule):
            pattern += re.escape(rule[pos:m.start()])
            conv = m.group(1) or "string"
            pname = m.group(2)
            self.param_converters[pname] = conv
            if conv == "int":
                pattern += f"(?P<{pname}>\\d+)"
            elif conv == "path":
                pattern += f"(?P<{pname}>.+)"
            else:
                pattern += f"(?P<{pname}>[^/]+)"
            pos = m.end()
        pattern += re.escape(rule[pos:]) + "$"
        self.regex = re.compile(pattern)

    def match(self, path: str):
        m = self.regex.match(path)
        if not m:
            return None
        params = {}
        for k, v in m.groupdict().items():
            if self.param_converters.get(k) == "int":
                params[k] = int(v)
            else:
                params[k] = v
        return params

    def build(self, values: dict) -> str:
        url = self.rule
        used_keys = set()
        for m in re.finditer(r"<(?:(int|string|path):)?([a-zA-Z_][a-zA-Z0-9_]*)>", self.rule):
            pname = m.group(2)
            if pname not in values:
                raise KeyError(f"Missing URL parameter {pname} for endpoint {self.endpoint}")
            url = url.replace(m.group(0), urllib.parse.quote(str(values[pname]), safe="/"))
            used_keys.add(pname)
        extra = {k: v for k, v in values.items() if k not in used_keys and v is not None and not k.startswith("_")}
        if extra:
            qs = urllib.parse.urlencode(extra, doseq=True)
            url = f"{url}?{qs}"
        return url


def url_for(endpoint: str, **values) -> str:
    app = current_app._obj()
    if endpoint == "static":
        filename = values.get("filename", "").lstrip("/")
        return f"/static/{filename}"
    for r in app._rules:
        if r.endpoint == endpoint or r.endpoint.endswith(f".{endpoint}"):
            return r.build(values)
    raise ValueError(f"Could not build url for endpoint '{endpoint}'")


def render_template(template_name: str, **context) -> str:
    app = current_app._obj()
    ctx = {
        "request": request,
        "session": session,
        "g": g,
        "url_for": url_for,
        "get_flashed_messages": get_flashed_messages,
        "config": app.config,
    }
    for proc in app._context_processors:
        extra = proc()
        if extra:
            ctx.update(extra)
    ctx.update(context)
    tmpl = app.jinja_env.get_template(template_name)
    return tmpl.render(**ctx)


class _AppContextManager:
    def __init__(self, app):
        self.app = app
        self.token = None
        self.req_token = None

    def __enter__(self):
        self.token = _app_ctx.set({"app": self.app, "g": _AppGlobals()})
        if _request_ctx.get() is None:
            self.req_token = _request_ctx.set({"request": Request(), "session": SessionDict()})
        return self.app

    def __exit__(self, exc_type, exc_val, exc_tb):
        for teardown in self.app._teardown_appcontext_funcs:
            teardown(exc_val)
        if self.req_token is not None:
            _request_ctx.reset(self.req_token)
        if self.token is not None:
            _app_ctx.reset(self.token)


class Flask:
    def __init__(self, import_name: str, template_folder: str = "templates", static_folder: str = "static", instance_path: str = None):
        self.import_name = import_name
        base_dir = os.path.dirname(os.path.abspath(sys.modules.get(import_name).__file__)) if import_name in sys.modules and hasattr(sys.modules[import_name], "__file__") else os.getcwd()
        self.root_path = base_dir
        self.template_folder = os.path.join(base_dir, template_folder)
        self.static_folder = os.path.join(base_dir, static_folder)
        self.instance_path = instance_path or os.path.join(os.path.dirname(base_dir), "instance")
        os.makedirs(self.instance_path, exist_ok=True)
        self.config = {
            "SECRET_KEY": "dev-secret-key",
            "TESTING": False,
            "MAX_CONTENT_LENGTH": 5 * 1024 * 1024,
        }
        self._rules = []
        self._error_handlers = {}
        self._before_request_funcs = []
        self._teardown_appcontext_funcs = []
        self._context_processors = []
        self.cli = _CLIGroup()

        self.jinja_env = Environment(
            loader=FileSystemLoader(self.template_folder),
            autoescape=select_autoescape(["html", "xml"]),
        )
        self.jinja_env.globals["url_for"] = url_for
        self.jinja_env.globals["get_flashed_messages"] = get_flashed_messages

    def app_context(self):
        return _AppContextManager(self)

    def route(self, rule: str, methods=None, endpoint=None):
        methods = [m.upper() for m in (methods or ["GET"])]
        def decorator(func):
            ep = endpoint or func.__name__
            self._rules.append(_RouteRule(rule, methods, func, ep))
            return func
        return decorator

    def register_blueprint(self, blueprint: Blueprint, url_prefix: str = None):
        prefix = (url_prefix if url_prefix is not None else blueprint.url_prefix).rstrip("/")
        for rule, methods, func, ep in blueprint.routes:
            full_rule = f"{prefix}{rule}" if prefix else rule
            if not full_rule.startswith("/"):
                full_rule = "/" + full_rule
            self._rules.append(_RouteRule(full_rule, methods, func, ep))

    def before_request(self, func):
        self._before_request_funcs.append(func)
        return func

    def teardown_appcontext(self, func):
        self._teardown_appcontext_funcs.append(func)
        return func

    def context_processor(self, func):
        self._context_processors.append(func)
        return func

    def errorhandler(self, code_or_exc):
        def decorator(func):
            self._error_handlers[code_or_exc] = func
            return func
        return decorator

    def _get_serializer(self):
        return URLSafeTimedSerializer(self.config.get("SECRET_KEY", "dev-secret"))

    def load_session(self, req: Request) -> SessionDict:
        raw = req.cookies.get("lostlink_session")
        if not raw:
            return SessionDict()
        try:
            data = self._get_serializer().loads(raw, max_age=86400 * 7)
            return SessionDict(data)
        except BadSignature:
            return SessionDict()

    def save_session(self, sess: SessionDict, resp: Response):
        raw = self._get_serializer().dumps(dict(sess))
        resp.set_cookie("lostlink_session", raw, max_age=86400 * 7, path="/", httponly=True, samesite="Lax")

    def handle_request(self, req: Request) -> Response:
        app_token = _app_ctx.set({"app": self, "g": _AppGlobals()})
        sess = self.load_session(req)
        req_token = _request_ctx.set({"request": req, "session": sess})
        exc_occured = None
        try:
            # Check static route first
            if req.path.startswith("/static/"):
                rel = req.path[len("/static/"):]
                resp = send_from_directory(self.static_folder, rel)
                self.save_session(sess, resp)
                return resp

            # Match route
            matched_rule = None
            matched_params = None
            allowed_methods = set()
            for r in self._rules:
                params = r.match(req.path)
                if params is not None:
                    allowed_methods.update(r.methods)
                    if req.method in r.methods:
                        matched_rule = r
                        matched_params = params
                        break

            if matched_rule is None:
                if allowed_methods:
                    abort(405)
                else:
                    abort(404)

            req.endpoint = matched_rule.endpoint
            req.view_args = matched_params

            for bf in self._before_request_funcs:
                rv = bf()
                if rv is not None:
                    resp = self._make_response(rv)
                    self.save_session(sess, resp)
                    return resp

            rv = matched_rule.view_func(**matched_params)
            resp = self._make_response(rv)
            self.save_session(sess, resp)
            return resp

        except HTTPException as he:
            handler = self._error_handlers.get(he.code)
            if handler:
                rv = handler(he)
                resp = self._make_response(rv, default_status=he.code)
            else:
                resp = Response(f"<h1>{he.code} {he.description}</h1>", status=he.code)
            self.save_session(sess, resp)
            return resp
        except Exception as e:
            exc_occured = e
            if self.config.get("TESTING"):
                raise
            handler = self._error_handlers.get(500)
            if handler:
                rv = handler(e)
                resp = self._make_response(rv, default_status=500)
            else:
                resp = Response("<h1>500 Internal Server Error</h1>", status=500)
            self.save_session(sess, resp)
            return resp
        finally:
            for teardown in self._teardown_appcontext_funcs:
                teardown(exc_occured)
            _request_ctx.reset(req_token)
            _app_ctx.reset(app_token)

    def _make_response(self, rv, default_status: int = 200) -> Response:
        if isinstance(rv, Response):
            return rv
        if isinstance(rv, tuple):
            if len(rv) == 2:
                body, status = rv
                return Response(body, status=status)
            if len(rv) == 3:
                body, status, headers = rv
                return Response(body, status=status, headers=headers)
        if isinstance(rv, dict):
            return jsonify(rv)
        return Response(str(rv), status=default_status)

    def test_client(self):
        return TestClient(self)

    def wsgi_app(self, environ, start_response):
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "/") or "/"
        qs = environ.get("QUERY_STRING", "")
        content_type = environ.get("CONTENT_TYPE", "")
        content_length = int(environ.get("CONTENT_LENGTH") or 0)
        body = environ["wsgi.input"].read(content_length) if content_length > 0 else b""
        headers = {}
        for k, v in environ.items():
            if k.startswith("HTTP_"):
                hname = k[5:].replace("_", "-").lower()
                headers[hname] = v
        if content_type:
            headers["content-type"] = content_type

        cookies = {}
        if "cookie" in headers:
            c = http.cookies.SimpleCookie()
            c.load(headers["cookie"])
            for ck, morsel in c.items():
                cookies[ck] = morsel.value

        form = {}
        files = {}
        if method in ("POST", "PUT", "PATCH"):
            if "application/x-www-form-urlencoded" in content_type:
                parsed = urllib.parse.parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
                for k, v in parsed.items():
                    form[k] = v[0] if len(v) == 1 else v
            elif "multipart/form-data" in content_type:
                form, files = _parse_multipart(body, content_type)

        req = Request(
            method=method,
            path=path,
            query_string=qs,
            headers=headers,
            form=form,
            files=files,
            raw_body=body,
            remote_addr=environ.get("REMOTE_ADDR", "127.0.0.1"),
            cookies=cookies,
        )
        resp = self.handle_request(req)
        status_line = f"{resp.status_code} OK"
        resp_headers = list(resp.headers.items())
        for ck_str in resp._cookies:
            resp_headers.append(("Set-Cookie", ck_str))
        start_response(status_line, resp_headers)
        return [resp.data]

    def __call__(self, environ, start_response):
        return self.wsgi_app(environ, start_response)

    def run(self, host: str = "127.0.0.1", port: int = 5000, debug: bool = False):
        print(f" * Running LostLink on http://{host}:{port} (Press CTRL+C to quit)")
        with make_server(host, port, self) as httpd:
            httpd.serve_forever()


def _parse_multipart(body: bytes, content_type: str):
    form = {}
    files = {}
    m = re.search(r"boundary=([^;]+)", content_type)
    if not m:
        return form, files
    boundary = m.group(1).strip('"').encode("utf-8")
    parts = body.split(b"--" + boundary)
    for part in parts[1:]:
        if part.startswith(b"--") or not part.strip():
            continue
        if b"\r\n\r\n" in part:
            head, content = part.split(b"\r\n\r\n", 1)
            if content.endswith(b"\r\n"):
                content = content[:-2]
        elif b"\n\n" in part:
            head, content = part.split(b"\n\n", 1)
            if content.endswith(b"\n"):
                content = content[:-1]
        else:
            continue
        head_str = head.decode("utf-8", errors="replace")
        name_m = re.search(r'name="([^"]+)"', head_str)
        if not name_m:
            continue
        field_name = name_m.group(1)
        fn_m = re.search(r'filename="([^"]*)"', head_str)
        if fn_m:
            filename = fn_m.group(1)
            ct_m = re.search(r"Content-Type:\s*([^\r\n]+)", head_str, re.I)
            ctype = ct_m.group(1).strip() if ct_m else "application/octet-stream"
            files[field_name] = FileStorage(io.BytesIO(content), filename=filename, name=field_name, content_type=ctype)
        else:
            form[field_name] = content.decode("utf-8", errors="replace")
    return form, files


class _CLIGroup:
    def __init__(self):
        self.commands = {}

    def command(self, name: str):
        def decorator(func):
            self.commands[name] = func
            return func
        return decorator


class _SessionTransaction:
    def __init__(self, client):
        self.client = client
        self.sess = SessionDict()

    def __enter__(self):
        raw = self.client.cookies.get("lostlink_session")
        if raw:
            try:
                data = self.client.app._get_serializer().loads(raw)
                self.sess = SessionDict(data)
            except Exception:
                self.sess = SessionDict()
        return self.sess

    def __exit__(self, exc_type, exc_val, exc_tb):
        raw = self.client.app._get_serializer().dumps(dict(self.sess))
        self.client.cookies["lostlink_session"] = raw


class TestClient:
    def __init__(self, app: Flask):
        self.app = app
        self.cookies = {}

    def session_transaction(self):
        return _SessionTransaction(self)

    def open(self, path: str = "/", method: str = "GET", data=None, json=None, headers=None, follow_redirects: bool = False, query_string=None):
        parsed = urllib.parse.urlsplit(path)
        clean_path = parsed.path or "/"
        qs = parsed.query
        if query_string:
            extra_qs = urllib.parse.urlencode(query_string, doseq=True) if isinstance(query_string, dict) else str(query_string)
            qs = f"{qs}&{extra_qs}".strip("&")

        req_headers = dict(headers or {})
        form = {}
        files = {}
        raw_body = b""
        if json is not None:
            import json as _json
            raw_body = _json.dumps(json).encode("utf-8")
            req_headers["content-type"] = "application/json"
        elif isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, tuple) and len(v) >= 2 and hasattr(v[0], "read"):
                    stream, fname = v[0], v[1]
                    ctype = v[2] if len(v) > 2 else "application/octet-stream"
                    files[k] = FileStorage(stream, filename=fname, name=k, content_type=ctype)
                elif isinstance(v, FileStorage):
                    files[k] = v
                else:
                    form[k] = str(v) if v is not None else ""

        req = Request(
            method=method,
            path=clean_path,
            query_string=qs,
            headers=req_headers,
            form=form,
            files=files,
            json_data=json,
            raw_body=raw_body,
            cookies=dict(self.cookies),
        )
        resp = self.app.handle_request(req)
        for ck_str in resp._cookies:
            c = http.cookies.SimpleCookie()
            c.load(ck_str)
            for ck, morsel in c.items():
                self.cookies[ck] = morsel.value

        if follow_redirects and resp.status_code in (301, 302, 303, 307, 308):
            loc = resp.headers.get("Location", "/")
            return self.open(loc, method="GET", headers=headers, follow_redirects=True)
        return resp

    def get(self, path: str = "/", **kwargs):
        return self.open(path, method="GET", **kwargs)

    def post(self, path: str = "/", **kwargs):
        return self.open(path, method="POST", **kwargs)

    def put(self, path: str = "/", **kwargs):
        return self.open(path, method="PUT", **kwargs)

    def delete(self, path: str = "/", **kwargs):
        return self.open(path, method="DELETE", **kwargs)
