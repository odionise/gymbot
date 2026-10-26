from pydantic import BaseModel, Field, field_validator, model_validator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .muscles import MUSCLE_GROUPS, split_muscle_groups


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


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    muscle_group: str = Field(min_length=1, max_length=120)
    weekday: int = Field(ge=0, le=6)
    send_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")

    @field_validator("muscle_group")
    @classmethod
    def valid_muscle_groups(cls, value: str) -> str:
        groups = split_muscle_groups(value)
        if not groups or any(group not in MUSCLE_GROUPS for group in groups):
            raise ValueError("Choose at least one muscle group from the list")
        return ", ".join(groups)


class ExerciseIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    position: int = Field(default=0, ge=0)
    sets_count: int = Field(default=3, ge=1, le=12)
    medium_weight: float = Field(ge=0, le=1000)
    weight_step: float = Field(default=2.5, gt=0, le=100)
    light_factor: float = Field(default=0.9, gt=0, le=2)
    heavy_factor: float = Field(default=1.05, gt=0, le=2)
    light_min: int = Field(default=12, ge=1, le=50)
    light_max: int = Field(default=15, ge=1, le=50)
    medium_min: int = Field(default=8, ge=1, le=50)
    medium_max: int = Field(default=12, ge=1, le=50)
    heavy_min: int = Field(default=6, ge=1, le=50)
    heavy_max: int = Field(default=8, ge=1, le=50)

    @model_validator(mode="after")
    def valid_ranges(self):
        for phase in ("light", "medium", "heavy"):
            if getattr(self, f"{phase}_min") > getattr(self, f"{phase}_max"):
                raise ValueError(f"{phase}: min cannot exceed max")
        return self


class OverrideIn(BaseModel):
    target_weight: float = Field(ge=0, le=1000)
    target_reps: int = Field(ge=1, le=50)


class ResultIn(BaseModel):
    weight: float = Field(ge=0, le=1000)
    reps: int = Field(ge=0, le=100)


class SkipIn(BaseModel):
    skipped: bool
