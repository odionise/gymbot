MUSCLE_GROUPS = ("Грудь", "Спина", "Плечи", "Руки", "Ноги")

DETAILED_GROUPS = {
    "Грудь": ("Грудь",),
    "Спина": ("Широчайшие", "Верх спины", "Разгибатели спины"),
    "Плечи": ("Передние дельты", "Средние дельты", "Задние дельты"),
    "Руки": ("Бицепс", "Трицепс", "Предплечья"),
    "Ноги": ("Квадрицепс", "Бицепс бедра", "Ягодичные", "Икры"),
}
ALL_DETAILED_GROUPS = tuple(group for groups in DETAILED_GROUPS.values() for group in groups)


def split_details(value: str | None) -> list[str]:
    return list(dict.fromkeys(part.strip() for part in (value or "").split(",") if part.strip()))


def split_muscle_groups(value: str) -> list[str]:
    return list(dict.fromkeys(part.strip() for part in value.split(",") if part.strip()))
