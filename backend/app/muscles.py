MUSCLE_GROUPS = ("Грудь", "Спина", "Плечи", "Руки", "Ноги", "Корпус")

DETAILED_GROUPS = {
    "Грудь": ("Грудь", "Верх груди"),
    "Спина": ("Спина", "Широчайшие", "Верх спины", "Трапеция", "Большие круглые",
               "Малые круглые", "Ромбовидные", "Разгибатели спины"),
    "Плечи": ("Передние дельты", "Средние дельты", "Задние дельты"),
    "Руки": ("Бицепс", "Трицепс", "Предплечья"),
    "Ноги": ("Квадрицепс", "Приводящие мышцы", "Бицепс бедра", "Задняя поверхность бедра", "Ягодичные",
             "Икры", "Икроножные", "Камбаловидные"),
    "Корпус": ("Пресс", "Косые мышцы живота"),
}
ALL_DETAILED_GROUPS = tuple(group for groups in DETAILED_GROUPS.values() for group in groups)

# Small anatomical labels share existing volume targets. Historical labels are
# kept verbatim so saved workout snapshots and progress series remain intact.
VOLUME_GROUP = {
    "Верх груди": "Грудь",
    "Трапеция": "Верх спины", "Большие круглые": "Верх спины",
    "Малые круглые": "Верх спины", "Ромбовидные": "Верх спины",
    "Задняя поверхность бедра": "Бицепс бедра",
    "Икроножные": "Икры", "Камбаловидные": "Икры",
    "Косые мышцы живота": "Пресс",
}


def volume_group(group: str) -> str:
    return VOLUME_GROUP.get(group, group)


VOLUME_TARGET_GROUPS = tuple(dict.fromkeys(volume_group(group) for group in ALL_DETAILED_GROUPS))


def split_details(value: str | None) -> list[str]:
    return list(dict.fromkeys(part.strip() for part in (value or "").split(",") if part.strip()))


def split_muscle_groups(value: str) -> list[str]:
    return list(dict.fromkeys(part.strip() for part in value.split(",") if part.strip()))
