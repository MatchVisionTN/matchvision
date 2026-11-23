import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import psycopg
from psycopg.rows import dict_row

app = FastAPI(title="Match Vision API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def get_db():
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise HTTPException(
            status_code=503,
            detail="Database is not configured yet"
        )

    return psycopg.connect(
        database_url,
        row_factory=dict_row
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

        if not match:
            return {"match": None}

        return {"match": match}

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Could not retrieve match"
        )