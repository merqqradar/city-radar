# -*- coding: utf-8 -*-
"""Які населені пункти канали згадують РАЗОМ з вашим містом — кандидати в CLOSE/NEAR.

    python3 tools/find_neighbors.py [--top 60]

Читає data/dump_*.json (див. dump_history.py або tools/collect_public.py),
знаходить повідомлення, де названо ваше місто, і рахує слова з великої
літери після «на / над / від / через / до / повз / курсом на». Найчастіші —
саме ті пункти, через які літак чи дрон іде на ваше місто.

Скрипт лише ПІДКАЗУЄ. Перевірте кожного кандидата на карті (tools/nearby_places.py
дає відстань і напрям), відкиньте тезок з інших областей і складіть корені за
правилами з region_profile.py. Потім `python3 region_check.py`.
"""

import argparse
import glob
import json
import re
from collections import Counter

import geo

PREP = re.compile(
    r"(?:курсом на|напрямку|повз|через|над|від|от|до|на|в районі|в районе)\s+"
    r"([А-ЯІЇЄҐ][а-яіїєґ'’ʼ\-]{3,}(?:\s+[А-ЯІЇЄҐ][а-яіїєґ'’ʼ\-]{3,})?)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=60)
    args = ap.parse_args()
    if not geo.CITIES.main:
        raise SystemExit("Спершу задайте місто (city_main_name / city_main_variants).")

    texts = []
    for path in glob.glob("data/dump_*.json"):
        try:
            texts += [m["text"] for m in json.load(open(path, encoding="utf-8"))]
        except (OSError, ValueError, KeyError):
            continue
    if not texts:
        raise SystemExit("Немає data/dump_*.json — зробіть dump_history.py або tools/collect_public.py.")

    with_city = [t for t in texts if geo.find_main(t.lower())]
    print(f"повідомлень: {len(texts)}, з вашим містом: {len(with_city)}")
    if not with_city:
        raise SystemExit("Про ваше місто в історії нічого немає — перевірте варіанти написання "
                         "міста або додайте канали.")

    counter = Counter()
    for text in with_city:
        for match in PREP.finditer(text):
            word = match.group(1).strip()
            if geo.find_main(word.lower()):
                continue
            counter[word] += 1
    print(f"\n{'разів':>5}  кандидат (перевірте на карті!)")
    for word, n in counter.most_common(args.top):
        print(f"{n:5}  {word}")
    print("\nПам'ятайте: форма слова залежить від відмінка («на Соснівку» / «над Соснівкою»); "
          "у профіль йде КОРІНЬ («соснівк»).")


if __name__ == "__main__":
    main()
