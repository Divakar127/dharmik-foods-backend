from datetime import date
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Category = Literal["Grains & millets", "Nuts & seeds", "Pantry essentials", "Drinks & infusions", "Pottery"]
Collection = Literal["Everyday nourishment", "Mindful sugar", "Hydration", "Balanced eating", "Diabetes-Friendly Picks"]

class ProductWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_default=True)
    @field_validator("collection", mode="before")
    @classmethod
    def canonical_collection(cls, value):
        return "Diabetes-Friendly Picks" if value == "Sugar Smart Pantry" else value

    sku: str = Field(default="", max_length=40, pattern=r"^(?:DF-(?:GRM|NTS|PNY|DRK|POT)-[0-9]{6,})?$")
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(min_length=10, max_length=3000)
    price: Decimal = Field(gt=0, le=1000000, decimal_places=2)
    category: Category
    collection: Collection
    pack_size: str = Field(min_length=1, max_length=60)
    ingredients: str = Field(min_length=1, max_length=1500)
    allergens: str = Field(min_length=1, max_length=500)
    storage: str = Field(min_length=1, max_length=500)
    origin: str = Field(min_length=1, max_length=120)
    image_url: str = Field(default="", max_length=1000)
    image_credit: str = Field(default="", max_length=500)
    image_source: str = Field(default="", max_length=1000)
    gallery_images: list[str] = Field(default_factory=list, max_length=6)
    search_aliases: list[str] = Field(default_factory=list, max_length=30)
    sugar_smart: bool = False
    glycemic_index: int | None = Field(default=None, ge=0, le=100)
    glycemic_source: str = Field(default="", max_length=1000)
    carbohydrate_g: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=2)
    stock: int = Field(default=0, ge=0, le=1000000)
    location: str = Field(default="A-01", min_length=1, max_length=60)
    best_before: date | None = None
    status: Literal["draft", "published"] = "draft"
    protein_g: Decimal = Field(default=0, ge=0, le=100, decimal_places=2)
    fibre_g: Decimal = Field(default=0, ge=0, le=100, decimal_places=2)
    sugar_g: Decimal = Field(default=0, ge=0, le=100, decimal_places=2)
    nutrition_basis: str = Field(default="per 100 g", min_length=1, max_length=60)

    @field_validator("sku", mode="before")
    @classmethod
    def normalized_sku(cls, value):
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("image_source", "glycemic_source")
    @classmethod
    def safe_source(cls, value):
        from urllib.parse import urlsplit
        if value:
            parsed = urlsplit(value)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in value):
                raise ValueError("Use a valid public HTTPS source URL")
        return value

    @field_validator("image_url")
    @classmethod
    def safe_image(cls, value):
        import re
        from urllib.parse import urlsplit
        if value.startswith("https://"):
            parsed = urlsplit(value)
            if not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in value):
                raise ValueError("Use a valid public HTTPS image URL without credentials")
        if value and not (value.startswith("https://") and len(value) <= 1000) and not re.fullmatch(r"/media/[a-f0-9]{32}\.webp", value) and value not in {f"/campaigns/promo-v2/{name}.webp" for name in ("everyday", "millets", "nuts", "tea", "pottery", "tradition")} and value not in {f"/campaigns/wide/{name}.webp" for name in ("everyday", "millets", "nuts", "tea", "pottery", "tradition")} and value not in {f"/campaigns/{name}.webp" for name in ("millets", "nuts", "tea", "pottery", "tradition")} and value not in {f"/food/photos/{name}.webp" for name in ("ragi", "oats", "almonds", "chia", "coconut", "water", "tea", "millet")} and value not in {f"/food/{name}.svg" for name in ("ragi", "oats", "almonds", "chia", "coconut", "water", "tea", "millet", "placeholder")}:
            raise ValueError("Use an HTTPS image URL")
        return value

    @field_validator("gallery_images")
    @classmethod
    def safe_gallery(cls, values):
        return list(dict.fromkeys(cls.safe_image(v) for v in values if v))

    @field_validator("search_aliases")
    @classmethod
    def clean_aliases(cls, values):
        if any(not v.strip() or len(v) > 80 for v in values):
            raise ValueError("Search aliases must contain 1–80 characters")
        return list(dict.fromkeys(v.strip() for v in values))

    @model_validator(mode="after")
    def valid_nutrition(self):
        if self.glycemic_index is not None and not self.glycemic_source.startswith("https://"):
            raise ValueError("A product-specific HTTPS evidence source is required for a reported GI value")
        if self.carbohydrate_g is not None and self.sugar_g > self.carbohydrate_g:
            raise ValueError("Total sugars cannot exceed total carbohydrate")
        if self.category == "Pottery" and (self.sugar_smart or self.glycemic_index is not None or self.collection != "Everyday nourishment"):
            raise ValueError("Pottery cannot be included in a dietary collection or have a GI value")
        if self.protein_g + self.fibre_g + self.sugar_g > 100:
            raise ValueError("Combined nutrients cannot exceed 100 g")
        return self

class ProductUpdate(ProductWrite):
    version: int = Field(ge=1)

class Product(ProductWrite):
    id: int
    version: int
    currency: str = "INR"
    available: bool

class ProductPage(BaseModel):
    items: list[Product]
    total: int
    page: int
    page_size: int
    search_suggestions: list[str] = Field(default_factory=list)
