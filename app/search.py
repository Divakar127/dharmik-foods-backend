"""Small-catalog multilingual relevance ranking. No external search service.

Unicode text, editable aliases, shared Tamil/Tanglish vocabulary and typo
matching are combined. The bounded scan is explicit: migrate candidate retrieval
to Atlas Search or Elasticsearch when the catalog exceeds 5,000 products.
"""
import re
import unicodedata
from difflib import SequenceMatcher

GROUPS = [
    ("ragi", "finger millet", "kezhvaragu", "kelvaragu", "கேழ்வரகு", "ராகி"),
    ("little millet", "samai", "saamai", "சாமை"),
    ("almond", "almonds", "badam", "badaam", "பாதாம்"),
    ("chia", "சியா", "chia seeds"),
    ("oats", "ஓட்ஸ்"),
    ("coconut", "thengai", "தேங்காய்"),
    ("water", "thanneer", "thannir", "thanni", "தண்ணீர்", "குடிநீர்"),
    ("ginger", "inji", "இஞ்சி"),
    ("tulsi", "thulasi", "துளசி"),
    ("pottery", "clay", "manpaanai", "manpanai", "mannpaanai", "மண்பானை", "மண் பானை", "earthen", "vessel"),
    ("grains", "millets", "siruthaniyam", "சிறுதானியம்"),
]
SUGAR_TERMS = {"diabetic", "diabetes", "diabetes friendly", "diabetic friendly", "sugar smart", "low sugar", "சர்க்கரை", "sakkarai"}

def normalize(value):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).casefold().strip())

def forms(query):
    q = normalize(query)
    expanded = {q}
    for group in GROUPS:
        if q in group:
            expanded.update(group)
    return expanded

def rank(query, products):
    queries = forms(query)
    scored = []
    for product in products:
        if normalize(query).startswith("df-"):
            if normalize(query) in normalize(product.get("sku", "")):
                scored.append((1.0, product))
            continue  # Inventory identifiers must never be typo-corrected.
        terms = [normalize(str(product.get(k, ""))) for k in ("name", "sku", "ingredients", "category")]
        terms += [normalize(a) for a in product.get("search_aliases", [])]
        if product.get("sugar_smart") or product.get("collection") == "Diabetes-Friendly Picks":
            terms += list(SUGAR_TERMS)
        if normalize(query) in {"low gi", "low glycemic", "low glycaemic"}:
            gi = product.get("glycemic_index")
            if gi is not None and gi <= 55 and product.get("glycemic_source", "").startswith("https://"):
                terms.append(normalize(query))
        best = 0.0
        words = [w for term in terms for w in term.split()]
        for q in queries:
            if not q:
                continue
            if q in terms:
                best = max(best, 1.0)
            elif any(q in term for term in terms):
                best = max(best, .94)
            else:
                tokens = q.split()
                matches = [max((SequenceMatcher(None, token, word).ratio() for word in words), default=0) for token in tokens]
                if matches and min(matches) >= .72 and min(map(len, tokens)) >= 3:
                    best = max(best, sum(matches)/len(matches)*.85)
        if best:
            scored.append((best, product))
    return [p for _, p in sorted(scored, key=lambda pair: (-pair[0], pair[1].get("_id", pair[1].get("id", 0))))]

def suggestions(query, products):
    return list(dict.fromkeys(p["name"] for p in rank(query, products)))[:5]
