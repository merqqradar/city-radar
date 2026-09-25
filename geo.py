# -*- coding: utf-8 -*-
"""Географические словари: [МІСТО], ближние сёла, район, область.

Списки собраны из реальной выгрузки за 30 дней — это те НП, которые
каналы упоминают вместе со [МІСТО] (через них идёт подлёт).

Правится только здесь. Поиск по КОРНЯМ в нижнем регистре,
чтобы ловить падежи: "на [СЕЛО]", "над [СЕЛО]", "[СЕЛО]".
"""

import re
from functools import lru_cache

import region_profile

# --- Пошук коренів ПО МЕЖІ СЛОВА ---------------------------------------------
# Раніше корені шукались простим «підрядок у тексті», і через це
# «Кордар» читався як село [СЕЛО] під [МІСТО] —
# радар підняв червону тривогу на новину про удар по Приморськ.
# Так само «Шахтарське» ловилось як «Тарське», «[СЕЛО]» як «Град».
#
# Тепер корінь має починати СЛОВО: перед ним не може стояти літера.
# Закінчення слова не перевіряємо — саме так ловляться відмінки:
# «на [СЕЛО]», «над [СЕЛО]», «[МІСТО]».


@lru_cache(maxsize=1024)
def _pattern(roots: tuple):
    """Регулярка «будь-який із коренів на початку слова».

    Додаємо українське чергування К→Ц у місцевому відмінку:
    «[СЕЛО]» → «у [СЕЛО]», «[СЕЛО]» → «в [СЕЛО]».
    Без цього «вибух у [СЕЛО]» не впізнавався взагалі — корінь
    «[СЕЛО]» не збігається з «[СЕЛО]», і село ближнього кола
    просто випадало з поля зору.
    """
    full = list(roots)
    for root in roots:
        if root.endswith("к"):
            full.append(root[:-1] + "ц")
    return re.compile("|".join(r"(?<!\w)" + re.escape(r) for r in full))


def _has(low: str, roots) -> bool:
    """Чи є в тексті хоч один корінь (на межі слова)."""
    roots = tuple(roots)
    return bool(roots) and bool(_pattern(roots).search(low))


# --- Ядро: головне місто ------------------------------------------------------
# Раніше тут був жорстко зашитий шаблон для [МІСТО]. Тепер місто береться
# з налаштувань: у полі перелічені варіанти написання через кому.
# Наприклад, для міста «Тестоград»: тестоград, тестограда, тестоградськ...
#
# ВАЖЛИВО: варіанти шукаються як підрядок, тому «[МІСТО]» ловить і «[МІСТО]»,
# і «[МІСТО]». Але «змі» вписувати не можна — воно зловить «зміни»,
# «зміст», «змішаний». Пишіть повні корені.


def _parse(raw: str) -> list:
    """Розбирає поле «варіанти написання» на список коренів."""
    return [part.strip().lower() for part in (raw or "").split(",")
            if part.strip()]


class _Cities:
    """Міста з налаштувань. Перечитуються після зміни в інтерфейсі."""

    def __init__(self):
        self.reload()

    def reload(self):
        import config

        self.main_name = config.CITY_MAIN_NAME or "Місто"
        self.main = _parse(config.CITY_MAIN_VARIANTS)
        self.extra = []
        for on, name, raw in (
                (config.CITY_2_ON, config.CITY_2_NAME, config.CITY_2_VARIANTS),
                (config.CITY_3_ON, config.CITY_3_NAME, config.CITY_3_VARIANTS)):
            roots = _parse(raw)
            if on and name.strip() and roots:
                self.extra.append((name.strip(), roots))
        self.district_name = config.DISTRICT_NAME
        self.district = _parse(config.DISTRICT_VARIANTS)


CITIES = _Cities()


def reload_cities() -> None:
    """Викликається після збереження налаштувань."""
    CITIES.reload()


def find_main(text: str) -> bool:
    """Чи згадане головне місто."""
    low = text.lower()
    return _has(low, CITIES.main)


def find_extra(low: str) -> list:
    """Додаткові міста, згадані в тексті."""
    return [name for name, roots in CITIES.extra if _has(low, roots)]


def main_name() -> str:
    return CITIES.main_name




# --- Ближний круг: сёла [МІСТО] громады и то, что рядом -------------------
# Подлёт на [МІСТО] идёт через них. Дают MEDIUM, а при включённом
# HIGH_INCLUDES_NEIGHBORS в config.py — HIGH.
CLOSE = region_profile.CLOSE

# --- Ближний пояс: цель тут ещё не на нас, но рядом ---------------------------
# Дают тихие уведомления «можлива зміна курсу». Эти названия неоднозначны
# ([СЕЛО], [СЕЛО] есть и в других областях), поэтому у каждого — список
# слов, при которых совпадение НЕ засчитывается.
NEAR = region_profile.NEAR


def find_near(low: str) -> list:
    """Ближний пояс. Учитывает слова-исключения для тёзок."""
    out = []
    for name, (roots, bad) in NEAR.items():
        if _has(low, roots) and not any(b in low for b in bad):
            out.append(name)
    return out


# --- Дальний круг: только как контекст, сам по себе уведомление не даёт ------
# [СУСІДНЄ-МІСТО] в 40 км восточнее: его обстрелы к [МІСТО] отношения не имеют,
# но упоминание рядом со [МІСТО] уточняет картину.
FAR = region_profile.FAR



# --- Район и область ---------------------------------------------------------
# [МІСТО] с 2020 года входит в [СУСІДНЄ-МІСТО] район [ОБЛАСТЬ] області.
def _district_roots() -> list:
    return CITIES.district
OBLAST = region_profile.OBLAST

# Другие области: если сообщение про них, к нам оно почти наверняка не относится
# ІНШІ ОБЛАСТІ (укр. + рос. корінь). Свою область радар виключає сам —
# за коренями з region_profile.OBLAST_ROOTS.
#
# Два рівні. «Надійні» корені ловляться самі по собі. «Обережні» збігаються
# з назвами сіл («Черкаська [СЕЛО]», «Вінницькі [СЕЛО]»), тому їх рахуємо
# лише впритул до слова «область». Це навчилося на реальних даних: коли ці
# корені були в основному списку, справжні повідомлення про цілі на такі
# села відкидались як «новина про іншу область».
_REGIONS_SAFE = [
    ("донецьк", "донецк"), ("херсонськ", "херсонск"),
    ("запорізьк", "запорожск"), ("дніпропетровськ", "днепропетровск"),
    ("полтавськ", "полтавск"), ("сумськ", "сумск"), ("київськ", "киевск"),
    ("одеськ", "одесск"), ("миколаївськ", "николаевск"),
    ("черніг", "черниг"), ("луганськ", "луганск"), ("харківськ", "харьковск"),
]
_REGIONS_CAREFUL = [
    ("вінницьк", "винницк"), ("волинськ", "волынск"),
    ("житомирськ", "житомирск"), ("закарпатськ", "закарпатск"),
    ("івано-франківськ", "ивано-франковск"), ("кіровоградськ", "кировоградск"),
    ("львівськ", "львовск"), ("рівненськ", "ровенск"),
    ("тернопільськ", "тернопольск"), ("хмельницьк", "хмельницк"),
    ("черкаськ", "черкасск"), ("чернівецьк", "черновицк"),
]


def _not_own(pairs) -> list:
    own = [r for r in region_profile.OBLAST_ROOTS if r]
    out = []
    for pair in pairs:
        if any(o[:5] == root[:5] for o in own for root in pair):
            continue
        out.extend(pair)
    return out


OTHER_REGIONS = _not_own(_REGIONS_SAFE)
_CAREFUL_RE = re.compile(
    r"(?<!\w)(?:" + "|".join(re.escape(r) for r in _not_own(_REGIONS_CAREFUL))
    + r")\w*\s+(?:област|обл\b)") if _not_own(_REGIONS_CAREFUL) else None


# Назви напрямків фронту збігаються з назвами сіл:
# «На Південно-[СЕЛО] напрямку» — це ділянка фронту за сотні
# кілометрів, а не [СЕЛО] під [МІСТО]. Такі звороти вирізаємо
# ДО пошуку населених пунктів.
DIRECTION_RE = re.compile(
    r"[\w’'`\-]+\s+напрям\w*"          # «[СЕЛО] напрямку»
    r"|[\w’'`\-]+\s+направлени\w*"     # «[СЕЛО] направлении»
    r"|напрямку\s+[\w’'`\-]+",          # «напрямку [СЕЛО]»
    re.IGNORECASE)


def strip_directions(text: str) -> str:
    """Прибирає згадки напрямків фронту — вони не є географією загрози."""
    return DIRECTION_RE.sub(" ", text)


def _match(low: str, table: dict) -> list:
    """Ищет в тексте НП из таблицы. Возвращает список имён."""
    return [name for name, roots in table.items() if _has(low, roots)]


def find_close(low: str) -> list:
    """Ближние НП (подлёт на [МІСТО]). Напрямки фронту не рахуються."""
    return _match(strip_directions(low), CLOSE)


def find_far(low: str) -> list:
    """Дальние НП — только контекст."""
    return _match(strip_directions(low), FAR)


# [МІСТО] громада окремо від усього [СУСІДНЄ-МІСТО] району:
# вибух у [СУСІДНЄ-МІСТО] за 40 км нас не стосується.
HOME_COMMUNITY = region_profile.HOME_COMMUNITY


def find_home_district(low: str) -> bool:
    """Саме [МІСТО] район / громада, а не весь [СУСІДНЄ-МІСТО]."""
    return _has(low, HOME_COMMUNITY)


def find_district(low: str) -> bool:
    """Упомянут ли район, за которым следит радар."""
    return _has(low, _district_roots())


def find_oblast(low: str) -> bool:
    """Упомянута ли [ОБЛАСТЬ] область."""
    return _has(low, OBLAST)


# Тревога объявляется по районам. Наш — [СУСІДНЄ-МІСТО] ([МІСТО] входит в него
# с 2020 года). «[ОБЛАСТЬ] район» — это другой район, западнее города,
# и к нам он отношения не имеет.
# «[ОБЛАСТЬ]» и связка «[ОБЛАСТЬ]… област…» в любом падеже.
# Одного слова «[ОБЛАСТЬ]» мало: «[ОБЛАСТЬ] територіальна громада» —
# это город, а не область, и тревога там не наша.
OBLAST_ROOTS = region_profile.OBLAST_ROOTS
OBLAST_WORDS = ["област"]
OBLAST_ALONE = list(region_profile.OBLAST_ALONE) + [
    "по всій області", "вся область"]


def is_our_alarm_area(low: str) -> bool:
    """Относится ли объявление тревоги к [МІСТО].

    Наши — [СУСІДНЄ-МІСТО]/[МІСТО] район и объявления на всю область.
    Тревога по [ОБЛАСНИЙ-ЦЕНТР] или [СЕЛО] району к [МІСТО] отношения не имеет.
    """
    if _has(low, _district_roots()):
        return True
    if _has(low, OBLAST_ALONE):
        return True
    return _has(low, OBLAST_ROOTS) and any(w in low for w in OBLAST_WORDS)


def mentions_other_region(low: str) -> bool:
    """Сообщение про другую область — скорее всего не про нас."""
    return (_has(low, OTHER_REGIONS)
            or bool(_CAREFUL_RE and _CAREFUL_RE.search(low)))


def oblast_label() -> str:
    """Коротка назва області для підписів («по області»), із профілю."""
    return region_profile.OBLAST_LABEL or "область"
