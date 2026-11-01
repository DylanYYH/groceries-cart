# Grocery Scout / Grocery Deal Finder

Local Richmond Hill and GTA grocery deal finder with a register-or-sign-in flow.

## Run it locally

```bash
python3 main.py
```

Open `http://127.0.0.1:8765/`.

The server reads `HOST` and `PORT` from the environment. Render supplies `PORT`
automatically, and production binds to `0.0.0.0` so Render can route traffic to it.

## Deploy on Render

This repository is a Python server with a custom HTTP handler, so Render is the
recommended host. Create a new Web Service from this repository, or use the
included `render.yaml`. Render will use the included build, start, and health
check settings. The free service may sleep after inactivity.

The sign-in page pre-fills the demo account (`demo` / `smartcart`). New test
accounts are stored as salted password hashes in `users.json`. On Render, the
Blueprint mounts a small persistent disk at `/var/data` and stores the file at
`/var/data/users.json`, so registered test users survive deploys and restarts.
Sessions remain in memory, so users must sign in again after a restart.

## Location map

The search page includes a Leaflet map using OpenStreetMap tiles. Users can
enter a city/postal code or grant browser location permission. OpenStreetMap
attribution is displayed in the UI. The included store and deal data remains
mock data until a compliant retailer feed or approved data source is connected.

## Vercel note

Vercel is not the right deployment target for this repository in its current
form because it runs a long-lived Python `HTTPServer`. If the UI is later split
into a React/Vite or Next.js frontend with API routes, the frontend can move to
Vercel while this Python service remains on Render.

## Flow

1. Sign in with the prefilled demo account or open the registration page.
2. Search an item such as `butter`, `milk`, or `chicken breast`.
3. Optionally update your current location and proximity radius from the search page.
4. Use the account panel on the search page to see the current user or log out.

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
