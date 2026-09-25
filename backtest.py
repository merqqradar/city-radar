# -*- coding: utf-8 -*-
"""Прогон фильтра по исторической выгрузке — без единого запроса в Telegram.

Показывает, сколько уведомлений система прислала бы за 30 дней,
как работает дедупликация и что именно попало бы в каждый уровень.
Это способ проверить фильтр ДО включения его в реальном времени.

Запуск:  python backtest.py           — сводка
         python backtest.py --high    — плюс все HIGH-уведомления целиком
"""

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime

import classify
import config

DEDUP_WINDOW_MIN = 12          # окно склейки дублей, минуты


def main() -> None:
    show_high = "--high" in sys.argv

    msgs = []
    for path in sorted(config.DATA_DIR.glob("dump_*.json")):
        channel = path.stem[len("dump_"):]
        for m in json.loads(path.read_text(encoding="utf-8")):
            m["channel"] = channel
            msgs.append(m)
    if not msgs:
        raise SystemExit("Нет выгрузок. Сначала: python dump_history.py")
    msgs.sort(key=lambda m: m["date"])

    matched, sent = [], []
    last_seen = {}                  # ключ дедупликации -> время последней отправки
    dropped = 0

    for m in msgs:
        res = classify.classify(m["text"])
        if not res:
            continue
        res["date"] = m["date"]
        res["channel"] = m["channel"]
        res["link"] = m["link"]
        matched.append(res)

        when = datetime.fromisoformat(m["date"])
        prev = last_seen.get(res["key"])
        if prev and (when - prev).total_seconds() < DEDUP_WINDOW_MIN * 60:
            dropped += 1                       # дубль из другого канала
            continue
        last_seen[res["key"]] = when
        sent.append(res)

    days = len({m["date"][:10] for m in msgs}) or 1

    print(f"Просмотрено сообщений: {len(msgs)} за {days} суток")
    print(f"Прошло фильтр:         {len(matched)}")
    print(f"Отброшено как дубли:   {dropped}")
    print(f"Было бы отправлено:    {len(sent)}  (~{len(sent)/days:.1f} в сутки)")
    print()

    by_level = Counter(r["level"] for r in sent)
    print(f"{'УРОВЕНЬ':<8}{'ВСЕГО':>7}{'В СУТКИ':>10}")
    for lvl in ("HIGH", "MEDIUM", "LOW", "INFO"):
        n = by_level.get(lvl, 0)
        print(f"{lvl:<8}{n:>7}{n / days:>10.1f}")
    print()

    print("Причины срабатывания:")
    for reason, n in Counter(r["reason"] for r in sent).most_common():
        print(f"  {n:>5}  {reason}")
    print()

    print("Источники (после дедупликации — кто успел первым):")
    for ch, n in Counter(r["channel"] for r in sent).most_common():
        print(f"  {n:>5}  {ch}")
    print()

    print("Типы угроз в отправленном:")
    tc = Counter(t for r in sent for t, _ in r["threats"])
    for t, n in tc.most_common():
        print(f"  {n:>5}  {t}")
    print()

    # Самые загруженные сутки — сколько раз телефон зазвонил бы в худший день
    per_day = defaultdict(Counter)
    for r in sent:
        per_day[r["date"][:10]][r["level"]] += 1
    worst = sorted(per_day.items(), key=lambda kv: -kv[1]["HIGH"])[:5]
    print("Худшие сутки по числу HIGH:")
    for day, c in worst:
        print(f"  {day}: HIGH {c['HIGH']}, MEDIUM {c['MEDIUM']}, LOW {c['LOW']}")

    if show_high:
        print("\n" + "=" * 78)
        print("ВСЕ HIGH-УВЕДОМЛЕНИЯ")
        print("=" * 78)
        for r in sent:
            if r["level"] != "HIGH":
                continue
            th = ", ".join(t for t, _ in r["threats"]) or "тип не вказано"
            print(f"\n[{r['date'][:16].replace('T', ' ')}] {r['channel']} · "
                  f"{r['reason']} · {th}")
            print(f"  {r['text'][:200]}")


if __name__ == "__main__":
    main()
