MUSCLE_GROUPS = ("Грудь", "Спина", "Плечи", "Руки", "Ноги")


def split_muscle_groups(value: str) -> list[str]:
    return list(dict.fromkeys(part.strip() for part in value.split(",") if part.strip()))
