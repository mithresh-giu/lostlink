"""
Database Management Module (Chapter 6.3.5 & 6.6 Database Integration).
Provides parameterized SQLite connection pooling per request, schema initialization,
and realistic campus seed data matching Chapter 7 screenshots (Figures 7.4, 7.5, 7.6, 7.7)
and the project team members from KPR Institute of Engineering and Technology.
"""
import os
import sqlite3
from lostlink.compat import current_app, g, generate_password_hash


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        db_path = current_app.config["DATABASE_PATH"]
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode = MEMORY;")
            conn.execute("PRAGMA synchronous = OFF;")
        except sqlite3.OperationalError:
            pass
        conn.execute("PRAGMA foreign_keys = ON;")
        g.db = conn
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        db.executescript(f.read())
    db.commit()


def seed_db():
    """
    Populates the SQLite database with realistic demo accounts (Students, Staff, Admin)
    and the exact 10 campus Lost & Found item records shown in Chapter 7:
    - Figure 7.4 (Item Listings: #1 Wallet, #2 Backpack, #3 ID Card, #4 Water Bottle)
    - Figure 7.5 & 7.6 (Wallet: Black wallet with 2 cards and cash, Library, 2025-08-20)
    - Figure 7.7 (Administrator Dashboard: Total Items = 10, Lost Items = 5, Found Items = 5, Pending Reports = 3)
    """
    db = get_db()
    existing_count = db.execute("SELECT COUNT(*) AS cnt FROM users").fetchone()["cnt"]
    if existing_count > 0:
        return

    users = [
        (
            "Dr. I. C. Amitha (Admin)",
            "ADMIN001",
            "admin@kpriet.ac.in",
            "+91 98422 10001",
            "Information Technology",
            "admin",
            generate_password_hash("Admin@123"),
        ),
        (
            "Ms. J. Rathanaa Ranjeni",
            "STAFF101",
            "rathanaa.it@kpriet.ac.in",
            "+91 98422 10002",
            "Information Technology",
            "staff",
            generate_password_hash("Staff@123"),
        ),
        (
            "Nishanth U",
            "25IT111",
            "nishanth.25it111@kpriet.ac.in",
            "+91 94870 25111",
            "Information Technology",
            "student",
            generate_password_hash("Student@123"),
        ),
        (
            "Nishanth Babu Karthika",
            "25IT110",
            "nishanthbabu.25it110@kpriet.ac.in",
            "+91 94870 25110",
            "Information Technology",
            "student",
            generate_password_hash("Student@123"),
        ),
        (
            "Mithresh S N",
            "25IT091",
            "mithresh.25it091@kpriet.ac.in",
            "+91 94870 25091",
            "Information Technology",
            "student",
            generate_password_hash("Student@123"),
        ),
        (
            "Jeevagan M B",
            "25IT069",
            "jeevagan.25it069@kpriet.ac.in",
            "+91 94870 25069",
            "Information Technology",
            "student",
            generate_password_hash("Student@123"),
        ),
    ]

    db.executemany(
        """
        INSERT INTO users (full_name, register_no, email, phone, department, role, password_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        users,
    )

    # Exact 10 items matching Figure 7.7 stats:
    # Total = 10 | Lost = 5 | Found = 5 | Pending = 3 (items #1, #3, #5 have status 'Pending')
    # First 4 items match Figure 7.4 & 7.7 table rows verbatim!
    items = [
        (
            "Wallet",
            "Lost",
            "Wallets & Purses",
            "Black wallet with 2 cards and cash. Lost near the reference section reading table on the second floor.",
            "Library",
            "2025-08-20",
            "Pending",
            "wallet.svg",
            "Nishanth U",
            "nishanth.25it111@kpriet.ac.in",
            "+91 94870 25111",
            "Contains HDFC debit card ending in 4821 and college bus pass",
            3,
        ),
        (
            "Backpack",
            "Found",
            "Bags & Backpacks",
            "Navy blue Wildcraft laptop backpack found near the beverage counter. Contains notebooks and a charger.",
            "Canteen",
            "2025-08-18",
            "Available",
            "backpack.svg",
            "Nishanth Babu Karthika",
            "nishanthbabu.25it110@kpriet.ac.in",
            "+91 94870 25110",
            "Identify the notebook subject name and charger brand inside",
            4,
        ),
        (
            "ID Card",
            "Lost",
            "ID Cards & Badges",
            "KPRIET B.Tech Information Technology Student Identity Card with blue lanyard.",
            "Academic Block",
            "2025-08-17",
            "Pending",
            "idcard.svg",
            "Mithresh S N",
            "mithresh.25it091@kpriet.ac.in",
            "+91 94870 25091",
            "Register number printed on the front barcode",
            5,
        ),
        (
            "Water Bottle",
            "Found",
            "Water Bottles & Containers",
            "Silver Milton insulated 1-litre stainless steel water bottle left on the spectators bench.",
            "Sports Ground",
            "2025-08-16",
            "Available",
            "bottle.svg",
            "Jeevagan M B",
            "jeevagan.25it069@kpriet.ac.in",
            "+91 94870 25069",
            "Sticker on the bottom base of the bottle",
            6,
        ),
        (
            "Casio Scientific Calculator",
            "Lost",
            "Electronics & Gadgets",
            "Casio fx-991EX ClassWiz non-programmable scientific calculator with black slide-on hard cover.",
            "IT Department Lab",
            "2025-08-15",
            "Pending",
            "calculator.svg",
            "Nishanth U",
            "nishanth.25it111@kpriet.ac.in",
            "+91 94870 25111",
            "Roll number etched on the back cover",
            3,
        ),
        (
            "Leather Wallet",
            "Found",
            "Wallets & Purses",
            "Black leather bi-fold wallet found under Reading Table 4. Handed over to Library Counter.",
            "Library",
            "2025-08-20",
            "Available",
            "wallet.svg",
            "Ms. J. Rathanaa Ranjeni",
            "rathanaa.it@kpriet.ac.in",
            "+91 98422 10002",
            "Confirm bank card type and approximate cash denomination",
            2,
        ),
        (
            "Wireless Earbuds",
            "Lost",
            "Electronics & Gadgets",
            "Matte black OnePlus Nord Buds 2 in charging case with red charging cable inside pouch.",
            "Main Auditorium",
            "2025-08-14",
            "Resolved",
            "earbuds.svg",
            "Mithresh S N",
            "mithresh.25it091@kpriet.ac.in",
            "+91 94870 25091",
            "Silicone case cover color and serial number",
            5,
        ),
        (
            "Bike Keys with Keychain",
            "Found",
            "Keys & Keychains",
            "Royal Enfield ignition key with a metallic KPRIET TechFest keychain found near Two-Wheeler Bay 3.",
            "Parking Area",
            "2025-08-13",
            "Available",
            "keys.svg",
            "Jeevagan M B",
            "jeevagan.25it069@kpriet.ac.in",
            "+91 94870 25069",
            "Key number tag or vehicle registration number",
            6,
        ),
        (
            "Data Structures Textbook",
            "Lost",
            "Books & Stationery",
            "Fundamentals of Data Structures in C by Horowitz and Sahni, 2nd Edition with yellow sticky notes.",
            "Academic Block",
            "2025-08-12",
            "Claimed",
            "book.svg",
            "Nishanth Babu Karthika",
            "nishanthbabu.25it110@kpriet.ac.in",
            "+91 94870 25110",
            "Signature on inner title page",
            4,
        ),
        (
            "Student ID Badge",
            "Found",
            "ID Cards & Badges",
            "Found a KPRIET student ID card in a transparent holder near Corridor B staircase.",
            "Academic Block",
            "2025-08-17",
            "Available",
            "idcard.svg",
            "Ms. J. Rathanaa Ranjeni",
            "rathanaa.it@kpriet.ac.in",
            "+91 98422 10002",
            "Provide student register number and blood group",
            2,
        ),
    ]

    db.executemany(
        """
        INSERT INTO items (
            title, item_type, category, description, location, date_reported,
            status, image_filename, contact_name, contact_email, contact_phone,
            verification_hint, reporter_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        items,
    )

    # Seed Claims & Ownership Verifications
    claims = [
        (
            6,
            3,
            "Nishanth U",
            "nishanth.25it111@kpriet.ac.in",
            "+91 94870 25111",
            "Ownership Claim",
            "It is my black leather wallet containing an HDFC debit card ending in 4821, my KPRIET bus pass, and Rs. 350 cash.",
            "Pending",
            None,
            None,
        ),
        (
            9,
            4,
            "Nishanth Babu Karthika",
            "nishanthbabu.25it110@kpriet.ac.in",
            "+91 94870 25110",
            "Ownership Claim",
            "My name and roll number 25IT110 are written in blue ink on page 1.",
            "Approved",
            "Verified student ID and signature on page 1.",
            1,
        ),
    ]

    db.executemany(
        """
        INSERT INTO claims (
            item_id, claimant_id, claimant_name, claimant_email, claimant_phone,
            claim_type, proof_description, status, admin_notes, reviewed_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        claims,
    )

    # Seed Notifications (Chapter 9.4.3 Automatic Notifications)
    notifications = [
        (
            3,
            6,
            "Potential Match Found for 'Wallet'!",
            "A found item 'Leather Wallet' reported at 'Library' on 2025-08-20 closely matches your lost item 'Wallet' (88% match confidence).",
            "match",
            0,
        ),
        (
            5,
            10,
            "Potential Match Found for 'ID Card'!",
            "A found item 'Student ID Badge' reported at 'Academic Block' on 2025-08-17 closely matches your lost item 'ID Card' (82% match confidence).",
            "match",
            0,
        ),
        (
            1,
            6,
            "New Ownership Claim Submitted",
            "Nishanth U (25IT111) submitted an ownership claim for Item #6 (Leather Wallet).",
            "claim",
            0,
        ),
    ]

    db.executemany(
        """
        INSERT INTO notifications (user_id, item_id, title, message, notification_type, is_read)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        notifications,
    )

    db.execute(
        """
        INSERT INTO audit_logs (actor_id, actor_name, action, target_type, target_id, details, ip_address)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (1, "Dr. I. C. Amitha (Admin)", "SYSTEM_SEED", "system", 0, "Initialized LostLink Campus database with seed records", "127.0.0.1"),
    )

    db.commit()


def init_app(app):
    app.teardown_appcontext(close_db)
