# -*- coding: utf-8 -*-
"""ВИГАДАНИЙ профіль для самоперевірки. Жодного реального міста.

`python3 final_check.py --sample` підставляє його замість вашого, щоб
перевірити, що сам рушій працює — незалежно від того, чи заповнили ви
свій профіль. Тут «Тестоград» у вигаданій «Тестовській області».
"""

SETTINGS = {
    "channels": ["example_channel"],
    "city_main_name": "Тестоград",
    "city_main_variants": "тестоград, тестограда, тестограду, тестоградом, "
                          "тестоградськ",
    "district_name": "Тестоградський район",
    "district_variants": "тестоградськ",
}

PROFILE = {
    "OBLAST_LABEL": "Тестовщина",
    "OBLAST_ROOTS": ["тестовськ"],
    "OBLAST_ALONE": ["тестовщин"],
    "OBLAST": ["тестовськ", "тестовщин"],
    "HOME_COMMUNITY": ["тестоградськ"],
    "CLOSE": {
        "Соснівка": ["соснівк", "сосновк"],
        "Дубрівка": ["дубрівк", "дубровк"],
    },
    "NEAR": {
        "Липівка": (["липівк", "липовк"], ["липовий"]),
        "Ясенів": (["ясенів", "ясенев"], []),
    },
    "FAR": {
        "Верхів": ["верхів"],
    },
    "CIVIL_SKIP": [],
}


def apply():
    """Підставляє вигаданий профіль. Викликати ДО import config/geo."""
    import settings
    import region_profile

    real_load = settings.load
    settings.load = lambda: {**settings.DEFAULTS, **SETTINGS}
    for name, value in PROFILE.items():
        setattr(region_profile, name, value)
    return real_load
