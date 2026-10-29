"""
Data sources. Two real integrations you'll need to wire up with your own
API access, plus mock data so the rest of the program is runnable/testable
without any keys.

1. geocode_address() / find_nearby_stores()
   -> Google Places API (Nearby Search + Geocoding API). Needs a
      GOOGLE_MAPS_API_KEY. Free tier covers a school project easily.
      Docs: https://developers.google.com/maps/documentation/places/web-service

2. fetch_deals_for_store()
   -> Flipp has no official public API. Community scrapers (e.g. on GitHub,
      search "flipp scraper python") hit Flipp's backend directly by postal
      code. This is unofficial and may violate Flipp's Terms of Service if
      used beyond personal/educational use -- read their ToS before you rely
      on it for anything more than a school project, and consider asking
      Flipp directly about developer access if you want to take this further.

Both real functions are stubbed below with clear TODOs. mock_* functions
give you Ontario-wide sample data so you can build/test the scoring and
CLI layers immediately.
"""
import math
import os
from typing import Optional

from models import Store, Deal

GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")

MOCK_LOCATIONS = {
    "richmond hill": (43.8828, -79.4403, "Richmond Hill Centre"),
    "richmond hill centre": (43.8828, -79.4403, "Richmond Hill Centre"),
    "markham": (43.8561, -79.3370, "Markham"),
    "vaughan": (43.8372, -79.5083, "Vaughan"),
    "toronto": (43.6532, -79.3832, "Toronto"),
    "north york": (43.7615, -79.4111, "North York"),
    "aurora": (44.0000, -79.4667, "Aurora"),
    "newmarket": (44.0500, -79.4667, "Newmarket"),
    "mississauga": (43.5890, -79.6441, "Mississauga"),
    "oakville": (43.4675, -79.6877, "Oakville"),
    "burlington": (43.3255, -79.7990, "Burlington"),
    "brampton": (43.7315, -79.7624, "Brampton"),
    "scarborough": (43.7764, -79.2318, "Scarborough"),
    "l4b": (43.8480, -79.4010, "Richmond Hill / L4B"),
    "l4c": (43.8900, -79.4370, "Richmond Hill / L4C"),
    "l4e": (43.9130, -79.4070, "Richmond Hill / L4E"),
    "l4s": (43.9200, -79.4490, "Richmond Hill / L4S"),
    "l3t": (43.8380, -79.3630, "Markham / L3T"),
    "m2n": (43.7685, -79.4141, "North York / M2N"),
}


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _normalize_location_text(text: str) -> str:
    return "".join(ch.lower() for ch in text if ch.isalnum() or ch.isspace()).strip()


def mock_geocode_location(location_text: str) -> tuple[float, float, str]:
    normalized = _normalize_location_text(location_text)
    compact = normalized.replace(" ", "")

    if compact[:3].upper() in {"L4B", "L4C", "L4E", "L4S", "L3T", "M2N"}:
        key = compact[:3].lower()
        lat, lng, label = MOCK_LOCATIONS[key]
        return lat, lng, label

    for key, value in MOCK_LOCATIONS.items():
        if key in normalized:
            lat, lng, label = value
            return lat, lng, label

    return MOCK_LOCATIONS["richmond hill"]


def geocode_address(address: str) -> tuple[float, float]:
    """
    TODO (real version): call Google Geocoding API:
      GET https://maps.googleapis.com/maps/api/geocode/json
          ?address={address}&key={GOOGLE_MAPS_API_KEY}
    Returns (lat, lng).
    """
    if not GOOGLE_MAPS_API_KEY:
        raise RuntimeError(
            "No GOOGLE_MAPS_API_KEY set. Using mock mode -- call mock_user_location() instead."
        )
    raise NotImplementedError("Wire this up with `requests` once you have an API key.")


def find_nearby_stores(lat: float, lng: float, radius_km: float = 5.0) -> list[Store]:
    """
    TODO (real version): call Google Places Nearby Search:
      GET https://maps.googleapis.com/maps/api/place/nearbysearch/json
          ?location={lat},{lng}&radius={radius_m}&type=grocery_or_supermarket
          &key={GOOGLE_MAPS_API_KEY}
    Map each result into a Store(...).
    """
    if not GOOGLE_MAPS_API_KEY:
        raise RuntimeError("No GOOGLE_MAPS_API_KEY set. Using mock mode -- call mock_nearby_stores() instead.")
    raise NotImplementedError("Wire this up with `requests` once you have an API key.")


def fetch_deals_for_store(store: Store) -> list[Deal]:
    """
    TODO (real version): use a Flipp-backend scraper keyed by postal code /
    lat-lng to pull current flyer items for `store.chain`, then map into
    Deal(...) objects. See module docstring re: ToS.
    """
    raise NotImplementedError("Wire this up with a Flipp scraper once you've reviewed their ToS.")


# ---------------------------------------------------------------------------
# Mock data - Ontario sample, so the app runs with no API keys.
# ---------------------------------------------------------------------------

def mock_user_location() -> tuple[float, float]:
    # Richmond Hill Centre area
    return (43.8828, -79.4403)


def mock_nearby_stores(lat: float, lng: float) -> list[Store]:
    raw = [
        # GTA
        ("No Frills Yonge & 16th", "No Frills", "10310 Yonge St, Richmond Hill", 43.8686, -79.4363),
        ("Metro Bathurst & Major Mack", "Metro", "9019 Bathurst St, Richmond Hill", 43.8477, -79.4441),
        ("FreshCo Elgin Mills", "FreshCo", "700 Elgin Mills Rd E, Richmond Hill", 43.8802, -79.4235),
        ("Food Basics Major Mack", "Food Basics", "9640 Bathurst St, Richmond Hill", 43.8637, -79.4436),
        ("Walmart Supercentre RH", "Walmart", "9350 Yonge St, Richmond Hill", 43.8443, -79.4374),
        ("Sobeys Bayview", "Sobeys", "12559 Bayview Ave, Richmond Hill", 43.9066, -79.3859),
        ("Longo's Aurora", "Longo's", "126 Wellington St E, Aurora", 44.0006, -79.4628),
        ("Farm Boy Newmarket", "Farm Boy", "17600 Yonge St, Newmarket", 44.0500, -79.4667),
        ("Loblaws North York", "Loblaws", "3777 Don Mills Rd, North York", 43.7572, -79.3516),
        ("Real Canadian Superstore Mississauga", "Real Canadian Superstore", "3040 Mavis Rd, Mississauga", 43.6057, -79.6648),

        # Eastern Ontario
        ("Food Basics Ottawa West", "Food Basics", "1230 Wellington St W, Ottawa", 45.4069, -75.7357),
        ("Metro Ottawa Centretown", "Metro", "450 Bank St, Ottawa", 45.4125, -75.6892),
        ("FreshCo Orleans", "FreshCo", "1226 Place d'Orleans Dr, Ottawa", 45.4841, -75.5147),
        ("Loblaws Kingston", "Loblaws", "1100 Princess St, Kingston", 44.2436, -76.5164),
        ("No Frills Brockville", "No Frills", "325 Stewart Blvd, Brockville", 44.6054, -75.7047),

        # Central / Southwestern Ontario
        ("Zehrs Kitchener", "Zehrs", "1005 Ottawa St N, Kitchener", 43.4509, -80.4701),
        ("Food Basics Waterloo", "Food Basics", "110 Erb St W, Waterloo", 43.4668, -80.5234),
        ("FreshCo London", "FreshCo", "1299 Oxford St E, London", 43.0023, -81.2330),
        ("Metro Hamilton", "Metro", "158 Main St E, Hamilton", 43.2561, -79.8692),
        ("No Frills St. Catharines", "No Frills", "400 Scott St, St. Catharines", 43.1712, -79.2498),
        ("Sobeys Burlington", "Sobeys", "1250 Brant St, Burlington", 43.3246, -79.7990),

        # Northern / Lake Superior corridor
        ("Foodland Sudbury", "Foodland", "945 Lasalle Blvd, Sudbury", 46.4917, -80.9930),
        ("Metro North Bay", "Metro", "1150 Cassells St, North Bay", 46.3113, -79.4545),
        ("Walmart Sault Ste. Marie", "Walmart", "293 Bay St, Sault Ste. Marie", 46.5259, -84.3461),
        ("No Frills Thunder Bay", "No Frills", "1250 Arthur St W, Thunder Bay", 48.3948, -89.2869),
    ]
    stores = []
    for name, chain, address, s_lat, s_lng in raw:
        store = Store(name=name, chain=chain, address=address, lat=s_lat, lng=s_lng)
        store.distance_km = haversine_km(lat, lng, s_lat, s_lng)
        stores.append(store)
    return stores


def mock_deals(stores: list[Store]) -> list[Deal]:
    store_lookup = {s.name: s for s in stores}
    deals = [
        # Vegetables / fruit
        Deal(store_lookup["FreshCo Elgin Mills"], "Carrots 2lb Bag", 2.49, 3.49),
        Deal(store_lookup["Food Basics Major Mack"], "Baby Carrots 340g", 1.99, 2.49),
        Deal(store_lookup["Sobeys Bayview"], "Broccoli Crowns", 2.79, 3.79),
        Deal(store_lookup["No Frills Yonge & 16th"], "Celery Bunch", 1.79, 2.29),
        Deal(store_lookup["Walmart Supercentre RH"], "Green Bell Peppers 3-pack", 4.49, 5.99),
        Deal(store_lookup["Metro Bathurst & Major Mack"], "Cauliflower Head", 3.49, 4.49),
        Deal(store_lookup["Longo's Aurora"], "Strawberries 1lb", 3.99, 5.99),
        Deal(store_lookup["Farm Boy Newmarket"], "Honeycrisp Apples 3lb Bag", 5.99, 7.49),

        # Dairy
        Deal(store_lookup["No Frills Yonge & 16th"], "Lactantia 2% Milk 4L", 5.49, 6.99),
        Deal(store_lookup["Metro Bathurst & Major Mack"], "Neilson 1% Milk 4L", 5.99, 6.49),
        Deal(store_lookup["FreshCo Elgin Mills"], "Oat Milk 1.89L, Natrel", 4.49, 5.29),
        Deal(store_lookup["Food Basics Major Mack"], "Almond Milk Unsweetened 1.89L", 3.99, 4.99),
        Deal(store_lookup["Walmart Supercentre RH"], "Great Value 2% Milk 4L", 5.29, 5.79),
        Deal(store_lookup["Sobeys Bayview"], "Chocolate Milk 2L", 3.49, 4.29),
        Deal(store_lookup["Longo's Aurora"], "Lactantia Salted Butter 454g", 4.79, 5.99),
        Deal(store_lookup["Metro Bathurst & Major Mack"], "Gay Lea Butter 454g", 4.99, 6.49),

        # Protein
        Deal(store_lookup["No Frills Yonge & 16th"], "Boneless Chicken Breast 1kg", 8.99, 12.99),
        Deal(store_lookup["Metro Bathurst & Major Mack"], "Ground Beef Lean 1kg", 7.99, 9.99),
        Deal(store_lookup["FreshCo Elgin Mills"], "Chicken Thighs Family Pack 1kg", 7.49, 9.49),
        Deal(store_lookup["Food Basics Major Mack"], "Chicken Wings 1kg", 6.99, 8.99),
        Deal(store_lookup["Sobeys Bayview"], "Pork Loin Chop 1kg", 8.49, 10.99),
        Deal(store_lookup["Walmart Supercentre RH"], "Tofu Firm 400g", 2.99, 3.79),
        Deal(store_lookup["Longo's Aurora"], "Atlantic Salmon Fillet 500g", 10.99, 14.99),
    ]
    return deals
