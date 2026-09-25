# -*- coding: utf-8 -*-
"""Фінальна перевірка системи. Запускати після будь-якої правки.

    python3 final_check.py            # з вашим профілем і налаштуваннями
    python3 final_check.py --sample   # з вигаданим профілем (перевірка самого рушія)

Перевіряє: модулі, налаштування, класифікацію на контрольних випадках
(вони складаються з НАЗВИ ВАШОГО МІСТА, тож працюють для будь-якого міста),
захист від хибних тривог, прогін по історії каналів (якщо є дамп),
зв'язок з Telegram, збірку інтерфейсу й резервну копію.

Нічого нікуди не надсилає, крім двох read-only запитів до Bot API (лише
якщо задано BOT_TOKEN і TARGET_CHAT_ID, і не з --sample).
"""

import glob
import json
import os
import sys
import tempfile
from collections import Counter
from datetime import datetime

SAMPLE = "--sample" in sys.argv
if SAMPLE:
    import sample_profile
    sample_profile.apply()

fails, warns = [], []


def check(name, cond, detail=""):
    print(f"  {'OK ' if cond else 'FAIL'} {name}{(' — ' + detail) if detail else ''}")
    if not cond:
        fails.append(name)


def main() -> int:
    print("=== 1. МОДУЛІ ===")
    import backup, classify, config, geo, monitor, notify, reader, settings
    import status, threats
    check("усі модулі імпортуються", True)
    main_name = geo.main_name()
    check("місто береться з налаштувань", bool(geo.CITIES.main),
          main_name if geo.CITIES.main else "порожньо — див. region_check.py")
    if not geo.CITIES.main:
        print("\nМісто не задано — далі перевіряти нічого. Заповніть налаштування")
        print("(див. README.md) або запустіть з --sample.")
        return 1

    print("\n=== 2. НАЛАШТУВАННЯ ===")
    saved = settings.load()
    check("усі ключі на місці", set(settings.DEFAULTS) <= set(saved),
          f"{len(saved)} ключів")
    problems = config.region_problems()
    for p in problems:
        print("  ⚠", p)
        warns.append(p)
    check("для всіх перевірених налаштувань є підказки",
          all(k in settings.HELP for k in ("critical_enabled", "channels",
                                            "dedup_window_min", "raid_calm",
                                            "smart_read", "report_clear")))

    print("\n=== 3. КЛАСИФІКАЦІЯ (на назві вашого міста) ===")
    district = geo.CITIES.district_name or "Тестоградський район"
    cases = [
        (f"Реактивный шахед на {main_name}", "HIGH", False),
        (f"Далее курс на {main_name}", "HIGH", False),
        (f"5 ракет на {main_name}", "HIGH", True),
        (f"Розвідувальний БпЛА над {main_name}", "MEDIUM", False),
        ("✋ Звуки наши", "INFO", False),
        ("Шахед на Нікудищево", None, False),
    ]
    for text, want_level, want_mass in cases:
        res = classify.classify(text)
        got = res["level"] if res else None
        mass = bool(res and res.get("mass_reason"))
        ok = got == want_level and mass == want_mass
        check(f"{text[:44]:<44} -> {got}", ok,
              "" if ok else f"очікувалось {want_level}, повтори={want_mass}")

    print("\n=== 3б. РОЗУМНЕ ЧИТАННЯ ПОВІДОМЛЕНЬ ===")
    deep = [
        ("кількість — лише з явної цифри: «3 шахеди»",
         classify.classify(f"3 шахеди на {main_name}")["count"] == 3),
        ("«на місто» без цифри в списку — не масова загроза",
         classify.classify(
             f"❗⚠️Область.\nШахеди:\n⚠️на Нікудищево\n⚠️на {main_name}\n"
             f"⚠️2 на Нікуди")["count"] < 3),
        ("заголовок «в області 3», а на місто одна цифра 1 — не масова",
         classify.classify(
             f"Наразі в області 3 шахеди:\n▪️1 на Нікудищево\n▪️1 на {main_name}\n"
             f"▪️1 на Нікуди")["count"] < 3),
        ("ціль ВІД міста не будить гучно",
         classify.classify(f"Шахед від {main_name} на Нікудищево")["level"] != "HIGH"),
        ("ціль НА місто — гучно",
         classify.classify(f"Шахед від Нікудищево на {main_name}")["level"] == "HIGH"),
        ("новина про удар по території рф — не тривога",
         classify.classify("⚡️СБУ вночі вдарили по базі рф у Новоросійську: "
                           "«Калібри», термінал") is None),
        ("добове зведення не дає ГУЧНОЇ тривоги",
         (classify.classify(
             f"❗️Протягом минулої доби ворожих ударів зазнали 10 населених "
             f"пунктів області. Ворог атакував ракетами {main_name}.")
          or {"level": None})["level"] != "HIGH"),
        ("корінь шукається лише на початку слова («дар» ≠ «Кордар»)",
         geo._has("кордар", ["дар"]) is False and geo._has("дарівка", ["дар"])),
        ("«чистоводовка» не читається як «чисто»",
         not threats.is_calm("ціль на чистоводовку")),
        ("«бандероли покидають область» — тихо знімає бандероль, не балістику",
         classify.left_matches(classify.threat_left(
             "Бандероли покидают нашу области в соседние области, по "
             "баллистике угроза сохраняется, для нашей без фиксации."), "Бандероль")
         and not classify.left_matches(classify.threat_left(
             "Бандероли покидают нашу области в соседние области, по "
             "баллистике угроза сохраняется, для нашей без фиксации."), "Балістика")),
        ("тип «Молния»/«Ударный» розпізнається",
         [n for n, _ in threats.detect_threats("молния, ударный на село")]
         == ["Молния", "БпЛА"]),
        ("пояснення вибуху: розмінування",
         classify.explain_boom("У районі проводили планове розмінування")
         is not None),
        ("зведення по області розпізнається",
         bool(reader.area_report("По області:\n▪️БпЛА на Нікудищево\n"
                                 "▪️Шахед на Нікуди"))),
    ]
    for name, cond in deep:
        check(name, cond)

    print("\n=== 4. ЗАХИСТ ВІД ХИБНИХ ТРИВОГ ===")
    check("оголошення «жовтий рівень» — не окрема ціль",
          classify.classify(
              f"{district} — повітряна тривога, жовтий рівень: Дронова загроза "
              f"(жовтий рівень)") is None)
    if geo.CITIES.district:
        check("тривога по вашому району розпізнається",
              classify.alarm_state(f"🔴 {district} - повітряна тривога!")
              == ("on", "Повітряна тривога"))
        check("відбій вашого району розпізнається",
              classify.alarm_state(f"🟢 {district} - відбій повітряної тривоги!")
              == ("off", None))
    check("відбій чужого району не знімає нашу тривогу",
          classify.alarm_state("🟢 Чужий район - відбій\n"
                               f"🔴 {district} - повітряна тривога!")
          == ("on", "Повітряна тривога") if geo.CITIES.district else True)
    check("робота ППО в Бєлгороді відкидається",
          classify.civil_state("Работа ПВО в Белгороде") is None)
    check("тарифи на воду — не тривога",
          classify.civil_state("Тарифи на воду виростуть") is None)

    print("\n=== 5. ПРОГІН ПО ІСТОРІЇ ===")
    msgs = []
    for path in glob.glob("data/dump_*.json"):
        channel = os.path.basename(path)[len("dump_"):-len(".json")]
        with open(path, encoding="utf-8") as fh:
            for m in json.load(fh):
                m["channel"] = channel
                msgs.append(m)
    if not msgs:
        print("     немає data/dump_*.json — пропускаю (зробіть python3 dump_history.py)")
    else:
        msgs.sort(key=lambda m: m["date"])
        levels, crit, last_seen = Counter(), 0, {}
        for msg in msgs:
            res = classify.classify(msg["text"])
            if not res:
                continue
            when = datetime.fromisoformat(msg["date"])
            prev = last_seen.get(res["key"])
            if prev and (when - prev).total_seconds() < settings.DEFAULTS[
                    "dedup_window_min"] * 60:
                continue                       # дубль з іншого каналу
            last_seen[res["key"]] = when
            levels[res["level"]] += 1
            crit += bool(res.get("mass_reason"))
        days = len({m["date"][:10] for m in msgs}) or 1
        print(f"     {len(msgs)} повідомлень за {days} діб: "
              f"HIGH {levels['HIGH']/days:.1f}/добу · MEDIUM "
              f"{levels['MEDIUM']/days:.1f} · LOW {levels['LOW']/days:.1f}")
        check("гучних не більше 10 на добу", levels["HIGH"] / days < 10,
              f"{levels['HIGH']/days:.1f}")
        check("екстрених не більше 2 на добу", crit / days < 2, f"{crit/days:.1f}")

    print("\n=== 6. TELEGRAM ===")
    if SAMPLE or not (config.BOT_TOKEN and config.TARGET_CHAT_ID):
        print("     пропускаю: немає BOT_TOKEN/TARGET_CHAT_ID (або режим --sample)")
    else:
        ok, res = notify.call("getMe", {})
        check("бот відповідає", ok, "@" + res.get("username", "") if ok else str(res))
        ok, chat = notify.call("getChat", {"chat_id": config.TARGET_CHAT_ID})
        check("канал доступний", ok, chat.get("title", "") if ok else str(chat))

    print("\n=== 7. ІНТЕРФЕЙС (лише macOS) ===")
    try:
        from AppKit import NSApplication
        import gui

        NSApplication.sharedApplication()

        class FakeRadar:
            running = True
            paused = False
            alarm = announced = active_threat = critical = None
            standby = False
            stats = {"seen": 0, "matched": 0, "sent": 0, "dupes": 0, "errors": 0}
            counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0,
                      "ALARM": 0, "CIVIL": 0}
            started = datetime.now()
            last_alert = None
            daily = {}

        class FakeApp:
            radar = FakeRadar()

            def toggle_pause(self, *a): pass
            def send_test(self, *a): pass
            def send_report(self, *a): pass
            def refresh_status(self, *a): pass
            def restart_radar(self, *a): pass
            def cancel_alarm(self, *a): pass

        win = gui.RadarWindow.alloc().initWithApp_(FakeApp())
        win.refresh()
        check("вікно будується", True, f"{int(win.window.frame().size.height)} px")
        check("три вкладки", win.tabs.numberOfTabViewItems() == 3)
        check("підказки не порожні",
              not [k for k in win.help_keys if not settings.HELP.get(k)],
              f"{len(win.help_keys)} кнопок «?»")
    except ImportError:
        print("     пропущено (немає AppKit — не macOS). Це нормально: "
              "на інших системах запускайте `python3 cloud_main.py`.")

    print("\n=== 8. РЕЗЕРВНА КОПІЯ ===")
    tmp = os.path.join(tempfile.gettempdir(), "radar_check.zip")
    ok, info = backup.create(tmp)
    check("копія створюється (або ще нічого зберігати)",
          ok or "нічого зберігати" in str(info), info)
    if os.path.exists(tmp):
        os.remove(tmp)

    print("\n" + "=" * 62)
    if warns and not SAMPLE:
        print(f"Застереження: {len(warns)} (див. вище; `python3 region_check.py`)")
    if fails:
        print("Є ПРОБЛЕМИ: " + ", ".join(fails))
        return 1
    print("УСЕ В ПОРЯДКУ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
