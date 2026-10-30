"""
User Authentication, Registration, Profile, and Notifications Blueprint
(Chapter 9.4.2 User Authentication & 9.4.3 Automatic Notifications).
"""
import re
from lostlink.compat import (
    Blueprint,
    check_password_hash,
    flash,
    g,
    generate_password_hash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from lostlink.db import get_db
from lostlink.security import EMAIL_REGEX, log_audit, login_required, validate_csrf

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if g.get("user"):
        return redirect(url_for("main.index"))

    if request.method == "POST":
        validate_csrf()
        identifier = (request.form.get("identifier") or request.form.get("email") or "").strip()
        password = request.form.get("password") or ""

        if not identifier or not password:
            flash("Please enter both your Email / Register Number and Password.", "danger")
            return render_template("login.html", identifier=identifier), 400

        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE LOWER(email) = LOWER(?) OR UPPER(register_no) = UPPER(?)",
            (identifier, identifier),
        ).fetchone()

        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Invalid campus credentials. Please check your Email/Register No. and Password.", "danger")
            return render_template("login.html", identifier=identifier), 401

        if not user["is_active"]:
            flash("Your account has been deactivated. Please contact the IT Department Administrator.", "danger")
            return render_template("login.html", identifier=identifier), 403

        session.clear()
        session["user_id"] = user["id"]
        session["user_role"] = user["role"]
        g.user = dict(user)
        log_audit("USER_LOGIN", "user", user["id"], f"User {user['register_no']} logged in")
        flash(f"Welcome back, {user['full_name']}!", "success")

        next_url = request.args.get("next") or request.form.get("next")
        if next_url and next_url.startswith("/") and not next_url.startswith("//"):
            return redirect(next_url)
        if user["role"] in ("admin", "staff"):
            return redirect(url_for("main.admin_dashboard"))
        return redirect(url_for("main.index"))

    return render_template("login.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if g.get("user"):
        return redirect(url_for("main.index"))

    if request.method == "POST":
        validate_csrf()
        full_name = (request.form.get("full_name") or "").strip()
        register_no = (request.form.get("register_no") or "").strip().upper()
        email = (request.form.get("email") or "").strip().lower()
        phone = (request.form.get("phone") or "").strip()
        department = (request.form.get("department") or "Information Technology").strip()
        password = request.form.get("password") or ""
        confirm_password = request.form.get("confirm_password") or ""

        errors = []
        if not full_name or len(full_name) < 3:
            errors.append("Full Name must be at least 3 characters.")
        if not register_no or not re.match(r"^[A-Z0-9]{4,16}$", register_no):
            errors.append("Register / Staff ID must be 4-16 alphanumeric characters (e.g., 25IT111).")
        if not email or not EMAIL_REGEX.match(email):
            errors.append("A valid institutional or personal email address is required.")
        if not phone or len(phone) < 7:
            errors.append("A valid contact phone number is required.")
        if len(password) < 6:
            errors.append("Password must be at least 6 characters long.")
        if password != confirm_password:
            errors.append("Passwords do not match.")

        db = get_db()
        if not errors:
            existing = db.execute(
                "SELECT id FROM users WHERE LOWER(email) = LOWER(?) OR UPPER(register_no) = UPPER(?)",
                (email, register_no),
            ).fetchone()
            if existing:
                errors.append("An account with that Email or Register Number already exists.")

        if errors:
            for err in errors:
                flash(err, "danger")
            return (
                render_template(
                    "register.html",
                    form_data={
                        "full_name": full_name,
                        "register_no": register_no,
                        "email": email,
                        "phone": phone,
                        "department": department,
                    },
                ),
                400,
            )

        cursor = db.execute(
            """
            INSERT INTO users (full_name, register_no, email, phone, department, role, password_hash)
            VALUES (?, ?, ?, ?, ?, 'student', ?)
            """,
            (full_name, register_no, email, phone, department, generate_password_hash(password)),
        )
        new_user_id = cursor.lastrowid
        db.execute(
            """
            INSERT INTO notifications (user_id, title, message, notification_type)
            VALUES (?, 'Welcome to LostLink Campus Portal!', 'Your campus account is active. You can now report lost/found items, receive automatic match alerts, and track ownership claims.', 'info')
            """,
            (new_user_id,),
        )
        db.commit()

        session.clear()
        session["user_id"] = new_user_id
        session["user_role"] = "student"
        log_audit("USER_REGISTER", "user", new_user_id, f"Registered student {register_no}")
        flash("Registration successful! Welcome to LostLink.", "success")
        return redirect(url_for("main.index"))

    return render_template("register.html", form_data={})


@auth_bp.route("/logout", methods=["GET", "POST"])
def logout():
    if g.get("user"):
        log_audit("USER_LOGOUT", "user", g.user["id"], f"User {g.user['register_no']} logged out")
    session.clear()
    flash("You have been logged out safely.", "info")
    return redirect(url_for("main.index"))


@auth_bp.route("/notifications", methods=["GET"])
@login_required
def notifications():
    db = get_db()
    rows = db.execute(
        """
        SELECT n.*, i.title AS item_title, i.item_type, i.status AS item_status
        FROM notifications n
        LEFT JOIN items i ON n.item_id = i.id
        WHERE n.user_id = ?
        ORDER BY n.id DESC
        """,
        (g.user["id"],),
    ).fetchall()

    my_claims = db.execute(
        """
        SELECT c.*, i.title AS item_title, i.item_type, i.location AS item_location
        FROM claims c
        JOIN items i ON c.item_id = i.id
        WHERE c.claimant_id = ? OR LOWER(c.claimant_email) = LOWER(?)
        ORDER BY c.id DESC
        """,
        (g.user["id"], g.user["email"]),
    ).fetchall()

    my_items = db.execute(
        """
        SELECT * FROM items
        WHERE reporter_id = ? OR LOWER(contact_email) = LOWER(?)
        ORDER BY id DESC
        """,
        (g.user["id"], g.user["email"]),
    ).fetchall()

    return render_template(
        "notifications.html",
        notifications=[dict(r) for r in rows],
        my_claims=[dict(c) for c in my_claims],
        my_items=[dict(it) for it in my_items],
    )


@auth_bp.route("/notifications/mark-read", methods=["POST"])
@login_required
def mark_notifications_read():
    validate_csrf()
    db = get_db()
    notif_id = request.form.get("notification_id")
    if notif_id:
        db.execute(
            "UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?",
            (int(notif_id), g.user["id"]),
        )
    else:
        db.execute(
            "UPDATE notifications SET is_read = 1 WHERE user_id = ?",
            (g.user["id"],),
        )
    db.commit()
    flash("Notifications marked as read.", "success")
    return redirect(url_for("auth.notifications"))
