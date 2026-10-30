"""
Comprehensive Automated Test Suite for LostLink – Campus Lost and Found Management System.
Covers:
- Chapter 8.4 Test Cases (TC01 through TC08) verbatim
- Unit Tests (8.3.1): Input validation, password hashing, smart matching algorithm, database schema & seed
- Integration Tests (8.3.2): Form submission -> Flask route -> SQLite persistence -> Notification generation
- Functional & E2E Flows (8.3.3 & 8.3.4): Student registration, login, reporting lost/found items with image upload,
  browsing listings, filtering, keyword & advanced searching, submitting ownership claims, and Admin moderation
- Security & Edge Cases: CSRF enforcement, RBAC authorization (403/302 on `/admin`), SQL injection resilience,
  invalid file upload rejection, and 404 error handling.

Runnable with one command:
  python3 -m unittest discover -s tests -p "test_*.py" -v
  (or `pytest -v` when pytest is installed)
"""
import io
import os
import tempfile
import unittest

from lostlink import create_app
from lostlink.compat import check_password_hash, generate_password_hash
from lostlink.db import get_db
from lostlink.matching import compute_match_score, find_potential_matches, tokenize
from lostlink.security import validate_item_form


class LostLinkTestCase(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self.upload_dir = tempfile.mkdtemp(prefix="lostlink_uploads_")
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": self.db_path,
                "UPLOAD_FOLDER": self.upload_dir,
                "CSRF_ENABLED": False,  # Disabled by default in functional tests; tested explicitly in test_csrf_protection
                "SEED_ON_STARTUP": True,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        os.close(self.db_fd)
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)
        for root, dirs, files in os.walk(self.upload_dir, topdown=False):
            for name in files:
                os.unlink(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))
        if os.path.exists(self.upload_dir):
            os.rmdir(self.upload_dir)

    def login(self, identifier: str, password: str):
        return self.client.post(
            "/login",
            data={"identifier": identifier, "password": password},
            follow_redirects=True,
        )

    # ==========================================================================
    # 1. CHAPTER 8.4 OFFICIAL REPORT TEST CASES (TC01 - TC08)
    # ==========================================================================

    def test_tc01_open_application_home_page(self):
        """TC01: Open the application -> The home page should load correctly (Figure 7.1)."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("LostLink", html)
        self.assertIn("Campus Lost and Found Management System", html)
        self.assertIn("Report Lost Item", html)
        self.assertIn("Report Found Item", html)
        self.assertIn("View Items", html)
        self.assertIn("Search", html)

    def test_tc02_submit_lost_item_report_valid(self):
        """TC02: Submit a lost item report with valid details -> Accepted and saved (Figure 7.2)."""
        resp = self.client.post(
            "/report-lost",
            data={
                "item_name": "Apple Pencil 2nd Gen",
                "description": "White Apple Pencil with magnetic side flat edge lost in Seminar Hall",
                "location": "Main Auditorium",
                "date_reported": "2026-10-28",
                "category": "Electronics & Gadgets",
                "contact_name": "Nishanth U",
                "contact_email": "nishanth.25it111@kpriet.ac.in",
                "verification_hint": "Engraved initials NU near tip",
            },
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("Apple Pencil 2nd Gen", html)
        self.assertIn("Main Auditorium", html)

        with self.app.app_context():
            db = get_db()
            row = db.execute(
                "SELECT * FROM items WHERE title = ?", ("Apple Pencil 2nd Gen",)
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["item_type"], "Lost")
            self.assertEqual(row["status"], "Pending")

    def test_tc03_submit_found_item_report_valid(self):
        """TC03: Submit a found item report with valid details -> Accepted and saved (Figure 7.3)."""
        resp = self.client.post(
            "/report-found",
            data={
                "item_name": "Lab Coat",
                "description": "White cotton chemistry lab coat size M found on bench 3",
                "location": "Academic Block",
                "date_reported": "2026-10-29",
                "category": "Accessories & Documents",
                "contact_name": "Mithresh S N",
                "contact_email": "mithresh.25it091@kpriet.ac.in",
            },
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("Lab Coat", html)
        self.assertIn("Available", html)

        with self.app.app_context():
            db = get_db()
            row = db.execute(
                "SELECT * FROM items WHERE title = ?", ("Lab Coat",)
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["item_type"], "Found")
            self.assertEqual(row["status"], "Available")

    def test_tc04_submit_form_with_required_fields_missing(self):
        """TC04: Submit a form with required fields missing -> Shows validation feedback and rejects (400)."""
        resp = self.client.post(
            "/report-lost",
            data={
                "item_name": "",
                "description": "",
                "location": "",
                "date_reported": "",
            },
        )
        self.assertEqual(resp.status_code, 400)
        html = resp.get_data(as_text=True)
        self.assertIn("Item Name is required.", html)
        self.assertIn("Description is required.", html)
        self.assertIn("Location is required.", html)
        self.assertIn("Date is required.", html)

    def test_tc05_view_item_listing_page_and_filters(self):
        """TC05: View the item listing page -> Available item records displayed with filters (Figure 7.4)."""
        resp_all = self.client.get("/items")
        self.assertEqual(resp_all.status_code, 200)
        html_all = resp_all.get_data(as_text=True)
        self.assertIn("Wallet", html_all)
        self.assertIn("Backpack", html_all)
        self.assertIn("ID Card", html_all)
        self.assertIn("Water Bottle", html_all)

        resp_lost = self.client.get("/items?type=lost")
        self.assertEqual(resp_lost.status_code, 200)
        html_lost = resp_lost.get_data(as_text=True)
        self.assertIn("Wallet", html_lost)
        self.assertNotIn("Silver Milton insulated", html_lost)

        resp_found = self.client.get("/items?type=found")
        self.assertEqual(resp_found.status_code, 200)
        html_found = resp_found.get_data(as_text=True)
        self.assertIn("Backpack", html_found)

    def test_tc06_search_existing_item(self):
        """TC06: Search for an existing item -> Relevant matching records displayed (Figure 7.5)."""
        resp = self.client.get("/search?q=wallet")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("Wallet", html)
        self.assertIn("Black wallet with 2 cards and cash", html)
        self.assertIn("Library", html)

    def test_tc07_search_non_existing_item(self):
        """TC07: Search for a non-existing item -> Appropriate message or empty result displayed."""
        resp = self.client.get("/search?q=nonexistent_quantum_telescope_999")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("Search Results (0 items found)", html)
        self.assertIn("No Matching Items Found", html)

    def test_tc08_open_item_details_page(self):
        """TC08: Open an item details page -> Selected item's available details displayed (Figure 7.6)."""
        resp = self.client.get("/items/1")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("Wallet", html)
        self.assertIn("Black wallet with 2 cards and cash", html)
        self.assertIn("Library", html)
        self.assertIn("2025-08-20", html)
        self.assertIn("Contact Owner", html)

    # ==========================================================================
    # 2. UNIT TESTS (8.3.1): Validation, Hashing, Matching Engine, Seed Stats
    # ==========================================================================

    def test_unit_password_hashing(self):
        pw_hash = generate_password_hash("CampusSecret#2026")
        self.assertTrue(check_password_hash(pw_hash, "CampusSecret#2026"))
        self.assertFalse(check_password_hash(pw_hash, "WrongPassword"))
        self.assertFalse(check_password_hash("invalid_hash", "CampusSecret#2026"))

    def test_unit_form_validation_edge_cases(self):
        with self.app.app_context():
            # Invalid date format and invalid email
            ok, errs, _ = validate_item_form(
                {
                    "item_name": "Keys",
                    "description": "Hostel room key with blue tag",
                    "location": "Canteen",
                    "date_reported": "20-08-2025",  # wrong format, expects YYYY-MM-DD
                    "contact_email": "not-an-email",
                }
            )
            self.assertFalse(ok)
            self.assertTrue(any("YYYY-MM-DD" in e for e in errs))
            self.assertTrue(any("valid contact email" in e for e in errs))

    def test_unit_smart_matching_algorithm(self):
        lost_wallet = {
            "id": 1,
            "title": "Wallet",
            "item_type": "Lost",
            "category": "Wallets & Purses",
            "description": "Black wallet with 2 cards and cash",
            "location": "Library",
            "date_reported": "2025-08-20",
            "status": "Pending",
        }
        found_wallet = {
            "id": 6,
            "title": "Leather Wallet",
            "item_type": "Found",
            "category": "Wallets & Purses",
            "description": "Black leather bi-fold wallet found under Reading Table 4",
            "location": "Library",
            "date_reported": "2025-08-20",
            "status": "Available",
        }
        unrelated_bottle = {
            "id": 4,
            "title": "Water Bottle",
            "item_type": "Found",
            "category": "Water Bottles & Containers",
            "description": "Silver Milton insulated water bottle",
            "location": "Sports Ground",
            "date_reported": "2025-08-01",
            "status": "Available",
        }
        high_score = compute_match_score(lost_wallet, found_wallet)
        low_score = compute_match_score(lost_wallet, unrelated_bottle)
        same_type_score = compute_match_score(lost_wallet, lost_wallet)

        self.assertGreaterEqual(high_score, 75)
        self.assertLess(low_score, 30)
        self.assertEqual(same_type_score, 0)

    def test_unit_seed_data_matches_figure_7_7_counts(self):
        """Verifies seed data matches Figure 7.7: Total=10, Lost=5, Found=5, Pending=3."""
        resp = self.client.get("/api/stats")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["total_items"], 10)
        self.assertEqual(data["lost_items"], 5)
        self.assertEqual(data["found_items"], 5)
        self.assertEqual(data["pending_reports"], 3)

    # ==========================================================================
    # 3. INTEGRATION & E2E TESTS (8.3.2 & 8.3.3): Auth, Uploads, Claims, Admin
    # ==========================================================================

    def test_e2e_student_registration_login_and_notifications(self):
        reg_resp = self.client.post(
            "/register",
            data={
                "full_name": "Arun Kumar S",
                "register_no": "25IT199",
                "email": "arun.25it199@kpriet.ac.in",
                "phone": "+91 98765 43210",
                "department": "Information Technology",
                "password": "Password@123",
                "confirm_password": "Password@123",
            },
            follow_redirects=True,
        )
        self.assertEqual(reg_resp.status_code, 200)
        self.assertIn("Registration successful", reg_resp.get_data(as_text=True))

        notif_resp = self.client.get("/notifications")
        self.assertEqual(notif_resp.status_code, 200)
        self.assertIn("Welcome to LostLink Campus Portal!", notif_resp.get_data(as_text=True))

        # Mark notifications read
        mark_resp = self.client.post("/notifications/mark-read", follow_redirects=True)
        self.assertEqual(mark_resp.status_code, 200)
        self.assertIn("Notifications marked as read", mark_resp.get_data(as_text=True))

    def test_e2e_image_upload_and_automatic_match_notification(self):
        # Log in as Student Nishanth U (id=3)
        self.login("25IT111", "Student@123")

        # Upload a found calculator that matches Lost Item #5 (Casio Scientific Calculator at IT Department Lab)
        fake_svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>'
        resp = self.client.post(
            "/report-found",
            data={
                "item_name": "Casio fx-991EX Calculator",
                "description": "Found black Casio scientific calculator in IT Department Lab near system 12",
                "location": "IT Department Lab",
                "date_reported": "2025-08-16",
                "category": "Electronics & Gadgets",
                "image": (io.BytesIO(fake_svg), "found_calc.svg", "image/svg+xml"),
            },
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("Casio fx-991EX Calculator", html)
        self.assertIn("Smart Potential Campus Matches", html)

    def test_e2e_ownership_claim_and_admin_approval_workflow(self):
        # Submit an ownership claim on Found Item #2 (Backpack)
        claim_resp = self.client.post(
            "/items/2/claim",
            data={
                "claimant_name": "Jeevagan M B",
                "claimant_email": "jeevagan.25it069@kpriet.ac.in",
                "claimant_phone": "+91 94870 25069",
                "claim_type": "Ownership Claim",
                "proof_description": "Contains my Operating Systems notebook and Dell 65W charger.",
            },
            follow_redirects=True,
        )
        self.assertEqual(claim_resp.status_code, 200)
        self.assertIn("has been submitted", claim_resp.get_data(as_text=True))

        # Verify non-admin cannot access /admin
        self.login("25IT069", "Student@123")
        forbidden_resp = self.client.get("/admin")
        self.assertEqual(forbidden_resp.status_code, 403)
        self.client.get("/logout")

        # Log in as Administrator (Figure 7.7)
        admin_login = self.login("admin@kpriet.ac.in", "Admin@123")
        self.assertEqual(admin_login.status_code, 200)
        admin_html = admin_login.get_data(as_text=True)
        self.assertIn("Administrator Dashboard", admin_html)

        # Find the newly created claim ID and approve it
        with self.app.app_context():
            db = get_db()
            claim = db.execute(
                "SELECT id FROM claims WHERE item_id = 2 ORDER BY id DESC LIMIT 1"
            ).fetchone()
            claim_id = claim["id"]

        review_resp = self.client.post(
            f"/admin/claims/{claim_id}/review",
            data={"decision": "Approved", "admin_notes": "Verified Dell charger serial number"},
            follow_redirects=True,
        )
        self.assertEqual(review_resp.status_code, 200)
        self.assertIn("has been approved", review_resp.get_data(as_text=True))

        # Confirm Item #2 status is now Resolved
        with self.app.app_context():
            db = get_db()
            item2 = db.execute("SELECT status FROM items WHERE id = 2").fetchone()
            self.assertEqual(item2["status"], "Resolved")

        # Test Admin direct status update and item deletion
        status_resp = self.client.post(
            "/admin/items/1/status",
            data={"status": "Resolved"},
            follow_redirects=True,
        )
        self.assertEqual(status_resp.status_code, 200)

        del_resp = self.client.post("/admin/items/10/delete", follow_redirects=True)
        self.assertEqual(del_resp.status_code, 200)
        self.assertIn("has been removed", del_resp.get_data(as_text=True))

    # ==========================================================================
    # 4. SECURITY, REST API & EDGE CASE TESTS
    # ==========================================================================

    def test_security_csrf_protection_enforced(self):
        csrf_app = create_app(
            {
                "TESTING": False,
                "DATABASE_PATH": self.db_path,
                "UPLOAD_FOLDER": self.upload_dir,
                "CSRF_ENABLED": True,
            }
        )
        csrf_client = csrf_app.test_client()
        # POST without CSRF token must return 400 Bad Request
        resp = csrf_client.post(
            "/report-lost",
            data={
                "item_name": "Test Item",
                "description": "Testing missing CSRF token",
                "location": "Library",
                "date_reported": "2026-10-30",
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("CSRF token missing or invalid", resp.get_data(as_text=True))

    def test_security_sql_injection_resilience(self):
        sqli_payload = "' OR 1=1; DROP TABLE items; --"
        resp = self.client.get("/search", query_string={"q": sqli_payload})
        self.assertEqual(resp.status_code, 200)
        # Ensure items table is completely intact
        health = self.client.get("/api/health").get_json()
        self.assertEqual(health["items_count"], 10)

    def test_security_reject_invalid_upload_extension(self):
        bad_file = (io.BytesIO(b"#!/bin/sh\necho hacked"), "exploit.sh", "application/x-sh")
        resp = self.client.post(
            "/report-lost",
            data={
                "item_name": "Laptop",
                "description": "Dell Inspiron 15 silver laptop",
                "location": "Library",
                "date_reported": "2026-10-30",
                "image": bad_file,
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Unsupported image file type", resp.get_data(as_text=True))

    def test_rest_api_endpoints_and_404_handler(self):
        items_api = self.client.get("/api/items?type=Lost&q=Wallet").get_json()
        self.assertEqual(items_api["count"], 1)
        self.assertEqual(items_api["items"][0]["title"], "Wallet")

        matches_api = self.client.get("/api/items/1/matches").get_json()
        self.assertTrue(len(matches_api["matches"]) >= 1)
        self.assertEqual(matches_api["matches"][0]["title"], "Leather Wallet")

        not_found = self.client.get("/items/99999")
        self.assertEqual(not_found.status_code, 404)
        self.assertIn("404", not_found.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
