#!/usr/bin/env python3
"""
LostLink – Campus Lost and Found Management System
Main Server Entrypoint (`python3 run.py`).
"""
import os
from lostlink import create_app

app = create_app()

if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV", "development") == "development"
    app.run(host=host, port=port, debug=debug)
