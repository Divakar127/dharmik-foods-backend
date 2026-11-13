"""Illustrative food catalog. Product and nutrition details are demo data."""
import json
from pathlib import Path

PHOTOS = {item["slug"]: item for item in json.loads((Path(__file__).parent / "photo_manifest.json").read_text(encoding="utf-8"))}

DESCRIPTIONS = {
 "ragi": "Finger millet, known as ragi or nachni, is a familiar ingredient in many regional kitchens. Try it in porridge, dosa batter, or flour blends for everyday cooking.",
 "oats": "Plain rolled oats for porridge, savoury bowls, and homemade muesli. Add your own fruit, nuts, or spices and choose the sweetness that suits your routine.",
 "almonds": "Raw almond kernels for snacking, grinding into meal, or adding a little crunch to breakfast. Contains tree nuts; check the allergen information before use.",
 "chia": "Whole chia seeds for soaked breakfast bowls and homemade puddings. Soak well in liquid before eating and follow the preparation instructions on the pack.",
 "coconut": "Coconut oil for a pantry inspired by regional Indian cooking. Use according to your recipe, and follow the pack guidance on cooking temperatures and storage.",
 "water": "Plain drinking water for everyday hydration. This is a sample catalog listing; refer to the actual bottle for source, quality, and best-before information.",
 "tea": "A ginger and tulsi infusion inspired by the simple, warming drinks made in home kitchens. Enjoy as part of your routine, without any treatment or immunity claims. Image shows ginger, a representative ingredient.",
 "millet": "Little millet, also called samai or kutki in some regions, brings another familiar grain to the table. Cook into a simple grain bowl, upma, or a recipe from your own family kitchen.",
}

SEEDS = [
    ("DF-GRM-000001", "Wholegrain ragi", "Grains & millets", "Mindful sugar", "500 g", "Ragi (finger millet)", "Packed in a facility that also handles wheat and nuts.", "Karnataka, India", "149.00", 42, 7.3, 11.2, 1.2, "ragi"),
    ("DF-GRM-000002", "Everyday rolled oats", "Grains & millets", "Balanced eating", "500 g", "Wholegrain oats", "Contains oats. May contain wheat; not certified gluten-free.", "India", "199.00", 28, 13, 10, 1, "oats"),
    ("DF-NTS-000003", "Raw almond kernels", "Nuts & seeds", "Everyday nourishment", "200 g", "Almonds", "Contains tree nuts (almonds).", "India", "329.00", 8, 21, 12, 4.4, "almonds"),
    ("DF-NTS-000004", "Whole chia seeds", "Nuts & seeds", "Balanced eating", "200 g", "Chia seeds", "May contain traces of sesame and tree nuts.", "India", "249.00", 35, 16.5, 34, 0, "chia"),
    ("DF-PNY-000005", "Cold-pressed coconut oil", "Pantry essentials", "Everyday nourishment", "500 ml", "Coconut oil", "Contains coconut. Check individual dietary needs.", "Kerala, India", "449.00", 19, 0, 0, 0, "coconut"),
    ("DF-DRK-000006", "Pure drinking water", "Drinks & infusions", "Hydration", "1 litre", "Drinking water", "No declared allergens. Refer to the pack for full details.", "India", "40.00", 60, 0, 0, 0, "water"),
    ("DF-DRK-000007", "Ginger & tulsi infusion", "Drinks & infusions", "Everyday nourishment", "20 infusion bags", "Dried ginger, tulsi leaves", "May contain traces of other herbs. Check the pack before use.", "India", "229.00", 16, 0, 0, 0, "tea"),
    ("DF-GRM-000008", "Unpolished little millet", "Grains & millets", "Mindful sugar", "500 g", "Little millet", "Packed in a facility that also handles wheat and nuts.", "Tamil Nadu, India", "169.00", 0, 7.7, 7.6, 0.5, "millet"),
]

def seed_products():
    for sku, name, category, collection, pack, ingredients, allergens, origin, price, stock, protein, fibre, sugar, art in SEEDS:
        yield dict(sku=sku, name=name, category=category, collection=collection, pack_size=pack,
                   ingredients=ingredients, allergens=allergens, origin=origin, price=price, stock=stock,
                   protein_g=str(protein), fibre_g=str(fibre), sugar_g=str(sugar), nutrition_basis="per 100 ml" if art in ("water", "tea", "coconut") else "per 100 g",
                   description=DESCRIPTIONS[art] + " Sample product: supplier, origin, nutrition and pack details must be verified before sale.",
                   storage="Store in a cool, dry place away from sunlight. Follow pack instructions after opening.",
                   image_url=PHOTOS[art]["local_path"], image_credit=PHOTOS[art]["artist"] + " · " + PHOTOS[art]["license"], image_source=PHOTOS[art]["source"], location=f"A-{1 + (int(sku[-3:]) - 1) // 2:02d}", best_before=None, status="published")
