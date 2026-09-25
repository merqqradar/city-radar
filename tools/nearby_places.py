# -*- coding: utf-8 -*-
"""Підбір населених пунктів навколо вашого міста (OpenStreetMap).

    python3 tools/nearby_places.py "Назва міста" [--radius 45] [--country ua]
    python3 tools/nearby_places.py --lat 50.0 --lon 36.0 --radius 45

Що робить: знаходить координати міста (Nominatim), просить в Overpass API усі
міста, селища й села в радіусі, і виводить таблицю: назва українською та
російською, тип, відстань, напрям. Результат також пишеться в
data/nearby.json — з нього зручно складати CLOSE / NEAR / FAR у
region_profile.py.

Цей скрипт лише ПІДКАЗУЄ кандидатів. Корені й рішення «ближнє коло чи ні»
за вами (або за Claude Code): дивіться SETUP_WITH_CLAUDE_CODE.md.

Потрібен інтернет. Дані © учасники OpenStreetMap (ODbL). Запити рідкі,
у межах правил публічних серверів — не запускайте скрипт у циклі.
"""

import argparse
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

UA = "CityRadar-setup/1.0 (одноразове налаштування профілю)"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
OVERPASS = "https://overpass-api.de/api/interpreter"


def _get(url: str, data: bytes | None = None) -> dict:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8"))


def geocode(name: str, country: str) -> tuple:
    query = urllib.parse.urlencode({
        "q": name, "format": "json", "limit": 3, "countrycodes": country,
        "accept-language": "uk"})
    rows = _get(f"{NOMINATIM}?{query}")
    if not rows:
        raise SystemExit(f"Не знайдено «{name}». Спробуйте --lat/--lon.")
    for row in rows:
        print(f"  знайдено: {row.get('display_name')}")
    first = rows[0]
    return float(first["lat"]), float(first["lon"])


def distance_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def bearing(lat1, lon1, lat2, lon2) -> str:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    deg = (math.degrees(math.atan2(x, y)) + 360) % 360
    names = ["пн", "пн-сх", "сх", "пд-сх", "пд", "пд-зх", "зх", "пн-зх"]
    return names[int((deg + 22.5) // 45) % 8]


def guess_roots(name: str) -> list:
    """Грубий здогад кореня: без закінчення. ЗАВЖДИ перевіряйте вручну."""
    low = name.lower().replace("’", "'").replace("ʼ", "'")
    for ending in ("івка", "овка", "івці", "ка", "ці", "ове", "ово", "яр",
                   "е", "а", "я", "о", "и", "ь"):
        if low.endswith(ending) and len(low) - len(ending) >= 4:
            return [low[:len(low) - len(ending) + (2 if ending in ("івка", "овка") else 0)]]
    return [low]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("city", nargs="?", help="назва міста")
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--radius", type=float, default=45, help="км, до 80")
    ap.add_argument("--country", default="ua")
    args = ap.parse_args()
    if args.lat is None or args.lon is None:
        if not args.city:
            ap.error("вкажіть назву міста або --lat і --lon")
        lat, lon = geocode(args.city, args.country)
        time.sleep(1)                      # ввічливість до публічного сервера
    else:
        lat, lon = args.lat, args.lon
    radius = min(args.radius, 80) * 1000
    print(f"центр: {lat:.4f}, {lon:.4f}; радіус {radius / 1000:.0f} км")

    overpass_q = (f'[out:json][timeout:60];(node["place"~"^(city|town|village|'
                  f'hamlet|suburb)$"](around:{int(radius)},{lat},{lon}););out tags center;')
    data = _get(OVERPASS, urllib.parse.urlencode({"data": overpass_q}).encode())
    rows = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        name = tags.get("name:uk") or tags.get("name")
        if not name:
            continue
        rows.append({
            "name_uk": name,
            "name_ru": tags.get("name:ru", ""),
            "type": tags.get("place", ""),
            "population": tags.get("population", ""),
            "km": round(distance_km(lat, lon, el["lat"], el["lon"]), 1),
            "dir": bearing(lat, lon, el["lat"], el["lon"]),
            "root_guess": guess_roots(name),
        })
    rows.sort(key=lambda r: r["km"])
    print(f"\n{'км':>5} {'напрям':<6} {'тип':<8} назва (укр / рос)")
    for r in rows:
        ru = f" / {r['name_ru']}" if r["name_ru"] and r["name_ru"] != r["name_uk"] else ""
        print(f"{r['km']:5.1f} {r['dir']:<6} {r['type']:<8} {r['name_uk']}{ru}")
    Path("data").mkdir(exist_ok=True)
    Path("data/nearby.json").write_text(
        json.dumps({"center": [lat, lon], "radius_km": radius / 1000, "places": rows},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nзбережено: data/nearby.json ({len(rows)} пунктів). "
          "Пам'ятайте: одна назва може повторюватись в інших областях.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
