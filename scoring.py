"""
Scoring engine for grocery deal ranking.

The app ranks each matched flyer item with a composite score from 0 to 100:

    Composite = DiscountScore * 0.45
              + DistanceScore * 0.30
              + SubstituteScore * 0.25

Each component is also reported on a 0-100 scale so the UI can explain why
an item ranked where it did.
"""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import math
import re

from models import Deal, ScoredResult


@dataclass(frozen=True)
class ScoringConfig:
    weight_discount: float = 0.45
    weight_distance: float = 0.30
    weight_substitute: float = 0.25
    min_substitute_score: float = 30.0

    def normalized_weights(self) -> tuple[float, float, float]:
        total = self.weight_discount + self.weight_distance + self.weight_substitute
        return (
            self.weight_discount / total,
            self.weight_distance / total,
            self.weight_substitute / total,
        )


PRODUCT_FAMILIES = {
    "dairy": {
        "keywords": {
            "milk",
            "butter",
            "cheese",
            "yogurt",
            "cream",
            "egg",
            "eggs",
        },
        "related": {"dairy_alternatives"},
    },
    "dairy_alternatives": {
        "keywords": {"oat milk", "almond milk", "soy milk", "coconut milk", "plant milk"},
        "related": {"dairy"},
    },
    "protein": {
        "keywords": {
            "chicken",
            "beef",
            "pork",
            "turkey",
            "fish",
            "salmon",
            "tofu",
            "beans",
            "lentils",
            "chickpeas",
        },
        "related": {"vegetables"},
    },
    "vegetables": {
        "keywords": {
            "carrot",
            "broccoli",
            "cauliflower",
            "celery",
            "cabbage",
            "cucumber",
            "lettuce",
            "spinach",
            "kale",
            "pepper",
            "peppers",
            "zucchini",
            "tomato",
            "potato",
            "onion",
            "mushroom",
            "mushrooms",
            "asparagus",
            "pea",
            "peas",
        },
        "related": {"fruits", "protein"},
    },
    "fruits": {
        "keywords": {"apple", "banana", "orange", "berries", "berry", "grape", "grapes", "pear", "melon"},
        "related": {"vegetables"},
    },
    "grains": {
        "keywords": {"rice", "pasta", "bread", "oats", "cereal", "tortilla", "tortillas"},
        "related": {"protein"},
    },
}

SIZE_TOKENS = {
    "g",
    "kg",
    "ml",
    "l",
    "lb",
    "oz",
    "pack",
    "pk",
    "count",
    "ct",
    "dozen",
    "bunch",
    "bag",
    "box",
    "carton",
    "tray",
    "pc",
    "pcs",
}


def _normalize_text(text: str) -> str:
    return re.sub(r"[^a-z0-9\s%]+", " ", text.lower()).strip()


def _tokenize(text: str) -> set[str]:
    return {token for token in _normalize_text(text).split() if token}


def _size_signature(text: str) -> set[str]:
    tokens = _tokenize(text)
    return {
        token
        for token in tokens
        if token in SIZE_TOKENS or re.fullmatch(r"\d+(\.\d+)?%?", token) or re.fullmatch(r"\d+(\.\d+)?(g|kg|ml|l|lb|oz|ct|pk)", token)
    }


def _content_tokens(text: str) -> set[str]:
    tokens = _tokenize(text)
    return {token for token in tokens if token not in SIZE_TOKENS and not re.fullmatch(r"\d+(\.\d+)?%?", token)}


def infer_family(text: str) -> str | None:
    normalized = _normalize_text(text)
    tokens = _tokenize(text)
    best_family: str | None = None
    best_score = -1
    for family, spec in PRODUCT_FAMILIES.items():
        for keyword in sorted(spec["keywords"], key=len, reverse=True):
            matched = False
            if " " in keyword:
                matched = keyword in normalized
            elif keyword in tokens:
                matched = True
            if matched:
                score = len(keyword)
                if score > best_score:
                    best_score = score
                    best_family = family
    return best_family


def family_affinity(query_family: str | None, product_family: str | None) -> float:
    if not query_family or not product_family:
        return 0.0
    if query_family == product_family:
        return 1.0
    related = PRODUCT_FAMILIES.get(query_family, {}).get("related", set())
    if product_family in related:
        return 0.68
    return 0.0


def _distance_tier(distance_km: float | None) -> str:
    if distance_km is None:
        return "Unknown distance"
    if distance_km <= 1.5:
        return "Walking distance"
    if distance_km <= 5:
        return "Biking / quick drive"
    if distance_km <= 15:
        return "Standard drive"
    if distance_km <= 30:
        return "Extended drive"
    return "Long-range GTA search"


def distance_score(distance_km: float | None) -> float:
    """
    Piecewise 0-100 score based on straight-line distance.

    This follows the requested thresholds with smooth linear drops inside each
    band and a slow decay past 30 km that never quite reaches zero.
    """
    if distance_km is None:
        return 0.0
    d = max(0.0, distance_km)
    if d <= 1.5:
        return 100.0 - (d / 1.5) * 10.0
    if d <= 5.0:
        return 90.0 - ((d - 1.5) / 3.5) * 20.0
    if d <= 15.0:
        return 70.0 - ((d - 5.0) / 10.0) * 30.0
    if d <= 30.0:
        return 40.0 - ((d - 15.0) / 15.0) * 30.0

    decay = 10.0 - min(5.0, math.log1p(d - 30.0) * 1.2)
    return max(5.0, decay)


def discount_score(discount_fraction: float) -> float:
    """
    Convert a raw discount fraction (0.0-1.0) into a 0-100 score.
    Discounts under 5% are treated as noise and score zero.
    """
    pct = max(0.0, discount_fraction) * 100.0
    if pct < 5.0:
        return 0.0
    return min(100.0, (pct / 50.0) * 100.0)


def _match_exact(query: str, product_name: str) -> tuple[str, str, float]:
    return "Exact match", "Same item and brand text.", 100.0


def _match_direct(query: str, product_name: str, q_tokens: set[str], p_tokens: set[str]) -> tuple[str, str, float]:
    overlap = len(q_tokens & p_tokens) / max(1, len(q_tokens))
    score = 95.0 + min(3.0, overlap * 3.0)
    return "Direct substitute", "Same item, different brand or store label.", min(98.0, score)


def _match_size_variation(query: str, product_name: str) -> tuple[str, str, float]:
    q_size = _size_signature(query)
    p_size = _size_signature(product_name)
    size_gap = len(q_size.symmetric_difference(p_size))
    score = 90.0 - min(10.0, size_gap * 2.0)
    return "Size / format variation", "Same item with a different size, pack count, or format.", max(80.0, score)


def _match_category(query_family: str, q_tokens: set[str], p_tokens: set[str]) -> tuple[str, str, float]:
    overlap = len(q_tokens & p_tokens) / max(1, len(q_tokens))
    score = 60.0 + min(15.0, overlap * 20.0)
    return "Category substitute", "Same product family, but a different cut or variant.", min(75.0, score)


def _match_distant(query_family: str | None, product_family: str | None) -> tuple[str, str, float]:
    affinity = family_affinity(query_family, product_family)
    score = 30.0 + affinity * 20.0
    return "Distant substitute", "Related category that can work in a pinch.", min(50.0, score)


def classify_match(query: str, product_name: str) -> tuple[str, str, float]:
    q_norm = _normalize_text(query)
    p_norm = _normalize_text(product_name)
    if not q_norm or not p_norm:
        return "Irrelevant", "No useful comparison available.", 0.0

    if q_norm == p_norm:
        return _match_exact(query, product_name)

    q_tokens = _content_tokens(query)
    p_tokens = _content_tokens(product_name)
    q_family = infer_family(query)
    p_family = infer_family(product_name)
    shared = q_tokens & p_tokens
    overlap = len(shared) / max(1, len(q_tokens))
    char_ratio = SequenceMatcher(None, q_norm, p_norm).ratio()
    size_gap = _size_signature(query).symmetric_difference(_size_signature(product_name))

    if q_family and p_family and q_family == p_family:
        if overlap >= 0.8 and size_gap:
            return _match_size_variation(query, product_name)
        if overlap >= 0.75 or char_ratio >= 0.72:
            return _match_direct(query, product_name, q_tokens, p_tokens)
        if q_family == "dairy":
            if overlap >= 0.25:
                return _match_category(q_family, q_tokens, p_tokens)
            return "Irrelevant", "Same aisle, but not a usable dairy substitute.", 0.0
        return _match_category(q_family, q_tokens, p_tokens)

    if family_affinity(q_family, p_family) > 0:
        return _match_distant(q_family, p_family)

    if overlap >= 0.65:
        return _match_direct(query, product_name, q_tokens, p_tokens)

    if overlap >= 0.35 or char_ratio >= 0.55:
        return "Loose substitute", "Very approximate match, kept because the overlap is still meaningful.", 35.0

    return "Irrelevant", "Not a useful grocery substitute.", 0.0


def broaden_query(query: str) -> str:
    family = infer_family(query)
    base = _normalize_text(query)
    if not family:
        return f"{base} grocery item"
    if family == "dairy":
        return f"{base} milk butter"
    if family == "dairy_alternatives":
        return f"{base} plant milk"
    if family == "protein":
        return f"{base} chicken beef"
    if family == "vegetables":
        return f"{base} produce"
    if family == "fruits":
        return f"{base} produce"
    return f"{base} {family}"


def score_deal(query: str, deal: Deal, config: ScoringConfig) -> ScoredResult | None:
    match_type, match_note, substitute = classify_match(query, deal.product_name)
    if substitute < config.min_substitute_score:
        return None

    d_score = distance_score(deal.store.distance_km)
    disc_score = discount_score(deal.discount_pct)
    w_disc, w_dist, w_sub = config.normalized_weights()
    total = (disc_score * w_disc) + (d_score * w_dist) + (substitute * w_sub)

    return ScoredResult(
        deal=deal,
        match_type=match_type,
        match_note=match_note,
        distance_score=d_score,
        discount_score=disc_score,
        substitute_score=substitute,
        total_score=total,
        transport_tier=_distance_tier(deal.store.distance_km),
    )


def rank_deals(
    query: str,
    deals: list[Deal],
    config: ScoringConfig,
    max_distance_km: float | None = None,
) -> list[ScoredResult]:
    results: list[ScoredResult] = []
    for deal in deals:
        if max_distance_km is not None and deal.store.distance_km is not None and deal.store.distance_km > max_distance_km:
            continue
        scored = score_deal(query, deal, config)
        if scored is not None:
            results.append(scored)
    return sorted(results, key=lambda r: r.total_score, reverse=True)


def rank_deals_with_fallback(
    query: str,
    deals: list[Deal],
    config: ScoringConfig,
    max_distance_km: float | None = None,
) -> tuple[str, list[ScoredResult]]:
    direct = rank_deals(query, deals, config, max_distance_km=max_distance_km)
    if direct:
        return query, direct

    expanded = broaden_query(query)
    if expanded != query:
        relaxed = ScoringConfig(
            weight_discount=config.weight_discount,
            weight_distance=config.weight_distance,
            weight_substitute=config.weight_substitute,
            min_substitute_score=max(20.0, config.min_substitute_score * 0.7),
        )
        fallback = rank_deals(expanded, deals, relaxed, max_distance_km=max_distance_km)
        if fallback:
            return expanded, fallback

    return query, direct
