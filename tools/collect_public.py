# -*- coding: utf-8 -*-
"""Збирає історію публічних каналів БЕЗ Telegram-акаунта і без файлу сесії.

    python3 tools/collect_public.py              # один знімок усіх каналів
    python3 tools/collect_public.py --loop 30    # знімок кожні 30 хв (Ctrl+C — зупинити)

Публічна сторінка t.me/s/<канал> віддає лише ~20 останніх повідомлень, тож
історію за 30 днів так не отримати миттєво — вона накопичується. Скрипт
дописує нові повідомлення в data/dump_<канал>.json (той самий формат, що
робить dump_history.py) і не дублює вже збережені. Залиште `--loop` на
кілька діб — і `region_check.py`, `backtest.py`, `final_check.py` матимуть
реальні дані для калібрування.

Якщо у вас є акаунт Telegram, швидше зробити `python3 auth.py` і
`python3 dump_history.py` — це дає 30 днів одразу.
"""

import argparse
import asyncio
import json
import time
from pathlib import Path

import config
import public_source


async def snapshot() -> int:
    client = public_source.PublicClient()
    added = 0
    for channel in config.CHANNELS:
        path = Path(config.DATA_DIR) / f"dump_{channel}.json"
        old = []
        if path.exists():
            try:
                old = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                old = []
        seen = {m["id"] for m in old}
        fresh = []
        try:
            async for msg in client.iter_messages(channel, limit=25):
                if msg.text and msg.id not in seen:
                    fresh.append({"id": msg.id,
                                  "date": msg.date.isoformat(),
                                  "text": msg.text,
                                  "link": f"https://t.me/{channel}/{msg.id}"})
        except Exception as exc:                          # noqa: BLE001
            print(f"  {channel}: помилка {type(exc).__name__}: {exc}")
            continue
        if fresh:
            merged = sorted(old + fresh, key=lambda m: m["date"])
            path.write_text(json.dumps(merged, ensure_ascii=False),
                            encoding="utf-8")
        print(f"  {channel:<24} нових {len(fresh):3}  усього {len(old) + len(fresh)}")
        added += len(fresh)
    try:
        await client.close()
    except Exception:                                     # noqa: BLE001
        pass
    return added


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=int, default=0, help="повторювати кожні N хвилин")
    args = ap.parse_args()
    if not config.CHANNELS:
        raise SystemExit("Список каналів порожній: додайте channels у data/settings.json.")
    while True:
        print(time.strftime("%Y-%m-%d %H:%M:%S"), "— знімок")
        total = asyncio.run(snapshot())
        print(f"  додано {total} повідомлень")
        if not args.loop:
            break
        time.sleep(args.loop * 60)


if __name__ == "__main__":
    main()
