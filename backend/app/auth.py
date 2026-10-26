import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from fastapi import Depends, Header, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import User


def verify_init_data(raw: str, token: str, now: int | None = None) -> int:
    if not token or not raw:
        raise ValueError("Missing Telegram authentication")
    pairs = dict(parse_qsl(raw, keep_blank_values=True, strict_parsing=True))
    received_hash = pairs.pop("hash", "")
    pairs.pop("signature", None)
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(received_hash, expected_hash):
        raise ValueError("Invalid Telegram signature")
    current = int(time.time()) if now is None else now
    auth_date = int(pairs["auth_date"])
    if auth_date > current + 60 or current - auth_date > 86400:
        raise ValueError("Expired Telegram authentication")
    user_id = int(json.loads(pairs["user"])["id"])
    if user_id <= 0:
        raise ValueError("Invalid Telegram user")
    return user_id


def current_user(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
    x_dev_user_id: int | None = Header(default=None),
) -> User:
    settings = get_settings()
    if settings.app_env == "development" and x_dev_user_id and x_dev_user_id == settings.dev_telegram_id:
        user_id = x_dev_user_id
    else:
        if not authorization or not authorization.startswith("tma "):
            raise HTTPException(401, "Open the app from Telegram")
        try:
            user_id = verify_init_data(authorization[4:], settings.bot_token)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise HTTPException(401, str(exc)) from exc
    user = db.get(User, user_id)
    if user is None:
        user = User(telegram_id=user_id)
        db.add(user)
        try:
            db.commit()
            db.refresh(user)
        except IntegrityError:
            db.rollback()
            user = db.get(User, user_id)
            if user is None:
                raise
    return user
