"""
Security, Authentication, Role-Based Access Control (RBAC), Input Validation,
and Audit Logging Module (Chapter 4.5 Security, 5.5 Input Design, 6.5 Data Validation).
"""
import functools
import os
import re
import secrets
from datetime import datetime
from lostlink.compat import (
    abort,
    current_app,
    flash,
    g,
    redirect,
    request,
    secure_filename,
    session,
    url_for,
)
from lostlink.db import get_db

EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def generate_csrf_token() -> str:
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(24)
    return session["_csrf_token"]


def validate_csrf():
    """
    Validates CSRF token on state-changing requests (POST, PUT, DELETE)
    unless CSRF is explicitly disabled in test config (`WTF_CSRF_ENABLED=False`).
    """
    if not current_app.config.get("CSRF_ENABLED", True):
        return
    if request.method in ("POST", "PUT", "DELETE"):
        # API JSON requests can pass X-CSRF-Token header or form csrf_token
        if request.path.startswith("/api/"):
            return
        token = request.form.get("csrf_token") or request.headers.get("x-csrf-token")
        expected = session.get("_csrf_token")
        if not expected or not token or not secrets.compare_digest(str(token), str(expected)):
            abort(400, "CSRF token missing or invalid. Please refresh the page and try again.")


def load_logged_in_user():
    user_id = session.get("user_id")
    if user_id is None:
        g.user = None
        g.unread_notifications_count = 0
    else:
        db = get_db()
        user = db.execute(
            "SELECT id, full_name, register_no, email, phone, department, role, is_active, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if user and user["is_active"]:
            g.user = dict(user)
            cnt = db.execute(
                "SELECT COUNT(*) AS c FROM notifications WHERE user_id = ? AND is_read = 0",
                (user_id,),
            ).fetchone()["c"]
            g.unread_notifications_count = cnt
        else:
            session.clear()
            g.user = None
            g.unread_notifications_count = 0


def login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.get("user") is None:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        return view(**kwargs)
    return wrapped_view


def admin_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        user = g.get("user")
        if user is None:
            flash("Administrator login required.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        if user.get("role") not in ("admin", "staff"):
            abort(403, "Access Denied: Administrator or Staff privileges required.")
        return view(**kwargs)
    return wrapped_view


def validate_item_form(form_data: dict) -> tuple[bool, list[str], dict]:
    """
    Validates Lost/Found item submission form data (Chapter 5.5 Input Design & 6.5 Data Validation).
    Checks required fields: item_name (title), description, location, date_reported.
    Returns (is_valid, error_messages, cleaned_data).
    """
    errors = []
    title = (form_data.get("item_name") or form_data.get("title") or "").strip()
    description = (form_data.get("description") or "").strip()
    location = (form_data.get("location") or "").strip()
    date_reported = (form_data.get("date_reported") or form_data.get("date") or "").strip()
    category = (form_data.get("category") or "Other").strip()
    contact_name = (form_data.get("contact_name") or "").strip()
    contact_email = (form_data.get("contact_email") or "").strip()
    contact_phone = (form_data.get("contact_phone") or "").strip()
    verification_hint = (form_data.get("verification_hint") or "").strip()

    # Fallback to logged-in user details for contact info if not explicitly entered
    user = g.get("user")
    if not contact_name and user:
        contact_name = user["full_name"]
    if not contact_email and user:
        contact_email = user["email"]
    if not contact_phone and user:
        contact_phone = user.get("phone", "")

    if not contact_name:
        contact_name = "Campus User"
    if not contact_email:
        contact_email = "helpdesk@kpriet.ac.in"

    if not title:
        errors.append("Item Name is required.")
    elif len(title) < 2 or len(title) > 120:
        errors.append("Item Name must be between 2 and 120 characters.")

    if not description:
        errors.append("Description is required.")
    elif len(description) < 5 or len(description) > 2000:
        errors.append("Description must be between 5 and 2000 characters.")

    if not location:
        errors.append("Location is required.")
    elif len(location) < 2 or len(location) > 120:
        errors.append("Location must be between 2 and 120 characters.")

    if not date_reported:
        errors.append("Date is required.")
    else:
        if not DATE_REGEX.match(date_reported):
            errors.append("Date must be in valid YYYY-MM-DD format.")
        else:
            try:
                datetime.strptime(date_reported, "%Y-%m-%d")
            except ValueError:
                errors.append("Invalid calendar date provided.")

    if contact_email and not EMAIL_REGEX.match(contact_email):
        errors.append("Please enter a valid contact email address.")

    cleaned = {
        "title": title,
        "description": description,
        "location": location,
        "date_reported": date_reported,
        "category": category or "Other",
        "contact_name": contact_name,
        "contact_email": contact_email,
        "contact_phone": contact_phone,
        "verification_hint": verification_hint,
    }
    return (len(errors) == 0, errors, cleaned)


def allowed_file(filename: str) -> bool:
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in current_app.config.get("ALLOWED_EXTENSIONS", {"png", "jpg", "jpeg", "gif", "webp", "svg"})


def save_uploaded_image(file_storage) -> tuple[str | None, str | None]:
    """
    Validates and saves an uploaded item image (Chapter 9.4.1 Image Upload).
    Returns (saved_filename, error_message).
    """
    if not file_storage or not getattr(file_storage, "filename", ""):
        return None, None

    orig_name = file_storage.filename
    if not allowed_file(orig_name):
        return None, "Unsupported image file type. Allowed formats: PNG, JPG, JPEG, GIF, WEBP, SVG."

    safe_name = secure_filename(orig_name)
    ext = safe_name.rsplit(".", 1)[1].lower() if "." in safe_name else "png"
    unique_name = f"item_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}.{ext}"
    upload_dir = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(upload_dir, exist_ok=True)
    dest_path = os.path.join(upload_dir, unique_name)
    file_storage.save(dest_path)
    return unique_name, None


def log_audit(action: str, target_type: str, target_id: int = 0, details: str = ""):
    db = get_db()
    user = g.get("user")
    actor_id = user["id"] if user else None
    actor_name = user["full_name"] if user else "Anonymous Campus User"
    ip_addr = getattr(request, "remote_addr", "127.0.0.1")
    db.execute(
        """
        INSERT INTO audit_logs (actor_id, actor_name, action, target_type, target_id, details, ip_address)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (actor_id, actor_name, action, target_type, target_id, details, ip_addr),
    )
    db.commit()
