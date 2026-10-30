"""
Smart Matching & Automatic Notification Engine (Chapter 6.6 AI Features & Chapter 9.4.3 / 9.4.4).
Computes similarity scores between Lost and Found items based on:
- Category match (35% weight)
- Location proximity / exact campus zone match (25% weight)
- Title & Description keyword token Jaccard/TF overlap + synonym mapping (30% weight)
- Date proximity (10% weight)
Automatically generates in-app notifications when a newly submitted item matches an existing
opposite-type report with >= 45% confidence.
"""
import re
from datetime import datetime

STOPWORDS = {
    "a", "an", "the", "in", "on", "at", "near", "by", "with", "and", "or",
    "of", "for", "to", "from", "was", "is", "lost", "found", "item", "my",
    "near", "side", "floor", "table", "counter", "campus", "kpriet",
}

SYNONYM_GROUPS = [
    {"wallet", "purse", "bifold", "cardholder", "cash", "leather"},
    {"id", "identity", "card", "badge", "lanyard", "roll", "register"},
    {"backpack", "bag", "rucksack", "laptopbag", "wildcraft", "pouch"},
    {"bottle", "flask", "thermos", "milton", "waterbottle", "container"},
    {"calculator", "casio", "classwiz", "fx991ex", "scientific"},
    {"earbuds", "earphones", "airpods", "headphones", "buds", "oneplus"},
    {"keys", "key", "keychain", "ignition", "bike", "royalenfield"},
    {"book", "textbook", "notebook", "manual", "horowitz", "structures"},
]


def tokenize(text: str) -> set:
    if not text:
        return set()
    words = re.findall(r"[a-z0-9]+", text.lower())
    tokens = {w for w in words if len(w) > 1 and w not in STOPWORDS}
    expanded = set(tokens)
    for t in tokens:
        for group in SYNONYM_GROUPS:
            if t in group:
                expanded.update(group)
    return expanded


def compute_match_score(item_a: dict, item_b: dict) -> int:
    """
    Returns an integer similarity confidence score between 0 and 100
    comparing a Lost item and a Found item.
    """
    if item_a.get("item_type") == item_b.get("item_type"):
        return 0
    if item_a.get("status") in ("Resolved", "Rejected") or item_b.get("status") in ("Resolved", "Rejected"):
        return 0

    score = 0.0

    # 1. Category Match (up to 35 points)
    cat_a = (item_a.get("category") or "").strip().lower()
    cat_b = (item_b.get("category") or "").strip().lower()
    if cat_a and cat_a == cat_b:
        score += 35.0

    # 2. Location Match (up to 25 points)
    loc_a = (item_a.get("location") or "").strip().lower()
    loc_b = (item_b.get("location") or "").strip().lower()
    if loc_a and loc_b:
        if loc_a == loc_b:
            score += 25.0
        elif loc_a in loc_b or loc_b in loc_a:
            score += 18.0

    # 3. Keyword & Semantic Token Overlap (up to 30 points)
    tokens_a = tokenize(f"{item_a.get('title', '')} {item_a.get('description', '')}")
    tokens_b = tokenize(f"{item_b.get('title', '')} {item_b.get('description', '')}")
    if tokens_a and tokens_b:
        intersection = tokens_a.intersection(tokens_b)
        union = tokens_a.union(tokens_b)
        jaccard = len(intersection) / max(len(union), 1)
        overlap_ratio = len(intersection) / max(min(len(tokens_a), len(tokens_b)), 1)
        text_score = min(30.0, (jaccard * 15.0) + (overlap_ratio * 20.0))
        score += text_score

    # 4. Date Proximity (up to 10 points)
    try:
        d_a = datetime.strptime(str(item_a.get("date_reported", ""))[:10], "%Y-%m-%d")
        d_b = datetime.strptime(str(item_b.get("date_reported", ""))[:10], "%Y-%m-%d")
        days_diff = abs((d_a - d_b).days)
        if days_diff == 0:
            score += 10.0
        elif days_diff <= 3:
            score += 8.0
        elif days_diff <= 7:
            score += 5.0
        elif days_diff <= 14:
            score += 2.0
    except ValueError:
        score += 4.0

    return min(99, int(round(score)))


def find_potential_matches(db, target_item, min_score: int = 40, limit: int = 5) -> list:
    """
    Finds opposite-type items in the database that potentially match `target_item`.
    """
    target_dict = dict(target_item)
    opposite_type = "Found" if target_dict.get("item_type") == "Lost" else "Lost"
    candidates = db.execute(
        """
        SELECT * FROM items
        WHERE item_type = ? AND status NOT IN ('Resolved', 'Rejected') AND id != ?
        ORDER BY id DESC
        """,
        (opposite_type, target_dict.get("id", 0)),
    ).fetchall()

    results = []
    for cand in candidates:
        cand_dict = dict(cand)
        confidence = compute_match_score(target_dict, cand_dict)
        if confidence >= min_score:
            cand_dict["match_confidence"] = confidence
            results.append(cand_dict)

    results.sort(key=lambda x: x["match_confidence"], reverse=True)
    return results[:limit]


def trigger_match_notifications(db, new_item_id: int) -> int:
    """
    Checks newly created item against opposite-type items and creates automatic
    notifications (Chapter 9.4.3) for both reporters when a match >= 45% is found.
    Returns number of notifications created.
    """
    new_item = db.execute("SELECT * FROM items WHERE id = ?", (new_item_id,)).fetchone()
    if not new_item:
        return 0

    matches = find_potential_matches(db, new_item, min_score=45, limit=3)
    created_count = 0

    for matched in matches:
        conf = matched["match_confidence"]
        # Notify the existing item's reporter if they have a user account
        if matched.get("reporter_id"):
            db.execute(
                """
                INSERT INTO notifications (user_id, item_id, title, message, notification_type)
                VALUES (?, ?, ?, ?, 'match')
                """,
                (
                    matched["reporter_id"],
                    new_item["id"],
                    f"Potential Match Found for '{matched['title']}'!",
                    f"A newly reported {new_item['item_type'].lower()} item '{new_item['title']}' at '{new_item['location']}' matches your report ({conf}% confidence).",
                ),
            )
            created_count += 1

        # Notify the new item's reporter if they have a user account
        if new_item["reporter_id"] and new_item["reporter_id"] != matched.get("reporter_id"):
            db.execute(
                """
                INSERT INTO notifications (user_id, item_id, title, message, notification_type)
                VALUES (?, ?, ?, ?, 'match')
                """,
                (
                    new_item["reporter_id"],
                    matched["id"],
                    f"Existing Match Found for '{new_item['title']}'!",
                    f"An existing {matched['item_type'].lower()} report '{matched['title']}' at '{matched['location']}' matches your submission ({conf}% confidence).",
                ),
            )
            created_count += 1

    if created_count > 0:
        db.commit()
    return created_count
