import os
import secrets
import base64
import time
import hashlib
from datetime import datetime, timezone, timedelta

import asyncpg
import aiohttp
from aiohttp import web

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# ENVIRONMENT
# ============================================================

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
ADMIN_API_TOKEN = os.getenv("ADMIN_API_TOKEN", "").strip()

try:
    OWNER_ID = int(os.getenv("OWNER_ID", "0") or 0)
except ValueError:
    OWNER_ID = 0

try:
    PORT = int(os.getenv("PORT", "8080"))
except ValueError:
    PORT = 8080

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing.")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing.")

# ============================================================
# GLOBALS
# ============================================================

db_pool: asyncpg.Pool | None = None
http_runner: web.AppRunner | None = None
http_site: web.TCPSite | None = None

# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def discord_timestamp(dt: datetime) -> str:
    return f"<t:{int(dt.timestamp())}:F>"


def hash_key(key: str) -> str:
    return hashlib.sha256(
        str(key).strip().encode("utf-8")
    ).hexdigest()


def normalize_hwid(hwid: str) -> str:
    if not isinstance(hwid, str):
        return ""
    return hwid.strip().lower()[:256]


def hash_hwid(hwid: str) -> str:
    return hashlib.sha256(
        normalize_hwid(hwid).encode("utf-8")
    ).hexdigest()


def parse_duration(value: str) -> timedelta:
    value = str(value).strip().lower()

    if len(value) < 2:
        raise ValueError(
            "Use a duration such as `30d`, `90d`, `12h`, or `1y`."
        )

    try:
        amount = int(value[:-1])
    except ValueError as exc:
        raise ValueError("Invalid duration.") from exc

    if amount <= 0:
        raise ValueError("Duration must be greater than zero.")

    unit = value[-1]

    if unit == "m":
        return timedelta(minutes=amount)
    if unit == "h":
        return timedelta(hours=amount)
    if unit == "d":
        return timedelta(days=amount)
    if unit == "y":
        return timedelta(days=365 * amount)

    raise ValueError("Use `m`, `h`, `d`, or `y`.")


def generate_license_key() -> str:
    raw = secrets.token_bytes(48)
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"GUARDIAN-{encoded}"

# ============================================================
# DATABASE
# ============================================================

async def init_database():
    global db_pool

    print("Connecting to PostgreSQL...")

    db_pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=5,
        command_timeout=30,
    )

    async with db_pool.acquire() as conn:

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS licenses (
                id BIGSERIAL PRIMARY KEY,
                key_hash TEXT NOT NULL UNIQUE,
                created_at TIMESTAMPTZ NOT NULL,
                expires_at TIMESTAMPTZ NOT NULL,
                activated_at TIMESTAMPTZ,
                discord_user_id BIGINT,
                machine_id TEXT,
                status TEXT NOT NULL DEFAULT 'UNUSED',
                CONSTRAINT licenses_status_check CHECK (
                    status IN (
                        'UNUSED',
                        'ACTIVE',
                        'EXPIRED',
                        'REVOKED',
                        'SUSPENDED'
                    )
                )
            )
        """)

        # Migrate the old constraint used by earlier versions.
        await conn.execute("""
            ALTER TABLE licenses
            DROP CONSTRAINT IF EXISTS licenses_status_check
        """)

        await conn.execute("""
            ALTER TABLE licenses
            ADD CONSTRAINT licenses_status_check
            CHECK (
                status IN (
                    'UNUSED',
                    'ACTIVE',
                    'EXPIRED',
                    'REVOKED',
                    'SUSPENDED'
                )
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                guild_id BIGINT PRIMARY KEY,
                dashboard_channel_id BIGINT,
                dashboard_message_id BIGINT
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id BIGSERIAL PRIMARY KEY,
                license_id BIGINT NOT NULL
                    REFERENCES licenses(id)
                    ON DELETE CASCADE,
                category TEXT NOT NULL DEFAULT 'Other',
                message TEXT NOT NULL,
                profile_name TEXT,
                status TEXT NOT NULL DEFAULT 'OPEN',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                admin_reply TEXT,
                replied_by BIGINT
            )
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_feedback_license_id
            ON feedback(license_id)
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_licenses_discord_user_id
            ON licenses(discord_user_id)
        """)

    print("PostgreSQL database initialized.")
    print("DATABASE: ONLINE")


async def close_database():
    global db_pool

    if db_pool is not None:
        await db_pool.close()
        db_pool = None
        print("PostgreSQL connection closed.")


async def check_database():
    if db_pool is None:
        return {
            "online": False,
            "latency": None,
            "message": "Database pool is not initialized.",
        }

    started = time.perf_counter()

    try:
        async with db_pool.acquire() as conn:
            result = await conn.fetchval("SELECT 1")

        elapsed = (time.perf_counter() - started) * 1000

        if result != 1:
            return {
                "online": False,
                "latency": round(elapsed, 2),
                "message": f"Unexpected response: {result}",
            }

        return {
            "online": True,
            "latency": round(elapsed, 2),
            "message": "PostgreSQL responded successfully.",
        }

    except Exception as exc:
        elapsed = (time.perf_counter() - started) * 1000
        return {
            "online": False,
            "latency": round(elapsed, 2),
            "message": str(exc),
        }


async def expire_licenses():
    if db_pool is None:
        return

    async with db_pool.acquire() as conn:
        await conn.execute("""
            UPDATE licenses
            SET status='EXPIRED'
            WHERE expires_at <= $1
              AND status IN ('UNUSED', 'ACTIVE')
        """, utc_now())


async def get_license(key: str):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM licenses WHERE key_hash=$1",
            hash_key(key),
        )


async def get_license_by_id(license_id: int):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM licenses WHERE id=$1",
            int(license_id),
        )


async def get_stats():
    await expire_licenses()

    result = {
        "TOTAL": 0,
        "ACTIVE": 0,
        "UNUSED": 0,
        "EXPIRED": 0,
        "REVOKED": 0,
        "SUSPENDED": 0,
    }

    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT status, COUNT(*) AS count
            FROM licenses
            GROUP BY status
        """)

    for row in rows:
        status = row["status"]
        count = int(row["count"])
        result["TOTAL"] += count
        if status in result:
            result[status] = count

    return result

# ============================================================
# LICENSE AUTHENTICATION
# ============================================================

async def activate_license(license_key: str, hwid: str):
    if db_pool is None:
        return {
            "success": False,
            "code": "DATABASE_OFFLINE",
            "message": "License database unavailable.",
        }

    license_key = str(license_key or "").strip()
    hwid = normalize_hwid(hwid)

    if not license_key:
        return {
            "success": False,
            "code": "INVALID_KEY",
            "message": "License key is required.",
        }

    if not hwid:
        return {
            "success": False,
            "code": "INVALID_HWID",
            "message": "HWID is required.",
        }

    hwid_hash_value = hash_hwid(hwid)
    now = utc_now()

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("""
                SELECT *
                FROM licenses
                WHERE key_hash=$1
                FOR UPDATE
            """, hash_key(license_key))

            if row is None:
                return {
                    "success": False,
                    "code": "INVALID_KEY",
                    "message": "Invalid license key.",
                }

            if row["status"] == "REVOKED":
                return {
                    "success": False,
                    "code": "REVOKED",
                    "message": "This license has been revoked.",
                }

            if row["status"] == "SUSPENDED":
                return {
                    "success": False,
                    "code": "SUSPENDED",
                    "message": "This license has been restricted.",
                }

            if row["expires_at"] <= now:
                await conn.execute(
                    "UPDATE licenses SET status='EXPIRED' WHERE id=$1",
                    row["id"],
                )
                return {
                    "success": False,
                    "code": "EXPIRED",
                    "message": "This license has expired.",
                }

            if row["status"] == "UNUSED":
                await conn.execute("""
                    UPDATE licenses
                    SET
                        status='ACTIVE',
                        activated_at=$1,
                        machine_id=$2
                    WHERE id=$3
                """, now, hwid_hash_value, row["id"])

                return {
                    "success": True,
                    "code": "ACTIVATED",
                    "message": "License activated successfully.",
                    "expires_at": row["expires_at"].isoformat(),
                }

            if row["status"] == "ACTIVE":
                stored_hwid = str(row["machine_id"] or "")

                if not stored_hwid:
                    return {
                        "success": False,
                        "code": "INVALID_BINDING",
                        "message": "License is active but has no HWID binding.",
                    }

                if not secrets.compare_digest(
                    stored_hwid,
                    hwid_hash_value,
                ):
                    return {
                        "success": False,
                        "code": "HWID_MISMATCH",
                        "message": "This license is already bound to another computer.",
                    }

                return {
                    "success": True,
                    "code": "VALID",
                    "message": "License verified successfully.",
                    "expires_at": row["expires_at"].isoformat(),
                }

    return {
        "success": False,
        "code": "INVALID_STATUS",
        "message": "License cannot be activated.",
    }


async def validate_license(license_key: str, hwid: str):
    if db_pool is None:
        return {
            "success": False,
            "code": "DATABASE_OFFLINE",
            "message": "License database unavailable.",
        }

    license_key = str(license_key or "").strip()
    hwid = normalize_hwid(hwid)

    if not license_key or not hwid:
        return {
            "success": False,
            "code": "INVALID_REQUEST",
            "message": "License key and HWID are required.",
        }

    row = await get_license(license_key)

    if row is None:
        return {
            "success": False,
            "code": "INVALID_KEY",
            "message": "Invalid license key.",
        }

    now = utc_now()

    if row["expires_at"] <= now:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE licenses SET status='EXPIRED' WHERE id=$1",
                row["id"],
            )

        return {
            "success": False,
            "code": "EXPIRED",
            "message": "This license has expired.",
        }

    if row["status"] == "REVOKED":
        return {
            "success": False,
            "code": "REVOKED",
            "message": "This license has been revoked.",
        }

    if row["status"] == "SUSPENDED":
        return {
            "success": False,
            "code": "SUSPENDED",
            "message": "This license has been restricted.",
        }

    if row["status"] != "ACTIVE":
        return {
            "success": False,
            "code": "NOT_ACTIVATED",
            "message": "License has not been activated.",
        }

    stored_hwid = str(row["machine_id"] or "")
    supplied_hwid = hash_hwid(hwid)

    if not stored_hwid or not secrets.compare_digest(
        stored_hwid,
        supplied_hwid,
    ):
        return {
            "success": False,
            "code": "HWID_MISMATCH",
            "message": "This license is bound to another computer.",
        }

    return {
        "success": True,
        "code": "VALID",
        "message": "License is valid.",
        "expires_at": row["expires_at"].isoformat(),
    }

# ============================================================
# FEEDBACK
# ============================================================

async def get_active_license_for_request(license_key, hwid):
    row = await get_license(license_key)

    if row is None:
        return None, "Invalid license key."

    if row["status"] == "REVOKED":
        return None, "This license has been revoked."

    if row["status"] == "SUSPENDED":
        return None, "This license has been restricted."

    if row["status"] != "ACTIVE":
        return None, "License is not active."

    if row["expires_at"] <= utc_now():
        return None, "This license has expired."

    stored = str(row["machine_id"] or "")
    supplied = hash_hwid(hwid)

    if not stored or not secrets.compare_digest(stored, supplied):
        return None, "HWID mismatch."

    return row, ""


async def api_feedback_submit(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({
            "success": False,
            "message": "Invalid JSON.",
        }, status=400)

    license_row, error = await get_active_license_for_request(
        data.get("license_key", ""),
        data.get("hwid", ""),
    )

    if license_row is None:
        return web.json_response({
            "success": False,
            "message": error,
        }, status=403)

    message = str(data.get("message", "")).strip()
    category = str(data.get("category", "Other")).strip()[:40] or "Other"
    profile_name = str(data.get("profile_name", "")).strip()[:80]

    if len(message) < 5:
        return web.json_response({
            "success": False,
            "message": "Feedback message is too short.",
        }, status=400)

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO feedback (
                license_id,
                category,
                message,
                profile_name
            )
            VALUES ($1, $2, $3, $4)
            RETURNING id
        """, license_row["id"], category, message[:4000], profile_name)

    return web.json_response({
        "success": True,
        "feedback_id": int(row["id"]),
        "message": "Feedback submitted successfully.",
    })


async def api_feedback_poll(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({
            "success": False,
            "message": "Invalid JSON.",
        }, status=400)

    license_row, error = await get_active_license_for_request(
        data.get("license_key", ""),
        data.get("hwid", ""),
    )

    if license_row is None:
        return web.json_response({
            "success": False,
            "message": error,
        }, status=403)

    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                id,
                category,
                message,
                status,
                created_at,
                updated_at,
                admin_reply
            FROM feedback
            WHERE license_id=$1
            ORDER BY id DESC
            LIMIT 25
        """, license_row["id"])

    return web.json_response({
        "success": True,
        "feedback": [
            {
                "id": int(row["id"]),
                "category": row["category"],
                "message": row["message"],
                "status": row["status"].lower(),
                "created_at": row["created_at"].isoformat(),
                "updated_at": row["updated_at"].isoformat(),
                "admin_reply": row["admin_reply"],
            }
            for row in rows
        ],
    })

# ============================================================
# ADMIN API
# ============================================================

def require_admin_api(request):
    if not ADMIN_API_TOKEN:
        raise web.HTTPInternalServerError(
            text="ADMIN_API_TOKEN is not configured."
        )

    supplied = request.headers.get(
        "Authorization",
        "",
    )

    expected = f"Bearer {ADMIN_API_TOKEN}"

    if not secrets.compare_digest(
        supplied,
        expected,
    ):
        raise web.HTTPUnauthorized(
            text="Invalid administrator token."
        )


async def api_admin_auth(request):
    require_admin_api(request)

    return web.json_response({
        "success": True,
        "message": "Administrator authenticated.",
    })


async def api_admin_stats(request):
    require_admin_api(request)

    return web.json_response({
        "success": True,
        **(await get_stats()),
    })


async def api_admin_licenses(request):
    require_admin_api(request)

    await expire_licenses()

    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                id,
                created_at,
                expires_at,
                activated_at,
                discord_user_id,
                machine_id,
                status
            FROM licenses
            ORDER BY id DESC
        """)

    return web.json_response({
        "success": True,
        "licenses": [
            {
                "id": int(row["id"]),
                "created_at": row["created_at"].isoformat(),
                "expires_at": row["expires_at"].isoformat(),
                "activated_at": (
                    row["activated_at"].isoformat()
                    if row["activated_at"] else None
                ),
                "discord_user_id": row["discord_user_id"],
                "machine_id": row["machine_id"],
                "status": row["status"],
            }
            for row in rows
        ],
    })


async def api_admin_license_generate(request):
    require_admin_api(request)

    try:
        data = await request.json()
        duration = str(data.get("duration", "")).strip()
        delta = parse_duration(duration)
    except Exception as exc:
        raise web.HTTPBadRequest(text=str(exc))

    key_value = generate_license_key()
    created = utc_now()
    expires = created + delta

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO licenses (
                key_hash,
                created_at,
                expires_at,
                status
            )
            VALUES ($1, $2, $3, 'UNUSED')
            RETURNING id
        """, hash_key(key_value), created, expires)

    return web.json_response({
        "success": True,
        "license_id": int(row["id"]),
        "license_key": key_value,
        "duration": duration,
        "expires_at": expires.isoformat(),
        "status": "UNUSED",
    })


async def api_admin_license_info(request):
    require_admin_api(request)

    try:
        data = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Invalid JSON.")

    license_key = str(
        data.get("license_key", "")
    ).strip()

    row = await get_license(license_key)

    if row is None:
        raise web.HTTPNotFound(text="License not found.")

    return web.json_response({
        "success": True,
        "id": int(row["id"]),
        "status": row["status"],
        "created_at": row["created_at"].isoformat(),
        "expires_at": row["expires_at"].isoformat(),
        "activated_at": (
            row["activated_at"].isoformat()
            if row["activated_at"] else None
        ),
        "discord_user_id": row["discord_user_id"],
        "hwid_bound": bool(row["machine_id"]),
    })


async def api_admin_license_action(request):
    require_admin_api(request)

    try:
        data = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Invalid JSON.")

    action = str(
        data.get("action", "")
    ).strip().lower()

    try:
        license_id = int(data.get("license_id"))
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(text="Invalid license_id.")

    row = await get_license_by_id(license_id)

    if row is None:
        raise web.HTTPNotFound(text="License not found.")

    if action == "suspend":
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE licenses SET status='SUSPENDED' WHERE id=$1",
                license_id,
            )
        return web.json_response({
            "success": True,
            "message": "License restricted.",
            "status": "SUSPENDED",
        })

    if action == "restore":
        if row["expires_at"] <= utc_now():
            status = "EXPIRED"
        elif row["activated_at"]:
            status = "ACTIVE"
        else:
            status = "UNUSED"

        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE licenses SET status=$1 WHERE id=$2",
                status,
                license_id,
            )

        return web.json_response({
            "success": True,
            "message": "License restored.",
            "status": status,
        })

    if action == "revoke":
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE licenses SET status='REVOKED' WHERE id=$1",
                license_id,
            )

        return web.json_response({
            "success": True,
            "message": "License revoked.",
            "status": "REVOKED",
        })

    if action == "reset_hwid":
        async with db_pool.acquire() as conn:
            await conn.execute("""
                UPDATE licenses
                SET
                    status='UNUSED',
                    activated_at=NULL,
                    machine_id=NULL
                WHERE id=$1
            """, license_id)

        return web.json_response({
            "success": True,
            "message": "HWID binding reset.",
            "status": "UNUSED",
        })

    if action == "delete":
        async with db_pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM licenses WHERE id=$1",
                license_id,
            )

        return web.json_response({
            "success": True,
            "message": "License deleted.",
        })

    raise web.HTTPBadRequest(text="Unknown license action.")


async def api_admin_feedback(request):
    require_admin_api(request)

    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                f.id,
                f.license_id,
                f.category,
                f.message,
                f.profile_name,
                f.status,
                f.created_at,
                f.updated_at,
                f.admin_reply,
                f.replied_by,
                l.discord_user_id
            FROM feedback f
            JOIN licenses l ON l.id=f.license_id
            ORDER BY f.id DESC
            LIMIT 200
        """)

    return web.json_response({
        "success": True,
        "feedback": [
            {
                "id": int(row["id"]),
                "license_id": int(row["license_id"]),
                "category": row["category"],
                "message": row["message"],
                "profile_name": row["profile_name"],
                "status": row["status"],
                "created_at": row["created_at"].isoformat(),
                "updated_at": row["updated_at"].isoformat(),
                "admin_reply": row["admin_reply"],
                "replied_by": row["replied_by"],
                "discord_user_id": row["discord_user_id"],
            }
            for row in rows
        ],
    })


async def api_admin_feedback_reply(request):
    require_admin_api(request)

    try:
        data = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Invalid JSON.")

    try:
        feedback_id = int(data.get("feedback_id"))
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(text="Invalid feedback_id.")

    reply = str(data.get("reply", "")).strip()
    status = str(
        data.get("status", "IN_PROGRESS")
    ).upper().strip()

    if not reply:
        raise web.HTTPBadRequest(text="Reply is required.")

    if status not in {
        "OPEN",
        "IN_PROGRESS",
        "RESOLVED",
        "CLOSED",
    }:
        raise web.HTTPBadRequest(text="Invalid feedback status.")

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            UPDATE feedback
            SET
                admin_reply=$1,
                status=$2,
                replied_by=$3,
                updated_at=NOW()
            WHERE id=$4
            RETURNING id
        """, reply[:4000], status, data.get("replied_by"), feedback_id)

    if row is None:
        raise web.HTTPNotFound(text="Feedback ticket not found.")

    return web.json_response({
        "success": True,
        "feedback_id": int(row["id"]),
        "status": status,
    })

# ============================================================
# HTTP SERVER
# ============================================================

async def api_root(request):
    db = await check_database()
    return web.json_response({
        "status": "online",
        "service": "GUARDIAN API",
        "version": "1.3.0",
        "discord_bot": bot.is_ready(),
        "database": db["online"],
    })


async def api_health(request):
    db = await check_database()
    healthy = db["online"]

    return web.json_response({
        "status": "healthy" if healthy else "degraded",
        "service": "GUARDIAN API",
        "database": {
            "status": "online" if healthy else "offline",
            "latency_ms": db["latency"],
        },
        "discord_bot": {"ready": bot.is_ready()},
    }, status=200 if healthy else 503)


async def api_simple_health(request):
    return web.json_response({
        "status": "healthy",
        "service": "GUARDIAN API",
    })


async def api_status(request):
    db = await check_database()
    return web.json_response({
        "status": "online",
        "service": "GUARDIAN API",
        "discord_bot": "online" if bot.is_ready() else "starting",
        "database": "online" if db["online"] else "offline",
        "database_latency_ms": db["latency"],
    })


async def api_simple_status(request):
    return web.json_response({
        "status": "online",
        "service": "GUARDIAN API",
    })


async def api_db_health(request):
    result = await check_database()

    if result["online"]:
        return web.json_response({
            "status": "healthy",
            "database": "online",
            "latency_ms": result["latency"],
            "response": 1,
        })

    return web.json_response({
        "status": "error",
        "database": "offline",
        "error": result["message"],
    }, status=503)


async def start_http_server():
    global http_runner, http_site

    if http_runner is not None:
        print("HTTP API already running; skipping duplicate start.")
        return

    app = web.Application()

    app.router.add_get("/", api_root)
    app.router.add_get("/health", api_simple_health)
    app.router.add_get("/api/health", api_health)
    app.router.add_get("/status", api_simple_status)
    app.router.add_get("/api/status", api_status)
    app.router.add_get("/health/db", api_db_health)

    app.router.add_post(
        "/api/license/activate",
        api_license_activate,
    )
    app.router.add_post(
        "/api/license/validate",
        api_license_validate,
    )

    app.router.add_post(
        "/api/feedback/submit",
        api_feedback_submit,
    )
    app.router.add_post(
        "/api/feedback/poll",
        api_feedback_poll,
    )

    app.router.add_get(
        "/api/admin/auth",
        api_admin_auth,
    )
    app.router.add_get(
        "/api/admin/stats",
        api_admin_stats,
    )
    app.router.add_get(
        "/api/admin/licenses",
        api_admin_licenses,
    )
    app.router.add_post(
        "/api/admin/license/generate",
        api_admin_license_generate,
    )
    app.router.add_post(
        "/api/admin/license/info",
        api_admin_license_info,
    )
    app.router.add_post(
        "/api/admin/license/action",
        api_admin_license_action,
    )
    app.router.add_get(
        "/api/admin/feedback",
        api_admin_feedback,
    )
    app.router.add_post(
        "/api/admin/feedback/reply",
        api_admin_feedback_reply,
    )

    http_runner = web.AppRunner(app)
    await http_runner.setup()

    try:
        http_site = web.TCPSite(
            http_runner,
            host="0.0.0.0",
            port=PORT,
        )
        await http_site.start()
    except Exception:
        await http_runner.cleanup()
        http_runner = None
        http_site = None
        raise

    print()
    print("=" * 60)
    print("GUARDIAN HTTP API")
    print("=" * 60)
    print(f"Listening on 0.0.0.0:{PORT}")
    print(f"Railway PORT: {PORT}")
    print("Public:")
    print("  POST /api/license/activate")
    print("  POST /api/license/validate")
    print("  POST /api/feedback/submit")
    print("  POST /api/feedback/poll")
    print("Admin:")
    print("  GET  /api/admin/auth")
    print("  GET  /api/admin/stats")
    print("  GET  /api/admin/licenses")
    print("  POST /api/admin/license/generate")
    print("  POST /api/admin/license/info")
    print("  POST /api/admin/license/action")
    print("  GET  /api/admin/feedback")
    print("  POST /api/admin/feedback/reply")
    print("=" * 60)
    print()


async def stop_http_server():
    global http_runner, http_site

    if http_runner is not None:
        print("Stopping HTTP API...")
        await http_runner.cleanup()
        http_runner = None
        http_site = None
        print("HTTP API stopped.")

# ============================================================
# DISCORD DASHBOARD
# ============================================================

async def get_config(guild_id: int):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM settings WHERE guild_id=$1",
            guild_id,
        )


async def save_config(
    guild_id: int,
    channel_id: int,
    message_id: int,
):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO settings (
                guild_id,
                dashboard_channel_id,
                dashboard_message_id
            )
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id)
            DO UPDATE SET
                dashboard_channel_id=EXCLUDED.dashboard_channel_id,
                dashboard_message_id=EXCLUDED.dashboard_message_id
        """, guild_id, channel_id, message_id)


async def dashboard_embed():
    stats = await get_stats()
    db = await check_database()

    embed = discord.Embed(
        title="🔴 GUARDIAN LICENSE DATABASE",
        description="Live GUARDIAN license statistics.",
        color=discord.Color.from_rgb(190, 25, 35),
        timestamp=utc_now(),
    )

    for name, value in [
        ("📊 Total Licenses", stats["TOTAL"]),
        ("🟢 Active", stats["ACTIVE"]),
        ("🟡 Unused", stats["UNUSED"]),
        ("🔵 Expired", stats["EXPIRED"]),
        ("🔴 Revoked", stats["REVOKED"]),
        ("🟠 Suspended", stats["SUSPENDED"]),
    ]:
        embed.add_field(
            name=name,
            value=f"`{value}`",
            inline=True,
        )

    embed.add_field(
        name="🗄️ Database",
        value=(
            f"`ONLINE` • `{db['latency']}ms`"
            if db["online"]
            else "`OFFLINE`"
        ),
        inline=True,
    )

    embed.set_footer(
        text="GUARDIAN License System • Automatic refresh every 60 seconds"
    )

    return embed


async def update_dashboard(guild_id: int):
    row = await get_config(guild_id)

    if not row:
        return

    channel = bot.get_channel(row["dashboard_channel_id"])

    if channel is None:
        try:
            channel = await bot.fetch_channel(
                row["dashboard_channel_id"]
            )
        except discord.DiscordException:
            return

    embed = await dashboard_embed()

    try:
        message = await channel.fetch_message(
            row["dashboard_message_id"]
        )
        await message.edit(embed=embed)

    except discord.NotFound:
        try:
            message = await channel.send(embed=embed)
            await save_config(
                guild_id,
                channel.id,
                message.id,
            )
        except discord.DiscordException:
            pass

    except discord.DiscordException as exc:
        print(
            f"Dashboard update failed for guild {guild_id}: {exc}"
        )


@tasks.loop(seconds=60)
async def dashboard_loop():
    if not bot.is_ready():
        return

    for guild in bot.guilds:
        try:
            await update_dashboard(guild.id)
        except Exception as exc:
            print(
                f"Dashboard loop error for guild {guild.id}: {exc}"
            )


@dashboard_loop.before_loop
async def before_dashboard_loop():
    await bot.wait_until_ready()

# ============================================================
# BOT
# ============================================================

class GuardianBot(commands.Bot):

    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=discord.Intents.default(),
        )

    async def setup_hook(self):
        await init_database()
        await start_http_server()
        await self.tree.sync()

        if not dashboard_loop.is_running():
            dashboard_loop.start()

        print("Slash commands synchronized.")

    async def close(self):
        if dashboard_loop.is_running():
            dashboard_loop.cancel()

        await stop_http_server()
        await close_database()
        await super().close()

    async def on_ready(self):
        print()
        print("=" * 60)
        print("GUARDIAN ONLINE")
        print("=" * 60)
        print(f"Discord: {self.user} ({self.user.id})")
        print(f"API PORT: {PORT}")
        print(f"Guilds: {len(self.guilds)}")
        print("=" * 60)
        print()


bot = GuardianBot()

# ============================================================
# PERMISSIONS
# ============================================================

def is_admin(interaction: discord.Interaction) -> bool:
    if OWNER_ID and interaction.user.id == OWNER_ID:
        return True

    return (
        isinstance(interaction.user, discord.Member)
        and interaction.user.guild_permissions.administrator
    )


async def require_admin(interaction: discord.Interaction) -> bool:
    if is_admin(interaction):
        return True

    if interaction.response.is_done():
        await interaction.followup.send(
            "❌ Administrator permission required.",
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            "❌ Administrator permission required.",
            ephemeral=True,
        )

    return False

# ============================================================
# /GUARDIAN
# ============================================================

guardian = app_commands.Group(
    name="guardian",
    description="GUARDIAN administration",
)


@guardian.command(
    name="api-status",
    description="Test the GUARDIAN HTTP API.",
)
async def guardian_api_status(interaction: discord.Interaction):
    if not await require_admin(interaction):
        return

    await interaction.response.defer(ephemeral=True)
    started = time.perf_counter()

    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                f"http://127.0.0.1:{PORT}/health"
            ) as response:
                body = await response.text()

        latency = (time.perf_counter() - started) * 1000

        embed = discord.Embed(
            title=(
                "🟢 GUARDIAN API STATUS"
                if response.status == 200
                else "🟡 GUARDIAN API STATUS"
            ),
            color=(
                discord.Color.green()
                if response.status == 200
                else discord.Color.orange()
            ),
        )
        embed.add_field(
            name="Status",
            value="`ONLINE`" if response.status == 200 else "`DEGRADED`",
        )
        embed.add_field(
            name="HTTP",
            value=f"`{response.status}`",
        )
        embed.add_field(
            name="Latency",
            value=f"`{latency:.2f}ms`",
        )
        embed.add_field(
            name="Response",
            value=f"```json\n{body[:1000]}\n```",
            inline=False,
        )

    except Exception as exc:
        embed = discord.Embed(
            title="🔴 GUARDIAN API STATUS",
            color=discord.Color.red(),
        )
        embed.add_field(name="Status", value="`OFFLINE`")
        embed.add_field(
            name="Error",
            value=f"```text\n{str(exc)[:1000]}\n```",
            inline=False,
        )

    await interaction.followup.send(
        embed=embed,
        ephemeral=True,
    )


@guardian.command(
    name="db-status",
    description="Test the GUARDIAN PostgreSQL database.",
)
async def guardian_db_status(interaction: discord.Interaction):
    if not await require_admin(interaction):
        return

    result = await check_database()

    if result["online"]:
        embed = discord.Embed(
            title="🟢 DATABASE STATUS",
            color=discord.Color.green(),
        )
        embed.add_field(name="Status", value="`ONLINE`")
        embed.add_field(name="Latency", value=f"`{result['latency']}ms`")
        embed.add_field(name="Response", value="`SELECT 1` → `1`")
    else:
        embed = discord.Embed(
            title="🔴 DATABASE STATUS",
            color=discord.Color.red(),
        )
        embed.add_field(name="Status", value="`OFFLINE`")
        embed.add_field(
            name="Error",
            value=f"```{result['message'][:1000]}```",
        )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


@guardian.command(
    name="dashboard",
    description="Create or move the live GUARDIAN dashboard.",
)
@app_commands.describe(
    channel="Channel where the dashboard should appear.",
)
async def guardian_dashboard(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
):
    if not await require_admin(interaction):
        return

    await interaction.response.defer(ephemeral=True)

    old = await get_config(interaction.guild_id)

    if old:
        old_channel = bot.get_channel(
            old["dashboard_channel_id"]
        )
        if old_channel:
            try:
                old_message = await old_channel.fetch_message(
                    old["dashboard_message_id"]
                )
                await old_message.delete()
            except discord.DiscordException:
                pass

    message = await channel.send(
        embed=await dashboard_embed()
    )

    await save_config(
        interaction.guild_id,
        channel.id,
        message.id,
    )

    await interaction.followup.send(
        f"✅ Dashboard configured in {channel.mention}.",
        ephemeral=True,
    )


@guardian.command(
    name="refresh",
    description="Immediately refresh the dashboard.",
)
async def guardian_refresh(interaction: discord.Interaction):
    if not await require_admin(interaction):
        return

    await update_dashboard(interaction.guild_id)

    await interaction.response.send_message(
        "✅ Dashboard refreshed.",
        ephemeral=True,
    )


@guardian.command(
    name="dashboard-remove",
    description="Remove the configured dashboard.",
)
async def guardian_dashboard_remove(
    interaction: discord.Interaction,
):
    if not await require_admin(interaction):
        return

    row = await get_config(interaction.guild_id)

    if row:
        channel = bot.get_channel(
            row["dashboard_channel_id"]
        )

        if channel:
            try:
                message = await channel.fetch_message(
                    row["dashboard_message_id"]
                )
                await message.delete()
            except discord.DiscordException:
                pass

        async with db_pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM settings WHERE guild_id=$1",
                interaction.guild_id,
            )

    await interaction.response.send_message(
        "✅ Dashboard removed.",
        ephemeral=True,
    )


bot.tree.add_command(guardian)

# ============================================================
# /KEY
# ============================================================

key_group = app_commands.Group(
    name="key",
    description="GUARDIAN license management",
)


@key_group.command(
    name="generate",
    description="Generate a GUARDIAN license key.",
)
@app_commands.describe(
    duration="Examples: 30d, 90d, 1y",
)
async def key_generate(
    interaction: discord.Interaction,
    duration: str,
):
    if not await require_admin(interaction):
        return

    try:
        delta = parse_duration(duration)
    except ValueError as exc:
        await interaction.response.send_message(
            f"❌ {exc}",
            ephemeral=True,
        )
        return

    key_value = generate_license_key()
    created = utc_now()
    expires = created + delta

    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO licenses (
                key_hash,
                created_at,
                expires_at,
                status
            )
            VALUES ($1, $2, $3, 'UNUSED')
        """, hash_key(key_value), created, expires)

    embed = discord.Embed(
        title="🔑 GUARDIAN LICENSE GENERATED",
        color=discord.Color.from_rgb(190, 25, 35),
    )
    embed.add_field(
        name="License Key",
        value=f"```{key_value}```",
        inline=False,
    )
    embed.add_field(
        name="Duration",
        value=f"`{duration}`",
    )
    embed.add_field(
        name="Expires",
        value=discord_timestamp(expires),
    )
    embed.add_field(
        name="Status",
        value="`UNUSED`",
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


@key_group.command(
    name="check",
    description="Check a GUARDIAN license.",
)
@app_commands.describe(
    key="Complete GUARDIAN license key.",
)
async def key_check(
    interaction: discord.Interaction,
    key: str,
):
    if not await require_admin(interaction):
        return

    row = await get_license(key)

    if not row:
        await interaction.response.send_message(
            "❌ License not found.",
            ephemeral=True,
        )
        return

    if (
        row["status"] in ("UNUSED", "ACTIVE")
        and row["expires_at"] <= utc_now()
    ):
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE licenses SET status='EXPIRED' WHERE id=$1",
                row["id"],
            )
        row = await get_license(key)

    embed = discord.Embed(
        title="🔑 GUARDIAN LICENSE",
        color=discord.Color.from_rgb(190, 25, 35),
    )
    embed.add_field(name="Status", value=f"`{row['status']}`")
    embed.add_field(name="Expires", value=discord_timestamp(row["expires_at"]))
    embed.add_field(
        name="Discord User",
        value=(
            f"`{row['discord_user_id']}`"
            if row["discord_user_id"]
            else "`Not linked`"
        ),
    )
    embed.add_field(
        name="HWID",
        value="`BOUND`" if row["machine_id"] else "`NOT BOUND`",
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


@key_group.command(
    name="link",
    description="Associate a license with a Discord user.",
)
@app_commands.describe(
    key="Complete GUARDIAN license key.",
    user="Discord user to associate with the license.",
)
async def key_link(
    interaction: discord.Interaction,
    key: str,
    user: discord.User,
):
    if not await require_admin(interaction):
        return

    row = await get_license(key)

    if not row:
        await interaction.response.send_message(
            "❌ License not found.",
            ephemeral=True,
        )
        return

    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE licenses SET discord_user_id=$1 WHERE id=$2",
            user.id,
            row["id"],
        )

    await interaction.response.send_message(
        f"✅ License `#{row['id']}` linked to {user.mention}.",
        ephemeral=True,
    )


@key_group.command(
    name="revoke",
    description="Revoke a GUARDIAN license.",
)
@app_commands.describe(
    key="Complete GUARDIAN license key.",
)
async def key_revoke(
    interaction: discord.Interaction,
    key: str,
):
    if not await require_admin(interaction):
        return

    async with db_pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE licenses
            SET status='REVOKED'
            WHERE key_hash=$1
              AND status!='REVOKED'
        """, hash_key(key))

    await interaction.response.send_message(
        "🔴 License revoked."
        if result.endswith("1")
        else "❌ License not found or already revoked.",
        ephemeral=True,
    )


@key_group.command(
    name="unrevoke",
    description="Restore a revoked or suspended license.",
)
@app_commands.describe(
    key="Complete GUARDIAN license key.",
)
async def key_unrevoke(
    interaction: discord.Interaction,
    key: str,
):
    if not await require_admin(interaction):
        return

    row = await get_license(key)

    if not row:
        await interaction.response.send_message(
            "❌ License not found.",
            ephemeral=True,
        )
        return

    if row["expires_at"] <= utc_now():
        status = "EXPIRED"
    elif row["activated_at"]:
        status = "ACTIVE"
    else:
        status = "UNUSED"

    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE licenses SET status=$1 WHERE id=$2",
            status,
            row["id"],
        )

    await interaction.response.send_message(
        f"🟢 License restored as `{status}`.",
        ephemeral=True,
    )


@key_group.command(
    name="extend",
    description="Extend a GUARDIAN license.",
)
@app_commands.describe(
    key="Complete GUARDIAN license key.",
    duration="Examples: 30d, 90d, 1y",
)
async def key_extend(
    interaction: discord.Interaction,
    key: str,
    duration: str,
):
    if not await require_admin(interaction):
        return

    try:
        delta = parse_duration(duration)
    except ValueError as exc:
        await interaction.response.send_message(
            f"❌ {exc}",
            ephemeral=True,
        )
        return

    row = await get_license(key)

    if not row:
        await interaction.response.send_message(
            "❌ License not found.",
            ephemeral=True,
        )
        return

    new_expiry = max(
        row["expires_at"],
        utc_now(),
    ) + delta

    status = row["status"]
    if status == "EXPIRED":
        status = "ACTIVE" if row["activated_at"] else "UNUSED"

    async with db_pool.acquire() as conn:
        await conn.execute("""
            UPDATE licenses
            SET
                expires_at=$1,
                status=$2
            WHERE id=$3
        """, new_expiry, status, row["id"])

    await interaction.response.send_message(
        "✅ Extended. "
        f"New expiry: {discord_timestamp(new_expiry)}",
        ephemeral=True,
    )


@key_group.command(
    name="delete",
    description="Permanently delete a license record.",
)
@app_commands.describe(
    key="Complete GUARDIAN license key.",
)
async def key_delete(
    interaction: discord.Interaction,
    key: str,
):
    if not await require_admin(interaction):
        return

    async with db_pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM licenses WHERE key_hash=$1",
            hash_key(key),
        )

    await interaction.response.send_message(
        "🗑️ License deleted."
        if result.endswith("1")
        else "❌ License not found.",
        ephemeral=True,
    )


bot.tree.add_command(key_group)

# ============================================================
# /HWID
# ============================================================

hwid_group = app_commands.Group(
    name="hwid",
    description="GUARDIAN HWID management",
)


@hwid_group.command(
    name="reset",
    description="Reset the HWID binding of a GUARDIAN license.",
)
@app_commands.describe(
    license="Complete GUARDIAN license key.",
)
async def hwid_reset(
    interaction: discord.Interaction,
    license: str,
):
    if not await require_admin(interaction):
        return

    license = license.strip()
    row = await get_license(license)

    if not row:
        await interaction.response.send_message(
            "❌ License not found.",
            ephemeral=True,
        )
        return

    if row["status"] == "REVOKED":
        await interaction.response.send_message(
            "❌ This license is revoked.",
            ephemeral=True,
        )
        return

    if not row["machine_id"]:
        await interaction.response.send_message(
            "⚠️ This license does not currently have an HWID bound to it.",
            ephemeral=True,
        )
        return

    async with db_pool.acquire() as conn:
        await conn.execute("""
            UPDATE licenses
            SET
                machine_id=NULL,
                activated_at=NULL,
                status='UNUSED'
            WHERE id=$1
        """, row["id"])

    await interaction.response.send_message(
        f"✅ HWID reset for license `#{row['id']}`. It is now `UNUSED`.",
        ephemeral=True,
    )


@hwid_group.command(
    name="see",
    description="View HWID information for a GUARDIAN license.",
)
@app_commands.describe(
    license="Complete GUARDIAN license key.",
)
async def hwid_see(
    interaction: discord.Interaction,
    license: str,
):
    if not await require_admin(interaction):
        return

    license = license.strip()
    row = await get_license(license)

    if not row:
        await interaction.response.send_message(
            "❌ License not found.",
            ephemeral=True,
        )
        return

    if (
        row["status"] in ("UNUSED", "ACTIVE")
        and row["expires_at"] <= utc_now()
    ):
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE licenses SET status='EXPIRED' WHERE id=$1",
                row["id"],
            )
        row = await get_license(license)

    machine_id = str(row["machine_id"] or "")

    embed = discord.Embed(
        title="🖥️ GUARDIAN HWID INFORMATION",
        color=discord.Color.from_rgb(190, 25, 35),
        timestamp=utc_now(),
    )
    embed.add_field(
        name="License",
        value=f"`#{row['id']}`",
    )
    embed.add_field(
        name="License Status",
        value=f"`{row['status']}`",
    )
    embed.add_field(
        name="HWID Status",
        value="🟢 `BOUND`" if machine_id else "⚪ `NOT BOUND`",
    )
    embed.add_field(
        name="HWID Hash",
        value=f"`{machine_id}`" if machine_id else "`None`",
        inline=False,
    )
    embed.add_field(
        name="Activated",
        value=(
            discord_timestamp(row["activated_at"])
            if row["activated_at"]
            else "`Never`"
        ),
    )
    embed.add_field(
        name="Discord User",
        value=(
            f"<@{row['discord_user_id']}>"
            if row["discord_user_id"]
            else "`Not linked`"
        ),
    )
    embed.add_field(
        name="Expires",
        value=discord_timestamp(row["expires_at"]),
        inline=False,
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


bot.tree.add_command(hwid_group)

# ============================================================
# /USER
# ============================================================

@bot.tree.command(
    name="user",
    description="View GUARDIAN licenses associated with a Discord user.",
)
@app_commands.describe(
    user="Discord user to look up.",
)
async def user_lookup(
    interaction: discord.Interaction,
    user: discord.User,
):
    if not await require_admin(interaction):
        return

    await expire_licenses()

    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                id,
                expires_at,
                activated_at,
                machine_id,
                status
            FROM licenses
            WHERE discord_user_id=$1
            ORDER BY id DESC
        """, user.id)

    embed = discord.Embed(
        title="👤 GUARDIAN USER",
        description=f"License information for {user.mention}",
        color=discord.Color.from_rgb(190, 25, 35),
        timestamp=utc_now(),
    )

    embed.add_field(
        name="Discord",
        value=f"{user} • `{user.id}`",
        inline=False,
    )

    if not rows:
        embed.add_field(
            name="Licenses",
            value="`No linked licenses found.`",
            inline=False,
        )
    else:
        for row in rows[:20]:
            embed.add_field(
                name=f"License #{row['id']}",
                value=(
                    f"Status: `{row['status']}`\n"
                    f"Expires: {discord_timestamp(row['expires_at'])}\n"
                    f"HWID: `{'BOUND' if row['machine_id'] else 'NOT BOUND'}`"
                ),
                inline=False,
            )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )

# ============================================================
# /FEEDBACK
# ============================================================

feedback_group = app_commands.Group(
    name="feedback",
    description="GUARDIAN beta feedback management",
)


@feedback_group.command(
    name="list",
    description="List recent GUARDIAN feedback tickets.",
)
async def feedback_list(
    interaction: discord.Interaction,
):
    if not await require_admin(interaction):
        return

    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                id,
                license_id,
                category,
                status,
                message,
                profile_name,
                created_at
            FROM feedback
            ORDER BY id DESC
            LIMIT 10
        """)

    embed = discord.Embed(
        title="✉️ GUARDIAN FEEDBACK",
        color=discord.Color.from_rgb(190, 25, 35),
        timestamp=utc_now(),
    )

    if not rows:
        embed.description = "No feedback tickets yet."
    else:
        for row in rows:
            name = (
                f"#{row['id']} • {row['category']} • {row['status']}"
            )
            value = (
                f"License: `#{row['license_id']}`\n"
                f"User: `{row['profile_name'] or 'Unknown'}`\n"
                f"{row['message'][:700]}"
            )
            embed.add_field(
                name=name,
                value=value,
                inline=False,
            )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


@feedback_group.command(
    name="reply",
    description="Reply to a GUARDIAN feedback ticket.",
)
@app_commands.describe(
    ticket="Feedback ticket ID.",
    message="Reply to send to the user.",
    status="OPEN, IN_PROGRESS, RESOLVED, or CLOSED.",
)
async def feedback_reply(
    interaction: discord.Interaction,
    ticket: int,
    message: str,
    status: str = "IN_PROGRESS",
):
    if not await require_admin(interaction):
        return

    status = status.upper().strip()

    if status not in {
        "OPEN",
        "IN_PROGRESS",
        "RESOLVED",
        "CLOSED",
    }:
        await interaction.response.send_message(
            "❌ Invalid status.",
            ephemeral=True,
        )
        return

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            UPDATE feedback
            SET
                admin_reply=$1,
                status=$2,
                replied_by=$3,
                updated_at=NOW()
            WHERE id=$4
            RETURNING id, license_id
        """, message[:4000], status, interaction.user.id, ticket)

    if row is None:
        await interaction.response.send_message(
            "❌ Feedback ticket not found.",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        f"✅ Reply sent to ticket `#{ticket}` for license `#{row['license_id']}`.",
        ephemeral=True,
    )


@feedback_group.command(
    name="close",
    description="Close a GUARDIAN feedback ticket.",
)
@app_commands.describe(
    ticket="Feedback ticket ID.",
)
async def feedback_close(
    interaction: discord.Interaction,
    ticket: int,
):
    if not await require_admin(interaction):
        return

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            UPDATE feedback
            SET status='CLOSED', updated_at=NOW()
            WHERE id=$1
            RETURNING id
        """, ticket)

    await interaction.response.send_message(
        "✅ Ticket closed."
        if row
        else "❌ Feedback ticket not found.",
        ephemeral=True,
    )


bot.tree.add_command(feedback_group)

# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    print()
    print("=" * 60)
    print("STARTING GUARDIAN")
    print("=" * 60)
    print(f"Railway PORT: {PORT}")
    print("=" * 60)
    print()

    try:
        bot.run(TOKEN)
    except KeyboardInterrupt:
        print("GUARDIAN stopped.")
