"""
Application Configuration for LostLink – Campus Lost and Found Management System.
Loads settings from environment variables (.env) with sensible defaults.
"""
import os
from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(BASE_DIR, ".env"))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "lostlink-kpriet-campus-secret-key-2026-prod")
    DATABASE_PATH = os.environ.get(
        "DATABASE_PATH", os.path.join(BASE_DIR, "instance", "lostlink.db")
    )
    UPLOAD_FOLDER = os.environ.get(
        "UPLOAD_FOLDER", os.path.join(BASE_DIR, "lostlink", "static", "uploads")
    )
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", 5 * 1024 * 1024))
    ALLOWED_EXTENSIONS = set(
        os.environ.get("ALLOWED_EXTENSIONS", "png,jpg,jpeg,gif,webp,svg").split(",")
    )
    CAMPUS_NAME = os.environ.get(
        "CAMPUS_NAME", "KPR Institute of Engineering and Technology (Autonomous)"
    )
    CAMPUS_LOCATION = "Arasur, Coimbatore – 641 407"
    UNIVERSITY_NAME = "Anna University, Chennai – 600 025"
    ITEM_CATEGORIES = [
        "Wallets & Purses",
        "ID Cards & Badges",
        "Bags & Backpacks",
        "Electronics & Gadgets",
        "Books & Stationery",
        "Keys & Keychains",
        "Water Bottles & Containers",
        "Accessories & Documents",
        "Other",
    ]
    CAMPUS_LOCATIONS = [
        "Library",
        "Canteen",
        "Academic Block",
        "Sports Ground",
        "IT Department Lab",
        "Main Auditorium",
        "Hostel Block A",
        "Hostel Block B",
        "Parking Area",
        "Admin Office",
        "Other Campus Area",
    ]
