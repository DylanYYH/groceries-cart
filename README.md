# BrightCart / Grocery Deal Finder

Local Richmond Hill and GTA grocery deal finder with a register-or-sign-in flow.

## Run it

```bash
python3 main.py
```

Open `http://127.0.0.1:8765/`.

## Flow

1. Register with email and password or sign in to an existing account.
2. Search an item such as `butter`, `milk`, or `chicken breast`.
3. Optionally update your current location and proximity radius from the search page.

## Ranking model

Every matched item is scored on a 0-100 scale with:

`Composite Score = (DiscountScore * 0.45) + (DistanceScore * 0.30) + (SubstituteScore * 0.25)`

### Discount Score

- Based on percent off relative to the regular price baseline.
- `score = min(100, (percent_discount / 50.0) * 100)`
- Discounts under 5% score 0.

### Distance Score

- Calculated from straight-line distance in km.
- 0 to 1.5 km: 100 down to 90
- 1.5 to 5 km: 90 down to 70
- 5 to 15 km: 70 down to 40
- 15 to 30 km: 40 down to 10
- Beyond 30 km: slow decay with a floor near 5

### Substitute Score

- Exact match: 100
- Direct substitute: 95-98
- Size / format variation: 80-90
- Category substitute: 60-75
- Distant substitute: 30-50
- Irrelevant: 0

## Project files

- `main.py` - local web server and auth-first search UI
- `scoring.py` - scoring logic, distance tiers, and match classifier
- `data_sources.py` - mock Richmond Hill / GTA stores, flyers, and geocoding
- `models.py` - shared dataclasses

## Mock data

The included dataset covers Richmond Hill, Aurora, Newmarket, Vaughan, North York, Toronto, Mississauga, and nearby GTA stores with sample flyer items for:

- dairy
- dairy alternatives
- vegetables
- fruit
- proteins

The app is intentionally mock-backed so the full flow works without external APIs.
