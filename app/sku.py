"""Stable inventory identifiers: brand, initial category, global sequence."""
CODES = {"Grains & millets": "GRM", "Nuts & seeds": "NTS", "Pantry essentials": "PNY", "Drinks & infusions": "DRK", "Pottery": "POT"}

def make_sku(category, product_id):
    return f"DF-{CODES[category]}-{product_id:06d}"
