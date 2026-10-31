"""
Local web entrypoint for the grocery finder prototype.

Run:
    python main.py

The app is dependency-free and uses mock Richmond Hill / GTA data so the
entire flow works immediately:
  1. register or sign in with email + password
  2. search grocery items and inspect ranked deal matches
  3. optionally adjust location and proximity from the search page
"""
from __future__ import annotations

import html
import hashlib
import hmac
import json
import os
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse
import uuid
import webbrowser

from data_sources import mock_deals, mock_geocode_location, mock_nearby_stores
from scoring import ScoringConfig, broaden_query, infer_family, rank_deals_with_fallback


HOST = os.environ.get("HOST") or (
    "0.0.0.0" if os.environ.get("APP_ENV") == "production" else "127.0.0.1"
)
PORT = int(os.environ.get("PORT", "8765"))
SESSION_COOKIE_NAME = "groceryscout_session"
DEMO_USERNAME = "demo"
DEMO_PASSWORD = "smartcart"

SESSION_STORE: dict[str, dict[str, object]] = {}
USER_STORE: dict[str, str] = {}

PROXIMITY_OPTIONS = {
    "close": {
        "label": "Walking distance",
        "radius": 2.0,
        "summary": "Prioritize the closest stores first.",
    },
    "nearby": {
        "label": "Biking / quick drive",
        "radius": 8.0,
        "summary": "Keep the search tight around Richmond Hill and nearby suburbs.",
    },
    "gta": {
        "label": "GTA-wide drive",
        "radius": 30.0,
        "summary": "Search farther across the GTA for stronger discounts.",
    },
}


def money(value: float) -> str:
    return f"${value:.2f}"


def pct(value: float) -> str:
    return f"{value:.0f}%"


def escape(value: object) -> str:
    return html.escape("" if value is None else str(value))


def password_digest(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}${digest.hex()}"


def password_matches(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


# A seeded account makes the public demo easy to evaluate.  This is intentionally
# in-memory and must not be used as real authentication or production data.
USER_STORE.setdefault(DEMO_USERNAME, password_digest(DEMO_PASSWORD))


def parse_cookie_value(cookie_header: str | None) -> str | None:
    if not cookie_header:
        return None
    cookie = SimpleCookie()
    cookie.load(cookie_header)
    morsel = cookie.get(SESSION_COOKIE_NAME)
    return morsel.value if morsel else None


def get_session(handler: BaseHTTPRequestHandler) -> tuple[str | None, dict[str, object] | None]:
    session_id = parse_cookie_value(handler.headers.get("Cookie"))
    if not session_id:
        return None, None
    return session_id, SESSION_STORE.get(session_id)


def create_session() -> tuple[str, dict[str, object]]:
    session_id = uuid.uuid4().hex
    session = {
        "authenticated": False,
        "email": "",
        "location_text": "Richmond Hill",
        "lat": 43.8828,
        "lng": -79.4403,
        "location_label": "Richmond Hill Centre",
        "proximity_key": "nearby",
        "max_distance_km": PROXIMITY_OPTIONS["nearby"]["radius"],
        "last_query": "butter",
    }
    SESSION_STORE[session_id] = session
    return session_id, session


def ensure_session(handler: BaseHTTPRequestHandler) -> tuple[str, dict[str, object]]:
    session_id, session = get_session(handler)
    if session_id and session:
        return session_id, session
    return create_session()


def read_form(handler: BaseHTTPRequestHandler) -> dict[str, str]:
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length).decode("utf-8") if length else ""
    data = parse_qs(raw)
    return {key: values[0].strip() for key, values in data.items()}


def send_html(handler: BaseHTTPRequestHandler, body: str, status: int = 200, cookie_value: str | None = None, location: str | None = None) -> None:
    payload = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    if cookie_value:
        secure = "; Secure" if os.environ.get("APP_ENV") == "production" else ""
        handler.send_header("Set-Cookie", f"{SESSION_COOKIE_NAME}={cookie_value}; Path=/; HttpOnly; SameSite=Lax{secure}")
    if location:
        handler.send_header("Location", location)
    handler.end_headers()
    handler.wfile.write(payload)


def redirect(handler: BaseHTTPRequestHandler, location: str, cookie_value: str | None = None) -> None:
    handler.send_response(303)
    if cookie_value:
        secure = "; Secure" if os.environ.get("APP_ENV") == "production" else ""
        handler.send_header("Set-Cookie", f"{SESSION_COOKIE_NAME}={cookie_value}; Path=/; HttpOnly; SameSite=Lax{secure}")
    handler.send_header("Location", location)
    handler.end_headers()


def proximity_summary(key: str) -> dict[str, object]:
    return PROXIMITY_OPTIONS.get(key, PROXIMITY_OPTIONS["nearby"])


def build_context(query: str, session: dict[str, object]) -> dict[str, object]:
    lat = float(session["lat"])
    lng = float(session["lng"])
    max_distance_km = float(session["max_distance_km"])
    stores = mock_nearby_stores(lat, lng)
    deals = mock_deals(stores)
    config = ScoringConfig()
    effective_query, results = rank_deals_with_fallback(query, deals, config, max_distance_km=max_distance_km)

    if not results and query != broaden_query(query):
        effective_query = broaden_query(query)

    return {
        "stores": sorted(stores, key=lambda store: store.distance_km or 9999.0),
        "deals": deals,
        "results": results,
        "config": config,
        "effective_query": effective_query,
        "query_family": infer_family(query),
        "location_label": session["location_label"],
        "location_text": session["location_text"],
        "proximity_key": session["proximity_key"],
        "max_distance_km": max_distance_km,
    }


def render_progress(active: str) -> str:
    return ""


def render_shell(title: str, active_step: str, main_html: str, sidebar_html: str) -> str:
    hero_title = "Compare grocery prices near you."
    hero_copy = "Search an item and see nearby store prices, distances, and savings in one place."
    sidebar_block = f'<aside class="panel">{sidebar_html}</aside>' if sidebar_html.strip() else ""
    layout_class = "layout single" if not sidebar_html.strip() else "layout"
    hero_class = "hero compact" if not sidebar_html.strip() else "hero"
    progress_html = render_progress(active_step)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(title)}</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" crossorigin="" />
  <style>
    :root {{
      --bg: #f3f8fb;
      --bg-2: #edf7ff;
      --card: rgba(255, 255, 255, 0.90);
      --border: rgba(104, 149, 189, 0.18);
      --text: #18354a;
      --muted: #5e7587;
      --primary: #356b9a;
      --primary-2: #6fb0da;
      --accent: #99e2d1;
      --accent-2: #dcf7ef;
      --shadow: 0 16px 42px rgba(47, 82, 114, 0.12);
      --radius: 24px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--text);
      font-family: "Avenir Next", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
      background:
        radial-gradient(circle at top left, rgba(111, 176, 218, 0.28), transparent 28%),
        radial-gradient(circle at top right, rgba(153, 226, 209, 0.22), transparent 22%),
        linear-gradient(180deg, var(--bg), #ffffff 56%, #f9fdff 100%);
      min-height: 100vh;
    }}
    .wrap {{
      max-width: 1220px;
      margin: 0 auto;
      padding: 28px 20px 48px;
    }}
    .hero {{
      position: relative;
      overflow: hidden;
      border: 1px solid var(--border);
      background: linear-gradient(135deg, rgba(255,255,255,0.94), rgba(238,248,255,0.96));
      border-radius: 32px;
      box-shadow: var(--shadow);
      padding: 28px;
      margin-bottom: 18px;
      text-align: center;
    }}
    .hero.compact {{
      max-width: 980px;
      margin-left: auto;
      margin-right: auto;
      padding: 24px 28px;
      text-align: left;
    }}
    .hero.compact h1 {{
      max-width: none;
      font-size: clamp(30px, 4vw, 46px);
      line-height: 1.08;
    }}
    .hero.compact p {{ margin-left: 0; margin-right: 0; max-width: 760px; }}
    .hero:not(.compact) {{ text-align: left; }}
    .hero:not(.compact) h1, .hero:not(.compact) p {{ margin-left: 0; margin-right: 0; }}
    .hero:not(.compact) .steps {{ justify-content: flex-start; }}
    .hero-mark {{
      display: inline-grid;
      place-items: center;
      width: 52px;
      height: 52px;
      flex: 0 0 52px;
      border-radius: 16px;
      color: #ffffff;
      background: linear-gradient(135deg, var(--primary), var(--primary-2));
      box-shadow: 0 10px 22px rgba(53, 107, 154, 0.20);
    }}
    .hero-mark svg {{ width: 30px; height: 30px; }}
    .hero-heading {{ display: flex; align-items: center; gap: 16px; }}
    .hero-heading h1 {{ margin: 0; max-width: none; }}
    .app-name {{
      margin: 0 0 10px;
      color: var(--primary);
      font-size: 14px;
      font-weight: 900;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .eyebrow {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--primary);
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      font-size: 12px;
      margin: 0 0 12px;
    }}
    h1 {{
      margin: 0;
      font-size: clamp(32px, 5vw, 58px);
      line-height: 1.02;
      letter-spacing: -0.04em;
      max-width: 900px;
      margin-left: auto;
      margin-right: auto;
    }}
    .hero p {{
      margin: 14px 0 0;
      max-width: 760px;
      margin-left: auto;
      margin-right: auto;
      color: var(--muted);
      font-size: 17px;
      line-height: 1.65;
    }}
    .steps {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 20px;
      justify-content: center;
    }}
    .step {{
      display: inline-flex;
      align-items: center;
      padding: 9px 12px;
      border-radius: 999px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,0.85);
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
    }}
    .step.active {{
      background: linear-gradient(135deg, var(--primary), var(--primary-2));
      color: white;
      border-color: transparent;
    }}
    .step-link {{ text-decoration: none; cursor: pointer; }}
    .step-link:hover {{ filter: brightness(1.06); transform: translateY(-1px); }}
    .step.done {{
      background: rgba(153,226,209,0.24);
      color: #1c6654;
      border-color: rgba(153,226,209,0.40);
    }}
    .layout {{
      display: grid;
      grid-template-columns: minmax(0, 1.5fr) minmax(300px, 0.9fr);
      gap: 20px;
      align-items: start;
    }}
    .layout > aside {{ position: sticky; top: 18px; }}
    .layout.single {{ grid-template-columns: minmax(0, 1fr); max-width: 980px; margin: 0 auto; }}
    .panel {{
      background: var(--card);
      backdrop-filter: blur(14px);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 22px;
    }}
    .panel h2 {{
      margin: 0 0 8px;
      font-size: 24px;
      letter-spacing: -0.03em;
    }}
    .panel .sub {{
      margin: 0 0 16px;
      color: var(--muted);
      line-height: 1.6;
    }}
    .field-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }}
    .auth-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
      margin-top: 12px;
    }}
    .auth-card {{
      padding: 18px;
      border-radius: 20px;
      background: linear-gradient(180deg, rgba(255,255,255,0.96), rgba(240,248,255,0.94));
      border: 1px solid rgba(104, 149, 189, 0.14);
    }}
    .auth-card h3 {{
      margin: 0 0 12px;
      font-size: 20px;
      letter-spacing: -0.03em;
    }}
    .demo-credentials {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      margin: 16px 0 4px;
      padding: 14px 16px;
      border-radius: 18px;
      background: linear-gradient(135deg, rgba(153,226,209,0.28), rgba(255,255,255,0.92));
      border: 1px solid rgba(85, 170, 152, 0.20);
      color: #24564b;
    }}
    .demo-credentials strong, .demo-credentials span {{ display: block; }}
    .demo-credentials span {{ margin-top: 4px; font-size: 13px; }}
    .demo-credentials code {{ font-weight: 800; color: #1c6654; }}
    .demo-inline {{ margin-top: 12px; padding: 10px 12px; }}
    .demo-inline .btn {{ padding: 10px 12px; font-size: 13px; }}
    .field {{
      display: grid;
      gap: 8px;
      margin-bottom: 12px;
    }}
    .field label {{
      font-size: 13px;
      font-weight: 800;
      letter-spacing: 0.02em;
      color: #355064;
    }}
    .field input, .field select {{
      width: 100%;
      border-radius: 16px;
      border: 1px solid rgba(104, 149, 189, 0.24);
      padding: 14px 16px;
      font-size: 15px;
      outline: none;
      color: var(--text);
      background: rgba(255,255,255,0.94);
    }}
    .field input:focus, .field select:focus {{
      border-color: var(--primary-2);
      box-shadow: 0 0 0 4px rgba(111, 176, 218, 0.18);
    }}
    .field input::placeholder {{
      color: #88a0b1;
    }}
    .actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 16px;
    }}
    .btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: 0;
      border-radius: 16px;
      padding: 14px 18px;
      font-weight: 800;
      font-size: 15px;
      cursor: pointer;
      text-decoration: none;
    }}
    .btn-primary {{
      color: white;
      background: linear-gradient(135deg, var(--primary), var(--primary-2));
      box-shadow: 0 10px 20px rgba(53, 107, 154, 0.20);
    }}
    .btn-secondary {{
      color: var(--primary);
      background: rgba(53, 107, 154, 0.08);
    }}
    .btn:hover {{ transform: translateY(-1px); filter: brightness(1.02); }}
    .btn:focus-visible, a:focus-visible {{ outline: 3px solid rgba(111,176,218,0.55); outline-offset: 3px; }}
    .quick-searches {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; align-items: center; }}
    .quick-searches span {{ color: var(--muted); font-size: 13px; font-weight: 700; margin-right: 2px; }}
    .quick-searches a {{ padding: 8px 11px; border-radius: 999px; color: var(--primary); background: rgba(53,107,154,0.08); text-decoration: none; font-size: 13px; font-weight: 800; }}
    .quick-searches a:hover {{ background: rgba(153,226,209,0.35); }}
    .guest-note {{ padding: 12px 14px; border-radius: 16px; background: var(--accent-2); color: #24564b; font-size: 13px; line-height: 1.5; }}
    .notice {{
      margin: 0 0 16px;
      padding: 14px 16px;
      border-radius: 18px;
      background: linear-gradient(180deg, rgba(153,226,209,0.22), rgba(255,255,255,0.90));
      border: 1px solid rgba(85, 170, 152, 0.18);
      color: #24564b;
      line-height: 1.55;
    }}
    .error {{
      margin: 0 0 16px;
      padding: 14px 16px;
      border-radius: 18px;
      background: rgba(255, 228, 228, 0.8);
      border: 1px solid rgba(196, 87, 87, 0.18);
      color: #7c2323;
      line-height: 1.55;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
      margin-top: 18px;
    }}
    .stat {{
      border-radius: 18px;
      padding: 16px 18px;
      background: linear-gradient(180deg, rgba(255,255,255,0.94), rgba(240,248,255,0.94));
      border: 1px solid rgba(104, 149, 189, 0.16);
    }}
    .stat strong {{
      display: block;
      font-size: 24px;
      margin-bottom: 4px;
      letter-spacing: -0.03em;
    }}
    .stat span {{
      color: var(--muted);
      font-size: 14px;
      line-height: 1.4;
    }}
    .results {{
      display: grid;
      gap: 14px;
    }}
    .deal-card {{
      border-radius: 22px;
      border: 1px solid rgba(104, 149, 189, 0.16);
      background: linear-gradient(180deg, rgba(255,255,255,0.96), rgba(243,249,255,0.94));
      padding: 18px;
    }}
    .deal-head {{
      display: flex;
      justify-content: space-between;
      gap: 14px;
      align-items: start;
    }}
    .deal-kicker {{
      margin: 0 0 5px;
      color: var(--primary);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 11px;
      font-weight: 800;
    }}
    .deal-card h3 {{
      margin: 0;
      font-size: 21px;
      letter-spacing: -0.03em;
      line-height: 1.2;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 9px 12px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 800;
      white-space: nowrap;
    }}
    .badge-score {{
      background: rgba(53, 107, 154, 0.10);
      color: var(--primary);
    }}
    .badge-match {{
      background: rgba(153, 226, 209, 0.24);
      color: #1f6957;
    }}
    .price-row {{
      display: flex;
      justify-content: space-between;
      align-items: end;
      gap: 12px;
      margin-top: 14px;
    }}
    .price {{
      display: block;
      font-size: 30px;
      font-weight: 800;
      letter-spacing: -0.04em;
      color: #173c59;
    }}
    .regular {{
      display: inline-block;
      margin-top: 3px;
      color: #7a91a6;
      font-size: 14px;
    }}
    .meta {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-top: 14px;
    }}
    .meta-item {{
      padding: 10px 12px;
      border-radius: 14px;
      background: rgba(255,255,255,0.92);
      border: 1px solid rgba(104, 149, 189, 0.12);
    }}
    .meta-item span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 4px;
      font-weight: 800;
    }}
    .meta-item strong {{
      display: block;
      font-size: 14px;
      line-height: 1.4;
    }}
    .score-breakdown {{
      margin-top: 14px;
      padding: 14px;
      border-radius: 18px;
      background: linear-gradient(180deg, rgba(155,231,212,0.16), rgba(255,255,255,0.92));
      border: 1px solid rgba(85, 170, 152, 0.14);
    }}
    .score-breakdown summary {{ cursor: pointer; color: #1f6957; font-weight: 800; font-size: 13px; }}
    .score-breakdown[open] summary {{ margin-bottom: 12px; }}
    .score-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }}
    .score-cell {{
      padding: 10px 12px;
      border-radius: 14px;
      background: rgba(255,255,255,0.86);
      border: 1px solid rgba(104, 149, 189, 0.10);
    }}
    .score-cell span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      font-weight: 800;
    }}
    .score-cell strong {{
      display: block;
      margin-top: 4px;
      font-size: 18px;
      letter-spacing: -0.02em;
    }}
    .formula {{
      margin: 12px 0 0;
      color: var(--text);
      font-size: 14px;
      line-height: 1.55;
    }}
    .sidebar-list {{
      display: grid;
      gap: 12px;
    }}
    .store-chip {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      padding: 14px 16px;
      border-radius: 18px;
      background: linear-gradient(180deg, rgba(255,255,255,0.92), rgba(241,249,255,0.95));
      border: 1px solid rgba(104, 149, 189, 0.15);
    }}
    .store-chip strong {{
      display: block;
      font-size: 15px;
    }}
    .store-chip p {{
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 13px;
    }}
    .store-chip span {{
      color: var(--primary);
      font-weight: 800;
      white-space: nowrap;
    }}
    .footer-note {{
      margin-top: 18px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.6;
    }}
    .empty-state {{
      padding: 22px;
      text-align: center;
      border-radius: 20px;
      background: rgba(255,255,255,0.84);
      border: 1px dashed rgba(104, 149, 189, 0.24);
      color: var(--muted);
    }}
    .map-panel {{
      min-height: 340px;
      overflow: hidden;
      border-radius: 20px;
      border: 1px solid rgba(104, 149, 189, 0.16);
      background: #dfeef5;
      margin: 18px 0;
    }}
    #store-map {{ min-height: 340px; width: 100%; }}
    .map-attribution {{
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 12px;
    }}
    .summary-card {{
      padding: 16px;
      border-radius: 18px;
      background: linear-gradient(180deg, rgba(255,255,255,0.94), rgba(240,248,255,0.94));
      border: 1px solid rgba(104, 149, 189, 0.14);
      margin-bottom: 14px;
    }}
    .summary-card strong {{
      display: block;
      font-size: 16px;
      margin-bottom: 4px;
    }}
    .summary-card p {{
      margin: 0;
      color: var(--muted);
      line-height: 1.5;
    }}
    @media (max-width: 900px) {{
      .layout, .stats, .score-grid, .field-grid, .meta {{
        grid-template-columns: 1fr;
      }}
      .deal-head, .price-row {{
        flex-direction: column;
        align-items: start;
      }}
      .layout > aside {{ position: static; }}
      .wrap {{ padding: 16px 12px 32px; }}
      .hero, .panel {{ padding: 18px; border-radius: 22px; }}
      .demo-credentials {{ align-items: flex-start; flex-direction: column; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="{hero_class}">
      <div class="app-name">Grocery Scout</div>
      <div class="hero-heading">
        <div class="hero-mark" aria-hidden="true">
          <svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M10 14H17L22 40H50L56 22H20" stroke="currentColor" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
            <circle cx="27" cy="51" r="4" fill="currentColor"/>
            <circle cx="47" cy="51" r="4" fill="currentColor"/>
            <path d="M29 30H48" stroke="currentColor" stroke-width="5" stroke-linecap="round"/>
          </svg>
        </div>
        <h1>{escape(hero_title)}</h1>
      </div>
      <p>{escape(hero_copy)}</p>
      {f'<div class="steps">{progress_html}</div>' if progress_html else ''}
    </section>
    <div class="{layout_class}">
      <section class="panel">
        {main_html}
      </section>
      {sidebar_block}
    </div>
  </div>
  <script>
    function useBrowserLocation() {{
      if (!navigator.geolocation) {{
        alert("Location is not available in this browser. Enter a postal code or city instead.");
        return;
      }}
      navigator.geolocation.getCurrentPosition(function(position) {{
        const form = document.createElement("form");
        form.method = "post";
        form.action = "/location";
        [["location", "My current location"], ["lat", position.coords.latitude], ["lng", position.coords.longitude], ["proximity", "nearby"]].forEach(function(pair) {{
          const input = document.createElement("input");
          input.type = "hidden";
          input.name = pair[0];
          input.value = pair[1];
          form.appendChild(input);
        }});
        document.body.appendChild(form);
        form.submit();
      }}, function() {{
        alert("We could not access your location. Enter a postal code or city instead.");
      }}, {{ enableHighAccuracy: false, maximumAge: 300000, timeout: 10000 }});
    }}

    function fillDemoCredentials() {{
      const username = document.getElementById("signin_email");
      const password = document.getElementById("signin_password");
      if (username && password) {{
        username.value = "demo";
        password.value = "smartcart";
        username.focus();
      }}
    }}

    const mapData = window.BRIGHTCART_MAP_DATA;
    if (mapData && document.getElementById("store-map")) {{
      const script = document.createElement("script");
      script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
      script.onload = function() {{
        const map = L.map("store-map").setView([mapData.lat, mapData.lng], 11);
        L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{ maxZoom: 19, attribution: "&copy; OpenStreetMap contributors" }}).addTo(map);
        L.marker([mapData.lat, mapData.lng]).addTo(map).bindPopup("Your selected location");
        mapData.stores.forEach(function(store) {{
          L.marker([store.lat, store.lng]).addTo(map).bindPopup("<strong>" + store.name + "</strong><br>" + store.address + "<br>" + store.distance_km.toFixed(1) + " km");
        }});
      }};
      document.head.appendChild(script);
    }}
  </script>
</body>
</html>"""


def render_auth_main(error: str | None = None) -> str:
    error_html = f'<div class="error">{escape(error)}</div>' if error else ""
    return f"""
      <h2>Register or sign in</h2>
      {error_html}
      <div class="auth-grid">
        <form method="post" action="/register" class="auth-card">
          <h3>Create account</h3>
          <div class="field">
            <label for="register_email">Email address</label>
            <input id="register_email" name="email" type="email" placeholder="name@example.com" required />
          </div>
          <div class="field">
            <label for="register_password">Password</label>
            <input id="register_password" name="password" type="password" placeholder="Create a password" required />
          </div>
          <div class="actions">
            <button class="btn btn-primary" type="submit">Register</button>
          </div>
        </form>
        <form method="post" action="/signin" class="auth-card">
          <h3>Sign in</h3>
          <div class="field">
            <label for="signin_email">Username or email</label>
            <input id="signin_email" name="email" type="text" placeholder="demo or name@example.com" required />
          </div>
          <div class="field">
            <label for="signin_password">Password</label>
            <input id="signin_password" name="password" type="password" placeholder="Your password" required />
          </div>
          <div class="actions">
            <button class="btn btn-primary" type="submit">Sign in</button>
          </div>
          <div class="demo-credentials demo-inline">
            <div>
              <strong>Demo account</strong>
              <span>Username: <code>demo</code> &nbsp; Password: <code>smartcart</code></span>
            </div>
            <button class="btn btn-secondary" type="button" onclick="fillDemoCredentials()">Fill credentials</button>
          </div>
        </form>
      </div>
    """


def render_auth_sidebar() -> str:
    return ""


def render_search_controls(session: dict[str, object], error: str | None = None) -> str:
    error_html = f'<div class="error">{escape(error)}</div>' if error else ""
    current_location = escape(session.get("location_text", "Richmond Hill"))
    current_key = session.get("proximity_key", "nearby")
    options_html = []
    for key, option in PROXIMITY_OPTIONS.items():
        selected = "selected" if key == current_key else ""
        options_html.append(f'<option value="{escape(key)}" {selected}>{escape(option["label"])} - up to {option["radius"]:.0f} km</option>')
    return f"""
      <h2>Location and radius</h2>
      <p class="sub">Optional. Update your current area so nearby store ranking stays relevant.</p>
      {error_html}
      <form method="post" action="/location">
        <div class="field">
          <label for="location">Current location</label>
          <input id="location" name="location" type="text" value="{current_location}" placeholder="L4B 3P8, Richmond Hill, Markham, Toronto..." required />
        </div>
        <div class="field">
          <label for="proximity">Store proximity preference</label>
          <select id="proximity" name="proximity">
            {''.join(options_html)}
          </select>
        </div>
        <div class="actions">
          <button class="btn btn-primary" type="submit">Update location</button>
          <button class="btn btn-secondary" type="button" onclick="useBrowserLocation()">Use my location</button>
        </div>
      </form>
    """


def render_search_sidebar(session: dict[str, object]) -> str:
    account_html = (
        f'<strong>Signed in as</strong><p>{escape(session.get("email", ""))}</p>'
        if session.get("authenticated")
        else '<strong>Browsing as a guest</strong><p>No account needed to search or compare deals.</p>'
    )
    guest_html = "" if session.get("authenticated") else '<div class="guest-note">You can search freely. <a href="/auth">Create an account</a> only if you want to try the demo sign-in flow.</div>'
    return f"""
      <div class="summary-card">
        {account_html}
      </div>
      {guest_html}
      {render_search_controls(session)}
    """


def component_formula(result) -> str:
    discount_part = result.discount_score * 0.45
    distance_part = result.distance_score * 0.30
    substitute_part = result.substitute_score * 0.25
    return (
        f"{result.discount_score:.1f} × 0.45 = {discount_part:.1f}, "
        f"{result.distance_score:.1f} × 0.30 = {distance_part:.1f}, "
        f"{result.substitute_score:.1f} × 0.25 = {substitute_part:.1f}"
    )


def render_result_card(result) -> str:
    deal = result.deal
    store = deal.store
    savings_pct = deal.discount_pct * 100.0
    regular_price = money(deal.regular_price) if deal.regular_price is not None else "No baseline"
    savings_text = pct(savings_pct) if savings_pct > 0 else "0%"
    return f"""
      <article class="deal-card">
        <div class="deal-head">
          <div>
            <p class="deal-kicker">{escape(store.chain)}</p>
            <h3>{escape(deal.product_name)}</h3>
          </div>
          <div class="badge badge-score">Composite {result.total_score:.1f}/100</div>
        </div>
        <div class="price-row">
          <div>
            <span class="price">{escape(money(deal.sale_price))}</span>
            <span class="regular">Original price: {escape(regular_price)} | Savings: {escape(savings_text)}</span>
          </div>
          <div class="badge badge-match">{escape(result.match_type)}</div>
        </div>
        <div class="meta">
          <div class="meta-item">
            <span>Store Name</span>
            <strong>{escape(store.name)}</strong>
          </div>
          <div class="meta-item">
            <span>Distance & Transport Mode</span>
            <strong>{store.distance_km:.1f} km - {escape(result.transport_tier)}</strong>
          </div>
          <div class="meta-item">
            <span>Item Name</span>
            <strong>{escape(deal.product_name)}</strong>
          </div>
          <div class="meta-item">
            <span>Match Type Note</span>
            <strong>{escape(result.match_note)}</strong>
          </div>
        </div>
        <details class="score-breakdown">
          <summary>Why this result?</summary>
          <div class="score-grid">
            <div class="score-cell">
              <span>Discount Score</span>
              <strong>{result.discount_score:.1f}/100</strong>
            </div>
            <div class="score-cell">
              <span>Distance Score</span>
              <strong>{result.distance_score:.1f}/100</strong>
            </div>
            <div class="score-cell">
              <span>Substitute Score</span>
              <strong>{result.substitute_score:.1f}/100</strong>
            </div>
          </div>
          <p class="formula">
            Composite Score = (DiscountScore × 0.45) + (DistanceScore × 0.30) + (SubstituteScore × 0.25)<br />
            {escape(component_formula(result))}<br />
            Final score: <strong>{result.total_score:.1f}/100</strong>
          </p>
        </details>
      </article>
    """


def render_search_main(session: dict[str, object], context: dict[str, object], query: str) -> str:
    results = context["results"]
    effective_query = context["effective_query"]
    location_label = context["location_label"]
    proximity_key = context["proximity_key"]
    proximity = proximity_summary(proximity_key)
    top_result = results[0] if results else None

    query_value = escape(query)
    fallback_notice = ""
    if effective_query != query:
        fallback_notice = f"""
          <div class="notice">
            No direct match for <strong>{escape(query)}</strong>. The search broadened to
            <strong>{escape(effective_query)}</strong> so the app could still surface useful substitutes.
          </div>
        """

    results_html = "".join(render_result_card(result) for result in results[:8]) or """
      <div class="empty-state">
        <h3>No suitable matches yet.</h3>
        <p>Try a broader grocery term like butter, milk, chicken, apples, or vegetables.</p>
      </div>
    """

    store_list = "".join(
        f"""
        <div class="store-chip">
          <div>
            <strong>{escape(store.name)}</strong>
            <p>{escape(store.chain)} - {escape(store.address)}</p>
          </div>
          <span>{store.distance_km:.1f} km</span>
        </div>
        """
        for store in context["stores"][:6]
    )

    main_html = f"""
      <h2>Search grocery deals</h2>
      <p class="sub">
        Ranked results use your location in {escape(location_label)} and a proximity preference of
        {escape(proximity["label"])}.
      </p>
      <form method="get" action="/search">
        <div class="field">
          <label for="q">What are you looking for?</label>
          <input id="q" name="q" type="search" value="{query_value}" placeholder="Try eggs, milk, coffee, or chicken" autofocus />
        </div>
        <div class="actions">
          <button class="btn btn-primary" type="submit">Compare prices</button>
        </div>
      </form>
      <div class="quick-searches" aria-label="Popular searches">
        <span>Popular:</span>
        <a href="/search?q=eggs">Eggs</a>
        <a href="/search?q=milk">Milk</a>
        <a href="/search?q=coffee">Coffee</a>
        <a href="/search?q=chicken">Chicken</a>
      </div>
      {fallback_notice}
      <div class="stats">
        <div class="stat">
          <strong>{len(results)}</strong>
          <span>Ranked matches inside your chosen radius</span>
        </div>
        <div class="stat">
          <strong>{escape(location_label)}</strong>
          <span>Current location used for distance scoring</span>
        </div>
        <div class="stat">
          <strong>{escape(proximity["label"])}</strong>
          <span>Search radius up to {proximity["radius"]:.0f} km</span>
        </div>
      </div>
      <div class="map-panel"><div id="store-map" aria-label="Map of nearby grocery stores"></div></div>
      <p class="map-attribution">Map data © OpenStreetMap contributors. Location is used only for this search session.</p>
      <script>window.BRIGHTCART_MAP_DATA = {json.dumps({"lat": float(session["lat"]), "lng": float(session["lng"]), "stores": [{"name": store.name, "address": store.address, "lat": store.lat, "lng": store.lng, "distance_km": store.distance_km or 0.0} for store in context["stores"][:12]]})};</script>
      <div class="results" style="margin-top:18px;">
        {results_html}
      </div>
    """

    sidebar_html = f"""
      <div class="summary-card">
        <strong>Signed in as</strong>
        <p>{escape(session.get("email", ""))}</p>
      </div>
      {render_search_controls(session)}
      <h2 style="margin-top:20px;">Closest stores</h2>
      <p class="sub">Sorted by straight-line distance from the selected location.</p>
      <div class="sidebar-list">
        {store_list}
      </div>
      <p class="footer-note">
        Top result: {escape(top_result.deal.product_name if top_result else "No result yet")}<br />
        Store: {escape(top_result.deal.store.name if top_result else "n/a")}<br />
        Match family: {escape(context["query_family"] or "general")}
      </p>
    """
    return render_shell("Grocery Scout | Grocery deal finder", "search", main_html, sidebar_html)


def render_register_page(error: str | None = None) -> str:
    return render_shell("Grocery Scout | Register or sign in", "auth", render_auth_main(error), render_auth_sidebar())


def render_search_page(session: dict[str, object], query: str) -> str:
    context = build_context(query, session)
    return render_search_main(session, context, query)


class GroceryHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            send_html(self, '{"status":"ok"}', status=200)
            return
        if parsed.path in {"", "/"}:
            redirect(self, "/auth")
            return

        session_id, session = get_session(self)
        if parsed.path == "/auth":
            if session and session.get("authenticated"):
                redirect(self, "/search")
                return
            send_html(self, render_register_page())
            return

        if parsed.path == "/search":
            if not session:
                session_id, session = ensure_session(self)
            else:
                session_id = session_id
            params = parse_qs(parsed.query)
            query = params.get("q", [session.get("last_query", "butter")])[0].strip() or "butter"
            session["last_query"] = query
            send_html(self, render_search_page(session, query), cookie_value=session_id)
            return

        send_html(self, render_register_page("Unknown page. Use /auth or /search."), status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        form = read_form(self)

        session_id, session = ensure_session(self)
        if parsed.path == "/register":
            email = form.get("email", "").strip()
            password = form.get("password", "").strip()
            if not email or not password:
                send_html(self, render_register_page("Email and password are required."))
                return
            if email in USER_STORE:
                send_html(self, render_register_page("That email already exists. Use sign in instead."))
                return

            USER_STORE[email] = password_digest(password)
            session["authenticated"] = True
            session["email"] = email
            redirect(self, "/search", cookie_value=session_id)
            return

        if parsed.path == "/signin":
            email = form.get("email", "").strip()
            password = form.get("password", "").strip()
            if not email or not password:
                send_html(self, render_register_page("Email and password are required."))
                return

            stored_password = USER_STORE.get(email)
            if stored_password is None:
                send_html(self, render_register_page("No account found for that email."))
                return
            if not password_matches(password, stored_password):
                send_html(self, render_register_page("Incorrect password."))
                return

            session["authenticated"] = True
            session["email"] = email
            redirect(self, "/search", cookie_value=session_id)
            return

        if parsed.path == "/location":
            location_text = form.get("location", "").strip()
            proximity_key = form.get("proximity", "nearby").strip()
            if not location_text:
                send_html(self, render_search_page(session, session.get("last_query", "butter")), status=200)
                return
            if proximity_key not in PROXIMITY_OPTIONS:
                proximity_key = "nearby"

            try:
                lat = float(form["lat"])
                lng = float(form["lng"])
                if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                    raise ValueError
                label = "Current browser location"
            except (KeyError, TypeError, ValueError):
                lat, lng, label = mock_geocode_location(location_text)
            session["location_text"] = location_text
            session["lat"] = lat
            session["lng"] = lng
            session["location_label"] = label
            session["proximity_key"] = proximity_key
            session["max_distance_km"] = PROXIMITY_OPTIONS[proximity_key]["radius"]
            session["last_query"] = session.get("last_query", "butter")
            redirect(self, "/search", cookie_value=session_id)
            return

        send_html(self, render_register_page("Unsupported form submission."), status=404)

    def log_message(self, format, *args):  # noqa: A003
        return


def main() -> None:
    server = HTTPServer((HOST, PORT), GroceryHandler)
    url = f"http://{HOST}:{PORT}/"
    print(f"Serving Grocery Scout on {url}")
    print("Register or sign in first, then search items like: butter, milk, chicken breast, apples")
    if os.environ.get("APP_ENV") != "production":
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
