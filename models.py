"""
Core data structures used across the grocery finder.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Store:
    name: str
    chain: str            # e.g. "No Frills", "Metro", "FreshCo"
    address: str
    lat: float
    lng: float
    place_id: Optional[str] = None
    distance_km: Optional[float] = None  # filled in after user location is known


@dataclass
class Deal:
    store: Store
    product_name: str          # exact name as listed in the flyer
    sale_price: float
    regular_price: Optional[float]
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None

    @property
    def discount_pct(self) -> float:
        """Percent discount, 0.0-1.0. Falls back to 0 if no regular price on file."""
        if not self.regular_price or self.regular_price <= 0:
            return 0.0
        pct = (self.regular_price - self.sale_price) / self.regular_price
        return max(0.0, min(pct, 1.0))


@dataclass
class ScoredResult:
    deal: Deal
    match_type: str
    match_note: str
    distance_score: float    # 0-100
    discount_score: float    # 0-100
    substitute_score: float  # 0-100
    total_score: float       # 0-100
    transport_tier: str


@dataclass
class UserProfile:
    email: str
    location_text: str
    lat: float
    lng: float
    proximity_label: str
    max_distance_km: float
