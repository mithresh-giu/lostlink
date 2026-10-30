"""
Framework import bridge: prefers native Flask & Werkzeug when installed in the
virtualenv; falls back transparently to `flask_compat` in offline environments.
"""
try:
    from flask import (
        Flask,
        Blueprint,
        request,
        session,
        g,
        current_app,
        flash,
        redirect,
        url_for,
        render_template,
        jsonify,
        abort,
        send_from_directory,
        get_flashed_messages,
    )
    from werkzeug.security import generate_password_hash, check_password_hash
    from werkzeug.utils import secure_filename
except ImportError:
    from flask_compat import (
        Flask,
        Blueprint,
        request,
        session,
        g,
        current_app,
        flash,
        redirect,
        url_for,
        render_template,
        jsonify,
        abort,
        send_from_directory,
        get_flashed_messages,
        generate_password_hash,
        check_password_hash,
        secure_filename,
    )

__all__ = [
    "Flask",
    "Blueprint",
    "request",
    "session",
    "g",
    "current_app",
    "flash",
    "redirect",
    "url_for",
    "render_template",
    "jsonify",
    "abort",
    "send_from_directory",
    "get_flashed_messages",
    "generate_password_hash",
    "check_password_hash",
    "secure_filename",
]
