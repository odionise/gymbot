from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chat_id: Mapped[int | None] = mapped_column(BigInteger)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorkoutTemplate(Base):
    __tablename__ = "workout_templates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    muscle_group: Mapped[str] = mapped_column(String(120))
    weekday: Mapped[int] = mapped_column(Integer)
    send_time: Mapped[str] = mapped_column(String(5), default="09:00")
    next_phase: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    exercises: Mapped[list["Exercise"]] = relationship(back_populates="template", order_by="Exercise.position")


class Exercise(Base):
    __tablename__ = "exercises"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    template_id: Mapped[str] = mapped_column(ForeignKey("workout_templates.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    position: Mapped[int] = mapped_column(Integer, default=0)
    sets_count: Mapped[int] = mapped_column(Integer, default=3)
    medium_weight: Mapped[float] = mapped_column(Numeric(7, 2))
    weight_step: Mapped[float] = mapped_column(Numeric(7, 2), default=2.5)
    light_factor: Mapped[float] = mapped_column(Numeric(5, 3), default=0.9)
    heavy_factor: Mapped[float] = mapped_column(Numeric(5, 3), default=1.05)
    light_min: Mapped[int] = mapped_column(Integer, default=12)
    light_max: Mapped[int] = mapped_column(Integer, default=15)
    medium_min: Mapped[int] = mapped_column(Integer, default=8)
    medium_max: Mapped[int] = mapped_column(Integer, default=12)
    heavy_min: Mapped[int] = mapped_column(Integer, default=6)
    heavy_max: Mapped[int] = mapped_column(Integer, default=8)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    template: Mapped[WorkoutTemplate] = relationship(back_populates="exercises")


class WorkoutSession(Base):
    __tablename__ = "workout_sessions"
    __table_args__ = (UniqueConstraint("template_id", "scheduled_date"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id"), index=True)
    template_id: Mapped[str] = mapped_column(ForeignKey("workout_templates.id"), index=True)
    template_name: Mapped[str] = mapped_column(String(120))
    muscle_group: Mapped[str] = mapped_column(String(120))
    scheduled_date: Mapped[date] = mapped_column(Date)
    phase: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="planned")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exercises: Mapped[list["SessionExercise"]] = relationship(back_populates="session", order_by="SessionExercise.position", cascade="all, delete-orphan")


class SessionExercise(Base):
    __tablename__ = "session_exercises"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("workout_sessions.id"), index=True)
    exercise_id: Mapped[str] = mapped_column(ForeignKey("exercises.id"))
    name: Mapped[str] = mapped_column(String(120))
    position: Mapped[int] = mapped_column(Integer)
    sets_count: Mapped[int] = mapped_column(Integer)
    target_weight: Mapped[float] = mapped_column(Numeric(7, 2))
    target_reps: Mapped[int] = mapped_column(Integer)
    min_reps: Mapped[int] = mapped_column(Integer)
    max_reps: Mapped[int] = mapped_column(Integer)
    skipped: Mapped[bool] = mapped_column(Boolean, default=False)
    session: Mapped[WorkoutSession] = relationship(back_populates="exercises")
    results: Mapped[list["SetResult"]] = relationship(back_populates="session_exercise", order_by="SetResult.set_index", cascade="all, delete-orphan")


class SetResult(Base):
    __tablename__ = "set_results"
    __table_args__ = (UniqueConstraint("session_exercise_id", "set_index"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_exercise_id: Mapped[str] = mapped_column(ForeignKey("session_exercises.id"), index=True)
    set_index: Mapped[int] = mapped_column(Integer)
    weight: Mapped[float] = mapped_column(Numeric(7, 2))
    reps: Mapped[int] = mapped_column(Integer)
    session_exercise: Mapped[SessionExercise] = relationship(back_populates="results")


class Reminder(Base):
    __tablename__ = "reminders"
    __table_args__ = (UniqueConstraint("template_id", "local_date"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    template_id: Mapped[str] = mapped_column(ForeignKey("workout_templates.id"))
    local_date: Mapped[date] = mapped_column(Date)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    message_id: Mapped[int | None] = mapped_column(Integer)
