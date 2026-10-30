"""
LostLink – Campus Lost and Found Management System
Application Factory (`create_app`).
"""
import os
from lostlink.compat import Flask, render_template
from lostlink.config import Config
from lostlink.db import get_db, init_app as init_db_app, init_db, seed_db
from lostlink.security import generate_csrf_token, load_logged_in_user


def create_app(test_config: dict = None) -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    # Load default configuration
    for attr in dir(Config):
        if attr.isupper():
            app.config[attr] = getattr(Config, attr)

    app.config["CSRF_ENABLED"] = True

    if test_config:
        app.config.update(test_config)

    os.makedirs(os.path.dirname(os.path.abspath(app.config["DATABASE_PATH"])), exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    # Register DB lifecycle hooks
    init_db_app(app)

    # Ensure database schema & seed records exist on startup
    with app.app_context():
        init_db()
        if app.config.get("SEED_ON_STARTUP", True):
            seed_db()

    # Register before_request user session loader
    app.before_request(load_logged_in_user)

    # Inject CSRF token and campus metadata into all Jinja2 templates
    @app.context_processor
    def inject_template_globals():
        return {
            "csrf_token": generate_csrf_token,
            "campus_name": app.config.get("CAMPUS_NAME"),
            "campus_location": app.config.get("CAMPUS_LOCATION"),
            "university_name": app.config.get("UNIVERSITY_NAME"),
        }

    # Register Blueprints
    from lostlink.auth import auth_bp
    from lostlink.routes import main_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    # Custom Error Handlers (Chapter 6.5 Data Validation and Error Handling)
    @app.errorhandler(400)
    def bad_request_error(e):
        return render_template("error.html", code=400, title="Bad Request", message=getattr(e, "description", str(e))), 400

    @app.errorhandler(403)
    def forbidden_error(e):
        return render_template("error.html", code=403, title="Access Restricted", message=getattr(e, "description", "You do not have permission to access this resource.")), 403

    @app.errorhandler(404)
    def not_found_error(e):
        return render_template("error.html", code=404, title="Record or Page Not Found", message=getattr(e, "description", "The requested item or page could not be found.")), 404

    @app.errorhandler(500)
    def internal_error(e):
        return render_template("error.html", code=500, title="System Error", message="An unexpected server error occurred. Please try again."), 500

    return app
