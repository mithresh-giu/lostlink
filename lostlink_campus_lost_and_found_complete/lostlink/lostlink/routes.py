"""
Main Application Routes & REST API Blueprints for LostLink:
- 6.3.1 Home Page Module (`/`) - Figure 7.1
- 6.3.2 Lost Item Reporting Module (`/report-lost`) - Figure 7.2
- 6.3.3 Found Item Reporting Module (`/report-found`) - Figure 7.3
- 6.3.4 Search and View Module (`/items`, `/search`, `/items/<id>`) - Figures 7.4, 7.5, 7.6
- 7.8 Administrator Page (`/admin`, claim moderation, status updates, report deletion) - Figure 7.7
- JSON REST API (`/api/items`, `/api/stats`, `/api/matches/<id>`, `/api/health`)
"""
from lostlink.compat import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from lostlink.db import get_db
from lostlink.matching import find_potential_matches, trigger_match_notifications
from lostlink.security import (
    EMAIL_REGEX,
    admin_required,
    log_audit,
    save_uploaded_image,
    validate_csrf,
    validate_item_form,
)

main_bp = Blueprint("main", __name__)


def _get_summary_stats(db) -> dict:
    """
    Computes exact summary statistics for Home Page and Administrator Dashboard (Figure 7.7):
    Total Items, Lost Items, Found Items, Pending Reports, Resolved Items, Active Claims.
    """
    row = db.execute(
        """
        SELECT
            COUNT(*) AS total_items,
             COALESCE(SUM(CASE WHEN item_type = 'Lost' THEN 1 ELSE 0 END), 0) AS lost_items,
            COALESCE(SUM(CASE WHEN item_type = 'Found' THEN 1 ELSE 0 END), 0) AS found_items,
            COALESCE(SUM(CASE WHEN status = 'Pending' THEN 1 ELSE 0 END), 0) AS pending_reports,
            COALESCE(SUM(CASE WHEN status = 'Available' THEN 1 ELSE 0 END), 0) AS available_items,
            COALESCE(SUM(CASE WHEN status IN ('Resolved', 'Claimed') THEN 1 ELSE 0 END), 0) AS resolved_items
        FROM items
        """
    ).fetchone()
    pending_claims = db.execute(
        "SELECT COUNT(*) AS cnt FROM claims WHERE status = 'Pending'"
    ).fetchone()["cnt"]
    return {
        "total_items": row["total_items"],
        "lost_items": row["lost_items"],
        "found_items": row["found_items"],
        "pending_reports": row["pending_reports"],
        "available_items": row["available_items"],
        "resolved_items": row["resolved_items"],
        "pending_claims": pending_claims,
    }


@main_bp.route("/", methods=["GET"])
def index():
    """
    6.3.1 Home Page Module & Figure 7.1: LostLink Home Page.
    Displays hero banner with 4 primary action buttons (Report Lost Item, Report Found Item,
    View Items, Search), live campus statistics, and recent item highlights.
    """
    db = get_db()
    stats = _get_summary_stats(db)
    recent_items = db.execute(
        "SELECT * FROM items ORDER BY id ASC LIMIT 6"
    ).fetchall()
    return render_template(
        "index.html",
        stats=stats,
        recent_items=[dict(r) for r in recent_items],
    )


@main_bp.route("/report-lost", methods=["GET", "POST"])
def report_lost():
    """
    6.3.2 Lost Item Reporting Module & Figure 7.2: Lost Item Reporting Page.
    Fields: Item Name *, Description *, Location Last Seen *, Date Lost *, plus optional
    Category, Item Photo Upload (9.4.1), Verification Hint, and Contact Info.
    """
    categories = current_app.config["ITEM_CATEGORIES"]
    locations = current_app.config["CAMPUS_LOCATIONS"]

    if request.method == "POST":
        validate_csrf()
        is_valid, errors, cleaned = validate_item_form(request.form)

        image_file = request.files.get("image")
        saved_image, img_err = save_uploaded_image(image_file)
        if img_err:
            errors.append(img_err)
            is_valid = False

        if not is_valid:
            for err in errors:
                flash(err, "danger")
            return (
                render_template(
                    "report_lost.html",
                    categories=categories,
                    locations=locations,
                    form_data=request.form,
                ),
                400,
            )

        db = get_db()
        reporter_id = g.user["id"] if g.get("user") else None
        default_img = saved_image or _pick_default_svg(cleaned["title"], cleaned["category"])

        cursor = db.execute(
            """
            INSERT INTO items (
                title, item_type, category, description, location, date_reported,
                status, image_filename, contact_name, contact_email, contact_phone,
                verification_hint, reporter_id
            ) VALUES (?, 'Lost', ?, ?, ?, ?, 'Pending', ?, ?, ?, ?, ?, ?)
            """,
            (
                cleaned["title"],
                cleaned["category"],
                cleaned["description"],
                cleaned["location"],
                cleaned["date_reported"],
                default_img,
                cleaned["contact_name"],
                cleaned["contact_email"],
                cleaned["contact_phone"],
                cleaned["verification_hint"],
                reporter_id,
            ),
        )
        new_item_id = cursor.lastrowid
        db.commit()

        # Trigger automatic match detection and notifications (Chapter 9.4.3)
        matches_found = trigger_match_notifications(db, new_item_id)
        log_audit("REPORT_LOST_ITEM", "item", new_item_id, f"Reported lost item: {cleaned['title']} at {cleaned['location']}")

        if matches_found > 0:
            flash(
                f"Lost item '{cleaned['title']}' registered! We also found potential matches on campus—check the item details below.",
                "success",
            )
        else:
            flash(f"Lost item report for '{cleaned['title']}' has been submitted and saved.", "success")
        return redirect(url_for("main.item_details", item_id=new_item_id))

    return render_template(
        "report_lost.html",
        categories=categories,
        locations=locations,
        form_data={},
    )


@main_bp.route("/report-found", methods=["GET", "POST"])
def report_found():
    """
    6.3.3 Found Item Reporting Module & Figure 7.3: Found Item Reporting Page.
    Fields: Item Name *, Description *, Location Found *, Date Found *, plus optional
    Category, Item Photo Upload (9.4.1), Verification Hint, and Contact Info.
    """
    categories = current_app.config["ITEM_CATEGORIES"]
    locations = current_app.config["CAMPUS_LOCATIONS"]

    if request.method == "POST":
        validate_csrf()
        is_valid, errors, cleaned = validate_item_form(request.form)

        image_file = request.files.get("image")
        saved_image, img_err = save_uploaded_image(image_file)
        if img_err:
            errors.append(img_err)
            is_valid = False

        if not is_valid:
            for err in errors:
                flash(err, "danger")
            return (
                render_template(
                    "report_found.html",
                    categories=categories,
                    locations=locations,
                    form_data=request.form,
                ),
                400,
            )

        db = get_db()
        reporter_id = g.user["id"] if g.get("user") else None
        default_img = saved_image or _pick_default_svg(cleaned["title"], cleaned["category"])

        cursor = db.execute(
            """
            INSERT INTO items (
                title, item_type, category, description, location, date_reported,
                status, image_filename, contact_name, contact_email, contact_phone,
                verification_hint, reporter_id
            ) VALUES (?, 'Found', ?, ?, ?, ?, 'Available', ?, ?, ?, ?, ?, ?)
            """,
            (
                cleaned["title"],
                cleaned["category"],
                cleaned["description"],
                cleaned["location"],
                cleaned["date_reported"],
                default_img,
                cleaned["contact_name"],
                cleaned["contact_email"],
                cleaned["contact_phone"],
                cleaned["verification_hint"],
                reporter_id,
            ),
        )
        new_item_id = cursor.lastrowid
        db.commit()

        matches_found = trigger_match_notifications(db, new_item_id)
        log_audit("REPORT_FOUND_ITEM", "item", new_item_id, f"Reported found item: {cleaned['title']} at {cleaned['location']}")

        if matches_found > 0:
            flash(
                f"Found item '{cleaned['title']}' recorded! Automatic match notifications have been sent to users who lost similar items.",
                "success",
            )
        else:
            flash(f"Found item report for '{cleaned['title']}' has been recorded and saved.", "success")
        return redirect(url_for("main.item_details", item_id=new_item_id))

    return render_template(
        "report_found.html",
        categories=categories,
        locations=locations,
        form_data={},
    )


@main_bp.route("/items", methods=["GET"])
def item_listings():
    """
    7.5 Item Listing Page & Figure 7.4: Item Listing Page.
    Supports filter tabs for All, Lost Items, and Found Items, plus category and status filters.
    """
    db = get_db()
    filter_type = (request.args.get("type") or "all").strip()
    category_filter = (request.args.get("category") or "").strip()
    status_filter = (request.args.get("status") or "").strip()

    query = "SELECT * FROM items WHERE 1=1"
    params = []

    if filter_type.lower() == "lost":
        query += " AND item_type = 'Lost'"
    elif filter_type.lower() == "found":
        query += " AND item_type = 'Found'"

    if category_filter:
        query += " AND category = ?"
        params.append(category_filter)

    if status_filter:
        query += " AND status = ?"
        params.append(status_filter)

    query += " ORDER BY id ASC"
    rows = db.execute(query, params).fetchall()

    return render_template(
        "items.html",
        items=[dict(r) for r in rows],
        current_type=filter_type.lower(),
        current_category=category_filter,
        current_status=status_filter,
        categories=current_app.config["ITEM_CATEGORIES"],
    )


@main_bp.route("/search", methods=["GET"])
def search():
    """
    6.3.4 Search and View Module, 7.6 Search Results Page (Figure 7.5),
    and 9.4.4 Advanced Search (keyword, type, category, location, date range).
    """
    db = get_db()
    q = (request.args.get("q") or "").strip()
    item_type = (request.args.get("type") or "").strip()
    category = (request.args.get("category") or "").strip()
    location = (request.args.get("location") or "").strip()
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    status = (request.args.get("status") or "").strip()

    has_criteria = any([q, item_type, category, location, date_from, date_to, status])

    query = "SELECT * FROM items WHERE 1=1"
    params = []

    if q:
        like_q = f"%{q}%"
        query += " AND (LOWER(title) LIKE LOWER(?) OR LOWER(description) LIKE LOWER(?) OR LOWER(location) LIKE LOWER(?) OR LOWER(category) LIKE LOWER(?))"
        params.extend([like_q, like_q, like_q, like_q])

    if item_type in ("Lost", "Found"):
        query += " AND item_type = ?"
        params.append(item_type)

    if category:
        query += " AND category = ?"
        params.append(category)

    if location:
        query += " AND LOWER(location) LIKE LOWER(?)"
        params.append(f"%{location}%")

    if date_from:
        query += " AND date_reported >= ?"
        params.append(date_from)

    if date_to:
        query += " AND date_reported <= ?"
        params.append(date_to)

    if status:
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY id ASC"
    rows = db.execute(query, params).fetchall()

    return render_template(
        "search.html",
        results=[dict(r) for r in rows],
        q=q,
        item_type=item_type,
        category=category,
        location=location,
        date_from=date_from,
        date_to=date_to,
        status=status,
        has_criteria=has_criteria,
        categories=current_app.config["ITEM_CATEGORIES"],
        locations=current_app.config["CAMPUS_LOCATIONS"],
    )


@main_bp.route("/items/<int:item_id>", methods=["GET"])
def item_details(item_id: int):
    """
    7.7 Item Details Page & Figure 7.6: Item Details Page.
    Displays full item details, image preview, status badge, Contact Owner / Submit Claim
    modal & form, and Smart Potential Matches (Chapter 6.6 / 9.4.4).
    """
    db = get_db()
    item = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        abort(404, f"Item #{item_id} was not found in the campus database.")

    item_dict = dict(item)
    potential_matches = find_potential_matches(db, item_dict, min_score=40, limit=4)
    claims = db.execute(
        "SELECT * FROM claims WHERE item_id = ? ORDER BY id DESC", (item_id,)
    ).fetchall()

    return render_template(
        "item_details.html",
        item=item_dict,
        potential_matches=potential_matches,
        claims=[dict(c) for c in claims],
    )


@main_bp.route("/items/<int:item_id>/claim", methods=["POST"])
def submit_claim(item_id: int):
    """
    Handles 'Contact Owner' / Ownership Verification & Claim submission on Figure 7.6.
    """
    validate_csrf()
    db = get_db()
    item = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        abort(404, "Item not found.")

    claimant_name = (request.form.get("claimant_name") or "").strip()
    claimant_email = (request.form.get("claimant_email") or "").strip()
    claimant_phone = (request.form.get("claimant_phone") or "").strip()
    claim_type = (request.form.get("claim_type") or "Ownership Claim").strip()
    proof_description = (request.form.get("proof_description") or "").strip()

    if g.get("user"):
        claimant_name = claimant_name or g.user["full_name"]
        claimant_email = claimant_email or g.user["email"]
        claimant_phone = claimant_phone or g.user.get("phone", "")

    errors = []
    if not claimant_name or len(claimant_name) < 2:
        errors.append("Your Name is required to contact the owner or claim this item.")
    if not claimant_email or not EMAIL_REGEX.match(claimant_email):
        errors.append("A valid Email Address is required.")
    if not claimant_phone or len(claimant_phone) < 7:
        errors.append("A valid Contact Phone Number is required.")
    if not proof_description or len(proof_description) < 10:
        errors.append("Please provide specific verification details or message (at least 10 characters).")

    if errors:
        for err in errors:
            flash(err, "danger")
        return redirect(url_for("main.item_details", item_id=item_id))

    if claim_type not in ("Ownership Claim", "Found Match Report", "Direct Inquiry"):
        claim_type = "Ownership Claim"

    claimant_id = g.user["id"] if g.get("user") else None
    cursor = db.execute(
        """
        INSERT INTO claims (
            item_id, claimant_id, claimant_name, claimant_email, claimant_phone,
            claim_type, proof_description, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'Pending')
        """,
        (item_id, claimant_id, claimant_name, claimant_email, claimant_phone, claim_type, proof_description),
    )
    claim_id = cursor.lastrowid

    # Notify item reporter if registered
    if item["reporter_id"]:
        db.execute(
            """
            INSERT INTO notifications (user_id, item_id, title, message, notification_type)
            VALUES (?, ?, ?, ?, 'claim')
            """,
            (
                item["reporter_id"],
                item_id,
                f"New {claim_type} on '{item['title']}'",
                f"{claimant_name} ({claimant_email}) submitted a {claim_type.lower()} for '{item['title']}'.",
            ),
        )

    db.commit()
    log_audit("SUBMIT_CLAIM", "claim", claim_id, f"Claim submitted for Item #{item_id} by {claimant_email}")
    flash(
        f"Your {claim_type.lower()} for '{item['title']}' has been submitted! The reporter and campus administrator have been notified.",
        "success",
    )
    return redirect(url_for("main.item_details", item_id=item_id))


@main_bp.route("/admin", methods=["GET"])
@admin_required
def admin_dashboard():
    """
    7.8 Administrator Page & Figure 7.7: Administrator Dashboard.
    Displays summary cards (Total Items, Lost Items, Found Items, Pending Reports),
    Recent Reports table with moderation controls, Ownership Claims review queue,
    and Security Audit Logs.
    """
    db = get_db()
    stats = _get_summary_stats(db)
    items = db.execute("SELECT * FROM items ORDER BY id ASC").fetchall()
    claims = db.execute(
        """
        SELECT c.*, i.title AS item_title, i.item_type, i.location AS item_location, i.status AS item_status
        FROM claims c
        JOIN items i ON c.item_id = i.id
        ORDER BY CASE WHEN c.status = 'Pending' THEN 0 ELSE 1 END, c.id DESC
        """
    ).fetchall()
    audit_logs = db.execute(
        "SELECT * FROM audit_logs ORDER BY id DESC LIMIT 15"
    ).fetchall()

    return render_template(
        "admin.html",
        stats=stats,
        items=[dict(r) for r in items],
        claims=[dict(c) for c in claims],
        audit_logs=[dict(a) for a in audit_logs],
    )


@main_bp.route("/admin/items/<int:item_id>/status", methods=["POST"])
@admin_required
def admin_update_item_status(item_id: int):
    """
    Allows Administrator to update an item's status (Pending, Available, Claimed, Resolved, Rejected)
    as specified in Chapter 9.4.5 & 10.3.6.
    """
    validate_csrf()
    new_status = (request.form.get("status") or "").strip()
    valid_statuses = ("Pending", "Available", "Claimed", "Resolved", "Rejected")
    if new_status not in valid_statuses:
        flash("Invalid status value selected.", "danger")
        return redirect(url_for("main.admin_dashboard"))

    db = get_db()
    item = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        abort(404, "Item not found.")

    db.execute(
        "UPDATE items SET status = ?, updated_at = datetime('now') WHERE id = ?",
        (new_status, item_id),
    )

    if item["reporter_id"]:
        db.execute(
            """
            INSERT INTO notifications (user_id, item_id, title, message, notification_type)
            VALUES (?, ?, ?, ?, 'status_update')
            """,
            (
                item["reporter_id"],
                item_id,
                f"Status Updated for '{item['title']}'",
                f"An administrator updated the status of your report '{item['title']}' from '{item['status']}' to '{new_status}'.",
            ),
        )

    db.commit()
    log_audit("ADMIN_UPDATE_STATUS", "item", item_id, f"Updated Item #{item_id} status to {new_status}")
    flash(f"Item #{item_id} ('{item['title']}') status updated to '{new_status}'.", "success")
    return redirect(request.referrer or url_for("main.admin_dashboard"))


@main_bp.route("/admin/items/<int:item_id>/delete", methods=["POST"])
@admin_required
def admin_delete_item(item_id: int):
    """
    Allows Administrator to remove inappropriate or duplicate item entries (Chapter 9.4.5).
    """
    validate_csrf()
    db = get_db()
    item = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        abort(404, "Item not found.")

    title = item["title"]
    db.execute("DELETE FROM items WHERE id = ?", (item_id,))
    db.commit()
    log_audit("ADMIN_DELETE_ITEM", "item", item_id, f"Deleted Item #{item_id} ('{title}')")
    flash(f"Report #{item_id} ('{title}') has been removed from the system.", "info")
    return redirect(url_for("main.admin_dashboard"))


@main_bp.route("/admin/claims/<int:claim_id>/review", methods=["POST"])
@admin_required
def admin_review_claim(claim_id: int):
    """
    Allows Administrator to approve or reject an ownership claim and automatically mark
    the associated item as Claimed/Resolved (Chapter 10.3.6).
    """
    validate_csrf()
    decision = (request.form.get("decision") or "").strip()
    admin_notes = (request.form.get("admin_notes") or "").strip()
    if decision not in ("Approved", "Rejected"):
        flash("Invalid claim review decision.", "danger")
        return redirect(url_for("main.admin_dashboard"))

    db = get_db()
    claim = db.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
    if claim is None:
        abort(404, "Claim record not found.")

    db.execute(
        """
        UPDATE claims
        SET status = ?, admin_notes = ?, reviewed_by = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (decision, admin_notes, g.user["id"], claim_id),
    )

    if decision == "Approved":
        db.execute(
            "UPDATE items SET status = 'Resolved', updated_at = datetime('now') WHERE id = ?",
            (claim["item_id"],),
        )

    if claim["claimant_id"]:
        db.execute(
            """
            INSERT INTO notifications (user_id, item_id, title, message, notification_type)
            VALUES (?, ?, ?, ?, 'claim')
            """,
            (
                claim["claimant_id"],
                claim["item_id"],
                f"Your Claim #{claim_id} was {decision}",
                f"Administrator reviewed your claim: {decision}. {admin_notes}",
            ),
        )

    db.commit()
    log_audit("ADMIN_REVIEW_CLAIM", "claim", claim_id, f"Claim #{claim_id} marked {decision}")
    flash(f"Claim #{claim_id} has been {decision.lower()}.", "success")
    return redirect(url_for("main.admin_dashboard"))


# ==============================================================================
# JSON REST API Endpoints (for programmatic integration & automated verification)
# ==============================================================================

@main_bp.route("/api/health", methods=["GET"])
def api_health():
    db = get_db()
    cnt = db.execute("SELECT COUNT(*) AS c FROM items").fetchone()["c"]
    return jsonify({
        "status": "ok",
        "service": "LostLink - Campus Lost and Found Management System",
        "items_count": cnt,
    })


@main_bp.route("/api/stats", methods=["GET"])
def api_stats():
    db = get_db()
    return jsonify(_get_summary_stats(db))


@main_bp.route("/api/items", methods=["GET"])
def api_items():
    db = get_db()
    item_type = request.args.get("type")
    q = (request.args.get("q") or "").strip()
    sql = "SELECT * FROM items WHERE 1=1"
    params = []
    if item_type in ("Lost", "Found"):
        sql += " AND item_type = ?"
        params.append(item_type)
    if q:
        sql += " AND (LOWER(title) LIKE LOWER(?) OR LOWER(description) LIKE LOWER(?) OR LOWER(location) LIKE LOWER(?))"
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    sql += " ORDER BY id ASC"
    rows = db.execute(sql, params).fetchall()
    return jsonify({"count": len(rows), "items": [dict(r) for r in rows]})


@main_bp.route("/api/items/<int:item_id>/matches", methods=["GET"])
def api_item_matches(item_id: int):
    db = get_db()
    item = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if not item:
        return jsonify({"error": "Item not found"}), 404
    matches = find_potential_matches(db, dict(item), min_score=35, limit=5)
    return jsonify({"item_id": item_id, "matches": matches})


def _pick_default_svg(title: str, category: str) -> str:
    t = f"{title} {category}".lower()
    if "wallet" in t or "purse" in t or "cash" in t:
        return "wallet.svg"
    if "backpack" in t or "bag" in t:
        return "backpack.svg"
    if "id" in t or "card" in t or "badge" in t:
        return "idcard.svg"
    if "bottle" in t or "water" in t or "flask" in t:
        return "bottle.svg"
    if "calc" in t:
        return "calculator.svg"
    if "earbud" in t or "phone" in t or "laptop" in t or "electronic" in t:
        return "earbuds.svg"
    if "key" in t:
        return "keys.svg"
    if "book" in t or "note" in t:
        return "book.svg"
    return "default_item.svg"
