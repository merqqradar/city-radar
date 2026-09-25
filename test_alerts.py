# -*- coding: utf-8 -*-
"""Проверки ЛОГИКИ монитора: звук, повтори, налёт, ручне зняття, «покинули область».

    python3 test_alerts.py            # з вашим містом
    python3 test_alerts.py --sample   # з вигаданим профілем

Працює повністю в ізоляції: стан — у тимчасовій папці, відправка в Telegram
підмінена. Нічого нікуди не надсилає. Запускайте після будь-якої правки
monitor.py — тут ловляться помилки, які класифікатор (final_check.py) не бачить:
наприклад, коли справжня загроза приходить без звуку.
"""

import asyncio
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

if "--sample" in sys.argv:
    import sample_profile
    sample_profile.apply()

import config
import geo
import monitor
import notify

config.HIGH_INCLUDES_NEIGHBORS = True
TMP = Path(tempfile.mkdtemp())
for _n in ("STATE_FILE", "ALARM_FILE", "DAILY_FILE", "ACTIVE_THREAT_FILE",
           "PREV_FILE"):
    setattr(monitor, _n, TMP / (_n.lower() + ".json"))

SENT = []
notify.send = lambda text, silent=False: (
    SENT.append((text.split("\n")[0][:70], silent)) or (True, "ok"))
notify.send_to = lambda *a, **k: (True, "ok")

CITY = geo.main_name()
failures = []


def fresh():
    for f in TMP.glob("*.json"):
        f.unlink()
    radar = monitor.Radar()
    radar.dedup = monitor.Dedup(0)
    SENT.clear()
    return radar


async def go(radar, channel, msg_id, text, shift=0):
    when = datetime.now().astimezone() + timedelta(seconds=shift)
    await radar._ingest(channel, msg_id, when, text, None)
    radar.recent_sent = {}


def check(name, cond):
    print(f"  {'OK ' if cond else 'FAIL'} {name}")
    if not cond:
        failures.append(name)


async def main():
    print("1. ЗВУК ЛИШЕ КОЛИ ТРЕБА")
    r = fresh()
    await go(r, "a", 1, f"Розвідувальний БпЛА над {CITY}")
    check("розвідник над містом — тихо", SENT and SENT[-1][1] is True)
    SENT.clear()
    await go(r, "b", 2, f"Реактивный шахед на {CITY}")
    check("справжній HIGH ПІСЛЯ тихого MEDIUM — ЗІ ЗВУКОМ", SENT and SENT[0][1] is False)
    SENT.clear()
    await go(r, "c", 3, f"Далее курс на {CITY}, шахед")
    await go(r, "d", 4, f"Шахед на {CITY}")
    check("наступні про те саме місце (наліт) — тихо",
          SENT and all(s for _, s in SENT))
    SENT.clear()
    await go(r, "e", 5, f"Бандероль на {CITY}‼️")
    check("новий важкий тип — знову зі звуком", any(not s for _, s in SENT))

    print("2. СЕРІЇ ПОВТОРІВ")
    r = fresh()
    await go(r, "a", 1, f"3 шахеди на {CITY}")
    check("явне «3» — серія повторів запущена", r.critical is not None)
    r.critical = None
    await go(r, "b", 2, f"4 шахеди на {CITY}")
    check("друга серія в межах 15 хв не стартує", r.critical is None)
    await go(r, "c", 3, f"Ракета на {CITY}‼️")
    check("нова ракета — серія знову", r.critical is not None)
    r = fresh()
    await go(r, "a", 1, f"Шахед на {CITY}")
    check("один шахед без цифри — БЕЗ серії повторів", r.critical is None)

    print("3. РУЧНЕ ЗНЯТТЯ")
    r = fresh()
    await go(r, "a", 1, f"Шахед курсом на {CITY}")
    msg = await r.cancel_alarm("тест")
    check("тривогу знято", r.active_threat is None and "знято" in msg.lower())
    check("у чаті немає слова «хибна» (зняття ≠ помилка)",
          not any("хибн" in t.lower() for t, _ in SENT))
    SENT.clear()
    await go(r, "b", 2, f"Реактивный шахед на {CITY}")
    check("те саме місце після зняття — тихо", SENT and all(s for _, s in SENT))
    SENT.clear()
    await go(r, "c", 3, f"Ракета на {CITY}‼️")
    check("ракета після зняття — знову зі звуком", any(not s for _, s in SENT))

    print("4. «ЦІЛЬ ПОКИНУЛА ОБЛАСТЬ»")
    r = fresh()
    await go(r, "a", 1, f"Бандероль на {CITY}‼️")
    SENT.clear()
    await r._ingest("b", 2, datetime.now().astimezone() + timedelta(seconds=5),
                    "Бандероли покидают нашу области в соседние области, по "
                    "баллистике угроза сохраняется, для нашей без фиксации.", None)
    check("бандероль знято", r.active_threat is None)
    check("повідомлення «минула» — без звуку",
          any("МИНУЛА" in t.upper() and s for t, s in SENT))
    r = fresh()
    await go(r, "a", 1, f"Шахед курсом на {CITY}")
    await r._ingest("b", 2, datetime.now().astimezone() + timedelta(seconds=5),
                    "Бандероли покидают нашу области в соседние области", None)
    check("шахед НЕ знято повідомленням про бандероли", r.active_threat is not None)

    print("\n" + "=" * 60)
    if failures:
        print("ПРОБЛЕМИ:", ", ".join(failures))
        return 1
    print("УСЕ В ПОРЯДКУ")
    return 0


if __name__ == "__main__":
    code = asyncio.run(main())
    shutil.rmtree(TMP, ignore_errors=True)
    raise SystemExit(code)
