# -*- coding: utf-8 -*-
"""Перевірка регіонального профілю: що заповнено і де можливі хибні спрацьовування.

    python3 region_check.py            # ваш профіль
    python3 region_check.py --sample   # вигаданий (перевірка самого рушія)

Що робить:
  1. показує, що задано (місто, район, область, села, канали);
  2. ловить типові помилки в коренях: занадто короткі, однакові у різних
     пунктів, один корінь є початком іншого;
  3. самоперевірка: для міста й кожного села складає повідомлення
     «Шахед на <назва>» і дивиться, що вирішить радар;
  4. якщо є історія каналів (data/dump_*.json) — рахує, у скількох
     повідомленнях кожен корінь спрацьовує, і показує приклади для
     підозрілих. Так знаходяться корені, що збігаються зі звичайними словами.

Нічого нікуди не надсилає.
"""

import glob
import json
import sys
from collections import Counter

if "--sample" in sys.argv:
    import sample_profile
    sample_profile.apply()

import classify
import config
import geo
import region_profile

MIN_ROOT = 5


def _all_roots():
    """[(розділ, назва, корінь)] з усього профілю."""
    out = []
    for name, roots in region_profile.CLOSE.items():
        out += [("CLOSE", name, r) for r in roots]
    for name, (roots, _bad) in region_profile.NEAR.items():
        out += [("NEAR", name, r) for r in roots]
    for name, roots in region_profile.FAR.items():
        out += [("FAR", name, r) for r in roots]
    return out


def _load_dumps():
    msgs = []
    for path in glob.glob("data/dump_*.json") + glob.glob("data/night/*.json"):
        if "settings" in path:
            continue
        try:
            for m in json.load(open(path, encoding="utf-8")):
                msgs.append(m["text"])
        except (OSError, ValueError, KeyError):
            continue
    return msgs


def main() -> int:
    warn, fail = [], []
    print("=== ПРОФІЛЬ ===")
    print(f"джерело      : {region_profile.SOURCE}")
    print(f"місто        : {geo.main_name()!r}  варіантів: {len(geo.CITIES.main)}")
    print(f"район тривоги: {geo.CITIES.district_name!r}  варіантів: {len(geo.CITIES.district)}")
    print(f"область      : коренів {len(region_profile.OBLAST_ROOTS)}, "
          f"окремих слів {len(region_profile.OBLAST_ALONE)}")
    print(f"села         : ближніх {len(region_profile.CLOSE)}, пояс "
          f"{len(region_profile.NEAR)}, дальніх {len(region_profile.FAR)}")
    print(f"канали       : {len(config.CHANNELS)}")

    print("\n=== ПРОБЛЕМИ НАЛАШТУВАННЯ ===")
    problems = config.region_problems()
    for p in problems:
        print("  ✗", p)
        fail.append(p)
    if not problems:
        print("  усе основне заповнено")

    print("\n=== ЯКІСТЬ КОРЕНІВ ===")
    roots = _all_roots()
    for section, name, root in roots:
        if len(root) < MIN_ROOT:
            warn.append(f"{section} «{name}»: корінь «{root}» коротший за {MIN_ROOT} літер — "
                        "ризик збігу зі звичайними словами")
    seen = {}
    for section, name, root in roots:
        if root in seen and seen[root] != name:
            warn.append(f"корінь «{root}» є і в «{seen[root]}», і в «{name}»")
        seen[root] = name
    for _s1, n1, r1 in roots:
        for _s2, n2, r2 in roots:
            if n1 != n2 and r1 != r2 and r2.startswith(r1):
                warn.append(f"корінь «{r1}» («{n1}») є початком «{r2}» («{n2}») — "
                            f"«{n1}» спрацює і на «{n2}»")
    for w in sorted(set(warn)):
        print("  !", w)
    if not warn:
        print("  зауважень немає")

    print("\n=== САМОПЕРЕВІРКА ===")
    main_name = geo.main_name()
    cases = [(f"Шахед на {main_name}", "HIGH")]
    for name in region_profile.CLOSE:
        cases.append((f"Шахед на {name}", None))          # HIGH або MEDIUM
    for name in region_profile.NEAR:
        cases.append((f"Шахед курсом на {name}", None))
    bad = 0
    for text, want in cases:
        res = classify.classify(text)
        got = res["level"] if res else None
        ok = (got == want) if want else got is not None
        print(f"  {'✓' if ok else '✗'} {text:<40} -> {got}")
        bad += (not ok)
    if bad:
        fail.append(f"{bad} самоперевірок не пройдено")

    dumps = _load_dumps()
    print(f"\n=== ІСТОРІЯ КАНАЛІВ ({len(dumps)} повідомлень) ===")
    if not dumps:
        print("  немає data/dump_*.json — пропускаю. Зробіть `python3 dump_history.py`.")
    else:
        hits, samples = Counter(), {}
        for text in dumps:
            low = text.lower()
            for _s, name, root in roots:
                if geo._has(low, [root]):
                    hits[name] += 1
                    samples.setdefault(name, []).append(text[:110].replace("\n", " "))
        for name, n in hits.most_common(15):
            print(f"  {name:<18} {n:5} повідомлень")
        rare = [n for _s, n, _r in roots if hits[n] == 0]
        if rare:
            print("  жодного збігу:", ", ".join(sorted(set(rare))),
                  "— перевірте написання")
        loud = [(n, c) for n, c in hits.items()
                if c > max(40, len(dumps) // 25)]
        for name, c in loud:
            print(f"\n  ⚠ «{name}» спрацьовує в {c} повідомленнях — надто часто. "
                  "Приклади (чи це справді ваше село?):")
            for s in samples[name][:4]:
                print("     ·", s)

    print("\n" + "=" * 60)
    if fail:
        print("Є проблеми, які треба виправити:", len(fail))
        return 1
    print("Профіль виглядає робочим." + (f" Зауважень: {len(set(warn))}." if warn else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
