
import asyncio
import os
import logging
from datetime import datetime

import psycopg
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

# -----------------------------
# CONFIGURATION
# -----------------------------

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DATABASE_URL = os.getenv("DATABASE_URL")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN is missing from .env")

if not ADMIN_ID:
    raise RuntimeError("ADMIN_ID is missing from .env")

if not CHANNEL_ID:
    raise RuntimeError("CHANNEL_ID is missing from .env")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing from .env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MatchVision")

dp = Dispatcher()


# -----------------------------
# DATABASE
# -----------------------------

def get_db():
    return psycopg.connect(DATABASE_URL)


def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS matches (
                    id BIGSERIAL PRIMARY KEY,
                    team_a TEXT NOT NULL,
                    team_b TEXT NOT NULL,
                    match_date TEXT NOT NULL,
                    prediction TEXT NOT NULL,
                    analysis TEXT NOT NULL,
                    status TEXT DEFAULT 'draft',
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    extra_analysis TEXT DEFAULT ''
                )
            """)

            # Safe migration for an older matches table
            cur.execute("""
                ALTER TABLE matches
                ADD COLUMN IF NOT EXISTS extra_analysis TEXT DEFAULT ''
            """)


# -----------------------------
# HELPERS
# -----------------------------

def is_admin(message: Message):
    return (
        message.from_user is not None
        and message.from_user.id == ADMIN_ID
    )


def main_menu():
    kb = InlineKeyboardBuilder()

    kb.button(
        text="⚽ التوقع المجاني | Free Prediction",
        callback_data="free"
    )

    kb.button(
        text="🔒 تحليلات إضافية | Extra Analysis",
        callback_data="extra"
    )

    kb.button(
        text="📊 الإحصائيات | Statistics",
        callback_data="stats"
    )

    kb.adjust(1)
    return kb.as_markup()


# -----------------------------
# START
# -----------------------------

@dp.message(CommandStart())
async def start(message: Message):

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (user_id, username)
                VALUES (%s, %s)
                ON CONFLICT (user_id)
                DO UPDATE SET username = EXCLUDED.username
            """, (
                message.from_user.id,
                message.from_user.username
            ))

    await message.answer(
        "⚽ Welcome to Match Vision!\n"
        "مرحباً بك في Match Vision!\n\n"
        "اختر الخدمة التي تريدها:",
        reply_markup=main_menu()
    )


# -----------------------------
# FREE PREDICTION
# -----------------------------

@dp.callback_query(F.data == "free")
async def free_prediction(call: CallbackQuery):

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT team_a, team_b, match_date,
                       prediction, analysis
                FROM matches
                WHERE status = 'published'
                ORDER BY id DESC
                LIMIT 1
            """)
            match = cur.fetchone()

    if match:
        team_a, team_b, match_date, prediction, analysis = match

        text = (
            "⚽ MATCH VISION | FREE PREDICTION\n\n"
            f"🏆 المباراة: {team_a} ضد {team_b}\n"
            f"📅 الموعد: {match_date}\n"
            f"🎯 التوقع: {prediction}\n\n"
            f"📊 التحليل المجاني:\n{analysis}\n\n"
            "⚠️ التوقعات تحليلية وليست ضماناً للنتائج."
        )
    else:
        text = "⚽ لا توجد توقعات منشورة حالياً."

    await call.message.answer(text)
    await call.answer()


# -----------------------------
# EXTRA ANALYSIS
# -----------------------------

@dp.callback_query(F.data == "extra")
async def extra_analysis(call: CallbackQuery):

    # Temporary testing: admin only
    if call.from_user.id != ADMIN_ID:
        await call.message.answer(
            "🔒 Extra Analysis\n\n"
            "هذا المحتوى مخصص للمشتركين.\n"
            "سيتم تفعيل نظام الوصول قريباً."
        )
        await call.answer()
        return

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT team_a, team_b, match_date, extra_analysis
                FROM matches
                WHERE status = 'published'
                ORDER BY id DESC
                LIMIT 1
            """)
            match = cur.fetchone()

    if not match:
        await call.message.answer(
            "لا توجد مباراة منشورة حالياً."
        )
    else:
        team_a, team_b, match_date, extra = match

        if not extra:
            extra = "لم تتم إضافة تحليل إضافي لهذه المباراة."

        await call.message.answer(
            "🔒 MATCH VISION | EXTRA ANALYSIS\n\n"
            f"⚽ المباراة: {team_a} ضد {team_b}\n"
            f"📅 الموعد: {match_date}\n\n"
            f"📊 التحليل الإضافي:\n{extra}"
        )

    await call.answer()


# -----------------------------
# STATISTICS
# -----------------------------

@dp.callback_query(F.data == "stats")
async def statistics(call: CallbackQuery):

    with get_db() as conn:
        with conn.cursor() as cur:

            cur.execute("SELECT COUNT(*) FROM users")
            users_count = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM matches")
            matches_count = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(*) FROM matches
                WHERE status = 'published'
            """)
            published_count = cur.fetchone()[0]

    await call.message.answer(
        f"👥 المستخدمون: {users_count}\n"
        f"⚽ المباريات المحفوظة: {matches_count}\n"
        f"📢 المباريات المنشورة: {published_count}"
    )

    await call.answer()


# -----------------------------
# MY ID
# -----------------------------

@dp.message(Command("myid"))
async def get_my_id(message: Message):

    await message.answer(
        f"Your Telegram ID: {message.from_user.id}"
    )


# -----------------------------
# CHECK CHANNEL
# -----------------------------

@dp.message(Command("checkchannel"))
async def check_channel(message: Message):

    if not is_admin(message):
        await message.answer("⛔ ليس لديك صلاحية.")
        return

    try:
        chat = await message.bot.get_chat(CHANNEL_ID)
        bot_info = await message.bot.get_me()

        member = await message.bot.get_chat_member(
            chat_id=chat.id,
            user_id=bot_info.id
        )

        result = (
            "✅ تم العثور على القناة!\n\n"
            f"اسم القناة: {chat.title}\n"
            f"Channel ID: {chat.id}\n"
            f"Bot status: {member.status}\n"
        )

        if member.status == "administrator":
            can_post = member.can_post_messages
            result += f"Can post messages: {can_post}"

            if can_post:
                result += "\n\n🎉 القناة جاهزة للنشر!"
            else:
                result += "\n\n⚠️ فعّل صلاحية Post Messages."

        elif member.status == "creator":
            result += "\nالقناة جاهزة."
        else:
            result += "\n\n❌ البوت ليس مسؤولاً في القناة."

        await message.answer(result)

    except Exception:
        logger.exception("Channel check failed")
        await message.answer(
            "❌ فشل الاتصال بالقناة. تحقق من إعداداتها وصلاحيات البوت."
        )


# -----------------------------
# ADD MATCH
# -----------------------------

@dp.message(Command("addmatch"))
async def add_match(message: Message):

    if not is_admin(message):
        await message.answer("⛔ ليس لديك صلاحية.")
        return

    if message.chat.type != "private":
        await message.answer(
            "استعمل الأمر في المحادثة الخاصة مع البوت."
        )
        return

    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        await message.answer(
            "⚽ طريقة إضافة مباراة:\n\n"
            "/addmatch Team A | Team B | 2026-11-21 20:00 | 1X | Free analysis | Extra analysis\n\n"
            "أدخل 6 معلومات مفصولة بعلامة |"
        )
        return

    fields = [item.strip() for item in parts[1].split("|")]

    if len(fields) != 6 or not all(fields):
        await message.answer(
            "❌ المعلومات غير مكتملة.\n\n"
            "استعمل الصيغة:\n"
            "/addmatch Team A | Team B | 2026-11-21 20:00 | 1X | Free analysis | Extra analysis"
        )
        return

    (
        team_a,
        team_b,
        match_date,
        prediction,
        analysis,
        extra_analysis_text
    ) = fields

    try:
        datetime.strptime(match_date, "%Y-%m-%d %H:%M")
    except ValueError:
        await message.answer(
            "❌ التاريخ غير صحيح.\n"
            "استعمل YYYY-MM-DD HH:MM"
        )
        return

    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO matches (
                        team_a, team_b, match_date,
                        prediction, analysis, extra_analysis
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    team_a,
                    team_b,
                    match_date,
                    prediction,
                    analysis,
                    extra_analysis_text
                ))

                match_id = cur.fetchone()[0]

    except Exception:
        logger.exception("Adding match failed")
        await message.answer("❌ فشل حفظ المباراة في قاعدة البيانات.")
        return

    await message.answer(
        "✅ تمت إضافة المباراة بنجاح!\n\n"
        f"رقم المباراة: {match_id}\n"
        f"⚽ {team_a} ضد {team_b}\n"
        f"📅 {match_date}\n"
        f"🎯 التوقع المجاني: {prediction}\n"
        "📊 التحليل المجاني: تم الحفظ\n"
        "🔒 التحليل الإضافي: تم الحفظ كخاص\n\n"
        f"للنشر استعمل:\n/publishmatch {match_id}"
    )


# -----------------------------
# LIST MATCHES
# -----------------------------

@dp.message(Command("matches"))
async def list_matches(message: Message):

    if not is_admin(message):
        await message.answer("⛔ ليس لديك صلاحية.")
        return

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, team_a, team_b, match_date,
                       prediction, status
                FROM matches
                ORDER BY id DESC
                LIMIT 15
            """)
            matches = cur.fetchall()

    if not matches:
        await message.answer("لا توجد مباريات محفوظة حالياً.")
        return

    text = "⚽ قائمة المباريات:\n\n"

    for item in matches:
        match_id, team_a, team_b, date, prediction, status = item

        status_text = (
            "منشورة" if status == "published" else "مسودة"
        )

        text += (
            f"رقم: {match_id}\n"
            f"{team_a} ضد {team_b}\n"
            f"📅 {date}\n"
            f"🎯 {prediction}\n"
            f"الحالة: {status_text}\n"
            "--------------------\n"
        )

    await message.answer(text)


# -----------------------------
# PUBLISH SAVED MATCH
# -----------------------------

@dp.message(Command("publishmatch"))
async def publish_match(message: Message):

    if not is_admin(message):
        await message.answer("⛔ ليس لديك صلاحية للنشر.")
        return

    if message.chat.type != "private":
        await message.answer(
            "استعمل الأمر في المحادثة الخاصة مع البوت."
        )
        return

    parts = message.text.split(maxsplit=1)

    if len(parts) < 2 or not parts[1].strip().isdigit():
        await message.answer(
            "طريقة النشر:\n"
            "/publishmatch 1\n\n"
            "استعمل رقم المباراة من /matches."
        )
        return

    match_id = int(parts[1].strip())

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT team_a, team_b, match_date,
                       prediction, analysis, status
                FROM matches
                WHERE id = %s
            """, (match_id,))
            match = cur.fetchone()

    if not match:
        await message.answer("❌ لم يتم العثور على هذه المباراة.")
        return

    team_a, team_b, match_date, prediction, analysis, status = match

    if status == "published":
        await message.answer("⚠️ هذه المباراة منشورة من قبل.")
        return

    post = (
        "⚽ MATCH VISION | FREE PREDICTION\n\n"
        f"🏆 Match: {team_a} vs {team_b}\n"
        f"📅 Date: {match_date}\n"
        f"🎯 Prediction: {prediction}\n\n"
        f"📊 Analysis: {analysis}\n\n"
        "⚠️ Predictions are not guaranteed results.\n"
        "Follow Match Vision for more analysis."
    )

    if len(post) > 4096:
        await message.answer("❌ المنشور أطول من الحد المسموح.")
        return

    try:
        sent = await message.bot.send_message(
            chat_id=CHANNEL_ID,
            text=post
        )

        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE matches
                    SET status = 'published'
                    WHERE id = %s
                """, (match_id,))

        await message.answer(
            "✅ تم نشر المباراة بنجاح!\n"
            f"رقم المباراة: {match_id}\n"
            f"Message ID: {sent.message_id}"
        )

    except Exception:
        logger.exception("Match publishing failed")
        await message.answer(
            "❌ فشل النشر. استعمل /checkchannel."
        )


# -----------------------------
# MANUAL PUBLISH
# -----------------------------

@dp.message(Command("publish"))
async def publish_prediction(message: Message):

    if not is_admin(message):
        await message.answer("⛔ ليس لديك صلاحية للنشر.")
        return

    if message.chat.type != "private":
        await message.answer(
            "استعمل أمر النشر في المحادثة الخاصة مع البوت."
        )
        return

    parts = message.text.split(maxsplit=1)
    prediction = parts[1].strip() if len(parts) > 1 else ""

    if not prediction:
        await message.answer(
            "⚽ طريقة النشر:\n\n"
            "/publish\n"
            "MATCH OF THE DAY\n"
            "Team A vs Team B\n"
            "Prediction: 1X"
        )
        return

    if len(prediction) > 4096:
        await message.answer(
            "❌ المنشور طويل جداً. الحد الأقصى 4096 حرفاً."
        )
        return

    try:
        sent = await message.bot.send_message(
            chat_id=CHANNEL_ID,
            text=prediction
        )

        await message.answer(
            "✅ تم النشر بنجاح!\n"
            f"Message ID: {sent.message_id}"
        )

    except Exception:
        logger.exception("Publishing failed")
        await message.answer(
            "❌ فشل النشر. استعمل /checkchannel."
        )


# -----------------------------
# START BOT
# -----------------------------

async def main():

    init_db()

    bot = Bot(token=TOKEN)

    print("⚽ Match Vision is running with Neon PostgreSQL...")

    try:
        await dp.start_polling(bot)

    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
