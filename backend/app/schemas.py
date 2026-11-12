from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

from .muscles import ALL_DETAILED_GROUPS, MUSCLE_GROUPS, split_muscle_groups


class SettingsIn(BaseModel):
    timezone: str

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown timezone") from exc
        return value


class ProfileIn(BaseModel):
    sex: Literal["male", "female"]
    display_name: str = Field(min_length=1, max_length=80)
    birth_date: date

    @field_validator("display_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Укажите имя")
        return value

    @field_validator("birth_date")
    @classmethod
    def valid_birth_date(cls, value: date) -> date:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("Europe/Moscow")).date()
        if value >= today or value.year < 1900:
            raise ValueError("Укажите прошедшую дату рождения")
        return value


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    muscle_group: str = Field(min_length=1, max_length=120)
    weekday: int = Field(ge=0, le=6)
    send_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")

    @field_validator("muscle_group")
    @classmethod
    def valid_muscle_groups(cls, value: str) -> str:
        groups = split_muscle_groups(value)
        if not groups or any(group not in (*MUSCLE_GROUPS, "Кардио", "Растяжка", "Другое") for group in groups):
            raise ValueError("Choose at least one workout section from the list")
        return ", ".join(groups)


class CycleSlotIn(BaseModel):
    day: int = Field(ge=1, le=30)
    template_id: str


class CycleConfigIn(BaseModel):
    length_days: int = Field(ge=2, le=30)
    start_date: date
    slots: list[CycleSlotIn] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def valid_slots(self):
        if any(slot.day > self.length_days for slot in self.slots):
            raise ValueError("День занятия выходит за пределы цикла")
        if len({(slot.day, slot.template_id) for slot in self.slots}) != len(self.slots):
            raise ValueError("Одинаковое занятие нельзя поставить дважды в один день")
        return self


class ExerciseOrderIn(BaseModel):
    exercise_ids: list[str] = Field(min_length=1)


class ExerciseIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    position: int = Field(default=0, ge=0)
    sets_count: int = Field(default=3, ge=1, le=12)
    medium_weight: float = Field(default=0, ge=0, le=1000)
    weight_step: float = Field(default=2.5, ge=0.01, le=100, multiple_of=0.01)
    light_factor: float = Field(default=0.9, gt=0, le=2)
    heavy_factor: float = Field(default=1.05, gt=0, le=2)
    light_min: int = Field(default=12, ge=1, le=50)
    light_max: int = Field(default=15, ge=1, le=50)
    medium_min: int = Field(default=8, ge=1, le=50)
    medium_max: int = Field(default=12, ge=1, le=50)
    heavy_min: int = Field(default=6, ge=1, le=50)
    heavy_max: int = Field(default=8, ge=1, le=50)
    movement_id: str | None = None
    rep_min: int | None = Field(default=None, ge=1, le=50)
    rep_max: int | None = Field(default=None, ge=1, le=50)
    rir_target: float | None = Field(default=2, ge=0, le=6, multiple_of=0.5, deprecated=True)
    duration_minutes: int | None = Field(default=None, ge=1, le=600)

    @model_validator(mode="after")
    def valid_ranges(self):
        for phase in ("light", "medium", "heavy"):
            if getattr(self, f"{phase}_min") > getattr(self, f"{phase}_max"):
                raise ValueError(f"{phase}: min cannot exceed max")
        if (self.rep_min if self.rep_min is not None else self.medium_min) > (
                self.rep_max if self.rep_max is not None else self.medium_max):
            raise ValueError("rep_min cannot exceed rep_max")
        return self


class MovementIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["strength", "cardio", "stretch", "other_timed"] = "strength"
    primary_group: str = "Не применяется"
    secondary_groups: list[str] = Field(default_factory=list)
    is_anchor: bool = False

    @model_validator(mode="after")
    def valid_groups(self):
        if self.kind != "strength":
            if self.secondary_groups or self.is_anchor:
                raise ValueError("Timed exercises cannot have muscle groups or an anchor")
            self.primary_group = "Не применяется"
            return self
        if self.primary_group not in ALL_DETAILED_GROUPS:
            raise ValueError("Choose a detailed primary muscle group")
        if (self.primary_group in self.secondary_groups or
                len(set(self.secondary_groups)) != len(self.secondary_groups) or
                any(group not in ALL_DETAILED_GROUPS for group in self.secondary_groups)):
            raise ValueError("Invalid secondary muscle groups")
        return self


class ReplacementSettings(BaseModel):
    model_config = {"extra": "forbid"}
    sets_count: int | None = Field(default=None, ge=1, le=12)
    medium_weight: float | None = Field(default=None, ge=0, le=1000)
    weight_step: float | None = Field(default=None, ge=0.01, le=100, multiple_of=0.01)
    rep_min: int | None = Field(default=None, ge=1, le=50)
    rep_max: int | None = Field(default=None, ge=1, le=50)
    duration_minutes: int | None = Field(default=None, ge=1, le=600)

    @model_validator(mode="after")
    def valid_range(self):
        if self.rep_min is not None and self.rep_max is not None and self.rep_min > self.rep_max:
            raise ValueError("Минимум повторов не может превышать максимум")
        return self


class ReplacementIn(BaseModel):
    model_config = {"extra": "forbid"}
    movement_id: str = Field(min_length=1, max_length=36)
    history_mode: Literal["new", "resume"]
    history_id: str | None = None
    settings: ReplacementSettings

    @model_validator(mode="after")
    def history_choice(self):
        if self.history_mode == "resume" and not self.history_id:
            raise ValueError("Выберите прежнюю базу результатов")
        if self.history_mode == "new" and self.history_id is not None:
            raise ValueError("Для новой базы не указывают прежнюю историю")
        return self


class RescheduleIn(BaseModel):
    scheduled_date: str


class RecoveryIn(BaseModel):
    feeling_beat_up: bool


class VolumeCapIn(BaseModel):
    volume_cap: int = Field(ge=8, le=30)


class MuscleTargetIn(BaseModel):
    min_sets: int = Field(ge=1, le=30)
    max_sets: int = Field(ge=1, le=30)
    cap_sets: int = Field(ge=1, le=30)

    @model_validator(mode="after")
    def ordered(self):
        if not self.min_sets <= self.max_sets <= self.cap_sets:
            raise ValueError("Minimum, maximum and cap must be ordered")
        return self


class OverrideIn(BaseModel):
    target_weight: float = Field(ge=0, le=1000)
    target_reps: int = Field(ge=1, le=50)


class SetsCountIn(BaseModel):
    sets_count: int = Field(ge=1, le=12)


class ResultIn(BaseModel):
    weight: float = Field(ge=0, le=1000)
    reps: int = Field(ge=0, le=100)
    rir_reported: float | None = Field(default=None, ge=0, le=10, multiple_of=0.5)
    is_working: bool = True

    @model_validator(mode="after")
    def working_rir(self):
        if self.is_working and self.rir_reported is None:
            raise ValueError("Для рабочего подхода укажите ПДО")
        return self


class SkipIn(BaseModel):
    skipped: bool


class DurationIn(BaseModel):
    minutes: int = Field(ge=1, le=600)


class NextWeekIn(BaseModel):
    kind: Literal["deload", "vacation"]


class PreviewWeekOut(BaseModel):
    week_start: date
    week_number: int
    phase_type: str
    deload_reason: str | None
    is_postponed: bool
    missed_deload: bool
    source: Literal["saved", "calculated"]


class PreviewReferenceOut(BaseModel):
    id: str
    scheduled_date: date
    status: str


class PreviewBlockerOut(BaseModel):
    code: str
    message: str
    template_id: str | None = None
    exercise_id: str | None = None


class PreviewExerciseOut(BaseModel):
    exercise_id: str
    slot_id: str
    history_id: str
    movement_id: str
    name: str
    kind: str
    position: int
    sets_count: int | None
    target_weight: float | None
    target_reps: int | None
    target_rir: float | None
    target_duration_minutes: int | None
    recommendation: dict | None


class SessionPreviewOut(BaseModel):
    state: Literal["ready", "existing", "blocked"]
    template_id: str
    on_date: date
    timezone: str
    computed_at: datetime
    provisional: Literal[True]
    persisted: Literal[False]
    week: PreviewWeekOut | None
    exercises: list[PreviewExerciseOut]
    existing_session: PreviewReferenceOut | None
    blocking_reasons: list[PreviewBlockerOut]
