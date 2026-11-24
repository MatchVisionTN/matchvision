import os
import json
import hmac
import hashlib
import uuid
import time

from urllib.parse import parse_qsl

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

app = FastAPI(title="Match Vision API")

MONETAG_ZONE_ID = "12332963"


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class TelegramAuthRequest(BaseModel):
    init_data: str


def get_db():
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise HTTPException(
            status_code=503,
            detail="Database is not configured"
        )

    return psycopg.connect(
        database_url,
        row_factory=dict_row
    )


def verify_telegram_user(init_data: str):
    bot_token = os.getenv("BOT_TOKEN")

    if not bot_token:
        raise HTTPException(
            status_code=503,
            detail="Bot token is not configured"
        )

    if not init_data:
        raise HTTPException(status_code=401, detail="Missing Telegram data")

    try:
        pairs = parse_qsl(init_data, keep_blank_values=True)
        data = dict(pairs)

        # Reject duplicate parameters
        if len(data) != len(pairs):
            raise ValueError("Duplicate parameters")

        received_hash = data.pop("hash", None)

        if not received_hash:
            raise ValueError("Missing hash")

        data_check_string = "\n".join(
            f"{key}={value}" for key, value in sorted(data.items())
        )

        secret_key = hmac.new(
            b"WebAppData",
            bot_token.encode(),
            hashlib.sha256
        ).digest()

        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            raise ValueError("Invalid Telegram signature")

        auth_date = int(data.get("auth_date", "0"))

        if auth_date > int(time.time()) + 60:
            raise ValueError("Invalid authentication date")

        if int(time.time()) - auth_date > 86400:
            raise ValueError("Telegram session expired")

        user = json.loads(data["user"])
        telegram_id = int(user["id"])

        return telegram_id

    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired Telegram session"
        )


@app.get("/")
def home():
    return {"message": "Match Vision API is running"}


@app.get("/api/matches/latest")
def latest_match():
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, team_a, team_b, match_date,
                           prediction, analysis
                    FROM matches
                    WHERE status = 'published'
                    ORDER BY id DESC
                    LIMIT 1
                """)
                match = cur.fetchone()

        return {"match": match}

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Could not retrieve match"
        )


@app.post("/api/ad-sessions")
def create_ad_session(payload: TelegramAuthRequest, match_id: int = Query(...)):
    telegram_id = verify_telegram_user(payload.init_data)
    ymid = uuid.uuid4().hex

    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id
                    FROM matches
                    WHERE id = %s
                      AND status = 'published'
                      AND extra_analysis <> ''
                """, (match_id,))

                match = cur.fetchone()

                if not match:
                    raise HTTPException(
                        status_code=404,
                        detail="Extra analysis is not available"
                    )

                cur.execute("""
                    INSERT INTO ad_sessions
                        (ymid, telegram_id, match_id, status)
                    VALUES (%s, %s, %s, 'pending')
                """, (ymid, telegram_id, match_id))

        return {"ymid": ymid}

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Could not create ad session"
        )


@app.get("/postback")
def monetag_postback(
    secret: str = Query(""),
    ymid: str = Query(""),
    zone_id: str = Query(""),
    event_type: str = Query(""),
    reward_event_type: str = Query(""),
    telegram_id: str = Query("")
):
    expected_secret = os.getenv("POSTBACK_SECRET")

    if not expected_secret or not hmac.compare_digest(
        secret, expected_secret
    ):
        raise HTTPException(status_code=403, detail="Invalid secret")

    if zone_id != MONETAG_ZONE_ID:
        raise HTTPException(status_code=400, detail="Invalid zone")

    if not ymid or event_type not in ("impression", "click"):
        raise HTTPException(status_code=400, detail="Invalid postback")

    # No reward for non-valued events
    if reward_event_type != "valued":
        return {"ok": True, "rewarded": False}

    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT telegram_id, match_id, status
                    FROM ad_sessions
                    WHERE ymid = %s
                    FOR UPDATE
                """, (ymid,))

                session = cur.fetchone()

                if not session:
                    return {"ok": True, "rewarded": False}

                # If Monetag supplied a Telegram ID, it must match
                if telegram_id:
                    try:
                        if int(telegram_id) != session["telegram_id"]:
                            return {"ok": True, "rewarded": False}
                    except ValueError:
                        return {"ok": True, "rewarded": False}

                if session["status"] != "pending":
                    return {"ok": True, "rewarded": False}

                cur.execute("""
                    INSERT INTO ad_rewards
                        (ymid, telegram_id, match_id, zone_id,
                         reward_event_type)
                    VALUES (%s, %s, %s, %s, 'valued')
                    ON CONFLICT (ymid) DO NOTHING
                    RETURNING ymid
                """, (
                    ymid,
                    session["telegram_id"],
                    session["match_id"],
                    zone_id
                ))

                inserted = cur.fetchone()

                if inserted:
                    cur.execute("""
                        UPDATE ad_sessions
                        SET status = 'rewarded'
                        WHERE ymid = %s
                    """, (ymid,))

        return {"ok": True, "rewarded": bool(inserted)}

    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Could not process postback"
        )


@app.post("/api/matches/{match_id}/extra")
def get_extra_analysis(
    match_id: int,
    payload: TelegramAuthRequest
):
    telegram_id = verify_telegram_user(payload.init_data)

    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT m.extra_analysis
                    FROM matches m
                    JOIN ad_rewards r ON r.match_id = m.id
                    WHERE m.id = %s
                      AND m.status = 'published'
                      AND r.telegram_id = %s
                    LIMIT 1
                """, (match_id, telegram_id))

                result = cur.fetchone()

        if not result:
            raise HTTPException(
                status_code=403,
                detail="Complete a rewarded ad to unlock this analysis"
            )

        return {"extra_analysis": result["extra_analysis"]}

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Could not retrieve extra analysis"
        )