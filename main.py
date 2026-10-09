import asyncio
import json
import os
import re
import time
import random
import threading
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from PIL import Image, ImageDraw, ImageFont
import string
import logging
import urllib.request
import zipfile
import shutil
import urllib.parse
import urllib.error
import ssl
import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
import hashlib
import hmac
import fcntl
from datetime import datetime, timedelta

from telethon import TelegramClient, events, Button, functions, types
from telethon.network import ConnectionTcpIntermediate
from telethon.sessions import StringSession, MemorySession
from telethon.tl.types import (
    MessageEntityCustomEmoji, MessageEntityBold, MessageEntityItalic, 
    MessageEntityCode, MessageEntityPre, MessageEntityTextUrl, 
    MessageEntityMention, MessageEntityHashtag, MessageEntityUrl
)
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.errors import (
    SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError,
    FloodWaitError, PhoneNumberInvalidError, PhoneNumberBannedError,
    UserNotParticipantError, AuthKeyUnregisteredError, MessageNotModifiedError,
    RPCError
)

def _load_local_env():
    """تحميل قيم .env محليًا دون طباعة أي مفتاح أو قيمة سرية."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if not os.path.isfile(env_path):
        return
    try:
        with open(env_path, 'r', encoding='utf-8') as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        pass

_load_local_env()

# ================================
#  الثوابت والتعريفات الأساسية
# ================================
# ================================================================
#              إعدادات البوت — اكتب بياناتك هنا
# ================================================================
# رقم API ID — رقم فقط بدون علامات اقتباس
API_ID = 37045517  # مثال: 12345678

# API HASH — القيمة المقدمة للتشغيل الحالي
API_HASH = '5dbc88e84896daa2b65f9b60ae9ddbc1'
# BOT TOKEN — التوكن المقدم للتشغيل الحالي
BOT_TOKEN = '8604935351:AAFiyuLM9tZU-QBzTSod3wYi5M7iA5kuG2M'

# أرقام الأدمن — أرقام داخل قائمة
ADMINS = [8356292519]  # مثال: [123456789]
OWNER_ID = ADMINS[0]

if API_ID <= 0 or not API_HASH or API_HASH.startswith('ضع_'):
    raise RuntimeError('ضع API_ID وAPI_HASH في قسم إعدادات البوت أعلى الملف قبل التشغيل.')
if not BOT_TOKEN or BOT_TOKEN.startswith('ضع_'):
    raise RuntimeError('ضع BOT_TOKEN في قسم إعدادات البوت أعلى الملف قبل التشغيل.')
DEVELOPER_USER = "MOSCOW1081BOT"
LOG_CHANNEL_ID = -1004343876430

DEFAULT_FORCE_CHANNELS = [
    {"id": -1004394389297, "username": "MOSCOW100BOT", "title": "قناة التحديثات"},
    {"id": -1004343876430, "username": "MOSCOW8BOT", "title": "قناة التفعيلات"},
]
DB_FILE = "sliner_numbers_db.json"
DB_BACKUP_FILE = DB_FILE + ".bak"
SESSIONS_DIR = "numbers_sessions"
SESSION_ARCHIVE_DIR = "numbers_sessions_archive"
SESSION_REGISTRY_FILE = "session_registry.json"
# إرسال نسخة احتياطية تلقائية إلى الأدمن كل 50 دقيقة.
AUTO_BACKUP_INTERVAL = max(60, int(os.getenv("AUTO_BACKUP_INTERVAL", str(50 * 60))))
os.makedirs(SESSIONS_DIR, exist_ok=True)
os.makedirs(SESSION_ARCHIVE_DIR, exist_ok=True)

def save_session_to_disk(phone, session_str):
    """حفظ الجلسة كملف .session على القرص لضمان عدم ضياعها"""
    try:
        phone_clean = str(phone).replace('+', '').strip()
        path = os.path.join(SESSIONS_DIR, f"{phone_clean}.session")
        with open(path, 'w', encoding='utf-8') as f:
            f.write(session_str)
        return True
    except Exception as e:
        logger.error(f"Error saving session to disk for {phone}: {e}")
        return False


def session_fingerprint(session_str):
    """بصمة غير قابلة للعكس لتعريف الجلسة دون تسجيل محتواها في السجل."""
    return hashlib.sha256(str(session_str).encode('utf-8')).hexdigest()


def archive_session_snapshot(phone, session_str, reason="update"):
    """حفظ نسخة تاريخية من الجلسة قبل استبدالها."""
    try:
        phone_clean = str(phone).replace('+', '').strip() or 'unknown'
        fingerprint = session_fingerprint(session_str)[:16]
        filename = f"{phone_clean}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{reason}_{fingerprint}.session"
        path = os.path.join(SESSION_ARCHIVE_DIR, filename)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(str(session_str))
        return path
    except Exception as e:
        logger.error(f"Error archiving session for {phone}: {e}")
        return None


def register_session_identity(acc, session_str, me=None, status="observed"):
    """تسجيل هوية الجلسة وبصمتها لمنع خلط جلسة برقم آخر."""
    fingerprint = session_fingerprint(session_str)
    identity = {
        "phone": str(acc.get('phone') or '').lstrip('+'),
        "telegram_user_id": int(getattr(me, 'id', 0) or 0) if me else acc.get('telegram_user_id'),
        "telegram_phone": str(getattr(me, 'phone', '') or '').lstrip('+') if me else acc.get('telegram_phone'),
        "fingerprint": fingerprint,
        "updated_at": datetime.now().isoformat(),
        "status": status,
    }
    acc['session_fingerprint'] = fingerprint
    if identity['telegram_user_id']:
        acc['telegram_user_id'] = identity['telegram_user_id']
    if identity['telegram_phone']:
        acc['telegram_phone'] = identity['telegram_phone']
    acc['session_registry_updated_at'] = identity['updated_at']
    try:
        registry = {}
        if os.path.exists(SESSION_REGISTRY_FILE):
            with open(SESSION_REGISTRY_FILE, 'r', encoding='utf-8') as f:
                registry = json.load(f)
        registry[str(acc.get('id') or acc.get('phone'))] = identity
        tmp = SESSION_REGISTRY_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(registry, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, SESSION_REGISTRY_FILE)
    except Exception as e:
        logger.error(f"Error updating session registry: {e}")
    return fingerprint


async def verify_account_session_for_sale(acc, retries=3):
    """تحقق نهائي قبل البيع: لا يُسلّم الحساب إلا بعد اتصال وتطابق الهوية."""
    session_str = acc.get('session')
    phone = str(acc.get('phone') or '').lstrip('+')
    if not session_str:
        return False, "لا توجد جلسة محفوظة"
    last_error = "تعذر التحقق"
    for attempt in range(retries):
        client = None
        try:
            client = TelegramClient(
                StringSession(session_str), API_ID, API_HASH,
                connection=ConnectionTcpIntermediate,
                connection_retries=3, request_retries=2,
                retry_delay=5, auto_reconnect=False, flood_sleep_threshold=60
            )
            await client.connect()
            if not await client.is_user_authorized():
                last_error = "الجلسة غير مصرح بها"
            else:
                me = await client.get_me()
                actual_phone = str(getattr(me, 'phone', '') or '').lstrip('+')
                if not actual_phone:
                    last_error = "لم يظهر رقم الحساب داخل الجلسة"
                elif phone and actual_phone != phone:
                    last_error = "هوية الجلسة لا تطابق الرقم المسجل"
                else:
                    latest_session = StringSession.save(client.session)
                    if latest_session != session_str:
                        archive_session_snapshot(phone, session_str, reason="before_sale_update")
                        acc['session'] = latest_session
                    register_session_identity(acc, acc.get('session', session_str), me, status="verified_before_sale")
                    acc['last_pre_sale_check'] = datetime.now().isoformat()
                    acc['session_health_status'] = 'valid'
                    return True, None
        except AuthKeyUnregisteredError:
            last_error = "مفتاح الجلسة غير مسجل"
        except FloodWaitError as e:
            last_error = f"انتظار Telegram: {e.seconds} ثانية"
        except Exception as e:
            last_error = str(e)
        finally:
            if client:
                try:
                    await client.disconnect()
                except Exception:
                    pass
        if attempt + 1 < retries:
            await asyncio.sleep(2 * (attempt + 1))
    acc['session_health_status'] = 'needs_review'
    acc['session_health_error'] = last_error
    return False, last_error

def ensure_sessions_on_disk():
    """التأكد من أن جميع الحسابات المتاحة لها ملفات جلسة على القرص"""
    count = 0
    for acc in db.get('accounts', []):
        if acc.get('status') == 'available' and acc.get('session'):
            if save_session_to_disk(acc['phone'], acc['session']):
                count += 1
    if count > 0:
        logger.info(f"✅ تم التأكد من وجود {count} ملف جلسة على القرص.")

MIN_DEPOSIT = 0.30
MIN_BINANCE_DEPOSIT = 0.10
MAX_DEPOSIT = 500.00
DEFAULT_ACCOUNT_PRICE = 1.50 # سيتم تحميله من الإعدادات لاحقاً

# ================================================================
#              إعدادات Binance Pay
# ================================================================
# معرّف Binance Pay الذي يستقبل التحويلات.
BINANCE_TRANSFER_ID = os.getenv('BINANCE_TRANSFER_ID', '1268704908').strip()

# مفتاح API من Binance — ضع المفتاح بين علامات الاقتباس هنا.
# لا ترسل المفتاح أو المفتاح السري في المحادثة.
BINANCE_API_KEY = os.getenv('BINANCE_API_KEY', 'ضع مفتاح Binance API هنا').strip()

# المفتاح السري Secret Key من Binance — ضع المفتاح بين علامات الاقتباس هنا.
BINANCE_SECRET_KEY = os.getenv('BINANCE_SECRET_KEY', 'ضع المفتاح السري هنا').strip()

def _binance_key_is_ready(value):
    value = str(value or '').strip()
    return bool(value) and not value.startswith('ضع ')
BINANCE_API_BASE = os.getenv("BINANCE_API_BASE", "https://api.binance.com")
# Binance Pay يسمح بالاستعلام عن السجل حتى 90 يومًا؛ لا نحصر دفعة صحيحة في 7 أيام.
BINANCE_HISTORY_DAYS = min(90, max(1, int(os.getenv("BINANCE_HISTORY_DAYS", "90"))))
VOFACASH_RATE_EGP_PER_USD = 50  # كل 50 جنية = 1 دولار
MIN_VOFACASH_EGP = 20  # أقل مبلغ للشحن 20 جنيه
# ================================
# Vodafone Cash عبر SMS Forwarder (بدون بوابة دفع خارجية)
# ================================
VODAFONE_WALLET_NUMBER = os.getenv("VODAFONE_WALLET_NUMBER", "01030428675").strip()
VODAFONE_SMS_WEBHOOK_TOKEN = os.getenv("VODAFONE_SMS_WEBHOOK_TOKEN", "").strip()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://moscownamber.up.railway.app").rstrip("/")
VODAFONE_RATE_EGP_PER_USD = Decimal(os.getenv("VODAFONE_RATE_EGP_PER_USD", "52"))
VODAFONE_MIN_EGP = Decimal(os.getenv("VODAFONE_MIN_EGP", "1"))
VODAFONE_MAX_EGP = Decimal(os.getenv("VODAFONE_MAX_EGP", "10000"))
VODAFONE_ORDER_TTL = max(300, int(os.getenv("VODAFONE_ORDER_TTL", "7200")))
BOT_LOOP = None

SESSION_TIMEOUT = 315360000 # 10 سنوات (لانهاية عملياً)
JOIN_GRACE_PERIOD = 30
CODE_REQUEST_COOLDOWN = 10
TXID_ATTEMPT_COOLDOWN = 5
TEMP_BAN_DURATION = 300  # 5 دقائق = 300 ثانية
# لا تُلغِ جلسات تيليجرام الأخرى تلقائياً بعد استيراد الرقم.
# ResetAuthorizationsRequest قد يجعل جلسة الرقم المخزنة غير قابلة للاستخدام
# إذا نفّذ بالتزامن مع البيع أو مع إعادة اتصال أخرى. فعّله فقط عند الحاجة:
# RESET_OTHER_SESSIONS=1
RESET_OTHER_SESSIONS = os.getenv("RESET_OTHER_SESSIONS", "0").strip().lower() in {
    "1", "true", "yes", "on"
}
# لا تُسجّل جلسة البوت خروجًا تلقائيًا بعد الشراء؛ إذا استُخدمت نفس الجلسة
# على جهاز المستخدم فقد يؤدي ذلك إلى طرده من الحساب. يمكن تفعيله فقط صراحةً.
AUTO_LOGOUT_AFTER_PURCHASE = os.getenv("AUTO_LOGOUT_AFTER_PURCHASE", "0").strip().lower() in {
    "1", "true", "yes", "on"
}

# ================================
#  حماية التشغيل ومحدد معدل Bot API
# ================================
BOT_API_MIN_INTERVAL = float(os.getenv("BOT_API_MIN_INTERVAL", "0.35"))
REFERRAL_MONITOR_INTERVAL = max(30, int(os.getenv("REFERRAL_MONITOR_INTERVAL", "60")))
_bot_api_rate_lock = asyncio.Lock()
_bot_api_last_started = 0.0
_instance_lock_handle = None

def acquire_single_instance_lock():
    """يضمن عدم تشغيل نسختين تستخدمان نفس البوت في الوقت نفسه."""
    global _instance_lock_handle
    token_fingerprint = hashlib.sha256(BOT_TOKEN.encode("utf-8")).hexdigest()[:20]
    lock_path = os.path.join("/tmp", f"sliner_numbers_bot_{token_fingerprint}.lock")
    _instance_lock_handle = open(lock_path, "a+", encoding="utf-8")
    try:
        fcntl.flock(_instance_lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        _instance_lock_handle.close()
        _instance_lock_handle = None
        raise RuntimeError("نسخة أخرى من البوت تعمل بالفعل بنفس BOT_TOKEN")
    _instance_lock_handle.seek(0)
    _instance_lock_handle.truncate()
    _instance_lock_handle.write(str(os.getpid()))
    _instance_lock_handle.flush()

# ================================
#  تعريف كائن البوت (MemorySession)
# ================================
bot = TelegramClient(
    MemorySession(),
    API_ID,
    API_HASH,
    connection=ConnectionTcpIntermediate,
    connection_retries=15,
    request_retries=5,
    retry_delay=10,
    auto_reconnect=True,
    # انتظر تلقائيًا عند FloodWait بدل تحويله إلى انقطاع فوري.
    flood_sleep_threshold=60
)

WALLETS = {
    "LTC":  "ltc1qlf8e7mvzrjmeg4xdc4acq5m3z8zg4shcjy89ap",
    "BTC":  "PUT_YOUR_BTC_ADDRESS_HERE",
    "TON":  "PUT_YOUR_TON_ADDRESS_HERE",
    "USDT": "PUT_YOUR_BSC_USDT_BEP20_ADDRESS_HERE",
}

NETWORKS = {
    "LTC":  "Litecoin Network",
    "BTC":  "Bitcoin Network",
    "TON":  "TON Network",
    "USDT": "BEP20 (Binance Smart Chain)",
    "STARS": "Telegram Stars",
}

# ================================
#  مصدر الحقيقة لشحن النجوم (صارم)
# ================================
# السعر الرسمي للنجمة الواحدة بالدولار: 0.01$ (10 نجوم = 0.10$)
# يُحسب عبر Decimal لمنع أي خطأ تقسيم/ضرب على Float
STAR_PRICE_USD: Decimal = Decimal('0.01')
STAR_PRICE_CENTS: int = 1                     # 1 cent = 1 star
_STAR_PRICE_QUANTUM = Decimal('0.01')         # للتحقق من المبلغ الإجمالي

# متغيّر قابل للقراءة فقط — يحظر تجاوزه
STARS_RATE = float(STAR_PRICE_USD)             # للتوافق مع الكود القديم فقط

STARS_MAX_PER_INVOICE = 10000
STARS_MIN_PER_INVOICE = 1
STARS_USD_MIN = Decimal('0.10')                # = 10 نجوم
STARS_USD_MAX = STAR_PRICE_USD * Decimal(STARS_MAX_PER_INVOICE)
# دفعات النجوم نهائية بعد نجاح الدفع وإضافة الرصيد.
# لا تغيّر هذه القيمة إلى True: البوت لا ينفّذ استرداداً لنجوم تيليجرام.
STARS_REFUNDS_ENABLED = False

def stars_to_usd(stars) -> Decimal:
    """تحويل عدد نجوم (int) إلى Decimal بالدولار بدقة كاملة.
    يرفع ValueError لو كان خارج الحدود المسموحة."""
    try:
        s = int(stars)
    except Exception:
        raise ValueError(f"عدد النجوم غير صحيح: {stars!r}")
    if s < STARS_MIN_PER_INVOICE:
        raise ValueError(f"عدد النجوم أقل من الحد الأدنى ({STARS_MIN_PER_INVOICE})")
    if s > STARS_MAX_PER_INVOICE:
        raise ValueError(f"عدد النجوم أكبر من الحد الأقصى ({STARS_MAX_PER_INVOICE})")
    # الضرب بين Int و Decimal آمن وبدون انحراف
    return (Decimal(s) * STAR_PRICE_USD).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)

def usd_to_stars(usd) -> int:
    """تحويل مبلغ بالدولار إلى عدد نجوم صحيح.
    يرفض بدقة أي مبلغ ليس مضاعفاً تاماً لـ 0.01$ (لا تسامح مع الكسور)."""
    try:
        u = Decimal(str(usd))
    except (InvalidOperation, ValueError):
        raise ValueError(f"المبلغ بالدولار غير صحيح: {usd!r}")
    if u < STARS_USD_MIN:
        raise ValueError(f"المبلغ أقل من الحد الأدنى ({STARS_USD_MIN}$)")
    if u > STARS_USD_MAX:
        raise ValueError(f"المبلغ أكبر من الحد الأقصى ({STARS_USD_MAX}$)")
    # المضاعف التام: u * 100 يجب أن يكون عدداً صحيحاً تماماً
    cents = u * 100
    if cents != cents.to_integral_value():
        raise ValueError(
            f"المبلغ ({u}$) ليس مضاعفاً تاماً للسينت "
            f"(STAR_PRICE_USD={STAR_PRICE_USD}$). المتطابق الأقرب: {cents.quantize(Decimal('1'), rounding=ROUND_HALF_UP) / 100}$"
        )
    return int(cents)  # 1 cent == 1 star

def stars_payload_encode(uid: int, stars: int, nonce: int) -> str:
    """تشفير منظّم لـ payload فاتورة النجوم.
    صيغة: STARS|uid=<uid>|stars=<stars>|n=<nonce>
    تحلّ محل الفهرسة split() التي سبّبت العلة الجذرية."""
    stars = int(stars)
    uid = int(uid)
    nonce = int(nonce)
    if not (STARS_MIN_PER_INVOICE <= stars <= STARS_MAX_PER_INVOICE):
        raise ValueError(f"عدد النجوم خارج الحدود: {stars}")
    return f"STARS|uid={uid}|stars={stars}|nonce={nonce}"

def stars_payload_decode(payload: str):
    """فكّ تشفير payload بأمان، يرجع dict أو None لو غير صالح.
    يمنع رفض القيم السلبية أو المحارف الفاسدة.
    لا يستخرج أبداً عبر split()[index] لتفادي العلة الأصلية."""
    if not isinstance(payload, str) or not payload:
        return None
    if isinstance(payload, (bytes, bytearray)):
        try:
            payload = payload.decode('utf-8')
        except Exception:
            return None
    if not payload.startswith("STARS|"):
        return None
    out = {"uid": None, "stars": None, "nonce": None}
    try:
        for part in payload.split("|"):
            if "=" not in part:
                continue
            k, v = part.split("=", 1)
            if k in out:
                # نقبل int موجب فقط
                v_int = int(v)
                if v_int < 0:
                    return None
                out[k] = v_int
    except Exception:
        return None
    if out["uid"] is None or out["stars"] is None:
        return None
    if not (STARS_MIN_PER_INVOICE <= out["stars"] <= STARS_MAX_PER_INVOICE):
        return None
    return out

def stars_is_charge_seen(charge_id: str) -> bool:
    """التحقق من تكرار معرّف الشحن (idempotency).
    يقبل None/فارغ ويعيد False."""
    if not charge_id:
        return False
    cid = str(charge_id)
    for tx in db.get('transactions', []):
        if tx.get('currency') == 'STARS' and str(tx.get('txid', '')) == cid:
            return True
    return False

# قفل وحدة لكل charge_id لمنع الكتابة المتزامنة المزدوجة عبر raw handler + message handler
_STARS_LOCKS: dict = {}
_STARS_LOCKS_META = threading.RLock()

FALLBACK_RATES = {
    "LTC": 70.0,
    "BTC": 60000.0,
    "TON":  5.0,
    "USDT": 1.0,
}
AMOUNT_TOLERANCE = 0.05

# ================================
#  ثوابت خاصة بالمخطلت
# ================================
# سيتم تحميل MIXED_PRICE من قاعدة البيانات لاحقاً
MIXED_PRICE = 0.18          # السعر الافتراضي لأرقام المخطلت
MIXED_LABEL = "📛 أرقام سبام"    # التسمية الظاهرة للمستخدم
SPAM_MIX_CODE = "spam_mix"
SPAM_MIX_LABEL = "سبام Mix"
SPAM_MIX_EMOJI_ID = "5301238155897224446"
FAKE_LABEL = "⚠️ مزيف و احتيالي" # التسمية للزر الجديد
FAKE_PRICE = 2.0             # السعر الثابت للزر الجديد
UNVERIFIED_CODE = "unverified"
UNVERIFIED_LABEL = "🃏 أرقام سبام مزيف"
UNVERIFIED_PRICE = 0.50
USA_CLEAN_CODE = 'usa_clean'
USA_CLEAN_LABEL = '🇺🇸 أمريكا'
USA_CLEAN_PRICE = 0.40        # السعر الثابت بالدولار لزر أمريكا السليم
USA_SPAM_PRICE = 0.18         # السعر الثابت بالدولار لأرقام أمريكا السبام
OLD_NUMBERS_CODE = 'old_numbers'
OLD_NUMBERS_LABEL = 'أرقام قديمة'
OLD_NUMBERS_LABEL_EN = 'Old Numbers'
OLD_NUMBERS_PRICE = 1.00
OLD_SPAM_CODE = 'old_spam'
OLD_SPAM_LABEL = 'أرقام اسبام قديمة'
OLD_SPAM_PRICE = 1.00
MONTHLY_NUMBERS_CODE = 'monthly_special'
MONTHLY_NUMBERS_LABEL = 'أرقام مميزة شهر'
MONTHLY_NUMBERS_PRICE = 1.00  # سعر افتراضي، يحدده الأدمن عند الاستيراد
BIMONTHLY_NUMBERS_CODE = 'bimonthly_special'
BIMONTHLY_NUMBERS_LABEL = 'أرقام مميزة شهرين'
BIMONTHLY_NUMBERS_BUTTON_LABEL = 'أرقام مميزة شهرين'
BIMONTHLY_NUMBERS_PRICE = 2.00  # سعر افتراضي، يحدده الأدمن عند الاستيراد
RANDOM_NUMBERS_CODE = 'random_special'
RANDOM_NUMBERS_LABEL = 'أرقام مميزة عشوائي'
RANDOM_NUMBERS_BUTTON_LABEL = 'أرقام مميزة عشوائي 🎲'
RANDOM_NUMBERS_PRICE = 2.00
DAILY_NUMBERS_CODE = 'daily_special'
DAILY_NUMBERS_LABEL = 'أرقام مميزة يوم'
DAILY_NUMBERS_BUTTON_LABEL = 'أرقام مميزة يوم ☀️'
DAILY_NUMBERS_PRICE = 1.50

logging.basicConfig(
    format='%(asctime)s • %(levelname)s • %(message)s',
    level=logging.INFO
)
logging.getLogger('telethon').setLevel(logging.WARNING)
logger = logging.getLogger("sliner_numbers")

# ================================
#  قاعدة البيانات مع أقفال
# ================================
_db_lock = asyncio.Lock()
_PURCHASE_FLOW_LOCK = asyncio.Lock()  # يحمي التعديلات الذرية على قاعدة البيانات
_USER_PURCHASE_LOCKS = {}

def get_user_purchase_lock(user_id):
    """قفل مستقل لكل مستخدم لمنع شراءين متزامنين من نفس الحساب."""
    uid = int(user_id)
    lock = _USER_PURCHASE_LOCKS.get(uid)
    if lock is None:
        lock = asyncio.Lock()
        _USER_PURCHASE_LOCKS[uid] = lock
    return lock
_USER_CACHE = {}
_USERNAME_MAP = {}
_BOT_USERNAME_MAP = {}
DB_DIRTY = False

def _default_db():
    # حساب أعلى ID للحسابات لتجنب التكرار
    existing_ids = [a.get('id', 0) for a in db.get('accounts', [])] if 'db' in globals() else []
    max_acc_id = max(existing_ids) if existing_ids else 0
    return {
        "users": {},
        "captcha": {},
        "countries": {},

        "accounts": [],
        "scam_channels": [],
        "scam_purchases": [],
        "purchases": [],
        "transactions": [],
        "deposits": {},
        "manual_payments": [],
        "manual_requests": [],
        "used_txids": [],


        "main_url_buttons": [],
        "custom_emojis": {},
        "hidden_buttons": [],
        "button_overrides": {},
        "pending_spam_choice": {},  # إضافة حقل مؤقت للاختيار
        # نظام الإحالة الجديد: كل مستخدم تتم إحالتُه يُسجل هنا بواسطة ID
        # حتى نستطيع إيقاف/إعادة المكافأة عند مغادرة القنوات أو حظر البوت.
        "referrals": {},
        "settings": {
            "maintenance": False,
            "welcome_text": "",
            "support_url": f"https://t.me/{DEVELOPER_USER}",
            "force_channels": DEFAULT_FORCE_CHANNELS,
            "force_sub_enabled": True,
            "referral_enabled": True,
            "referral_reward": 0.006,
            "referral_check_interval": 1,


            "next_account_id": max_acc_id + 1,
            "next_purchase_id": 2,
            "next_tx_id": 1,
            "next_deposit_id": 3,
            "next_manual_id": 2,
            "next_scam_channel_id": 1,
            "monitored_channels": [],
            "sold_numbers_count": 1250,
            "mixed_price": 0.21,
            "old_spam_price": OLD_SPAM_PRICE,
            "extra_admins": []
        }
    }

def load_db():
    if not os.path.exists(DB_FILE):
        data = _default_db()
        save_db(data)
        return data
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"خطأ في قراءة DB: {e} — إعادة إنشاء")
        data = _default_db()
        save_db(data)
        return data

    default = _default_db()
    for k, v in default.items():
        if k not in data:
            data[k] = v
        elif isinstance(v, dict):
            for kk, vv in v.items():
                if kk not in data[k]:
                    data[k][kk] = vv

    if str(OWNER_ID) not in data['users']:
        data['users'][str(OWNER_ID)] = {
            'username': '', 'full_name': 'Owner', 'balance': 0.0,
            'verified': True, 'banned': False,
            'total_spent': 0.0, 'total_deposited': 0.0,
            'joined_at': datetime.now().isoformat(),

            '_state': {}
        }
    save_db(data)
    data.setdefault('countries', {})
    data['countries'].setdefault(USA_CLEAN_CODE, {'name': USA_CLEAN_LABEL, 'price': USA_CLEAN_PRICE})
    data.setdefault('scam_channels', [])
    data.setdefault('scam_purchases', [])
    # تحديث الأسعار العالمية من الإعدادات
    global MIXED_PRICE, DEFAULT_ACCOUNT_PRICE, FAKE_PRICE
    MIXED_PRICE = data.get('settings', {}).get('mixed_price', 0.21)
    DEFAULT_ACCOUNT_PRICE = data.get('settings', {}).get('default_price', 1.50)
    FAKE_PRICE = data.get('settings', {}).get('fake_price', 2.0)
    global OLD_SPAM_PRICE
    OLD_SPAM_PRICE = data.get('settings', {}).get('old_spam_price', OLD_SPAM_PRICE)
    # بناء الفهارس للبحث السريع
    global _USERNAME_MAP, _BOT_USERNAME_MAP
    _USERNAME_MAP = {}
    _BOT_USERNAME_MAP = {}
    for uid, u in data.get('users', {}).items():
        uname = u.get('username')
        if uname:
            _USERNAME_MAP[uname.lower().lstrip('@')] = uid
        buname = u.get('bot_username')
        if buname:
            _BOT_USERNAME_MAP[buname.lower()] = uid
    return data

def update_user_cache(uid):
    uid = str(uid)
    if uid in db.get('users', {}):
        _USER_CACHE[uid] = db['users'][uid]
    else:
        _USER_CACHE.pop(uid, None)

async def _real_save_db_async(data):
    async with _db_lock:
        global DB_DIRTY
        try:
            tmp = DB_FILE + ".tmp"
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            if os.path.exists(DB_FILE):
                shutil.copy2(DB_FILE, DB_BACKUP_FILE)
            os.replace(tmp, DB_FILE)
            DB_DIRTY = False
        except Exception as e:
            logger.error(f"Error in _real_save_db_async: {e}")

def _real_save_db(data):
    global DB_DIRTY
    try:
        tmp = DB_FILE + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(DB_FILE):
            shutil.copy2(DB_FILE, DB_BACKUP_FILE)
        os.replace(tmp, DB_FILE)
        DB_DIRTY = False
    except Exception as e:
        logger.error(f"Error in _real_save_db: {e}")

async def save_db_async(data):
    global DB_DIRTY
    DB_DIRTY = True
    # تحديث الكاش فقط
    for uid in data.get('users', {}):
        _USER_CACHE[uid] = data['users'][uid]

def save_db(data):
    global DB_DIRTY
    DB_DIRTY = True
    # تحديث الكاش فقط
    for uid in data.get('users', {}):
        _USER_CACHE[uid] = data['users'][uid]

async def db_saver_task():
    while True:
        try:
            await asyncio.sleep(30)
            if DB_DIRTY:
                await _real_save_db_async(db)
        except Exception as e:
            logger.error(f"Error in db_saver_task: {e}")


def create_full_backup_zip():
    """إنشاء ملف ZIP كامل مؤقتًا لإرساله للأدمن."""
    backup_name = os.path.abspath(
        f"backup_auto_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    )
    targets = [
        DB_FILE, "sliner_numbers_bot_session.session", SESSIONS_DIR,
        SESSION_ARCHIVE_DIR, SESSION_REGISTRY_FILE,
    ]
    with zipfile.ZipFile(backup_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for target in targets:
            if os.path.exists(target):
                if os.path.isdir(target):
                    for root, dirs, files in os.walk(target):
                        for file in files:
                            file_path = os.path.join(root, file)
                            zipf.write(file_path, arcname=file_path)
                else:
                    zipf.write(target, arcname=target)
    return backup_name


async def automatic_backup_task():
    """إرسال نسخة احتياطية كاملة لكل الأدمن بشكل دوري."""
    while True:
        try:
            await asyncio.sleep(AUTO_BACKUP_INTERVAL)
            if DB_DIRTY:
                await _real_save_db_async(db)

            backup_name = None
            try:
                backup_name = create_full_backup_zip()
                caption = (
                    "📦 *نسخة احتياطية تلقائية للمشروع*\n\n"
                    f"📅 التاريخ: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n"
                    f"👥 عدد المستخدمين: `{len(db.get('users', {}))}`\n"
                    f"💰 إجمالي الأرصدة: `"
                    f"{sum(u.get('balance', 0) for u in db.get('users', {}).values()):.2f}$`\n\n"
                    "✅ يتم الإرسال تلقائيًا كل 50 دقيقة."
                )
                for admin_id in ADMINS:
                    try:
                        await bot.send_file(admin_id, backup_name, caption=caption, parse_mode='md')
                    except Exception as admin_error:
                        logger.error(f"تعذر إرسال النسخة الاحتياطية للأدمن {admin_id}: {admin_error}")
                logger.info("✅ تم إرسال النسخة الاحتياطية التلقائية إلى الأدمن.")
            finally:
                if backup_name and os.path.exists(backup_name):
                    os.remove(backup_name)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"خطأ في النسخة الاحتياطية التلقائية: {e}")

db = load_db()
db.setdefault('vodafone_sms_orders', {})
db['hidden_buttons'] = []
db.setdefault('referrals', {})
db.setdefault('settings', {})
db['settings'].setdefault('referral_enabled', True)
# مكافأة الإحالة ثابتة: 0.006$ لكل إحالة.
# يتم فرض القيمة حتى لو كانت قاعدة البيانات تحتوي على قيمة قديمة مثل 0.01$.
db['settings']['referral_reward'] = 0.006
db['settings'].setdefault('referral_check_interval', 1)
# فحص الإحالة سريع؛ لا نسمح بقيمة قديمة كبيرة من قاعدة البيانات.
db['settings']['referral_check_interval'] = 1
db['settings'].setdefault('referral_max_per_hour', 20)
db['settings'].setdefault('referral_max_per_5min', 5)
db.setdefault('referral_pending', {})
# ضمان وجود تصنيف الأرقام القديمة حتى لو كانت الحسابات مستوردة من نسخة سابقة
# وكانت خانة الدولة الخاصة بها غير موجودة في db['countries'].
db['countries'].setdefault(
    OLD_NUMBERS_CODE,
    {'name': OLD_NUMBERS_LABEL, 'price': OLD_NUMBERS_PRICE}
)
db['countries'].setdefault(
    OLD_SPAM_CODE,
    {'name': OLD_SPAM_LABEL, 'price': db.get('settings', {}).get('old_spam_price', OLD_SPAM_PRICE)}
)
for _uid, _u in db.get('users', {}).items():
    _u.setdefault('referral_points', 0.0)
if 'sold_numbers_count' not in db['settings'] or db['settings']['sold_numbers_count'] < 1251:
    db['settings']['sold_numbers_count'] = 1251
# التأكد من وجود pending_spam_choice
if 'pending_spam_choice' not in db:
    db['pending_spam_choice'] = {}
save_db(db)

# ================================
#  إيموجيات مخصصة وأزرار ملونة (كاملة)
# ================================
BUTTON_STYLES = ("primary", "success", "success")

BUTTON_ICON_BY_CALLBACK = {
    "account_menu": "5309901482890382924",
    "show_stats": "👤",
    "set_my_delay": "5344026935087346880",
    "del_group": "5879937509579820068",
    "add_group": "5287354223141342798",
    "ads_menu": "4992560350982309130",
    "keywords_menu": "5195172521183295517",
    "start_loop": "5116447063432758252",
    "stop_loop": "5348125953090403204",
    "logout_request": "5974506040828366250",
    "add_new_ad": "5287354223141342798",
    "list_delete_ads": "5897484821805929855",
    "clear_ads": "5879937509579820068",
    "add_kw": "5287354223141342798",
    "list_kw": "5897484821805929855",
    "user_home": "5325598171018051937",
    "buy": "5287354223141342798",
    "deposit": "4992560350982309130",
    "pay:STARS": "5438496463044752972",
    "pay_orange": "5836714629455157161",
    "my_balance": "👤",
    "my_purchases": "5897484821805929855",
    "info": "5195172521183295517",
    "back_main": "5325598171018051937",
    "cancel_action": "5879937509579820068",
    "a_cancel": "5879937509579820068",
    "verify_captcha": "5309901482890382924",
    "check_sub": "5309901482890382924",
    "a:panel": "5309901482890382924",
    "a:stats": "👤",
    "a:txs": "👤",
    "a:addbal": "5287354223141342798",
    "a:subbal": "5287354223141342798",
    "a:ban": "5879937509579820068",
    "a:broadcast": "4992560350982309130",
    "a:countries": "5195172521183295517",
    "a:accounts": "5897484821805929855",
    "a:manualpay": "5287354223141342798",
    "a:wallets": "5309901482890382924",
    "a:welcome": "5309901482890382924",
    "a:channels": "4992560350982309130",
    "a:maintenance": "5348125953090403204",
    "a:mainbtns": "5287354223141342798",
    "transfer_start": "6192718082004228266",
    "buy_sessions": "5323463074055739425",
    "buy_type:monthly": "4958714479681471536",
    "import_monthly": "4958714479681471536",
    "add:monthly": "4958714479681471536",
    "buy_type:bimonthly": "4958714479681471536",
    "buy_sessions_type:bimonthly": "4958714479681471536",
    "import_bimonthly": "4958714479681471536",
    "add:bimonthly": "4958714479681471536",
    "import_clean": "5771390788223115615",
    "buy_type:clean": "5771390788223115615",
    "buy_type:spam_mix": SPAM_MIX_EMOJI_ID,
    "buy_sessions_type:spam_mix": SPAM_MIX_EMOJI_ID,
    "add:spam_mix": SPAM_MIX_EMOJI_ID,
    "import_spam_mix": SPAM_MIX_EMOJI_ID,
    "buy_sessions_type:clean": "5771390788223115615",
    "import_unverified": "6037597564218384009",
    "buy_type:unverified": "6037597564218384009",
    "buy_sessions_type:unverified": "6037597564218384009",
    "add:unverified": "6037597564218384009",
}

BUTTON_ICON_BY_TEXT = {
    SPAM_MIX_LABEL: SPAM_MIX_EMOJI_ID,
    # أيقونة حقيقية لزر الأرقام القديمة عبر Telegram Bot API.
    "أرقام قديمة": "5942878198013368300",
    "Old Numbers": "5942878198013368300",
    "إدارة الحساب": "5309901482890382924",
    "الإحصائيات": "5798765088701685144",
    "التوقيت": "5344026935087346880",
    "🗑 حذف قروب": "5800901190686351655",
    "➕ إضافة قروب": "5798773923449413575",
    "إدارة الإعلانات": "5798858890787431096",
    "ردود القروبات": "5801040472180792567",
    "⏸ بدء النشر": "5801167435709029054",
    "▶️ إيقاف النشر": "5801087759770720933",
    "🧑‍💻 المطور": "5388816589216823151",
    "🔧 ربط الحساب": "5413398757226076065",
    "🔃 تغيير الحساب": "5346269127059196142",
    "🚪 خروج من الحساب": "5974506040828366250",
    "🤍 رجوع": "6192930064410091053",
    "🔙 رجوع": "5325598171018051937",
    "🔥 شراء رقم  🔥": "5800686322062466063",
    "💵 شحن رصيد": "5801135030180782815",
    "رصيدي": "4988124994090305556",
    "معلومات": "6192905565916632738",
    "🪙 LTC (Litecoin)": "4985673495477225332",
    "₿ BTC (Bitcoin)": "5935842277078342221",
    "💎 TON (Toncoin)": "5798798787015090690",
    "✅ تحقق": "✅",
    "شراء أرقام": "4987902454654831335",
    "شراء جلسات": "5323463074055739425",
    "عدد الأرقام المباعة": "5895763905719832199",
    "هدية يومية": "6192485518115084690",
    "🏠 القائمة الرئيسية": "5801019761848490177",
    "💸 دفع فودافون كاش 💸": "4988196741518984970",
    "💸 شحن عن طريق BINANCE 🪙": "4987882440107230847",
    "🔵 دفعت المبلغ": "✅",
    "⑤ حسابي": "👤",
    "تحويل رصيد": "6192718082004228266",
    "تغيير اللغة": "5801036598120291572",
    "الشروط": "5798578124480323191",
    "التحديثات": "5800686322062466063",
    "قناة التفعيلات": "5798537025938267498",
    "الدعم الفني": "5213179235996294999",
    "💸 دفع فودافون كاش 💸": "4988196741518984970",
    "💸 شحن عن طريق BINANCE 🪙": "4987882440107230847",
}

_STATIC_ICON_PREFIXES = sorted([
    "👨‍💻", "🧑‍💻", "⏱️", "🗒️", "▶️", "👤", "📈", "📊", "🕰", "🗑", "➕", "📣", "📢", "💬", "⏸", "🛑", "🔧", "🔗", "🔃", "🔄", "🚪", "🤍", "🔙", "🔥", "💰", "💵", "💳", "📱", "📋", "⚡", "🪙", "₿", "💎", "🌐", "⚠️", "✓", "❌", "🔄", "⬅️", "➡️", "🖥", "📺", "✏️", "🟩", "🟥", "🚸", "🔑", "📩", "📸", "💼", "📦", "⏳", "🔍", "🌍", "📁", "🛠", "🎛", "🔧", "🛒", "⑤", "📞",
], key=len, reverse=True)

CUSTOM_EMOJIS = {
    "✨": "6267219374994626613",
    # رموز رسائل Binance Pay؛ تظهر كـ Custom Emoji عند قبولها من Telegram
    # وتعود تلقائياً إلى الإيموجي العادي إذا تعذر إرسال الكيان المخصص.
    "🌟": "6267219374994626613",
    "💸": "4987882440107230847",
    "📉": "5798765088701685144",
    "📈": "5798765088701685144",
    "🛡️": "5309901482890382924",
    "🎉": "5188344996356448758",
    "🧾": "5895541903155269098",
    "⚠️": "5895576786879647172",
    "🔍": "5195172481183295517",
    "🔁": "5346269127059196142",
    "🚀": "5463424023734014980",
    "🧪": "6037597564218384009",
    "✅": "5771390788223115615",
    "🛫": "5463424023734014980",
    "💱": "5798834177545609756",
    "🗓️": "5472279086657199080",
    "🔓": "6192953424737213249",
    "🧩": "5213306719215577669",
    "🔗": "5798508588959811072",
    "🏆": "5188344996356448758",
    "📊": "5877485980901971030",
    "📛": "5895576786879647172",
    "📄": "5895541903155269098",
    "💵": "💰",
    "💼": "📦",
    "🐷": "5417831807720642261",
    "🏅": "5424746623462823358",
    "🧲": "5202106638508512484",
    "🌱": "5474417568053745249",
    "🪧": "5429278861932124623",
    "📈": "5798765088701685144",
    "🫴": "5440457429147997980",
    "⚖️": "5461152608804689572",
    "📞": "5213179235996294999",
    "🚀": "5188481279963715781",
    "💳": "6267068789146260253",
    "🗺": "5235794253149394263",
    "💎": "5798798787015090690",
    "🏷️": "5298877105000439431",
    "📩": "5472239203590888751",
    "⛏": "5461047575379466857",
    "⛏️": "4987793199276754762",
    "🎰": "5235989279024373566",
    "🪂": "5461128651477111908",
    "🧾": "5204242830687494041",
    "👛": "6192750908439271662",
    "⌨️": "5298975240708187753",
    "🔑": "5307843983102204243",
    "🔋": "5307905813451397794",
    "⭐": "6192525822088190795",
    "🎁": "6192485518115084690",
    "👏": "6190313892455915190",
    "🤍": "6192930064410091053",
    "✓": "✅",
    "👎": "5801035245205594136",
    "💻": "6192757496919104777",
    "✔": "6192785873768029586",
    "☑️": "6192630030879694031",
    "❌": "5800982150819880883",
    "👍": "5798502833703625629",
    "🙅": "6192913176598682994",
    "🆗": "6192957908683069785",
    "🆙": "6190544081228146516",
    "🔽": "5800703239938645256",
    "▶️": "5801087759770720933",
    "👆": "6190546018258395366",
    "👇": "6192911218093596524",
    "👈": "6190613904511473859",
    "👉": "6192901618841689911",
    "🔼": "5800749754434461867",
    "🔄": "5800709991627235905",
    "💸": "4988196741518984970",
    "❗️": "5800872667808539150",
    "◀️": "6192865141684443844",
    "➖": "6192744882600156381",
    "#⃣": "6192526930189752487",
    "🩵": "6192821066730053826",
    "🩶": "6192581433324739498",
    "🟢": "6192924051455875915",
    "🟣": "6192991456672617901",
    "🛎": "6192691762444639496",
    "❗": "6192996361525272662",
    "🗡": "6190728253720764254",
    "🍎": "4985873099787339567",
    "🧠": "6192771610181638630",
    "🎈": "6192995764524817249",
    "💀": "6190695255487028081",
    "🎲": "6192652751256689378",
    "😴": "6192686509699636321",
    "🕺": "6192696048822000099",
    "🚬": "6192535266721274487",
    "⤴️": "6192747528300009321",
    "⤵️": "6192737254738238732",
    "💭": "5798608812021652982",
    "⏱": "6192969805742481441",
    "🚶": "6192981522413263701",
    "😘": "6192543130806393140",
    "❓": "⏳",
    "⁉️": "5801034613845401731",
    "🤪": "6192664351963355398",
    "🛡": "5801181213964116634",
    "🔖": "5798514803777478100",
    "😔": "6192971768542533371",
    "👽": "6192992620608756811",
    "🙊": "6192620371498243937",
    "🔝": "5798792056801337532",
    "🫰": "6192547649111989929",
    "ℹ️": "5801026762645183933",
    "📉": "5798839125347934488",
    "💲": "4985975255584475169",
    "🇮🇶": "5221980268230882832",
    "🇱🇾": "5222194286451242896",
    "🧱": "4990387896394450305",
    "🥇": "5800923447206878778",
    "🛢️": "4988173840753362667",
    "🥉": "4987880284033648742",
    "🇺🇸": "5228866831678191568",
    "🅰️": "4988102200698865765",
    "🅿️": "4988194709999453700",
    "🏪": "4985673847664543603",
    "☎️": "4987788960144033698",
    "⏲": "4988263180368086422",
    "🎧": "4987810271771756259",
    "🤗": "4988035259338589864",
    "🇲🇦": "5224530035695693965",
    "🇲🇷": "4987869374816716743",
    "🇩🇿": "4985849249833944893",
    "🇹🇳": "5221991375016310330",
    "🇸🇩": "5224372990216514135",
    "🇹🇷": "5224601903383457698",
    "🇯🇴": "5222292177345853436",
    "🇱🇧": "5222244425899455269",
    "🇸🇾": "4987923474224776895",
    "🇴🇲": "5222396686785066306",
    "🇾🇪": "5222300655611294950",
    "🇦🇪": "5224565851427976312",
    "🇶🇦": "5222225596762830469",
    "🇰🇼": "5221949726718442491",
    "🇧🇭": "4988003274717136929",
    "🌍": "🌍",
    "⛔": "4988246344096286984",
    "🏬": "4988080158926702169",
    "📢": "4985742588616115840",
    "🤖": "5897870213516365139",
    "🇨🇳": "5224435456220868088",
    "🫂": "4987799113446721271",
    "↗️": "4987970980858038223",
    "🆘": "4988268630681585851",
    "🔔": "5798407695883050599",
    "😍": "4985693686118484446",
    "🕌": "4987923036138112391",
    "🤲": "4985846440925333794",
    "🕋": "4988044562237753453",
    "🕓": "4985991877107910599",
    "🔶": "4987751585338623524",
    "🟡": "4988130139461126095",
    "🔵": "4985885611027072556",
    "🏹": "4988211426012170104",
    "✍️": "4988044210050435044",
    "⚡️": "5800716253689552373",
    "⛔️": "5800672088540848193",
    "⚠️": "5798578124480323191",
    "🕯": "5798926940249269416",
    "🆒": "5800914135717780769",
    "🤡": "5798845649403256094",
    "🫦": "5800848684711157054",
    "💥": "5895638385300606573",
    "🎙": "5800807165262306582",
    "🎤": "5798827614835581300",
    "🤫": "5800796277520211267",
    "🗣️": "5800855964680723701",
    "🔍": "5798537025938267498",
    "🖥": "5798699538910813626",
    "©": "5798908403170418380",
    "⏸": "5801167435709029054",
    "🆕": "5798926888709660483",
    "🔜": "5800722021830630903",
    "📍": "5800980278214140705",
    "➕": "5798773923449413575",
    "⭐️": "5801027363940605910",
    "🗑": "5800901190686351655",
    "😮": "5800765796137311354",
    "📎": "5800945677957603558",
    "🔈": "5798664874229766837",
    "⌛": "5798757306220945657",
    "🌧": "5800927329857314292",
    "🌛": "5798519661385490150",
    "❄️": "5798620962484133218",
    "🌈": "5798471287168834477",
    "💧": "5798837059468673404",
    "🗓": "5798649884793905183",
    "💡": "5801162784259448444",
    "🥈": "5801109045628680243",
    "🎵": "5798836355094028247",
    "🆓": "5798921812058316243",
    "✏️": "5800769433974611462",
    "🏠": "5801019761848490177",
    "🚩": "5798529973601967087",
    "🎉": "5798812556680240763",
    "🇺🇦": "5228979978296637145",
    "🇵🇱": "5228849784952994382",
    "🇰🇿": "5229225186569497729",
    "🇦🇿": "5228904988167647199",
    "🇪🇺": "5231239461806812430",
    "🇺🇳": "5451772687993031127",
    "🇦🇲": "5230937478361263474",
    "🇷🇺": "5228853994020941586",
    "🇺🇿": "5228887709514217105",
    "🇩🇪": "5228737776500879312",
    "🇯🇵": "5229171752881369793",
    "🇧🇾": "5228928172401112019",
    "🇬🇧": "5913443365499703513",
    "🇮🇳": "5229086076873748176",
    "🇧🇷": "5911148568768418614",
    "🇿🇲": "5404780716368090908",
    "🏴󠁧󠁢󠁷󠁬󠁳󠁿": "5224431333052264232",
    "🇻🇮": "5224395882392201810",
    "🇻🇳": "5222359651282071925",
    "🇻🇦": "5222420266155520507",
    "🇻🇺": "5222126748090512778",
    "🇺🇾": "5222466849370813232",
    "🇺🇬": "5222464040462200940",
    "🇹🇲": "5224256935905208951",
    "🇹🇹": "5224391883777651050",
    "🇹🇬": "5222408051268532030",
    "🇹🇭": "5224638530864556281",
    "🇹🇿": "5224397364155923150",
    "🇹🇯": "5222217865821696536",
    "🇨🇭": "5224707263226194753",
    "🇸🇪": "5222201098269373561",
    "🇸🇿": "5224269666188274723",
    "🇸🇷": "5224567367551428669",
    "🇪🇸": "5222024776976970940",
    "🇱🇰": "5224277294050192388",
    "🇸🇸": "5224618146949773268",
    "🇰🇷": "5222345550904439270",
    "🇿🇦": "5224696216570309138",
    "🇸🇴": "5222370504664428325",
    "🇸🇧": "5222290588207954120",
    "🇸🇮": "5224660718665607511",
    "🇸🇰": "5222401879400528047",
    "🇸🇬": "5224194023224257181",
    "🇸🇱": "5224420995065983217",
    "🇸🇨": "5224467496676896871",
    "🇷🇸": "5222145396838512729",
    "🇸🇳": "5224358988623130949",
    "🏴󠁧󠁢󠁳󠁣󠁴󠁿": "5224580312582861623",
    "🇸🇹": "5221953304426198315",
    "🇼🇸": "5224660353593387686",
    "🇻🇨": "5224541228380467535",
    "🇱🇨": "5222000927023577045",
    "🇷🇼": "5222449197055227754",
    "🇷🇴": "5222273794885826118",
    "🇵🇷": "5224220115150582423",
    "🇵🇹": "5224404094369672274",
    "🇵🇭": "5222065042295376892",
    "🇵🇪": "5224482026551258766",
    "🇵🇾": "5222152565138929235",
    "🇵🇬": "5224500164198149905",
    "🇵🇦": "5222111719999945107",
    "🇵🇰": "5224637061985742245",
    "🇳🇴": "5224465228934163949",
    "🇳🇬": "5224723614166691638",
    "🇳🇪": "5222099049846420864",
    "🇳🇿": "5224573595254009705",
    "🇳🇱": "5224516489368841614",
    "🇳🇵": "5222444378101925267",
    "🇳🇦": "5224690826386351746",
    "🇲🇿": "5222470388423864826",
    "🇲🇪": "5224463399278096980",
    "🇲🇳": "5224192257992701543",
    "🇲🇨": "5221937224068640464",
    "🇲🇩": "5224216473018314447",
    "🇫🇲": "5222280486444873367",
    "🇲🇽": "5221971386238514431",
    "🇲🇺": "5224238347286752315",
    "🇲🇭": "5224538449536624503",
    "🏁": "5222206157740847357",
    "🇧🇲": "5222482143749353810",
    "🇲🇹": "5224731388057497620",
    "🇲🇱": "5224322352552096671",
    "🇲🇻": "5224393700548814960",
    "🇲🇾": "5224312886444174057",
    "🇰🇪": "5222279743415531561",
    "🇲🇬": "5222042605386217334",
    "🇲🇰": "5222470435668505656",
    "🇱🇺": "5224499567197700690",
    "🇱🇹": "5224245902134226386",
    "🇱🇷": "5221998371518034740",
    "🇱🇸": "5224245850594619415",
    "🇱🇻": "5224401229626484931",
    "🇱🇦": "5224200843632324642",
    "🇰🇬": "5224388147156102493",
    "🇽🇰": "5222197129719592160",
    "🇰🇮": "5224652244695134610",
    "🇯🇲": "5222007034467074185",
    "🇮🇪": "5222233374948602940",
    "🇮🇹": "5222460101977190141",
    "🇮🇱": "5224720599099648709",
    "🇮🇷": "5224374154152653367",
    "🇮🇩": "5224405893960969756",
    "🇮🇸": "5222063229819172521",
    "🇭🇺": "5224691998912427164",
    "🇭🇳": "5222434624231191289",
    "🇭🇹": "5224683146984831315",
    "🇬🇾": "5224570532942329532",
    "🇬🇼": "5224705704153066489",
    "🇬🇳": "5222337588035073000",
    "🇬🇹": "5222128302868672826",
    "🇬🇩": "5222234560359577687",
    "🇬🇷": "5222463490706389920",
    "🇬🇭": "5224511339703056124",
    "🇬🇪": "5222152195771742239",
    "🇬🇲": "5221949872747330159",
    "🇬🇦": "5224669733801963467",
    "🇫🇷": "5222029789203804982",
    "🇫🇮": "5224282903277482188",
    "🇫🇯": "5221962676044838178",
    "🇪🇹": "5224467805914542024",
    "🇪🇪": "5222195463272281351",
    "🇬🇶": "5222172811614762423",
    "🏴󠁧󠁢󠁥󠁮󠁧󠁿": "5224402728570071579",
    "🇸🇻": "5224337131534559907",
    "🇪🇨": "5224191188545840926",
    "🇹🇱": "5224515905253291409",
    "🃏": "5375232836020235940",
    "🎪": "5377841891213600379",
    "🎭": "5224450179368767019",
    "🔤": "5801036598120291572",
    "🎴": "5872953068122806160",
    "🃑": "5197288647275071607",
    "🃒": "5875165762259261557",
    "🃓": "5377667979397848775",
    "🃔": "5375296873982604963",
    "🃕": "5318776349907757200",
    "🃖": "5970053985103516666",
    "🃗": "5375296873982604963",
    "🃘": "6041705726206808304",
    "🛠️": "5893161718179173515",
    "⏳": "5902050947567194830",
    "👑": "5875344888165308204",
    "😢": "5872713129774814996",
    "💫": "5875278857338099139",
    "✅": "5875150442110916703",
    "🌟": "5872967623766972414",
    "🪙": "5873245783028929844",
    "🏦": "5872712949386188934",
    "🤑": "5873046706999793897",
    "⬆️": "5873077544864978833",
    "⬇️": "5872697143906540161",
    "⬅️": "5873120988459178827",
    "➡️": "5875365697281857557",
    "🫕": "5875248358775331988",
    "🤒": "5875448749064459684",
    "🤔": "5875236947047224747",
    "🛒": "5874970813693694955",
    "🌐": "5872802027007907176",
    "📹": "5873028294474995070",
    "📷": "5872783408324679279",
    "🐣": "5875376271491340579",
    "🎮": "5873201214153299437",
    "👀": "5872890623593290366",
    "🛍": "5872824468212028704",
    "🛑": "5875044253339490005",
    "🐗": "5875423782419567974",
    "🔴": "5874974992696874989",
    "💝": "5873042072730080813",
    "🚨": "5875377310873425801",
    "🕦": "5875489083102336823",
    "🧡": "5875029783594669567",
    "🫡": "5874998872715040810",
    "🫶": "5875225333455657568",
    "🔥": "5875093791492282301",
    "⭕️": "5873009942079740554",
    "📱": "5872815547564955937",
    "❤": "5872846703257721517",
    "☄️": "5875165762259261557",
    "❤️": "5872748674924159388",
    "💯": "5875486935618689000",
    "‼️": "5874951254412629451",
    "🌕": "5873157491386226821",
    "🖤": "5875187280045414809",
    "❤️‍🔥": "5872930790127441100",
    "🔇": "5873185717911295940",
    "⚡": "5872788532220663259",
    "⚙️": "5874962223759103487",
    "😂": "5875211228783056435",
    "🆔": "5873044297523140571",
    "💰": "6267068789146260253",
    "6267219374994626613": "5872981307532777275",
    "🥲": "5872813833873004587",
    "☺️": "5875219440760526661",
    "😗": "5874995075963950890",
    "🥺": "5875196372491179337",
    "😙": "5875322773378703329",
    "🚢": "5875120282850563668",
    "🫐": "5873178072869509050",
    "🍞": "5875490118189455026",
    "🍟": "5872891345147795955",
    "😐": "5875123465421332021",
    "😠": "5875024470720123981",
    "🌚": "5875053105267087486",
    "🍢": "5873232000478878100",
    "🤓": "5875351742933112000",
    "🙂": "5875467608265856488",
    "😀": "5875458017603884485",
    "😏": "5875154960416511765",
    "🔒": "5872904960194124954",
    "😎": "5875111173224928723",
    "😊": "5875382323100259616",
    "🌸": "5875499988024301358",
    "😽": "5874986378655176018",
    "🇪🇬": "5875214673346828334",
    "🇸🇦": "5872764652202497691",
    "🇵🇸": "5875177345786058139",
    "😄": "5875434378103887732",
    "🥹": "5872958028810032319",
    "💐": "5875249797589375630",
    "🅾": "5875100027784797000",
    "💵": "6267068789146260253",
    "👋": "5875231148841376016",
    "✔️": "5872789425573860900",
    "🚫": "5875291531786590590",
    "🤦‍♂️": "5875308557036950894",
    "😳": "5875142711169784354",
    "🙄": "5872770136875735055",
    "😆": "5873073206948010078",
    "🤝": "5873227619612235088",
    "💬": "5872929200989542843",
    "💘": "5874996690871654238",
    "🕊": "5875195470548047567",
    "💃": "5872889850499176835",
    "🌻": "5873101347573733925",
    "🫵": "5872727870102575896",
    "📣": "5872976900896331921",
    "😞": "5873088381067468415",
    "😼": "5873080632946464998",
    "🌄": "5875134134120094556",
    "🔲": "5872777399665432151",
    "🐈": "5873236789367412414",
    "👊": "5874964736314971438",
    "😖": "5875475751523851414",
    "😁": "5875353151682386339",
    "🤭": "5872904363193670073",
    "😋": "5872793832210306551",
    "🍿": "5875011444084317354",
    "➰": "5875059122516269321",
    "😱": "5872736837994289756",
    "🈵": "5873082260739069484",
    "🍲": "5875414883247331138",
    "🦋": "5875141719032339632",
    "🙈": "5872907962376263970",
    "🫣": "5875268613841098882",
    "💜": "5875027490082133838",
    "☕️": "5875112556204399060",
    "💕": "5874949592260286720",
    "😭": "5873068589858166980",
    "🤨": "5875179823982189155",
    "😡": "5873055653416671071",
    "💞": "5875269962460830099",
    "🛡️": "5801181213964116634",
    "🎯": "5461009483314517035",
    "🔐": "4987971534908819045",
    "📝": "5800855964680723701",
    "👤": "👤",
    # إيموجيات إضافية مستخدمة في رسائل البوت
    "📛": "5873241422491729876",
    "📋": "5873234743640292222",
    "📑": "5873156537836882986",
    "🚸": "5873188114381739890",
    "💼": "5873210622885834348",
    "🔰": "5873157491386226821",
    # إيموجيات إضافية
    "🏷️": "5873234743640292222",
    "📌": "5873157491386226821",
    "⚠️": "5798578124480323191",
    # إيموجيات رسالة الترحيب المميزة الجديدة (Placeholders)
    "5224450179368767019": "5224450179368767019",
    "5801036598120291572": "5801036598120291572",
    "5312361253610475399": "5312361253610475399",
    "5267500801240092311": "5267500801240092311",
    "5319082718514915605": "5319082718514915605",
    "5377667979397848775": "5377667979397848775",
    "5318776349907757200": "5318776349907757200",
    "5875298240525506231": "5875298240525506231",
    "5197434882321567830": "5197434882321567830",
}

# ================================
#  دوال إدارة الحالة
# ================================
def get_user_state(uid):
    uid = str(uid)
    if uid not in db.get('users', {}):
        return {}
    return db['users'][uid].get('_state', {})

def set_user_state(uid, state, **data):
    uid = str(uid)
    if uid not in db.get('users', {}):
        ensure_user_by_id(uid)
    db['users'][uid]['_state'] = {'state': state, 'data': data}
    save_db(db)
    update_user_cache(uid)

def clear_user_state(uid):
    uid = str(uid)
    if uid in db.get('users', {}):
        db['users'][uid].pop('_state', None)
        save_db(db)
        update_user_cache(uid)

# ================================
#  دوال الحظر المؤقت
# ================================
def apply_temp_ban(uid, duration=None):
    """وظيفة قديمة — تم تعطيل الحظر التلقائي.
    الإبقاء عليها كـ no-op لتفادي كسر أي استدعاء قديم في الكود.
    أي محاولة لاستخدامها لن تفعل شيئاً وستطبع تحذير.
    """
    try:
        logger.warning(f"⚠️ تم استدعاء apply_temp_ban() للمستخدم {uid} لكن الحظر التلقائي معطّل — تم التجاهل.")
    except Exception:
        pass
    return False

def is_temp_banned(uid):
    """تحقق إذا المستخدم محظور مؤقتاً"""
    uid = str(uid)
    user = db.get('users', {}).get(uid)
    if not user:
        return False
    ban_until = user.get('temp_ban_until', 0)
    if ban_until and time.time() < ban_until:
        return True
    # إذا انتهت المدة، نظف الحظر
    if ban_until and time.time() >= ban_until:
        user.pop('temp_ban_until', None)
        save_db(db)
        update_user_cache(uid)
    return False

def get_temp_ban_remaining(uid):
    """إرجاع الوقت المتبقي من الحظر"""
    uid = str(uid)
    user = db.get('users', {}).get(uid)
    if not user:
        return 0
    ban_until = user.get('temp_ban_until', 0)
    remaining = ban_until - time.time()
    return max(0, int(remaining))

def format_ban_time(seconds):
    """تنسيق الوقت المتبقي"""
    if seconds <= 0:
        return "0 ثانية"
    mins = seconds // 60
    secs = seconds % 60
    if mins > 0:
        return f"{mins} دقيقة و{secs} ثانية"
    return f"{secs} ثانية"

def fmt_amt(amount, uid):
    """تنسيق المبلغ بناءً على عملة المستخدم المختارة"""
    udata = db['users'].get(str(uid), {})
    currency = udata.get('currency', 'USD')
    if currency == 'EGP':
        egp_val = float(amount) * VOFACASH_RATE_EGP_PER_USD
        return f"{egp_val:,.2f} ج.م"
    # عرض ما يصل إلى ثلاث منازل مع إزالة الأصفار الزائدة: 0.180 تصبح 0.18.
    # تبقى القيم الدقيقة مثل 0.006 محفوظة دون تقريب.
    formatted = f"{float(amount):,.3f}".rstrip('0').rstrip('.')
    return f"{formatted}$"

async def ask_currency(event, uid):
    """إرسال رسالة اختيار العملة للعضو الجديد"""
    text = (
        "🌟 *أهلاً بك يا بطل!* 🌟\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "لتقديم أفضل تجربة لك، يرجى اختيار العملة التي تفضل عرض الأسعار بها داخل البوت:\n\n"
        "🇪🇬 *الجنيه المصري (EGP)*\n"
        "🇺🇸 *الدولار الأمريكي (USD)*\n\n"
        "💡 يمكنك تغيير هذا الخيار لاحقاً من القائمة الرئيسية."
    )
    buttons = [
        [Button.inline("🇪🇬 الجنيه المصري", b"set_currency:EGP"),
         Button.inline("🇺🇸 الدولار الأمريكي", b"set_currency:USD")]
    ]
    # محاولة إرسال ملصق مميز إذا أمكن (اختياري)
    try:
        # ملصق ترحيبي (مثال)
        await bot.send_file(event.chat_id, "CAACAgIAAxkBAAEL6pll9z2S5S4S4S4S4S4S4S4S4S4", silent=True)
    except:
        pass
        
    if hasattr(event, 'edit'):
        await safe_edit(event, text, buttons=buttons)
    else:
        await send_msg(event, text, buttons=buttons)

def ensure_user_by_id(uid):
    uid = str(uid)
    if uid in _USER_CACHE:
        return _USER_CACHE[uid]
    if uid not in db['users']:
        is_owner = (int(uid) in ADMINS)
        db['users'][uid] = {
            'username': '',
            'full_name': f'User_{uid}',
            'balance': 0.0,
            'verified': False, # تفعيل الكابتشا للجميع في البداية
            'registered': True, # اعتبار الجميع مسجلين لتخطي واجهة التسجيل الملغاة
            'bot_username': None,
            'bot_password': None,
            'banned': False,
            'total_spent': 0.0,
            'total_deposited': 0.0,
            'joined_at': datetime.now().isoformat(),

            'lang': 'ar',
            'currency': None,
            'referral_points': 0.0,
            '_state': {}
        }
        save_db(db)
    _USER_CACHE[uid] = db['users'][uid]
    return _USER_CACHE[uid]

# ================================
#  دوال الإيموجيات المخصصة (كاملة)
# ================================
def get_active_custom_emojis():
    try:
        db_emojis = db.get('custom_emojis', {}) or {}
    except Exception:
        db_emojis = {}
    merged = dict(CUSTOM_EMOJIS)
    for k, v in db_emojis.items():
        if k and v:
            merged[k] = str(v)
    return merged

def _build_custom_emoji_entities(text):
    active = get_active_custom_emojis()
    if not text or not active:
        return []
    keys_sorted = sorted(active.keys(), key=len, reverse=True)
    entities = []
    pos = 0
    text_idx = 0
    text_len = len(text)
    while text_idx < text_len:
        matched = False
        for emo in keys_sorted:
            if text.startswith(emo, text_idx):
                emo_utf16_len = len(emo.encode('utf-16-le')) // 2
                doc_id = active.get(emo)
                if doc_id:
                    try:
                        entities.append(MessageEntityCustomEmoji(
                            offset=pos,
                            length=emo_utf16_len,
                            document_id=int(doc_id)
                        ))
                    except Exception as e:
                        logger.debug(f"custom emoji entity build failed: {e}")
                pos += emo_utf16_len
                text_idx += len(emo)
                matched = True
                break
        if not matched:
            ch = text[text_idx]
            pos += len(ch.encode('utf-16-le')) // 2
            text_idx += 1
    return entities

_EMOJI_PLACEHOLDER_RE = re.compile(r"\(EMOJI(\d+)\)")

def _apply_emoji_placeholders(text):
    if not text or '(EMOJI' not in text:
        return text, []
    # يجب ألا يكون الـ placeholder أرقاماً؛ عند رفض Bot API للـ custom entity
    # كان المسار الاحتياطي يرسل الـ placeholder كما هو للمستخدم.
    # هذا الرمز يظهر بشكل طبيعي كبديل آمن، ويُستبدل بالـ custom emoji عند نجاح الكيان.
    placeholder_char = "🔹"
    result_chars = []
    entities = []
    utf16_pos = 0
    last_end = 0
    for m in _EMOJI_PLACEHOLDER_RE.finditer(text):
        segment = text[last_end:m.start()]
        result_chars.append(segment)
        utf16_pos += len(segment.encode('utf-16-le')) // 2
        doc_id = m.group(1)
        placeholder_len = len(placeholder_char.encode('utf-16-le')) // 2
        try:
            entities.append(MessageEntityCustomEmoji(
                offset=utf16_pos,
                length=placeholder_len,
                document_id=int(doc_id)
            ))
        except Exception as e:
            logger.debug(f"placeholder emoji entity failed: {e}")
        result_chars.append(placeholder_char)
        utf16_pos += placeholder_len
        last_end = m.end()
    result_chars.append(text[last_end:])
    return "".join(result_chars), entities

def _telethon_entities_to_bot_api(entities):
    if not entities: return None
    bot_api_entities = []
    for e in entities:
        try:
            e_dict = {"offset": e.offset, "length": e.length}
            if isinstance(e, MessageEntityBold): e_dict["type"] = "bold"
            elif isinstance(e, MessageEntityItalic): e_dict["type"] = "italic"
            elif isinstance(e, MessageEntityCode): e_dict["type"] = "code"
            elif isinstance(e, MessageEntityPre): e_dict["type"] = "pre"
            elif isinstance(e, MessageEntityTextUrl): 
                e_dict["type"] = "text_link"
                e_dict["url"] = e.url
            elif isinstance(e, MessageEntityMention): e_dict["type"] = "mention"
            elif isinstance(e, MessageEntityHashtag): e_dict["type"] = "hashtag"
            elif isinstance(e, MessageEntityUrl): e_dict["type"] = "url"
            elif isinstance(e, MessageEntityCustomEmoji):
                e_dict["type"] = "custom_emoji"
                e_dict["custom_emoji_id"] = str(e.document_id)
            else: continue
            bot_api_entities.append(e_dict)
        except Exception:
            continue
    return bot_api_entities if bot_api_entities else None

def _merge_entities_with_custom_emojis(client, text, parse_mode='md'):
    text_with_placeholders, placeholder_entities = _apply_emoji_placeholders(text)
    try:
        if parse_mode:
            from telethon.extensions import markdown as md_parser
            from telethon.extensions import html as html_parser
            if str(parse_mode).lower() in ('md', 'markdown'):
                plain, base_entities = md_parser.parse(text_with_placeholders)
            elif str(parse_mode).lower() == 'html':
                plain, base_entities = html_parser.parse(text_with_placeholders)
            else:
                plain, base_entities = text_with_placeholders, []
        else:
            plain, base_entities = text_with_placeholders, []
    except Exception as e:
        logger.debug(f"parse fallback: {e}")
        plain, base_entities = text_with_placeholders, []

    fixed_placeholder_entities = []
    placeholder_char = '🔹'
    if placeholder_char in plain:
        # ابحث عن سلسلة الـ placeholder كاملة؛ المرور حرفاً حرفاً كان يجعل
        # الأرقام تظهر للمستخدم بدلاً من تحويلها إلى custom emoji entity.
        doc_ids = [e.document_id for e in placeholder_entities]
        idx = 0
        search_pos = 0
        while idx < len(doc_ids):
            found = plain.find(placeholder_char, search_pos)
            if found < 0:
                break
            try:
                offset = len(plain[:found].encode('utf-16-le')) // 2
                length = len(placeholder_char.encode('utf-16-le')) // 2
                fixed_placeholder_entities.append(MessageEntityCustomEmoji(
                    offset=offset, length=length, document_id=doc_ids[idx]
                ))
            except Exception:
                pass
            idx += 1
            search_pos = found + len(placeholder_char)

    custom_entities = _build_custom_emoji_entities(plain)
    return plain, (base_entities or []) + fixed_placeholder_entities + custom_entities

async def send_msg(target, text, buttons=None, **kwargs):
    parse_mode = kwargs.pop('parse_mode', 'md')
    cli = getattr(target, 'client', None) or (bot if isinstance(target, int) else target)
    plain, entities = _merge_entities_with_custom_emojis(cli, text, parse_mode)
    
    if buttons:
        try:
            chat_id = None
            if hasattr(target, 'chat_id'):
                chat_id = target.chat_id
            elif hasattr(target, 'id'):
                chat_id = target.id
            if chat_id:
                bot_entities = _telethon_entities_to_bot_api(entities)
                resp = await fast_send_with_colored_buttons(chat_id, plain, buttons, entities=bot_entities)
                if resp and resp.get("ok"):
                    return
        except Exception as fast_e:
            logger.debug(f"fast_send failed, falling back: {fast_e}")

    try:
        cli = getattr(target, 'client', None) or (bot if isinstance(target, int) else target)
        plain, entities = _merge_entities_with_custom_emojis(cli, text, parse_mode)
        if hasattr(target, 'respond'):
            return await target.respond(
                plain,
                buttons=buttons,
                formatting_entities=entities if entities else None,
                **kwargs
            )
        if isinstance(target, int):
            return await bot.send_message(
                target,
                plain,
                buttons=buttons,
                formatting_entities=entities if entities else None,
                **kwargs
            )
        entity = kwargs.pop('entity', None)
        return await cli.send_message(
            entity,
            plain,
            buttons=buttons,
            formatting_entities=entities if entities else None,
            **kwargs
        )
    except Exception as e:
        logger.error(f"send_msg failed: {e} — falling back")
        if isinstance(target, int):
            return await bot.send_message(target, text, buttons=buttons, parse_mode=parse_mode, **kwargs)
        if hasattr(target, 'respond'):
            return await target.respond(text, buttons=buttons, parse_mode=parse_mode, **kwargs)
        entity = kwargs.pop('entity', None)
        try:
            return await target.send_message(entity, text, buttons=buttons, parse_mode=parse_mode, **kwargs)
        except Exception:
            return await bot.send_message(target, text, buttons=buttons, parse_mode=parse_mode, **kwargs)

# ================================
#  دوال الأزرار الملونة (كاملة)
# ================================
def _btn_text_value(btn):
    raw = getattr(btn, 'button', btn)
    txt = getattr(raw, 'text', None) or getattr(btn, 'text', None)
    return _compact_button_text(txt) if txt else ""

def _is_button_hidden(btn):
    try:
        hidden = db.get('hidden_buttons', []) or []
    except Exception:
        return False
    if not hidden:
        return False
    txt = _btn_text_value(btn)
    if not txt:
        return False
    stripped = _compact_button_text(_strip_static_button_icon(txt))
    for h in hidden:
        h_norm = _compact_button_text(h)
        if not h_norm:
            continue
        if h_norm == txt or h_norm == stripped:
            return True
        if h_norm == _compact_button_text(_strip_static_button_icon(h_norm)):
            if _compact_button_text(_strip_static_button_icon(h_norm)) == stripped:
                return True
    return False

def _filter_hidden_buttons(rows):
    try:
        hidden = db.get('hidden_buttons', []) or []
    except Exception:
        return rows
    if not hidden:
        return rows
    new_rows = []
    for row in rows:
        if not isinstance(row, (list, tuple)):
            if _is_button_hidden(row):
                continue
            new_rows.append(row)
            continue
        kept = [b for b in row if not _is_button_hidden(b)]
        if kept:
            new_rows.append(kept)
    return new_rows

def _normalize_button_rows(buttons):
    if not buttons:
        return []
    if not isinstance(buttons, (list, tuple)):
        rows = [[buttons]]
    elif buttons and not isinstance(buttons[0], (list, tuple)):
        rows = [list(buttons)]
    else:
        rows = list(buttons)
    rows = _filter_hidden_buttons(rows)
    return rows

def _decode_callback_data(data):
    if data is None:
        return None
    if isinstance(data, bytes):
        return data.decode("utf-8", "ignore")
    return str(data)

def _stable_index(value, size):
    if size <= 0:
        return 0
    value = str(value or "")
    total = 0
    for ch in value:
        total = (total * 131 + ord(ch)) % 1_000_000_007
    return total % size

def _compact_button_text(text):
    return " ".join(str(text or "").strip().split())

def _strip_static_button_icon(text):
    text = str(text or "").strip()
    for prefix in _STATIC_ICON_PREFIXES:
        if text.startswith(prefix):
            return text[len(prefix):].strip()
    return text

def _get_button_icon_id(text, callback_data=None, url=None):
    if not text: return None
    compact = _compact_button_text(text)
    
    # محاولة المطابقة المباشرة
    if compact in BUTTON_ICON_BY_TEXT:
        return BUTTON_ICON_BY_TEXT[compact]

    # محاولة المطابقة بعد تنظيف الأيقونات القديمة
    clean = _compact_button_text(_strip_static_button_icon(compact))
    for known_text, emoji_id in BUTTON_ICON_BY_TEXT.items():
        known_clean = _compact_button_text(_strip_static_button_icon(known_text))
        if clean == known_clean or clean in known_clean or known_clean in clean:
            return emoji_id

    if callback_data in BUTTON_ICON_BY_CALLBACK:
        return BUTTON_ICON_BY_CALLBACK[callback_data]
    if callback_data and (
        callback_data.startswith("buy_c:unverified:")
        or callback_data.startswith("bs_c:unverified:")
    ):
        return "6037597564218384009"
    if callback_data and (
        callback_data.startswith("buy_c:spam:")
        or callback_data.startswith("bs_c:spam:")
    ):
        return "5895576786879647172"
    if callback_data and callback_data.startswith('buy_c:monthly:'):
        return '4958714479681471536'

    if compact.startswith("➕"):
        return "5287354223141342798"
    if compact.startswith("🗑"):
        return "5879937509579820068"
    if compact.startswith("🗒"):
        return "5897484821805929855"

    if url and "t.me" in str(url).lower() and "مطور" in compact:
        return "5388816589216823151"
    return None

def _remove_icon_fields(markup):
    if not markup:
        return markup
    try:
        clean_markup = json.loads(json.dumps(markup, ensure_ascii=False))
        for row in clean_markup.get("inline_keyboard", []):
            for button in row:
                button.pop("icon_custom_emoji_id", None)
        return clean_markup
    except:
        return markup

def _get_button_override(text, callback_data=None):
    try:
        overrides = db.get('button_overrides', {}) or {}
    except Exception:
        return None
    if not overrides:
        return None
    if callback_data and callback_data in overrides:
        return overrides[callback_data]
    compact = _compact_button_text(text)
    if compact in overrides:
        return overrides[compact]
    clean = _compact_button_text(_strip_static_button_icon(compact))
    if clean and clean in overrides:
        return overrides[clean]
    return None

def _button_to_bot_api(button):
    # زر Telegram الأصلي لنسخ النص مباشرة إلى حافظة المستخدم.
    # يُرسل عبر Bot API لأن Telethon لا يوفّر له wrapper مباشرًا في بعض الإصدارات.
    if isinstance(button, dict) and button.get('_copy_text'):
        return {
            'text': str(button.get('label') or '📋 Copy'),
            'copy_text': {'text': str(button.get('copy_value') or '')}
        }
    raw_button = getattr(button, 'button', button)
    text = getattr(raw_button, 'text', None) or getattr(button, 'text', None) or str(button)
    url = getattr(raw_button, 'url', None) or getattr(button, 'url', None)
    data = getattr(raw_button, 'data', None) or getattr(button, 'data', None)
    
    callback_data = _decode_callback_data(data)
    if not callback_data and not url:
        callback_data = "noop"

    icon_id = _get_button_icon_id(text, callback_data, url)
    if icon_id:
        shown_text = _strip_static_button_icon(text)
    else:
        shown_text = text

    # ===== تلوين الأزرار (أخضر وأزرق) =====
    # تحديد اللون بناءً على نوع الزر
    cd_lower = (callback_data or "").lower()
    text_lower = (shown_text or "").lower()
    
    # الأزرار الخضراء (success): شحن، دفع، شراء، تأكيد، موافقة
    green_keywords = [
        "deposit", "pay", "buy", "confirm", "approve", "charge", "addbal",
        "binance", "vodafone", "stars", "manual", "submit_tx", "paid",
        "mp_send", "aa:add", "aa:add_session", "am:add", "ab:add",
        "ac:add", "ae:add", "ah:add", "abe:add", "back_main",
        "buy_c:", "bs_c:", "confirm_buy", "execute_bs", "req_code",
        "buy_type:spam", "buy_sessions_type:spam",
        "buy_type:old_spam", "buy_sessions_type:old_spam",
        "buy_type:unverified", "buy_sessions_type:unverified",
        "my_balance", "my_purchases", "info", "deposit", "transfer",
        "change_lang", "rules", "logout", "verify_captcha",
        "captcha_ans", "check_sub", "cancel_action",
    ]
    
    # الأزرار الزرقاء (primary): لوحة تحكم، إدارة، عرض، تعديل
    blue_keywords = [
        "شراء أرقام", "MOSCOWiqBOT",
        "a:stats", "a:txs", "a:addbal", "a:subbal",
        "a:ban", "a:broadcast", "a:accounts", "a:manualpay",
        "a:mainbtns", "a:hidebtns", "a:welcome",
        "a:ref_settings", "a:channels", "a:maintenance", "a:clear_points",
        "a:backup", "a:restore", "a:import_sessions", "a:close", "a:panel",
        "a:countries", "ac:list", "ac:edit", "ac:edit_name", "ac:del",
        "am:list", "am:del", "aw:set", "lang:",
        "ae:list", "ae:del", "ah:list", "ah:del", "ah:clear",
        "ab:list", "ab:del", "abe:list", "abe:manual", "abe:show",
        "abe:reset", "abe:clearall", "a:btnedit", "ac_fs:",
        "a:edit_ref", "a:manualpay",
        "import_mixed", "import_normal", "import_current",
        "a_cancel", "cancel_deposit", "a:manual", "a:welcome",
    ]
    
    # تحديد اللون
    is_green = False
    is_blue = False

    # أزرار الدول داخل قسمي السبام يجب أن تبقى خضراء صراحةً؛ لا نعتمد
    # على التخمين أو على نص اسم الدولة لتحديد لونها.
    is_spam_country_button = cd_lower.startswith(("buy_c:", "bs_c:"))
    if is_spam_country_button:
        is_green = True

    # زر شراء أرقام في رسائل قناة التفعيلات رابط مباشر، لذلك نثبّت لونه بالأزرق
    # اعتمادًا على رابط البدء buy وليس على callback_data.
    is_activation_buy_button = bool(url and "?start=buy" in str(url).lower())
    if is_activation_buy_button:
        is_blue = True
    
    for kw in green_keywords:
        if is_activation_buy_button:
            break
        if cd_lower and (kw in cd_lower or cd_lower.startswith(kw.rstrip(":"))):
            is_green = True
            break
        if text_lower and kw in text_lower:
            is_green = True
            break
    
    if not is_green and not is_activation_buy_button:
        for kw in blue_keywords:
            if cd_lower and (kw in cd_lower or cd_lower.startswith(kw.rstrip(":"))):
                is_blue = True
                break
            if text_lower and kw in text_lower:
                is_blue = True
                break
    
    # تعيين الـ style
    if is_green:
        style = "success"  # أخضر
    elif is_blue:
        style = "primary"  # أزرق
    else:
        # نفس توزيع الألوان في الملف المرجعي للأزرار غير المصنفة، مع بقاء
        # أزرار السبام محددة صراحةً بالأخضر في الشرط السابق.
        style_key = callback_data or url or text
        btn_hash = 0
        for char in str(style_key):
            btn_hash = (btn_hash * 31 + ord(char)) % 100
        style = "primary" if btn_hash < 50 else "success"

    item = {"text": shown_text, "style": style}
    if icon_id:
        item["icon_custom_emoji_id"] = str(icon_id)
    if url:
        item["url"] = url
    else:
        item["callback_data"] = str(callback_data)
    return item

def build_colored_reply_markup(buttons):
    rows = []
    for row in _normalize_button_rows(buttons):
        converted_row = []
        for button in row:
            try:
                converted_row.append(_button_to_bot_api(button))
            except Exception:
                continue
        if converted_row:
            rows.append(converted_row)
    if not rows:
        return None
    return {"inline_keyboard": rows}

import http.client
import ssl
async def bot_api_request(method, payload):
    """طلب Bot API بمحدد معدل وbackoff تدريجي عند 429 والأخطاء المؤقتة."""
    global _bot_api_last_started
    url_path = f"/bot{BOT_TOKEN}/{method}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def _post_fast():
        conn = None
        try:
            context = ssl.create_default_context()
            conn = http.client.HTTPSConnection("api.telegram.org", context=context, timeout=30)
            conn.request("POST", url_path, body=data, headers={"Content-Type": "application/json", "Connection": "close"})
            resp = conn.getresponse()
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                result = json.loads(raw)
            except json.JSONDecodeError:
                result = {"ok": False, "description": raw[:300]}
            result["_http_status"] = resp.status
            return result
        except Exception as e:
            return {"ok": False, "description": str(e), "_http_status": 0}
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    for attempt in range(6):
        async with _bot_api_rate_lock:
            now = time.monotonic()
            wait_for = max(0.0, BOT_API_MIN_INTERVAL - (now - _bot_api_last_started))
            if wait_for:
                await asyncio.sleep(wait_for)
            _bot_api_last_started = time.monotonic()
            result = await asyncio.to_thread(_post_fast)

        status = int(result.pop("_http_status", 0) or 0)
        if result.get("ok"):
            return result
        if status == 429 or result.get("error_code") == 429:
            params = result.get("parameters") or {}
            retry_after = int(params.get("retry_after", 0) or 0)
            delay = max(retry_after, min(60, 2 ** (attempt + 2))) + random.uniform(0.5, 1.5)
            logger.warning(f"⚠️ Bot API 429 في {method}; إعادة المحاولة بعد {delay:.1f} ثانية")
            await asyncio.sleep(delay)
            continue
        if status in (408, 425, 500, 502, 503, 504) or status == 0:
            delay = min(30, 2 ** attempt) + random.uniform(0.2, 0.8)
            await asyncio.sleep(delay)
            continue
        return result
    return {"ok": False, "description": f"Bot API فشل بعد عدة محاولات: {method}"}

async def apply_colored_buttons(chat_id, message_id, buttons):
    reply_markup = build_colored_reply_markup(buttons)
    if not reply_markup or not chat_id or not message_id:
        return
    response = await bot_api_request(
        "editMessageReplyMarkup",
        {"chat_id": chat_id, "message_id": message_id, "reply_markup": reply_markup},
    )
    if not response.get("ok"):
        fallback_markup = _remove_icon_fields(reply_markup)
        await bot_api_request(
            "editMessageReplyMarkup",
            {"chat_id": chat_id, "message_id": message_id, "reply_markup": fallback_markup},
        )

async def fast_edit_with_colored_buttons(chat_id, message_id, text, buttons,
                                          parse_mode='Markdown',
                                          disable_web_page_preview=True,
                                          entities=None):
    if not chat_id or not message_id:
        return None
    reply_markup = build_colored_reply_markup(buttons) if buttons else None
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text or "",
        "disable_web_page_preview": disable_web_page_preview,
    }
    if entities:
        payload["entities"] = entities
    else:
        payload["parse_mode"] = parse_mode
        
    if reply_markup:
        payload["reply_markup"] = reply_markup
    resp = await bot_api_request("editMessageText", payload)
    if not resp.get("ok"):
        # إذا رفض Bot API أيقونة زر مخصصة، أعد المحاولة بدون الأيقونة
        # مع إبقاء style الأخضر وكيانات الإيموجي داخل نص الرسالة.
        if "reply_markup" in payload:
            payload["reply_markup"] = _remove_icon_fields(payload["reply_markup"])
        resp = await bot_api_request("editMessageText", payload)
        if resp.get("ok"):
            return resp
        # محاولة أخيرة بدون كيانات النص عند تعذر قبولها أيضًا.
        if "entities" in payload:
            del payload["entities"]
            payload["parse_mode"] = parse_mode
        resp = await bot_api_request("editMessageText", payload)
    return resp

async def fast_send_with_colored_buttons(chat_id, text, buttons,
                                          parse_mode='Markdown',
                                          disable_web_page_preview=True,
                                          entities=None):
    if not chat_id:
        return None
    reply_markup = build_colored_reply_markup(buttons) if buttons else None
    payload = {
        "chat_id": chat_id,
        "text": text or "",
        "disable_web_page_preview": disable_web_page_preview,
    }
    if entities:
        payload["entities"] = entities
    else:
        payload["parse_mode"] = parse_mode
        
    if reply_markup:
        payload["reply_markup"] = reply_markup
    resp = await bot_api_request("sendMessage", payload)
    if not resp.get("ok"):
        # إعادة المحاولة بدون أيقونات الأزرار فقط، مع الحفاظ على style
        # والـ custom emojis الموجودة داخل نص الرسالة.
        if "reply_markup" in payload:
            payload["reply_markup"] = _remove_icon_fields(payload["reply_markup"])
        resp = await bot_api_request("sendMessage", payload)
        if resp.get("ok"):
            return resp
        if "entities" in payload:
            del payload["entities"]
            payload["parse_mode"] = parse_mode
        resp = await bot_api_request("sendMessage", payload)
    return resp

def _event_message_id(event):
    return (
        getattr(event, "message_id", None)
        or getattr(event, "id", None)
        or getattr(getattr(event, "query", None), "msg_id", None)
    )

def _message_chat_id(message, fallback=None):
    return getattr(message, "chat_id", None) or fallback

def _message_id(message, fallback=None):
    return getattr(message, "id", None) or getattr(message, "message_id", None) or fallback

_ORIGINAL_NEW_RESPOND = getattr(events.NewMessage.Event, "respond", None)
_ORIGINAL_CALLBACK_RESPOND = getattr(events.CallbackQuery.Event, "respond", None)
_ORIGINAL_CALLBACK_EDIT = getattr(events.CallbackQuery.Event, "edit", None)

# Patching logic removed for stability

# ================================
#  الترجمات والدوال الأساسية
# ================================
TRANSLATIONS = {
    'ar': {
        'welcome': (
            "**• مرحبا بك عزيزي المستخدم**\n"
            "- في - بوت ارقام MOSCOW NAMBER\n"
            "- لخدمات الحسابات التيلجرام الجاهزة .\n\n"
            "1 - أكثر من 200 دولة في المخزون مع إضافات جديدة .\n"
            "2 - سرعة العمل، أرخص بوت لبيع الأرقام الجاهزة \n"
            "3 - سعر الرقم يبدأ من 0.21 سنت ويحتوي على أكثر دول العالم\n"
            "4 - يحتوي على الأرقام النادرة .\n\n"
            "- يرجى بدء الاستخدام بإنشاء حساب، إذا لديك حساب من قبل، قم بالضغط على زر تسجيل الدخول.\n\n"
            "الإدارة والدعم الفني:  @MOSCOW108BOT"
        ),
        'buy': "شراء أرقام",
        'buy_sessions': "شراء جلسات",
        'daily_gift': "هدية يومية",
        'my_account': "⑤ حسابي",
        'deposit': "شحن رصيد",
        'referral': "رابط دعوة",
        'transfer': "تحويل رصيد",
        'change_lang': "تغيير اللغة",
        'rules': "الشروط",
        'updates': "التحديثات",
        'activations': "قناة التفعيلات",
        'support': "الدعم الفني",
        'closed_temp': " (مقفل مؤقتاً)",
        'sold_count': "عدد الأرقام المباعة: "
    },
    'en': {
        'welcome': (
            "Welcome!\n\n"
            "Global Numbers Bot\n"
            "────────────────────────\n"
            "• Numbers from all countries\n"
            "• 100% Genuine accounts\n"
            "• Instant delivery after purchase\n"
            "• Guarantee on all numbers\n"
            "• Competitive prices\n"
            "• Daily gifts and offers\n"
            "────────────────────────\n\n"
            "ID: {id}\n"
            "Balance: ${balance}\n\n"
            "Choose from the menu:"
        ),
        'buy': "Buy Numbers",
        'buy_sessions': "Buy Sessions",
        'daily_gift': "Daily Gift",
        'my_account': "⑤ My Account",
        'deposit': "Deposit",
        'referral': "Referral Link",
        'transfer': "Transfer Balance",
        'change_lang': "Change Language",
        'rules': "Rules",
        'updates': "Updates",
        'activations': "Activations",
        'support': "Support",
        'closed_temp': " (Temporarily Closed)",
        'sold_count': "Sold Numbers: "
    },
    'fa': {
        'welcome': (
            "خوش آمدید!\n\n"
            "🤖 ربات شماره‌های MOSCOW NAMBER\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "• شماره‌های کشورهای مختلف\n"
            "• تحویل سریع پس از خرید\n"
            "• قیمت‌های مناسب و خدمات مطمئن\n\n"
            "از منوی زیر گزینه موردنظر خود را انتخاب کنید."
        ),
        'buy': "خرید شماره",
        'buy_sessions': "خرید سشن",
        'daily_gift': "هدیه روزانه",
        'my_account': "⑤ حساب من",
        'deposit': "افزایش موجودی",
        'referral': "لینک دعوت",
        'transfer': "انتقال موجودی",
        'change_lang': "تغییر زبان",
        'rules': "قوانین",
        'updates': "به‌روزرسانی‌ها",
        'activations': "کانال فعال‌سازی",
        'support': "پشتیبانی",
        'closed_temp': " (موقتاً بسته است)",
        'sold_count': "تعداد شماره‌های فروخته‌شده: ",
        'change_currency': "تغییر ارز 💱",
        'choose_language': "زبان موردنظر خود را انتخاب کنید"
    },
    'zh': {
        'welcome': (
            "欢迎使用！\n\n"
            "🤖 MOSCOW NAMBER 号码机器人\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "• 支持多个国家的号码\n"
            "• 购买后快速交付\n"
            "• 价格优惠，服务稳定\n\n"
            "请从下面的菜单选择操作。"
        ),
        'buy': "购买号码",
        'buy_sessions': "购买会话",
        'daily_gift': "每日礼物",
        'my_account': "⑤ 我的账户",
        'deposit': "充值余额",
        'referral': "邀请链接",
        'transfer': "转账余额",
        'change_lang': "更改语言",
        'rules': "使用规则",
        'updates': "更新频道",
        'activations': "激活频道",
        'support': "技术支持",
        'closed_temp': "（暂时关闭）",
        'sold_count': "已售号码数量：",
        'change_currency': "更改货币 💱",
        'choose_language': "请选择您使用的语言"
    }
}

DEFAULT_WELCOME = TRANSLATIONS['ar']['welcome']

# ================================
#  دوال قاعدة البيانات المساعدة
# ================================
def _next(key):
    val = db['settings'].get(key, 1)
    db['settings'][key] = val + 1
    save_db(db)
    return val

ALL_COUNTRIES = [
    ("1242", "🇧🇸 الباهاماس"), ("1246", "🇧🇧 باربادوس"), ("1264", "🇦🇮 أنغويلا"),
    ("1268", "🇦🇬 أنتيغوا"), ("1284", "🇻🇬 جزر العذراء البريطانية"),
    ("1340", "🇻🇮 جزر العذراء الأمريكية"), ("1345", "🇰🇾 جزر كايمان"),
    ("1441", "🇧🇲 برمودا"), ("1473", "🇬🇩 غرينادا"), ("1649", "🇹🇨 تركس وكايكوس"),
    ("1664", "🇲🇸 مونتسرات"), ("1670", "🇲🇵 ماريانا الشمالية"), ("1671", "🇬🇺 غوام"),
    ("1684", "🇦🇸 ساموا الأمريكية"), ("1721", "🇸🇽 سينت مارتن"),
    ("1758", "🇱🇨 سانت لوسيا"), ("1767", "🇩🇲 دومينيكا"), ("1784", "🇻🇨 سانت فينسنت"),
    ("1787", "🇵🇷 بورتوريكو"), ("1809", "🇩🇴 الدومينيكان"),
    ("1868", "🇹🇹 ترينيداد"), ("1869", "🇰🇳 سانت كيتس"),
    ("1876", "🇯🇲 جامايكا"),
    ("212", "🇲🇦 المغرب"), ("213", "🇩🇿 الجزائر"), ("216", "🇹🇳 تونس"),
    ("218", "🇱🇾 ليبيا"), ("220", "🇬🇲 غامبيا"), ("221", "🇸🇳 السنغال"),
    ("222", "🇲🇷 موريتانيا"), ("223", "🇲🇱 مالي"), ("224", "🇬🇳 غينيا"),
    ("225", "🇨🇮 ساحل العاج"), ("226", "🇧🇫 بوركينا فاسو"), ("227", "🇳🇪 النيجر"),
    ("228", "🇹🇬 توغو"), ("229", "🇧🇯 بنين"), ("230", "🇲🇺 موريشيوس"),
    ("231", "🇱🇷 ليبيريا"), ("232", "🇸🇱 سيراليون"), ("233", "🇬🇭 غانا"),
    ("234", "🇳🇬 نيجيريا"), ("235", "🇹🇩 تشاد"), ("236", "🇨🇫 إفريقيا الوسطى"),
    ("237", "🇨🇲 الكاميرون"), ("238", "🇨🇻 الرأس الأخضر"), ("239", "🇸🇹 ساو تومي"),
    ("240", "🇬🇶 غينيا الاستوائية"), ("241", "🇬🇦 الغابون"), ("242", "🇨🇬 الكونغو"),
    ("243", "🇨🇩 الكونغو الديمقراطية"), ("244", "🇦🇴 أنغولا"), ("245", "🇬🇼 غينيا بيساو"),
    ("248", "🇸🇨 سيشل"), ("249", "🇸🇩 السودان"), ("250", "🇷🇼 رواندا"),
    ("251", "🇪🇹 إثيوبيا"), ("252", "🇸🇴 الصومال"), ("253", "🇩🇯 جيبوتي"),
    ("254", "🇰🇪 كينيا"), ("255", "🇹🇿 تنزانيا"), ("256", "🇺🇬 أوغندا"),
    ("257", "🇧🇮 بوروندي"), ("258", "🇲🇿 موزمبيق"),
    ("260", "🇿🇲 زامبيا"), ("261", "🇲🇬 مدغشقر"), ("262", "🇷🇪 ريونيون"),
    ("263", "🇿🇼 زيمبابوي"), ("264", "🇳🇦 ناميبيا"), ("265", "🇲🇼 ملاوي"),
    ("266", "🇱🇸 ليسوتو"), ("267", "🇧🇼 بوتسوانا"), ("268", "🇸🇿 إسواتيني"),
    ("269", "🇰🇲 جزر القمر"), ("291", "🇪🇷 إريتريا"),
    ("351", "🇵🇹 البرتغال"), ("352", "🇱🇺 لوكسمبورغ"), ("353", "🇮🇪 أيرلندا"),
    ("354", "🇮🇸 آيسلندا"), ("355", "🇦🇱 ألبانيا"), ("356", "🇲🇹 مالطا"),
    ("357", "🇨🇾 قبرص"), ("358", "🇫🇮 فنلندا"), ("359", "🇧🇬 بلغاريا"),
    ("370", "🇱🇹 ليتوانيا"), ("371", "🇱🇻 لاتفيا"), ("372", "🇪🇪 إستونيا"),
    ("373", "🇲🇩 مولدوفا"), ("374", "🇦🇲 أرمينيا"), ("375", "🇧🇾 بيلاروسيا"),
    ("376", "🇦🇩 أندورا"), ("377", "🇲🇨 موناكو"), ("378", "🇸🇲 سان مارينو"),
    ("380", "🇺🇦 أوكرانيا"), ("381", "🇷🇸 صربيا"), ("382", "🇲🇪 الجبل الأسود"),
    ("383", "🇽🇰 كوسوفو"), ("385", "🇭🇷 كرواتيا"), ("386", "🇸🇮 سلوفينيا"),
    ("387", "🇧🇦 البوسنة"), ("389", "🇲🇰 مقدونيا الشمالية"),
    ("420", "🇨🇿 التشيك"), ("421", "🇸🇰 سلوفاكيا"), ("423", "🇱🇮 ليختنشتاين"),
    ("500", "🇫🇰 فوكلاند"), ("501", "🇧🇿 بليز"), ("502", "🇬🇹 غواتيمالا"),
    ("503", "🇸🇻 السلفادور"), ("504", "🇭🇳 هندوراس"), ("505", "🇳🇮 نيكاراغوا"),
    ("506", "🇨🇷 كوستاريكا"), ("507", "🇵🇦 بنما"), ("509", "🇭🇹 هايتي"),
    ("591", "🇧🇴 بوليفيا"), ("592", "🇬🇾 غيانا"), ("593", "🇪🇨 الإكوادور"),
    ("595", "🇵🇾 باراغواي"), ("597", "🇸🇷 سورينام"), ("598", "🇺🇾 أوروغواي"),
    ("670", "🇹🇱 تيمور الشرقية"), ("672", "🇦🇶 أنتاركتيكا"), ("673", "🇧🇳 بروناي"),
    ("674", "🇳🇷 ناورو"), ("675", "🇵🇬 بابوا غينيا الجديدة"), ("676", "🇹🇴 تونغا"),
    ("677", "🇸🇧 جزر سليمان"), ("678", "🇻🇺 فانواتو"), ("679", "🇫🇯 فيجي"),
    ("680", "🇵🇼 بالاو"), ("681", "🇼🇫 والس"), ("682", "🇨🇰 جزر كوك"),
    ("683", "🇳🇺 نيوي"), ("685", "🇼🇸 ساموا"), ("686", "🇰🇮 كيريباتي"),
    ("687", "🇳🇨 كاليدونيا الجديدة"), ("688", "🇹🇻 توفالو"),
    ("852", "🇭🇰 هونغ كونغ"), ("853", "🇲🇴 ماكاو"), ("855", "🇰🇭 كمبوديا"),
    ("856", "🇱🇦 لاوس"), ("880", "🇧🇩 بنغلاديش"), ("886", "🇹🇼 تايوان"),
    ("960", "🇲🇻 المالديف"), ("961", "🇱🇧 لبنان"), ("962", "🇯🇴 الأردن"),
    ("963", "🇸🇾 سوريا"), ("964", "🇮🇶 العراق"), ("965", "🇰🇼 الكويت"),
    ("966", "🇸🇦 السعودية"), ("967", "🇾🇪 اليمن"), ("968", "🇴🇲 عُمان"),
    ("970", "🇵🇸 فلسطين"), ("971", "🇦🇪 الإمارات"), ("972", "🇮🇱 إسرائيل"),
    ("973", "🇧🇭 البحرين"), ("974", "🇶🇦 قطر"), ("975", "🇧🇹 بوتان"),
    ("976", "🇲🇳 منغوليا"), ("977", "🇳🇵 نيبال"), ("992", "🇹🇯 طاجيكستان"),
    ("993", "🇹🇲 تركمانستان"), ("994", "🇦🇿 أذربيجان"), ("995", "🇬🇪 جورجيا"),
    ("996", "🇰🇬 قيرغيزستان"), ("998", "🇺🇿 أوزبكستان"),
    ("20", "🇪🇬 مصر"), ("27", "🇿🇦 جنوب أفريقيا"), ("30", "🇬🇷 اليونان"),
    ("31", "🇳🇱 هولندا"), ("32", "🇧🇪 بلجيكا"), ("33", "🇫🇷 فرنسا"),
    ("34", "🇪🇸 إسبانيا"), ("36", "🇭🇺 المجر"), ("39", "🇮🇹 إيطاليا"),
    ("40", "🇷🇴 رومانيا"), ("41", "🇨🇭 سويسرا"), ("43", "🇦🇹 النمسا"),
    ("44", "🇬🇧 بريطانيا"), ("45", "🇩🇰 الدنمارك"), ("46", "🇸🇪 السويد"),
    ("47", "🇳🇴 النرويج"), ("48", "??🇱 بولندا"), ("49", "🇩🇪 ألمانيا"),
    ("51", "🇵🇪 بيرو"), ("52", "🇲🇽 المكسيك"), ("53", "🇨🇺 كوبا"),
    ("54", "🇦🇷 الأرجنتين"), ("55", "🇧🇷 البرازيل"), ("56", "🇨🇱 تشيلي"),
    ("57", "🇨🇴 كولومبيا"), ("58", "🇻🇪 فنزويلا"), ("60", "🇲🇾 ماليزيا"),
    ("61", "🇦🇺 أستراليا"), ("62", "🇮🇩 إندونيسيا"), ("63", "🇵🇭 الفلبين"),
    ("64", "🇳🇿 نيوزيلندا"), ("65", "🇸🇬 سنغافورة"), ("66", "🇹🇭 تايلاند"),
    ("81", "🇯🇵 اليابان"), ("82", "🇰🇷 كوريا الجنوبية"),
    ("84", "🇻🇳 فيتنام"), ("86", "🇨🇳 الصين"), ("90", "🇹🇷 تركيا"),
    ("91", "🇮🇳 الهند"), ("92", "🇵🇰 باكستان"), ("93", "🇦🇫 أفغانستان"),
    ("94", "🇱🇰 سريلانكا"), ("95", "🇲🇲 ميانمار"), ("98", "🇮🇷 إيران"),
    ("1", "🇺🇸 أمريكا/كندا"), ("7", "🇷🇺 روسيا/كازاخستان"),
]

def detect_country(phone):
    if not phone:
        return None, None
    digits = phone.lstrip("+").strip()
    # ترتيب الدول حسب طول الكود تنازلياً لضمان دقة المطابقة
    sorted_countries = sorted(ALL_COUNTRIES, key=lambda x: len(x[0]), reverse=True)
    for code, name in sorted_countries:
        if digits.startswith(code):
            return code, name
    return None, None

def get_country_name(code):
    for c, name in ALL_COUNTRIES:
        if c == str(code):
            return name
    return f"دولة ({code})"

def get_user_lang(uid):
    u = db['users'].get(str(uid), {})
    lang = u.get('lang') or 'ar'
    return lang if lang in TRANSLATIONS else 'ar'

def ui_text(uid, arabic, english):
    """إرجاع النص حسب لغة المستخدم المختارة."""
    return english if get_user_lang(uid) == 'en' else arabic

def old_numbers_label(uid=None):
    return OLD_NUMBERS_LABEL_EN if uid is not None and get_user_lang(uid) == 'en' else OLD_NUMBERS_LABEL

def set_user_lang(uid, lang):
    if str(uid) in db['users']:
        db['users'][str(uid)]['lang'] = lang
        save_db(db)
        update_user_cache(uid)

def is_admin(uid):
    if int(uid) in ADMINS: return True
    return int(uid) in db['settings'].get('extra_admins', [])

def get_balance(uid):
    u = db['users'].get(str(uid))
    return float(u.get('balance', 0)) if u else 0.0

def update_balance(uid, amount):
    uid = str(uid)
    if uid not in db['users']:
        return
    db['users'][uid]['balance'] = round(db['users'][uid].get('balance', 0) + amount, 4)
    if amount > 0:
        db['users'][uid]['total_deposited'] = round(db['users'][uid].get('total_deposited', 0) + amount, 4)
    else:
        db['users'][uid]['total_spent'] = round(db['users'][uid].get('total_spent', 0) + (-amount), 4)
    _real_save_db(db) # الرصيد عملية حساسة، نحفظها فوراً
    update_user_cache(uid)

async def find_user(identifier):
    if not identifier: return None, None
    identifier = str(identifier).strip()
    clean_id = identifier.lstrip("@").lower()
    
    # 1. بحث بالـ ID الرقمي في قاعدة البيانات
    if identifier.isdigit():
        u = db['users'].get(identifier)
        if u:
            return identifier, u
        # إذا لم يُوجد بالـ ID مباشرة، ابحث في جميع المستخدمين عن تطابق جزئي
        # أو ابحث عن مستخدمين لديهم هذا الـ ID كجزء من بياناتهم
        for uid, u in db['users'].items():
            if uid == identifier:
                return uid, u
            
    # 2. بحث بالـ username باستخدام الفهرس السريع
    uid = _USERNAME_MAP.get(clean_id)
    if uid and uid in db['users']:
        return uid, db['users'][uid]
    
    # 3. بحث بالـ username في قاعدة البيانات مباشرة (بدون الفهرس)
    for uid, u in db['users'].items():
        uname = u.get('username')
        if uname and uname.lower().lstrip('@') == clean_id:
            return uid, u
            
    # 4. بحث بالـ bot_username
    for uid, u in db['users'].items():
        buname = u.get('bot_username')
        if buname and buname.lower() == clean_id:
            return uid, u
            
    # 5. بحث بالـ full_name في قاعدة البيانات (مطابقة تامة)
    for uid, u in db['users'].items():
        fname = (u.get('full_name') or '').lower().strip()
        if fname == clean_id:
            return uid, u
    
    # 6. بحث بالـ full_name (مطابقة جزئية - يحتوي على)
    if len(clean_id) >= 3:
        for uid, u in db['users'].items():
            fname = (u.get('full_name') or '').lower().strip()
            if clean_id in fname or fname in clean_id:
                return uid, u
            
    # 7. بحث مباشر في تيليجرام (إذا كان يوزر نيم أو آيدي)
    # نبحث فقط إذا كان يبدو كـ username (يبدأ بـ @) أو ID رقمي طويل (>= 7 أرقام)
    is_telegram_lookup = False
    if identifier.startswith('@') or (identifier.startswith('+') and len(identifier) > 7):
        is_telegram_lookup = True
    if identifier.isdigit() and len(identifier) >= 7:
        is_telegram_lookup = True
    
    if is_telegram_lookup:
        try:
            entity = await bot.get_entity(identifier)
            if entity:
                target_id = str(entity.id)
                # إذا وجده في تيليجرام، نتأكد من وجوده في قاعدة البيانات أو ننشئه
                u = ensure_user_by_id(target_id)
                # تحديث اليوزر نيم إذا تغير
                if hasattr(entity, 'username') and entity.username:
                    u['username'] = entity.username
                    save_db(db)
                return target_id, u
        except Exception:
            pass
            
    return None, None

def _normalize_txid(txid):
    """توحيد TXID لمنع إعادة استخدامه بسبب اختلاف الحروف أو المسافات."""
    return str(txid or '').strip().casefold()


def is_txid_used(txid, exclude_manual_id=None):
    txid_key = _normalize_txid(txid)
    if not txid_key:
        return False
    for used in db.get('used_txids', []):
        if _normalize_txid(used) == txid_key:
            return True
    for transaction in db.get('transactions', []):
        if (
            _normalize_txid(transaction.get('txid')) == txid_key
            and transaction.get('status') == 'completed'
        ):
            return True
    for request in db.get('manual_requests', []):
        if (exclude_manual_id is not None and request.get('id') == exclude_manual_id):
            continue
        if _normalize_txid(request.get('hashid')) == txid_key:
            return True
    return False


def mark_txid_used(txid):
    """تسجيل TXID بشكل دائم؛ لا نحذف السجل القديم حتى لا يُعاد استخدامه لاحقًا."""
    txid = str(txid or '').strip()
    if not txid:
        return
    if 'used_txids' not in db:
        db['used_txids'] = []
    if not any(_normalize_txid(existing) == _normalize_txid(txid) for existing in db['used_txids']):
        db['used_txids'].append(txid)
    save_db(db)

def generate_captcha_image(text, path):
    width, height = 240, 100
    image = Image.new('RGB', (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)
    for _ in range(150):
        x, y = random.randint(0, width), random.randint(0, height)
        draw.point((x, y), fill=(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)))
    for _ in range(8):
        x1, y1 = random.randint(0, width), random.randint(0, height)
        x2, y2 = random.randint(0, width), random.randint(0, height)
        draw.line((x1, y1, x2, y2), fill=(random.randint(0, 200), random.randint(0, 200), random.randint(0, 200)), width=2)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 45)
    except:
        font = ImageFont.load_default()
    for i, char in enumerate(text):
        draw.text((30 + i * 35, 25 + random.randint(-10, 10)), char, font=font, fill=(random.randint(0, 150), random.randint(0, 150), random.randint(0, 150)))
    image.save(path)

# ================================
#  دوال الأزرار والواجهات (كاملة)
# ================================
def kb_back():
    # هذا الزر يعيد المستخدم مباشرة إلى واجهة البوت الرئيسية.
    return [[Button.inline("🏠 القائمة الرئيسية", b"back_main")]]

def kb_cancel():
    return [[Button.inline("إلغاء", b"cancel_action")]]

def kb_admin_cancel():
    return [[Button.inline("إلغاء", b"a_cancel")]]

def kb_captcha(options=None):
    if not options:
        return [[Button.inline("تحقق", b"verify_captcha")]]
    rows = []
    row1 = [Button.inline(options[0], f"captcha_ans:{options[0]}".encode()), 
            Button.inline(options[1], f"captcha_ans:{options[1]}".encode())]
    row2 = [Button.inline(options[2], f"captcha_ans:{options[2]}".encode()), 
            Button.inline(options[3], f"captcha_ans:{options[3]}".encode())]
    rows.append(row1)
    rows.append(row2)
    return rows

def kb_force_sub(channels):
    rows = []
    for ch in channels:
        rows.append([Button.url(f"{ch['title']}", f"https://t.me/{ch['username']}")])
    rows.append([Button.inline("تحقق من الاشتراك", b"check_sub")])
    return rows

def kb_deposit_methods():
    return [
        [Button.inline("دفع فودافون كاش", b"pay_vodafone")],
        [Button.inline("🌟 شحن تلقائي عبر النجوم", b"pay:STARS")],
        [Button.inline("شحن تلقائي عبر Binance Pay", b"pay_binance")],
        [Button.inline("رجوع", b"back_main")],
    ]

def kb_binance_pay(uid=None):
    is_en = uid is not None and get_user_lang(uid) == 'en'
    return [
        [{'_copy_text': True, 'label': "📋 Copy Transfer ID" if is_en else "📋 نسخ رقم التحويل", 'copy_value': BINANCE_TRANSFER_ID}],
        [Button.inline("I Paid" if is_en else "تم الدفع", b"binance_paid")],
        [Button.inline("Back" if is_en else "رجوع", b"deposit")]
    ]

def kb_after_deposit_create(deposit_id):
    return [
        [Button.inline("إرسال TXID للتحقق", f"submit_tx:{deposit_id}".encode())],
        [Button.inline("إلغاء الطلب", f"cancel_deposit:{deposit_id}".encode())],
        [Button.inline("رجوع", b"deposit")],
    ]

def kb_countries(uid, countries_list, page=0, per_page=8, kind='clean'):
    total_pages = max(1, (len(countries_list) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    page_cs = countries_list[start:start + per_page]
    rows = []
    for c in page_cs:
        price_fmt = fmt_amt(c['price'], uid)
        display_name = (MONTHLY_NUMBERS_LABEL if kind == 'monthly' else (BIMONTHLY_NUMBERS_BUTTON_LABEL if kind == 'bimonthly' else (f"{c['name']} 📛" if kind == 'old_spam' and '📛' not in str(c['name']) else (c['name'] if kind in ('old', 'old_spam') else (old_numbers_label(uid) if c.get('code') == OLD_NUMBERS_CODE else c['name'])))))
        if kind in ('old', 'fake', 'unverified'):
            txt = f"{display_name}\n💰 {price_fmt}"
            rows.append([Button.inline(txt, f"buy_c:{kind}:{c['code']}".encode())])
        else:
            txt = f"{display_name} • {price_fmt}"
            button = Button.inline(txt, f"buy_c:{kind}:{c['code']}".encode())
            if rows and len(rows[-1]) < 2:
                rows[-1].append(button)
            else:
                rows.append([button])
    nav = []
    if page > 0:
        nav.append(Button.inline("السابق", f"cpage:{page-1}:{kind}".encode()))
    if total_pages > 1:
        nav.append(Button.inline(f"{page+1}/{total_pages}", b"noop"))
    if page + 1 < total_pages:
        nav.append(Button.inline("التالي", f"cpage:{page+1}:{kind}".encode()))
    if nav:
        rows.append(nav)
    rows.append([Button.inline("الرجوع", b"back_main")])
    return rows

def scam_channel_label(uid=None):
    override = db.get('button_overrides', {}).get('scam_channels', {}) or {}
    return override.get('text') or '🚨 قنوات احتالي'

def available_scam_channels():
    return [c for c in db.get('scam_channels', []) if c.get('status', 'available') == 'available']

def scam_channel_username(value):
    raw=str(value or '').strip()
    raw=re.sub(r'^https?://','',raw,flags=re.I)
    raw=re.sub(r'^t\.me/','',raw,flags=re.I).split('?',1)[0].strip('/')
    return raw.lstrip('@').strip()

def kb_scam_channels(uid):
    rows=[]
    for ch in available_scam_channels():
        username=scam_channel_username(ch.get('username'))
        rows.append([Button.inline(f'📢 @{username} • {fmt_amt(ch.get("price",0),uid)}', f'scam_buy:{ch.get("id")}'.encode())])
    rows.append([Button.inline('🔙 رجوع',b'back_main')])
    return rows

async def on_scam_channels_menu(event,user):
    if not available_scam_channels():
        return await safe_edit(event,'⚠️ لا توجد قنوات احتالي متاحة حالياً.',buttons=kb_back())
    text='🚨 *قنوات احتالي*\n━━━━━━━━━━━━━━━━━━━━\n\nاختر القناة التي تريد شراءها:'
    return await safe_edit(event,text,buttons=kb_scam_channels(user.id))

async def on_scam_channel_purchase(event,user,channel_id):
    async with get_user_purchase_lock(user.id):
        async with _PURCHASE_FLOW_LOCK:
            channel=next((c for c in available_scam_channels() if str(c.get('id'))==str(channel_id)),None)
            if not channel: return await safe_edit(event,'⚠️ هذه القناة تم بيعها أو لم تعد متاحة.',buttons=kb_back())
            price=float(channel.get('price',0) or 0)
            if price<=0: return await safe_edit(event,'⚠️ سعر القناة غير صالح، راجع الدعم.',buttons=kb_back())
            if get_balance(user.id)<price: return await check_purchase_balance_message(event,user.id,price)
            update_balance(user.id,-price)
            order_id=f'SCAM{random.randint(1000000,9999999)}'
            while any(str(x.get('order_id'))==order_id for x in db.get('scam_purchases',[])):
                order_id=f'SCAM{random.randint(1000000,9999999)}'
            now=datetime.now(); username=scam_channel_username(channel.get('username'))
            buyer_username=getattr(user,'username',None) or ''
            rec={'order_id':order_id,'channel_id':channel.get('id'),'channel_username':username,'user_id':user.id,'buyer_username':buyer_username,'price':price,'purchased_at':now.isoformat(),'status':'completed'}
            db.setdefault('scam_purchases',[]).append(rec)
            channel.update({'status':'sold','sold_to':user.id,'sold_at':now.isoformat()})
            save_db(db)
    # يظهر يوزر العميل كاملاً عند توفره، وإلا يظهر الـID مع إخفاء 3 أرقام.
    if buyer_username:
        buyer = f'@{buyer_username}'
    else:
        buyer_id = str(user.id)
        buyer = f'{buyer_id[:4]}xxx{buyer_id[-3:]}' if len(buyer_id) > 7 else buyer_id
    support=(f'🚨 *تم شراء قناة احتالي*\n\n'
             f'معرف الطلب: {order_id}\n\n'
             f'يوزر القناة: @{username}\n'
             f'يوزر الشاري: {buyer}\n\n'
             'حول هذه الرسالة للدعم الفني.\n'
             '@MOSCOW1081BOT')
    try:
        # رسالة الدعم تُرسل للأدمن فقط، ولا تُرسل إلى قناة التفعيلات.
        await bot.send_message(OWNER_ID, support)
    except Exception as e: logger.error(f'Failed to notify support for scam order {order_id}: {e}')
    # قناة التفعيلات تعرض ID العميل مخفياً دائماً، وليس اليوزر.
    customer_id = str(user.id)
    customer_display = f'{customer_id[:4]}xxx{customer_id[-3:]}' if len(customer_id) > 7 else customer_id
    activation=(f'✅ *تم شراء قناة احتالي بنجاح*\n\n✅ تم تفعيل الرقم بنجاح\n\n📱 المنصة: تليجرام\n📞 القناة: @{username}\n💰 السعر: ${price:.2f}\n👤 العميل: {customer_display}\n🔑 تم تسليم\n✅ الحالة: تم\n\n📅 التاريخ والوقت: {now.strftime("%Y-%m-%d %H:%M:%S")}')
    try:
        activation_buttons = [[Button.url('🛒 شراء أرقام', 'https://t.me/MOSCOWiqBOT?start=buy')]]
        # مسار الأزرار الملوّنة يثبت رابط start=buy باللون الأزرق.
        sent = await fast_send_with_colored_buttons(LOG_CHANNEL_ID, activation, activation_buttons)
        if not sent or not sent.get('ok'):
            await bot.send_message(LOG_CHANNEL_ID, activation, buttons=activation_buttons)
    except Exception as e: logger.error(f'Failed to notify activation channel for scam order {order_id}: {e}')
    support_buttons = [[Button.url('حول الرسالة للدعم الفني', 'https://t.me/MOSCOW1081BOT')]]
    return await safe_edit(event, support, buttons=support_buttons)

async def admin_scam_channels_menu(event):
    channels=db.get('scam_channels',[])
    text='🚨 *إدارة قنوات احتالي*\n━━━━━━━━━━━━━━━━━━━━\n\n'
    text += '\n'.join(f'`{c.get("id")}` @{scam_channel_username(c.get("username"))} — `${float(c.get("price",0)):.2f}` — {c.get("status","available")}' for c in channels) if channels else 'لا توجد قنوات مضافة.'
    return await safe_edit(event,text,buttons=[[Button.inline('➕ إضافة قنوات احتالي',b'asc:add')],[Button.inline('🔙 رجوع',b'a:panel')]])

def kb_purchase_type(kind, uid=None):
    if kind == 'sessions':
        clean_data, spam_data, spam_mix_data, old_data, old_spam_data, fake_data, unverified_data, monthly_data, daily_data, bimonthly_data = (b'buy_sessions_type:clean', b'buy_sessions_type:spam', b'buy_sessions_type:spam_mix', b'buy_sessions_type:old', b'buy_sessions_type:old_spam', b'buy_sessions_type:fake', b'buy_sessions_type:unverified', b'buy_sessions_type:monthly', b'buy_sessions_type:daily', b'buy_sessions_type:bimonthly')
    else:
        clean_data, spam_data, spam_mix_data, old_data, old_spam_data, fake_data, unverified_data, monthly_data, daily_data, bimonthly_data = (b'buy_type:clean', b'buy_type:spam', b'buy_type:spam_mix', b'buy_type:old', b'buy_type:old_spam', b'buy_type:fake', b'buy_type:unverified', b'buy_type:monthly', b'buy_type:daily', b'buy_type:bimonthly')
    available = [
        a for a in db.get('accounts', [])
        if a.get('status') == 'available' and a.get('session')
    ]
    categories = {account_purchase_category(a) for a in available}
    has_clean = 'clean' in categories
    has_spam = 'spam' in categories
    has_spam_mix = 'spam_mix' in categories
    has_old = 'old' in categories
    has_old_spam = 'old_spam' in categories
    has_fake = 'fake' in categories
    has_unverified = 'unverified' in categories
    has_monthly = kind != 'sessions' and 'monthly' in categories
    has_daily = kind != 'sessions' and 'daily' in categories
    has_bimonthly = kind != 'sessions' and 'bimonthly' in categories
    has_random = kind != 'sessions' and 'random' in categories

    rows = []
    if has_clean:
        rows.append([Button.inline(ui_text(uid, "✅ أرقام سليمة", "✅ Clean Numbers"), clean_data)])
    if has_spam:
        rows.append([Button.inline(ui_text(uid, "📛 أرقام سبام", "📛 Spam Numbers"), spam_data)])
    if has_spam_mix:
        rows.append([Button.inline(SPAM_MIX_LABEL, spam_mix_data)])
    if has_old:
        rows.append([Button.inline(ui_text(uid, "　　 أرقام قديمة　　 ", "　　 Old Numbers　　 "), old_data)])
    if has_old_spam:
        rows.append([Button.inline(ui_text(uid, f"{OLD_SPAM_LABEL} 📛", "Old Spam Numbers"), old_spam_data)])
    if available_scam_channels():
        rows.append([Button.inline(scam_channel_label(uid), b"scam_channels")])
    if has_fake:
        rows.append([Button.inline(ui_text(uid, "⚠️ مزيف واحتيالي — أرقام سليمة ✅", "⚠️ Fake & Fraudulent — Clean ✅"), fake_data)])
    if has_unverified:
        rows.append([Button.inline(ui_text(uid, "🃏 أرقام سبام مزيف", "🃏 Fake Spam Numbers"), unverified_data)])
    if has_monthly:
        rows.append([Button.inline(ui_text(uid, "🌟 أرقام مميزة شهر", "🌟 Monthly Special Numbers"), monthly_data)])
    if has_daily:
        rows.append([Button.inline(ui_text(uid, DAILY_NUMBERS_BUTTON_LABEL, '🌟 Special One-Day Numbers'), b"buy_type:daily")])
    if has_bimonthly:
        rows.append([Button.inline(ui_text(uid, BIMONTHLY_NUMBERS_BUTTON_LABEL, "🌟 Special Two-Month Numbers"), bimonthly_data)])
    if has_random:
        rows.append([Button.inline(ui_text(uid, RANDOM_NUMBERS_BUTTON_LABEL, "🌟 Random Special Numbers"), b"buy_type:random")])
    rows.append([Button.inline(ui_text(uid, "رجوع", "Back"), b"back_main")])
    return rows

def kb_confirm_buy(code, kind='clean'):
    return [
        [Button.inline("تأكيد الشراء", f"confirm_buy:{kind}:{code}".encode())],
        [Button.inline("رجوع", b"buy")],
    ]

def kb_session_countries(countries_list, uid=None, page=0, per_page=8, kind='clean'):
    total_pages = max(1, (len(countries_list) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    page_cs = countries_list[start:start + per_page]
    rows = []
    for c in page_cs:
        display_name = BIMONTHLY_NUMBERS_BUTTON_LABEL if kind == 'bimonthly' else (f"{c['name']} 📛" if kind == 'old_spam' and '📛' not in str(c['name']) else (c['name'] if kind in ('old', 'old_spam') else (old_numbers_label(uid) if c.get('code') == OLD_NUMBERS_CODE else c['name'])))
        if kind in ('old', 'fake', 'unverified'):
            txt = f"{display_name}\n💰 {c['price']}$"
            rows.append([Button.inline(txt, f"bs_c:{kind}:{c['code']}".encode())])
        else:
            txt = f"{display_name} • {c['price']}$"
            button = Button.inline(txt, f"bs_c:{kind}:{c['code']}".encode())
            if rows and len(rows[-1]) < 2:
                rows[-1].append(button)
            else:
                rows.append([button])
    nav = []
    if page > 0:
        nav.append(Button.inline("السابق", f"bspage:{page-1}:{kind}".encode()))
    if total_pages > 1:
        nav.append(Button.inline(f"{page+1}/{total_pages}", b"noop"))
    if page + 1 < total_pages:
        nav.append(Button.inline("التالي", f"bspage:{page+1}:{kind}".encode()))
    if nav:
        rows.append(nav)
    rows.append([Button.inline("الرجوع", b"back_main")])
    return rows

def kb_confirm_sessions(code, qty, kind='clean'):
    return [
        [Button.inline("تأكيد الشراء", f"execute_bs:{kind}:{code}:{qty}".encode())],
        [Button.inline("رجوع", b"buy_sessions")],
    ]

def kb_after_purchase(account_id):
    return [
        [Button.inline("جلب كود", f"req_code:{account_id}".encode())],
    ]

def kb_after_code(account_id):
    return [
        [Button.inline("جلب كود آخر", f"req_code:{account_id}".encode()), Button.inline("خروج البوت من الرقم", f"logout:{account_id}".encode())],
    ]

def kb_confirm_logout(account_id):
    return [
        [Button.inline("✅ تأكيد إزالة البوت", f"confirm_logout:{account_id}".encode())],
        [Button.inline("❌ إلغاء", f"cancel_logout:{account_id}".encode())],
    ]

def kb_manual_methods():
    methods = db.get('manual_payments', [])
    rows = []
    for m in methods:
        rows.append([Button.inline(f"{m['name']}", f"mp_show:{m['name']}".encode())])
    rows.append([Button.inline("رجوع", b"deposit")])
    return rows

def kb_manual_confirm(name):
    return [
        [Button.inline("أرسلت + رفع الإثبات", f"mp_send:{name}".encode())],
        [Button.inline("رجوع", b"manual_pay")],
    ]

def kb_admin_back():
    return [[Button.inline("رجوع للوحة", b"a:panel")]]

def kb_admin_countries():
    return [
        [Button.inline("عرض الدول المضافة", b"ac:list")],
        [Button.inline("تعديل سعر دولة", b"ac:edit"),
         Button.inline("تعديل اسم دولة", b"ac:edit_name")],
        [Button.inline("حذف دولة", b"ac:del")],
        [Button.inline("💰 السعر الافتراضي", b"ac:set_default_price"),
         Button.inline("📛 سعر أرقام السبام", b"ac:set_mixed_price"),
         Button.inline("🕰 سعر أرقام اسبام قديمة", b"ac:set_old_spam_price")],
        [Button.inline("رجوع", b"a:panel")],
    ]

def kb_admin_accounts():
    return [
        [Button.inline("اضافه رقم جديد (كود)", b"aa:add")],
        [Button.inline("إضافة ملف جلسة (Session)", b"aa:add_session")],
        [Button.inline("تغيير 2FA لجميع الأرقام", b"aa:bulk_2fa")],
        [Button.inline("رجوع", b"a:panel")],
    ]

def kb_admin_manual():
    return [
        [Button.inline("إضافة طريقة دفع", b"am:add")],
        [Button.inline("عرض الطرق", b"am:list")],
        [Button.inline("حذف طريقة", b"am:del")],
        [Button.inline("رجوع", b"a:panel")],
    ]

def kb_admin_wallets():
    rows = []
    for cur, addr in WALLETS.items():
        shown = (addr[:10] + "..." + addr[-6:]) if len(addr) > 25 else addr
        rows.append([Button.inline(f"{cur}: {shown}", f"aw:set:{cur}".encode())])
    rows.append([Button.inline("رجوع", b"a:panel")])
    return rows

def kb_lang_select():
    return [
        [Button.inline("🇸🇦 عربي", b"lang:ar")],
        [Button.inline("🇺🇸 English", b"lang:en")],
        [Button.inline("🇮🇷 فارسی", b"lang:fa")],
        [Button.inline("🇨🇳 中文", b"lang:zh")],
    ]

def kb_main(uid, balance=0):
    lang = get_user_lang(uid)
    t = TRANSLATIONS.get(lang, TRANSLATIONS['ar'])
    transfer_btn_text = t['transfer']
    sold_count = db['settings'].get('sold_numbers_count', 0)
    rows = [
        [Button.inline(t['buy'], b"buy"), Button.inline(t['buy_sessions'], b"buy_sessions")],
        [Button.inline(t['deposit'], b"deposit")],
        [Button.inline(transfer_btn_text, b"transfer_start"), Button.inline(t.get('change_currency', "تغيير العملة 💱"), b"change_currency")],
        [Button.inline(t.get('referral', "رابط دعوة"), b"referral_menu")],
        [
            Button.inline(t['change_lang'], b"change_lang"),
            Button.inline(t['rules'], b"rules")
        ],
        [
            Button.url(t['updates'], "https://t.me/MOSCOW100BOT"),
            Button.url(t['activations'], "https://t.me/MOSCOW8BOT")
        ],
        [Button.url(t['support'], f"https://t.me/{DEVELOPER_USER}")],
        [Button.inline(f"{t['sold_count']}{sold_count}", b"noop")]
    ]
    return rows

def kb_admin_main(uid):
    rows = [
        [Button.inline("إضافة رصيد", b"a:addbal"),
         Button.inline("خصم رصيد", b"a:subbal")],
        [Button.inline("حظر وفك حظر", b"a:ban")],
        [Button.inline("إذاعة", b"a:broadcast")],
        [Button.inline("إدارة الحسابات", b"a:accounts"),
         Button.inline("🌍 إدارة الدول", b"a:countries")],
        [Button.inline("📊 معرفة عدد الأرقام", b"a:count_accounts")],
        [Button.inline("🔗 رابط دعوة", b"a:referral_menu")],
        [Button.inline("🚨 قنوات احتالي", b"a:scam_channels")],
        [Button.inline("قنوات الاشتراك", b"a:channels"),
         Button.inline("الصيانة", b"a:maintenance")],
        [Button.inline("مسح نقاط الجميع", b"a:clear_points")],
        [Button.inline("نسخ احتياطي للملفات", b"a:backup"),
         Button.inline("استعادة البيانات", b"a:restore")],
        [Button.inline("استيراد جلسات (ZIP)", b"a:import_sessions")],
        [Button.inline("إغلاق", b"a:close")],
    ]
    return rows

# ================================
_rates_cache = {"data": None, "ts": 0}

async def get_crypto_rates():
    now = time.time()
    if _rates_cache["data"] and now - _rates_cache["ts"] < 300:
        return _rates_cache["data"]
    url = "https://api.coingecko.com/api/v3/simple/price?ids=litecoin,bitcoin,the-open-network,tether&vs_currencies=usd"
    try:
        loop = asyncio.get_event_loop()
        def _fetch():
            req = urllib.request.Request(url, headers={"User-Agent": "sliner-bot/2.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        data = await loop.run_in_executor(None, _fetch)
        rates = {
            "LTC":  float(data.get("litecoin", {}).get("usd", FALLBACK_RATES["LTC"])),
            "BTC":  float(data.get("bitcoin", {}).get("usd", FALLBACK_RATES["BTC"])),
            "TON":  float(data.get("the-open-network", {}).get("usd", FALLBACK_RATES["TON"])),
            "USDT": float(data.get("tether", {}).get("usd", FALLBACK_RATES["USDT"])),
        }
        _rates_cache["data"] = rates
        _rates_cache["ts"] = now
        return rates
    except Exception as e:
        logger.warning(f"فشل جلب الأسعار من CoinGecko: {e} — fallback")
        return FALLBACK_RATES.copy()

def usd_to_crypto(amount_usd, rate):
    return round(amount_usd / rate, 8)

async def _fetch_json(url, timeout=20, headers=None):
    loop = asyncio.get_event_loop()
    def _do():
        req = urllib.request.Request(url, headers=headers or {"User-Agent": "sliner-bot/2.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    return await loop.run_in_executor(None, _do)

async def verify_btc_tx(txid, expected_address):
    try:
        url = f"https://blockstream.info/api/tx/{txid}"
        data = await _fetch_json(url, timeout=20)
        if not data:
            return False, 0, "TXID غير موجود على شبكة Bitcoin"
        status = data.get("status", {})
        confirmed = status.get("confirmed", False)
        total = 0
        for vout in data.get("vout", []):
            addr = vout.get("scriptpubkey_address", "")
            if addr.lower() == expected_address.lower():
                total += vout.get("value", 0)
        if total == 0:
            return False, 0, "هذه المعاملة لا تتضمن تحويلاً إلى محفظتنا"
        btc = total / 1e8
        return True, btc, ("مؤكدة ✅" if confirmed else "في mempool ⏳")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, 0, "TXID غير موجود على شبكة Bitcoin"
        return False, 0, f"تعذّر الوصول لشبكة BTC (HTTP {e.code})"
    except Exception as e:
        return False, 0, f"خطأ شبكي: {e}"

async def verify_ltc_tx(txid, expected_address):
    try:
        url = f"https://sochain.com/api/v2/get_tx/LTC/{txid}"
        data = await _fetch_json(url, timeout=20)
        if data.get("status") == "success":
            tx_data = data.get("data", {})
            confirmations = tx_data.get("confirmations", 0)
            total = 0
            for out in tx_data.get("outputs", []):
                if out.get("address", "").lower() == expected_address.lower():
                    total += float(out.get("value", 0))
            if total > 0:
                status_msg = f"تأكيدات: {confirmations}" if confirmations else "في mempool"
                return True, total, status_msg
            return False, 0, "المعاملة لا تتضمن تحويلاً إلى محفظتنا"
    except Exception as e:
        logger.warning(f"SoChain failed: {e}")
    try:
        url = f"https://api.blockchair.com/litecoin/dashboards/transaction/{txid}"
        data = await _fetch_json(url, timeout=20)
        tx_obj = data.get("data", {}).get(txid)
        if not tx_obj:
            return False, 0, "TXID غير موجود على شبكة Litecoin"
        outputs = tx_obj.get("outputs", [])
        total_satoshi = 0
        for o in outputs:
            if o.get("recipient", "").lower() == expected_address.lower():
                total_satoshi += o.get("value", 0)
        if total_satoshi == 0:
            return False, 0, "المعاملة لا تتضمن تحويلاً إلى محفظتنا"
        ltc = total_satoshi / 1e8
        tx = tx_obj.get("transaction", {})
        confirmations = tx.get("block_id", -1)
        status_msg = "مؤكدة ✅" if confirmations and confirmations > 0 else "في mempool ⏳"
        return True, ltc, status_msg
    except Exception as e:
        return False, 0, f"خطأ شبكي: {e}"

async def verify_ton_tx(txid, expected_address):
    try:
        clean_tx = txid.strip()
        url = f"https://tonapi.io/v2/blockchain/transactions/{urllib.parse.quote(clean_tx)}"
        data = await _fetch_json(url, timeout=20)
        if not data or "error" in data:
            return False, 0, "TXID غير موجود على شبكة TON"
        total = 0
        in_msg = data.get("in_msg") or {}
        dest = (in_msg.get("destination") or {}).get("address", "")
        value = in_msg.get("value", 0)
        if expected_address and dest and _ton_addr_match(dest, expected_address):
            total += int(value or 0)
        for out in data.get("out_msgs", []) or []:
            dest = (out.get("destination") or {}).get("address", "")
            if expected_address and dest and _ton_addr_match(dest, expected_address):
                total += int(out.get("value", 0) or 0)
        if total == 0:
            return False, 0, "المعاملة لا تتضمن تحويلاً إلى محفظتنا"
        ton_amount = total / 1e9
        success = data.get("success", True)
        return True, ton_amount, "مؤكدة ✅" if success else "غير ناجحة ❌"
    except Exception as e:
        return False, 0, f"خطأ شبكي: {e}"

def _ton_addr_match(a, b):
    a = (a or "").lower().replace("-", "").replace("_", "")
    b = (b or "").lower().replace("-", "").replace("_", "")
    if a == b:
        return True
    if len(a) >= 40 and len(b) >= 40 and a[-40:] == b[-40:]:
        return True
    return False

USDT_BEP20_CONTRACT = "0x55d398326f99059fF775485246999027B3197955"

async def verify_usdt_bep20_tx(txid, expected_address):
    try:
        url = (f"https://api.bscscan.com/api?module=proxy&action=eth_getTransactionReceipt"
               f"&txhash={txid}")
        data = await _fetch_json(url, timeout=20)
        result = data.get("result")
        if not result:
            return False, 0, "TXID غير موجود على شبكة BSC"
        status = result.get("status", "0x0")
        if status != "0x1":
            return False, 0, "المعاملة فشلت على الشبكة"
        transfer_topic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
        total = 0
        for log in result.get("logs", []):
            if log.get("address", "").lower() != USDT_BEP20_CONTRACT.lower():
                continue
            topics = log.get("topics", [])
            if len(topics) < 3 or topics[0].lower() != transfer_topic.lower():
                continue
            to_addr = "0x" + topics[2][-40:].lower()
            if to_addr.lower() != expected_address.lower():
                continue
            amount_hex = log.get("data", "0x0")
            amount_wei = int(amount_hex, 16)
            total += amount_wei
        if total == 0:
            return False, 0, "المعاملة لا تتضمن تحويل USDT إلى محفظتنا"
        usdt = total / 1e18
        return True, usdt, "مؤكدة ✅"
    except Exception as e:
        return False, 0, f"خطأ شبكي: {e}"

async def verify_binance_pay_tx(txid, expected_usd=None):
    """تحقق خادمي من معاملة Binance Pay عبر سجل Pay Trade History.
    لا يضع أي رصيد إلا إذا طابق TXID والمبلغ وUSDT ومعرّف المستلم.
    """
    txid = str(txid or "").strip()
    if (not txid or not _binance_key_is_ready(BINANCE_API_KEY)
            or not _binance_key_is_ready(BINANCE_SECRET_KEY)):
        return False, 0.0, "إعدادات Binance API غير مكتملة على الخادم"
    try:
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - BINANCE_HISTORY_DAYS * 24 * 60 * 60 * 1000
        params = {
            "startTime": start_ms,
            "endTime": now_ms,
            "limit": 100,
            "recvWindow": 5000,
            "timestamp": now_ms,
        }
        query = urllib.parse.urlencode(params)
        signature = hmac.new(
            BINANCE_SECRET_KEY.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        url = f"{BINANCE_API_BASE.rstrip('/')}/sapi/v1/pay/transactions?{query}&signature={signature}"
        data = await _fetch_json(url, timeout=20, headers={
            "X-MBX-APIKEY": BINANCE_API_KEY,
            "User-Agent": "sliner-bot-binance-pay/1.0",
        })
        if not data.get("success") or not isinstance(data.get("data"), list):
            return False, 0.0, data.get("message", "تعذّر قراءة سجل Binance Pay")

        expected = None
        if expected_usd is not None:
            expected = Decimal(str(expected_usd)).quantize(Decimal("0.00000001"))
        for tx in data["data"]:
            # قد تعرض Binance أكثر من معرف للعملية؛ لا نفترض أن transactionId هو الوحيد.
            candidate_ids = {
                str(tx.get(field) or "").strip()
                for field in ("transactionId", "orderId", "txId", "id")
                if str(tx.get(field) or "").strip()
            }
            candidate_ids_normalized = {_normalize_txid(value) for value in candidate_ids}
            if _normalize_txid(txid) not in candidate_ids_normalized:
                continue
            if str(tx.get("orderType", "PAY")).upper() in {"PAY_REFUND", "PAYOUT", "REMITTANCE"}:
                return False, 0.0, "نوع المعاملة ليس إيداعًا صالحًا"
            # لا نعتمد أي معاملة غير مكتملة أو مرفوضة حتى لو ظهر لها TXID.
            status_raw = tx.get("status") or tx.get("transactionStatus") or tx.get("payStatus")
            if status_raw is not None:
                status = str(status_raw).strip().upper()
                if status not in {"SUCCESS", "SUCCEEDED", "COMPLETED", "CONFIRMED", "PAID", "1"}:
                    return False, 0.0, f"حالة المعاملة غير ناجحة: {status_raw}"
            currency = str(tx.get("currency") or "").upper()
            amount_raw = tx.get("amount")
            if currency != "USDT" and isinstance(tx.get("fundsDetail"), list):
                for fund in tx["fundsDetail"]:
                    if str(fund.get("currency", "")).upper() == "USDT":
                        currency = "USDT"
                        amount_raw = fund.get("amount")
                        break
            if currency != "USDT":
                return False, 0.0, "المعاملة ليست بعملة USDT"
            actual = Decimal(str(amount_raw or "0"))
            if actual <= 0:
                return False, 0.0, "المعاملة ليست دفعة واردة"
            receiver = tx.get("receiverInfo") or {}
            configured_receiver = str(BINANCE_TRANSFER_ID).strip()
            # في بعض أنواع التحويل تُرجع Binance accountId، وفي أنواع أخرى binanceId.
            # نقبل المطابقة إذا طابق أيٌّ منهما المعرّف الثابت، ولا نقبل غيابهما.
            receiver_ids = {
                str(receiver.get(field) or "").strip()
                for field in ("accountId", "binanceId")
                if str(receiver.get(field) or "").strip()
            }
            if not receiver_ids or configured_receiver not in receiver_ids:
                return False, 0.0, "تعذّر إثبات أن المعاملة وصلت إلى معرّف Binance المحدد"
            if expected is not None and abs(actual - expected) > Decimal("0.00000001"):
                return False, float(actual), f"المبلغ الفعلي {actual} USDT لا يطابق المبلغ المطلوب {expected} USDT"
            return True, float(actual), "تم التحقق من دفعة Binance Pay ✅"
        return False, 0.0, "لم يتم العثور على عملية صالحة. تأكد من TXID وحاول مرة أخرى."
    except urllib.error.HTTPError as e:
        # Binance يعيد عادةً JSON يحتوي code/message يوضح سبب 400.
        # نعرض التفاصيل الآمنة فقط، ولا نسجل API key أو Secret key.
        try:
            raw = e.read().decode("utf-8", errors="replace")
            error_data = json.loads(raw) if raw else {}
            code = error_data.get("code", "غير معروف")
            message = error_data.get("message") or error_data.get("msg") or "رفضت Binance الطلب"
            if e.code == 451:
                return False, 0.0, (
                    "خدمة Binance Pay غير متاحة من موقع استضافة البوت حاليًا "
                    "(HTTP 451 — Restricted Location). انقل البوت إلى استضافة "
                    "في منطقة تدعمها Binance رسميًا أو تواصل مع دعم Binance."
                )
            return False, 0.0, f"خطأ Binance Pay HTTP {e.code} — code={code}: {message}"
        except Exception:
            return False, 0.0, f"خطأ Binance Pay HTTP {e.code} — لم تُرسل Binance تفاصيل إضافية"
    except Exception as e:
        logger.exception("Binance Pay verification failed")
        return False, 0.0, "تعذّر الاتصال بـ Binance Pay"


async def verify_transaction(currency, txid, expected_address):
    currency = currency.upper()
    if currency == "BTC":
        return await verify_btc_tx(txid, expected_address)
    elif currency == "LTC":
        return await verify_ltc_tx(txid, expected_address)
    elif currency == "TON":
        return await verify_ton_tx(txid, expected_address)
    elif currency == "USDT":
        return await verify_usdt_bep20_tx(txid, expected_address)
    return False, 0, "عملة غير مدعومة"


async def check_subscription(user_id, channels=None):
    """التحقق من الاشتراك؛ يمكن تمرير لقطة قنوات خاصة بالإحالة لمنع الخصم الرجعي."""
    # لا ترسل طلبات Telegram قبل اكتمال اتصال البوت.
    if not bot.is_connected():
        return []
    if not db['settings'].get('force_sub_enabled', True):
        return []
    
    if channels is None:
        channels = db['settings'].get('force_channels', [])
    if not channels:
        return []

    async def check_single(ch):
        try:
            # قد ينقطع الاتصال أثناء تنفيذ دورة الفحص؛ لا ترسل طلبًا في هذه الحالة.
            if not bot.is_connected():
                return None
            # الفحص بواسطة ID القناة أسرع بكثير (مع محاولة اليوزر نيم كبديل)
            target = ch.get('id') or ch.get('username')
            if not target:
                return None
            
            participant = await bot(GetParticipantRequest(channel=target, participant=user_id))
            p = participant.participant
            
            if isinstance(p, (types.ChannelParticipantLeft, types.ChannelParticipantBanned)):
                return ch
            return None
        except UserNotParticipantError:
            return ch
        except Exception as e:
            # الخطأ الشبكي المؤقت لا يجب أن يوقف البوت أو يملأ السجل.
            logger.debug(f"فشل مؤقت في فحص قناة {ch.get('username')}: {e}")
            return None

    # تشغيل الفحص لكل القنوات في نفس اللحظة (Parallel)
    results = await asyncio.gather(*(check_single(ch) for ch in channels))
    
    # تصفية النتائج للحصول على القنوات التي لم يشترك فيها فقط
    not_subbed = [r for r in results if r is not None]
    return not_subbed

async def send_captcha(event, user_id):
    correct_code = "".join(random.choices(string.ascii_uppercase + string.digits, k=3))
    options = [correct_code]
    while len(options) < 4:
        wrong = "".join(random.choices(string.ascii_uppercase + string.digits, k=3))
        if wrong not in options:
            options.append(wrong)
    random.shuffle(options)
    db["captcha"][str(user_id)] = {"code": correct_code, "options": options}
    save_db(db)
    img_path = f"captcha_{user_id}.png"
    generate_captcha_image(correct_code, img_path)
    text = "⚠️ *التحقق من أنك لست روبوت* ⚠️\n━━━━━━━━━━━━━━━━━━━━\n\n🔐 يرجى اختيار الكلمة الصحيحة الموجودة في الصورة أدناه:\n\n✅ اضغط على الزر المطابق للكلمة لتجاوز التحقق\n\n🎯 اختر واحداً من الأزرار أدناه\n🛡️ الحماية مفعّلة لحماية حسابك"
    set_user_state(user_id, "awaiting_captcha_visual")
    try:
        # استخدام وظيفة Telethon الأصلية لإرسال الملف
        # هذا يضمن رفع الصورة بشكل صحيح كمرفق (multipart/form-data)
        await bot.send_file(
            user_id, 
            img_path, 
            caption=text, 
            parse_mode="md", 
            buttons=kb_captcha(options)
        )
        if os.path.exists(img_path): os.remove(img_path)
    except Exception as e:
        logger.error(f"Error sending visual captcha: {e}")
        if os.path.exists(img_path): os.remove(img_path)
        await bot.send_message(user_id, "فشل تحميل الصورة، يرجى المحاولة لاحقاً.")

# ============================================================
#  الدالة الأساسية التي تجمع الدول مع دمج السبام في المخطلت
# ============================================================
def account_purchase_category(account):
    """يعيد قسماً واحداً حصرياً لكل حساب حتى لا يظهر في أكثر من زر."""
    explicit = account.get('purchase_category')
    valid = {'clean', 'spam', 'spam_mix', 'fake', 'unverified', 'old', 'old_spam', 'monthly', 'daily', 'bimonthly', 'random'}
    if explicit in valid and explicit != 'clean':
        return explicit
    if account.get('is_old_spam', False):
        return 'old_spam'
    if account.get('is_bimonthly', False):
        return 'bimonthly'
    if account.get('is_daily_special', False):
        return 'daily'
    if account.get('is_random_special', False):
        return 'random'
    if account.get('is_monthly', False):
        return 'monthly'
    if account.get('is_unverified', False):
        return 'unverified'
    if account.get('is_fake', False):
        return 'fake'
    if account.get('is_old', False):
        return 'old'
    if account.get('is_spam_mix', False):
        return 'spam_mix'
    if account.get('is_spam', False):
        return 'spam'
    # أصلح السجلات القديمة التي تحفظ purchase_category=clean لكن اسمها
    # أو أعلامها يوضح أنها من قسم خاص؛ لا نعرضها ضمن زر السليم.
    country_data = db.get('countries', {}).get(account.get('country_code'), {})
    name = f"{account.get('country_name', '')} {country_data.get('name', '')}"
    if UNVERIFIED_LABEL in name or 'أرقام سبام مزيف' in name:
        return 'unverified'
    if FAKE_LABEL in name or 'مزيف و احتيالي' in name:
        return 'fake'
    if OLD_SPAM_LABEL in name:
        return 'old_spam'
    if BIMONTHLY_NUMBERS_LABEL in name:
        return 'bimonthly'
    if DAILY_NUMBERS_LABEL in name:
        return 'daily'
    if RANDOM_NUMBERS_LABEL in name:
        return 'random'
    if MONTHLY_NUMBERS_LABEL in name:
        return 'monthly'
    if 'مخطلت' in name or MIXED_LABEL in name or 'أرقام سبام' in name:
        return 'spam'
    if explicit == 'clean':
        return 'clean'
    return 'clean'


def set_account_purchase_category(account, category):
    """تثبيت الحساب في زر واحد ومسح كل أعلام التصنيف المتعارضة."""
    valid = {'clean', 'spam', 'spam_mix', 'fake', 'unverified', 'old', 'old_spam', 'monthly', 'daily', 'bimonthly', 'random'}
    category = category if category in valid else 'clean'
    account['purchase_category'] = category
    for field in ('is_spam', 'is_spam_mix', 'is_fake', 'is_unverified', 'is_old', 'is_old_spam', 'is_monthly', 'is_daily_special', 'is_bimonthly', 'is_random_special'):
        account[field] = False
    account['is_spam'] = category == 'spam'
    account['is_spam_mix'] = category == 'spam_mix'
    account['is_fake'] = category == 'fake'
    account['is_unverified'] = category == 'unverified'
    account['is_old'] = category == 'old'
    account['is_old_spam'] = category == 'old_spam'
    account['is_monthly'] = category == 'monthly'
    account['is_daily_special'] = category == 'daily'
    account['is_bimonthly'] = category == 'bimonthly'
    account['is_random_special'] = category == 'random'
    return account


def available_accounts_by_country():
    by_c = {}
    for a in db.get('accounts', []):
        if a.get('status') != 'available' or account_purchase_category(a) != 'clean':
            continue
        c = a.get('country_code')
        if c not in by_c:
            country_data = db['countries'].get(c, {})
            name = country_data.get('name', f"دولة ({c})")
            price = a.get('price', country_data.get('price', DEFAULT_ACCOUNT_PRICE))
            by_c[c] = {'code': c, 'name': name, 'price': price, 'count': 0, 'prices': []}
        by_c[c]['prices'].append(a.get('price', db['countries'].get(c, {}).get('price', DEFAULT_ACCOUNT_PRICE)))
        by_c[c]['count'] += 1
    for item in by_c.values():
        if item['prices']:
            item['price'] = min(item['prices'])
    return sorted(by_c.values(), key=lambda x: x['name'])

# ================================
#  نظام الإذاعة — إعلان القنوات حسب نوع الحسابات المضافة
#  أول ما يضغط المستخدم على زر "إذاعة" يظهر له إعلان مخصص:
#  إذا أضاف حسابات USA Spam يظهر (USA Spam accounts added — Most are old and active)
#  إذا أضاف في مزيف و احتيالي يظهر (⚠️ مزيف و احتيالي)، وهكذا حسب النوع المضاف
#  مع العدد الكلي وزر شراء @MOSCOWiqBOT
# ================================
SHOP_CHANNEL_URL = "https://t.me/MOSCOWiqBOT"
SHOP_CHANNEL_USERNAME = "@MOSCOWiqBOT"

def _get_accounts_by_type():
    """جمع الأرقام المتاحة حسب النوع: مزيف و احتيالي / مخطلت / USA Spam / دول أخرى."""
    result = {
        'fake': {'count': 0, 'codes': []},
        'mixed': {'count': 0, 'codes': []},
        'usa_spam': {'count': 0},
        'other': {'count': 0, 'codes': [], 'codes_by_name': {}},
    }
    for a in db.get('accounts', []):
        if a.get('status') != 'available':
            continue
        code = a.get('country_code', '')
        name = a.get('country_name', '')
        # مزيف و احتيالي
        if a.get('is_fake', False) or FAKE_LABEL in name or "مزيف و احتيالي" in name:
            result['fake']['count'] += 1
            if code not in result['fake']['codes']:
                result['fake']['codes'].append(code)
            continue
        # مخطلت (سبام)
        if a.get('is_spam', False) or "مخطلت" in name:
            result['mixed']['count'] += 1
            if code not in result['mixed']['codes']:
                result['mixed']['codes'].append(code)
            continue
        # أمريكا السبام: دولة باسم USA Spam أو رمز أمريكا
        if "USA Spam" in name or "usa spam" in name.lower() or code == '+1':
            result['usa_spam']['count'] += 1
            continue
        # باقي الدول
        result['other']['count'] += 1
        label = db['countries'].get(code, {}).get('name', name or f"دولة ({code})")
        result['other']['codes_by_name'].setdefault(label, 0)
        result['other']['codes_by_name'][label] += 1
        if code not in result['other']['codes']:
            result['other']['codes'].append(code)
    return result

# ================================
#  نظام إذاعة الإعلان في القناة — قالب موحد (عربي/إنجليزي) لكل نوع
#  الأنواع: USA Spam / مزيف و احتيالي / مخطلت / أرقام دول عادية
# ================================

def generate_broadcast_text(category_type: str, display_type: str, count: int) -> str:
    """
    توليد نص الإذاعة باللغتين العربية والإنجليزية بنفس القالب المطلوب:
    تم إضافة حسابات محادثات قديمة
    النوع: X
    X accounts added — Most are old and active
    Type: X
    - العدد الكلي : N
    - للشراء  @MOSCOWiqBOT
    """
    text = (
        f"📢 **تم إضافة حسابات محادثات قديمة**\n"
        f"**النوع:** {display_type}\n\n"
        f"**{category_type} accounts added — Most are old and active**\n"
        f"**Type:** {category_type}\n\n"
        f"- **العدد الكلي :** `{count}`\n"
        f"- **للشراء :** {SHOP_CHANNEL_USERNAME}"
    )
    return text


# بيانات أنواع الإعلانات: (مفتاح, نوع النص الإنجليزي, اسم العرض العربي)
BROADCAST_TYPES = {
    'usa':     ('USA Spam', 'USA Spam'),
    'fake':    ('Fake & Scam', '⚠️ مزيف و احتيالي'),
    'mixed':   ('Mixed', '📛 مخطلت'),
    'normal':  ('Normal', '🌍 أرقام عادية'),
}


def _get_accounts_by_type():
    """جمع الأرقام المتاحة حسب النوع: مزيف و احتيالي / مخطلت / USA Spam / دول أخرى."""
    result = {
        'fake': {'count': 0, 'codes': []},
        'mixed': {'count': 0, 'codes': []},
        'usa_spam': {'count': 0},
        'other': {'count': 0, 'codes': [], 'codes_by_name': {}},
    }
    for a in db.get('accounts', []):
        if a.get('status') != 'available':
            continue
        code = a.get('country_code', '')
        name = a.get('country_name', '')
        # مزيف و احتيالي
        if a.get('is_fake', False) or FAKE_LABEL in name or "مزيف و احتيالي" in name:
            result['fake']['count'] += 1
            if code not in result['fake']['codes']:
                result['fake']['codes'].append(code)
            continue
        # مخطلت (سبام)
        if a.get('is_spam', False) or "مخطلت" in name:
            result['mixed']['count'] += 1
            if code not in result['mixed']['codes']:
                result['mixed']['codes'].append(code)
            continue
        # أمريكا السبام: دولة باسم USA Spam أو رمز أمريكا
        if "USA Spam" in name or "usa spam" in name.lower() or code == '+1':
            result['usa_spam']['count'] += 1
            continue
        # باقي الدول
        result['other']['count'] += 1
        label = db['countries'].get(code, {}).get('name', name or f"دولة ({code})")
        result['other']['codes_by_name'].setdefault(label, 0)
        result['other']['codes_by_name'][label] += 1
        if code not in result['other']['codes']:
            result['other']['codes'].append(code)
    return result


def kb_broadcast_types(uid):
    """أزرار الإذاعة — زر منفصل لكل نوع حسابات متوفر."""
    acc_types = _get_accounts_by_type()
    rows = []
    if acc_types['usa_spam']['count'] > 0:
        rows.append([Button.inline(
            f"🇺🇸 USA Spam — {acc_types['usa_spam']['count']}", b"pub:broadcast:usa")])
    if acc_types['mixed']['count'] > 0:
        rows.append([Button.inline(
            f"أرقام سبام 📛 — {acc_types['mixed']['count']}", b"pub:broadcast:mixed")])
    if acc_types['other']['count'] > 0:
        rows.append([Button.inline(
            f"🌍 أرقام دول عادية — {acc_types['other']['count']}", b"pub:broadcast:normal")])
    if not rows:
        return None
    rows.append([Button.inline("🔙 رجوع", b"pub:broadcast:back")])
    return rows


# ربط أنواع الإذاعة بمفاتيح _get_accounts_by_type
BROADCAST_KEY_MAP = {
    'usa': 'usa_spam',
    'fake': 'fake',
    'mixed': 'mixed',
    'normal': 'other',
}


def build_broadcast_text_for_type(kind: str):
    """بناء نص إعلان الإذاعة لنوع محدد (usa/fake/mixed/normal). تعيد (text, count) أو None."""
    acc_types = _get_accounts_by_type()
    count = acc_types[BROADCAST_KEY_MAP[kind]]['count']
    if count == 0:
        return None
    en_type, ar_display = BROADCAST_TYPES[kind]
    text = generate_broadcast_text(en_type, ar_display, count)
    return text, count


async def send_broadcast_ad(event, uid, target=None):
    """عرض قائمة أزرار الإذاعة (زر منفصل لكل نوع حسابات متوفر)."""
    acc_types = _get_accounts_by_type()
    total = (acc_types['usa_spam']['count'] + acc_types['fake']['count']
             + acc_types['mixed']['count'] + acc_types['other']['count'])
    if total == 0:
        return await send_msg(event,
            "⚠️ لا توجد حسابات متاحة حالياً للإعلان عنها.\n"
            "سيظهر زر الإذاعة الإعلانات تلقائياً عند إضافة أرقام جديدة.",
            buttons=kb_main(uid))
    return await send_msg(event,
        "📢 **إذاعة للقنوات**\n\n"
        "اختر نوع الحسابات التي تريد إذاعتها عن الحسابات المتاحة:",
        buttons=kb_broadcast_types(uid))


async def publish_broadcast_for_type(event, uid, kind: str):
    """إذاعة آمنة: فشل مستخدم/قناة أو FloodWait لا يوقف البوت بالكامل."""
    try:
        result = build_broadcast_text_for_type(kind)
        if result is None:
            try:
                await event.answer("⚠️ لا توجد حسابات متاحة من هذا النوع حالياً.", alert=True)
            except Exception:
                pass
            return await send_msg(event,
                "⚠️ لا توجد حسابات متاحة من هذا النوع حالياً للإعلان عنها.",
                buttons=kb_main(uid))

        text, count = result
        _, ar_display = BROADCAST_TYPES[kind]
        buy_buttons = [[Button.url("🛒 شراء أرقام", SHOP_CHANNEL_URL)]]

        # عرض الإعلان للأدمن؛ فشل المعاينة لا يمنع محاولة النشر في القناة.
        try:
            await send_msg(event, text, buttons=buy_buttons)
        except FloodWaitError as e:
            logger.warning(f"FloodWait أثناء عرض معاينة الإذاعة: {e.seconds} ثانية")
        except Exception:
            logger.exception("فشل عرض معاينة الإذاعة")

        if not LOG_CHANNEL_ID:
            try:
                await event.answer("✅ تم إنشاء إعلان الإذاعة.", alert=False)
            except Exception:
                pass
            return

        try:
            await bot.send_message(LOG_CHANNEL_ID, text, buttons=buy_buttons)
            try:
                await event.answer(f"✅ تمت إذاعة {ar_display} في القناة بنجاح!", alert=False)
            except Exception:
                pass
        except FloodWaitError as e:
            wait_seconds = int(getattr(e, "seconds", 0) or 0)
            logger.warning(f"FloodWait أثناء نشر الإذاعة في القناة: {wait_seconds} ثانية")
            try:
                await event.answer(
                    f"⚠️ Telegram أوقف الإذاعة مؤقتًا لمدة {wait_seconds} ثانية. أعد المحاولة لاحقًا.",
                    alert=True,
                )
            except Exception:
                pass
        except RPCError as e:
            logger.error(f"فشل نشر الإذاعة في القناة بسبب Telegram RPC: {e}")
            try:
                await event.answer("⚠️ تعذر النشر في القناة. تحقق من صلاحيات البوت فيها.", alert=True)
            except Exception:
                pass
        except Exception:
            logger.exception("خطأ غير متوقع أثناء نشر الإذاعة في القناة")
            try:
                await event.answer("⚠️ حدث خطأ أثناء الإذاعة وتم تسجيله دون إيقاف البوت.", alert=True)
            except Exception:
                pass
    except Exception:
        # الحماية الأخيرة: لا تسمح لخطأ في زر الإذاعة بإنهاء معالج البوت.
        logger.exception("Broadcast handler crashed")
        try:
            await event.answer("⚠️ فشلت الإذاعة، لكن البوت ما زال يعمل.", alert=True)
        except Exception:
            pass


async def broadcast_back(event, uid):
    """زر رجوع من قائمة أنواع الإذاعة إلى القائمة الرئيسية."""
    await event.answer()
    user = db['users'].get(str(uid), {})
    return await show_main_menu(event, user)


# ================================
#  دوال معالجة الاختيار (سبام / عادي)
# ================================
async def handle_add_spam_choice(event, data):
    uid = event.sender_id
    if not is_admin(uid):
        await event.answer("غير مصرح.", alert=True)
        return
    choice = data.split(":")[1]  # spam أو normal أو fake أو unverified
    pending = db.get('pending_spam_choice', {})
    if not pending:
        await event.answer("لا توجد عملية معلقة.", alert=True)
        return
    if choice == 'custom':
        set_user_state(uid, 'a_awaiting_account_target')
        return await event.edit(
            "🧷 *اختر الزر الذي تريد إضافة الرقم/الجلسة إليه*\n\n"
            "اختر زرًا موجودًا، أو أنشئ زرًا جديدًا. ستبقى الأرقام ضمن الزر المختار فقط:",
            buttons=kb_category_targets())
    typ = pending.get('type')
    is_spam = (choice == 'spam')
    is_spam_mix = (choice == 'spam_mix')
    is_fake = (choice == 'fake')
    is_unverified = (choice == 'unverified')
    is_usa_clean = (choice == 'usa')
    is_old = (choice == 'old')
    is_old_spam = (choice == 'old_spam')
    is_monthly = (choice == 'monthly')
    is_daily_special = (choice == 'daily')
    is_bimonthly = (choice == 'bimonthly')
    is_random_special = (choice == 'random')
    purchase_category = {
        'spam': 'spam', 'spam_mix': 'spam_mix', 'fake': 'fake', 'unverified': 'unverified',
        'usa': 'clean', 'normal': 'clean', 'monthly': 'monthly', 'daily': 'daily', 'bimonthly': 'bimonthly', 'random': 'random',
        'old': 'old', 'old_spam': 'old_spam'
    }.get(choice, 'clean')

    if is_old or is_old_spam:
        pending['is_old'] = is_old
        pending['is_old_spam'] = is_old_spam
        pending['is_fake'] = False
        pending['is_unverified'] = False
        save_db(db)
        set_user_state(uid, 'a_awaiting_old_year', classification='old_spam' if is_old_spam else 'old')
        return await event.edit(
            "📅 *سنة إنشاء الحساب القديم*\n\n"
            "أرسل سنة إنشاء الحساب يدويًا، مثال: `2020`:",
            buttons=kb_admin_cancel())
    
    if typ == 'phone':
        if is_bimonthly:
            pending['is_bimonthly'] = True
            pending['is_monthly'] = False
            pending['is_spam'] = False
            pending['is_fake'] = False
            pending['is_old'] = False
            pending['code'] = BIMONTHLY_NUMBERS_CODE
            pending['name'] = BIMONTHLY_NUMBERS_LABEL
        elif is_monthly:
            pending['is_monthly'] = True
            pending['is_spam'] = False
            pending['is_fake'] = False
            pending['is_old'] = False
            pending['code'] = MONTHLY_NUMBERS_CODE
            pending['name'] = MONTHLY_NUMBERS_LABEL
        if is_usa_clean and pending.get('code') != '1':
            await event.answer('زر أمريكا السليم مخصص للأرقام الأمريكية التي تبدأ بـ +1 فقط.', alert=True)
            return
        if False and is_fake:
            # احتياطي قديم غير مستخدم؛ المزيف يمر الآن مباشرة إلى إدخال السعر.
            phone = pending['phone']
            code = pending['code']
            name = pending['name']
            
            if is_fake:
                price = FAKE_PRICE
                name = FAKE_LABEL
                code = 'fake'
            elif is_old:
                price = OLD_NUMBERS_PRICE
                name = old_numbers_label(uid)
                code = OLD_NUMBERS_CODE
            elif is_usa_clean:
                price = USA_CLEAN_PRICE
                name = USA_CLEAN_LABEL
                code = USA_CLEAN_CODE
            else:
                price = MIXED_PRICE
            
            success, msg = await start_admin_login(phone)
            if success:
                db['pending_spam_choice'] = {}
                save_db(db)
                set_user_state(uid, 'awaiting_admin_code',
                               phone=phone, code=code, name=name, price=price, 
                               is_spam=is_spam, is_spam_mix=is_spam_mix, is_fake=is_fake, is_unverified=is_unverified, is_usa_clean=is_usa_clean, is_old=is_old)
                
                label_text = UNVERIFIED_LABEL if is_unverified else FAKE_LABEL if is_fake else old_numbers_label(uid) if is_old else USA_CLEAN_LABEL if is_usa_clean else '📛 مخطلت'
                price_line = f"💰 السعر الثابت: `{price}$`\n\n"
                await event.edit(
                    f"📱 الرقم: `{phone}` ({label_text})\n"
                    f"🌍 الدولة: {name}\n"
                    f"{price_line}"
                    "📩 تم إرسال كود التفعيل.\n"
                    "الرجاء إدخال الكود المستلم:"
                )
            else:
                await event.edit(f"فشل طلب الكود: {msg}")
                db['pending_spam_choice'] = {}
                save_db(db)
        else:
            # سليم، نطلب السعر
            pending['is_spam'] = is_spam
            pending['is_spam_mix'] = is_spam_mix
            pending['is_fake'] = is_fake
            pending['is_unverified'] = is_unverified
            pending['is_old_spam'] = is_old_spam
            pending['is_old'] = False
            pending['is_monthly'] = is_monthly
            pending['is_daily_special'] = is_daily_special
            pending['is_bimonthly'] = is_bimonthly
            pending['is_random_special'] = is_random_special
            pending['is_usa_clean'] = is_usa_clean
            pending['purchase_category'] = purchase_category
            db['pending_spam_choice'] = pending
            save_db(db)
            set_user_state(uid, 'a_awaiting_account_price')
            await event.edit(
                f"💰 *تحديد السعر*\n\n"
                f"📱 الرقم: `+{pending['phone']}` ({UNVERIFIED_LABEL if is_unverified else ('مزيف واحتيالي ⚠️' if is_fake else ('سبام 📛' if is_spam else 'سليم ✅'))})\n"
                f"🌍 الدولة: {pending['name']}\n\n"
                f"⚡ أرسل السعر الذي تريده لهذا الرقم (مثال: `1.20`):",
                buttons=kb_admin_cancel()
            )
    elif typ == 'session_file':
        if False and is_fake:
            # احتياطي قديم غير مستخدم؛ المزيف يمر الآن مباشرة إلى إدخال السعر.
            file_path = pending['file_path']
            file_name = pending['file_name']
            
            if is_fake:
                price = FAKE_PRICE
            elif is_old:
                price = OLD_NUMBERS_PRICE
            elif is_usa_clean:
                price = USA_CLEAN_PRICE
            else:
                price = MIXED_PRICE
                
            await event.edit(f"⏳ جاري معالجة ملف ({FAKE_LABEL if is_fake else (old_numbers_label(uid) if is_old else (USA_CLEAN_LABEL if is_usa_clean else '📛 مخطلت'))})...")
            try:
                result = await process_session_file(file_path, file_name, is_spam, uid, custom_price=price, is_fake=is_fake, is_usa_clean=is_usa_clean, is_old=is_old)
                await event.edit(result, buttons=kb_admin_accounts())
            except Exception as e:
                await event.edit(f"فشل معالجة الملف: {e}", buttons=kb_admin_accounts())
            finally:
                if os.path.exists(file_path): os.remove(file_path)
                db['pending_spam_choice'] = {}
                save_db(db)
        else:
            # سليم، نطلب السعر
            pending['is_spam'] = is_spam
            pending['is_spam_mix'] = is_spam_mix
            pending['is_fake'] = is_fake
            pending['is_unverified'] = is_unverified
            pending['is_old_spam'] = is_old_spam
            pending['is_old'] = False
            pending['is_monthly'] = is_monthly
            pending['is_daily_special'] = is_daily_special
            pending['is_bimonthly'] = is_bimonthly
            pending['is_random_special'] = is_random_special
            pending['is_usa_clean'] = is_usa_clean
            pending['purchase_category'] = purchase_category
            db['pending_spam_choice'] = pending
            save_db(db)
            set_user_state(uid, 'a_awaiting_account_price')
            await event.edit(
                f"💰 *تحديد السعر*\n\n"
                f"📂 الملف: `{pending['file_name']}` ({'مزيف واحتيالي ⚠️' if is_fake else ('سبام 📛' if is_spam else 'سليم ✅')})\n\n"
                f"⚡ أرسل السعر الذي تريده لهذه الجلسة (مثال: `1.20`):",
                buttons=kb_admin_cancel()
            )
    else:
        await event.answer("نوع غير معروف.", alert=True)
        db['pending_spam_choice'] = {}
        save_db(db)

async def kick_other_sessions(session_str):
    """
    محاولة إنهاء الجلسات الأخرى للحساب ليبقى البوت هو الجلسة الوحيدة.
    بعض الجلسات الجديدة جداً لا يسمح تيليجرام لها بتنفيذ ResetAuthorizations فوراً،
    لذلك نتعامل مع الحالة كتحذير فقط بدل تسجيلها كخطأ يربك التشغيل.
    """
    client = None
    try:
        if not RESET_OTHER_SESSIONS:
            logger.info("ℹ️ تم تخطي ResetAuthorizationsRequest لأن RESET_OTHER_SESSIONS غير مفعّل.")
            return True
        client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
        await client.connect()
        if await client.is_user_authorized():
            try:
                await client(functions.auth.ResetAuthorizationsRequest())
                logger.info("✅ تم إنهاء جميع الجلسات الأخرى بنجاح.")
            except RPCError as e:
                msg = str(e).lower()
                if "too new" in msg or "reset other authorisations yet" in msg or "reset other authorizations yet" in msg:
                    logger.warning("⚠️ تم تخطي ResetAuthorizations لأن الجلسة جديدة جداً. سيُعاد المحاولة لاحقاً بدون إزعاج التشغيل.")
                    return False
                raise
        return True
    except Exception as e:
        logger.error(f"❌ خطأ أثناء إنهاء الجلسات الأخرى: {e}")
        return False
    finally:
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass

def extract_creation_year(metadata):
    """استخراج سنة إنشاء الحساب من حقول بيانات الجلسة إن كانت مرفقة."""
    if not isinstance(metadata, dict):
        return None
    for key in ('creation_year', 'created_year', 'registration_year', 'account_year', 'created_at', 'date_created'):
        value = metadata.get(key)
        match = re.search(r'\b(20\d{2})\b', str(value or ''))
        if match:
            year = int(match.group(1))
            if 2010 <= year <= datetime.now().year:
                return year
    return None

async def process_session_file(file_path, file_name, is_spam, admin_uid, custom_price=None, is_fake=False, is_spam_mix=False, is_unverified=False, is_usa_clean=False, is_old=False, is_old_spam=False, old_year=None, custom_label=None, custom_country_code=None, is_monthly=False, is_daily_special=False, is_bimonthly=False, is_random_special=False):
    session_str = None
    password = None
    phone = None
    metadata = {}
    file_ext = os.path.splitext(os.path.basename(file_name))[1].lower()
    if file_ext == '.json':
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                metadata = data
                session_str = data.get('session_str')
                password = data.get('twoFA') or data.get('2fa') or data.get('2FA') or data.get('password')
                raw_phone = data.get('phone', '')
                if raw_phone:
                    raw_phone = str(raw_phone).strip()
                    if not raw_phone.startswith('+'):
                        raw_phone = '+' + raw_phone
                    phone = '+' + ''.join(filter(str.isdigit, raw_phone))
        except Exception as e:
            return f"❌ فشل قراءة ملف JSON: {e}"
        if not phone or len(phone) < 7:
            base_name = file_name.rsplit('.', 1)[0]
            phone = '+' + ''.join(filter(str.isdigit, base_name))
    else:  # .session
        try:
            client = TelegramClient(file_path, API_ID, API_HASH)
            await client.connect()
            if not await client.is_user_authorized():
                await client.disconnect()
                return "⚠️ الجلسة غير صالحة أو منتهية الصلاحية."
            # SQLiteSession.save() لا يعيد StringSession؛ يجب تحويلها صراحةً
            # حتى يمكن تخزينها في قاعدة البيانات واستخدامها لاحقاً.
            session_str = StringSession.save(client.session)
            me = await client.get_me()
            if me and me.phone:
                phone = me.phone
            await client.disconnect()
        except Exception as e:
            return f"❌ فشل تحميل الجلسة: {e}"
        base_name = file_name.rsplit('.', 1)[0]
        if not phone:
            phone = '+' + ''.join(filter(str.isdigit, base_name))
    if not session_str:
        return "⚠️ لم يتم العثور على session_str في الملف."
    # ملفات JSON قد تحتوي على مسافات أو أسطر زائدة؛ تمريرها كما هي قد ينتج
    # جلسة مختلفة/غير قابلة للقراءة رغم أن الملف الأصلي صالح.
    if isinstance(session_str, str):
        session_str = session_str.strip()
    if not phone or len(phone) < 7:
        return f"⚠️ لم أتمكن من استخراج رقم هاتف صالح من الملف `{file_name}`."
    purchase_category = (
        'old_spam' if is_old_spam else
        'old' if is_old else
        'fake' if is_fake else
        'unverified' if is_unverified else
        'random' if is_random_special else
        'bimonthly' if is_bimonthly else
        'monthly' if is_monthly else
        'spam_mix' if is_spam_mix else
        'spam' if is_spam else
        'clean'
    )
    if (is_spam or is_spam_mix) and not is_old and not is_fake and not is_usa_clean:
        detected_code, detected_name = detect_country(phone)
        if not detected_code:
            return f"⚠️ لم أتمكن من تحديد دولة الرقم السبام `{phone}`."
        code = f"{SPAM_MIX_CODE}_{detected_code}" if is_spam_mix else f"spam_{detected_code}"
        label = f"{detected_name} {SPAM_MIX_LABEL}" if is_spam_mix else f"{detected_name} 📛"
    elif is_old_spam:
        detected_code, detected_name = detect_country(phone)
        if not detected_code:
            return f"⚠️ لم أتمكن من تحديد دولة الرقم الاسبام القديم `{phone}`."
        code = f"{OLD_SPAM_CODE}_{detected_code}"
        label = f"{detected_name} 📛"
    elif is_old:
        detected_code, detected_name = detect_country(phone)
        if not detected_code:
            return f"⚠️ لم أتمكن من تحديد دولة الرقم القديم `{phone}`."
        creation_year = old_year or extract_creation_year(metadata)
        label = f"{detected_name} {creation_year}" if creation_year else f"{detected_name} قديم"
        code = f"old_{detected_code}_{creation_year or 'unknown'}"
    elif is_fake:
        code, label = 'fake', FAKE_LABEL
    elif is_unverified:
        code, label = UNVERIFIED_CODE, UNVERIFIED_LABEL
    elif is_monthly:
        code, label = MONTHLY_NUMBERS_CODE, MONTHLY_NUMBERS_LABEL
    elif is_bimonthly:
        code, label = BIMONTHLY_NUMBERS_CODE, BIMONTHLY_NUMBERS_LABEL
    elif is_usa_clean:
        if not phone.lstrip('+').startswith('1'):
            return f"⚠️ زر أمريكا السليم مخصص للأرقام التي تبدأ بـ +1 فقط. الملف: `{file_name}`"
        code, label = USA_CLEAN_CODE, USA_CLEAN_LABEL
    elif custom_label:
        code = str(custom_country_code or ('custom_' + hashlib.sha1(custom_label.encode('utf-8')).hexdigest()[:12]))
        label = str(custom_label)
    else:
        code, label = detect_country(phone)
        
    if not code:
        return f"⚠️ لم أتعرف على دولة الرقم `{phone}`."
        
    if custom_label:
        db['countries'][code] = {
            'name': label,
            'price': custom_price if custom_price is not None else DEFAULT_ACCOUNT_PRICE
        }
    elif is_monthly or is_bimonthly:
        default_price = MONTHLY_NUMBERS_PRICE if is_monthly else BIMONTHLY_NUMBERS_PRICE
        db['countries'][code] = {
            'name': label,
            'price': custom_price if custom_price is not None else default_price
        }
    elif code not in db['countries']:
        # إضافة الدولة تلقائياً إذا لم تكن موجودة
        db['countries'][code] = {
            'name': label,
            'price': custom_price if custom_price is not None else DEFAULT_ACCOUNT_PRICE
        }
        save_db(db)
    elif is_old_spam and custom_price is not None:
        db['countries'][code]['price'] = custom_price

    if custom_label:
        selected_price = custom_price if custom_price is not None else db['countries'][code]['price']
        existing = [a for a in db.get('accounts', []) if a.get('phone') == phone]
        if existing:
            for old_account in existing:
                set_account_purchase_category(old_account, 'clean')
                old_account['country_code'] = code
                old_account['country_name'] = label
                old_account['price'] = selected_price
                old_account['session'] = session_str
                old_account['password'] = password
                old_account['is_usa_clean'] = False
            save_session_to_disk(phone, session_str)
            save_db(db)
            return (f"✅ تم نقل الرقم الموجود إلى الزر المحدد.\n\n"
                    f"📱 الرقم: `{phone}`\n🏷️ الزر: {label}\n💰 السعر: `{selected_price}$`")
        
    acc_id = _next('next_account_id')
    db['accounts'].append({
        'id': acc_id,
        'phone': phone,
        'session': session_str,
        'country_code': code,
        'country_name': label if is_fake or is_unverified or is_old or is_old_spam else db['countries'][code]['name'],
        'price': custom_price if custom_price is not None else db['countries'][code]['price'],
        'status': 'available',
        'password': password,
        'added_at': datetime.now().isoformat(),
        'is_spam': is_spam,
        'is_spam_mix': is_spam_mix,
        'is_fake': is_fake,
        'is_unverified': is_unverified,
        'is_usa_clean': is_usa_clean,
        'is_old': is_old,
        'is_old_spam': is_old_spam,
        'is_monthly': is_monthly,
        'is_bimonthly': is_bimonthly,
        'purchase_category': purchase_category,
    })
    save_session_to_disk(phone, session_str)
    save_db(db)
    
    # لا تُلغِ الجلسات الأخرى افتراضياً؛ هذا الخيار قد يبطل جلسة البيع.
    if RESET_OTHER_SESSIONS:
        asyncio.create_task(kick_other_sessions(session_str))
    
    if is_old:
        type_text = old_numbers_label(admin_uid)
    elif is_fake:
        type_text = FAKE_LABEL
    else:
        type_text = " **سبام (EMOJI5895576786879647172)**" if is_spam else " عادي"
        
    final_price = custom_price if custom_price is not None else db['countries'][code]['price']
    return (f"🔐 *تمت إضافة الجلسة بنجاح!* 🔐\n\n"
            f"📱 الرقم: `{phone}`\n"
            f"🌍 الدولة: {label if is_fake else db['countries'][code]['name']}\n"
            f"💰 السعر: `{final_price}$`\n"
            f"(EMOJI5307843983102204243) كلمة المرور (2FA): `{password or 'لا يوجد'}`\n"
            f"🏷️ التصنيف: {type_text}")

# ================================
#  دوال أخرى مساعدة
# ================================
async def safe_edit(event, text, buttons=None, parse_mode='md', **kwargs):
    """تعديل آمن للرسائل مع إجابة فورية للأزرار ومسارات احتياطية."""
    # يجب إنهاء حالة التحميل في زر CallbackQuery بأسرع وقت ممكن.
    if hasattr(event, 'answer'):
        try:
            await event.answer()
        except Exception:
            pass

    chat_id = getattr(event, 'chat_id', None)
    if chat_id is None:
        message = getattr(event, 'message', None)
        chat_id = getattr(message, 'chat_id', None)
    msg_id = _event_message_id(event)

    cli = getattr(event, 'client', None) or bot
    plain, entities = _merge_entities_with_custom_emojis(cli, text, parse_mode)
    bot_entities = _telethon_entities_to_bot_api(entities)

    # المسار السريع يحافظ على الأزرار الملونة والـ custom emojis.
    if chat_id is not None and msg_id is not None:
        try:
            response = await fast_edit_with_colored_buttons(
                chat_id,
                msg_id,
                plain,
                buttons,
                parse_mode='Markdown',
                entities=bot_entities,
                **kwargs
            )
            if response and response.get('ok'):
                return response
        except MessageNotModifiedError:
            return None
        except Exception as exc:
            logger.debug(f"Fast message edit failed: {exc}")

    # المسار التقليدي عبر Telethon عند تعذر استدعاء Bot API.
    if hasattr(event, 'edit'):
        try:
            return await event.edit(
                plain,
                buttons=buttons,
                formatting_entities=entities if entities else None,
                **kwargs
            )
        except MessageNotModifiedError:
            return None
        except Exception as exc:
            logger.debug(f"Telethon message edit failed: {exc}")

    # إذا لم تعد الرسالة قابلة للتعديل، أرسل رسالة بديلة بدلاً من إسقاط الحدث.
    try:
        return await send_msg(event, text, buttons=buttons, parse_mode=parse_mode, **kwargs)
    except Exception as exc:
        logger.error(f"safe_edit fallback failed: {exc}")
        return None


@bot.on(events.CallbackQuery)
async def global_callback_answer(event):
    """إجابة عامة وفورية لمنع بقاء مؤشر تحميل الزر."""
    try:
        await event.answer()
    except Exception:
        pass

def fmt_welcome(template, user, balance):
    full_name = ((getattr(user, 'first_name', '') or '') + ' ' +
                 (getattr(user, 'last_name', '') or '')).strip() or "عزيزي"
    username = user.username or "لا يوجد"
    bal_str = f"{balance:.2f}".rstrip('0').rstrip('.') or "0"
    
    if not template:
        template = db['settings'].get('welcome_text')
    if not template:
        lang = get_user_lang(user.id)
        template = TRANSLATIONS.get(lang, TRANSLATIONS['ar'])['welcome']

    try:
        return template.format(id=user.id, name=full_name, username=username, balance=bal_str)
    except:
        t = template.replace("{user}", full_name).replace("{name}", full_name)
        t = t.replace("{username}", username).replace("{id}", str(user.id)).replace("{balance}", bal_str)
        return t

async def show_main_menu(event, user):
    uid = str(user.id)
    udata = ensure_user_by_id(uid)
    balance = udata.get('balance', 0.0)
    if not udata.get('verified') and not is_admin(user.id):
        return await send_captcha(event, user)
    if False: # تم إلغاء نظام التسجيل بناءً على طلب المستخدم
        pass
    else:
        lang = get_user_lang(user.id)
        menu_templates = {
            'ar': "🏠 - القائمة الرئيسية.\n\n🆔 - ايديك: `{uid}`\n💵 - رصيدك: `{balance}`\n\n🔽 - تحكم عن طريق الأزرار بالأسفل.",
            'en': "🏠 - Main Menu\n\n🆔 - ID: `{uid}`\n💵 - Balance: `{balance}`\n\n🔽 - Use the buttons below.",
            'fa': "🏠 - منوی اصلی\n\n🆔 - شناسه: `{uid}`\n💵 - موجودی: `{balance}`\n\n🔽 - از دکمه‌های زیر استفاده کنید.",
            'zh': "🏠 - 主菜单\n\n🆔 - 用户ID：`{uid}`\n💵 - 余额：`{balance}`\n\n🔽 - 请使用下面的按钮。",
        }
        text = menu_templates.get(lang, menu_templates['ar']).format(
            uid=user.id, balance=fmt_amt(balance, user.id)
        )
        buttons = kb_main(user.id, balance)
    chat_id = getattr(event, 'chat_id', None)
    msg_id = _event_message_id(event)
    is_new = hasattr(event, 'message') and not hasattr(event, 'data')
    
    # Apply custom emoji entities
    cli = getattr(event, 'client', None) or bot
    plain, entities = _merge_entities_with_custom_emojis(cli, text, 'md')
    bot_entities = _telethon_entities_to_bot_api(entities)
    
    if hasattr(event, 'edit') and msg_id and not is_new:
        await fast_edit_with_colored_buttons(chat_id, msg_id, plain, buttons, entities=bot_entities)
    else:
        await fast_send_with_colored_buttons(chat_id, plain, buttons, entities=bot_entities)

# ================================
#  نظام رابط الدعوة / الإحالة
# ================================
def referral_reward():
    # مكافأة جميع روابط الإحالة ثابتة دائمًا: 0.006$
    return 0.006

def referral_is_enabled():
    return bool(db.get('settings', {}).get('referral_enabled', True))

def _ensure_referral_user_fields(uid):
    u = ensure_user_by_id(uid)
    u.setdefault('referral_points', 0.0)
    return u

def _apply_referral_balance(uid, amount):
    """إضافة/خصم مكافأة الإحالة من الرصيد الحالي دون استبداله."""
    uid = str(uid)
    if uid not in db.get('users', {}):
        return False
    current = float(db['users'][uid].get('balance', 0.0) or 0.0)
    # الرصيد الجديد = الرصيد السابق + قيمة العملية؛ لا يتم تصفيره أو استبداله.
    db['users'][uid]['balance'] = round(current + float(amount), 4)
    _real_save_db(db)
    update_user_cache(uid)
    return True

async def _register_referral_from_start(new_uid, start_param):
    """تسجيل إحالة بعد اجتياز التحقق، مع حماية قوية من الرشق."""
    if not referral_is_enabled() or not start_param or not start_param.startswith('ref_'):
        return False
    referrer_raw = start_param[4:].strip()
    if not referrer_raw.isdigit():
        return False
    referrer_id = int(referrer_raw)
    new_uid = int(new_uid)
    if referrer_id == new_uid or str(referrer_id) not in db.get('users', {}):
        return False

    user = db.get('users', {}).get(str(new_uid), {})
    # لا تُحتسب الإحالة إلا لحساب لديه Username واجتاز CAPTCHA.
    if not user.get('username') or not user.get('verified'):
        return False

    referrals = db.setdefault('referrals', {})
    key = str(new_uid)
    # كل مستخدم مُحال يُكافأ مرة واحدة فقط؛ لا نضيف 0.006 عند تكرار /start.
    if key in referrals:
        return False

    # حد للرشق: 20 إحالة موثقة كحد أقصى لكل داعٍ خلال آخر ساعة.
    now_dt = datetime.now()
    cutoff = now_dt.timestamp() - 3600
    recent = 0
    for rec in referrals.values():
        if str(rec.get('referrer_id')) != str(referrer_id):
            continue
        try:
            created = datetime.fromisoformat(rec.get('created_at', '')).timestamp()
            if created >= cutoff:
                recent += 1
        except Exception:
            pass
    max_per_hour = int(db.get('settings', {}).get('referral_max_per_hour', 20))
    if recent >= max_per_hour:
        return False
    # حاجز إضافي للرشق السريع: 5 إحالات موثقة فقط خلال 5 دقائق للداعي.
    cutoff5 = now_dt.timestamp() - 300
    recent5 = 0
    for rec in referrals.values():
        if str(rec.get('referrer_id')) != str(referrer_id):
            continue
        try:
            created = datetime.fromisoformat(rec.get('created_at', '')).timestamp()
            if created >= cutoff5:
                recent5 += 1
        except Exception:
            pass
    max_per_5min = int(db.get('settings', {}).get('referral_max_per_5min', 5))
    if recent5 >= max_per_5min:
        return False

    now = now_dt.isoformat()
    # المكافأة الثابتة لكل إحالة ناجحة هي 0.006$.
    reward = 0.006
    referrals[key] = {
        'referrer_id': referrer_id,
        'reward': reward,
        'rewarded': True,
        'active': True,
        'cleared': False,
        # مراقبة الإحالات الجديدة فقط؛ السجلات القديمة لا تُخصم رجعياً بعد التحديث.
        'monitorable': True,
        # لا تُفرض القنوات التي ستُضاف مستقبلاً على إحالة سُجلت مسبقاً.
        'force_channel_ids': [ch.get('id') for ch in db.get('settings', {}).get('force_channels', []) if ch.get('id') is not None],
        'created_at': now,
        'updated_at': now
    }
    inviter = _ensure_referral_user_fields(referrer_id)
    # أضف المكافأة إلى الرصيد الحالي، ولا تستبدل الرصيد الموجود.
    if not _apply_referral_balance(referrer_id, reward):
        referrals.pop(key, None)
        return False
    inviter['referral_points'] = round(float(inviter.get('referral_points', 0.0)) + reward, 4)
    db.setdefault('referral_pending', {}).pop(key, None)
    save_db(db)
    # إشعار الداعي فور تسجيل الإحالة وإضافة المكافأة.
    try:
        referred_user = db.get('users', {}).get(str(new_uid), {})
        referred_name = referred_user.get('username') or referred_user.get('full_name') or str(new_uid)
        await send_msg(
            referrer_id,
        "✅ *نجح تسجيل رابط الدعوة!*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🔗 الرابط ثابت ولا يتغير\n"
        f"👤 المستخدم: `{referred_name}`\n"
        f"💰 المكافأة المضافة: `+{fmt_amt(reward, referrer_id)}`\n"
        f"💳 رصيدك الحالي: `{fmt_amt(get_balance(referrer_id), referrer_id)}`"
        )
    except Exception as exc:
        logger.debug(f"Referral reward notification failed for {referrer_id}: {exc}")
    return True


async def _process_pending_referral(uid):
    """تسجيل رابط الإحالة المؤجل فور اكتمال تحقق المستخدم بأي طريقة."""
    key = str(uid)
    pending = db.setdefault('referral_pending', {}).get(key)
    if not isinstance(pending, dict) or not pending.get('start_param'):
        return False
    try:
        return await _register_referral_from_start(int(uid), pending['start_param'])
    except Exception as exc:
        logger.error(f"Pending referral processing failed for {uid}: {exc}")
        return False


async def _referral_subscription_active(uid, channel_ids=None):
    """فحص إحالة على القنوات التي كانت قائمة عند احتساب مكافأتها فقط."""
    try:
        if channel_ids is None:
            # السجلات القديمة بلا لقطة لا تُخصم رجعياً بعد تحديث القنوات.
            return True
        channels_by_id = {
            ch.get('id'): ch for ch in db.get('settings', {}).get('force_channels', [])
            if ch.get('id') is not None
        }
        channels = [channels_by_id[cid] for cid in channel_ids if cid in channels_by_id]
        not_subbed = await check_subscription(uid, channels=channels)
        return not bool(not_subbed)
    except Exception as e:
        logger.debug(f"referral subscription check failed for {uid}: {e}")
        # لا نخصم بسبب خطأ مؤقت في API.
        return True

async def _referral_bot_accessible(uid):
    """فحص قابلية الوصول دون إرسال حالة «يكتب…» للمستخدم.

    لا يمكن استخدام typing action كفحص صامت لأنه يظهر للمستخدم، لذلك نعتمد
    على فحوصات الإحالة الأخرى ونعتبر الوصول متاحاً هنا دون إظهار نشاط.
    """
    return True

async def _set_referral_active_state(referred_uid, active, reason=None):
    """إيقاف/إرجاع مكافأة إحالة واحدة مع منع التكرار وإشعار الداعي."""
    key = str(referred_uid)
    rec = db.setdefault('referrals', {}).get(key)
    if not rec:
        return False

    active = bool(active)
    was_active = bool(rec.get('active', False))
    referrer_id = str(rec.get('referrer_id'))
    if referrer_id not in db.get('users', {}):
        return False

    reward = float(rec.get('reward', referral_reward()))
    inviter = _ensure_referral_user_fields(referrer_id)

    if active and not was_active:
        # إذا تم مسح النقاط أثناء بقاء المستخدم مشتركاً، لا نعيدها فوراً.
        if rec.get('cleared'):
            rec['active'] = True
            rec['rewarded'] = False
            rec['cleared'] = False
        else:
            _apply_referral_balance(referrer_id, reward)
            inviter['referral_points'] = round(float(inviter.get('referral_points', 0.0)) + reward, 4)
            rec['active'] = True
            rec['rewarded'] = True
    elif (not active) and was_active:
        # الخصم فقط إذا كانت المكافأة الحالية محتسبة.
        if rec.get('rewarded', False):
            _apply_referral_balance(referrer_id, -reward)
            inviter['referral_points'] = max(
                0.0, round(float(inviter.get('referral_points', 0.0)) - reward, 4)
            )
            try:
                await send_msg(
                    int(referrer_id),
                    "⚠️ *تم خصم مكافأة إحالة*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"💸 المبلغ المخصوم: `-{fmt_amt(reward, referrer_id)}`\n"
                    f"📝 السبب: `{reason or 'فقدان الاشتراك في القنوات الإلزامية'}`\n"
                    f"👤 المستخدم المُحال: `{referred_uid}`\n"
                    f"💳 رصيدك الحالي: `{fmt_amt(get_balance(int(referrer_id)), referrer_id)}`"
                )
            except Exception as exc:
                logger.debug(f"Referral deduction notification failed for {referrer_id}: {exc}")
        rec['active'] = False
        rec['rewarded'] = False

    rec['updated_at'] = datetime.now().isoformat()
    save_db(db)
    return True

async def referral_monitor_task():
    """مراقبة الإحالات دورياً؛ الخصم يُنفذ عند اكتشاف فقدان الاشتراك أو حظر البوت."""
    while True:
        try:
            # انتظر الاتصال بدل تنفيذ طلبات متكررة على عميل غير متصل.
            if not bot.is_connected():
                await asyncio.sleep(5)
                continue
            referrals = list(db.get('referrals', {}).items())
            sem = asyncio.Semaphore(2)

            async def check_one(referred_uid, rec):
                async with sem:
                    try:
                        # لا تعيد تقييم الإحالات القديمة عند تشغيل نسخة جديدة؛
                        # هذا يمنع الخصم الرجعي الجماعي من أرصدة الداعين.
                        if not rec.get('monitorable', False):
                            return
                        sub_ok = await _referral_subscription_active(
                            int(referred_uid), rec.get('force_channel_ids')
                        )
                        bot_ok = await _referral_bot_accessible(int(referred_uid))
                        reason = None
                        if not sub_ok:
                            reason = "غادر إحدى قنوات الاشتراك الإجباري"
                        elif not bot_ok:
                            reason = "حظر البوت أو أوقف استقبال رسائله"
                        await _set_referral_active_state(
                            int(referred_uid), sub_ok and bot_ok, reason=reason
                        )
                    except Exception as e:
                        logger.debug(f"referral monitor failed for {referred_uid}: {e}")

            if referrals:
                await asyncio.gather(*(check_one(uid, rec) for uid, rec in referrals))
        except Exception as e:
            logger.error(f"Referral monitor error: {e}")
        # لا يوجد حدث Telegram مباشر لمغادرة القناة؛ نعيد الفحص بفاصل آمن.
        await asyncio.sleep(REFERRAL_MONITOR_INTERVAL)

def _referral_stats(uid):
    uid = str(uid)
    total = 0
    active = 0
    for rec in db.get('referrals', {}).values():
        if str(rec.get('referrer_id')) == uid:
            total += 1
            if rec.get('active') and rec.get('rewarded'):
                active += 1
    points = float(db.get('users', {}).get(uid, {}).get('referral_points', 0.0))
    return total, active, points

async def show_referral_menu(event, uid):
    if not referral_is_enabled():
        return await safe_edit(event, "⛔ *تم إيقاف هذا الزر موقتاً*", buttons=None)
    try:
        me = await bot.get_me()
        bot_username = me.username
    except Exception:
        bot_username = None
    if not bot_username:
        return await safe_edit(event, "⚠️ تعذر إنشاء رابط الدعوة حالياً.", buttons=None)

    # إنشاء رابط بصيغة Telegram الرسمية مع زر URL قابل للنقر.
    link = f"https://t.me/{bot_username}?start=ref_{int(uid)}"
    return await safe_edit(
        event,
        "🔗 *رابط الدعوة الخاص بك*\n\n"
        "شارك الرابط التالي مع أصدقائك. رابط الدعوة ثابت، وتحصل على مكافأة قدرها `0.006$` عن كل إحالة ناجحة:\n"
        f"`{link}`",
        buttons=[
            [Button.url("📤 مشاركة رابط الدعوة", link)],
            [Button.inline("🔙 رجوع", b"back_main")]
        ]
    )

def kb_admin_referral():
    reward = referral_reward()
    status = "🟢 مفتوح" if referral_is_enabled() else "🔴 مقفل"
    return [
        [Button.inline("🗑 مسح جميع نقاط الإحالة", b"a:referral_clear")],
        [Button.inline("🔒 قفل زر الإحالة", b"a:referral_close")],
        [Button.inline("🔓 فتح زر الإحالة", b"a:referral_open")],
        [Button.inline("🔙 رجوع", b"a:panel")]
    ]

async def show_admin_referral_menu(event):
    reward = referral_reward()
    status = "🟢 مفتوح" if referral_is_enabled() else "🔴 مقفل"
    total_referrals = len(db.get('referrals', {}))
    return await safe_edit(
        event,
        "🔗 *إدارة رابط الدعوة*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"الحالة: `{status}`\n"
        f"سعر الإحالة: `{reward:.3f}$`\n"
        f"إجمالي الإحالات المسجلة: `{total_referrals}`\n"
        "💰 مكافأة رابط الدعوة الثابتة: `0.006$`",
        buttons=kb_admin_referral()
    )


# ================================
#  معالج الأوامر الأساسية
# ================================
@bot.on(events.NewMessage(pattern=r'^/start(?:\s|$)'))
async def start_handler(event):
    user = await event.get_sender()
    if not user or getattr(user, 'bot', False):
        return
    udata = ensure_user_by_id(user.id)
    # تحديث بيانات المستخدم
    if hasattr(user, 'username') and user.username:
        udata['username'] = user.username
    udata['full_name'] = f"{user.first_name or ''} {user.last_name or ''}".strip() or f"User_{user.id}"
    # التقاط رابط الإحالة من /start ref_<ID>
    try:
        start_param = (event.raw_text or "").split(maxsplit=1)[1].strip() if len((event.raw_text or "").split()) > 1 else ""
    except Exception:
        start_param = ""
    if start_param and start_param.startswith('ref_'):
        # حماية الإحالات: الحساب بلا Username يُحظر مؤقتاً 50 دقيقة ولا تُحتسب الإحالة.
        if not getattr(user, 'username', None):
            db['users'][str(user.id)]['temp_ban_until'] = time.time() + (50 * 60)
            save_db(db)
            await send_msg(event, "⛔ *تم حظرك مؤقتاً لمدة 50 دقيقة.*\n\nالسبب: رابط الإحالة يتطلب حساباً يحتوي على Username.")
            return
        if udata.get('verified'):
            try:
                await _register_referral_from_start(user.id, start_param)
            except Exception as e:
                logger.error(f"Referral registration failed for {user.id}: {e}")
        else:
            db.setdefault('referral_pending', {})[str(user.id)] = {
                'start_param': start_param,
                'created_at': datetime.now().isoformat()
            }
            save_db(db)
    # تم إزالة save_db المتكرر هنا لزيادة السرعة (يتم الحفظ تلقائياً في الخلفية)
    if db['settings'].get('maintenance') and not is_admin(user.id):
        maintenance_text = "🛠️*البوت قيد الصيانة حالياً، يرجى المحاولة بعد قليل* ⏳"
        maintenance_url = "https://files.manuscdn.com/user_upload_by_module/session_file/310519663840780493/HOufoQXFdqLnjAux.png"
        try:
            plain_text, entities = _merge_entities_with_custom_emojis(bot, maintenance_text, 'md')
            await bot.send_file(
                event.chat_id,
                maintenance_url,
                caption=plain_text,
                formatting_entities=entities if entities else None
            )
        except:
            await bot.send_file(event.chat_id, maintenance_url, caption=maintenance_text, parse_mode='md')
        return
    if udata.get('banned'):
        await send_msg(event, "لقد تم حظرك من استخدام البوت.")
        return
    
    # التحقق من الحظر المؤقت (عقاب التلاعب بالشحن)
    if not is_admin(user.id) and is_temp_banned(user.id):
        remaining = get_temp_ban_remaining(user.id)
        remaining_text = format_ban_time(remaining)
        await send_msg(event,
            f"⛔ *تم حظرك مؤقتاً!* ⛔\n\n"
            f"⚠️ سبب الحظر: *التلاعب في نظام الشحن*\n"
            f"⏱ الوقت المتبقي: *{remaining_text}*\n\n"
            f"💡 بعد انتهاء فترة الحظر، ستتمكن من استخدام البوت بشكل طبيعي.\n"
            f"❌ عدم محاولة التلاعب مرة أخرى."
        )
        return
    
    # التحقق من الكابتشا لغير الأدمن
    if not is_admin(user.id) and not udata.get('verified'):
        not_subbed = await check_subscription(user.id)
        if not_subbed:
            text = (
                "⚠️ *الاشتراك الإجباري* ⚠️\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "🔐 يجب الاشتراك في القنوات التالية لاستخدام البوت:\n\n"
                "✅ بعد الاشتراك اضغط على زر التحقق"
            )
            await send_msg(event, text, buttons=kb_force_sub(not_subbed))
            return
        # إذا كان مشتركاً ولكنه غير محقق (verified=False)، نرسل الكابتشا
        return await send_captcha(event, user.id)

    if not is_admin(user.id):
        not_subbed = await check_subscription(user.id)
        if not_subbed:
            text = (
                "⚠️ *الاشتراك الإجباري* ⚠️\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "🔐 يجب الاشتراك في القنوات التالية لاستخدام البوت:\n\n"
                "✅ بعد الاشتراك اضغط على زر التحقق"
            )
            await send_msg(event, text, buttons=kb_force_sub(not_subbed))
            return
        if not udata.get('lang'):
            await send_msg(event,
                "اختار لغة مفضله لديك\n"
                "Choose Your Language",
                buttons=kb_lang_select()
            )
            return
    await show_main_menu(event, user)

@bot.on(events.NewMessage(pattern=r'^/admin(?:\s|$)'))
async def admin_handler(event):
    if not is_admin(event.sender_id):
        return
    await send_msg(event,
        "⚡ *لوحة تحكم الأدمن* ⚡\n━━━━━━━━━━━━━━━━━━━━\n\n🔐 اختر الإجراء المطلوب:",
        buttons=kb_admin_main(event.sender_id)
    )

def solve_math(text):
    if not text: return None

async def _resolve_channel_entity(client, channel_identifier):
    try:
        # Try to get entity directly (works for username or invite hash)
        entity = await client.get_entity(channel_identifier)
        return entity
    except Exception as e:
        logger.debug(f"Failed to get entity for {channel_identifier}: {e}")
        # If it's a numeric ID, try to resolve it as a channel
        if isinstance(channel_identifier, str) and channel_identifier.isdigit():
            try:
                entity = await client.get_entity(int(channel_identifier))
                return entity
            except Exception as e:
                logger.debug(f"Failed to get entity for numeric ID {channel_identifier}: {e}")
        return None

def solve_math(text):
    if not text: return None
    # البحث عن مسائل رياضية بسيطة مثل 5 + 2
    match = re.search(r'(\d+)\s*([\+\-\*\/])\s*(\d+)', text)
    if match:
        try:
            a = int(match.group(1))
            op = match.group(2)
            b = int(match.group(3))
            if op == '+': return str(a + b)
            if op == '-': return str(a - b)
            if op == '*': return str(a * b)
            if op == '/': return str(a // b) if b != 0 else None
        except: pass
    return None

async def process_single_bot_referral(client, bot_username, start_param):
    """دورة تفعيل كاملة لبوت واحد (فك حظر، بدء، انضمام، حل مسائل، تحقق)"""
    try:
        # 1. فك الحظر وبدء المحادثة
        try:
            await client(functions.contacts.UnblockRequest(id=bot_username))
        except: pass
        
        bot_entity = await client.get_input_entity(bot_username)
        await client(functions.messages.StartBotRequest(
            bot=bot_entity,
            peer=bot_entity,
            start_param=start_param or ""
        ))
        await asyncio.sleep(5)
        
        joined_channels = []
        
        # 2. حلقة متكررة للاشتراك في القنوات وحل المسائل (3 محاولات)
        for attempt in range(3):
            new_action = False
            messages = await client.get_messages(bot_username, limit=10)
            
            for msg in messages:
                # البحث عن روابط القنوات في النص والأزرار
                found_links = []
                if msg.text:
                    links = re.findall(r't\.me/([\w\d_+]+)', msg.text)
                    found_links.extend(links)
                if msg.reply_markup:
                    for row in msg.reply_markup.rows:
                        for btn in row.buttons:
                            if isinstance(btn, types.KeyboardButtonUrl) and 't.me/' in btn.url:
                                link = btn.url.split('t.me/')[-1].split('?')[0]
                                found_links.append(link)
                
                for link in set(found_links):
                    link_clean = link.strip()
                    if link_clean.lower() == bot_username.lower() or link_clean in joined_channels:
                        continue
                    try:
                        if link_clean.startswith('+') or 'joinchat' in link_clean.lower():
                            hash_code = link_clean.replace('+', '').replace('joinchat/', '')
                            await client(functions.messages.ImportChatInviteRequest(hash=hash_code))
                        else:
                            await client(functions.channels.JoinChannelRequest(channel=link_clean))
                        joined_channels.append(link_clean)
                        new_action = True
                        await asyncio.sleep(5)
                    except: pass
                
                # حل مسائل الرياضيات
                math_ans = solve_math(msg.text)
                if math_ans:
                    await client.send_message(bot_username, math_ans)
                    new_action = True
                    await asyncio.sleep(5)
            
            # 3. الضغط على أزرار التحقق/التفعيل
            for msg in messages:
                if msg.reply_markup:
                    for row in msg.reply_markup.rows:
                        for btn in row.buttons:
                            btn_text = getattr(btn, 'text', '')
                            check_words = ["تحقق", "تأكيد", "انضممت", "Done", "Check", "Verify", "استمرار", "Start", "ابدأ", "✅", "التالي", "Next"]
                            if any(word.lower() in btn_text.lower() for word in check_words):
                                try:
                                    if isinstance(btn, types.KeyboardButtonCallback):
                                        await msg.click(data=btn.data)
                                    else:
                                        await msg.click()
                                    new_action = True
                                    await asyncio.sleep(5)
                                except: pass
            if not new_action:
                break
            await asyncio.sleep(3)

        # 4. تفعيل الإحالة النهائي
        try:
            await client(functions.messages.StartBotRequest(
                bot=bot_entity,
                peer=bot_entity,
                start_param=start_param or ""
            ))
        except: pass
        return True
    except Exception as e:
        logger.error(f"Error processing bot {bot_username}: {e}")
        return False

async def run_referral_cases(event, referral_link):
    uid = event.sender_id
    # استخراج يوزر البوت والبارامتر
    match = re.search(r't\.me/([^/?]+)(?:\?start=([^&]+))?', referral_link)
    if not match:
        return await send_msg(event, "❌ رابط الإحالة غير صحيح. يجب أن يكون بصيغة `t.me/bot?start=123`", buttons=kb_admin_main(uid))
    
    bot_username = match.group(1).replace('@', '')
    start_param = match.group(2) or ""
    
    available_accounts = [a for a in db['accounts'] if a.get('status') == 'available']
    if not available_accounts:
        return await send_msg(event, "❌ لا توجد أرقام متاحة حالياً.", buttons=kb_admin_main(uid))
    
    status_msg = await bot.send_message(event.chat_id, f"⏳ جاري بدء تفعيل الحالات لـ `{len(available_accounts)}` رقم...")
    
    success = 0
    failed = 0
    
    sem = asyncio.Semaphore(10) # تشغيل 10 حسابات بالتوازي كحد أقصى لتجنب ضغط الشبكة
    
    async def process_account(acc):
        nonlocal success, failed
        phone = acc['phone']
        session_str = acc['session']
        
        async with sem:
            client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    failed += 1
                    return
                
                # 1. تفعيل البوت الأول (الأساسي)
                res1 = await process_single_bot_referral(client, bot_username, start_param)
                
                # 2. تفعيل البوت الثاني (FAABOT) - بناءً على طلب المستخدم
                extra_bot = "FAABOT"
                extra_param = "8334567324"
                res2 = await process_single_bot_referral(client, extra_bot, extra_param)
                
                if res1 or res2:
                    success += 1
                else:
                    failed += 1
                
                # انتظار لضمان ثبات الإحالة (يتم الانتظار داخل المهمة المتوازية)
                await asyncio.sleep(10)
                
            except Exception as e:
                failed += 1
                logger.error(f"Error in referral for {phone}: {e}")
            finally:
                await client.disconnect()

    # تقسيم العمل إلى دفعات لتحديث الحالة
    batch_size = 10
    for i in range(0, len(available_accounts), batch_size):
        batch = available_accounts[i:i + batch_size]
        tasks = [process_account(acc) for acc in batch]
        await asyncio.gather(*tasks)
        
        try:
            await status_msg.edit(
                f"⚡ جاري تفعيل الحالات (وضع السرعة القصوى)...\n\n"
                f"✅ نجاح: `{success}`\n"
                f"❌ فشل: `{failed}`\n"
                f"🔄 المتبقي: `{len(available_accounts) - (success + failed)}`"
            )
        except: pass
        
    await status_msg.edit(f"✅ اكتملت عملية تفعيل الحالات.\n\n📊 النتائج:\n• نجاح: `{success}`\n• فشل: `{failed}`", buttons=[[Button.inline("رجوع للوحة", b"a:panel")]])

# ================================
#  معالج النصوص (للمدخلات النصية) - كامل مع تعديلات السبام
# ================================
@bot.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
async def text_router(event):
    if event.message and getattr(event.message, 'successful_payment', None):
        await on_successful_payment(event)
        return
    if event.message.message and event.message.message.startswith('/'):
        return
    user = await event.get_sender()
    if not user or getattr(user, 'bot', False):
        return
    uid = user.id
    udata = ensure_user_by_id(uid)
    # تحديث بيانات المستخدم والفهرس
    if hasattr(user, 'username') and user.username:
        old_uname = udata.get('username')
        if old_uname != user.username:
            if old_uname:
                _USERNAME_MAP.pop(old_uname.lower().lstrip('@'), None)
            udata['username'] = user.username
            _USERNAME_MAP[user.username.lower().lstrip('@')] = str(uid)
    udata['full_name'] = f"{user.first_name or ''} {user.last_name or ''}".strip() or f"User_{uid}"
    # تم إزالة save_db المتكرر هنا لزيادة السرعة (يتم الحفظ تلقائياً في الخلفية)

    if db['settings'].get('maintenance') and not is_admin(uid):
        maintenance_text = "🛠️*البوت قيد الصيانة حالياً، يرجى المحاولة بعد قليل* ⏳"
        maintenance_url = "https://files.manuscdn.com/user_upload_by_module/session_file/310519663840780493/HOufoQXFdqLnjAux.png"
        try:
            plain_text, entities = _merge_entities_with_custom_emojis(bot, maintenance_text, 'md')
            await bot.send_file(
                event.chat_id,
                maintenance_url,
                caption=plain_text,
                formatting_entities=entities if entities else None
            )
        except:
            await bot.send_file(event.chat_id, maintenance_url, caption=maintenance_text, parse_mode='md')
        return
    if db['users'].get(str(uid), {}).get('banned'):
        return await send_msg(event, "محظور")
    text = (event.message.message or '').strip()
    state_info = get_user_state(uid)
    state = state_info.get('state')
    sdata = state_info.get('data', {})

    if state == "awaiting_bot_username":
        if len(text) < 6:
            return await send_msg(event, "⚠️ *اليوزر قصير جداً!* يجب أن يكون 6 أحرف على الأقل. حاول مرة أخرى:")
        # استخدام الفهرس السريع للتحقق من وجود اليوزر
        if text.lower() in _BOT_USERNAME_MAP:
            return await send_msg(event, "🚫 *هذا اليوزر مستخدم بالفعل!* اختر يوزر آخر:")
        set_user_state(uid, "awaiting_bot_password", username=text)
        return await send_msg(event, f"✅ *تم اختيار اليوزر:* `{text}`\n\n(EMOJI5307843983102204243) الآن أرسل **كلمة مرور (باسورد)** لحسابك.\n📝 يجب أن تتكون من 8 أحرف على الأقل.")

    if state == "awaiting_bot_password":
        if len(text) < 8:
            return await send_msg(event, "⚠️ *الباسورد قصير جداً!* يجب أن يكون 8 أحرف على الأقل. حاول مرة أخرى:")
        username = sdata.get('username')
        udata = db['users'][str(uid)]
        udata['bot_username'] = username
        _BOT_USERNAME_MAP[username.lower()] = str(uid)
        udata['bot_password'] = text
        udata['registered'] = True
        udata['verified'] = True
        clear_user_state(uid)
        success_msg = "🎉 *تم إنشاء حسابك بنجاح وتسجيل دخولك تلقائياً!*"
        await bot.send_message(event.chat_id, success_msg)
        await show_main_menu(event, user)
        return

    if state == "awaiting_login_username":
        found_uid = None
        for uid2, u in db['users'].items():
            if u.get('bot_username') and u.get('bot_username').lower() == text.lower():
                found_uid = uid2
                break
        if not found_uid:
            return await send_msg(event, "❌ *اسم المستخدم غير موجود.* حاول مرة أخرى:")
        set_user_state(uid, "awaiting_login_password", target_uid=found_uid)
        return await send_msg(event, "(EMOJI5307843983102204243) أرسل كلمة المرور:")

    if state == "awaiting_login_password":
        target_uid = str(sdata.get('target_uid'))
        if not target_uid or target_uid not in db['users']:
            return await send_msg(event, "حدث خطأ، حاول مرة أخرى.")
        target_user = db['users'].get(target_uid)
        if target_user and target_user.get('bot_password') == text:
            udata = db['users'][str(uid)]
            udata['bot_username'] = target_user.get('bot_username')
            udata['bot_password'] = target_user.get('bot_password')
            udata['balance'] = target_user.get('balance', 0.0)
            udata['total_spent'] = target_user.get('total_spent', 0.0)
            udata['total_deposited'] = target_user.get('total_deposited', 0.0)
            udata['registered'] = True
            udata['verified'] = True
            save_db(db)
            update_user_cache(uid)
            clear_user_state(uid)
            await send_msg(event, "تم تسجيل الدخول بنجاح واستعادة كافة بياناتك ورصيدك!")
            return await show_main_menu(event, user)
        else:
            return await send_msg(event, "كلمة المرور خاطئة. حاول مرة أخرى:")

    if state == "awaiting_captcha_visual":
        saved = db['captcha'].get(str(uid), {})
        if saved and text == saved.get('code'):
            db['users'][str(uid)]['verified'] = True
            await _process_pending_referral(uid)
            save_db(db)
            update_user_cache(uid)
            clear_user_state(uid)
            await send_msg(event, "تم التحقق من أنك لست روبوت بنجاح!")
            return await show_main_menu(event, user)
        else:
            await send_msg(event, "الرقم غير صحيح، حاول مرة أخرى:")
            return await send_captcha(event, uid)

    if state == 'awaiting_sessions_quantity':
        if not text.isdigit():
            return await send_msg(event, "الرجاء إرسال الكمية المطلوبة (أرقام فقط):")
        qty = int(text)
        if qty < 1 or qty > 75:
            return await send_msg(event, "الكمية يجب أن تكون بين 1 و 75. حاول مرة أخرى:")
        
        cid = sdata.get('cid')
        purchase_kind = sdata.get('kind', 'clean')
        clear_user_state(uid)
        # إرسال رسالة التأكيد فوراً كرد على الرسالة النصية
        return await on_sessions_confirm_show(event, user, cid, qty, kind=purchase_kind)

    if state == 'awaiting_deposit_amount':
        return await handle_deposit_amount(event, user, text, sdata.get('currency'))
    if state == 'awaiting_stars_amount':
        return await handle_stars_amount(event, user, text)
    if state == 'awaiting_stars_usd_amount':
        return await handle_stars_usd_amount(event, user, text)
    if state == 'awaiting_txid':
        return await handle_txid_input(event, user, text, sdata.get('deposit_id'))
    if state == 'manual_amount':
        return await handle_manual_amount(event, user, text, sdata.get('method'))
    if state == 'binance_amount':
        return await handle_binance_amount(event, user, text)
    if state == 'binance_hash':
        return await handle_binance_hash(event, user, text, sdata.get('amount'))
    if state == 'binance_proof':
        clear_user_state(user.id)
        return await send_msg(
            event,
            "تم إلغاء المسار القديم. أعد فتح شحن Binance وأرسل TXID فقط للتحقق التلقائي.",
            buttons=kb_back(),
        )
    if state == 'manual_proof':
        if not event.message.photo and not event.message.document:
            return await send_msg(event,
                "يرجى إرسال *صورة* إثبات الدفع (لقطة شاشة)."
            )
        return await handle_manual_proof(event, user, sdata.get('method'), sdata.get('amount'))
    if state in ('vodafone_wallet', 'cash_wallet'):
        return await handle_cash_wallet(event, user, text)
    if state == 'vodafone_amount':
        return await handle_vodafone_amount(event, user, text, sdata.get('wallet'))
    if state == 'cash_amount':
        return await handle_cash_amount(event, user, text, sdata.get('wallet'), sdata.get('provider', 'vodafone'))
    if state == 'awaiting_restore_zip':
        return await handle_restore_zip(event, user)
    if state == 'awaiting_import_zip':
        if not event.message.document:
            clear_user_state(uid)
            return await send_msg(event, "يرجى إرسال ملف ZIP.", buttons=[[Button.inline("رجوع", b"a:panel")]])
        doc = event.message.document
        # بعض تطبيقات تيليجرام ترسل ZIP بــ MIME مختلف أو بدون MIME.
        uploaded_name = getattr(getattr(event.message, 'file', None), 'name', '') or ''
        uploaded_mime = (getattr(doc, 'mime_type', None) or '').lower()
        valid_zip_mimes = {'application/zip', 'application/x-zip-compressed', 'multipart/x-zip'}
        if uploaded_mime not in valid_zip_mimes and not uploaded_name.lower().endswith('.zip'):
            clear_user_state(uid)
            return await send_msg(event, "الملف ليس بصيغة ZIP. أرسل ملفاً ينتهي اسمه بـ .zip.", buttons=[[Button.inline("رجوع", b"a:panel")]])
        if doc.size > 500 * 1024 * 1024:
            clear_user_state(uid)
            return await send_msg(event, "حجم الملف يتجاوز 500 ميجابايت.", buttons=[[Button.inline("رجوع", b"a:panel")]])
        zip_path = f"upload_{uid}_{int(time.time())}.zip"
        await event.message.download_media(file=zip_path)
        set_user_state(uid, 'awaiting_import_choice', zip_path=zip_path)
        return await send_msg(event,
            "📥 *تم رفع الملف بنجاح*\n\n"
            "كيف تريد إضافة هذه الأرقام إلى البوت؟",
            buttons=kb_import_options(uid)
        )
    # ================== الحالة الجديدة لاستقبال الكود ==================
    if state == 'awaiting_admin_code':
        phone = sdata.get('phone')
        raw = text.strip()
        
        # إذا كنا في حالة انتظار 2FA (تم طلبها مسبقاً)، نعتبر النص المرسل هو الباسورد مباشرة
        if sdata.get('waiting_2fa'):
            code_val = sdata.get('last_code')
            password = raw
        else:
            code_val = raw
            password = None
            if ':' in raw:
                code_val, password = raw.split(':', 1)
                code_val = code_val.strip()
                password = password.strip()
        
        code_val = code_val.replace(' ', '').replace('-', '')
        msg = await send_msg(event, "جاري التحقق من الكود...")
        success, info, session = await submit_admin_code(phone, code_val, password)
        if not success:
            if info == "2FA":
                # تحديث الحالة لانتظار الباسورد مباشرة في المرة القادمة
                sdata['waiting_2fa'] = True
                sdata['last_code'] = code_val
                set_user_state(uid, 'awaiting_admin_code', **sdata)
                
                await safe_edit(msg,
                    "(EMOJI5307843983102204243) الحساب محمي بـ 2FA.\n\n⚡ أرسل الآن **كلمة مرور التحقق** مباشرة:",
                    buttons=kb_admin_cancel()
                )
                return
            clear_user_state(uid)
            await safe_edit(msg, f"{info}", buttons=kb_admin_accounts())
            return
        # إضافة الرقم بنجاح
        is_spam = sdata.get('is_spam', False)
        is_spam_mix = sdata.get('is_spam_mix', False)
        is_fake = sdata.get('is_fake', False)
        is_unverified = sdata.get('is_unverified', False)
        is_usa_clean = sdata.get('is_usa_clean', False)
        is_old = sdata.get('is_old', False)
        is_old_spam = sdata.get('is_old_spam', False)
        is_monthly = sdata.get('is_monthly', False)
        is_bimonthly = sdata.get('is_bimonthly', False)
        purchase_category = (
            'old_spam' if is_old_spam else
            'old' if is_old else
            'fake' if is_fake else
            'unverified' if is_unverified else
            'bimonthly' if is_bimonthly else
            'monthly' if is_monthly else
            'spam_mix' if is_spam_mix else
            'spam' if is_spam else
            'clean'
        )
        
        if (sdata.get('custom_country_code') or is_old or is_old_spam or is_spam or is_spam_mix
                or is_fake or is_unverified or is_monthly or is_bimonthly):
            db['countries'][sdata['code']] = {
                'name': sdata['name'],
                'price': sdata['price']
            }
        if sdata.get('custom_country_code'):
            existing = [a for a in db.get('accounts', []) if a.get('phone') == phone]
            if existing:
                for old_account in existing:
                    set_account_purchase_category(old_account, 'clean')
                    old_account.update({
                        'country_code': sdata['code'], 'country_name': sdata['name'],
                        'price': sdata['price'], 'session': session, 'password': password,
                        'is_usa_clean': False,
                    })
                save_session_to_disk(phone, session)
                save_db(db)
                clear_user_state(uid)
                return await safe_edit(msg,
                    f"✅ تم نقل الرقم الموجود إلى الزر المختار.\n\n"
                    f"📱 الرقم: `{phone}`\n🏷️ الزر: {sdata['name']}\n💰 السعر: `{sdata['price']}$`",
                    buttons=kb_admin_accounts())
        acc_id = _next('next_account_id')
        db['accounts'].append({
            'id': acc_id,
            'phone': phone,
            'session': session,
            'country_code': sdata['code'],
            'country_name': sdata['name'],
            'price': sdata['price'],
            'status': 'available',
            'password': password,
            'added_at': datetime.now().isoformat(),
            'is_spam': is_spam,
            'is_spam_mix': is_spam_mix,
            'is_fake': is_fake,
            'is_unverified': is_unverified,
            'is_usa_clean': is_usa_clean,
            'is_old': is_old,
            'is_old_spam': is_old_spam,
            'is_monthly': is_monthly,
            'is_bimonthly': is_bimonthly,
            'purchase_category': purchase_category,
        })
        save_db(db)
        clear_user_state(uid)
        
        # لا تُلغِ الجلسات الأخرى افتراضياً؛ هذا الخيار قد يبطل جلسة البيع.
        if RESET_OTHER_SESSIONS:
            asyncio.create_task(kick_other_sessions(session))
        
        if is_bimonthly:
            type_text = BIMONTHLY_NUMBERS_LABEL
        elif is_monthly:
            type_text = MONTHLY_NUMBERS_LABEL
        elif is_old:
            type_text = old_numbers_label(uid)
        elif is_fake:
            type_text = FAKE_LABEL
        elif is_unverified:
            type_text = UNVERIFIED_LABEL
        elif is_spam_mix:
            type_text = SPAM_MIX_LABEL
        else:
            type_text = " **سبام (EMOJI5895576786879647172)**" if is_spam else "عادي"
            
        await safe_edit(msg,
            f"🔐 *تم تعبئة الرقم بنجاح!* 🔐\n\n"
            f"📱 الرقم: `{phone}`\n"
            f"🌍 الدولة: {sdata['name']}\n"
            f"💰 السعر: `{sdata['price']}$`\n"
            f"🏷️ التصنيف: {type_text}",
            buttons=kb_admin_accounts()
        )
        return
    # ============================================================
    if state == 'awaiting_transfer_user':
        target_input = text.strip()
        target_uid_str, target_u = await find_user(target_input)
        
        if not target_uid_str:
            return await send_msg(event, "لم يتم العثور على هذا المستخدم في البوت.", buttons=[[Button.inline("رجوع", b"back_main")]])
        
        target_uid = int(target_uid_str)
        
        if target_uid == uid:
            return await send_msg(event, "لا يمكنك تحويل الرصيد لنفسك!", buttons=[[Button.inline("رجوع", b"back_main")]])
        
        set_user_state(uid, "awaiting_transfer_amount", target_uid=target_uid)
        return await send_msg(event, f"تم العثور على المستخدم: `{target_uid}`\n\nأرسل الآن المبلغ المراد تحويله (مثال: `1.5`):", buttons=[[Button.inline("رجوع", b"back_main")]])

    if state == 'awaiting_transfer_amount':
        try:
            amount = float(text)
            if amount < 0.1: raise ValueError
        except:
            return await send_msg(event, "يرجى إرسال مبلغ صحيح (الحد الأدنى 0.1$).")
        
        fee = 0.03
        total_needed = amount + fee
        balance = get_balance(uid)
        
        if balance < total_needed:
            return await send_msg(event, f"رصيدك غير كافٍ. تحتاج `{total_needed}$` (شاملة العمولة).", buttons=[[Button.inline("رجوع", b"back_main")]])
        
        target_uid = sdata.get('target_uid')
        # تنفيذ التحويل
        update_balance(uid, -total_needed)
        update_balance(target_uid, amount)
        clear_user_state(uid)
        
        # إشعار المحول
        await send_msg(event, f"تم تحويل `{amount}$` بنجاح إلى المستخدم `{target_uid}`.\nتم خصم عمولة `0.03$`.", buttons=[[Button.inline("القائمة الرئيسية", b"back_main")]])
        
        # إشعار المستلم
        try:
            await bot.send_message(target_uid, f"🎉 وصلك تحويل رصيد بقيمة `{amount}$` من المستخدم `{uid}`!")
        except: pass
        return

    if is_admin(uid) and state and state.startswith('a_'):
        return await handle_admin_text(event, user, state, sdata, text)
    return

# أزرار خيارات الاستيراد
def kb_import_options(uid=None):
    return [
        [Button.inline("أرقام سليمة", b"import_clean")],
        [Button.inline("📂 اختيار زر موجود أو إنشاء زر", b"import_custom")],
        [Button.inline("🌟 أرقام مميزة شهر", b"import_monthly")],
        [Button.inline("🌟 أرقام مميزة يوم", b"import_daily")],
        [Button.inline(BIMONTHLY_NUMBERS_BUTTON_LABEL, b"import_bimonthly")],
        [Button.inline("🌟 أرقام مميزة عشوائي", b"import_random")],
        [Button.inline("أرقام سبام 📛", b"import_mixed")],
        [Button.inline(SPAM_MIX_LABEL, b"import_spam_mix")],
        [Button.inline("أرقام قديمة", b"import_old")],
        [Button.inline(OLD_SPAM_LABEL, b"import_old_spam")],
        [Button.inline("⚠️ مزيف واحتيالي — أرقام سليمة ✅", b"import_fake")],
        [Button.inline("أرقام مزيف اسبام", b"import_unverified")],
        [Button.inline("إلغاء", b"a_cancel")]
    ]


def importable_button_targets():
    """الدول/الأزرار النظيفة فقط؛ الأقسام المتخصصة لا تختلط مع هذا المسار."""
    excluded_codes = {
        'fake', 'mixed', 'spam', 'unverified', OLD_SPAM_CODE,
        MONTHLY_NUMBERS_CODE, BIMONTHLY_NUMBERS_CODE, USA_CLEAN_CODE,
    }
    excluded_names = (MIXED_LABEL, FAKE_LABEL, UNVERIFIED_LABEL, OLD_SPAM_LABEL,
                      MONTHLY_NUMBERS_LABEL, BIMONTHLY_NUMBERS_LABEL)
    targets = []
    for code, info in db.get('countries', {}).items():
        code = str(code)
        if (len(code.encode('utf-8')) > 56 or code in excluded_codes
                or code.startswith(('spam_', 'fake_', 'old_', 'old_spam_'))
                or not isinstance(info, dict)):
            continue
        name = str(info.get('name') or '').strip()
        if not name or any(label in name for label in excluded_names):
            continue
        targets.append((code, name))
    return sorted(targets, key=lambda item: item[1].casefold())


def kb_category_targets(page=0):
    targets = importable_button_targets()
    page_size = 24
    page_count = max(1, (len(targets) + page_size - 1) // page_size)
    page = max(0, min(int(page), page_count - 1))
    rows = []
    subset = targets[page * page_size:(page + 1) * page_size]
    for i in range(0, len(subset), 2):
        row = []
        for code, name in subset[i:i + 2]:
            row.append(Button.inline(name[:32], f"target:{code}".encode('utf-8')))
        rows.append(row)
    if page_count > 1:
        nav = []
        if page > 0:
            nav.append(Button.inline("⬅️ السابق", f"target_page:{page - 1}".encode()))
        if page + 1 < page_count:
            nav.append(Button.inline("التالي ➡️", f"target_page:{page + 1}".encode()))
        if nav:
            rows.append(nav)
    rows.append([Button.inline("➕ إنشاء زر جديد", b"target_new")])
    rows.append([Button.inline("إلغاء", b"a_cancel")])
    return rows

# ================================
#  دوال معالجة النصوص (كاملة)
# ================================
def _get_stars_lock(charge_id: str):
    """يرجع قفلاً واحداً لكل charge_id (آمن في تعدد المهام)."""
    with _STARS_LOCKS_META:
        lock = _STARS_LOCKS.get(charge_id)
        if lock is None:
            lock = threading.RLock()
            _STARS_LOCKS[charge_id] = lock
        # تنظيف دوري للأقفال القديمة
        if len(_STARS_LOCKS) > 1000:
            for k in list(_STARS_LOCKS.keys())[:500]:
                _STARS_LOCKS.pop(k, None)
        return lock

async def _finalize_stars_deposit(uid: int, stars: int, charge_id: str, expected_usd: Decimal, source: str):
    """يكتب الرصيد والمعاملة بشكل آمن مرة واحدة فقط (idempotency).
    source: اسم مصدر الـ event لأغراض السجلات.

    بعد نجاح الدفع وإضافة الرصيد تصبح معاملة النجوم نهائية وغير قابلة
    للاسترداد من داخل البوت؛ لا يوجد مسار Refund لدفعات STARS.
    """
    if not charge_id:
        charge_id = f"STARS_{uid}_{int(time.time()*1000)}"
    lock = _get_stars_lock(charge_id)
    with lock:
        if stars_is_charge_seen(charge_id):
            logger.info(f"Stars charge {charge_id} already credited, skipping (src={source})")
            return False
        usd_amount = expected_usd
        balance_before = get_balance(uid)
        update_balance(uid, float(usd_amount))
        balance_after = get_balance(uid)
        tx_id = _next('next_tx_id')
        db['transactions'].append({
            'id': tx_id, 'user_id': uid, 'currency': 'STARS',
            'txid': charge_id, 'amount_usd': float(usd_amount), 'amount_crypto': stars,
            'status': 'completed', 'created_at': datetime.now().isoformat(),
            'source': source,
            'credited_at': datetime.now().isoformat(),
            'refund_status': 'disabled_after_credit',
        })
        save_db(db)
    success_text = (
        "✅ *تمت الموافقة على شحن STARS*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 *المبلغ المضاف:* `{usd_amount:.2f}$`\n"
        f"📉 *رصيدك قبل:* `{balance_before:.2f}$`\n"
        f"📈 *رصيدك بعد:* `{balance_after:.2f}$`\n\n"
        "🎉 شكرًا لاستخدام بوت MOSCOW NAMBER."
    )
    await send_msg(uid, success_text, buttons=kb_main(uid, balance_after))
    try:
        await send_msg(OWNER_ID,
            f"🌟 *شحن نجوم جديد ناجح*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 المستخدم: `{uid}`\n"
            f"💰 المبلغ: `{usd_amount}$` ({stars} 🌟)\n"
            f"🆔 المعاملة: `{charge_id}`\n"
            f"🔗 المصدر: `{source}`"
        )
    except Exception as e:
        logger.error(f"Admin notification failed: {e}")
    return True


async def refund_stars_payment(*args, **kwargs):
    """حاجز أمان: استرداد نجوم تيليجرام ممنوع نهائياً.

    الدالة لا تستدعي Telegram refund API ولا تعيد أي رصيد بعد اعتماد الدفعة.
    وجودها يمنع إضافة مسار استرداد بالخطأ في المستقبل.
    """
    logger.warning("Stars refund blocked: STARS_REFUNDS_ENABLED=%s", STARS_REFUNDS_ENABLED)
    return False


async def on_successful_payment(event):
    """معالج الحدث من NewMessage: الرسالة تحمل successful_payment داخل message payload،
    لكن تيليجرام يضع المبلغ الفعلي في successful_payment.total_amount (بالـ XTR cents = عدد النجوم)."""
    try:
        payment = event.message.successful_payment
        raw_payload = getattr(payment, 'payload', '')
        decoded = stars_payload_decode(raw_payload)
        if decoded is None:
            logger.warning(f"Stars payment rejected: bad payload {raw_payload!r}")
            return
        uid = decoded['uid']
        expected_stars = decoded['stars']
        # المبلغ الفعلي حسب تيليجرام في XTR = عدد النجوم نفسه
        telegram_total = getattr(payment, 'total_amount', None)
        if telegram_total is None or int(telegram_total) != int(expected_stars):
            logger.error(
                f"Stars payment total mismatch: telegram={telegram_total} expected={expected_stars} uid={uid}"
            )
            try:
                await send_msg(OWNER_ID, (
                    f"🚨 *محاولة شحن نجوم مشكوك فيها*\n"
                    f"👤 `{uid}`\n"
                    f"📦 telegram_total: `{telegram_total}`\n"
                    f"📦 expected: `{expected_stars}`\n"
                    f"🆔 payload: `{raw_payload}`"
                ))
            except Exception: pass
            return
        expected_usd = stars_to_usd(expected_stars)             # Decimal بدقة كاملة
        charge_id = str(getattr(payment, 'telegram_payment_charge_id', f"STARS_{uid}_{int(time.time())}"))
        await _finalize_stars_deposit(uid, expected_stars, charge_id, expected_usd, source='message')
    except ValueError as ve:
        logger.error(f"Stars payment validation error: {ve}")
    except Exception as e:
        logger.error(f"Error in on_successful_payment: {e}")

async def handle_deposit_amount(event, user, text, currency):
    try:
        amount = float(text.replace(',', '.'))
    except Exception:
        return await send_msg(event, "مبلغ غير صحيح. أرسل رقم فقط (مثل: 5 أو 10.5)")
    if amount < MIN_DEPOSIT:
        return await send_msg(event, f"المبلغ أقل من الحد الأدنى ({MIN_DEPOSIT}$)")
    if amount > MAX_DEPOSIT:
        return await send_msg(event, f"المبلغ أكبر من الحد الأقصى ({MAX_DEPOSIT}$)")
    rates = await get_crypto_rates()
    rate = rates.get(currency, FALLBACK_RATES[currency])
    amount_crypto = usd_to_crypto(amount, rate)
    deposit_id = _next('next_deposit_id')
    db['deposits'][str(deposit_id)] = {
        'id': deposit_id,
        'user_id': user.id,
        'currency': currency,
        'amount_usd': amount,
        'amount_crypto': amount_crypto,
        'rate': rate,
        'address': WALLETS[currency],
        'status': 'pending',
        'created_at': datetime.now().isoformat(),
        'txid': None
    }
    save_db(db)
    clear_user_state(user.id)
    cur_icon = {"LTC": "🪙", "BTC": "₿", "TON": "💎", "USDT": "💵"}.get(currency, "💠")
    text_msg = (
        f"{cur_icon} *طلب شحن #{deposit_id}* {cur_icon}\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 المبلغ: `{amount}$`\n"
        f"⚡ العملة: *{currency}*\n"
        f"🌐 الشبكة: *{NETWORKS[currency]}*\n"
        f"💱 السعر: `1 {currency} = {rate:.2f}$`\n\n"
        f"📤 *حوّل بالضبط هذا المبلغ:*\n`{amount_crypto} {currency}`\n\n"
        f"📩 *إلى العنوان:*\n`{WALLETS[currency]}`\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ *تنبيهات هامة:*\n"
        "🔐 تأكد من إرسال المبلغ بنفس الشبكة المذكورة\n"
        "🔐 فرق ±5% مقبول (تذبذب الأسعار)\n"
        "🔐 بعد الإرسال، اضغط *إرسال TXID للتحقق*"
    )
    await send_msg(event, text_msg, buttons=kb_after_deposit_create(deposit_id))

async def handle_stars_amount(event, user, text):
    try:
        stars = int(text)
    except Exception:
        return await send_msg(event, "يرجى إرسال عدد صحيح للنجوم.")
    try:
        _ = stars_to_usd(stars)
    except ValueError as ve:
        return await send_msg(event, str(ve))
    clear_user_state(user.id)
    return await on_execute_stars_pay(event, user, stars)

async def handle_stars_usd_amount(event, user, text):
    try:
        usd_dec = Decimal(str(text.replace(',', '.')))
    except (InvalidOperation, ValueError):
        return await send_msg(event, "مبلغ غير صحيح. أرسل رقم فقط (مثال: 5)")
    try:
        stars = usd_to_stars(usd_dec)
    except ValueError as ve:
        return await send_msg(event, str(ve))
    clear_user_state(user.id)
    return await on_execute_stars_pay(event, user, stars)

async def handle_txid_input(event, user, txid, deposit_id):
    uid = user.id
    txid = (txid or "").strip()
    now_ts = time.time()
    if not hasattr(handle_txid_input, '_last_attempt'):
        handle_txid_input._last_attempt = {}
    last_attempt = handle_txid_input._last_attempt.get(uid, 0)
    if now_ts - last_attempt < TXID_ATTEMPT_COOLDOWN:
        wait = int(TXID_ATTEMPT_COOLDOWN - (now_ts - last_attempt))
        return await send_msg(event, f"انتظر {wait} ثانية قبل المحاولة مجدداً.")
    handle_txid_input._last_attempt[uid] = now_ts
    if len(txid) < 8:
        return await send_msg(event,
            "⚠️ *معرف العملية غير صحيح*\n\n"
            "🔐 الـ TXID قصير جداً. أعد إرسال المعرف الكامل.",
        )
    deposit = db['deposits'].get(str(deposit_id))
    if not deposit or str(deposit['user_id']) != str(user.id):
        clear_user_state(user.id)
        return await send_msg(event, "طلب الإيداع غير موجود", buttons=kb_back())
    if deposit['status'] != 'pending':
        clear_user_state(user.id)
        return await send_msg(event, f"هذا الطلب: *{deposit['status']}*", buttons=kb_back())
    if is_txid_used(txid):
        return await send_msg(event,
            "⚠️ *هذا الـ TXID مستخدم مسبقاً!*\n\n"
            "🔐 يبدو أن هذا المعرّف تم استخدامه في عملية أخرى.\n"
            "⚡ تحقق من نسخ المعرّف الصحيح وأعد المحاولة، أو اضغط إلغاء."
        )
    msg = await send_msg(event, "*جاري التحقق من المعاملة على الشبكة...*\n\nيستغرق هذا 10-30 ثانية، يرجى الانتظار...")
    currency = deposit['currency']
    expected_addr = deposit['address']
    expected_amount = deposit['amount_crypto']
    try:
        ok, amount_crypto, info_msg = await verify_transaction(currency, txid, expected_addr)
    except Exception as e:
        ok, amount_crypto, info_msg = False, 0, f"خطأ: {e}"
    if not ok:
        clear_user_state(user.id)
        await safe_edit(msg,
            "⚠️ *معرّف العملية غير صحيح* ⚠️\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔻 السبب: _{info_msg}_\n\n"
            "🔐 تحقق من نسخ TXID بشكل صحيح من محفظتك،\n"
            "⚡ وتأكد أنك أرسلت على الشبكة الصحيحة وللعنوان الصحيح.\n\n"
            "💡 يمكنك المحاولة مجدداً من قائمة الشحن.",
            buttons=[
                [Button.inline("إعادة المحاولة", f"submit_tx:{deposit_id}".encode())],
                [Button.inline("القائمة الرئيسية", b"back_main")],
            ]
        )
        return
    rates = await get_crypto_rates()
    rate = rates.get(currency, deposit['rate'])
    amount_usd = round(amount_crypto * rate, 2)
    expected_usd = deposit['amount_usd']
    diff_ratio = abs(amount_usd - expected_usd) / expected_usd if expected_usd > 0 else 1
    if diff_ratio > AMOUNT_TOLERANCE:
        await safe_edit(msg,
            f"⚠️ *تم العثور على المعاملة لكن المبلغ مختلف*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💰 المبلغ المتوقع: `{expected_usd}$`\n"
            f"💵 المبلغ الفعلي: `{amount_usd}$`\n"
            f"🔻 الفرق: `{diff_ratio*100:.1f}%`\n\n"
            "🔄 *تم إرسال الطلب للأدمن للمراجعة.*",
            buttons=kb_back()
        )
        async with _PURCHASE_FLOW_LOCK:
            if is_txid_used(txid):
                clear_user_state(user.id)
                return await safe_edit(msg, "❌ هذا TXID استُخدم للتو ولا يمكن اعتماده مرة أخرى.", buttons=kb_back())
            tx_id = _next('next_tx_id')
            db['transactions'].append({
                'id': tx_id, 'user_id': user.id, 'currency': currency,
                'txid': txid, 'amount_usd': amount_usd, 'amount_crypto': amount_crypto,
                'status': 'pending_manual', 'deposit_id': deposit_id,
                'created_at': datetime.now().isoformat(),
                'error': f"المبلغ مختلف: متوقع {expected_usd}$ فعلي {amount_usd}$"
            })
            deposit['status'] = 'pending_manual'
            deposit['txid'] = txid
            save_db(db)
        try:
            kb = [[
                Button.inline("موافقة بالمبلغ الفعلي", f"admin_mr:approve:{tx_id}".encode()),
                Button.inline("رفض", f"admin_mr:reject:{tx_id}".encode())
            ]]
            await send_msg(OWNER_ID,
                f"⚠️ *المبلغ مختلف عن المتوقع*\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"👤 `{user.id}` (@{user.username or 'لا يوجد'})\n"
                f"⚡ العملة: {currency}\n"
                f"💰 متوقع: `{expected_usd}$`\n"
                f"💵 فعلي: `{amount_usd}$` ({amount_crypto} {currency})\n"
                f"🔑 TXID: `{txid}`",
                buttons=kb
            )
        except Exception:
            pass
        clear_user_state(user.id)
        return
    async with _PURCHASE_FLOW_LOCK:
        if is_txid_used(txid):
            clear_user_state(user.id)
            return await safe_edit(msg, "❌ هذا TXID استُخدم للتو ولا يمكن اعتماده مرة أخرى.", buttons=kb_back())
        tx_id = _next('next_tx_id')
        db['transactions'].append({
            'id': tx_id, 'user_id': user.id, 'currency': currency,
            'txid': txid, 'amount_usd': amount_usd, 'amount_crypto': amount_crypto,
            'status': 'completed', 'deposit_id': deposit_id,
            'created_at': datetime.now().isoformat()
        })
        deposit['status'] = 'completed'
        deposit['txid'] = txid
        mark_txid_used(txid)
        save_db(db)
    balance_before = get_balance(user.id)
    update_balance(user.id, amount_usd)
    balance_after = get_balance(user.id)
    clear_user_state(user.id)
    cur_icon = {"LTC": "🪙", "BTC": "₿", "TON": "💎", "USDT": "💵"}.get(currency, "💠")
    await safe_edit(msg,
        "✅ *تمت الموافقة على شحن CRYPTO*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{cur_icon} العملة: *{currency}*\n"
        f"💰 المبلغ المضاف: `{amount_usd:.2f}$`\n"
        f"📦 ({amount_crypto} {currency})\n"
        f"📉 رصيدك قبل: `{balance_before:.2f}$`\n"
        f"📈 رصيدك بعد: `{balance_after:.2f}$`\n"
        f"📡 الحالة: {info_msg}\n"
        f"🔑 TXID: `{txid[:25]}...`\n\n"
        "🎉 شكرًا لاستخدام بوت MOSCOW NAMBER.",
        buttons=kb_back()
    )
    try:
        await send_msg(OWNER_ID,
            f"💠 *شحن جديد ناجح*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 `{user.id}` (@{user.username or 'لا يوجد'})\n"
            f"{cur_icon} {currency} — `{amount_usd:.2f}$`\n"
            f"📦 {amount_crypto} {currency}\n"
            f"🔑 `{txid}`"
        )
    except Exception:
        pass

async def handle_manual_amount(event, user, text, method):
    try:
        amount = float(text.replace(',', '.'))
    except Exception:
        return await send_msg(event, "مبلغ غير صحيح. أرسل رقم فقط.")
    if amount < MIN_DEPOSIT or amount > MAX_DEPOSIT:
        return await send_msg(event, f"المبلغ خارج النطاق ({MIN_BINANCE_DEPOSIT:.2f}$ - {MAX_DEPOSIT:.2f}$)")
    set_user_state(user.id, 'manual_proof', method=method, amount=amount)
    await send_msg(event,
        f"✅ المبلغ: `{amount}$`\n\n"
        "📸 *الآن أرسل صورة إثبات الدفع (لقطة شاشة):*",
        buttons=kb_cancel()
    )

async def handle_manual_proof(event, user, method, amount):
    if amount < MIN_DEPOSIT or amount > MAX_DEPOSIT:
        clear_user_state(user.id)
        return await send_msg(event,
            f"⚠️ المبلغ `{amount}$` خارج النطاق المسموح ({MIN_BINANCE_DEPOSIT:.2f}$ - {MAX_DEPOSIT:.2f}$)\n"
            "🔙 يرجى إعادة الشحن بمبلغ ضمن النطاق.",
            buttons=kb_back()
        )
    req_id = _next('next_manual_id')
    photo_id = None
    if event.message.photo:
        photo_id = event.message.photo.id
    elif event.message.document:
        photo_id = event.message.document.id
    req = {
        'id': req_id,
        'user_id': user.id,
        'method': method,
        'amount': amount,
        'message_id': event.message.id,
        'chat_id': event.chat_id,
        'status': 'pending',
        'photo_id': photo_id,
        'created_at': datetime.now().isoformat()
    }
    db.setdefault('manual_requests', []).append(req)
    save_db(db)
    clear_user_state(user.id)
    await send_msg(event,
        f"✅ *تم إرسال طلبك #{req_id}* للأدمن للمراجعة.\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💳 الطريقة: *{method}*\n"
        f"💰 المبلغ: `{amount}$`\n\n"
        "⏳ سيتم إضافة الرصيد بعد الموافقة (خلال 24 ساعة عادةً).",
        buttons=kb_back()
    )
    try:
        kb = [[
            Button.inline("موافقة بالمبلغ المطلوب", f"admin_mr:mp_approve:{req_id}".encode()),
            Button.inline("موافقة بمبلغ مختلف", f"admin_mr:mp_confirm_amount:{req_id}".encode()),
            Button.inline("رفض", f"admin_mr:mp_reject:{req_id}".encode())
        ]]
        caption = (
            f"💼 *طلب دفع يدوي #{req_id}* 🛡️\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 المستخدم: `{user.id}` (@{user.username or 'لا يوجد'})\n"
            f"💳 الطريقة: *{method}*\n"
            f"💰 المبلغ المطلوب من المستخدم: `{amount}$`\n\n"
            "📸 إثبات الدفع مرفق ⬇️\n\n"
            "⚠️ *تنبيه:* تحقق من المبلغ في الصورة قبل الموافقة!\n"
            "✅ *موافقة بالمبلغ المطلوب* = المطابقة 100%\n"
            "✏️ *تأكيد بمبلغ آخر* = إذا الصورة فيها مبلغ مختلف\n"
            "🚫 *رفض بدون حظر* = رفض الطلب فقط (الحظر التلقائي معطّل)"
        )
        await bot.forward_messages(OWNER_ID, event.message)
        await send_msg(OWNER_ID, caption, buttons=kb)
    except Exception as e:
        logger.error(f"manual proof admin notify failed: {e}")

async def handle_restore_zip(event, user):
    uid = user.id
    clear_user_state(uid)
    if not event.message.document:
        return await send_msg(event, "يرجى إرسال ملف ZIP صالح.", buttons=kb_admin_back())
    document = event.message.document
    if document.mime_type != "application/zip":
        return await send_msg(event, "الملف المرسل ليس ملف ZIP.", buttons=kb_admin_back())
    if document.size > 1000 * 1024 * 1024:
        return await send_msg(event, "حجم الملف يتجاوز الحد الأقصى المسموح به (1000 ميجابايت).", buttons=kb_admin_back())
    try:
        await send_msg(event, "جاري تنزيل ملف النسخة الاحتياطية واستعادته... قد يستغرق هذا بعض الوقت.")
        zip_path = f"restore_{uid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        await event.message.download_media(file=zip_path)
        extract_dir = f"restore_extract_{uid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        extracted_db_path = os.path.join(extract_dir, DB_FILE)
        if os.path.exists(extracted_db_path):
            shutil.copy(extracted_db_path, DB_FILE)
            global db
            db = load_db()
            logger.info(f"DB_FILE restored from {extracted_db_path}")
        else:
            await send_msg(event, "لم يتم العثور على ملف قاعدة البيانات (sliner_numbers_db.json) في الأرشيف.")
        extracted_sessions_dir = os.path.join(extract_dir, SESSIONS_DIR)
        if os.path.exists(extracted_sessions_dir) and os.path.isdir(extracted_sessions_dir):
            if os.path.exists(SESSIONS_DIR):
                shutil.rmtree(SESSIONS_DIR)
            shutil.copytree(extracted_sessions_dir, SESSIONS_DIR)
            logger.info(f"Sessions directory restored from {extracted_sessions_dir}")
        else:
            await send_msg(event, "لم يتم العثور على مجلد الجلسات (numbers_sessions) في الأرشيف.")
        await send_msg(event, "تم استعادة البيانات بنجاح! يرجى إعادة تشغيل البوت لتطبيق التغييرات.", buttons=kb_admin_back())
    except Exception as e:
        logger.error(f"خطأ أثناء استعادة ملف ZIP: {e}")
        await send_msg(event, f"حدث خطأ أثناء استعادة البيانات: {e}", buttons=kb_admin_back())
    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir)

def _safe_extract_zip(zip_path, extract_dir):
    """استخراج ZIP بأمان ومنع المسارات الخارجة عن مجلد الاستخراج."""
    target_dir = os.path.realpath(extract_dir)
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        for member in zip_ref.infolist():
            member_path = os.path.realpath(os.path.join(extract_dir, member.filename))
            if member_path != target_dir and not member_path.startswith(target_dir + os.sep):
                raise ValueError(f"مسار غير آمن داخل ZIP: {member.filename}")
        zip_ref.extractall(extract_dir)


async def process_uploaded_sessions_zip(zip_path, merge_as_mixed=False, custom_price=None, is_fake=False, is_spam_mix=False, is_unverified=False, is_old=False, is_old_spam=False, custom_label=None, old_year=None, is_monthly=False, is_daily_special=False, is_bimonthly=False, is_random_special=False, custom_country_code=None):
    global MIXED_PRICE
    extract_dir = f"session_extract_{int(time.time())}_{random.randint(1000, 9999)}"
    os.makedirs(extract_dir, exist_ok=True)
    added = 0
    duplicates = 0
    failed = 0
    errors = []
    try:
        _safe_extract_zip(zip_path, extract_dir)
        files_by_phone = {}
        for root, _, files in os.walk(extract_dir):
            for f in files:
                base, ext = os.path.splitext(f)
                ext = ext.lower()
                if ext not in ('.json', '.session'):
                    continue
                # يقبل: +201285175788.session أو 201285175788.session.
                base = base.strip()
                if not base:
                    continue
                if base not in files_by_phone:
                    files_by_phone[base] = {}
                files_by_phone[base][ext] = os.path.join(root, f)
        for phone, paths in files_by_phone.items():
            json_path = paths.get('.json')
            session_path = paths.get('.session')
            session_str = None
            if json_path:
                try:
                    with open(json_path, 'r', encoding='utf-8') as f:
                        json_data = json.load(f)
                    session_str = json_data.get('session_str') or json_data.get('session')
                    api_id = json_data.get('app_id', API_ID)
                    api_hash = json_data.get('app_hash', API_HASH)
                    device_model = json_data.get('device_model') or json_data.get('device', "iPhone 14 Pro")
                    system_version = json_data.get('sdk', "iOS 17.0")
                    password_2fa = json_data.get('twoFA') or json_data.get('2fa') or json_data.get('2FA') or json_data.get('password')
                    raw_phone = json_data.get('phone', phone)
                except Exception as e:
                    errors.append(f"{phone}: فشل قراءة JSON - {e}")
                    failed += 1
                    continue
            else:
                api_id = API_ID
                api_hash = API_HASH
                device_model = "iPhone 14 Pro"
                system_version = "iOS 17.0"
                password_2fa = None
                raw_phone = phone

            if not session_str and session_path and os.path.exists(session_path):
                try:
                    client = TelegramClient(session_path, api_id, api_hash)
                    await client.connect()
                    if await client.is_user_authorized():
                        session_str = StringSession.save(client.session)
                        me = await client.get_me()
                        if me and me.phone:
                            raw_phone = me.phone
                        await client.disconnect()
                    else:
                        await client.disconnect()
                        errors.append(f"{phone}: ملف الجلسة .session غير صالح (غير مصرح)")
                        failed += 1
                        continue
                except Exception as e:
                    errors.append(f"{phone}: فشل قراءة ملف الجلسة .session - {e}")
                    failed += 1
                    continue

            if not session_str:
                errors.append(f"{phone}: لا يوجد session_str في JSON ولا ملف .session صالح")
                failed += 1
                continue

            if not str(raw_phone).startswith('+'):
                raw_phone = '+' + str(raw_phone).lstrip('+')

            is_valid, phone_or_error, _ = await validate_session(
                session_str, api_id, api_hash, device_model, system_version
            )
            if not is_valid:
                failed += 1
                errors.append(f"{phone}: {phone_or_error}")
                continue

            if phone_or_error and phone_or_error.startswith('+'):
                raw_phone = phone_or_error

            incoming_category = (
                'old_spam' if is_old_spam else
                'old' if is_old else
                'fake' if is_fake else
                'unverified' if is_unverified else
                'monthly' if is_monthly else
                'daily' if is_daily_special else
                'random' if is_random_special else
                'bimonthly' if is_bimonthly else
                'spam_mix' if is_spam_mix else
                'spam' if merge_as_mixed else
                'clean'
            )
            if is_old_spam:
                detected_code, detected_name = detect_country(raw_phone)
                if not detected_code:
                    failed += 1
                    errors.append(f"{phone}: لم يتم التعرف على دولة الرقم الاسبام القديم")
                    continue
                country_code = f"{OLD_SPAM_CODE}_{detected_code}"
                country_label = f"{detected_name} 📛"
            elif is_bimonthly:
                country_code, country_label = BIMONTHLY_NUMBERS_CODE, BIMONTHLY_NUMBERS_LABEL
            elif is_monthly:
                country_code, country_label = MONTHLY_NUMBERS_CODE, MONTHLY_NUMBERS_LABEL
            elif custom_label and custom_country_code:
                country_code, country_label = str(custom_country_code), str(custom_label)
            elif custom_label:
                # تجميع الجلسات المرفوعة في زر/دولة مخصصة يحددها الأدمن.
                if custom_label == USA_CLEAN_LABEL and not raw_phone.lstrip('+').startswith('1'):
                    failed += 1
                    errors.append(f"{phone}: زر أمريكا مخصص للأرقام التي تبدأ بـ +1 فقط")
                    continue
                country_code = USA_CLEAN_CODE if custom_label == USA_CLEAN_LABEL else ('custom_' + hashlib.sha1(custom_label.encode('utf-8')).hexdigest()[:12])
                country_label = custom_label
            elif is_old:
                detected_code, detected_name = detect_country(raw_phone)
                if not detected_code:
                    failed += 1
                    errors.append(f"{phone}: لم يتم التعرف على دولة الرقم القديم")
                    continue
                country_code = f"old_{detected_code}_{old_year or 'unknown'}"
                country_label = f"{detected_name} {old_year}" if old_year else f"{detected_name} قديم"
            elif is_fake:
                country_code, country_label = 'fake', FAKE_LABEL
            elif is_unverified:
                country_code, country_label = UNVERIFIED_CODE, UNVERIFIED_LABEL
            elif is_spam_mix:
                # سبام Mix هو زر موحّد: لا نقسم الملف حسب الدولة.
                # كل أرقام ZIP، مهما اختلفت دولها، تحفظ تحت نفس الكود والاسم.
                country_code, country_label = SPAM_MIX_CODE, SPAM_MIX_LABEL
            else:
                country_code, country_label = detect_country(raw_phone)
                
            if not country_code:
                failed += 1
                errors.append(f"{phone}: لم يتم التعرف على دولة الرقم {raw_phone}")
                continue

            if is_old_spam:
                country_name = country_label
                price = custom_price if custom_price is not None else OLD_SPAM_PRICE
                db['countries'][country_code] = {'name': country_name, 'price': price}
            elif is_bimonthly:
                country_name = BIMONTHLY_NUMBERS_LABEL
                price = custom_price if custom_price is not None else BIMONTHLY_NUMBERS_PRICE
                db['countries'][BIMONTHLY_NUMBERS_CODE] = {'name': country_name, 'price': price}
            elif is_monthly:
                country_name = MONTHLY_NUMBERS_LABEL
                price = custom_price if custom_price is not None else MONTHLY_NUMBERS_PRICE
                db['countries'][MONTHLY_NUMBERS_CODE] = {'name': country_name, 'price': price}
            elif custom_label:
                country_name = custom_label
                price = custom_price if custom_price is not None else DEFAULT_ACCOUNT_PRICE
                db['countries'][country_code] = {'name': country_name, 'price': price}
            elif is_old:
                country_name = country_label
                price = custom_price if custom_price is not None else OLD_NUMBERS_PRICE
                db['countries'][country_code] = {'name': country_name, 'price': price}
            elif is_unverified:
                country_name = UNVERIFIED_LABEL
                price = custom_price if custom_price is not None else UNVERIFIED_PRICE
                db['countries'][UNVERIFIED_CODE] = {'name': country_name, 'price': price}
            elif is_fake:
                country_name = FAKE_LABEL
                price = custom_price if custom_price is not None else FAKE_PRICE
                if 'fake' not in db['countries']:
                    db['countries']['fake'] = {'name': FAKE_LABEL, 'price': price}
                else:
                    db['countries']['fake']['price'] = price
            elif is_spam_mix:
                country_name = SPAM_MIX_LABEL
                price = custom_price if custom_price is not None else MIXED_PRICE
                db['countries'][country_code] = {'name': country_name, 'price': price}
            elif merge_as_mixed:
                country_name = MIXED_LABEL
                # إذا تم إدخال سعر مخصص نحدث سعر المخطلت، وإلا نستخدم السعر الحالي المسجل
                if custom_price is not None:
                    price = custom_price
                    MIXED_PRICE = price # تحديث المتغير العام في الجلسة الحالية
                    # تحديث السعر في إعدادات قاعدة البيانات إذا كان متاحاً
                    if 'settings' in db:
                        db['settings']['mixed_price'] = price
                else:
                    price = MIXED_PRICE

                if country_code not in db['countries']:
                    db['countries'][country_code] = {'name': country_name, 'price': price}
                else:
                    db['countries'][country_code]['price'] = price
            else:
                # منطق السعر الدائم للدولة
                if country_code in db['countries']:
                    # إذا كانت الدولة موجودة مسبقاً
                    if custom_price is not None:
                        # إذا أدخل الأدمن سعراً جديداً، نقوم بتحديث سعر الدولة الدائم
                        price = custom_price
                        db['countries'][country_code]['price'] = price
                    else:
                        # إذا لم يدخل سعراً، نستخدم السعر المسجل مسبقاً لهذه الدولة
                        price = db['countries'][country_code]['price']
                else:
                    # إذا كانت دولة جديدة تماماً
                    price = custom_price if custom_price is not None else DEFAULT_ACCOUNT_PRICE
                    db['countries'][country_code] = {
                        'name': country_label or f"دولة ({country_code})",
                        'price': price
                    }
                
                country_name = db['countries'][country_code]['name']

            existing = [a for a in db.get('accounts', []) if a.get('phone') == raw_phone]
            if existing:
                # نقل الرقم بالكامل إلى التصنيف والزر الجديدين دون إنشاء نسخة مكررة.
                for old_account in existing:
                    set_account_purchase_category(old_account, incoming_category)
                    old_account['country_code'] = country_code
                    old_account['country_name'] = country_name
                    old_account['price'] = price
                    old_account['is_usa_clean'] = custom_label == USA_CLEAN_LABEL
                save_db(db)
                duplicates += 1
                errors.append(f"{phone}: موجود مسبقاً — تم تحديث الزر إلى {country_name}")
                continue

            acc_id = _next('next_account_id')
            purchase_category = (
                'old_spam' if is_old_spam else
                'old' if is_old else
                'fake' if is_fake else
                'unverified' if is_unverified else
                'monthly' if is_monthly else
                'daily' if is_daily_special else
                'random' if is_random_special else
                'bimonthly' if is_bimonthly else
                'spam_mix' if is_spam_mix else
                'spam' if merge_as_mixed else
                'clean'
            )
            db['accounts'].append({
                'id': acc_id,
                'phone': raw_phone,
                'session': session_str,
                'country_code': country_code,
                'country_name': country_name,
                'price': price,
                'status': 'available',
                'password': password_2fa,
                'added_at': datetime.now().isoformat(),
                'is_spam': merge_as_mixed,  # وضع علامة سبام عند الدمج
                'is_spam_mix': is_spam_mix,
                'is_fake': is_fake,
                'is_unverified': is_unverified,
                'is_usa_clean': custom_label == USA_CLEAN_LABEL,
                'is_old': is_old,
                'is_old_spam': is_old_spam,
                'is_monthly': is_monthly,
                'is_daily_special': is_daily_special,
                'is_bimonthly': is_bimonthly,
                'is_random_special': is_random_special,
                'purchase_category': purchase_category
            })
            save_session_to_disk(raw_phone, session_str)
            save_db(db)
            added += 1
            logger.info(f"✅ تم إضافة الرقم {raw_phone} (ID: {acc_id})")
    except Exception as e:
        logger.error(f"خطأ في معالجة ZIP: {e}")
        errors.append(f"خطأ عام: {e}")
    finally:
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir, ignore_errors=True)
        if os.path.exists(zip_path):
            os.remove(zip_path)
    return added, duplicates, failed, errors

async def validate_session(session_str, api_id, api_hash, device_model="iPhone 14 Pro", system_version="iOS 17.0", retries=3):
    last_error = None
    for attempt in range(retries):
        client = None
        try:
            client = TelegramClient(
                StringSession(session_str),
                api_id,
                api_hash,
                device_model=device_model,
                system_version=system_version,
                app_version="10.0",
                lang_code="en"
            )
            await client.connect()
            if not await client.is_user_authorized():
                return False, "الجلسة غير مصرح بها (انتهت صلاحيتها)", None
            me = await client.get_me()
            phone = getattr(me, 'phone', '')
            if not phone:
                return False, "لم يتم العثور على رقم هاتف في الجلسة", None
            return True, phone, client
        except AuthKeyUnregisteredError:
            return False, "مفتاح الجلسة غير مسجل (منتهي الصلاحية)", None
        except SessionPasswordNeededError:
            return False, "تتطلب الجلسة كلمة مرور 2FA", None
        except FloodWaitError as e:
            wait_time = e.seconds
            if attempt < retries - 1 and wait_time < 10:
                await asyncio.sleep(wait_time + 1)
                continue
            return False, f"Flood wait: {wait_time} ثانية", None
        except (RPCError, ConnectionError, TimeoutError) as e:
            last_error = str(e)
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            return False, f"خطأ في الاتصال: {e}", None
        except Exception as e:
            last_error = str(e)
            if attempt < retries - 1:
                await asyncio.sleep(2)
                continue
            return False, f"خطأ: {e}", None
        finally:
            if client and client.is_connected():
                try:
                    await client.disconnect()
                except Exception:
                    pass
    return False, f"فشل بعد {retries} محاولات: {last_error}", None

async def fetch_login_code(session_string, password=None, retries=5, delay=3):
    last_err = None
    for attempt in range(retries):
        client = None
        try:
            client = TelegramClient(
                StringSession(session_string),
                API_ID,
                API_HASH,
                device_model="iPhone 14 Pro",
                system_version="iOS 17.0",
                app_version="10.0",
                lang_code="en"
            )
            await client.connect()
            authorized = await client.is_user_authorized()
            logger.warning(
                "CODE_FETCH_SESSION_CHECK attempt=%s authorized=%s connected=%s",
                attempt + 1,
                authorized,
                client.is_connected(),
            )
            if not authorized:
                # جلسة Telegram نفسها غير مصرح بها، وليست مشكلة تأخر عابرة.
                last_err = "جلسة Telegram غير مصرح بها أو تم إلغاؤها"
                if attempt < retries - 1:
                    await asyncio.sleep(delay * (attempt + 1))
                    continue
                return False, None, (
                    "جلسة الرقم غير مصرح بها أو انتهت صلاحيتها. "
                    "يجب إعادة تفعيل الرقم/إنشاء جلسة جديدة؛ لا يمكن قراءة كود جديد من الجلسة الحالية."
                )
            async for msg in client.iter_messages(777000, limit=5):
                if msg.text:
                    text = msg.text
                    patterns = [
                        r'Login code[:\s]+([0-9]{5,7})',
                        r'code is[:\s]+([0-9]{5,7})',
                        r'كود[:\s]+([0-9]{5,7})',
                        r'start=([0-9a-zA-Z]{5,20})',
                        r'\b([0-9]{5,7})\b',
                    ]
                    for p in patterns:
                        m = re.search(p, text, re.IGNORECASE)
                        if m:
                            return True, m.group(1), text
            return False, None, "لم يتم العثور على كود في الرسائل الأخيرة"
        except SessionPasswordNeededError:
            if password:
                try:
                    await client.sign_in(password=password)
                    async for msg in client.iter_messages(777000, limit=5):
                        if msg.text:
                            text = msg.text
                            patterns = [
                                r'Login code[:\s]+([0-9]{5,7})',
                                r'code is[:\s]+([0-9]{5,7})',
                                r'كود[:\s]+([0-9]{5,7})',
                                r'start=([0-9a-zA-Z]{5,20})',
                                r'\b([0-9]{5,7})\b',
                            ]
                            for p in patterns:
                                m = re.search(p, text, re.IGNORECASE)
                                if m:
                                    return True, m.group(1), text
                    return False, None, "تم تسجيل الدخول ولكن لم نجد الكود"
                except Exception as e:
                    return False, None, f"خطأ في كلمة المرور: {e}"
            else:
                return False, None, "تتطلب الجلسة كلمة مرور 2FA"
        except AuthKeyUnregisteredError:
            return False, None, "مفتاح الجلسة غير مسجل (منتهي الصلاحية)"
        except FloodWaitError as e:
            wait_time = e.seconds
            if attempt < retries - 1 and wait_time < 10:
                await asyncio.sleep(wait_time + 1)
                continue
            return False, None, f"Flood wait: {wait_time} ثانية"
        except (RPCError, ConnectionError, TimeoutError) as e:
            last_err = str(e)
            if attempt < retries - 1:
                await asyncio.sleep(delay * (attempt + 1))
                continue
            return False, None, f"خطأ في الاتصال: {e}"
        except Exception as e:
            last_err = str(e)
            if attempt < retries - 1:
                await asyncio.sleep(delay)
                continue
            return False, None, f"خطأ: {e}"
        finally:
            if client and client.is_connected():
                try:
                    await client.disconnect()
                except Exception:
                    pass
    return False, None, f"فشل بعد {retries} محاولات: {last_err}"


async def refund_invalid_session_purchase(purchase, reason):
    """إرجاع سعر الرقم التالف إلى رصيد المستخدم مرة واحدة فقط.

    هذا استرداد رصيد داخلي خاص بشراء الرقم، وليس استرداداً لنجوم تيليجرام.
    يُسمح به فقط عندما يثبت فشل الجلسة في أول محاولة تفعيل.
    """
    if purchase.get('refunded_at'):
        return False, float(purchase.get('refunded_amount', purchase.get('price', 0)) or 0)

    async with _PURCHASE_FLOW_LOCK:
        # إعادة الفحص بعد القفل تمنع الاسترداد المزدوج عند ضغط الزر بالتزامن.
        if purchase.get('refunded_at'):
            return False, float(purchase.get('refunded_amount', purchase.get('price', 0)) or 0)
        try:
            amount = round(float(purchase.get('price', 0) or 0), 4)
        except (TypeError, ValueError):
            amount = 0.0
        if amount <= 0:
            return False, 0.0

        update_balance(purchase['user_id'], amount)
        purchase['refunded_at'] = datetime.now().isoformat()
        purchase['refunded_amount'] = amount
        purchase['refund_type'] = 'internal_balance_invalid_number'
        purchase['refund_currency'] = 'USD_BALANCE'
        purchase['balance_refunded'] = True
        purchase['refund_reason'] = reason
        purchase['status'] = 'refunded_invalid_session'
        save_db(db)
        return True, amount

# ================================
#  دوال الكولباك (المكتملة مع تعديلات السبام)
# ================================
active_sessions = {}
_last_txid_attempt = {}

@bot.on(events.CallbackQuery())
async def callback_router(event):
    user = await event.get_sender()
    if not user:
        return
    uid = user.id
    ensure_user_by_id(uid)
    data = event.data.decode('utf-8', errors='ignore') if event.data else ""

    # مهم: لا نؤكد Callback الخاص بتأكيد الشراء هنا، لأن on_execute_buy
    # يحتاج أن يرسل Popup (alert=True) بنفس الـ CallbackQuery عند نقص الرصيد.
    # باقي الأزرار يتم تأكيدها كالمعتاد لتجنب بقاء مؤشر التحميل.
    if not data.startswith("confirm_buy:"):
        try:
            await event.answer()
        except Exception:
            pass

    if data == "noop":
        await event.answer()
        return

    if data == "show_main_after_sub":
        udata = db['users'].get(str(uid), {})
        if not udata.get('verified'):
            return await send_captcha(event, uid)
        else:
            return await show_main_menu(event, user)

    # Removed broken block

    # معالجة اختيار سبام / عادي
    if data.startswith("add:"):
        return await handle_add_spam_choice(event, data)

    if db['settings'].get('maintenance') and not is_admin(uid):
        maintenance_text = "🛠️*البوت قيد الصيانة حالياً، يرجى المحاولة بعد قليل* ⏳"
        maintenance_url = "https://files.manuscdn.com/user_upload_by_module/session_file/310519663840780493/HOufoQXFdqLnjAux.png"
        try:
            plain_text, entities = _merge_entities_with_custom_emojis(bot, maintenance_text, 'md')
            await event.edit(
                file=maintenance_url,
                text=plain_text,
                formatting_entities=entities if entities else None
            )
        except:
            await event.edit(
                file=maintenance_url,
                text=maintenance_text,
                parse_mode='md'
            )
        return

    if db['users'].get(str(uid), {}).get('banned'):
        await event.answer("محظور", alert=True)
        return

    # التحقق من الحظر المؤقت (عقاب التلاعب بالشحن)
    if not is_admin(uid) and is_temp_banned(uid):
        remaining = get_temp_ban_remaining(uid)
        remaining_text = format_ban_time(remaining)
        await event.answer(f"محظور مؤقتاً ({remaining_text}). انتظر حتى ينتهي الحظر.", alert=True)
        return

    if data.startswith("captcha_ans:"):
        ans = data.split(":")[1]
        saved = db['captcha'].get(str(uid))
        if isinstance(saved, dict) and ans == saved.get('code'):
            db['users'][str(uid)]['verified'] = True
            await _process_pending_referral(uid)
            save_db(db)
            update_user_cache(uid)
            clear_user_state(uid)
            await event.answer("تم التحقق بنجاح", alert=True)
            try: await event.delete()
            except: pass
            user = await event.get_sender()
            return await show_main_menu(event, user)
        else:
            await event.answer("اختيار خاطئ، حاول مرة أخرى", alert=True)
            return await send_captcha(event, uid)

    if data == "start_registration":
        await event.answer()
        not_subbed = await check_subscription(uid)
        if not_subbed:
            return await safe_edit(event,
                "⚠️ *الاشتراك الإجباري* ⚠️\n━━━━━━━━━━━━━━━━━━━━\n\n"
                "🔐 يجب الاشتراك في القنوات التالية:",
                buttons=kb_force_sub(not_subbed)
            )
        user = await event.get_sender()
        return await show_main_menu(event, user)

    if data == "login_account":
        await event.answer()
        await send_msg(event, "يرجى إرسال اسم المستخدم الخاص بك:")
        set_user_state(uid, "awaiting_login_username")
        return

    if data == "verify_captcha":
        return await on_verify_captcha(event, uid)
    if data == "check_sub":
        return await on_check_sub(event, uid)
    if data == "change_lang":
        await event.answer()
        return await send_msg(event, 
            "🌐 اختر اللغة التي تفضل استخدامها\nChoose your language\nزبان خود را انتخاب کنید\n请选择您的语言",
            buttons=kb_lang_select())
    if data == "transfer_closed":
        lang = get_user_lang(uid)
        msg = "⚠️ عذراً، خدمة تحويل الرصيد مقفلة مؤقتاً." if lang == 'ar' else "⚠️ Sorry, balance transfer is temporarily closed."
        return await event.answer(msg, alert=True)
    if data.startswith("lang:"):
        lang = data.split(":", 1)[1]
        if lang in ("ar", "en", "fa", "zh"):
            set_user_lang(uid, lang)
            confirmation = {
                "ar": "تم تغيير اللغة بنجاح",
                "en": "Language changed successfully",
                "fa": "زبان با موفقیت تغییر کرد",
                "zh": "语言已成功更改",
            }
            await event.answer(confirmation[lang])
            try:
                await event.delete()
            except Exception:
                pass
            return await show_main_menu(event, user)
        return await event.answer()

    if data == "referral_menu":
        # رابط الدعوة لا يحتاج إلى إكمال CAPTCHA حتى يستطيع المستخدم نسخه ومشاركته.
        return await show_referral_menu(event, uid)

    if data == "pub:broadcast":
        # زر إذاعة للقنوات — يعرض قائمة بأزرار منفصلة لكل نوع حسابات متوفر
        await event.answer()
        return await send_broadcast_ad(event, uid)

    if data.startswith("pub:broadcast:"):
        kind = data.split(":", 2)[-1]
        await event.answer()
        if kind == "usa":
            return await publish_broadcast_for_type(event, uid, 'usa')
        if kind == "fake":
            return await publish_broadcast_for_type(event, uid, 'fake')
        if kind == "mixed":
            return await publish_broadcast_for_type(event, uid, 'mixed')
        if kind == "normal":
            return await publish_broadcast_for_type(event, uid, 'normal')
        if kind == "back":
            return await broadcast_back(event, uid)
        await event.answer("⚠️ خيار غير معروف.", alert=True)
        return await send_broadcast_ad(event, uid)

    if not is_admin(uid) and not db['users'].get(str(uid), {}).get('verified'):
        await event.answer("يجب التحقق أولاً، اضغط /start", alert=True)
        return

    if data == "back_main":
        clear_user_state(uid)
        await event.answer()
        return await show_main_menu(event, user)

    if data == "change_currency":
        return await ask_currency(event, uid)

    if data.startswith("set_currency:"):
        currency = data.split(":")[1]
        db['users'][str(uid)]['currency'] = currency
        save_db(db)
        update_user_cache(uid)
        await event.answer(f"تم تغيير العملة إلى {currency} بنجاح", alert=True)
        user = await event.get_sender()
        return await show_main_menu(event, user)

    if data == "transfer_start":
        balance = get_balance(uid)
        text = (
            "🔄 *تحويل رصيد لـ مستخدم آخر :*\n\n"
            f"💰 رصيدك الحالي: `{fmt_amt(balance, uid)}`\n\n"
            "⚠️ *تنبيهات مهمة:*\n"
            f"• الحد الأدنى للتحويل: `{fmt_amt(0.1, uid)}` وسيتم خصم `{fmt_amt(0.03, uid)}` عمولة البوت .\n"
            "• لا يمكن استرداد المبلغ بعد التحويل\n\n"
            "✏️ *أرسل الآن معرف أو يوزر المستلم:*"
        )
        set_user_state(uid, "awaiting_transfer_user")
        await event.answer()
        return await safe_edit(event, text, buttons=[[Button.inline("رجوع", b"back_main")]])
    if data == "my_balance":
        return await on_my_balance(event, user)
    if data == "my_purchases":
        return await on_my_purchases(event, user)
    if data == "info":
        return await on_info(event)
    if data == "daily_gift":
        return await on_daily_gift(event, user)
    if data == "rules":
        return await on_rules(event)
    if data == "developer_page":
        return await on_developer_page(event)

    if data == "logout_request":
        udata = db['users'].get(str(uid), {})
        udata['registered'] = False
        save_db(db)
        update_user_cache(uid)
        await event.answer("تم تسجيل الخروج بنجاح", alert=True)
        return await show_main_menu(event, user)

    if data == "cancel_action":
        clear_user_state(uid)
        await event.answer("تم الإلغاء")
        return await show_main_menu(event, user)

    if data == "a_cancel":
        if not is_admin(uid):
            return await event.answer("غير مصرح", alert=True)
        state_info = get_user_state(uid)
        zip_path = state_info.get('data', {}).get('zip_path')
        if zip_path and os.path.exists(zip_path):
            os.remove(zip_path)
        pending_file = db.get('pending_spam_choice', {}).get('file_path')
        if pending_file and os.path.exists(pending_file):
            os.remove(pending_file)
        if db.get('pending_spam_choice'):
            db['pending_spam_choice'] = {}
            save_db(db)
        clear_user_state(uid)
        await event.answer("تم الإلغاء")
        return await safe_edit(event,
            "⚡ *لوحة تحكم الأدمن* ⚡\n━━━━━━━━━━━━━━━━━━━━\n\n🔐 اختر الإجراء المطلوب:",
            buttons=kb_admin_main(uid)
        )

    if data == "scam_channels":
        await event.answer()
        return await on_scam_channels_menu(event, user)
    if data.startswith("scam_buy:"):
        return await on_scam_channel_purchase(event, user, data.split(":", 1)[1])
    if data == "buy":
        await event.answer()
        return await safe_edit(event, ui_text(uid, "🔐 اختر نوع الأرقام:", "🔐 Choose number type:"), buttons=kb_purchase_type('numbers', uid))
    if data == "buy_sessions":
        await event.answer()
        return await safe_edit(event, ui_text(uid, "🔐 اختر نوع الجلسات:", "🔐 Choose session type:"), buttons=kb_purchase_type('sessions', uid))
    if data == "buy_type:clean":
        return await on_buy_menu(event, user, kind='clean')
    if data == "buy_type:spam":
        return await on_buy_menu(event, user, kind='spam')
    if data == "buy_type:spam_mix":
        return await on_buy_menu(event, user, kind='spam_mix')
    if data == "buy_type:old":
        return await on_buy_menu(event, user, kind='old')
    if data == "buy_type:old_spam":
        return await on_buy_menu(event, user, kind='old_spam')
    if data == "buy_type:fake":
        return await on_buy_menu(event, user, kind='fake')
    if data == "buy_type:unverified":
        return await on_buy_menu(event, user, kind='unverified')
    if data == "buy_type:monthly":
        return await on_buy_menu(event, user, kind='monthly')
    if data == "buy_type:daily":
        return await on_buy_menu(event, user, kind='daily')
    if data == "buy_type:bimonthly":
        return await on_buy_menu(event, user, kind='bimonthly')
    if data == "buy_type:random":
        return await on_buy_menu(event, user, kind='random')
    if data == "buy_sessions_type:clean":
        return await on_buy_sessions_menu(event, user, kind='clean')
    if data == "buy_sessions_type:spam":
        return await on_buy_sessions_menu(event, user, kind='spam')
    if data == "buy_sessions_type:spam_mix":
        return await on_buy_sessions_menu(event, user, kind='spam_mix')
    if data == "buy_sessions_type:old":
        return await on_buy_sessions_menu(event, user, kind='old')
    if data == "buy_sessions_type:old_spam":
        return await on_buy_sessions_menu(event, user, kind='old_spam')
    if data == "buy_sessions_type:fake":
        return await on_buy_sessions_menu(event, user, kind='fake')
    if data == "buy_sessions_type:unverified":
        return await on_buy_sessions_menu(event, user, kind='unverified')
    if data == "buy_sessions_type:monthly":
        return await on_buy_sessions_menu(event, user, kind='monthly')
    if data == "buy_sessions_type:bimonthly":
        return await on_buy_sessions_menu(event, user, kind='bimonthly')
    if data.startswith("bspage:"):
        parts = data.split(":")
        page = int(parts[1])
        kind = parts[2] if len(parts) > 2 else 'clean'
        return await on_buy_sessions_menu(event, user, page=page, kind=kind)
    if data.startswith("bs_c:"):
        parts = data.split(":", 2)
        if len(parts) == 3:
            return await on_bs_country_selected(event, user, parts[2], kind=parts[1])
        return await on_bs_country_selected(event, user, parts[1], kind='clean')
    if data.startswith("execute_bs:"):
        parts = data.split(":")
        if len(parts) >= 4:
            return await on_execute_sessions(event, user, parts[2], int(parts[3]), kind=parts[1])
        return await on_execute_sessions(event, user, parts[1], int(parts[2]), kind='clean')
    if data.startswith("cpage:"):
        parts = data.split(":")
        page = int(parts[1])
        kind = parts[2] if len(parts) > 2 else 'clean'
        return await on_buy_menu(event, user, page=page, kind=kind)
    if data.startswith("buy_c:"):
        parts = data.split(":", 2)
        if len(parts) == 3:
            return await on_confirm_buy(event, user, parts[2], kind=parts[1])
        return await on_confirm_buy(event, user, parts[1], kind='clean')
    if data.startswith("confirm_buy:"):
        parts = data.split(":", 2)
        if len(parts) == 3:
            return await on_execute_buy(event, user, parts[2], kind=parts[1])
        return await on_execute_buy(event, user, parts[1], kind='clean')
    if data.startswith("req_code:"):
        return await on_request_code(event, user, int(data.split(":")[1]))
    if data.startswith("logout:"):
        return await on_logout_session(event, user, int(data.split(":")[1]))
    if data.startswith("confirm_logout:"):
        return await on_confirm_logout_session(event, user, int(data.split(":")[1]))
    if data.startswith("cancel_logout:"):
        return await on_cancel_logout_session(event, user, int(data.split(":")[1]))

    if data == "deposit":
        return await on_deposit_menu(event)
    if data.startswith("pay:"):
        currency = data.split(":", 1)[1]
        if currency == "STARS":
            return await on_pay_stars_menu(event, user)
        return await on_pay_crypto(event, user, currency)
    if data == "stars_custom":
        return await on_stars_custom_prompt(event, user)
    if data.startswith("stars_buy:"):
        return await on_execute_stars_pay(event, user, data.split(":", 1)[1])
    if data.startswith("submit_tx:"):
        return await on_submit_tx_prompt(event, user, int(data.split(":", 1)[1]))
    if data.startswith("cancel_deposit:"):
        return await on_cancel_deposit(event, user, int(data.split(":", 1)[1]))
    if data == "pay_binance":
        return await on_binance_pay(event, user)
    if data == "copy:binance":
        lang = get_user_lang(uid)
        label = "Binance transfer ID" if lang == 'en' else "معرّف Binance للتحويل"
        await event.answer("Copied" if lang == 'en' else "تم عرض المعرّف للنسخ")
        return await send_msg(event, f"📋 {label}:\n`{BINANCE_TRANSFER_ID}`", buttons=kb_back())
    if data == "binance_paid":
        return await on_binance_paid_prompt(event, user)
    if data.startswith("vf_check:"):
        order_id = data.split(":", 1)[1].strip()
        rec = db.setdefault('vodafone_sms_orders', {}).get(order_id)
        if not rec or int(rec.get('user_id', 0)) != int(uid):
            return await send_msg(event, "❌ طلب الشحن غير موجود أو لا يخص حسابك.", buttons=kb_back())
        if rec.get('status') == 'credited':
            return await send_msg(event, "✅ تم شحن رصيدك بنجاح، وتم تأكيد التحويل بالفعل.", buttons=kb_back())
        return await send_msg(
            event,
            "❌ لم يتم تأكيد وصول المبلغ حتى الآن. تأكد من إتمام التحويل إلى محفظة Vodafone Cash الصحيحة. "
            "لن يُضاف الرصيد إلا بعد وصول رسالة الاستلام الأصلية ومطابقة المبلغ ورقم المُحوِّل ورقم العملية.\n\n"
            "لو لسه محوّل حالًا، انتظر وصول رسالة Vodafone Cash ثم اضغط «دفعت المبلغ» مرة أخرى.",
            buttons=[[Button.inline("دفعت المبلغ", f"vf_check:{order_id}".encode())], [Button.inline("رجوع", b"back_main")]],
        )
    if data == "pay_vodafone":
        return await on_cash_payment(event, user, 'vodafone')
    if data == "pay_orange":
        return await send_msg(event, "❌ أورنج كاش غير متاح حاليًا. استخدم فودافون كاش.", buttons=kb_deposit_methods())
    if data == "manual_pay":
        return await on_manual_pay_list(event)
    if data.startswith("mp_show:"):
        return await on_manual_pay_show(event, user, data.split(":", 1)[1])
    if data.startswith("mp_send:"):
        return await on_manual_pay_start_amount(event, user, data.split(":", 1)[1])

    # خيارات استيراد ZIP
    if data == "import_fake":
        state_info = get_user_state(uid)
        zip_path = state_info.get('data', {}).get('zip_path')
        if not zip_path or not os.path.exists(zip_path):
            await event.answer("الملف غير موجود", alert=True)
            clear_user_state(uid)
            return await safe_edit(event, "حدث خطأ، حاول مجددًا.", buttons=kb_admin_back())
        set_user_state(uid, 'a_awaiting_zip_fake_year', zip_path=zip_path)
        return await safe_edit(event,
            "📅 *سنة إنشاء الأرقام المزيفة والاحتيالية*\n\n"
            "أرسل سنة الإنشاء يدويًا، مثال: `2020`:",
            buttons=kb_admin_cancel())

    if data == "import_old":
        state_info = get_user_state(uid)
        zip_path = state_info.get('data', {}).get('zip_path')
        if not zip_path or not os.path.exists(zip_path):
            await event.answer("الملف غير موجود", alert=True)
            clear_user_state(uid)
            return await safe_edit(event, "حدث خطأ، حاول مجدداً.", buttons=kb_admin_back())
        set_user_state(uid, 'a_awaiting_zip_old_year', zip_path=zip_path)
        return await safe_edit(event,
            "📅 *سنة إنشاء الأرقام القديمة*\n\n"
            "أرسل سنة الإنشاء يدويًا، مثال: `2020`:",
            buttons=kb_admin_cancel())
        clear_user_state(uid)
        report = (
            f"✅ *تم استيراد {old_numbers_label(uid)} بنجاح!*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🟢 الأرقام المُضافة: `{added}`\n"
            f"🟡 المكررة (تخطي): `{duplicates}`\n"
            f"🔴 الفاشلة: `{failed}`\n"
            f"💰 السعر المطبق: `{OLD_NUMBERS_PRICE:.2f}$` (ثابت)\n\n"
        )
        if errors:
            report += "📋 *الأخطاء (أول 10):*\n" + "\n".join(f"  • {e}" for e in errors[:10])
        else:
            report += "✅ *جميع الأرقام تمت معالجتها بنجاح!*"
        await safe_edit(event, report, buttons=[[Button.inline("رجوع للوحة", b"a:panel")]])
        return

    if data == "import_monthly":
        state_info = get_user_state(uid)
        zip_path = state_info.get('data', {}).get('zip_path')
        if not zip_path or not os.path.exists(zip_path):
            await event.answer("الملف غير موجود", alert=True)
            clear_user_state(uid)
            return await safe_edit(event, "حدث خطأ، حاول مجدداً.", buttons=kb_admin_back())
        set_user_state(uid, 'a_awaiting_zip_monthly_price', zip_path=zip_path)
        return await safe_edit(event, '💰 *تحديد سعر أرقام مميزة شهر*\n\nأرسل السعر الذي تريده لكل رقم، مثال: `5`:', buttons=kb_admin_cancel())

    if data == "import_daily":
        state_info = get_user_state(uid)
        zip_path = state_info.get('data', {}).get('zip_path')
        if not zip_path or not os.path.exists(zip_path):
            await event.answer("الملف غير موجود", alert=True)
            clear_user_state(uid)
            return await safe_edit(event, "حدث خطأ، حاول مجددًا.", buttons=kb_admin_back())
        set_user_state(uid, 'a_awaiting_zip_daily_price', zip_path=zip_path)
        return await safe_edit(event, '☀️ *تحديد سعر أرقام مميزة يوم*\n\nأرسل السعر لكل رقم، مثال: `1.5`:', buttons=kb_admin_cancel())

    if data == "import_random":
        state_info = get_user_state(uid)
        zip_path = state_info.get('data', {}).get('zip_path')
        if not zip_path or not os.path.exists(zip_path):
            await event.answer("الملف غير موجود", alert=True)
            clear_user_state(uid)
            return await safe_edit(event, "حدث خطأ، حاول مجددًا.", buttons=kb_admin_back())
        set_user_state(uid, 'a_awaiting_zip_random_price', zip_path=zip_path)
        return await safe_edit(event, '🎲 *تحديد سعر أرقام مميزة عشوائي*\n\nأرسل السعر لكل رقم، مثال: `2`:', buttons=kb_admin_cancel())

    if data == "import_bimonthly":
        state_info = get_user_state(uid)
        zip_path = state_info.get('data', {}).get('zip_path')
        if not zip_path or not os.path.exists(zip_path):
            await event.answer("الملف غير موجود", alert=True)
            clear_user_state(uid)
            return await safe_edit(event, "حدث خطأ، حاول مجددًا.", buttons=kb_admin_back())
        set_user_state(uid, 'a_awaiting_zip_bimonthly_price', zip_path=zip_path)
        return await safe_edit(event, f'🌟 *تحديد سعر {BIMONTHLY_NUMBERS_LABEL}*\n\nأرسل السعر لكل رقم، مثال: `2`:', buttons=kb_admin_cancel())

    if data == "import_old_spam":
        state_info = get_user_state(uid)
        zip_path = state_info.get('data', {}).get('zip_path')
        if not zip_path or not os.path.exists(zip_path):
            await event.answer("الملف غير موجود", alert=True)
            clear_user_state(uid)
            return await safe_edit(event, "حدث خطأ، حاول مجددًا.", buttons=kb_admin_back())
        set_user_state(uid, 'a_awaiting_zip_old_spam_price', zip_path=zip_path)
        return await safe_edit(event, f"🕰 *تحديد سعر {OLD_SPAM_LABEL}*\n\nأرسل السعر لكل رقم، مثال: `0.5`:", buttons=kb_admin_cancel())

    if data == "import_spam_mix":
        state_info = get_user_state(uid)
        zip_path = state_info.get('data', {}).get('zip_path')
        if not zip_path or not os.path.exists(zip_path):
            await event.answer("الملف غير موجود", alert=True); clear_user_state(uid)
            return await safe_edit(event, "حدث خطأ، حاول مجدداً.", buttons=kb_admin_back())
        set_user_state(uid, 'a_awaiting_zip_spam_mix_price', zip_path=zip_path)
        return await safe_edit(event, f"(EMOJI{SPAM_MIX_EMOJI_ID}) *تحديد سعر {SPAM_MIX_LABEL}*\n\nأرسل السعر لكل رقم، مثال: `0.5`:", buttons=kb_admin_cancel())

    if data == "import_mixed":
        state_info = get_user_state(uid)
        zip_path = state_info.get('data', {}).get('zip_path')
        if not zip_path or not os.path.exists(zip_path):
            await event.answer("الملف غير موجود", alert=True)
            clear_user_state(uid)
            return await safe_edit(event, "حدث خطأ، حاول مجدداً.", buttons=kb_admin_back())
        
        set_user_state(uid, 'a_awaiting_zip_spam_price', zip_path=zip_path)
        return await safe_edit(event,
            "💰 *تحديد سعر أرقام السبام*\n\n"
            "أرسل السعر الذي تريده لكل رقم في هذا الملف، مثال: `0.4`:",
            buttons=kb_admin_cancel())
        clear_user_state(uid)
        report = (
            "✅ *تمت عملية الاستيراد بنجاح!*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🟢 الأرقام المُضافة (مخطلت): `{added}`\n"
            f"🟡 المكررة (تخطي): `{duplicates}`\n"
            f"🔴 الفاشلة: `{failed}`\n"
            f"💰 السعر المطبق: `{fmt_amt(0.18, uid)}` (ثابت)\n\n"
        )
        if errors:
            report += "📋 *الأخطاء (أول 10):*\n" + "\n".join(f"  • {e}" for e in errors[:10])
        else:
            report += "✅ *جميع الأرقام تمت معالجتها بنجاح!*"
        await safe_edit(event, report, buttons=[[Button.inline("رجوع للوحة", b"a:panel")]])
        return
        
    if data == "import_fake":
        state_info = get_user_state(uid)
        zip_path = state_info.get('data', {}).get('zip_path')
        if not zip_path or not os.path.exists(zip_path):
            await event.answer("الملف غير موجود", alert=True)
            clear_user_state(uid)
            return await safe_edit(event, "حدث خطأ، حاول مجدداً.", buttons=kb_admin_back())
        
        await event.answer(f"جاري معالجة الملف ({FAKE_LABEL}) بالسعر الثابت {FAKE_PRICE}$...", alert=True)
        added, duplicates, failed, errors = await process_uploaded_sessions_zip(zip_path, merge_as_mixed=False, custom_price=FAKE_PRICE, is_fake=True)
        clear_user_state(uid)
        report = (
            "✅ *تمت عملية الاستيراد بنجاح!*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🟢 الأرقام المُضافة ({FAKE_LABEL}): `{added}`\n"
            f"🟡 المكررة (تخطي): `{duplicates}`\n"
            f"🔴 الفاشلة: `{failed}`\n"
            f"💰 السعر المطبق: `{FAKE_PRICE}$` (ثابت)\n\n"
        )
        if errors:
            report += "📋 *الأخطاء (أول 10):*\n" + "\n".join(f"  • {e}" for e in errors[:10])
        else:
            report += "✅ *جميع الأرقام تمت معالجتها بنجاح!*"
        await safe_edit(event, report, buttons=[[Button.inline("رجوع للوحة", b"a:panel")]])
        return

    if data == "import_unverified":
        state_info = get_user_state(uid)
        zip_path = state_info.get('data', {}).get('zip_path')
        if not zip_path or not os.path.exists(zip_path):
            await event.answer("الملف غير موجود", alert=True)
            clear_user_state(uid)
            return await safe_edit(event, "حدث خطأ، حاول مجددًا.", buttons=kb_admin_back())
        set_user_state(uid, 'a_awaiting_zip_unverified_price', zip_path=zip_path)
        return await safe_edit(event, "💰 *تحديد سعر أرقام السبام*\n\nأرسل السعر لكل رقم، مثال: `0.5`:", buttons=kb_admin_cancel())

    if data == "import_usa":
        state_info = get_user_state(uid)
        zip_path = state_info.get('data', {}).get('zip_path')
        if not zip_path or not os.path.exists(zip_path):
            await event.answer("الملف غير موجود", alert=True)
            clear_user_state(uid)
            return await safe_edit(event, "حدث خطأ، حاول مجدداً.", buttons=kb_admin_back())
        set_user_state(uid, 'a_awaiting_zip_usa_price', zip_path=zip_path)
        await safe_edit(
            event,
            "💰 *تحديد سعر جلسات أمريكا السليمة*\n\n"
            "أرسل السعر الذي تريده لكل رقم في هذا الملف، مثال: `0.4`:",
            buttons=kb_admin_cancel()
        )
        return

    if data == "import_clean":
        state_info = get_user_state(uid)
        zip_path = state_info.get('data', {}).get('zip_path')
        if not zip_path or not os.path.exists(zip_path):
            await event.answer("الملف غير موجود", alert=True)
            clear_user_state(uid)
            return await safe_edit(event, "حدث خطأ، حاول مجدداً.", buttons=kb_admin_back())
        set_user_state(uid, 'a_awaiting_zip_separate_price', zip_path=zip_path)
        return await safe_edit(event,
            "💰 *سعر الأرقام السليمة*\n\n"
            "أرسل السعر الذي تريد تطبيقه على كل رقم، وسيتم حفظ كل رقم تحت دولته:",
            buttons=kb_admin_cancel())

    if data == "import_separate":
        state_info = get_user_state(uid)
        zip_path = state_info.get('data', {}).get('zip_path')
        if not zip_path or not os.path.exists(zip_path):
            await event.answer("الملف غير موجود", alert=True)
            clear_user_state(uid)
            return await safe_edit(event, "حدث خطأ، حاول مجدداً.", buttons=kb_admin_back())
        set_user_state(uid, 'a_awaiting_zip_separate_price', zip_path=zip_path)
        return await safe_edit(event,
            "💰 *سعر الدول المنفصلة*\n\n"
            "أرسل السعر الذي تريد تطبيقه على كل رقم، وسيتم حفظ كل رقم تحت دولته التي يتعرف عليها البوت:",
            buttons=kb_admin_cancel())

    if data == "import_normal":
        state_info = get_user_state(uid)
        zip_path = state_info.get('data', {}).get('zip_path')
        if not zip_path or not os.path.exists(zip_path):
            await event.answer("الملف غير موجود", alert=True)
            clear_user_state(uid)
            return await safe_edit(event, "حدث خطأ، حاول مجدداً.", buttons=kb_admin_back())
        
        # طلب السعر قبل معالجة الـ ZIP
        set_user_state(uid, 'awaiting_zip_price', zip_path=zip_path)
        await safe_edit(event, 
            "💰 *تحديد السعر للأرقام المستوردة*\n\n"
            "⚡ أرسل السعر الذي تريده لكل رقم في هذا الملف (مثال: `1.20`):\n\n"
            "💡 سيتم تطبيق هذا السعر على زر الدولة المخصص.",
            buttons=kb_admin_cancel())
        return

    # معالجة أوامر الأدمن
    if data.startswith("a:") or data.startswith("a_") or data.startswith("ac:") or data.startswith("aa:") \
            or data.startswith("am:") or data.startswith("aw:") \
            or data.startswith("admin_mr:") \
            or data.startswith("ac_edit:") or data.startswith("ac_del:") \
            or data.startswith("am_del:") or data.startswith("ap:") or data.startswith("apc:") \
            or data.startswith("ab:") or data.startswith("ac_fs:") \
            or data.startswith("ae:") or data.startswith("ah:") \
            or data.startswith("asc:") \
            or data.startswith("abe:") or data.startswith("aq_add:") or data.startswith("aq_sub:") \
            or data == "a:import_sessions" or data.startswith("import_") \
            or data.startswith("target:") or data.startswith("target_page:") or data == "target_new":
        if not is_admin(uid):
            return await event.answer("غير مصرح لك بدخول لوحة التحكم.", alert=True)
        await event.answer()
        return await admin_callback_handler(event, data)

    await event.answer("خيار غير مدعوم حالياً.")

# ================================
#  دوال الكولباك المساعدة (المكتملة)
# ================================
async def on_verify_captcha(event, uid):
    state = get_user_state(uid)
    if state.get('state') == 'captcha_passed' or db['users'].get(str(uid), {}).get('verified'):
        db['users'][str(uid)]['verified'] = True
        await _process_pending_referral(uid)
        save_db(db)
        update_user_cache(uid)
        clear_user_state(uid)
        await event.answer("تم التحقق بنجاح")
        user = await event.get_sender()
        await safe_edit(event,
            "🔐 *تم التحقق بنجاح!* 🔐\n━━━━━━━━━━━━━━━━━━━━\n\n✅ تم التأكد من أنك لست روبوت",
            buttons=None
        )
        udata = ensure_user_by_id(uid)
        if not udata.get('currency'):
            await ask_currency(event, uid)
        else:
            await show_main_menu(event, user)
    else:
        await event.answer("يرجى كتابة الرقم الظاهر في الصورة/الرسالة وإرساله أولاً!", alert=True)

async def on_check_sub(event, uid):
    # 1. إيقاف الـ Lag ودائرة التحميل فوراً
    await event.answer("🔍 جاري التحقق من اشتراكك...")
    
    # 2. الفحص السريع المتوازي
    not_subbed = await check_subscription(uid)
    
    # تحديث حالة الإحالة
    await _set_referral_active_state(uid, not bool(not_subbed))
    
    if not not_subbed:
        # 3. تم الاشتراك بنجاح
        user = await event.get_sender()
        udata = ensure_user_by_id(uid)
        
        # إذا كان المستخدم لم يتجاوز الكابتشا بعد، نوجهه إليها
        if not udata.get('verified') and not is_admin(uid):
            return await send_captcha(event, uid)
        
        # التوجيه المباشر لواجهة شراء الأرقام كما طلب المستخدم
        return await on_buy_menu(event, user)
    else:
        # لم يشترك في كل القنوات
        await event.answer("⚠️ يجب عليك الاشتراك في جميع القنوات أولاً!", alert=True)
        # تحديث الرسالة بقائمة القنوات المتبقية
        await safe_edit(event,
            "⚠️ *الاشتراك الإجباري* ⚠️\n━━━━━━━━━━━━━━━━━━━━\n\n🔐 يجب الاشتراك في القنوات التالية لاستخدام البوت:",
            buttons=kb_force_sub(not_subbed)
        )

async def on_my_balance(event, user):
    uid = user.id
    await event.answer()
    balance = get_balance(user.id)
    u = db['users'].get(str(user.id), {})
    text = (
        "💰 *معلومات حسابك* 💰\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⚡ الرصيد الحالي: `{fmt_amt(balance, uid)}`\n"
        f"💠 إجمالي الشحن: `{fmt_amt(u.get('total_deposited', 0), uid)}`\n"
        f"🛒 إجمالي المشتريات: `{fmt_amt(u.get('total_spent', 0), uid)}`\n\n"
        f"🆔 الايدي: `{user.id}`\n"
        f"👤 اليوزر: @{u.get('username') or 'لا يوجد'}"
    )
    await safe_edit(event, text, buttons=kb_back())

async def on_my_purchases(event, user):
    await event.answer()
    my = [p for p in db.get('purchases', []) if str(p['user_id']) == str(user.id)]
    my = sorted(my, key=lambda x: x.get('purchased_at', ''), reverse=True)[:20]
    if not my:
        text = "📋 *لا توجد مشتريات بعد*\n\n🔐 ابدأ بشراء أول رقم لك من قائمة الشراء!"
    else:
        text = "📋 *آخر مشترياتك* 📋\n━━━━━━━━━━━━━━━━━━━━\n\n"
        for p in my:
            text += f"📱 `+{p['phone']}` • {p['price']}$ • 📅 {p.get('purchased_at', '')[:10]}\n"
    await safe_edit(event, text, buttons=kb_back())


async def on_info(event):
    await event.answer()
    text = (
        "⚡ *معلومات البوت* ⚡\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔐 *بوت لبيع أرقام تيليجرام موثوقة*\n\n"
        f"💠 الحد الأدنى للشحن: `{MIN_DEPOSIT}$`\n"
        f"💠 الحد الأقصى للشحن: `{MAX_DEPOSIT}$`\n\n"
        "🔻 *طريقة الدفع المتاحة:*\n"
        "   💸 دفع فودافون كاش\n\n"
        f"🆘 [الدعم الفني]({db['settings'].get('support_url', '#')})"
    )
    await safe_edit(event, text, buttons=kb_back())

async def on_daily_gift(event, user):
    uid = str(user.id)
    not_subbed = await check_subscription(user.id)
    if not_subbed:
        text = (
            "⚠️ *عذراً، يجب عليك الاشتراك في قنوات البوت أولاً للحصول على الهدية اليومية.*\n\n"
            "🔐 اشترك في القنوات التالية ثم اضغط على زر التحقق:"
        )
        await safe_edit(event, text, buttons=kb_force_sub(not_subbed))
        return
    udata = db['users'].get(uid, {})
    last_gift = udata.get('last_daily_gift', 0)
    now = time.time()
    if now - last_gift < 86400:
        remaining = 86400 - (now - last_gift)
        hours = int(remaining // 3600)
        minutes = int((remaining % 3600) // 60)
        await event.answer(f"لقد استلمت هديتك بالفعل! عد بعد {hours} ساعة و {minutes} دقيقة.", alert=True)
        return
    gift_amount = 0.01
    udata['balance'] = round(udata.get('balance', 0) + gift_amount, 4)
    udata['last_daily_gift'] = now
    save_db(db)
    update_user_cache(uid)
    await event.answer(f"تم استلام الهدية اليومية: {fmt_amt(gift_amount, user.id)}", alert=True)
    await show_main_menu(event, user)

async def on_developer_page(event):
    try:
        await event.answer()
    except Exception:
        pass
    text = (
        "🧑‍💻 *قسم التواصل والدعم* 🧑‍💻\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "(EMOJI5188481279963715781) يمكنك التواصل معنا عبر القنوات والحسابات التالية لضمان أفضل خدمة:"
    )
    buttons = [
        [Button.url("قناة التحديثات", "https://t.me/MOSCOW100BOT")],
        [Button.url("قناة التفعيلات", "https://t.me/MOSCOW8BOT")],
        [Button.url("🆘 الدعم الفني", "https://t.me/MOSCOW108BOT")],
        [Button.inline("رجوع", b"back_main")]
    ]
    await safe_edit(event, text, buttons=buttons)

async def on_rules(event):
    try:
        await event.answer()
    except Exception:
        pass
    text = (
        "⚖️ *قوانين وشروط الاستخدام* ⚖️\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "مرحباً عزيزي، يجب عليك الالتزام بالقوانين التالية:\n"
        "1 - شحن رصيدك داخل البوت تلقائي.\n"
        "2 - في حال استلمت حساب من البوت وسجلت الدخول له يتم اخلاء مسؤليه المطورين من الحساب المُستلم.\n"
        "3 - في حال وجود مشكله تواصل مع المطور.\n"
        "4 - قرأتك للقوانين يعني موافقتك عليها و اذا لم تقم بقرائتها فهيه مشكلتك.\n"
        "5 - لتجنب لحظر و تجميد الارقام قم بالتسجيل في تطبيق التليكرام النسخه تيليجرام بليس.\n"
        "6 - اشتريت حساب من البوت سليم تجمذ يمك تحمل مسؤوليتك.\n\n"
        "⚠️ *ملاحظة:* لا يمكنك العودة إلا عبر الزر أدناه."
    )
    await safe_edit(event, text, buttons=[[Button.inline("موافق ورجوع", b"back_main")]])

async def on_deposit_menu(event):
    await event.answer()
    text = (
        "(EMOJI4987882440107230847) *اختر الطريقة المراد شحن حسابك بها*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "(EMOJI4987882440107230847) شحن تلقائي عبر Binance Pay\n\n"
    )
    await safe_edit(event, text, buttons=kb_deposit_methods())

async def on_binance_pay(event, user):
    await event.answer()
    if not BINANCE_TRANSFER_ID:
        return await safe_edit(
            event,
            "⚠️ *خدمة Binance Pay غير مهيأة حالياً.*\n\n"
            "يرجى ضبط `BINANCE_TRANSFER_ID` في متغيرات البيئة ثم إعادة تشغيل البوت.",
            buttons=[[Button.inline("رجوع", b"deposit")]],
        )
    text = (
        "يمكنك شحن حسابك عبر Binance Pay.\n\n"
        f"- قم بتحويل المبلغ إلى (EMOJI4987882440107230847) Binance ID:\n`{BINANCE_TRANSFER_ID}`\n"
        "- بعد التحويل اضغط على الزر أدناه وأدخل معرف العملية."
    )
    await safe_edit(event, text, buttons=kb_binance_pay(user.id))

async def on_binance_paid_prompt(event, user):
    await event.answer()
    set_user_state(user.id, 'binance_amount')
    await safe_edit(
        event,
        "💰 **أرسل مبلغ الشحن الذي قمت بتحويله بالدولار USDT:**\n\n"
        f"الحد الأدنى: `{MIN_BINANCE_DEPOSIT:.2f} USDT`\n"
        f"الحد الأقصى: `{MAX_DEPOSIT:.2f} USDT`\n\n"
        "اكتب المبلغ فقط، مثال: `5` أو `5.50`.",
        buttons=kb_cancel(),
    )

async def handle_binance_amount(event, user, text):
    raw_amount = str(text or '').strip().replace(',', '.')
    try:
        amount = float(raw_amount)
    except (TypeError, ValueError):
        return await send_msg(event, "❌ أرسل مبلغًا صحيحًا، مثال: `5.50`.", buttons=kb_cancel())
    if amount < MIN_BINANCE_DEPOSIT or amount > MAX_DEPOSIT:
        return await send_msg(
            event,
            f"❌ المبلغ يجب أن يكون بين `{MIN_BINANCE_DEPOSIT:.2f}` و`{MAX_DEPOSIT:.2f}` USDT.",
            buttons=kb_cancel(),
        )
    set_user_state(user.id, 'binance_hash', amount=round(amount, 8))
    await send_msg(
        event,
        "🔑 **أرسل معرف العملية TXID الخاص بـ Binance Pay:**\n\n"
        "بعد إرساله سيصل الطلب إلى الأدمن للمراجعة، وقد تستغرق المراجعة من 5 إلى 10 دقائق.\n"
        "لن تتم إضافة الرصيد إلا بعد موافقة الأدمن.",
        buttons=kb_cancel(),
    )

async def handle_binance_hash(event, user, text, amount):
    txid = str(text or '').strip()
    if not txid:
        return await send_msg(
            event,
            "🔑 **أرسل معرف العملية TXID الخاص بـ Binance Pay:**\n\nلا يمكن إنشاء الطلب بدون TXID.",
            buttons=kb_cancel(),
        )
    if len(txid) > 128:
        return await send_msg(event, "TXID غير صالح. أرسله كما يظهر في تطبيق Binance.", buttons=kb_cancel())
    if is_txid_used(txid):
        clear_user_state(user.id)
        return await send_msg(event, "❌ هذا TXID استُخدم سابقًا ولا يمكن شحنه مرة أخرى.", buttons=kb_back())
    try:
        requested_amount = round(float(amount), 8)
    except (TypeError, ValueError):
        clear_user_state(user.id)
        return await send_msg(event, "❌ انتهت بيانات مبلغ الشحن. ابدأ طلب Binance من جديد.", buttons=kb_back())
    if requested_amount < MIN_BINANCE_DEPOSIT or requested_amount > MAX_DEPOSIT:
        clear_user_state(user.id)
        return await send_msg(event, "❌ مبلغ الشحن خارج النطاق المسموح. ابدأ طلبًا جديدًا.", buttons=kb_back())

    req_id = _next('next_manual_id')
    req = {
        'id': req_id,
        'user_id': user.id,
        'method': 'Binance Pay',
        'amount': requested_amount,
        'hashid': txid,
        'status': 'pending',
        'created_at': datetime.now().isoformat(),
        'receiver_id': BINANCE_TRANSFER_ID,
        'source': 'binance_pay_manual_admin',
    }
    db.setdefault('manual_requests', []).append(req)
    save_db(db)
    clear_user_state(user.id)

    await send_msg(
        event,
        "⏳ **تم إرسال طلب الشحن للمراجعة**\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 المبلغ المطلوب: `{requested_amount:.8f} USDT`\n"
        f"🔑 TXID: `{txid}`\n\n"
        "🛡️ سيقوم الأدمن بمراجعة التحويل خلال 5 إلى 10 دقائق.\n"
        "لن يضاف الرصيد إلا بعد الموافقة.",
        buttons=kb_back(),
    )

    try:
        kb = [[
            Button.inline("✅ قبول وإضافة الرصيد", f"admin_mr:binance_approve:{req_id}".encode()),
            Button.inline("❌ رفض TXID", f"admin_mr:binance_reject:{req_id}".encode()),
        ]]
        caption = (
            f"💰 *طلب شحن Binance Pay جديد #{req_id}*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 المستخدم: `{user.id}` (@{user.username or 'لا يوجد'})\n"
            f"💵 المبلغ المطلوب إضافته: `{requested_amount:.8f} USDT`\n"
            f"🔑 معرف العملية TXID: `{txid}`\n"
            f"🎯 Binance ID المستلم: `{BINANCE_TRANSFER_ID}`\n\n"
            "⚠️ تحقق من وصول المبلغ وصحة TXID قبل القبول."
        )
        await send_msg(OWNER_ID, caption, buttons=kb)
    except Exception as e:
        logger.error(f"Binance admin notify failed: {e}")

async def handle_binance_proof(event, user, amount, hashid):
    # حالة قديمة فقط: لا تُنشئ طلبًا يدويًا ولا تنتظر موافقة الأدمن.
    clear_user_state(user.id)
    return await send_msg(
        event,
        "تم إلغاء إثبات الصورة وموافقة الأدمن في Binance. ابدأ من شحن Binance وأرسل TXID للتحقق التلقائي.",
        buttons=kb_back(),
    )
    if amount < MIN_BINANCE_DEPOSIT or amount > MAX_DEPOSIT:
        clear_user_state(user.id)
        return await send_msg(event,
            f"⚠️ المبلغ `{amount}$` خارج النطاق المسموح ({MIN_BINANCE_DEPOSIT:.2f}$ - {MAX_DEPOSIT:.2f}$)\n"
            "🔙 يرجى إعادة الشحن بمبلغ ضمن النطاق.",
            buttons=kb_back()
        )
    req_id = _next('next_manual_id')
    photo_id = None
    if event.message.photo:
        photo_id = event.message.photo.id
    elif event.message.document:
        photo_id = event.message.document.id
    req = {
        'id': req_id, 'user_id': user.id, 'method': 'Binance',
        'amount': amount, 'hashid': hashid, 'status': 'pending',
        'photo_id': photo_id, 'message_id': event.message.id,
        'chat_id': event.chat_id,
        'created_at': datetime.now().isoformat()
    }
    db.setdefault('manual_requests', []).append(req)
    save_db(db)
    clear_user_state(user.id)
    await send_msg(event, "جاري مراجعة العملية .. يستغرق الامر من 5 دقائق الى 12 ساعه", buttons=kb_back())
    try:
        kb = [[
            Button.inline("موافقة بالمبلغ المطلوب", f"admin_mr:binance_approve:{req_id}".encode()),
            Button.inline("موافقة بمبلغ مختلف", f"admin_mr:binance_confirm_amount:{req_id}".encode()),
            Button.inline("رفض", f"admin_mr:binance_reject:{req_id}".encode())
        ]]
        caption = (
            f"💰 *طلب شحن Binance جديد #{req_id}* 🛡️\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 المستخدم: `{user.id}` (@{user.username or 'لا يوجد'})\n"
            f"💰 المبلغ المطلوب من المستخدم: `{amount}$`\n"
            f"🔑 الهاش: `{hashid}`\n\n"
            "📸 صورة التحويل مرفقة ⬇️\n\n"
            "⚠️ *تنبيه:* تحقق من المبلغ في الصورة قبل الموافقة!\n"
            "✅ *موافقة بالمبلغ المطلوب* = المطابقة 100%\n"
            "✏️ *تأكيد بمبلغ آخر* = إذا الصورة فيها مبلغ مختلف\n"
            "🚫 *رفض بدون حظر* = رفض الطلب فقط (الحظر التلقائي معطّل)"
        )
        await bot.forward_messages(OWNER_ID, event.message)
        await send_msg(OWNER_ID, caption, buttons=kb)
    except Exception as e:
        logger.error(f"Binance admin notify failed: {e}")

def _normalize_sms_digits(value):
    trans = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
    return str(value or "").translate(trans)


def _parse_vodafone_cash_sms(message):
    """Parse only the known Vodafone Cash receipt SMS format; fail closed otherwise."""
    msg = _normalize_sms_digits(message)
    if "تم استلام مبلغ" not in msg or "على رقم محفظتك" not in msg or "رقم العملية" not in msg:
        return None
    amount_match = re.search(r"تم\s+استلام\s+مبلغ\s*([0-9]+(?:[.,][0-9]{1,2})?)\s*جنيه", msg)
    sender_match = re.search(r"من\s+رقم\s+(01[0-9]{9})", msg)
    receiver_match = re.search(r"على\s+رقم\s+محفظتك\s+(01[0-9]{9})", msg)
    tx_match = re.search(r"رقم\s+العملية\s*[:：]?\s*([0-9]{8,24})", msg)
    if not (amount_match and sender_match and receiver_match and tx_match):
        return None
    try:
        amount = Decimal(amount_match.group(1).replace(',', '.')).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return None
    return {
        "amount_egp": amount,
        "sender_phone": sender_match.group(1),
        "receiver_phone": receiver_match.group(1),
        "transaction_id": tx_match.group(1),
        "message": msg,
    }


async def _process_vodafone_cash_sms(message):
    parsed = _parse_vodafone_cash_sms(message)
    if not parsed:
        logger.warning("Vodafone SMS webhook received a message that did not match the expected receipt format")
        return False
    if parsed["receiver_phone"] != VODAFONE_WALLET_NUMBER:
        logger.warning("Vodafone SMS receipt rejected: receiving wallet mismatch")
        return False

    orders = db.setdefault('vodafone_sms_orders', {})
    used_ids = db.setdefault('vodafone_sms_transaction_ids', {})
    tx_id = parsed["transaction_id"]
    if tx_id in used_ids:
        logger.info("Duplicate Vodafone Cash transaction ignored")
        return False

    now = time.time()
    # Only match a still-open order with exact amount and sender number.
    matches = []
    for order_id, rec in orders.items():
        if rec.get('status') != 'pending':
            continue
        if now - float(rec.get('created_at', 0)) > VODAFONE_ORDER_TTL:
            continue
        try:
            expected_amount = Decimal(str(rec.get('amount_egp'))).quantize(Decimal('0.01'))
        except Exception:
            continue
        if expected_amount == parsed['amount_egp'] and str(rec.get('sender_phone')) == parsed['sender_phone']:
            matches.append((order_id, rec))
    # If two orders could match, don't guess which customer should receive the credit.
    if len(matches) != 1:
        logger.warning("Vodafone Cash SMS was not credited: matching order count=%s", len(matches))
        return False

    order_id, rec = matches[0]
    amount_usd = (parsed['amount_egp'] / VODAFONE_RATE_EGP_PER_USD).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    balance_before = get_balance(rec['user_id'])
    # Persist idempotency marker and credited status before notifying; duplicate webhooks cannot credit again.
    rec.update({
        'status': 'credited',
        'transaction_id': tx_id,
        'credited_at': now,
        'confirmed_amount_egp': str(parsed['amount_egp']),
    })
    used_ids[tx_id] = {'order_id': order_id, 'credited_at': now}
    db.setdefault('transactions', []).append({
        'id': f'VFCASH-{tx_id}', 'user_id': rec['user_id'], 'currency': 'EGP',
        'txid': tx_id, 'amount_usd': float(amount_usd), 'amount_crypto': float(parsed['amount_egp']),
        'status': 'completed', 'source': 'vodafone_cash_sms', 'provider': 'vodafone', 'created_at': now,
    })
    update_balance(rec['user_id'], float(amount_usd))
    save_db(db)
    balance_after = get_balance(rec['user_id'])
    try:
        await send_msg(
            rec['user_id'],
            "✅ *تم تأكيد تحويل فودافون كاش وإضافة الرصيد*\n\n"
            f"💵 *المبلغ المستلم:* `{parsed['amount_egp']}` جنيه\n"
            f"📱 *رقم المُحوِّل:* `{parsed['sender_phone']}`\n"
            f"💰 *المبلغ المضاف لحسابك:* `{amount_usd:.2f}$`\n"
            f"📉 *رصيدك قبل:* `{balance_before:.2f}$`\n"
            f"📈 *رصيدك بعد:* `{balance_after:.2f}$`\n"
            f"🧾 *رقم العملية:* `{tx_id}`",
            buttons=kb_back(),
        )
    except Exception:
        logger.exception("Could not notify user after Vodafone Cash credit")
    return True


async def handle_vodafone_webhook(payload):
    """Accept SMS-forwarder payloads; never trust customer-submitted fields for crediting."""
    if isinstance(payload, str):
        message = payload
    elif isinstance(payload, dict):
        message = next((payload.get(k) for k in ('msg', 'message', 'body', 'text', 'sms') if isinstance(payload.get(k), str)), None)
        if message is None and isinstance(payload.get('data'), dict):
            message = next((payload['data'].get(k) for k in ('msg', 'message', 'body', 'text', 'sms') if isinstance(payload['data'].get(k), str)), None)
    else:
        message = None
    if not message:
        return False
    return await _process_vodafone_cash_sms(message)


async def on_cash_payment(event, user, provider='vodafone'):
    await event.answer()
    if provider != 'vodafone':
        return await send_msg(event, "❌ طريقة الدفع دي غير متاحة حاليًا.", buttons=kb_deposit_methods())
    set_user_state(user.id, 'cash_wallet', provider='vodafone')
    await safe_edit(
        event,
        "💳 *شحن فودافون كاش*\n\n"
        f"حوّل إلى رقم المحفظة: `{VODAFONE_WALLET_NUMBER}`\n\n"
        "أولًا، أرسل رقم الموبايل الذي ستحوّل منه، وبعدها أدخل المبلغ بالجنيه.\n"
        "⚠️ لن يُضاف الرصيد إلا بعد وصول رسالة التحويل الفعلية ومطابقتها.",
        buttons=kb_cancel(),
    )


async def on_vodafone_cash(event, user):
    return await on_cash_payment(event, user, 'vodafone')


async def handle_cash_wallet(event, user, text):
    digits = _normalize_sms_digits(text)
    digits = "".join(c for c in digits if c.isdigit())
    if len(digits) != 11 or not digits.startswith("01"):
        return await send_msg(event, "أرسل رقم الموبايل المصري الذي ستحوّل منه (11 رقمًا ويبدأ بـ 01).")
    set_user_state(user.id, 'cash_amount', sender_phone=digits, provider='vodafone')
    return await send_msg(event, f"أرسل المبلغ الذي ستحوّله بالجنيه (من {VODAFONE_MIN_EGP} إلى {VODAFONE_MAX_EGP} جنيه).")


async def handle_vodafone_wallet(event, user, text):
    return await handle_cash_wallet(event, user, text)


async def handle_cash_amount(event, user, text, wallet=None, provider='vodafone'):
    if provider != 'vodafone':
        clear_user_state(user.id)
        return await send_msg(event, "❌ طريقة الدفع دي غير متاحة حاليًا.", buttons=kb_deposit_methods())
    normalized = _normalize_sms_digits(text).strip().replace(',', '.')
    try:
        egp = Decimal(normalized).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return await send_msg(event, "المبلغ غير صحيح. أرسل رقم المبلغ بالجنيه فقط، مثال: 100")
    if not (VODAFONE_MIN_EGP <= egp <= VODAFONE_MAX_EGP):
        return await send_msg(event, f"المبلغ يجب أن يكون من {VODAFONE_MIN_EGP} إلى {VODAFONE_MAX_EGP} جنيه.")
    state_data = get_user_state(user.id).get('data', {})
    sender_phone = str(state_data.get('sender_phone') or '').strip()
    if len(sender_phone) != 11 or not sender_phone.startswith('01'):
        clear_user_state(user.id)
        return await send_msg(event, "انتهت جلسة الطلب. ابدأ شحن فودافون كاش من جديد.", buttons=kb_deposit_methods())

    now = time.time()
    orders = db.setdefault('vodafone_sms_orders', {})
    # Prevent duplicate open requests from the same user for identical sender+amount.
    for existing_id, existing in orders.items():
        if (int(existing.get('user_id', 0)) == int(user.id)
                and existing.get('status') == 'pending'
                and existing.get('sender_phone') == sender_phone
                and Decimal(str(existing.get('amount_egp', '0'))) == egp
                and now - float(existing.get('created_at', 0)) <= VODAFONE_ORDER_TTL):
            clear_user_state(user.id)
            return await send_msg(
                event,
                "⏳ عندك بالفعل طلب شحن مفتوح بنفس الرقم والمبلغ. حوّل مرة واحدة فقط وانتظر رسالة التأكيد؛ لا تنشئ طلبًا مكررًا.",
                buttons=[[Button.inline("دفعت المبلغ", f"vf_check:{existing_id}".encode())], [Button.inline("رجوع", b"back_main")]],
            )
    order_id = hashlib.sha256(f"{user.id}:{sender_phone}:{egp}:{now}:{random.random()}".encode()).hexdigest()[:16]
    orders[order_id] = {
        'user_id': int(user.id), 'sender_phone': sender_phone, 'amount_egp': str(egp),
        'receiver_phone': VODAFONE_WALLET_NUMBER, 'provider': 'vodafone', 'status': 'pending',
        'created_at': now,
    }
    save_db(db)
    clear_user_state(user.id)
    return await send_msg(
        event,
        "🧾 *تم تسجيل طلب شحن فودافون كاش*\n\n"
        f"📱 *رقم المُحوِّل:* `{sender_phone}`\n"
        f"💵 *المبلغ المنتظر:* `{egp}` جنيه\n"
        f"📥 *حوّل إلى المحفظة:* `{VODAFONE_WALLET_NUMBER}`\n\n"
        "بعد التحويل اضغط زر «دفعت المبلغ». سيتأكد البوت من رسالة استلام Vodafone Cash الأصلية، ويطابق المبلغ ورقم المُحوِّل ورقم العملية.\n\n"
        "لو التحويل لم يصل أو لم تتطابق البيانات، سيظهر لك أن الدفع لم يتأكد ولن يُضاف رصيد. عند وصول الرسالة الصحيحة، اضغط الزر مرة أخرى.\n\n"
        "⚠️ لا ترسل بيانات أو أكواد سرية، ولا تعتبر الطلب ناجحًا قبل إشعار البوت.",
        buttons=[[Button.inline("دفعت المبلغ", f"vf_check:{order_id}".encode())], [Button.inline("رجوع", b"back_main")]],
    )


async def handle_vodafone_amount(event, user, text, wallet=None):
    return await handle_cash_amount(event, user, text, wallet, 'vodafone')

async def on_pay_stars_menu(event, user):
    try:
        await event.answer()
    except Exception:
        pass
    text = (
        "⭐️ شحن عبر نجوم تيليجرام\n\n"
        "💵 سعر النجمة: 0.01$\n"
        "📉 الحد الأدنى: 0.1$\n\n"
        "💰 أرسل المبلغ المراد شحنه بالدولار (مثال: 5):"
    )
    set_user_state(user.id, 'awaiting_stars_usd_amount')
    await safe_edit(event, text, buttons=[[Button.inline("رجوع", b"deposit")]])

async def on_stars_custom_prompt(event, user):
    try:
        await event.answer()
    except Exception:
        pass
    set_user_state(user.id, 'awaiting_stars_amount')
    text = (
        "🌟 *شحن كمية مخصصة من النجوم* 🌟\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📝 أرسل الآن *عدد النجوم* الذي تريد شحنه:\n\n"
        "💡 *ملاحظة:* سعر النجمة الواحدة `0.01$`\n"
        "⚠️ الحد الأدنى: `1` نجمة\n"
        "⚠️ الحد الأقصى: `10000` نجمة"
    )
    await safe_edit(event, text, buttons=kb_cancel())

async def on_execute_stars_pay(event, user, stars_amount):
    try:
        await event.answer()
    except Exception:
        pass
    try:
        stars = int(stars_amount)
        usd_d = stars_to_usd(stars)
        usd_amount = float(usd_d)
    except ValueError as ve:
        logger.error(f"Stars invoice rejected at creation: {ve}")
        return await send_msg(event, str(ve))
    nonce = (int(time.time() * 1000) ^ random.randint(0, 0xFFFFFFFF)) & 0xFFFFFFFFFFFFFFFF
    safe_payload = stars_payload_encode(user.id, stars, nonce)
    payload = {
        "chat_id": user.id,
        "title": f"شحن رصيد {stars} نجمة",
        "description": f"إضافة {usd_d}$ إلى رصيدك في البوت تلقائياً.",
        "payload": safe_payload,
        "provider_token": "",
        "currency": "XTR",
        "prices": [{"label": "Stars", "amount": stars}],
    }
    resp = await bot_api_request("sendInvoice", payload)
    if not resp.get("ok"):
        logger.error(f"Stars invoice failed: {resp}")
        return await send_msg(event, "عذراً، فشل إنشاء طلب الدفع بالنجوم حالياً.")
    try:
        if hasattr(event, 'query'):
            await event.delete()
    except Exception:
        pass

async def on_pay_crypto(event, user, currency):
    await event.answer()
    if currency not in WALLETS:
        return await event.answer("عملة غير مدعومة", alert=True)
    addr = WALLETS[currency]
    if "PUT_YOUR" in addr or len(addr) < 10:
        return await safe_edit(event,
            f"⚠️ *عنوان محفظة {currency} لم يُضبط بعد*\n\n"
            "🔐 يرجى التواصل مع الدعم.",
            buttons=[[Button.inline("رجوع", b"deposit")]]
        )
    set_user_state(user.id, 'awaiting_deposit_amount', currency=currency)
    cur_icon = {"LTC": "🪙", "BTC": "₿", "TON": "💎", "USDT": "💵"}.get(currency, "💠")
    text = (
        f"{cur_icon} *الدفع عبر {currency}* {cur_icon}\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🌐 الشبكة: *{NETWORKS[currency]}*\n\n"
        "📝 أرسل الآن *المبلغ بالدولار* الذي تريد شحنه:\n\n"
        f"⚡ الحد الأدنى: `{fmt_amt(MIN_DEPOSIT, user.id)}`\n"
        f"⚡ الحد الأقصى: `{fmt_amt(MAX_DEPOSIT, user.id)}`\n\n"
        "💡 _مثال:_ `5` أو `10.5`"
    )
    await safe_edit(event, text, buttons=kb_cancel())

async def on_submit_tx_prompt(event, user, deposit_id):
    await event.answer()
    deposit = db['deposits'].get(str(deposit_id))
    if not deposit or str(deposit['user_id']) != str(user.id):
        return await event.answer("طلب الإيداع غير موجود", alert=True)
    if deposit['status'] != 'pending':
        return await event.answer(f"الطلب: {deposit['status']}", alert=True)
    set_user_state(user.id, 'awaiting_txid', deposit_id=deposit_id)
    await safe_edit(event,
        "📤 *إرسال معرف المعاملة* 📤\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔐 الطلب رقم: `#{deposit_id}`\n"
        f"💰 المبلغ المتوقع: `{deposit['amount_usd']}$` ≈ `{deposit['amount_crypto']} {deposit['currency']}`\n\n"
        "⚡ أرسل الآن معرف المعاملة (TXID / Hash):",
        buttons=kb_cancel()
    )

async def on_cancel_deposit(event, user, deposit_id):
    deposit = db['deposits'].get(str(deposit_id))
    if not deposit or str(deposit['user_id']) != str(user.id):
        return await event.answer("غير موجود", alert=True)
    deposit['status'] = 'cancelled'
    save_db(db)
    clear_user_state(user.id)
    await event.answer("تم الإلغاء")
    await safe_edit(event, "*تم إلغاء الطلب بنجاح*", buttons=kb_back())

async def on_manual_pay_list(event):
    await event.answer()
    methods = db.get('manual_payments', [])
    if not methods:
        return await safe_edit(event,
            "⚠️ *لا توجد طرق دفع يدوي متاحة حالياً*\n\n"
            "💡 يمكنك استخدام إحدى عملات الكريبتو.",
            buttons=kb_back()
        )
    await safe_edit(event,
        "💳 *طرق الدفع اليدوي* 💳\n━━━━━━━━━━━━━━━━━━━━\n\n🔐 اختر إحدى الطرق:",
        buttons=kb_manual_methods()
    )

async def on_manual_pay_show(event, user, method_name):
    await event.answer()
    method = next((m for m in db['manual_payments'] if m['name'] == method_name), None)
    if not method:
        return await event.answer("غير موجودة", alert=True)
    await safe_edit(event,
        f"💳 *{method['name']}* 💳\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{method['description']}\n\n"
        "⚡ اضغط الزر للبدء بإرسال المبلغ والإثبات:",
        buttons=kb_manual_confirm(method_name)
    )

async def on_manual_pay_start_amount(event, user, method_name):
    await event.answer()
    set_user_state(user.id, 'manual_amount', method=method_name)
    await safe_edit(event,
        f"💳 *دفع يدوي: {method_name}*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📝 أرسل الآن *المبلغ الذي حوّلته بالدولار*:\n\n"
        f"⚡ الحد الأدنى: `{fmt_amt(MIN_DEPOSIT, user.id)}`\n"
        f"⚡ الحد الأقصى: `{fmt_amt(MAX_DEPOSIT, user.id)}`\n\n"
        "💡 _مثال:_ `5` أو `12.50`",
        buttons=kb_cancel()
    )

def available_spam_accounts_by_country():
    grouped = {}
    for account in db.get('accounts', []):
        if account.get('status') != 'available' or account_purchase_category(account) != 'spam':
            continue
        code = account.get('country_code')
        # أمريكا السبام تُعرّف بالتصنيف فقط، أما السعر فيؤخذ من سجل الرقم.
        is_usa_spam = code in ('spam_1', 'usa_spam') or str(account.get('phone', '')).lstrip('+').startswith('1')
        country = db.get('countries', {}).get(code, {})
        base_name = country.get('name') or account.get('country_name') or f'دولة ({code})'
        if is_usa_spam:
            base_name = '🇺🇸 أمريكا'
        if '📛' not in str(base_name):
            base_name = f'{base_name} 📛'
        item = grouped.setdefault(code, {
            'code': code,
            'name': base_name,
            'price': account.get('price', country.get('price', MIXED_PRICE)),
            'count': 0,
            'prices': []
        })
        item['count'] += 1
        item['prices'].append(account.get('price', item['price']))
    for item in grouped.values():
        if item['prices']:
            item['price'] = min(item['prices'])
    return sorted(grouped.values(), key=lambda x: x['name'])

def available_spam_mix_accounts_by_country():
    grouped = {}
    for account in db.get('accounts', []):
        if account.get('status') != 'available' or account_purchase_category(account) != 'spam_mix':
            continue
        code = account.get('country_code', SPAM_MIX_CODE)
        country = db.get('countries', {}).get(code, {})
        name = country.get('name') or account.get('country_name') or SPAM_MIX_LABEL
        item = grouped.setdefault(code, {'code': code, 'name': name, 'price': account.get('price', MIXED_PRICE), 'count': 0, 'prices': []})
        item['count'] += 1
        item['prices'].append(account.get('price', item['price']))
    for item in grouped.values():
        if item['prices']: item['price'] = min(item['prices'])
    return sorted(grouped.values(), key=lambda x: x['name'])

def available_fake_accounts_by_country():
    grouped = {}
    for account in db.get('accounts', []):
        if account.get('status') != 'available' or account_purchase_category(account) != 'fake':
            continue
        code = account.get('country_code')
        country = db.get('countries', {}).get(code, {})
        base_name = country.get('name') or account.get('country_name') or f'دولة ({code})'
        if 'مزيف واحتيالي' not in str(base_name):
            base_name = f'{base_name} ⚠️ مزيف واحتيالي'
        item = grouped.setdefault(code, {
            'code': code, 'name': base_name,
            'price': account.get('price', DEFAULT_ACCOUNT_PRICE),
            'count': 0, 'prices': []
        })
        item['count'] += 1
        item['prices'].append(account.get('price', item['price']))
    for item in grouped.values():
        if item['prices']:
            item['price'] = min(item['prices'])
    return sorted(grouped.values(), key=lambda x: x['name'])

def available_unverified_accounts_by_country():
    grouped = {}
    for account in db.get('accounts', []):
        if account.get('status') != 'available' or account_purchase_category(account) != 'unverified':
            continue
        code = account.get('country_code', UNVERIFIED_CODE)
        item = grouped.setdefault(code, {'code': code, 'name': UNVERIFIED_LABEL, 'price': account.get('price', UNVERIFIED_PRICE), 'count': 0, 'prices': []})
        item['count'] += 1
        item['prices'].append(account.get('price', item['price']))
    for item in grouped.values():
        if item['prices']: item['price'] = min(item['prices'])
    return sorted(grouped.values(), key=lambda x: x['name'])

def available_random_accounts_by_country():
    grouped = {}
    for account in db.get('accounts', []):
        if account.get('status') != 'available' or account_purchase_category(account) != 'random':
            continue
        code = account.get('country_code', RANDOM_NUMBERS_CODE)
        item = grouped.setdefault(code, {'code': code, 'name': RANDOM_NUMBERS_LABEL, 'price': account.get('price', RANDOM_NUMBERS_PRICE), 'count': 0, 'prices': []})
        item['count'] += 1
        item['prices'].append(account.get('price', item['price']))
    for item in grouped.values():
        if item['prices']: item['price'] = min(item['prices'])
    return sorted(grouped.values(), key=lambda x: x['name'])

def available_daily_accounts_by_country():
    grouped = {}
    for account in db.get('accounts', []):
        if account.get('status') != 'available' or account_purchase_category(account) != 'daily':
            continue
        code = account.get('country_code', DAILY_NUMBERS_CODE)
        item = grouped.setdefault(code, {'code': code, 'name': DAILY_NUMBERS_LABEL, 'price': account.get('price', DAILY_NUMBERS_PRICE), 'count': 0, 'prices': []})
        item['count'] += 1
        item['prices'].append(account.get('price', item['price']))
    for item in grouped.values():
        if item['prices']: item['price'] = min(item['prices'])
    return sorted(grouped.values(), key=lambda x: x['name'])

def available_bimonthly_accounts_by_country():
    grouped = {}
    for account in db.get('accounts', []):
        if account.get('status') != 'available' or account_purchase_category(account) != 'bimonthly':
            continue
        code = account.get('country_code', BIMONTHLY_NUMBERS_CODE)
        item = grouped.setdefault(code, {'code': code, 'name': BIMONTHLY_NUMBERS_LABEL, 'price': account.get('price', BIMONTHLY_NUMBERS_PRICE), 'count': 0, 'prices': []})
        item['count'] += 1
        item['prices'].append(account.get('price', item['price']))
    for item in grouped.values():
        if item['prices']: item['price'] = min(item['prices'])
    return sorted(grouped.values(), key=lambda x: x['name'])

def available_monthly_accounts_by_country():
    grouped = {}
    for account in db.get('accounts', []):
        if account.get('status') != 'available' or account_purchase_category(account) != 'monthly':
            continue
        code = account.get('country_code', MONTHLY_NUMBERS_CODE)
        item = grouped.setdefault(code, {'code': code, 'name': MONTHLY_NUMBERS_LABEL, 'price': account.get('price', MONTHLY_NUMBERS_PRICE), 'count': 0, 'prices': []})
        item['name'] = MONTHLY_NUMBERS_LABEL
        item['count'] += 1
        item['prices'].append(account.get('price', item['price']))
    for item in grouped.values():
        if item['prices']: item['price'] = min(item['prices'])
    return sorted(grouped.values(), key=lambda x: x['name'])

def available_old_spam_accounts_by_country():
    grouped = {}
    for account in db.get('accounts', []):
        if account.get('status') != 'available' or account_purchase_category(account) != 'old_spam':
            continue
        code = account.get('country_code', OLD_SPAM_CODE)
        country = db.get('countries', {}).get(code, {})
        name = country.get('name') or account.get('country_name') or OLD_SPAM_LABEL
        if '📛' not in str(name):
            name = f'{name} 📛'
        item = grouped.setdefault(code, {'code': code, 'name': name, 'price': account.get('price', OLD_SPAM_PRICE), 'count': 0, 'prices': []})
        item['count'] += 1
        item['prices'].append(account.get('price', item['price']))
    for item in grouped.values():
        if item['prices']:
            item['price'] = min(item['prices'])
    return sorted(grouped.values(), key=lambda x: x['name'])

def available_old_accounts_by_country():
    grouped = {}
    for account in db.get('accounts', []):
        if account.get('status') != 'available' or account_purchase_category(account) != 'old':
            continue
        code = account.get('country_code') or OLD_NUMBERS_CODE
        item = grouped.setdefault(code, {
            'code': code,
            'name': account.get('country_name') or old_numbers_label(None),
            'price': account.get('price', OLD_NUMBERS_PRICE),
            'count': 0,
            'prices': []
        })
        item['count'] += 1
        item['prices'].append(account.get('price', OLD_NUMBERS_PRICE))
    for item in grouped.values():
        if item['prices']:
            item['price'] = min(item['prices'])
    return sorted(grouped.values(), key=lambda x: x['name'])

async def on_buy_sessions_menu(event, user, page=0, kind='clean'):
    await event.answer()
    if kind == 'spam':
        accs = available_spam_accounts_by_country()
    elif kind == 'spam_mix':
        accs = available_spam_mix_accounts_by_country()
    elif kind == 'fake':
        accs = available_fake_accounts_by_country()
    elif kind == 'unverified':
        accs = available_unverified_accounts_by_country()
    elif kind == 'old_spam':
        accs = available_old_spam_accounts_by_country()
    elif kind == 'old':
        accs = available_old_accounts_by_country()
    elif kind == 'monthly':
        accs = available_monthly_accounts_by_country()
    elif kind == 'daily':
        accs = available_daily_accounts_by_country()
    elif kind == 'bimonthly':
        accs = available_bimonthly_accounts_by_country()
    elif kind == 'random':
        accs = available_random_accounts_by_country()
    else:
        accs = available_accounts_by_country()
    if not accs:
        text = (
            "⚠️ *لا توجد جلسات متاحة حالياً*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔐 جميع الأرقام نُفذت أو لم تُضف أرقام بعد.\n"
            "⚡ يرجى المحاولة لاحقاً."
        )
        await safe_edit(event, text, buttons=[[Button.inline("رجوع", b"back_main")]])
        return
    total = sum(c['count'] for c in accs)
    balance = get_balance(user.id)
    kind_label = {'clean': 'سليمة ✅', 'old': 'أرقام قديمة', 'old_spam': OLD_SPAM_LABEL, 'unverified': '🃏 أرقام سبام مزيف', 'fake': 'مزيف واحتيالي ⚠️', 'monthly': '🌟 أرقام مميزة شهر', 'daily': DAILY_NUMBERS_LABEL, 'bimonthly': BIMONTHLY_NUMBERS_LABEL, 'random': RANDOM_NUMBERS_LABEL, 'spam': '📛 أرقام سبام', 'spam_mix': f'(EMOJI{SPAM_MIX_EMOJI_ID}) {SPAM_MIX_LABEL}'}.get(kind, 'سبام 📛')
    text = (
        "🛒 *قسم شراء الجلسات (Sessions)* 🛒\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 رصيدك: `{balance:.2f}$`\n\n"
        f"🌍 اختر الدولة المطلوبة لشراء الجلسات منها ({kind_label}):\n"
        "⚠️ يرجى ملاحظة: عند شراء الجلسات لا يوجد استرجاع."
    )
    await safe_edit(event, text, buttons=kb_session_countries(accs, user.id, page, kind=kind))

async def on_bs_country_selected(event, user, code, kind='clean'):
    await event.answer()
    if code == "mixed":
        name = MIXED_LABEL
        price = MIXED_PRICE
        c_code = "MIXED"
    elif code == "fake":
        name = FAKE_LABEL
        price = FAKE_PRICE
        c_code = "FAKE"
    else:
        country = db['countries'].get(code)
        if not country:
            return await event.answer("الدولة غير متوفرة.", alert=True)
        name = old_numbers_label(user.id) if code == OLD_NUMBERS_CODE else country['name']
        price = country['price']
        c_code = f"+{code}"
    
    set_user_state(user.id, "awaiting_sessions_quantity", cid=code, kind=kind)
    if code == "mixed":
        text = (
            f"الدولة المختارة: [ {name} ]\n"
            f"الخادم: [ الخادم الرئيسي ]\n"
            f"السعر: [ {price}$ 💰 ]\n"
            "الرجاء إرسال الكمية المطلوبة الآن:\n"
            "[ الحد الأدنى: 1 | الحد الأقصى: 75 ]"
        )
    else:
        # إزالة كلمة "مخطلت" من اسم الدولة إذا وجدت في الأرقام العادية
        clean_name = name.replace("مخطلت", "").replace("📛", "").replace("6267219374994626613", "").strip()
        text = (
            f"الدولة المختارة: [ {clean_name} 🌍 ]\n"
            f"رمز الدولة: [ {c_code} ]\n"
            f"الخادم: [ الخادم الرئيسي ]\n"
            f"السعر: [ {price}$ 💰 ]\n"
            "الرجاء إرسال الكمية المطلوبة الآن:\n"
            "[ الحد الأدنى: 1 | الحد الأقصى: 75 ]"
        )
    await safe_edit(event, text, buttons=[[Button.inline("رجوع", b"buy_sessions")]])

async def on_sessions_confirm_show(event, user, code, qty, kind='clean'):
    if code == "mixed":
        name = MIXED_LABEL
        price_per = MIXED_PRICE
        c_code = "MIXED"
    elif code == "fake":
        name = FAKE_LABEL
        price_per = FAKE_PRICE
        c_code = "FAKE"
    else:
        country = db['countries'].get(code)
        if not country: return await event.answer("خطأ.", alert=True)
        name = old_numbers_label(user.id) if code == OLD_NUMBERS_CODE else country['name']
        price_per = country['price']
        c_code = f"+{code}"
    
    total_price = round(price_per * qty, 2)
    balance = get_balance(user.id)
    
    if code == "mixed":
        text = (
            f"• تم الاختِيار: [ {name} ].\n"
            f"• رمِز الدولَة: [ MIXED ].(EMOJI5895425908973506277)\n"
            f"• الخَادِم: [ الخادم الرئيسي (EMOJI5897870213516365139) ].\n"
            f"• السِعر: [ {fmt_amt(price_per, user.id)} 💰 ].\n"
            f"• الكَمية: [ {qty} ]. 📦\n"
            f"• السعر الإجمالي: [ {fmt_amt(total_price, user.id)} (EMOJI4988196741518984970) ].\n"
            "• التَحقُق بخِطوتَين: [ مرفق في الملفات ]. (EMOJI5895572268574051666)\n\n"
            "(EMOJI5895425908973506277) اضغط على زر التأكيد ادناه، لتأكيد عملية الشراء (EMOJI5800703239938645256).\n\n"
            "(EMOJI5800872667808539150) يرجى الملاحظة: عند شراء ( sessions/Tdata ) لا يوجد استرجاع أو استبدال(EMOJI5800982150819880883).\n\n"
            "يُرجى شراء كمية بسيطة أولاً لاختبار الجودة وتجنب أي مشاكل غير ضرورية.(EMOJI5798502833703625629)\n\n"
            "(EMOJI5800872667808539150) تحذير: جميع الحسابات التي تستلمها مختبرة ومضمونة للعمل بشكل ممتاز.(EMOJI5895425908973506277)\n\n"
            "لا نتحمل أي مسؤولية في حال إساءة استخدام sessions/Tdata، ولن تُقبل أي شكوى دون إثبات كافٍ وسبب مقنع خلال 30 دقيقة، وأي شكوى بعد 30 دقيقة سيتم رفضها .(EMOJI5800982150819880883)\n\n"
            "(EMOJI5800872667808539150) ملاحظة: جميع حساباتنا تأتي مع [app_id:4] ??"
        )
    else:
        # إزالة كلمة "مخطلت" من اسم الدولة إذا وجدت في الأرقام العادية
        clean_name = name.replace("مخطلت", "").replace("📛", "").replace("6267219374994626613", "").strip()
        text = (
            f"• تم الاختِيار: [ {clean_name} ].\n"
            f"• رمِز الدولَة: [ {c_code} ].(EMOJI5895425908973506277)\n"
            f"• الخَادِم: [ الخادم الرئيسي (EMOJI5897870213516365139) ].\n"
            f"• السِعر: [ {fmt_amt(price_per, user.id)} 💰 ].\n"
            f"• الكَمية: [ {qty} ]. 📦\n"
            f"• السعر الإجمالي: [ {fmt_amt(total_price, user.id)} (EMOJI4988196741518984970) ].\n"
            "• التَحقُق بخِطوتَين: [ مرفق في الملفات ]. (EMOJI5895572268574051666)\n\n"
            "(EMOJI5895425908973506277) اضغط على زر التأكيد ادناه، لتأكيد عملية الشراء (EMOJI5800703239938645256).\n\n"
            "(EMOJI5800872667808539150) يرجى الملاحظة: عند شراء ( sessions/Tdata ) لا يوجد استرجاع أو استبدال(EMOJI5800982150819880883).\n\n"
            "يُرجى شراء كمية بسيطة أولاً لاختبار الجودة وتجنب أي مشاكل غير ضرورية.(EMOJI5798502833703625629)\n\n"
            "(EMOJI5800872667808539150) تحذير: جميع الحسابات التي تستلمها مختبرة ومضمونة للعمل بشكل ممتاز.(EMOJI5895425908973506277)\n\n"
            "لا نتحمل أي مسؤولية في حال إساءة استخدام sessions/Tdata، ولن تُقبل أي شكوى دون إثبات كافٍ وسبب مقنع خلال 30 دقيقة، وأي شكوى بعد 30 دقيقة سيتم رفضها .(EMOJI5800982150819880883)\n\n"
            "(EMOJI5800872667808539150) ملاحظة: جميع حساباتنا تأتي مع [app_id:4] ??"
        )
    await safe_edit(event, text, buttons=kb_confirm_sessions(code, qty, kind=kind))

async def on_execute_sessions(event, user, code, qty, kind='clean'):
    # لا نرسل جوابًا مبكرًا حتى تبقى نافذة نقص الرصيد قادرة على الظهور.
    valid_accounts = []
    committed_purchase_records = []
    total_price = 0.0
    price_per = 0.0
    country_name = ""

    async with _PURCHASE_FLOW_LOCK:
        if code == "mixed":
            available = [a for a in db['accounts']
                         if account_purchase_category(a) == 'spam'
                         and a['status'] == 'available']
            price_per = MIXED_PRICE
            country_name = MIXED_LABEL
        elif code == "fake":
            available = [a for a in db['accounts']
                         if account_purchase_category(a) == 'fake'
                         and a['status'] == 'available']
            price_per = min(
                (a.get('price', FAKE_PRICE) for a in available),
                default=FAKE_PRICE,
            )
            country_name = FAKE_LABEL
        else:
            country = db['countries'].get(code)
            if not country:
                return await event.answer("خطأ.", alert=True)
            available = [a for a in db['accounts']
                         if a['country_code'] == code
                         and a['status'] == 'available'
                         and account_purchase_category(a) == kind]
            price_per = min((a.get('price', country['price']) for a in available), default=country['price'])
            country_name = country['name']

        if len(available) < qty:
            return await event.answer(f"الكمية المتاحة حالياً هي {len(available)} فقط.", alert=True)

        total_price = round(price_per * qty, 2)
        balance = get_balance(user.id)
        if balance < total_price:
            return await send_msg(
                event,
                f"⚠️ رصيدك لا يكفي، تحتاج إلى: {fmt_amt(total_price, user.id)}",
                buttons=[
                    [Button.inline("💳 شحن الرصيد", b"deposit")],
                    [Button.inline("🔙 رجوع", b"back_main")],
                ]
            )

        # تحقق نهائي قبل الخصم أو الحجز؛ الجلسة غير المؤكدة لا تدخل عملية البيع.
        valid_accounts = []
        for candidate in available:
            ok, reason = await verify_account_session_for_sale(candidate)
            if ok:
                valid_accounts.append(candidate)
            else:
                logger.warning(f"⚠️ تم تجاوز جلسة غير مؤكدة قبل البيع {candidate.get('phone')}: {reason}")
            if len(valid_accounts) >= qty:
                break
        if len(valid_accounts) < qty:
            return await event.answer(
                f"لم يتم العثور على {qty} جلسة مؤكدة حاليًا. المتاح المؤكد: {len(valid_accounts)}. لم يتم الخصم.",
                alert=True
            )
        update_balance(user.id, -total_price)
        reserve_ts = datetime.now().isoformat()
        for acc in valid_accounts:
            acc['status'] = 'reserved'
            acc['reserved_for'] = user.id
            acc['reserved_at'] = reserve_ts

    await safe_edit(event, "جاري تجهيز الجلسات... يرجى الانتظار.")
    await safe_edit(event, "جاري إنشاء ملف الجلسات وإرساله...")

    zip_path = os.path.join(SESSIONS_DIR, f"sessions_{user.id}_{int(time.time())}.zip")
    temp_dir = f"temp_sessions_{user.id}_{int(time.time())}"
    os.makedirs(temp_dir, exist_ok=True)

    success_count = 0
    failed_accounts = []
    try:
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for acc in valid_accounts:
                phone_clean = str(acc.get('phone', '')).replace('+', '')
                session_str = acc.get('session', '')
                password = acc.get('password', '')
                try:
                    session_file_path = os.path.join(temp_dir, f"{phone_clean}.session")
                    temp_ss = StringSession(session_str)
                    temp_client = TelegramClient(session_file_path, API_ID, API_HASH)
                    temp_client.session.set_dc(temp_ss.dc_id, temp_ss.server_address, temp_ss.port)
                    temp_client.session.auth_key = temp_ss.auth_key
                    temp_client.session.save()
                    await temp_client.disconnect()

                    zipf.write(session_file_path, f"{phone_clean}.session")
                    now_ts = int(time.time())
                    json_data = {
                        "session_file": f"{phone_clean}.session",
                        "phone": phone_clean,
                        "register_time": now_ts - 86400,
                        "session_str": session_str,
                        "app_id": API_ID,
                        "app_hash": API_HASH,
                        "sdk": "2.0",
                        "app_version": "10.3.2",
                        "device": "iPhone 14 Pro",
                        "perf_cat": 2,
                        "tz_offset": 10800,
                        "last_check_time": now_ts,
                        "avatar": "null",
                        "first_name": "",
                        "last_name": "",
                        "sex": 0,
                        "lang_code": "en",
                        "system_lang_code": "en-US",
                        "twoFA": password,
                        "ipv6": False,
                        "module": "AddAccount",
                        "program": "https://telegram.org/",
                        "client_type": "telethon"
                    }
                    zipf.writestr(f"{phone_clean}.json", json.dumps(json_data, indent=2, ensure_ascii=False))
                    success_count += 1
                except Exception as session_error:
                    failed_accounts.append((acc, str(session_error)))
                    logger.warning("تعذر تجهيز جلسة %s وسيتم استرداد قيمتها: %s", phone_clean, session_error)

        if success_count == 0:
            raise Exception("فشل إنشاء أي ملف جلسة")

        # استرداد قيمة الجلسات الفاشلة فقط، مع إبقاء خصم الجلسات الناجحة.
        failed_refund = round(price_per * len(failed_accounts), 2)
        total_price = round(price_per * success_count, 2)
        if failed_accounts:
            async with _PURCHASE_FLOW_LOCK:
                update_balance(user.id, failed_refund)
                for failed_acc, failed_reason in failed_accounts:
                    failed_acc['status'] = 'available'
                    failed_acc.pop('reserved_for', None)
                    failed_acc.pop('reserved_at', None)
                    failed_acc['last_session_build_error'] = failed_reason[:500]
                save_db(db)

        async with _PURCHASE_FLOW_LOCK:
            # لا تُسجّل ولا تُباع الجلسات الفاشلة؛ تُباع الناجحة فقط.
            failed_ids = {acc.get('id') for acc, _ in failed_accounts}
            valid_accounts = [acc for acc in valid_accounts if acc.get('id') not in failed_ids]
            purchase_time = datetime.now().isoformat()
            for acc in valid_accounts:
                acc['status'] = 'sold'
                acc['sold_to'] = user.id
                acc['sold_at'] = purchase_time
                acc.pop('reserved_for', None)
                acc.pop('reserved_at', None)

                purchase_id = _next('next_purchase_id')
                purchase_record = {
                    'id': purchase_id,
                    'user_id': user.id,
                    'account_id': acc['id'],
                    'phone': acc['phone'],
                    'country_code': acc['country_code'],
                    'country_name': acc['country_name'],
                    'price': price_per,
                    'password': acc.get('password', ''),
                    'purchased_at': purchase_time,
                    'type': 'session'
                }
                db['purchases'].append(purchase_record)
                committed_purchase_records.append(purchase_record)
            db['settings']['sold_numbers_count'] = (
                db['settings'].get('sold_numbers_count', 0) + len(valid_accounts)
            )

            sold_ids = {a['id'] for a in valid_accounts}
            db['accounts'] = [a for a in db['accounts'] if a['id'] not in sold_ids]
            save_db(db)

        order_id = f"SESS{random.randint(10**18, 10**19-1)}"
        clean_country_name = country_name.replace("مخطلت", "").replace("📛", "").replace("6267219374994626613", "").strip() if code != "mixed" else country_name
        if not clean_country_name:
            clean_country_name = "مخطلت"
        remaining_balance = get_balance(user.id)
        caption = (
            "*تم اكتمال طلب الجلسات بنجاح* ✨\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"*رقم الطلب:* `{order_id}`\n"
            f"*الحالة:* `اكتمل ✅`\n"
            f"*الكمية المطلوبة:* `{qty}`\n"
            f"*المكتمل:* `{len(valid_accounts)}`\n"
            f"*الفاشل:* `{len(failed_accounts)}`\n"
            f"*المسترد:* `{fmt_amt(failed_refund, user.id)}`\n"
            f"*الدولة:* `{clean_country_name}`\n"
            f"*السعر المُفرد:* `{fmt_amt(price_per, user.id)}`\n"
            f"*السعر الإجمالي:* `{fmt_amt(total_price, user.id)}`\n"
            f"*تم الخصم من رصيدك:* `{fmt_amt(total_price, user.id)}`\n"
            f"*رصيدك المتبقي:* `{fmt_amt(remaining_balance, user.id)}`\n\n"
            "*تمت المعالجة بنجاح، ملف الجلسات مرفق أدناه.*\n"
            "*التحقق بخطوتين مُرفق داخل ملفات json.*"
        )
        await bot.send_file(event.chat_id, zip_path, caption=caption, file_name="MOSCOW.zip")
        if failed_accounts:
            await event.respond(
                f"↩️ تم استرداد قيمة {len(failed_accounts)} جلسة لم تدخل الملف بسبب خلل.\n"
                f"💰 المبلغ المسترد: `{fmt_amt(failed_refund, user.id)}`\n"
                f"✅ تم تسليم {len(valid_accounts)} جلسة بنجاح."
            )

        try:
            clean_country_name = country_name.replace("مخطلت", "").replace("📛", "").replace("6267219374994626613", "").strip() if code != "mixed" else country_name
            log_text = (
                "✅ بيع جلسات جديدة\n"
                f"👤 المستخدم: `{user.id}`\n"
                f"🌍 الدولة: {clean_country_name}\n"
                f"🔢 الكمية: {qty}\n"
                f"✅ المكتمل: {len(valid_accounts)}\n"
                f"↩️ المسترد: {fmt_amt(failed_refund, user.id)}\n"
                f"💰 المبلغ: {fmt_amt(total_price, user.id)}\n"
                f"📦 الطلب: `{order_id}`"
            )
            await bot.send_message(LOG_CHANNEL_ID, log_text)
        except Exception as e:
            logger.error(f"Failed to send session sale log: {e}")
    except Exception as e:
        logger.error(f"Error executing session purchase: {e}")
        async with _PURCHASE_FLOW_LOCK:
            if total_price > 0:
                update_balance(user.id, total_price)
            if committed_purchase_records:
                # إذا فشل إرسال الملف بعد الحفظ، أعد الحالة إلى ما قبل الشراء
                # حتى لا يُخصم الرصيد وتختفي الحسابات دون تسليمها.
                db['purchases'] = [
                    p for p in db.get('purchases', [])
                    if p not in committed_purchase_records
                ]
                sold_ids = {p.get('account_id') for p in committed_purchase_records}
                for acc in valid_accounts:
                    if acc.get('id') in sold_ids:
                        acc['status'] = 'available'
                        acc.pop('sold_to', None)
                        acc.pop('sold_at', None)
                db['accounts'].extend(
                    acc for acc in valid_accounts
                    if acc.get('id') in sold_ids and acc not in db['accounts']
                )
                db['settings']['sold_numbers_count'] = max(
                    0,
                    db['settings'].get('sold_numbers_count', 0)
                    - len(committed_purchase_records)
                )
            for acc in valid_accounts:
                if acc in db['accounts'] and acc.get('reserved_for') == user.id:
                    acc['status'] = 'available'
                    acc.pop('reserved_for', None)
                    acc.pop('reserved_at', None)
            save_db(db)
        refunded_amount = total_price if total_price > 0 else 0.0
        await event.respond(
            "⚠️ حدثت مشكلة أثناء تجهيز ملف الجلسات.\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💰 *تم استرداد المبلغ المخصص للجلسات:* `{fmt_amt(refunded_amount, user.id)}`\n"
            f"💳 *تمت إضافة المبلغ إلى رصيدك:* `{fmt_amt(refunded_amount, user.id)}`\n"
            f"📊 *رصيدك الحالي:* `{fmt_amt(get_balance(user.id), user.id)}`\n\n"
            "✅ لم يضِع أي مبلغ من رصيدك."
        )
    finally:
        if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
        if os.path.exists(zip_path): os.remove(zip_path)

async def on_buy_menu(event, user, page=0, kind='clean'):
    await event.answer()
    if kind == 'spam':
        accs = available_spam_accounts_by_country()
    elif kind == 'spam_mix':
        accs = available_spam_mix_accounts_by_country()
    elif kind == 'fake':
        accs = available_fake_accounts_by_country()
    elif kind == 'unverified':
        accs = available_unverified_accounts_by_country()
    elif kind == 'old_spam':
        accs = available_old_spam_accounts_by_country()
    elif kind == 'old':
        accs = available_old_accounts_by_country()
    elif kind == 'monthly':
        accs = available_monthly_accounts_by_country()
    elif kind == 'daily':
        accs = available_daily_accounts_by_country()
    elif kind == 'bimonthly':
        accs = available_bimonthly_accounts_by_country()
    elif kind == 'random':
        accs = available_random_accounts_by_country()
    else:
        accs = available_accounts_by_country()
    if not accs:
        text = (
            "⚠️ *لا توجد حسابات متاحة حالياً*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔐 جميع الأرقام نُفذت أو لم تُضف أرقام بعد.\n"
            "⚡ يرجى المحاولة لاحقاً."
        )
        await safe_edit(event, text, buttons=[[Button.inline("رجوع", b"back_main")]])
        return
    total = sum(c['count'] for c in accs)
    balance = get_balance(user.id)
    kind_label = {'clean': 'سليمة ✅', 'old': 'أرقام قديمة', 'old_spam': OLD_SPAM_LABEL, 'unverified': '🃏 أرقام سبام مزيف', 'fake': 'مزيف واحتيالي ⚠️', 'monthly': '🌟 أرقام مميزة شهر', 'daily': DAILY_NUMBERS_LABEL, 'bimonthly': BIMONTHLY_NUMBERS_LABEL, 'random': RANDOM_NUMBERS_LABEL, 'spam': '📛 أرقام سبام', 'spam_mix': f'(EMOJI{SPAM_MIX_EMOJI_ID}) {SPAM_MIX_LABEL}'}.get(kind, 'سبام 📛')
    text = (
        "🛒 *الدول المتاحة للشراء* 🛒\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 رصيدك: `{fmt_amt(balance, user.id)}`\n\n"
        f"🔐 اختر الدولة التي تريد شراء رقم منها ({kind_label}):\n"
    )
    await safe_edit(event, text, buttons=kb_countries(user.id, accs, page, kind=kind))


async def check_purchase_balance_message(event, user_id, required_price):
    """رسالة نقص الرصيد داخل المحادثة مع Custom Emojis وبدون تكرار رمز العملة."""
    balance = float(get_balance(user_id) or 0.0)
    required_price = float(required_price or 0.0)

    if balance < required_price:
        return await send_msg(
            event,
            f"⚠️ رصيدك لا يكفي، تحتاج إلى: {fmt_amt(required_price, user_id)}",
            buttons=[
                [Button.inline("💳 شحن الرصيد", b"deposit")],
                [Button.inline("🔙 رجوع", b"back_main")],
            ]
        )

    return True


async def on_confirm_buy(event, user, code, kind='clean'):
    if kind == 'old_spam':
        available = [a for a in db['accounts']
                     if account_purchase_category(a) == 'old_spam'
                     and a.get('status') == 'available'
                     and (not code or code == OLD_SPAM_CODE or a.get('country_code') == code)]
        if not available: return await safe_edit(event, f'نفدت {OLD_SPAM_LABEL}.', buttons=kb_back())
        current_price = min(a.get('price', OLD_SPAM_PRICE) for a in available)
        if not await check_purchase_balance_message(event, user.id, current_price): return
        text = f"⚡ *تأكيد شراء {OLD_SPAM_LABEL}* ⚡\n\n💰 *السعر:* `{fmt_amt(current_price, user.id)}`\n📦 *المتاح:* `{len(available)}`\n\n🔐 هل تريد إتمام عملية الشراء؟"
        return await safe_edit(event, text, buttons=kb_confirm_buy(code, kind=kind))
    if kind in ('monthly', 'daily', 'bimonthly', 'random'):
        label = MONTHLY_NUMBERS_LABEL if kind == 'monthly' else (DAILY_NUMBERS_LABEL if kind == 'daily' else (BIMONTHLY_NUMBERS_LABEL if kind == 'bimonthly' else RANDOM_NUMBERS_LABEL))
        default_price = MONTHLY_NUMBERS_PRICE if kind == 'monthly' else (DAILY_NUMBERS_PRICE if kind == 'daily' else (BIMONTHLY_NUMBERS_PRICE if kind == 'bimonthly' else RANDOM_NUMBERS_PRICE))
        available = [a for a in db['accounts'] if account_purchase_category(a) == kind and a.get('status') == 'available']
        if not available: return await safe_edit(event, f'نفدت {label}.', buttons=kb_back())
        current_price = min(a.get('price', default_price) for a in available)
        if not await check_purchase_balance_message(event, user.id, current_price): return
        text = f"⚡ *تأكيد شراء {label}* ⚡\n\n💰 *السعر:* `{fmt_amt(current_price, user.id)}`\n\n🔐 هل تريد إتمام عملية الشراء؟"
        return await safe_edit(event, text, buttons=kb_confirm_buy(code, kind=kind))
    if code == UNVERIFIED_CODE:
        available = [a for a in db['accounts'] if account_purchase_category(a) == 'unverified' and a.get('status') == 'available']
        if not available:
            return await safe_edit(event, f'نفدت حسابات {UNVERIFIED_LABEL} حالياً.', buttons=kb_back())
        current_price = min(a.get('price', UNVERIFIED_PRICE) for a in available)
        if not await check_purchase_balance_message(event, user.id, current_price): return
        balance = get_balance(user.id)
        text = f"⚡ *تأكيد شراء {UNVERIFIED_LABEL}* ⚡\n\n💰 *السعر:* `{current_price}$`\n📦 *الكمية المتاحة:* `{len(available)}` حساب\n💳 *رصيدك الحالي:* `${balance:.2f}`\n\n🔐 هل تريد إتمام عملية الشراء؟"
        return await safe_edit(event, text, buttons=kb_confirm_buy(UNVERIFIED_CODE))
    if code == "fake":
        fake_country_codes = [c for c, data in db['countries'].items() if FAKE_LABEL in data.get('name', '') or "مزيف و احتيالي" in data.get('name', '')]
        available = [a for a in db['accounts']
                     if account_purchase_category(a) == 'fake'
                     and a['status'] == 'available']
        if not available:
            return await safe_edit(event, f"نفدت حسابات {FAKE_LABEL} حالياً.", buttons=kb_back())
            
        prices = [a.get('price', FAKE_PRICE) for a in available]
        current_price = min(prices) if prices else FAKE_PRICE
        if not await check_purchase_balance_message(event, user.id, current_price):
            return
        
        balance = get_balance(user.id)
        enough = "✓" if balance >= current_price else "⚠️"
        text = (
            "⚡ *تأكيد عملية الشراء* ⚡\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🌍 *المجموعة:* {FAKE_LABEL}\n"
            f"💰 *السعر:* `${current_price}`\n"
            f"📦 *الكمية المتاحة:* `{len(available)}` حساب\n"
            f"💳 *رصيدك الحالي:* `${balance:.2f}` {enough}\n\n"
            "🔐 هل تريد إتمام عملية الشراء؟"
        )
        await safe_edit(event, text, buttons=kb_confirm_buy("fake"))
    elif code == "mixed":
        mixed_country_codes = [c for c, data in db['countries'].items() if "مخطلت" in data.get('name', '')]
        available = [a for a in db['accounts']
                     if account_purchase_category(a) == 'spam'
                     and a['status'] == 'available']
        if not available:
            return await safe_edit(event, "نفدت حسابات المخطلت حالياً.", buttons=kb_back())
        # جلب أقل سعر متاح في حسابات المخطلت
        prices = [a.get('price', MIXED_PRICE) for a in available]
        current_price = min(prices) if prices else MIXED_PRICE
        if not await check_purchase_balance_message(event, user.id, current_price):
            return
        
        balance = get_balance(user.id)
        enough = "✓" if balance >= current_price else "⚠️"
        text = (
            "⚡ *تأكيد عملية الشراء* ⚡\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🌍 *الدولة:* {MIXED_LABEL}\n"
            f"💰 *السعر:* `{fmt_amt(current_price, user.id)}`\n"
            f"📦 *الكمية المتاحة:* `{len(available)}` حساب\n"
            f"💳 *رصيدك الحالي:* `{fmt_amt(balance, user.id)}` {enough}\n\n"
            "🔐 هل تريد إتمام عملية الشراء؟"
        )
        await safe_edit(event, text, buttons=kb_confirm_buy("mixed"))
    else:
        country = db['countries'].get(code)
        # توافق مع زر الأرقام القديمة في قواعد البيانات السابقة.
        if not country and code == OLD_NUMBERS_CODE:
            country = {'name': OLD_NUMBERS_LABEL, 'price': OLD_NUMBERS_PRICE}
            db['countries'][code] = country
            save_db(db)
        if not country:
            return await safe_edit(event, "الدولة غير موجودة في النظام.", buttons=kb_back())
        available = [a for a in db['accounts']
                     if a['country_code'] == code
                     and a['status'] == 'available'
                     and account_purchase_category(a) == kind]
        if not available:
            return await safe_edit(event, f"نفدت حسابات {country['name']} حالياً.", buttons=kb_back())
        # جلب أقل سعر متاح في حسابات هذه الدولة
        prices = [a.get('price', country['price']) for a in available]
        current_price = min(prices) if prices else country['price']
        if not await check_purchase_balance_message(event, user.id, current_price):
            return
        
        balance = get_balance(user.id)
        enough = "✓" if balance >= current_price else "⚠️"
        clean_name = country['name'].replace("مخطلت", "").replace("📛", "").replace("6267219374994626613", "").strip()
        text = (
            "⚡ *تأكيد عملية الشراء* ⚡\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🌍 *الدولة:* {clean_name}\n"
            f"💰 *السعر:* `{fmt_amt(current_price, user.id)}`\n"
            f"📦 *الكمية المتاحة:* `{len(available)}` حساب\n"
            f"💳 *رصيدك الحالي:* `{fmt_amt(balance, user.id)}` {enough}\n\n"
            "🔐 هل تريد إتمام عملية الشراء؟"
        )
        await safe_edit(event, text, buttons=kb_confirm_buy(code, kind=kind))

async def on_execute_buy(event, user, code, kind='clean'):
    # قفل المستخدم يمنع Double Spending لنفس المستخدم، والقفل العام يحمي DB.
    async with get_user_purchase_lock(user.id):
        # لا نرسل Answer قبل فحص الرصيد حتى نتمكن من عرض تنبيه Popup عند عدم كفاية الرصيد.
        async with _PURCHASE_FLOW_LOCK:
            if kind in ('monthly', 'daily', 'bimonthly', 'random'):
                default_price = MONTHLY_NUMBERS_PRICE if kind == 'monthly' else (DAILY_NUMBERS_PRICE if kind == 'daily' else (BIMONTHLY_NUMBERS_PRICE if kind == 'bimonthly' else RANDOM_NUMBERS_PRICE))
                label = MONTHLY_NUMBERS_LABEL if kind == 'monthly' else (DAILY_NUMBERS_LABEL if kind == 'daily' else (BIMONTHLY_NUMBERS_LABEL if kind == 'bimonthly' else RANDOM_NUMBERS_LABEL))
                available = [a for a in db['accounts'] if account_purchase_category(a) == kind and a.get('status') == 'available']
                if not available: return await safe_edit(event, f'نفدت {label}.', buttons=kb_back())
                account = random.choice(available)
                price = account.get('price', default_price)
            elif kind == 'old_spam':
                # هذا النوع له علم مستقل؛ لا يسقط إلى الفلتر العام الذي
                # لا يعرف kind='old_spam' فيعتبر القائمة فارغة.
                available = [
                    a for a in db['accounts']
                    if account_purchase_category(a) == 'old_spam'
                    and a.get('status') == 'available'
                    and (not code or code == OLD_SPAM_CODE or a.get('country_code') == code)
                ]
                if not available:
                    return await safe_edit(event, f'نفدت {OLD_SPAM_LABEL}.', buttons=kb_back())
                account = random.choice(available)
                price = account.get('price', OLD_SPAM_PRICE)
            elif code == UNVERIFIED_CODE:
                available = [a for a in db['accounts'] if account_purchase_category(a) == 'unverified' and a.get('status') == 'available']
                if not available: return await safe_edit(event, f'نفدت حسابات {UNVERIFIED_LABEL}.', buttons=kb_back())
                account = random.choice(available)
                price = account.get('price', UNVERIFIED_PRICE)
            elif code == "fake":
                fake_country_codes = [c for c, data in db['countries'].items() if FAKE_LABEL in data.get('name', '') or "مزيف و احتيالي" in data.get('name', '')]
                available = [a for a in db['accounts']
                             if account_purchase_category(a) == 'fake'
                             and a['status'] == 'available']
                if not available:
                    return await safe_edit(event, f"نفدت حسابات {FAKE_LABEL}.", buttons=kb_back())
                account = random.choice(available)
                price = account.get('price', FAKE_PRICE)
            elif code == "mixed":
                mixed_country_codes = [c for c, data in db['countries'].items() if "مخطلت" in data.get('name', '')]
                available = [a for a in db['accounts']
                             if account_purchase_category(a) == 'spam'
                             and a['status'] == 'available']
                if not available:
                    return await safe_edit(event, "نفدت حسابات المخطلت.", buttons=kb_back())
                account = random.choice(available)
                price = account.get('price', MIXED_PRICE)
            else:
                country = db['countries'].get(code)
                if not country and code == OLD_NUMBERS_CODE:
                    country = {'name': OLD_NUMBERS_LABEL, 'price': OLD_NUMBERS_PRICE}
                    db['countries'][code] = country
                    save_db(db)
                if not country:
                    return await safe_edit(event, "الدولة غير موجودة.", buttons=kb_back())
                available = [a for a in db['accounts']
                             if a['country_code'] == code
                             and a['status'] == 'available'
                             and account_purchase_category(a) == kind]
                if not available:
                    return await safe_edit(event, f"نفدت حسابات {country['name']}.", buttons=kb_back())
                account = available[0]
                price = account.get('price', country['price'])

            verified, verify_error = await verify_account_session_for_sale(account)
            if not verified:
                logger.warning(f"⚠️ منع بيع جلسة غير مؤكدة {account.get('phone')}: {verify_error}")
                safe_reason = str(verify_error or "سبب غير محدد")[:300]
                reason_lower = safe_reason.lower()
                permanent_failure = any(marker in reason_lower for marker in (
                    "الجلسة غير مصرح بها",
                    "جلسة غير مصرح بها",
                    "مفتاح الجلسة غير مسجل",
                    "هوية الجلسة لا تطابق",
                    "الرقم داخل الجلسة",
                    "auth key",
                    "unauthorized",
                    "mismatch",
                ))
                if permanent_failure:
                    # عزل الجلسة التالفة من المخزون حتى لا تُعرض للمستخدمين
                    # مرة أخرى، مع الاحتفاظ بنسخة أرشيفية للتدقيق.
                    account['status'] = 'invalid_session'
                    account['invalidated_at'] = datetime.now().isoformat()
                    account['invalidated_reason'] = safe_reason
                    archive_session_snapshot(
                        account.get('phone'), account.get('session', ''),
                        reason="invalid_before_sale"
                    )
                    if account in db.get('accounts', []):
                        db['accounts'].remove(account)
                    save_db(db)
                    try:
                        session_path = os.path.join(
                            SESSIONS_DIR,
                            f"{str(account.get('phone', '')).replace('+', '').strip()}.session"
                        )
                        if os.path.exists(session_path):
                            os.remove(session_path)
                    except Exception as cleanup_error:
                        logger.warning("تعذر حذف ملف الجلسة المعزولة: %s", cleanup_error)
                    safe_reason += " — تمت إزالة الرقم من المخزون"
                return await safe_edit(
                    event,
                    "⚠️ لم يتم بيع هذا الرقم لأن الجلسة تحتاج فحصًا إضافيًا.\n"
                    f"🔻 السبب: `{safe_reason}`\n"
                    "لم يتم خصم أي مبلغ، وسيبقى الرقم محفوظًا للمراجعة.",
                    buttons=kb_back()
                )

            balance = get_balance(user.id)
            if balance < price:
                return await check_purchase_balance_message(event, user.id, price)

            update_balance(user.id, -price)
            account['status'] = 'sold'
            account['sold_to'] = user.id
            account['sold_at'] = datetime.now().isoformat()
            account['price'] = price

            purchase_id = _next('next_purchase_id')
            db['settings']['sold_numbers_count'] = db['settings'].get('sold_numbers_count', 0) + 1
            db['purchases'].append({
                'id': purchase_id,
                'user_id': user.id,
                'account_id': account['id'],
                'phone': account['phone'],
                'country_code': account['country_code'],
                'country_name': account['country_name'],
                'price': price,
                'password': account.get('password'),
                'purchased_at': datetime.now().isoformat()
            })

            if account in db['accounts']:
                db['accounts'].remove(account)

            save_db(db)

        # الأرقام المميزة اليومية/الشهرية لها مدد مختلفة؛ باقي الأنواع تبقى 24 ساعة.
        if kind == 'bimonthly' or account.get('is_bimonthly', False):
            PURCHASE_SESSION_TIMEOUT = 60 * 24 * 60 * 60  # شهران تقريباً
        else:
            PURCHASE_SESSION_TIMEOUT = 24 * 60 * 60  # 24 ساعة (السلوك السابق لبقية الأقسام)
        expiry = time.time() + PURCHASE_SESSION_TIMEOUT
        active_sessions[user.id] = {
            'session': account['session'],
            'phone': account['phone'],
            'account_id': account['id'],
            'expiry': expiry,
            'logged_out': False,
            'last_code_request': 0
        }
        # ===================== رسالة التسليم المميزة (Premium Delivery) =====================
        order_id = f"MOS{random.randint(10**15, 10**16 - 1)}"
        remaining_balance = get_balance(user.id)
        raw_country = account.get('country_name', 'مخطلت')
        clean_country = raw_country.replace("مخطلت", "").replace("📛", "").replace("6267219374994626613", "").strip()
        if not clean_country:
            clean_country = "مخطلت"
        if kind == 'bimonthly' or account.get('is_bimonthly', False):
            account_type = BIMONTHLY_NUMBERS_LABEL
        elif kind == 'monthly' or account.get('is_monthly', False):
            account_type = MONTHLY_NUMBERS_LABEL
        elif code == "fake" or account.get('is_fake', False):
            account_type = "مزيف احتيالي"
        elif code == "mixed" or account.get('is_spam', False):
            account_type = "مخطلت (Mixed)"
        else:
            account_type = "عادي (Premium)"
        phone_clean = str(account['phone']).lstrip('+')
        text = (
            f"- الرقم : `{phone_clean}`\n\n"
            "• حاول تسجيل الدخول بالرقم في تطبيق تيليجرام ثم اضغط على زر *جلب الكود*"
        )
        # تم تأكيد الشراء بنجاح؛ نغلق حالة الـ Callback قبل تعديل الرسالة.
        try:
            await event.answer("تم الشراء بنجاح")
        except Exception:
            pass
        await safe_edit(event, text, buttons=kb_after_purchase(account['id']))
        if AUTO_LOGOUT_AFTER_PURCHASE:
            asyncio.create_task(_auto_logout(user.id, account['id'], PURCHASE_SESSION_TIMEOUT))

        # ======================== إرسال لقناة التفعيلات بعد الشراء ========================
        try:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            phone_str = str(account['phone'])
            phone_digits = phone_str.lstrip('+')
            if len(phone_digits) > 6:
                masked_phone = f"+{phone_digits[:2]}xxx{phone_digits[-4:]}"
            else:
                masked_phone = f"+{phone_digits[:2]}****"

            country = account.get('country_name', 'مخطلت')
            platform = 'تليجرام'
            buyer_id = str(user.id)
            if len(buyer_id) > 6:
                masked_id = f"{buyer_id[:4]}xxx{buyer_id[-3:]}"
            else:
                masked_id = buyer_id

            country_display = country
            if kind == 'bimonthly' or account.get('is_bimonthly', False):
                country_display = "🌟 أرقام مميزة شهرين"
            elif kind == 'monthly' or account.get('is_monthly', False):
                country_display = "🌟 أرقام مميزة شهر"
            elif kind == 'daily' or account.get('is_daily_special', False):
                country_display = "🌟 أرقام مميزة يوم"
            elif kind == 'random' or account.get('is_random_special', False):
                country_display = "🎲 أرقام مميزة عشوائي"
            elif (
                kind == 'spam_mix'
                or account.get('is_spam_mix', False)
                or account_purchase_category(account) == 'spam_mix'
                or str(account.get('country_code', '')).startswith(SPAM_MIX_CODE)
                or SPAM_MIX_LABEL in str(account.get('country_name', ''))
            ):
                country_display = "سبام 📛Mix"
            elif code == "mixed" or account.get('is_spam', False):
                if "مخطلت" not in country_display:
                    country_display = f"مخطلت {country_display}"
                if "(EMOJI5895576786879647172)" not in country_display:
                    country_display += ""
            else:
                country_display = country_display.replace("مخطلت", "").replace("📛", "").replace("6267219374994626613", "").strip()

            country_line = (
                "🌍 الدولة سبام 📛Mix"
                if country_display == "سبام 📛Mix"
                else f"🌍 الدولة: {country_display}"
            )
            channel_text = (
                f"✅ تم تفعيل الرقم بنجاح\n\n"
                f"{country_line}\n"
                f"📱 المنصة: {platform}\n"
                f"📞 الرقم: {masked_phone}\n"
                f"💰 السعر: ${price}\n"
                f"👤 العميل: {masked_id}\n"
                f"🔑 كود التفعيل: في انتظار الاستلام\n"
                f"✅ الحالة: تم التفعيل\n\n"
                f"📅 التاريخ والوقت: {now_str}"
            )

            from telethon.tl.custom import Button as TlButton
            buy_buttons = [
                [TlButton.url("شراء أرقام", "https://t.me/MOSCOWiqBOT?start=buy")]
            ]

            if LOG_CHANNEL_ID:
                try:
                    # يجب تمرير النص عبر محوّل الإيموجيات المخصصة؛ الإرسال المباشر
                    # كان يعرض (EMOJI...) للمستخدم بدل الإيموجي نفسه.
                    channel_plain, channel_entities = _merge_entities_with_custom_emojis(bot, channel_text, 'md')
                    channel_bot_entities = _telethon_entities_to_bot_api(channel_entities)
                    resp = await fast_send_with_colored_buttons(
                        LOG_CHANNEL_ID,
                        channel_plain,
                        buy_buttons,
                        entities=channel_bot_entities
                    )
                    if not resp:
                        resp = await bot.send_message(
                            LOG_CHANNEL_ID,
                            channel_plain,
                            buttons=buy_buttons,
                            formatting_entities=channel_entities if channel_entities else None
                        )

                    # حفظ رقم رسالة قناة التفعيلات حتى نستبدل "في انتظار الاستلام"
                    # بالكود الحقيقي عند وصوله.
                    info = active_sessions.get(user.id)
                    if info:
                        msg_id = None
                        # fast_send_with_colored_buttons يستخدم Bot API ويعيد dict.
                        if isinstance(resp, dict):
                            result = resp.get("result") or {}
                            msg_id = result.get("message_id")
                        # fallback: Telethon Message object.
                        if not msg_id:
                            msg_id = getattr(resp, "id", None)
                        if msg_id:
                            info["log_msg_id"] = msg_id
                            info["log_text_base"] = channel_text
                except Exception:
                    channel_plain, channel_entities = _merge_entities_with_custom_emojis(bot, channel_text, 'md')
                    resp = await bot.send_message(
                        LOG_CHANNEL_ID,
                        channel_plain,
                        buttons=buy_buttons,
                        formatting_entities=channel_entities if channel_entities else None
                    )
                    info = active_sessions.get(user.id)
                    if info:
                        msg_id = None
                        if isinstance(resp, dict):
                            result = resp.get("result") or {}
                            msg_id = result.get("message_id")
                        if not msg_id:
                            msg_id = getattr(resp, "id", None)
                        if msg_id:
                            info["log_msg_id"] = msg_id
                            info["log_text_base"] = channel_text
        except Exception as e:
            logger.error(f"Failed to send purchase log to channel: {e}")

async def _auto_logout(user_id, account_id, delay):
    await asyncio.sleep(delay)
    info = active_sessions.get(user_id)
    if info and info.get('account_id') == account_id and not info.get('logged_out'):
        try:
            await logout_telethon_session(info['session'])
        except Exception as e:
            logger.error(f"auto-logout error: {e}")
        active_sessions.pop(user_id, None)

async def logout_telethon_session(session_string):
    """إلغاء جلسة البوت الحالية فقط، دون تسجيل خروج جلسات المستخدم الأخرى.

    Telegram يفصل التفويض الحالي الذي أنشأه هذا StringSession فقط؛ جلسة
    المستخدم على تطبيق تيليجرام تكون تفويضًا آخر ولا تتأثر.
    """
    client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
    try:
        await client.connect()
        if await client.is_user_authorized():
            await client.log_out()
        await client.disconnect()
        return True, "تم تسجيل خروج البوت من الرقم، وبقي حساب المستخدم مفتوحًا على تيليجرام"
    except Exception as e:
        try:
            await client.disconnect()
        except Exception:
            pass
        return False, f"خطأ: {e}"

async def clean_single_account(session_str, phone, first_name="MOSCOW", about="@MOSCOWiqBOT"):
    """تنظيف حساب واحد: مغادرة القنوات، حذف المحادثات، حظر البوتات، وتصفير الهوية"""
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    special_info = {"premium": False, "stars": 0}
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return False, "الجلسة غير صالحة", special_info
        
        # 0. فحص المميزات (Premium & Stars)
        try:
            me = await client.get_me()
            if me.premium:
                special_info["premium"] = True
            
            # فحص النجوم
            try:
                stars_status = await client(functions.payments.GetStarsStatusRequest(peer='me'))
                special_info["stars"] = stars_status.balance
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Error checking special features for {phone}: {e}")

        await asyncio.sleep(1) # تأخير لتجنب التجميد

        # 1. تغيير الاسم والنبذة التعريفية
        try:
            await client(functions.account.UpdateProfileRequest(
                first_name=first_name,
                last_name="",
                about=about
            ))
        except Exception as e:
            logger.error(f"Error updating profile for {phone}: {e}")

        await asyncio.sleep(1)

        # 2. حذف اسم المستخدم (Username)
        try:
            await client(functions.account.UpdateUsernameRequest(username=""))
        except Exception:
            pass

        await asyncio.sleep(1)

        # 3. حذف جميع الصور الشخصية
        try:
            photos = await client.get_profile_photos('me')
            if photos:
                await client(functions.photos.DeletePhotosRequest(id=photos))
        except Exception as e:
            logger.error(f"Error deleting photos for {phone}: {e}")

        await asyncio.sleep(1)

        # 4. حذف جميع القصص (Stories)
        try:
            await client(functions.stories.DeleteStoriesRequest(peer='me', id=[]))
        except Exception:
            pass

        await asyncio.sleep(1)

        # 5. تنظيف الحوارات (مغادرة القنوات، حظر البوتات، حذف المحادثات)
        try:
            async for dialog in client.iter_dialogs():
                try:
                    if dialog.is_channel:
                        await client(functions.channels.LeaveChannelRequest(dialog.entity))
                    elif dialog.is_group:
                        # للمجموعات العادية
                        if isinstance(dialog.entity, types.Chat):
                            await client(functions.messages.DeleteChatUserRequest(chat_id=dialog.entity.id, user_id='me'))
                        else:
                            # للمجموعات الخارقة (التي هي أيضاً قنوات في تيليجرام)
                            await client(functions.channels.LeaveChannelRequest(dialog.entity))
                    
                    if dialog.is_user:
                        if dialog.entity.bot:
                            # حظر البوتات
                            await client(functions.contacts.BlockRequest(id=dialog.entity))
                        # حذف تاريخ المحادثة
                        await client(functions.messages.DeleteHistoryRequest(peer=dialog.entity, max_id=0, revoke=True))
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"Error cleaning dialogs for {phone}: {e}")
        
        return True, "تم التنظيف وتصفير الهوية بنجاح", special_info
    except Exception as e:
        return False, str(e), special_info
    finally:
        await client.disconnect()

async def on_request_code(event, user, account_id):
    await event.answer("جاري جلب الكود...")
    purchase = next((p for p in db['purchases']
                     if p['account_id'] == account_id and str(p['user_id']) == str(user.id)), None)
    if not purchase:
        return await safe_edit(event, "هذا الحساب ليس ملكك.", buttons=kb_back())
    # حفظ حالة تسجيل خروج البوت في قاعدة البيانات يمنع إعادة استخدام الحساب
    # بعد إعادة تشغيل البوت أو فقدان active_sessions من الذاكرة.
    if purchase.get('bot_logged_out', False):
        return await safe_edit(
            event,
            "🚪 *تم تسجيل خروج البوت من هذا الرقم مسبقًا*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "⚠️ لا يمكن طلب كود آخر بعد فصل البوت.",
            buttons=kb_back()
        )
    info = active_sessions.get(user.id)
    if not info or info.get('account_id') != account_id:
        return await safe_edit(event,
            "⚠️ *انتهت صلاحية الجلسة* ⚠️\n━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔐 مرّت المدة المحددة أو تم تسجيل الخروج.\n"
            "⚡ لا يمكن طلب الكود بعد الآن.",
            buttons=kb_back()
        )
    if info.get('logged_out'):
        return await safe_edit(event,
            "🚪 *تم تسجيل الخروج من هذا الحساب*\n\n"
            "⚠️ لا يمكن طلب الكود بعد تسجيل الخروج.",
            buttons=kb_back()
        )
    now = time.time()
    if info['expiry'] < now:
        active_sessions.pop(user.id, None)
        return await safe_edit(event,
            "⏱ *انتهت مدة الجلسة*\n\n⚠️ لا يمكن طلب الكود بعد الآن.",
            buttons=kb_back()
        )
    if now - info.get('last_code_request', 0) < CODE_REQUEST_COOLDOWN:
        wait = int(CODE_REQUEST_COOLDOWN - (now - info['last_code_request']))
        return await event.answer(f"انتظر {wait} ثانية", alert=True)
    info['last_code_request'] = now
    rem = int(info['expiry'] - now)
    rem_min, rem_sec = rem // 60, rem % 60
    await safe_edit(event,
        "⏳ *جاري جلب كود الدخول...* ⏳\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📱 الرقم: `+{str(purchase['phone']).lstrip('+')}`\n"
        f"⏱ الوقت المتبقي: `{rem_min}:{rem_sec:02d}`\n\n"
        "🔐 جاري قراءة الرسائل من تيليجرام..."
    )
    password = purchase.get('password')
    # فحص سلامة الرقم والاسترداد المالي يحدثان مرة واحدة فقط بعد الشراء.
    first_activation_check = not purchase.get('activation_checked', False)
    success, code, full = await fetch_login_code(info['session'], password=password)
    if not success:
        failure_reason = full or "تعذر التحقق من الجلسة"
        logger.warning(
            "CODE_FETCH_FAILED account_id=%s phone=%s reason=%s",
            account_id,
            purchase.get('phone'),
            failure_reason,
        )
        reason_lower = failure_reason.lower()
        invalid_session = (
            "الجلسة غير صالحة" in failure_reason
            or "الجلسة غير مصرح بها" in failure_reason
            or "مفتاح الجلسة غير مسجل" in failure_reason
            or "auth key" in reason_lower
            or "unauthorized" in reason_lower
        )
        if invalid_session and first_activation_check:
            refunded, refund_amount = await refund_invalid_session_purchase(
                purchase, failure_reason
            )
            # إزالة الجلسة التالفة من الجلسات النشطة حتى لا تستمر محاولات استخدامها.
            active_sessions.pop(user.id, None)
            refund_line = (
                f"💰 *تم استرداد المبلغ المخصص للرقم:* `{fmt_amt(refund_amount, user.id)}`\n"
                f"💳 *تمت إضافة المبلغ إلى رصيدك:* `{fmt_amt(refund_amount, user.id)}`\n"
                f"📊 *رصيدك الحالي:* `{fmt_amt(get_balance(user.id), user.id)}`\n\n"
                if refunded or purchase.get('refunded_at')
                else ""
            )
            await safe_edit(event,
                "❌ *الرقم أو الجلسة فيها مشكلة.*\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📱 الرقم: `+{str(purchase['phone']).lstrip('+')}`\n\n"
                f"🔻 السبب: {failure_reason}\n\n"
                f"{refund_line}"
                "يرجى شراء رقم آخر.",
                buttons=kb_back()
            )
            return
        if invalid_session:
            # بعد نجاح أول طلب، لا نحذف active_sessions بسبب فحص عابر أو
            # إعادة اتصال فاشلة؛ حذفها كان يمنع زر «جلب كود آخر» نهائيًا.
            # الحذف والاسترداد يظلّان محصورين في فحص التفعيل الأول أعلاه.
            await safe_edit(event,
                "⚠️ *تعذر جلب الكود الآن* ⚠️\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📱 الرقم: `+{str(purchase['phone']).lstrip('+')}`\n\n"
                f"🔻 السبب: {failure_reason}\n\n"
                "لم يتم تسجيل الخروج من الجلسة. اضغط «جلب كود آخر» بعد قليل للمحاولة مرة أخرى.",
                buttons=kb_after_code(account_id)
            )
            return
        await safe_edit(event,
            "⚠️ *تعذر جلب الكود* ⚠️\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📱 الرقم: `+{str(purchase['phone']).lstrip('+')}`\n\n"
            f"🔻 السبب: {failure_reason}\n\n"
            "⚡ جرّب مرة أخرى بعد قليل.",
            buttons=kb_after_code(account_id)
        )
        return
    copy_btn = None
    if code:
        if first_activation_check:
            purchase['activation_checked'] = True
            purchase['activation_checked_at'] = datetime.now().isoformat()
            purchase['activation_status'] = 'valid'
            save_db(db)
        two_fa = purchase.get('password') or "لا يوجد"
        text = (
            "- بيع ارقام تليكرام قديم:\n"
            f"- الرقم : `{str(purchase['phone']).lstrip('+')}`\n\n"
            "• حاول تسجيل الدخول بالرقم في تطبيق تليجرام ثم اضغط على زر جلب الكود\n\n"
            "✔ تم جلب كود جديد\n"
            f"الرقم : `{str(purchase['phone']).lstrip('+')}`\n"
            f"💬 الكود : `{code}`\n\n"
            f"⚠ تحقق بخطوتين `{two_fa}`\n\n"
            "💡 نصيحة: بعد تسجيل دخولك، اضغط على زر 'خروج البوت من الرقم' لتأمين حسابك بالكامل."
        )
        
        # تحديث رسالة قناة التفعيلات
        log_msg_id = info.get('log_msg_id')
        log_base = info.get('log_text_base')
        if log_msg_id and log_base and LOG_CHANNEL_ID:
            try:
                updated_log_text = log_base.replace(
                    "🔑 كود التفعيل: في انتظار الاستلام",
                    f"🔑 كود التفعيل: `{code}`"
                )
                updated_plain, updated_entities = _merge_entities_with_custom_emojis(
                    bot, updated_log_text, 'md'
                )
                updated_bot_entities = _telethon_entities_to_bot_api(updated_entities)
                from telethon.tl.custom import Button as TlButton
                buy_buttons = [[TlButton.url("شراء أرقام", "https://t.me/MOSCOWiqBOT?start=buy")]]
                # تعديل الرسالة عبر Bot API أولاً.
                edit_resp = await fast_edit_with_colored_buttons(
                    LOG_CHANNEL_ID, log_msg_id, updated_plain, buy_buttons,
                    entities=updated_bot_entities
                )

                # إذا فشل Bot API، استخدم Telethon كخطة بديلة.
                if not edit_resp or (isinstance(edit_resp, dict) and not edit_resp.get("ok", False)):
                    try:
                        await bot.edit_message(
                            LOG_CHANNEL_ID,
                            log_msg_id,
                            updated_plain,
                            formatting_entities=updated_entities if updated_entities else None,
                            buttons=buy_buttons
                        )
                    except Exception as telethon_edit_e:
                        logger.error(
                            f"فشل تعديل رسالة قناة التفعيلات عبر Telethon: {telethon_edit_e}"
                        )
            except Exception as log_up_e:
                logger.error(f"فشل تحديث رسالة قناة التفعيلات: {log_up_e}")
    else:
        snippet = (full or "")[:600]
        text = (
            "📩 *تم استلام رسالة من تيليجرام*\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📱 الرقم: `+{str(purchase['phone']).lstrip('+')}`\n\n"
            "📄 *محتوى الرسالة:*\n"
            f"```\n{snippet}\n```\n\n"
            f"⏱ الوقت المتبقي: `{rem_min}:{rem_sec:02d}`"
        )
    buttons = kb_after_code(account_id)
    if copy_btn:
        buttons.insert(0, [copy_btn])
    await safe_edit(event, text, buttons=buttons)
    
    # ملاحظة: إرسال قناة التفعيلات يتم في on_execute_buy مباشرة بعد الشراء

async def on_logout_session(event, user, account_id):
    info = active_sessions.get(user.id)
    if not info or info.get('account_id') != account_id or info.get('logged_out'):
        await event.answer("لا توجد جلسة نشطة لهذا الرقم", alert=True)
        return await safe_edit(event,
            "🚪 *لا توجد جلسة نشطة*\n\n⚠️ تم تسجيل الخروج مسبقاً.",
            buttons=kb_back()
        )

    await event.answer("يرجى تأكيد العملية", alert=True)
    await safe_edit(event,
        "⚠️ *هل أنت متأكد من إزالة البوت من الرقم؟* ⚠️\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📱 الرقم: `+{str(info.get('phone', '')).lstrip('+')}`\n\n"
        "بعد التأكيد سيخرج البوت من الرقم ولن تتمكن من جلب كود آخر لهذا الحساب.",
        buttons=kb_confirm_logout(account_id)
    )


async def on_cancel_logout_session(event, user, account_id):
    info = active_sessions.get(user.id)
    if not info or info.get('account_id') != account_id:
        return await safe_edit(event, "⚠️ لا توجد جلسة نشطة لهذا الرقم.", buttons=kb_back())
    await event.answer("تم إلغاء العملية")
    await safe_edit(event,
        "تم إلغاء إزالة البوت. يمكنك متابعة استخدام الرقم.",
        buttons=kb_after_code(account_id)
    )


async def on_confirm_logout_session(event, user, account_id):
    info = active_sessions.get(user.id)
    if not info or info.get('account_id') != account_id or info.get('logged_out'):
        await event.answer("لا توجد جلسة نشطة لهذا الرقم", alert=True)
        return await safe_edit(event,
            "🚪 *لا توجد جلسة نشطة*\n\n⚠️ تم تسجيل الخروج مسبقاً.",
            buttons=kb_back()
        )

    await event.answer("جاري تسجيل الخروج...")
    session = info.get('session')
    ok, msg = await logout_telethon_session(session)
    info['logged_out'] = True
    # حفظ الحالة بشكل دائم؛ active_sessions وحدها موجودة في الذاكرة فقط.
    purchase = next(
        (p for p in db.get('purchases', [])
         if p.get('account_id') == account_id
         and str(p.get('user_id')) == str(user.id)),
        None,
    )
    if purchase is not None:
        purchase['bot_logged_out'] = True
        purchase['bot_logged_out_at'] = datetime.now().isoformat()
        purchase['bot_logout_result'] = bool(ok)
        purchase['bot_logout_message'] = str(msg)
        save_db(db)
    # حذف الجلسة من الذاكرة فوراً لمنع أي طلب كود لاحقاً.
    active_sessions.pop(user.id, None)
    await safe_edit(event,
        "🚪 *تم فصل البوت من الرقم بنجاح* 🚪\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"✅ {msg}\n\n"
        "✅ الحساب ما زال مفتوحًا عندك في تطبيق تيليجرام.\n"
        "⚠️ لا يمكن طلب كود آخر من البوت بعد فصل اتصاله.",
        buttons=kb_back()
    )

# ================================
#  دوال لوحة التحكم (الأدمن) - مكتملة
# ================================
def kb_admin_emojis():
    return [
        [Button.inline("إضافة إيموجي مخصص", b"ae:add")],
        [Button.inline("عرض الإيموجيات", b"ae:list")],
        [Button.inline("حذف إيموجي", b"ae:del")],
        [Button.inline("رجوع", b"a:panel")],
    ]

def kb_admin_hidebtns():
    return [
        [Button.inline("إخفاء زر جديد", b"ah:add")],
        [Button.inline("عرض الأزرار المخفية", b"ah:list")],
        [Button.inline("إعادة إظهار زر", b"ah:del")],
        [Button.inline("مسح الكل", b"ah:clear")],
        [Button.inline("رجوع", b"a:panel")],
    ]

def kb_admin_mainbtns():
    rows = [
        [Button.inline("إضافة زر رابط", b"ab:add")],
        [Button.inline("عرض الأزرار", b"ab:list")],
        [Button.inline("حذف زر",     b"ab:del")],
        [Button.inline("رجوع", b"a:panel")],
    ]
    return rows

def kb_admin_btnedit():
    return [
        [Button.inline("اختر زرّاً للتعديل", b"abe:list:0")],
        [Button.inline("تعديل بـ callback_data يدويّاً", b"abe:manual")],
        [Button.inline("عرض التعديلات الحالية", b"abe:show")],
        [Button.inline("إعادة زر للأصل", b"abe:resetlist")],
        [Button.inline("مسح كل التعديلات", b"abe:clearall")],
        [Button.inline("رجوع", b"a:panel")],
    ]

EDITABLE_BUTTONS = [
    ("🔐 شراء رقم  🔐", "buy"),
    ("🚨 قنوات احتالي", "scam_channels"),
    ("💵 شحن رصيد", "deposit"),
    ("رصيدي", "my_balance"),
    ("📋 مشترياتي", "my_purchases"),
    ("معلومات", "info"),
    ("🖥 سيرفر 1", "🖥 سيرفر 1"),
    ("🖥 سيرفر 2", "🖥 سيرفر 2"),
    ("🖥 سيرفر 3", "🖥 سيرفر 3"),
    ("📩 طلب كود", "📩 طلب كود"),
    ("❌ إلغاء الرقم", "❌ إلغاء الرقم"),
    ("🔙 القائمة الرئيسية", "back_main"),
    ("🪙 LTC (Litecoin)", "🪙 LTC (Litecoin)"),
    ("₿ BTC (Bitcoin)", "₿ BTC (Bitcoin)"),
    ("💎 TON (Toncoin)", "💎 TON (Toncoin)"),
    ("💵 USDT BEP20", "💵 USDT BEP20"),
    ("💳 دفع يدوي", "manual_pay"),
    ("✅ تأكيد الشراء", "✅ تأكيد الشراء"),
    ("🔑 طلب كود الدخول", "🔑 طلب كود الدخول"),
    ("🚪 تسجيل الخروج", "🚪 تسجيل الخروج"),
    ("✅ تحقق", "verify_captcha"),
    ("✅ تحقق من الاشتراك", "check_sub"),
]

async def admin_callback_handler(event, data):
    uid = event.sender_id
    user = await event.get_sender()
    if not is_admin(uid):
        await event.answer("غير مصرح لك بدخول لوحة التحكم.", alert=True)
        return

    if data == 'import_custom':
        state_info = get_user_state(uid)
        zip_path = state_info.get('data', {}).get('zip_path')
        if not zip_path or not os.path.exists(zip_path):
            clear_user_state(uid)
            return await safe_edit(event, "ملف ZIP غير موجود؛ أعد رفعه من لوحة الأدمن.", buttons=kb_admin_main(uid))
        set_user_state(uid, 'a_awaiting_import_target', zip_path=zip_path)
        return await safe_edit(
            event,
            "🧷 *اختر الزر الذي تريد وضع أرقام الملف فيه*\n\n"
            "الأرقام الجديدة والمكررة ستُحفظ تحت الزر المختار فقط:",
            buttons=kb_category_targets())

    if data.startswith('target_page:'):
        state_name = get_user_state(uid).get('state')
        if state_name not in ('a_awaiting_import_target', 'a_awaiting_account_target'):
            return await event.answer("انتهت عملية اختيار الزر. ابدأ الإضافة من جديد.", alert=True)
        page = data.split(':', 1)[1]
        return await safe_edit(event, "اختر الزر المطلوب:", buttons=kb_category_targets(page))

    if data == 'target_new':
        state_info = get_user_state(uid)
        state_name = state_info.get('state')
        payload = state_info.get('data', {})
        if state_name == 'a_awaiting_import_target':
            set_user_state(uid, 'a_awaiting_import_target_name', zip_path=payload.get('zip_path'))
            return await safe_edit(event, "➕ أرسل اسم الزر الجديد (من 1 إلى 60 حرفًا):", buttons=kb_admin_cancel())
        if state_name == 'a_awaiting_account_target':
            set_user_state(uid, 'a_awaiting_account_target_name')
            return await safe_edit(event, "➕ أرسل اسم الزر الجديد (من 1 إلى 60 حرفًا):", buttons=kb_admin_cancel())
        return await event.answer("انتهت عملية اختيار الزر. ابدأ الإضافة من جديد.", alert=True)

    if data.startswith('target:'):
        code = data.split(':', 1)[1]
        state_info = get_user_state(uid)
        state_name = state_info.get('state')
        targets = dict(importable_button_targets())
        if code not in targets:
            return await event.answer("الزر لم يعد متاحًا؛ حدّث القائمة واختر زرًا آخر.", alert=True)
        label = targets[code]
        if state_name == 'a_awaiting_import_target':
            zip_path = state_info.get('data', {}).get('zip_path')
            if not zip_path or not os.path.exists(zip_path):
                clear_user_state(uid)
                return await safe_edit(event, "ملف ZIP غير موجود؛ أعد رفعه من لوحة الأدمن.", buttons=kb_admin_main(uid))
            set_user_state(uid, 'a_awaiting_import_target_price', zip_path=zip_path,
                           custom_country_code=code, custom_label=label)
            return await safe_edit(event,
                f"🏷️ الزر المختار: *{label}*\n\nأرسل السعر لكل رقم في الملف، مثال: `1.20`:",
                buttons=kb_admin_cancel())
        if state_name == 'a_awaiting_account_target':
            pending = db.get('pending_spam_choice', {})
            if not pending:
                clear_user_state(uid)
                return await safe_edit(event, "لا توجد إضافة معلقة.", buttons=kb_admin_accounts())
            pending.update({'custom_country_code': code, 'custom_label': label,
                            'code': code, 'name': label, 'purchase_category': 'clean'})
            db['pending_spam_choice'] = pending
            save_db(db)
            set_user_state(uid, 'a_awaiting_account_price')
            return await safe_edit(event,
                f"🏷️ الزر المختار: *{label}*\n\nأرسل السعر الذي تريده لهذا الرقم/الملف، مثال: `1.20`:",
                buttons=kb_admin_cancel())
        return await event.answer("انتهت عملية اختيار الزر. ابدأ الإضافة من جديد.", alert=True)

    if data == "a:panel":
        await safe_edit(event,
            "⚡ *لوحة تحكم الأدمن* ⚡\n━━━━━━━━━━━━━━━━━━━━\n\n🔐 اختر الإجراء المطلوب:",
            buttons=kb_admin_main(uid)
        )
        return

    if data == "a:referral_menu":
        return await show_admin_referral_menu(event)

    if data == "a:referral_close":
        db['settings']['referral_enabled'] = False
        save_db(db)
        return await show_admin_referral_menu(event)

    if data == "a:referral_open":
        db['settings']['referral_enabled'] = True
        save_db(db)
        return await show_admin_referral_menu(event)

    if data == "a:referral_price":
        return await safe_edit(
            event,
            "🔒 *سعر رابط الدعوة ثابت*\n\nالمكافأة المحددة لكل إحالة ناجحة هي `0.006$` ولا يمكن تغييرها.",
            buttons=kb_admin_referral()
        )

    if data == "a:referral_clear":
        # نصفر نقاط الإحالة فقط، ولا نلمس الرصيد الناتج من الشحن أو المشتريات.
        removed = 0.0
        affected = 0
        for inviter_uid, user_data in db.get('users', {}).items():
            points = float(user_data.get('referral_points', 0.0) or 0.0)
            if points > 0:
                # إزالة الجزء غير المصروف قدر الإمكان.
                deduction = min(points, max(0.0, get_balance(inviter_uid)))
                if deduction:
                    _apply_referral_balance(inviter_uid, -deduction)
                    removed += deduction
                user_data['referral_points'] = 0.0
                affected += 1

        # منع الإحالات النشطة الحالية من إعادة المكافأة مباشرة بعد المسح.
        for rec in db.get('referrals', {}).values():
            if rec.get('active'):
                rec['rewarded'] = False
                rec['cleared'] = True
        save_db(db)
        return await safe_edit(
            event,
            f"✅ *تم مسح نقاط الإحالة*\n\n"
            f"👥 المستخدمون المتأثرون: `{affected}`\n"
            f"💵 المبلغ المخصوم من الأرصدة المتاحة: `{removed:.3f}$`",
            buttons=kb_admin_referral()
        )

    if data == "a:countries":
        await safe_edit(event, "*إدارة الدول*", buttons=kb_admin_countries())
        return

    if data == "a:accounts":
        await safe_edit(event, "*إدارة الحسابات*", buttons=kb_admin_accounts())
        return

    if data == "a:count_accounts":
        accounts = db.get('accounts', [])
        total = len(accounts)
        available = sum(1 for a in accounts if a.get('status') == 'available')
        sold = sum(1 for a in accounts if a.get('status') == 'sold')
        spam = sum(1 for a in accounts if a.get('status') == 'available' and a.get('is_spam', False))
        old = sum(1 for a in accounts if a.get('status') == 'available' and a.get('is_old', False))
        clean = sum(1 for a in accounts if a.get('status') == 'available' and not a.get('is_spam', False) and not a.get('is_old', False) and not a.get('is_fake', False) and not a.get('is_unverified', False) and not a.get('is_monthly', False))
        text = (
            "📊 *إحصائيات الأرقام في البوت*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📦 إجمالي الأرقام: `{total}`\n"
            f"🟢 المتاحة للبيع: `{available}`\n"
            f"🔵 السليمة المتاحة: `{clean}`\n"
            f"📛 السبام المتاح: `{spam}`\n"
            f"📅 الأرقام القديمة: `{old}`\n"
            f"🛒 المباعة: `{sold}`"
        )
        return await safe_edit(event, text, buttons=kb_admin_back())

    if data == "a:wallets":
        text = "💳 *المحافظ الحالية* — اضغط لتعديل:\n━━━━━━━━━━━━━━━━━━━━\n\n"
        for cur, addr in WALLETS.items():
            icon = {"LTC": "🪙", "BTC": "₿", "TON": "💎", "USDT": "💵"}.get(cur, "💠")
            text += f"{icon} *{cur}* ({NETWORKS[cur]}):\n`{addr}`\n\n"
        await safe_edit(event, text, buttons=kb_admin_wallets())
        return

    if data == "a:scam_channels":
        return await admin_scam_channels_menu(event)
    if data == "asc:add":
        set_user_state(uid, 'a_scam_channel_link')
        return await safe_edit(event, '📢 أرسل رابط القناة أو @username:', buttons=kb_admin_cancel())
    if data == "a:channels":
        await admin_show_channels(event)
        return

    if data == "a:emojis":
        await admin_open_emojis(event)
        return

    if data == "a:hidebtns":
        await admin_open_hidebtns(event)
        return

    if data == "a:btnedit":
        await admin_open_btnedit(event)
        return

    if data == "a:stats":
        await admin_stats(event)
        return

    if data == "a:maintenance":
        current = db['settings'].get('maintenance', False)
        db['settings']['maintenance'] = not current
        save_db(db)
        new_status = "✅ مُفعّلة" if not current else "❌ معطّلة"
        await safe_edit(event,
            f"🔧 *حالة الصيانة:* {new_status}",
            buttons=kb_admin_main(uid)
        )
        return

    if data == "a:backup":
        try:
            await event.answer("جاري إنشاء النسخة الاحتياطية... قد يستغرق ذلك لحظات.", alert=True)
            import zipfile
            backup_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
            targets = [
                DB_FILE, 
                "sliner_numbers_bot_session.session", 
                SESSIONS_DIR,
                SESSION_ARCHIVE_DIR,
                SESSION_REGISTRY_FILE,
            ]
            with zipfile.ZipFile(backup_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for target in targets:
                    if os.path.exists(target):
                        if os.path.isdir(target):
                            for root, dirs, files in os.walk(target):
                                for file in files:
                                    file_path = os.path.join(root, file)
                                    zipf.write(file_path, arcname=file_path)
                        else:
                            zipf.write(target, arcname=target)
            caption = (
                f"📦 *نسخة احتياطية كاملة للمشروع*\n\n"
                f"📅 التاريخ: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n"
                f"👥 عدد المستخدمين: `{len(db.get('users', {}))}`\n"
                f"💰 إجمالي الأرصدة: `{sum(u.get('balance', 0) for u in db.get('users', {}).values()):.2f}$`\n\n"
                f"✅ تم ضغط كافة الملفات والجلسات بنجاح."
            )
            client = getattr(event, 'client', bot)
            await client.send_file(event.sender_id, backup_name, caption=caption)
            if os.path.exists(backup_name):
                os.remove(backup_name)
        except Exception as e:
            logger.error(f"Full Backup failed: {e}")
            await event.respond(f"❌ فشل إنشاء النسخة الاحتياطية الكاملة: {e}")
        return

    if data == "a:restore":
        set_user_state(uid, 'awaiting_restore_zip')
        await safe_edit(event, "يرجى إرسال ملف الـ ZIP الذي يحتوي على النسخة الاحتياطية.", buttons=kb_admin_cancel())
        return

    if data == "a:import_sessions":
        set_user_state(uid, 'awaiting_import_zip')
        await safe_edit(event,
            "📥 *استيراد جلسات من ملف ZIP*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔐 ارفق ملف `sessions.zip` يحتوي على:\n"
            "• `الرقم.session`\n"
            "• `الرقم.json`\n\n"
            "💡 مثال: `14432961584.session` + `14432961584.json`\n\n"
            "(EMOJI5798514803777478100) البوت سيقرأ الرقم من اسم الملف تلقائياً.",
            buttons=kb_admin_cancel()
        )
        return

    if data == "a:close":
        try:
            await event.delete()
        except Exception:
            pass
        return


    if data == "ac:list":
        return await admin_list_countries(event)
    if data == "ac:add":
        return await event.answer("تم إلغاء هذا الخيار، البوت الآن يتعرف على الدول تلقائياً عند إضافة الأرقام.", alert=True)
    if data == "ac:edit":
        return await admin_select_country_action(event, "edit")
    if data == "ac:edit_name":
        return await admin_select_country_action(event, "edit_name")
    if data == "ac:del":
        return await admin_select_country_action(event, "del")
    if data == "ac:set_default_price":
        set_user_state(uid, 'a_set_default_price')
        return await safe_edit(event, "💰 *تحديد السعر الافتراضي*\n\n⚡ أرسل السعر الافتراضي الجديد لأي دولة يتم اكتشافها تلقائياً:", buttons=kb_admin_cancel())
    if data == "ac:set_mixed_price":
        set_user_state(uid, 'a_set_mixed_price')
        return await safe_edit(event, "📛 *تحديد سعر المخطلت*\n\n⚡ أرسل السعر الجديد لقسم المخطلت (السبام):", buttons=kb_admin_cancel())
    if data == "ac:set_old_spam_price":
        set_user_state(uid, 'a_set_old_spam_price')
        return await safe_edit(event, f"🕰 *تحديد سعر {OLD_SPAM_LABEL}*\n\n⚡ أرسل السعر الجديد للقسم:", buttons=kb_admin_cancel())
    if data == "ac:set_fake_price":
        set_user_state(uid, 'a_set_fake_price')
        return await safe_edit(event, "⚠️ *تحديد سعر الاحتيالي*\n\n⚡ أرسل السعر الجديد لقسم الأرقام المزيفة/الاحتيالية:", buttons=kb_admin_cancel())
    if data.startswith("ac_edit:"):
        code = data.split(":")[1]
        set_user_state(uid, 'a_country_edit_price', code=code)
        c = db['countries'].get(code, {})
        return await safe_edit(event,
            f"💰 *تعديل سعر*\n\n🌍 الدولة: {c.get('name')}\n💰 السعر الحالي: `{c.get('price')}$`\n\n⚡ أرسل السعر الجديد:",
            buttons=kb_admin_cancel()
        )
    if data.startswith("ac_edit_name:"):
        code = data.split(":")[1]
        set_user_state(uid, 'a_country_edit_name', code=code)
        c = db['countries'].get(code, {})
        return await safe_edit(
            event,
            f"✏️ *تعديل اسم الدولة*\n\n"
            f"🌍 الدولة الحالية: {c.get('name', 'غير معروفة')}\n"
            f"📞 الرمز: `{code}`\n\n"
            "⚡ أرسل الاسم الجديد (مثال: `🇸🇦 السعودية`):",
            buttons=kb_admin_cancel()
        )
    if data.startswith("ac_del:"):
        code = data.split(":")[1]
        db['countries'].pop(code, None)
        save_db(db)
        return await safe_edit(event, f"تم حذف الدولة `{code}`", buttons=kb_admin_countries())

    if data == "aa:add":
        set_user_state(uid, 'a_add_phone')
        return await safe_edit(event,
            "📱 *تعبئة رقم جديد*\n\n⚡ أرسل الرقم بصيغة دولية:\nمثال: `+966512345678`\n\n💡 الدولة ستُكتشف تلقائياً.",
            buttons=kb_admin_cancel()
        )

    if data == "aa:add_session":
        set_user_state(uid, 'a_add_session_file')
        return await safe_edit(event,
            "📂 *إضافة ملف جلسة (Session)*\n\n⚡ يرجى إرسال ملف الجلسة الذي ينتهي بـ `.session` أو `.json`\n\n💡 تأكد أن اسم الملف هو رقم الهاتف (مثال: `+966512345678.session` أو `+966512345678.json`).",
            buttons=kb_admin_cancel()
        )
    if data == "aa:bulk_2fa":
        set_user_state(uid, 'a_bulk_2fa_new')
        return await safe_edit(event,
            "(EMOJI5307843983102204243) *تغيير التحقق بخطوتين (2FA) لجميع الأرقام المتاحة*\n\n"
            "⚡ سيقوم البوت تلقائياً باستخدام كلمة المرور المخزنة لكل رقم وتغييرها.\n\n"
            "يرجى إرسال **كلمة المرور الجديدة** الموحدة التي تريد تعيينها:",
            buttons=kb_admin_cancel()
        )


    if data == "a:manualpay":
        return await safe_edit(event, "*إدارة الدفع اليدوي*", buttons=kb_admin_manual())
    if data == "am:add":
        set_user_state(uid, 'a_mp_name')
        return await safe_edit(event,
            "➕ *إضافة طريقة دفع*\n\n⚡ أرسل اسم الطريقة (مثل: تحويل بنكي):",
            buttons=kb_admin_cancel()
        )
    if data == "am:list":
        methods = db['manual_payments']
        if not methods:
            return await safe_edit(event, "لا توجد طرق.", buttons=kb_admin_manual())
        text = "💳 *طرق الدفع اليدوي:*\n━━━━━━━━━━━━━━━━━━━━\n\n"
        for m in methods:
            text += f"🔐 *{m['name']}*\n_{m['description'][:80]}_\n\n"
        return await safe_edit(event, text, buttons=kb_admin_manual())
    if data == "am:del":
        methods = db['manual_payments']
        if not methods:
            return await safe_edit(event, "لا توجد طرق.", buttons=kb_admin_manual())
        rows = [[Button.inline(f"{m['name']}", f"am_del:{m['name']}".encode())] for m in methods]
        rows.append([Button.inline("رجوع", b"a:manualpay")])
        return await safe_edit(event, "اختر للحذف:", buttons=rows)
    if data.startswith("am_del:"):
        name = data.split(":", 1)[1]
        db['manual_payments'] = [m for m in db['manual_payments'] if m['name'] != name]
        save_db(db)
        return await safe_edit(event, f"تم حذف `{name}`", buttons=kb_admin_manual())

    if data.startswith("admin_mr:"):
        parts = data.split(":")
        action = parts[1]
        target_id = int(parts[2])
        return await admin_handle_manual_action(event, action, target_id)

    if data.startswith("aw:set:"):
        cur = data.split(":")[2]
        set_user_state(uid, 'a_wallet_set', currency=cur)
        return await safe_edit(event,
            f"✏️ *تعديل عنوان {cur}*\n\n📍 العنوان الحالي:\n`{WALLETS[cur]}`\n\n⚡ أرسل العنوان الجديد:",
            buttons=kb_admin_cancel()
        )

    if data == "a:welcome":
        set_user_state(uid, 'a_welcome')
        current = db['settings'].get('welcome_text', '')
        return await safe_edit(event,
            "✏️ *تعديل الترحيب*\n\n⚡ المتغيرات المدعومة:\n`{user}` `{username}` `{id}` `{balance}`\n\n"
            f"📄 *النص الحالي:*\n\n{current}",
            buttons=kb_admin_cancel()
        )

    if data.startswith("ac_fs:monitor:"):
        ch_id = int(data.split(":")[2])
        monitored = db['settings'].get('monitored_channels', [])
        if ch_id in monitored:
            monitored.remove(ch_id)
            await event.answer("تم إيقاف مراقبة هذه القناة")
        else:
            monitored.append(ch_id)
            await event.answer("تم تفعيل مراقبة هذه القناة")
        db['settings']['monitored_channels'] = monitored
        save_db(db)
        return await admin_show_channels(event)
    if data == "ac_fs:toggle":
        cur = db['settings'].get('force_sub_enabled', True)
        db['settings']['force_sub_enabled'] = not cur
        save_db(db)
        return await admin_show_channels(event)
    if data == "ac_fs:add":
        set_user_state(uid, 'a_fs_add')
        return await safe_edit(event,
            "➕ *إضافة قناة اشتراك*\n\n⚡ أرسل بالصيغة:\n"
            "`channel_id username العنوان`\n\n"
            "🔐 مثال:\n`-1001234567 mychannel قناتنا`",
            buttons=kb_admin_cancel()
        )
    if data.startswith("ac_fs:del:"):
        try:
            idx = int(data.split(":")[2])
            chs = db['settings'].get('force_channels', [])
            if 0 <= idx < len(chs):
                chs.pop(idx)
                db['settings']['force_channels'] = chs
                save_db(db)
        except Exception:
            pass
        return await admin_show_channels(event)

    if data == "a:mainbtns":
        return await admin_open_mainbtns(event)
    if data == "ab:add":
        set_user_state(uid, 'a_btn_add')
        return await safe_edit(event,
            "➕ *إضافة زر رابط*\n\n⚡ أرسل بالصيغة:\n"
            "`العنوان | الرابط`\n\nمثال:\n"
            "`🔗 موقعنا | https://example.com`",
            buttons=kb_admin_cancel()
        )
    if data == "ab:list":
        return await admin_open_mainbtns(event)
    if data == "ab:del":
        return await admin_mainbtns_list_for_delete(event)
    if data.startswith("ab:rm:"):
        try:
            idx = int(data.split(":")[2])
            btns = db.get('main_url_buttons', []) or []
            if 0 <= idx < len(btns):
                btns.pop(idx)
                db['main_url_buttons'] = btns
                save_db(db)
        except Exception:
            pass
        return await admin_open_mainbtns(event)

    if data == "a:clear_points":
        return await safe_edit(event,
            "⚠️ *تحذير: مسح جميع النقاط*\n\n"
            "هل أنت متأكد أنك تريد تصفير نقاط (رصيد) جميع المستخدمين؟\n"
            "هذا الإجراء لا يمكن التراجع عنه!",
            buttons=[
                [Button.inline("نعم، صفر الجميع", b"a:confirm_clear_points")],
                [Button.inline("تراجع", b"a:panel")]
            ]
        )

    if data == "a:confirm_clear_points":
        count = 0
        for uid in db['users']:
            db['users'][uid]['balance'] = 0.0
            count += 1
        save_db(db)
        return await safe_edit(event,
            f"✅ تم تصفير رصيد `{count}` مستخدم بنجاح.",
            buttons=kb_admin_main(uid)
        )

    if data == "a:broadcast":
        set_user_state(uid, 'a_broadcast')
        return await safe_edit(event,
            "📢 *إذاعة*\n\n⚡ أرسل الرسالة (يدعم Markdown):",
            buttons=kb_admin_cancel()
        )

    if data == "a:ban":
        # حماية: الأدمن فقط
        if not is_admin(uid):
            return await event.answer("🚫 هذا الإجراء للأدمن فقط", alert=True)
        set_user_state(uid, 'a_ban')
        return await safe_edit(event,
            "🚫 *إدارة حظر المستخدمين* 🚫\n━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔐 أرسل الآن **يوزر المستخدم** (مثل: `@username`) أو **الآيدي** الخاص به.\n\n"
            "💡 سيقوم البوت بالبحث عنه وإظهار خيارات (الحظر / فك الحظر / التفعيل) الخاصة به."
            "\n⚠️ *ملاحظة:* الحظر التلقائي معطّل — أنت من يقرر من يُحظر.",
            buttons=kb_admin_cancel()
        )

    if data == "a:txs":
        return await admin_show_txs(event)

    if data.startswith("a_addbal:"):
        target = data.split(":")[1]
        set_user_state(uid, 'a_addbal_for', target=target)
        return await safe_edit(event,
            f"🟩 *إضافة رصيد*\n\n⚡ أرسل المبلغ فقط للمستخدم `{target}`:",
            buttons=kb_admin_cancel()
        )
    if data.startswith("a_subbal:"):
        target = data.split(":")[1]
        set_user_state(uid, 'a_subbal_for', target=target)
        return await safe_edit(event,
            f"🟥 *خصم رصيد*\n\n⚡ أرسل المبلغ فقط للمستخدم `{target}`:",
            buttons=kb_admin_cancel()
        )

    # ========== أزرار التعديل السريع للرصيد (مبالغ محددة) ==========
    if data.startswith("aq_add:"):
        # aq_add:USER_ID:AMOUNT
        parts = data.split(":")
        target_uid = parts[1]
        try:
            amount = float(parts[2])
        except (IndexError, ValueError):
            return await event.answer("مبلغ غير صحيح", alert=True)
        u = db['users'].get(target_uid)
        if not u:
            return await event.answer("المستخدم غير موجود", alert=True)
        update_balance(target_uid, amount)
        new_bal = get_balance(target_uid)
        await event.answer(f"تم إضافة {amount}$")
        # إشعار المستخدم
        try:
            await bot.send_message(int(target_uid),
                f"🔐 *تمت إضافة رصيد*\n💰 المبلغ: `+{amount:.2f}$`\n💳 الرصيد الجديد: `{new_bal:.2f}$`")
        except Exception:
            pass
        # تم إزالة إشعار القناة لأنه سري
        return await admin_show_user(event, int(target_uid))

    if data.startswith("aq_sub:"):
        # aq_sub:USER_ID:AMOUNT
        parts = data.split(":")
        target_uid = parts[1]
        try:
            amount = float(parts[2])
        except (IndexError, ValueError):
            return await event.answer("مبلغ غير صحيح", alert=True)
        u = db['users'].get(target_uid)
        if not u:
            return await event.answer("المستخدم غير موجود", alert=True)
        update_balance(target_uid, -amount)
        new_bal = get_balance(target_uid)
        await event.answer(f"تم خصم {amount}$")
        # إشعار المستخدم
        try:
            await bot.send_message(int(target_uid),
                f"⚠️ *تم خصم رصيد*\n💰 المبلغ: `-{amount:.2f}$`\n💳 الرصيد الجديد: `{new_bal:.2f}$`")
        except Exception:
            pass
        # تم إزالة إشعار القناة لأنه سري
        return await admin_show_user(event, int(target_uid))

    if data.startswith("a_ban:"):
        # حماية: الأدمن فقط
        if not is_admin(uid):
            return await event.answer("🚫 هذا الإجراء للأدمن فقط", alert=True)
        target_uid = data.split(":")[1]
        u = db['users'].get(target_uid)
        if not u:
            return await event.answer("غير موجود", alert=True)
        u['banned'] = not u.get('banned')
        # عند فك الحظر تنظيف أي حظر مؤقت مرتبط
        if not u['banned'] and 'temp_ban_until' in u:
            u.pop('temp_ban_until', None)
        save_db(db)
        update_user_cache(target_uid)
        await event.answer("تم تغيير حالة الحظر (إجراء الأدمن)")
        return await admin_show_user(event, int(target_uid))

    if data.startswith("a_v:"):
        target_uid = data.split(":")[1]
        u = db['users'].get(target_uid)
        if not u:
            return await event.answer("غير موجود", alert=True)
        u['verified'] = True
        save_db(db)
        update_user_cache(target_uid)
        await event.answer("تم تفعيل المستخدم بنجاح")
        try:
            await bot.send_message(int(target_uid), "🎉 *مبروك! تم تفعيل حسابك بنجاح.*\n\n🔐 يمكنك الآن استخدام البوت بشكل كامل.\n⚡ أرسل /start للبدء.")
        except Exception:
            pass
        return await admin_show_user(event, int(target_uid))

    if data == "a:addbal":
        set_user_state(uid, 'a_addbal')
        return await safe_edit(event,
            "🟩 *إضافة رصيد*\n\n⚡ أرسل: `معرف_المستخدم المبلغ`\n\n"
            "🔐 أمثلة:\n• `@username 5`\n• `123456789 10.5`",
            buttons=kb_admin_cancel()
        )
    if data == "a:subbal":
        set_user_state(uid, 'a_subbal')
        return await safe_edit(event,
            "🟥 *خصم رصيد*\n\n⚡ أرسل: `معرف_المستخدم المبلغ`",
            buttons=kb_admin_cancel()
        )

    if data == "a:btnedit":
        return await admin_open_btnedit(event)
    if data.startswith("abe:list:"):
        try:
            page = int(data.split(":")[2])
        except Exception:
            page = 0
        return await admin_btnedit_list(event, page)
    if data.startswith("abe:pick:"):
        try:
            idx = int(data.split(":")[2])
        except Exception:
            return await event.answer("فهرس غير صحيح", alert=True)
        return await admin_btnedit_pick(event, user, idx)
    if data == "abe:show":
        return await admin_btnedit_show(event)
    if data == "abe:resetlist":
        return await admin_btnedit_resetlist(event)
    if data.startswith("abe:reset:"):
        try:
            idx = int(data.split(":")[2])
            overrides = db.get('button_overrides', {}) or {}
            keys = list(overrides.keys())
            if 0 <= idx < len(keys):
                overrides.pop(keys[idx], None)
                db['button_overrides'] = overrides
                save_db(db)
                await event.answer("تمت الإعادة للأصل")
        except Exception:
            pass
        return await admin_btnedit_resetlist(event)
    if data == "abe:clearall":
        db['button_overrides'] = {}
        save_db(db)
        await event.answer("تم مسح كل التعديلات", alert=True)
        return await admin_open_btnedit(event)
    if data == "abe:manual":
        set_user_state(uid, 'a_btnedit_manualkey')
        return await safe_edit(event,
            "✏️ *تعديل يدوي*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "⚡ أرسل مفتاح الزر المراد تعديله (callback_data أو نص الزر حرفيّاً)\n\n"
            "أمثلة:\n"
            "`buy`\n"
            "`back_main`\n"
            "`🔐 شراء رقم  🔐`",
            buttons=kb_admin_cancel())

    if data == "a:emojis":
        return await admin_open_emojis(event)
    if data == "ae:add":
        set_user_state(uid, 'a_emoji_add')
        return await safe_edit(event,
            "➕ *إضافة إيموجي مخصص*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "⚡ أرسل بالصيغة:\n"
            "`الإيموجي رقم_الإيموجي_المخصص`\n\n"
            "🔐 أمثلة:\n"
            "`🔐 5222148368955877900`\n"
            "`⚡ 5219943216781995020`\n\n"
            "💡 يمكنك الحصول على Document ID لأي إيموجي مخصص عبر بوت `@MarkdownEmojisBot`.",
            buttons=kb_admin_cancel()
        )
    if data == "ae:list":
        return await admin_open_emojis(event)
    if data == "ae:del":
        return await admin_emojis_list_for_delete(event)
    if data.startswith("ae:rm:"):
        try:
            idx = int(data.split(":")[2])
            emojis = db.get('custom_emojis', {}) or {}
            keys = list(emojis.keys())
            if 0 <= idx < len(keys):
                emojis.pop(keys[idx], None)
                db['custom_emojis'] = emojis
                save_db(db)
        except Exception:
            pass
        return await admin_open_emojis(event)

    if data == "a:hidebtns":
        return await admin_open_hidebtns(event)
    if data == "ah:add":
        set_user_state(uid, 'a_hidebtn_add')
        return await safe_edit(event,
            "➕ *إخفاء زر جديد*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "⚡ اكتب اسم الزر بالضبط كما يظهر في الواجهة.\n\n"
            "🔐 أمثلة:\n"
            "`⚡ معلومات`\n"
            "`💰 رصيدي`\n\n"
            "💡 يمكنك إرسال عدة أسماء دفعة واحدة بوضع كل اسم في سطر.",
            buttons=kb_admin_cancel()
        )
    if data == "ah:list":
        return await admin_open_hidebtns(event)
    if data == "ah:del":
        return await admin_hidebtns_list_for_unhide(event)
    if data.startswith("ah:rm:"):
        try:
            idx = int(data.split(":")[2])
            hidden = db.get('hidden_buttons', []) or []
            if 0 <= idx < len(hidden):
                hidden.pop(idx)
                db['hidden_buttons'] = hidden
                save_db(db)
        except Exception:
            pass
        return await admin_open_hidebtns(event)
    if data == "ah:clear":
        db['hidden_buttons'] = []
        save_db(db)
        return await admin_open_hidebtns(event)

    await event.answer()

async def admin_open_emojis(event):
    emojis = db.get('custom_emojis', {}) or {}
    text = (
        "🎨 *الإيموجيات المخصصة*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "💡 تستطيع إضافة إيموجي عادي وربطه بـ *Document ID* لإيموجي مخصص،\n"
        "وسيتم تحويله تلقائيّاً في جميع الرسائل والأزرار.\n\n"
    )
    if not emojis:
        text += "⚠️ لا توجد إيموجيات مخصصة مضافة حالياً."
    else:
        text += f"🔐 *العدد:* `{len(emojis)}`\n\n"
        for emo, eid in list(emojis.items())[:25]:
            text += f"{emo} ←→ `{eid}`\n"
        if len(emojis) > 25:
            text += f"\n... و `{len(emojis) - 25}` أكثر"
    await safe_edit(event, text, buttons=kb_admin_emojis())

async def admin_emojis_list_for_delete(event):
    emojis = db.get('custom_emojis', {}) or {}
    if not emojis:
        return await safe_edit(event, "لا توجد إيموجيات للحذف.",
            buttons=kb_admin_emojis())
    rows = []
    keys = list(emojis.keys())
    for i, emo in enumerate(keys):
        rows.append([Button.inline(f"{emo} ← {emojis[emo][:14]}", f"ae:rm:{i}".encode())])
    rows.append([Button.inline("رجوع", b"a:emojis")])
    await safe_edit(event, "اختر الإيموجي للحذف:", buttons=rows)

async def admin_open_hidebtns(event):
    hidden = db.get('hidden_buttons', []) or {}
    text = (
        "🙈 *إخفاء الأزرار*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "💡 اكتب اسم أي زر بالضبط لإخفائه من الواجهة.\n"
        "🔍 يدعم التطابق مع أو بدون الرمز التعبيري (إيموجي) في البداية.\n\n"
    )
    if not hidden:
        text += "✅ لا توجد أزرار مخفية حالياً."
    else:
        text += f"🔐 *العدد:* `{len(hidden)}`\n\n"
        for i, h in enumerate(hidden, 1):
            text += f"{i}. `{h}`\n"
    await safe_edit(event, text, buttons=kb_admin_hidebtns())

async def admin_hidebtns_list_for_unhide(event):
    hidden = db.get('hidden_buttons', []) or {}
    if not hidden:
        return await safe_edit(event, "لا توجد أزرار مخفية.",
            buttons=kb_admin_hidebtns())
    rows = []
    for i, h in enumerate(hidden):
        rows.append([Button.inline(f"{h[:32]}", f"ah:rm:{i}".encode())])
    rows.append([Button.inline("رجوع", b"a:hidebtns")])
    await safe_edit(event, "اختر زرّاً لإعادة إظهاره:", buttons=rows)

async def admin_open_mainbtns(event):
    btns = db.get('main_url_buttons', []) or {}
    text = (
        "🎛 *أزرار القائمة الرئيسية (روابط)*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    if not btns:
        text += "⚠️ لا توجد أزرار حالياً."
    else:
        for i, b in enumerate(btns, 1):
            text += f"{i}. *{b.get('title')}* → {b.get('url')}\n"
    await safe_edit(event, text, buttons=kb_admin_mainbtns())

async def admin_mainbtns_list_for_delete(event):
    btns = db.get('main_url_buttons', []) or {}
    if not btns:
        return await safe_edit(event, "لا توجد أزرار للحذف.",
            buttons=kb_admin_mainbtns())
    rows = []
    for i, b in enumerate(btns):
        rows.append([Button.inline(f"{b.get('title','#')}", f"ab:rm:{i}".encode())])
    rows.append([Button.inline("رجوع", b"a:mainbtns")])
    await safe_edit(event, "اختر الزر للحذف:", buttons=rows)

async def admin_open_btnedit(event):
    overrides = db.get('button_overrides', {}) or {}
    text = (
        "✏️ *محرر الأزرار — تغيير الاسم والإيموجي*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "💡 بإمكانك تخصيص أي زر في البوت:\n"
        "  · تغيير نصّ الزر إلى أي عبارة تريد.\n"
        "  · ربط الزر بـ *إيموجي مخصص* (Document ID).\n"
        "  · ترك الوظيفة أو الرابط كما هو (تعديل سطحي فقط).\n\n"
        f"🔐 عدد التعديلات الحالية: `{len(overrides)}`"
    )
    await safe_edit(event, text, buttons=kb_admin_btnedit())

async def admin_btnedit_list(event, page=0):
    PER_PAGE = 8
    overrides = db.get('button_overrides', {}) or {}
    items = list(EDITABLE_BUTTONS)
    total_pages = max(1, (len(items) + PER_PAGE - 1) // PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * PER_PAGE
    page_items = items[start:start + PER_PAGE]
    rows = []
    for i, (label, key) in enumerate(page_items, start=start):
        marker = "✏️ " if (key in overrides) else ""
        rows.append([Button.inline(f"{marker}{label[:36]}", f"abe:pick:{i}".encode())])
    nav = []
    if page > 0:
        nav.append(Button.inline("⬅️", f"abe:list:{page-1}".encode()))
    nav.append(Button.inline(f"{page+1}/{total_pages}", b"noop"))
    if page + 1 < total_pages:
        nav.append(Button.inline("➡️", f"abe:list:{page+1}".encode()))
    if nav:
        rows.append(nav)
    rows.append([Button.inline("رجوع", b"a:btnedit")])
    await safe_edit(event,
        "📋 *اختر الزر الذي ترغب بتعديله* (أو استخدم وضع التعديل اليدوي):",
        buttons=rows)

async def admin_btnedit_pick(event, user, idx):
    try:
        label, key = EDITABLE_BUTTONS[idx]
    except Exception:
        return await event.answer("فهرس غير صحيح", alert=True)
    overrides = db.get('button_overrides', {}) or {}
    cur = overrides.get(key, {})
    cur_text = cur.get('text', '—')
    cur_emoji = cur.get('emoji_id', '—')
    set_user_state(user.id, 'a_btnedit_text', btn_key=key, btn_label=label)
    text = (
        f"✏️ *تعديل الزر:* `{label}`\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"(EMOJI5798514803777478100) النص الحالي (بعد التعديل): `{cur_text}`\n"
        f"🎨 الإيموجي المخصص: `{cur_emoji}`\n\n"
        "⚡ أرسل الآن *النص الجديد للزر*\n"
        "  (أو اكتب `=` للإبقاء على النص الحالي)\n\n"
        "ثم سأطلب منك رقم الإيموجي المخصص (Document ID)."
    )
    await safe_edit(event, text, buttons=kb_admin_cancel())
    await event.answer()

async def admin_btnedit_show(event):
    overrides = db.get('button_overrides', {}) or {}
    if not overrides:
        return await safe_edit(event, "لا توجد تعديلات حاليّاً.",
            buttons=kb_admin_btnedit())
    text = "📑 *التعديلات الحالية للأزرار:*\n\n"
    for i, (k, v) in enumerate(list(overrides.items())[:40], 1):
        text += (f"{i}. مفتاح: `{k[:30]}`\n"
                 f"   نص: `{v.get('text','—')}`\n"
                 f"   إيموجي: `{v.get('emoji_id','—')}`\n")
    if len(overrides) > 40:
        text += f"\n... و `{len(overrides) - 40}` أكثر"
    await safe_edit(event, text, buttons=kb_admin_btnedit())

async def admin_btnedit_resetlist(event):
    overrides = db.get('button_overrides', {}) or {}
    if not overrides:
        return await safe_edit(event, "لا توجد تعديلات لإعادتها.",
            buttons=kb_admin_btnedit())
    rows = []
    keys = list(overrides.keys())
    for i, k in enumerate(keys[:25]):
        rows.append([Button.inline(f"{k[:32]}", f"abe:reset:{i}".encode())])
    rows.append([Button.inline("رجوع", b"a:btnedit")])
    await safe_edit(event, "*اختر تعديلاً لإعادته للأصل:*", buttons=rows)

async def admin_stats(event):
    users_count = len(db['users'])
    banned = sum(1 for u in db['users'].values() if u.get('banned'))
    avail = sum(1 for a in db['accounts'] if a.get('status') == 'available')
    sold = sum(1 for a in db['accounts'] if a.get('status') == 'sold')
    countries = len(db['countries'])
    total_sales = sum(p['price'] for p in db['purchases'])
    total_balance = sum(u.get('balance', 0) for u in db['users'].values())
    total_deposited = sum(t['amount_usd'] for t in db['transactions'] if t.get('status') == 'completed')
    pending_manual = sum(1 for r in db.get('manual_requests', []) if r.get('status') == 'pending')
    pending_manual += sum(1 for t in db['transactions'] if t.get('status') == 'pending_manual')
    text = (
        "📊 *إحصائيات البوت* 📊\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 المستخدمين: `{users_count}`\n"
        f"🚸 المحظورين: `{banned}`\n\n"
        f"🟩 حسابات متاحة: `{avail}`\n"
        f"🟥 حسابات مباعة: `{sold}`\n"
        f"🛒 مبيعات: `{len(db['purchases'])}`\n"
        f"🌍 الدول: `{countries}`\n\n"
        f"💰 إجمالي المبيعات: `{total_sales:.2f}$`\n"
        f"💵 إجمالي الشحن: `{total_deposited:.2f}$`\n"
        f"💳 إجمالي الأرصدة: `{total_balance:.2f}$`\n\n"
        f"⏳ طلبات بانتظار المراجعة: `{pending_manual}`"
    )
    await safe_edit(event, text, buttons=kb_admin_main(uid))

async def admin_show_txs(event):
    txs = sorted(db['transactions'], key=lambda x: x.get('id', 0), reverse=True)[:15]
    if not txs:
        return await safe_edit(event, "لا توجد معاملات.", buttons=kb_admin_back())
    text = "💰 *آخر 15 معاملة:*\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for t in txs:
        emoji = "✓" if t.get('status') == 'completed' else ("⏳" if 'pending' in t.get('status', '') else "❌")
        cur = t.get('currency', '?')
        cur_display = cur
        if cur == 'STARS':
            cur_display = '⭐ Stars'
        text += f"{emoji} `{t.get('user_id')}` • `{t.get('amount_usd', 0):.2f}$` • {cur_display} • {t.get('created_at', '')[:10]}\n"
    await safe_edit(event, text, buttons=kb_admin_back())

async def admin_list_countries(event):
    if not db['countries']:
        return await safe_edit(event, "لا توجد دول مضافة.", buttons=kb_admin_countries())
    text = "🌍 *قائمة الدول:*\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for code, c in db['countries'].items():
        text += f"🔐 {c['name']} (`{code}`) — `{c['price']}$`\n"
    await safe_edit(event, text, buttons=kb_admin_countries())

async def admin_select_country_action(event, action):
    if not db['countries']:
        return await safe_edit(event, "لا توجد دول.", buttons=kb_admin_countries())
    rows = []
    for code, c in db['countries'].items():
        rows.append([Button.inline(f"{c['name']} • {c['price']}$",
                                    f"ac_{action}:{code}".encode())])
    rows.append([Button.inline("رجوع", b"a:countries")])
    if action == "edit": label = "تعديل سعر"
    elif action == "edit_name": label = "تعديل اسم"
    else: label = "حذف"
    await safe_edit(event, f"اختر دولة لـ *{label}*:", buttons=rows)

async def admin_handle_manual_action(event, action, target_id):
    if action in ('approve', 'reject'):
        tx = next((t for t in db['transactions'] if t['id'] == target_id), None)
        if not tx:
            return await event.answer("غير موجودة", alert=True)
        if tx['status'] != 'pending_manual':
            return await event.answer(f"حالتها: {tx['status']}", alert=True)
        if action == 'approve':
            tx['status'] = 'completed'
            user_id = tx['user_id']
            amount = tx['amount_usd']
            if amount <= 0:
                set_user_state(event.sender_id, 'a_manual_tx_amount', tx_id=target_id)
                save_db(db)
                return await safe_edit(event,
                    f"💰 *معاملة #{target_id}* — أرسل المبلغ المؤكد بالدولار للإضافة:",
                    buttons=kb_admin_cancel()
                )
            if tx.get('txid'):
                mark_txid_used(tx['txid'])
            update_balance(user_id, amount)
            save_db(db)
            try:
                await send_msg(user_id,
                    f"🔐 *تمت الموافقة على شحنك* 🔐\n\n💰 المبلغ: `{amount:.2f}$`\n💳 رصيدك: `{get_balance(user_id):.2f}$`"
                )
            except Exception:
                pass
            await safe_edit(event,
                f"✅ *تم اعتماد TX#{target_id}* وإضافة `{amount}$` للمستخدم `{user_id}`",
                buttons=kb_admin_back()
            )
        else:
            tx['status'] = 'rejected'
            save_db(db)
            user_id = tx['user_id']
            try:
                await send_msg(user_id,
                    f"❌ *تم رفض طلب شحنك*\n\n⚠️ يرجى التواصل مع الدعم."
                )
            except Exception:
                pass
            await safe_edit(event,
                f"❌ *تم رفض TX#{target_id}*",
                buttons=kb_admin_back()
            )

    elif action in ('mp_approve', 'mp_reject', 'binance_approve', 'binance_reject',
                      'binance_confirm_amount', 'mp_confirm_amount',
                      'mp_punish', 'binance_punish', 'binance_ban5'):
        req = next((r for r in db['manual_requests'] if r['id'] == target_id), None)
        if not req:
            return await event.answer("غير موجود", alert=True)
        if req['status'] != 'pending':
            return await event.answer(f"حالته: {req['status']}", alert=True)

        # === الموافقة على الدفع اليدوي بالمبلغ المطلوب ===
        if action == 'mp_approve':
            req['status'] = 'approved'
            user_id = req['user_id']
            amount = req['amount']
            update_balance(user_id, amount)
            save_db(db)
            try:
                await send_msg(user_id,
                    f"✅ تم التأكد من عملية الشحن\n\n"
                    f"المبلغ المضاف: `{amount:.2f}$`\n"
                    f"رصيدك الحالي: `{get_balance(user_id):.2f}$`\n"
                    f"💲 شكراً لاستخدامك البوت!"
                )
            except Exception:
                pass
            await safe_edit(event,
                f"✅ *تم اعتماد #{target_id}* — أُضيف `{amount}$` للمستخدم `{user_id}`",
                buttons=kb_admin_back()
            )

        # === الموافقة على شحن Binance بالمبلغ المطلوب ===
        elif action == 'binance_approve':
            req['status'] = 'approved'
            user_id = req['user_id']
            amount = req['amount']
            txid = str(req.get('hashid') or '').strip()
            if txid and is_txid_used(txid, exclude_manual_id=target_id):
                req['status'] = 'rejected'
                save_db(db)
                return await event.answer("هذا TXID مستخدم مسبقًا.", alert=True)
            if txid:
                mark_txid_used(txid)
            db.setdefault('transactions', []).append({
                'id': _next('next_tx_id'),
                'user_id': user_id,
                'currency': 'USDT',
                'txid': txid,
                'amount_usd': amount,
                'amount_crypto': amount,
                'status': 'completed',
                'source': 'binance_pay_admin_approved',
                'receiver_id': req.get('receiver_id', BINANCE_TRANSFER_ID),
                'created_at': datetime.now().isoformat(),
            })
            balance_before = get_balance(user_id)
            update_balance(user_id, amount)
            balance_after = get_balance(user_id)
            save_db(db)
            try:
                await send_msg(user_id,
                    f"✅ *تمت الموافقة على شحن Binance Pay*\n\n"
                    f"💰 المبلغ المضاف: `{amount:.2f}$`\n"
                    f"📉 رصيدك قبل: `{balance_before:.2f}$`\n"
                    f"📈 رصيدك بعد: `{balance_after:.2f}$`\n\n"
                    f"🎉 شكرًا لاستخدام بوت MOSCOW NAMBER."
                )
            except Exception:
                pass
            await safe_edit(event,
                f"✅ *تم اعتماد شحن Binance #{target_id}* — أُضيف `{amount}$` للمستخدم `{user_id}`",
                buttons=kb_admin_back()
            )

        # === رفض الدفع اليدوي ===
        elif action == 'mp_reject':
            req['status'] = 'rejected'
            save_db(db)
            try:
                await send_msg(req['user_id'],
                    f"❌ *تم رفض دفعتك اليدوية #{target_id}*\n\n"
                    f"⚠️ سبب الرفض: المبلغ في صورة التحويل لا يطابق المبلغ المطلوب.\n"
                    f"💡 يرجى مراجعة التحويل وإرسال طلب جديد."
                )
            except Exception:
                pass
            await safe_edit(event,
                f"❌ *تم رفض #{target_id}*",
                buttons=kb_admin_back()
            )

        # === رفض شحن Binance ===
        elif action == 'binance_reject':
            req['status'] = 'rejected'
            save_db(db)
            try:
                await send_msg(req['user_id'],
                    f"❌ *تم رفض طلب شحن Binance #{target_id}*\n\n"
                    "⚠️ معرف العملية غير صحيح أو لم يتم العثور على تحويل مطابق.\n"
                    "💡 تأكد من TXID وأرسل طلبًا جديدًا إذا كان التحويل صحيحًا."
                )
            except Exception:
                pass
            await safe_edit(event,
                f"❌ *تم رفض شحن Binance #{target_id}*",
                buttons=kb_admin_back()
            )

        # === تأكيد بمبلغ آخر للدفع اليدوي ===
        elif action == 'mp_confirm_amount':
            set_user_state(event.sender_id, 'a_mp_confirm_amount', req_id=target_id, req_type='manual')
            await safe_edit(event,
                f"✏️ *طلب #{target_id}* — أدخل المبلغ الفعلي المرئي في الصورة:\n\n"
                f"👤 المستخدم: `{req['user_id']}`\n"
                f"💳 الطريقة: *{req['method']}*\n"
                f"💰 المبلغ المطلوب: `{req['amount']}$`\n\n"
                f"⚠️ *أدخل المبلغ الذي تراه في الصورة بالتحديد*",
                buttons=kb_admin_cancel()
            )

        # === تأكيد بمبلغ آخر لشحن Binance ===
        elif action == 'binance_confirm_amount':
            set_user_state(event.sender_id, 'a_mp_confirm_amount', req_id=target_id, req_type='binance')
            await safe_edit(event,
                f"✏️ *شحن Binance #{target_id}* — أدخل المبلغ الفعلي المرئي في الصورة:\n\n"
                f"👤 المستخدم: `{req['user_id']}`\n"
                f"💰 المبلغ المطلوب: `{req['amount']}$`\n"
                f"🔑 الهاش: `{req.get('hashid', 'لا يوجد')}`\n\n"
                f"⚠️ *أدخل المبلغ الذي تراه في الصورة بالتحديد*\n"
                f"💡 مثال: إذا المستخدم طلب 50$ لكن الصورة فيها 5$ فقط، اكتب: 5",
                buttons=kb_admin_cancel()
            )

        # === رفض فقط (بدون حظر) — الدفع اليدوي ===
        elif action == 'mp_punish':
            req['status'] = 'rejected'
            user_id = req['user_id']
            save_db(db)
            try:
                await send_msg(user_id,
                    f"🚫 *تم رفض طلبك#{target_id} إدارياً* \n\n"
                    f"⚠️ السبب: *محاولة تلاعب*\n"
                    f"📩 تواصل مع الدعم إن كان هناك خطأ."
                )
            except Exception:
                pass
            await safe_edit(event,
                f"❌ *تم رفض الطلب* `{target_id}` للمستخدم `{user_id}` (بدون حظر — الحظر التلقائي معطّل)",
                buttons=kb_admin_back()
            )

        elif action == 'binance_ban5':
            req['status'] = 'rejected'
            user_id = req['user_id']
            db['users'].setdefault(str(user_id), {})['temp_ban_until'] = time.time() + 300
            save_db(db)
            try:
                await send_msg(user_id,
                    "🚫 *تم رفض طلبك إدارياً*\n\n⚠️ السبب: *محاولة تلاعب في شحن Binance*\n⏱️ تم حظرك مؤقتاً لمدة *5 دقائق*.")
            except Exception:
                pass
            await safe_edit(event,
                f"🔨 *تم حظر المستخدم* `{user_id}` لمدة 5 دقائق بسبب التلاعب في شحن Binance.",
                buttons=kb_admin_back()
            )

        # === رفض فقط (بدون حظر) — شحن Binance ===
        elif action == 'binance_punish':
            req['status'] = 'rejected'
            user_id = req['user_id']
            save_db(db)
            try:
                await send_msg(user_id,
                    f"🚫 *تم رفض طلبك#{target_id} إدارياً* \n\n"
                    f"⚠️ السبب: *محاولة تلاعب في شحن Binance*\n"
                    f"📩 تواصل مع الدعم إن كان هناك خطأ."
                )
            except Exception:
                pass
            await safe_edit(event,
                f"❌ *تم رفض طلب الشحن Binance* `{target_id}` للمستخدم `{user_id}` (بدون حظر)",
                buttons=kb_admin_back()
            )


async def admin_show_channels(event):
    channels = db['settings'].get('force_channels', [])
    enabled = db['settings'].get('force_sub_enabled', True)
    status_lbl = "✅ مُفعل" if enabled else "❌ مُعطل"
    text = (
        "📺 *قنوات الاشتراك الإجباري*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔨 الحالة: {status_lbl}\n\n"
    )
    if not channels:
        text += "⚠️ لا توجد قنوات حالياً.\n"
    else:
        for i, ch in enumerate(channels):
            text += f"{i+1}. {ch.get('title')} (@{ch.get('username')}) — `{ch.get('id')}`\n"
    rows = [
        [Button.inline("تفعيل / تعطيل", b"ac_fs:toggle")],
        [Button.inline("إضافة قناة", b"ac_fs:add")],
    ]
    monitored = db['settings'].get('monitored_channels', [])
    for i, ch in enumerate(channels):
        is_monitored = "✅ مراقبة" if ch['id'] in monitored else "⚪️ مراقبة"
        rows.append([
            Button.inline(f"حذف: {ch.get('title','')[:20]}", f"ac_fs:del:{i}".encode()),
            Button.inline(is_monitored, f"ac_fs:monitor:{ch['id']}".encode())
        ])
    rows.append([Button.inline("رجوع", b"a:panel")])
    await safe_edit(event, text, buttons=rows)


# ================================
#  معالج الأحداث الخام للدفع بالنجوم
# ================================
@bot.on(events.Raw(types.UpdateBotPrecheckoutQuery))
async def precheckout_handler(event):
    try:
        await bot(functions.messages.SetBotPrecheckoutResultsRequest(
            query_id=event.query_id,
            success=True
        ))
    except Exception as e:
        logger.error(f"Precheckout failed: {e}")

@bot.on(events.Raw(types.UpdateNewMessage))
@bot.on(events.Raw(types.UpdateNewChannelMessage))
async def raw_payment_handler(event):
    try:
        if not hasattr(event, 'message'):
            return
        msg = event.message
        action = getattr(msg, 'action', None)
        if isinstance(action, types.MessageActionPaymentSentMe):
            payment = action
            payload = getattr(payment, 'payload', None)
            if payload and isinstance(payload, bytes):
                payload_str = payload.decode('utf-8')
                decoded = stars_payload_decode(payload_str)
                if decoded is not None:
                    await process_stars_payment(msg.peer_id, payment, decoded)
    except Exception as e:
        logger.error(f"Error in raw_payment_handler: {e}")

async def process_stars_payment(peer, payment, decoded):
    try:
        if isinstance(peer, types.PeerUser):
            uid = peer.user_id
            if int(uid) != int(decoded['uid']):
                logger.error(f"Stars payload uid mismatch: peer={uid} payload={decoded['uid']}")
                return
        else:
            uid = decoded['uid']
        expected_stars = decoded['stars']
        telegram_total = getattr(payment, 'total_amount', None) \
                         or getattr(payment, 'charge_amount', None)
        if telegram_total is None or int(telegram_total) != int(expected_stars):
            logger.error(
                f"Raw stars total mismatch: telegram={telegram_total} expected={expected_stars} uid={uid}"
            )
            return
        expected_usd = stars_to_usd(expected_stars)
        charge_id = str(getattr(payment, 'charge_id',
                                 getattr(payment, 'telegram_payment_charge_id',
                                         f"STARS_RAW_{uid}_{int(time.time()*1000)}")))
        await _finalize_stars_deposit(uid, expected_stars, charge_id, expected_usd, source='raw')
    except ValueError as ve:
        logger.error(f"Raw stars validation error: {ve}")
    except Exception as e:
        logger.error(f"Error in process_stars_payment: {e}")

# ================================
#  تحميل المحافظ وإزالة التكرار
# ================================
async def load_wallets_override():
    override = db['settings'].get('wallets_override', {})
    for cur, addr in override.items():
        if cur in WALLETS:
            WALLETS[cur] = addr

# ================================
#  دوال تسجيل الدخول للأدمن
# ================================
pending_admin_logins = {}

async def start_admin_login(phone):
    phone = phone.strip()
    if phone in pending_admin_logins:
        try:
            old = pending_admin_logins[phone].get('client')
            if old:
                await old.disconnect()
        except Exception:
            pass
        pending_admin_logins.pop(phone, None)
    client = TelegramClient(
        StringSession(), API_ID, API_HASH,
        device_model="iPhone 14 Pro", system_version="iOS 17.0",
        app_version="10.0", lang_code="en"
    )
    try:
        await client.connect()
    except Exception as e:
        return False, f"فشل الاتصال: {e}"
    try:
        sent = await client.send_code_request(phone, force_sms=False)
        pending_admin_logins[phone] = {
            'client': client,
            'phone_code_hash': sent.phone_code_hash
        }
        return True, "تم إرسال الكود إلى تطبيق تيليجرام"
    except FloodWaitError as e:
        await client.disconnect()
        return False, f"flood: انتظر {e.seconds} ث"
    except PhoneNumberInvalidError:
        await client.disconnect()
        return False, "رقم غير صحيح"
    except PhoneNumberBannedError:
        await client.disconnect()
        return False, "الرقم محظور"
    except Exception as e:
        try:
            await client.disconnect()
        except Exception:
            pass
        return False, f"خطأ: {e}"

async def submit_admin_code(phone, code, password=None):
    phone = phone.strip()
    if phone not in pending_admin_logins:
        return False, "لم يسبق طلب كود لهذا الرقم", None
    info = pending_admin_logins[phone]
    client = info['client']
    try:
        if not client.is_connected():
            await client.connect()
    except Exception:
        pass
    try:
        await client.sign_in(phone=phone, code=str(code), phone_code_hash=info['phone_code_hash'])
    except SessionPasswordNeededError:
        if password:
            try:
                await client.sign_in(password=password)
            except Exception as e:
                return False, f"كلمة المرور خطأ: {e}", None
        else:
            return False, "2FA", None
    except PhoneCodeInvalidError:
        return False, "الكود غير صحيح", None
    except PhoneCodeExpiredError:
        pending_admin_logins.pop(phone, None)
        return False, "انتهت صلاحية الكود", None
    except Exception as e:
        return False, f"خطأ: {e}", None
    session = client.session.save()
    try:
        with open(os.path.join(SESSIONS_DIR, f"{phone}.session"), 'w') as f:
            f.write(session)
    except Exception:
        pass
    try:
        await client.disconnect()
    except Exception:
        pass
    pending_admin_logins.pop(phone, None)
    return True, "تم تسجيل الدخول", session

# ================================
#  معالج النصوص للأدمن (الحالات a_*) - مع تعديلات السبام الكاملة
# ================================
async def handle_admin_text(event, user, state, sdata, text):
    uid = user.id

    if state == 'a_bulk_2fa_new':
        new_pass = text.strip()
        if not new_pass:
            return await send_msg(event, "يرجى إرسال كلمة مرور صالحة.", buttons=kb_admin_cancel())
        
        clear_user_state(uid)
        await send_msg(event, "⏳ جاري البدء في تغيير التحقق بخطوتين لجميع الأرقام المتاحة تلقائياً... يرجى الانتظار.")
        
        available_accs = [a for a in db.get('accounts', []) if a.get('status') == 'available']
        total = len(available_accs)
        success = 0
        failed = 0
        
        for acc in available_accs:
            phone = acc.get('phone')
            session_str = acc.get('session')
            # جلب كلمة المرور المخزنة لهذا الرقم تحديداً
            current_stored_pass = acc.get('password')
            
            if not session_str:
                failed += 1
                continue
                
            try:
                client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
                await client.connect()
                if await client.is_user_authorized():
                    # تغيير كلمة المرور باستخدام الكلمة المخزنة لكل رقم تلقائياً
                    # محاولة تغيير 2FA. إذا كان هناك كلمة مرور حالية، نستخدمها.
                    # إذا فشلت المحاولة الأولى (بسبب كلمة مرور خاطئة أو عدم وجودها)، نحاول مرة أخرى بدون كلمة مرور حالية.
                    try:
                        # محاولة تغيير 2FA باستخدام كلمة المرور المخزنة
                        await client.edit_2fa(new_password=new_pass, current_password=current_stored_pass)
                    except Exception as inner_e:
                        # إذا فشلت المحاولة الأولى (بسبب كلمة مرور خاطئة أو عدم وجودها)، نحاول بدون كلمة مرور حالية
                        try:
                            await client.edit_2fa(new_password=new_pass, current_password=None)
                        except Exception:
                            # إذا فشلت المحاولتان، نعيد رمي الخطأ الأصلي
                            raise inner_e
                    acc['password'] = new_pass
                    success += 1
                    logger.info(f"✅ تم تغيير 2FA للرقم {phone} بنجاح.")
                else:
                    failed += 1
                    logger.warning(f"⚠️ الجلسة غير مصرح بها للرقم {phone}")
                await client.disconnect()
            except Exception as e:
                failed += 1
                logger.error(f"❌ فشل تغيير 2FA للرقم {phone}: {e}")
            
            # انتظار قصير لتجنب الحظر
            await asyncio.sleep(2)
            
        save_db(db)
        return await send_msg(event,
            f"✅ *اكتملت عملية التغيير التلقائي للـ 2FA*\n\n"
            f"📊 النتائج:\n"
            f"• الإجمالي: `{total}`\n"
            f"• نجاح: `{success}`\n"
            f"• فشل: `{failed}`\n\n"
            f"(EMOJI5307843983102204243) الكلمة الجديدة الموحدة: `{new_pass}`",
            buttons=kb_admin_accounts()
        )

    if state == 'a_referral_price':
        clear_user_state(uid)
        return await send_msg(
            event,
            "🔒 سعر رابط الدعوة ثابت دائماً: `0.006$` لكل إحالة ناجحة.",
            buttons=kb_admin_referral()
        )

    if state == 'a_awaiting_referral_link':
        if not is_admin(uid):
            clear_user_state(uid)
            return
        referral_link = text.strip()
        clear_user_state(uid)
        return await run_referral_cases(event, referral_link)

    if state == 'a_awaiting_admin_id':
        if uid != OWNER_ID:
            clear_user_state(uid)
            return
        target_id_str = text.strip()
        if not target_id_str.isdigit():
            return await send_msg(event, "يرجى إرسال معرف (ID) صحيح (أرقام فقط).", buttons=kb_admin_cancel())
        
        target_id = int(target_id_str)
        extra_admins = db['settings'].get('extra_admins', [])
        
        if target_id in ADMINS or target_id in extra_admins:
            clear_user_state(uid)
            return await send_msg(event, "هذا الشخص مسؤول بالفعل في البوت.", buttons=kb_admin_main(uid))
            
        extra_admins.append(target_id)
        db['settings']['extra_admins'] = extra_admins
        save_db(db)
        clear_user_state(uid)
        
        # محاولة إخطار الأدمن الجديد
        try:
            await bot.send_message(target_id, "🎉 تهانينا! لقد تم تعيينك كمسؤول في البوت من قبل المدير العام.")
        except: pass
        
        return await send_msg(event, f"تم تعيين المستخدم `{target_id}` كمسؤول جديد بنجاح.", buttons=kb_admin_main(uid))

    if state == 'a_fs_add':
        parts = text.strip().split(maxsplit=2)
        if len(parts) < 3:
            return await send_msg(event,
                "⚠️ الصيغة: `channel_id username العنوان`",
                buttons=kb_admin_cancel())
        try:
            cid = int(parts[0])
        except Exception:
            return await send_msg(event, "channel_id غير صالح", buttons=kb_admin_cancel())
        un = parts[1].lstrip('@')
        title = parts[2]
        chs = db['settings'].get('force_channels', [])
        if any(int(ch.get('id')) == cid for ch in chs if ch.get('id') is not None):
            return await send_msg(event, "⚠️ هذه القناة مضافة بالفعل.", buttons=kb_admin_back())

        # ثبّت لقطة القنوات السابقة لكل إحالة قبل إضافة القناة الجديدة.
        # نحدّث كل السجلات، وليس السجلات التي لا تحتوي على المفتاح فقط،
        # لأن بعض الإصدارات القديمة كانت قد خزنت لقطة تشمل قناة أضيفت لاحقاً.
        previous_ids = [ch.get('id') for ch in chs if ch.get('id') is not None]
        for rec in db.get('referrals', {}).values():
            if not isinstance(rec, dict):
                continue
            old_ids = rec.get('force_channel_ids')
            if not isinstance(old_ids, list):
                old_ids = list(previous_ids)
            rec['force_channel_ids'] = [x for x in old_ids if x != cid]

        chs.append({"id": cid, "username": un, "title": title, "added_at": datetime.now().isoformat()})
        db['settings']['force_channels'] = chs
        save_db(db)
        clear_user_state(uid)
        return await send_msg(event, f"تمت إضافة القناة *{title}*",
            buttons=kb_admin_back())

    if state == 'a_scam_channel_link':
        username=scam_channel_username(text)
        if not username or not re.match(r'^[A-Za-z0-9_]{5,}$',username):
            return await send_msg(event,'⚠️ رابط أو يوزر قناة غير صالح. مثال: `https://t.me/channel`',buttons=kb_admin_cancel())
        set_user_state(uid,'a_scam_channel_price',username=username)
        return await send_msg(event,'💰 أرسل سعر القناة بالدولار، مثال: `0.2`:',buttons=kb_admin_cancel())
    if state == 'a_scam_channel_price':
        try:
            price=float(text.strip())
            if price<=0: raise ValueError
        except Exception:
            return await send_msg(event,'⚠️ السعر غير صالح.',buttons=kb_admin_cancel())
        username=sdata.get('username')
        if any(scam_channel_username(c.get('username')).lower()==username.lower() and c.get('status','available')=='available' for c in db.get('scam_channels',[])):
            return await send_msg(event,'⚠️ هذه القناة موجودة ومتاحة بالفعل.',buttons=kb_admin_back())
        channel_id=_next('next_scam_channel_id')
        db.setdefault('scam_channels',[]).append({'id':channel_id,'username':username,'price':price,'status':'available','added_at':datetime.now().isoformat()})
        save_db(db); clear_user_state(uid)
        return await send_msg(event,f'✅ تمت إضافة القناة @{username} بسعر `${price:.2f}`.',buttons=kb_admin_back())

    if state == 'a_emoji_add':
        raw = text.strip()
        if not raw:
            return await send_msg(event, "لم ترسل شيئاً.", buttons=kb_admin_cancel())
        m = re.match(r'^\s*(\S+?)\s+(\d{6,})\s*$', raw)
        if not m:
            return await send_msg(event,
                "⚠️ الصيغة غير صحيحة.\n\n"
                "⚡ الصيغة الصحيحة:\n"
                "`الإيموجي رقم_الإيموجي_المخصص`\n\n"
                "مثال: `🔐 5222148368955877900`",
                buttons=kb_admin_cancel())
        emo = m.group(1)
        eid = m.group(2)
        emojis = db.get('custom_emojis', {}) or {}
        emojis[emo] = eid
        db['custom_emojis'] = emojis
        save_db(db)
        clear_user_state(uid)
        return await send_msg(event,
            f"✅ *تمت الإضافة بنجاح*\n\n"
            f"{emo} ←→ `{eid}`\n\n"
            f"🔐 سيتم تحويل هذا الإيموجي تلقائيّاً في جميع الرسائل.",
            buttons=kb_admin_back())

    if state == 'a_hidebtn_add':
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return await send_msg(event, "لم تكتب أي اسم.", buttons=kb_admin_cancel())
        hidden = db.get('hidden_buttons', []) or []
        added = 0
        for ln in lines:
            ln_compact = _compact_button_text(ln)
            if ln_compact and ln_compact not in [_compact_button_text(h) for h in hidden]:
                hidden.append(ln_compact)
                added += 1
        db['hidden_buttons'] = hidden
        save_db(db)
        clear_user_state(uid)
        return await send_msg(event,
            f"✅ *تم إخفاء `{added}` زرّاً*\n\n"
            f"📊 إجمالي الأزرار المخفية: `{len(hidden)}`",
            buttons=kb_admin_back())

    if state == 'a_btn_add':
        if '|' not in text:
            return await send_msg(event,
                "⚠️ الصيغة: `العنوان | الرابط`",
                buttons=kb_admin_cancel())
        title, url = [p.strip() for p in text.split('|', 1)]
        if not (url.startswith('http://') or url.startswith('https://') or url.startswith('tg://')):
            return await send_msg(event, "الرابط غير صالح", buttons=kb_admin_cancel())
        btns = db.get('main_url_buttons', []) or []
        btns.append({"title": title, "url": url})
        db['main_url_buttons'] = btns
        save_db(db)
        clear_user_state(uid)
        return await send_msg(event, f"تمت إضافة الزر *{title}*",
            buttons=kb_admin_back())

    if state == 'a_btnedit_manualkey':
        key = text.strip()
        if not key:
            return await send_msg(event, "مفتاح غير صالح", buttons=kb_admin_cancel())
        set_user_state(uid, 'a_btnedit_text', btn_key=key, btn_label=key)
        cur = db.get('button_overrides', {}).get(key, {})
        cur_text = cur.get('text', '—')
        cur_emoji = cur.get('emoji_id', '—')
        return await send_msg(event,
            f"✏️ *تعديل الزر:* `{key}`\n"
            f"(EMOJI5798514803777478100) النص الحالي: `{cur_text}`\n"
            f"🎨 الإيموجي: `{cur_emoji}`\n\n"
            "⚡ أرسل النص الجديد (أو `=` للإبقاء على الحالي)",
            buttons=kb_admin_cancel())

    if state == 'a_btnedit_text':
        new_text = text.strip()
        btn_key = sdata.get('btn_key')
        btn_label = sdata.get('btn_label', btn_key)
        cur = db.get('button_overrides', {}).get(btn_key, {})
        if new_text == '=':
            new_text = cur.get('text') or btn_label
        if not new_text:
            return await send_msg(event, "نص غير صالح", buttons=kb_admin_cancel())
        set_user_state(uid, 'a_btnedit_emoji',
                       btn_key=btn_key, btn_label=btn_label, btn_text=new_text)
        return await send_msg(event,
            f"✅ تم حفظ النص الجديد: `{new_text}`\n\n"
            "🎨 الآن أرسل *رقم الإيموجي المخصص* (Document ID):\n"
            "  · مثال: `5325612636467903082`\n"
            "  · اكتب `=` للإبقاء على الحالي\n"
            "  · اكتب `-` لإزالة الإيموجي",
            buttons=kb_admin_cancel())

    if state == 'a_btnedit_emoji':
        emoji_id = text.strip()
        btn_key = sdata.get('btn_key')
        new_text = sdata.get('btn_text')
        cur = db.get('button_overrides', {}).get(btn_key, {})
        if emoji_id == '=':
            emoji_id = cur.get('emoji_id', '')
        elif emoji_id == '-':
            emoji_id = ''
        else:
            if not emoji_id.isdigit() or not (5 <= len(emoji_id) <= 25):
                return await send_msg(event,
                    "⚠️ رقم إيموجي غير صالح. جرّب رقماً من 5 إلى 25 خانة أرقام فقط.",
                    buttons=kb_admin_cancel())
        overrides = db.get('button_overrides', {}) or {}
        overrides[btn_key] = {"text": new_text, "emoji_id": emoji_id}
        db['button_overrides'] = overrides
        save_db(db)
        clear_user_state(uid)
        return await send_msg(event,
            f"✅ *تم حفظ التعديل بنجاح*\n\n"
            f"(EMOJI5798514803777478100) المفتاح: `{btn_key}`\n"
            f"✏️ النص الجديد: `{new_text}`\n"
            f"🎨 الإيموجي: `{emoji_id or '—'}`\n\n"
            f"⚡ التغيير يظهر فوراً في جميع الرسائل القادمة.",
            buttons=kb_admin_back())

    if state == 'a_country_code':
        code = text.strip().lstrip('+')
        if not code.isdigit() or len(code) > 5:
            return await send_msg(event, "الرمز يجب أن يكون أرقام (1-5 خانات).")
        auto_name = get_country_name(code)
        set_user_state(uid, 'a_country_name', code=code, auto_name=auto_name)
        return await send_msg(event,
            f"✅ الرمز: `{code}`\n📝 الاسم المقترح: {auto_name}\n\n"
            "⚡ أرسل اسم الدولة (أو `=` لاستخدام المقترح):",
            buttons=kb_admin_cancel()
        )

    if state == 'a_country_name':
        name = text.strip()
        if name == '=':
            name = sdata.get('auto_name')
        set_user_state(uid, 'a_country_price', code=sdata['code'], name=name)
        return await send_msg(event,
            "💰 أرسل سعر الحساب لهذه الدولة (مثل: `1.50`):",
            buttons=kb_admin_cancel()
        )

    if state == 'a_country_price':
        try:
            price = float(text)
            if price <= 0:
                raise ValueError
        except Exception:
            return await send_msg(event, "سعر غير صالح.", buttons=kb_admin_cancel())
        code = sdata['code']
        name = sdata['name']
        db['countries'][code] = {'name': name, 'price': price}
        save_db(db)
        clear_user_state(uid)
        return await send_msg(event,
            f"🔐 *تم إضافة الدولة* 🔐\n\n🌍 {name}\n📞 الرمز: `{code}`\n💰 السعر: `{price}$`",
            buttons=kb_admin_countries()
        )

    if state == 'a_country_edit_price':
        try:
            price = float(text)
        except Exception:
            return await send_msg(event, "سعر غير صالح.", buttons=kb_admin_cancel())
        code = sdata['code']
        if code in db['countries']:
            db['countries'][code]['price'] = price
            for a in db['accounts']:
                if a['country_code'] == code and a['status'] == 'available' and not a.get('is_spam', False):
                    a['price'] = price
            save_db(db)
        clear_user_state(uid)
        return await send_msg(event,
            f"✅ *تم تحديث السعر إلى* `{price}$`",
            buttons=kb_admin_countries()
        )

    if state == 'a_country_edit_name':
        name = text.strip()
        code = sdata['code']
        if code in db['countries']:
            old_name = db['countries'][code]['name']
            db['countries'][code]['name'] = name
            if 'accounts' in db:
                for a in db['accounts']:
                    if a.get('country_code') == code:
                        a['country_name'] = name
            if 'providers' in db:
                for prov, pdata in db['providers'].items():
                    for section in ['wa', 'sms']:
                        sec_data = pdata.get(section, {})
                        if code in sec_data:
                            sec_data[code]['name'] = name
            save_db(db)
            clear_user_state(uid)
            return await send_msg(event,
                f"✅ *تم تحديث اسم الدولة بنجاح*\n\nمن: `{old_name}`\nإلى: `{name}`",
                buttons=kb_admin_countries()
            )
        clear_user_state(uid)
        return await send_msg(event, "الدولة غير موجودة.", buttons=kb_admin_countries())

    if state == 'a_set_default_price':
        try:
            price = float(text)
            if price <= 0: raise ValueError
        except Exception:
            return await send_msg(event, "سعر غير صالح.", buttons=kb_admin_cancel())
        db['settings']['default_price'] = price
        global DEFAULT_ACCOUNT_PRICE
        DEFAULT_ACCOUNT_PRICE = price
        save_db(db)
        clear_user_state(uid)
        return await send_msg(event, f"✅ تم تحديث السعر الافتراضي إلى: `{price}$`", buttons=kb_admin_countries())

    if state == 'a_set_mixed_price':
        try:
            price = float(text)
            if price <= 0: raise ValueError
        except Exception:
            return await send_msg(event, "سعر غير صالح.", buttons=kb_admin_cancel())
        db['settings']['mixed_price'] = price
        global MIXED_PRICE
        MIXED_PRICE = price
        save_db(db)
        clear_user_state(uid)
        return await send_msg(event, f"✅ تم تحديث سعر المخطلت إلى: `{price}$`", buttons=kb_admin_countries())

    if state == 'a_set_old_spam_price':
        try:
            price = float(text)
            if price <= 0: raise ValueError
        except Exception:
            return await send_msg(event, "سعر غير صالح.", buttons=kb_admin_cancel())
        db['settings']['old_spam_price'] = price
        global OLD_SPAM_PRICE
        OLD_SPAM_PRICE = price
        db['countries'].setdefault(OLD_SPAM_CODE, {'name': OLD_SPAM_LABEL, 'price': price})['price'] = price
        for a in db.get('accounts', []):
            if a.get('is_old_spam') and a.get('status') == 'available':
                a['price'] = price
        save_db(db)
        clear_user_state(uid)
        return await send_msg(event, f"✅ تم تحديث سعر {OLD_SPAM_LABEL} إلى: `{price}$`", buttons=kb_admin_countries())

    if state == 'a_set_fake_price':
        try:
            price = float(text)
            if price <= 0: raise ValueError
        except Exception:
            return await send_msg(event, "سعر غير صالح.", buttons=kb_admin_cancel())
        db['settings']['fake_price'] = price
        global FAKE_PRICE
        FAKE_PRICE = price
        save_db(db)
        clear_user_state(uid)
        return await send_msg(event, f"✅ تم تحديث سعر الاحتيالي إلى: `{price}$`", buttons=kb_admin_countries())


    # ======================================================
    #  حالة أرقام قديمة: إدخال سنة الإنشاء يدويًا
    # ======================================================
    if state == 'a_awaiting_old_year':
        if not text.isdigit() or not (2010 <= int(text) <= datetime.now().year):
            return await send_msg(event, f"أرسل سنة صحيحة بين 2010 و{datetime.now().year}:", buttons=kb_admin_cancel())
        pending = db.get('pending_spam_choice', {})
        if not pending:
            clear_user_state(uid)
            return await send_msg(event, "لا توجد عملية معلقة.", buttons=kb_admin_accounts())
        pending['old_year'] = int(text)
        classification = sdata.get('classification', 'old')
        pending['is_old'] = classification == 'old'
        pending['is_fake'] = classification == 'fake'
        db['pending_spam_choice'] = pending
        save_db(db)
        set_user_state(uid, 'a_awaiting_account_price')
        return await send_msg(event, "💰 أرسل السعر الذي تريده لهذا الرقم أو لهذه الجلسة بالدولار، مثال: `0.8`:", buttons=kb_admin_cancel())

    # ======================================================
    #  حالة إضافة رقم هاتف يدوياً – مع السؤال عن التصنيف
    # ======================================================
    if state == 'a_awaiting_account_price':
        try:
            price = float(text)
            if price <= 0: raise ValueError
        except Exception:
            return await send_msg(event, "يرجى إرسال سعر صحيح (رقم موجب).")
        
        pending = db.get('pending_spam_choice', {})
        if not pending:
            clear_user_state(uid)
            return await send_msg(event, "لا توجد عملية معلقة.", buttons=kb_admin_accounts())
        
        typ = pending.get('type')
        is_spam = pending.get('is_spam', False)
        is_spam_mix = pending.get('is_spam_mix', False)
        is_fake = pending.get('is_fake', False)
        is_unverified = pending.get('is_unverified', False)
        is_old = pending.get('is_old', False)
        is_old_spam = pending.get('is_old_spam', False)
        is_usa_clean = pending.get('is_usa_clean', False)
        is_monthly = pending.get('is_monthly', False)
        is_daily_special = pending.get('is_daily_special', False)
        is_bimonthly = pending.get('is_bimonthly', False)
        
        if typ == 'phone':
            phone = pending['phone']
            code = pending['code']
            name = pending['name']
            if is_daily_special:
                code = DAILY_NUMBERS_CODE
                name = DAILY_NUMBERS_LABEL
            elif is_bimonthly:
                code = BIMONTHLY_NUMBERS_CODE
                name = BIMONTHLY_NUMBERS_LABEL
            elif is_monthly:
                code = MONTHLY_NUMBERS_CODE
                name = MONTHLY_NUMBERS_LABEL
            elif is_unverified:
                code = UNVERIFIED_CODE
                name = UNVERIFIED_LABEL
            elif is_fake:
                detected_code, detected_name = detect_country(phone)
                if not detected_code:
                    return await send_msg(event, "تعذر تحديد دولة الرقم المزيف والاحتيالي.", buttons=kb_admin_accounts())
                name = f"{detected_name} ⚠️ مزيف واحتيالي"
                code = f"fake_{detected_code}"
            elif is_old_spam:
                detected_code, detected_name = detect_country(phone)
                if not detected_code:
                    return await send_msg(event, "تعذر تحديد دولة الرقم الاسبام القديم.", buttons=kb_admin_accounts())
                name = f"{detected_name} {OLD_SPAM_LABEL}"
                code = OLD_SPAM_CODE
            elif is_old:
                detected_code, detected_name = detect_country(phone)
                if not detected_code:
                    return await send_msg(event, "تعذر تحديد دولة الرقم القديم.", buttons=kb_admin_accounts())
                year = pending.get('old_year')
                name = f"{detected_name} {year}"
                code = f"old_{detected_code}_{year}"
            elif is_spam_mix or is_spam:
                detected_code, detected_name = detect_country(phone)
                if not detected_code:
                    return await send_msg(event, "تعذر تحديد دولة الرقم السبام.", buttons=kb_admin_accounts())
                name = f"{detected_name} {SPAM_MIX_LABEL}" if is_spam_mix else f"{detected_name} 📛"
                code = f"{SPAM_MIX_CODE}_{detected_code}" if is_spam_mix else f"spam_{detected_code}"
            # إرسال طلب كود إلى الرقم
            success, msg = await start_admin_login(phone)
            if success:
                db['pending_spam_choice'] = {}
                save_db(db)
                set_user_state(uid, 'awaiting_admin_code',
                               phone=phone,
                               code=code,
                               name=name,
                               price=price,
                               is_spam=is_spam, is_fake=is_fake, is_unverified=is_unverified, is_old=is_old, is_old_spam=is_old_spam,
                               is_monthly=is_monthly,
                               is_bimonthly=is_bimonthly,
                               is_usa_clean=pending.get('is_usa_clean', False),
                               custom_country_code=pending.get('custom_country_code'))
                await send_msg(event,
                    f"📱 الرقم: `{phone}`\n"
                    f"🌍 الدولة: {name}\n"
                    f"💰 السعر المختار: `{price}$`\n\n"
                    "📩 تم إرسال كود التفعيل إلى الرقم.\n"
                    "الرجاء إدخال الكود المستلم (5 أرقام).\n"
                    "💡 إذا كان الحساب محمياً بـ 2FA أرسل بصيغة: `code:password`"
                )
            else:
                await send_msg(event, f"فشل طلب الكود: {msg}", buttons=kb_admin_accounts())
                db['pending_spam_choice'] = {}
                save_db(db)
                clear_user_state(uid)
        elif typ == 'session_file':
            file_path = pending['file_path']
            file_name = pending['file_name']
            await send_msg(event, "جاري معالجة الملف بالسعر الجديد...")
            try:
                # تعديل دالة process_session_file لتقبل السعر المخصص
                result = await process_session_file(
                    file_path, file_name, is_spam, uid, custom_price=price,
                    is_fake=is_fake, is_unverified=is_unverified,
                    is_usa_clean=is_usa_clean, is_old=is_old, is_old_spam=is_old_spam, is_spam_mix=is_spam_mix,
                    old_year=pending.get('old_year'), custom_label=pending.get('custom_label'),
                    custom_country_code=pending.get('custom_country_code'),
                    is_monthly=is_monthly, is_daily_special=is_daily_special, is_bimonthly=is_bimonthly, is_random_special=pending.get('is_random_special', False))
                await send_msg(event, result, buttons=kb_admin_accounts())
            except Exception as e:
                logger.error(f"Error processing session file: {e}")
                await send_msg(event, f"فشل معالجة الملف: {e}", buttons=kb_admin_accounts())
            finally:
                if os.path.exists(file_path):
                    os.remove(file_path)
                db['pending_spam_choice'] = {}
                save_db(db)
                clear_user_state(uid)
        return



    if state == 'a_awaiting_account_target_name':
        button_name = text.strip()
        if not button_name or len(button_name) > 60:
            return await send_msg(event, "اسم الزر غير صالح. أرسله بين 1 و60 حرفًا:", buttons=kb_admin_cancel())
        code = 'custom_' + hashlib.sha1(button_name.encode('utf-8')).hexdigest()[:12]
        pending = db.get('pending_spam_choice', {})
        if not pending:
            clear_user_state(uid)
            return await send_msg(event, "لا توجد إضافة معلقة.", buttons=kb_admin_accounts())
        pending.update({'custom_country_code': code, 'custom_label': button_name,
                        'code': code, 'name': button_name, 'purchase_category': 'clean'})
        db['pending_spam_choice'] = pending
        save_db(db)
        set_user_state(uid, 'a_awaiting_account_price')
        return await send_msg(event,
            f"🏷️ الزر الجديد: *{button_name}*\n\nأرسل السعر الذي تريده لهذا الرقم/الملف، مثال: `1.20`:",
            buttons=kb_admin_cancel())

    if state == 'a_awaiting_import_target_name':
        button_name = text.strip()
        if not button_name or len(button_name) > 60:
            return await send_msg(event, "اسم الزر غير صالح. أرسله بين 1 و60 حرفًا:", buttons=kb_admin_cancel())
        code = 'custom_' + hashlib.sha1(button_name.encode('utf-8')).hexdigest()[:12]
        zip_path = sdata.get('zip_path')
        if not zip_path or not os.path.exists(zip_path):
            clear_user_state(uid)
            return await send_msg(event, "ملف ZIP غير موجود؛ أعد رفعه من لوحة الأدمن.", buttons=kb_admin_accounts())
        set_user_state(uid, 'a_awaiting_import_target_price', zip_path=zip_path,
                       custom_country_code=code, custom_label=button_name)
        return await send_msg(event,
            f"🏷️ الزر الجديد: *{button_name}*\n\nأرسل السعر لكل رقم في الملف، مثال: `1.20`:",
            buttons=kb_admin_cancel())

    if state == 'a_awaiting_import_target_price':
        try:
            price = float(text.strip())
            if price <= 0:
                raise ValueError
        except Exception:
            return await send_msg(event, "السعر غير صالح. أرسل رقمًا موجبًا مثل `1.20`:", buttons=kb_admin_cancel())
        zip_path = sdata.get('zip_path')
        label = sdata.get('custom_label')
        code = sdata.get('custom_country_code')
        if not zip_path or not os.path.exists(zip_path) or not label or not code:
            clear_user_state(uid)
            return await send_msg(event, "بيانات الاستيراد غير مكتملة؛ أعد رفع الملف.", buttons=kb_admin_accounts())
        await send_msg(event, f"جاري إضافة الأرقام إلى زر `{label}` بسعر `{price}$`...")
        added, duplicates, failed, errors = await process_uploaded_sessions_zip(
            zip_path, merge_as_mixed=False, custom_price=price,
            custom_label=label, custom_country_code=code)
        clear_user_state(uid)
        report = (f"✅ اكتمل الاستيراد إلى الزر `{label}`\n━━━━━━━━━━━━━━━━━━━━\n\n"
                  f"🟢 المضافة: `{added}`\n🟡 الموجودة وتم نقلها/تحديثها: `{duplicates}`\n"
                  f"🔴 الفاشلة: `{failed}`\n💰 السعر: `{price}$` لكل رقم\n")
        if errors:
            report += "\n📋 *الأخطاء (أول 10):*\n" + "\n".join(f"• {e}" for e in errors[:10])
        return await send_msg(event, report, buttons=[[Button.inline("رجوع للوحة", b"a:panel")]])

    if state == 'a_awaiting_zip_unverified_price':
        try:
            price = float(text.strip())
            if price <= 0: raise ValueError
        except Exception:
            return await send_msg(event, "يرجى إرسال سعر صحيح (مثال: 0.5):", buttons=kb_admin_cancel())
        zip_path = sdata.get('zip_path')
        if not zip_path or not os.path.exists(zip_path):
            clear_user_state(uid)
            return await send_msg(event, "الملف غير موجود، حاول مجددًا.", buttons=kb_admin_accounts())
        await send_msg(event, f"جاري إضافة أرقام السبام بسعر `{price}$` لكل رقم...")
        added, duplicates, failed, errors = await process_uploaded_sessions_zip(zip_path, custom_price=price, is_unverified=True)
        clear_user_state(uid)
        report = ("✅ *تمت إضافة أرقام السبام بنجاح!*\n━━━━━━━━━━━━━━━━━━━━\n\n"
                  f"🟢 المضافة: `{added}`\n🟡 المكررة: `{duplicates}`\n🔴 الفاشلة: `{failed}`\n💰 السعر: `{price}$`\n\n")
        if errors:
            report += "📋 *الأخطاء (أول 10):*\n" + "\n".join(f"  • {e}" for e in errors[:10])
        else:
            report += "✅ *تمت معالجة جميع الأرقام بنجاح!*"
        return await send_msg(event, report, buttons=[[Button.inline("رجوع للوحة", b"a:panel")]])

    if state == 'a_awaiting_zip_usa_price':
        clean_price_text = "".join(c for c in text if c.isdigit() or c == '.')
        try:
            price = float(clean_price_text)
            if price <= 0: raise ValueError
        except Exception:
            return await send_msg(event, "يرجى إرسال سعر صحيح (مثال: 0.4):", buttons=kb_admin_cancel())
        zip_path = sdata.get('zip_path')
        if not zip_path or not os.path.exists(zip_path):
            clear_user_state(uid)
            return await send_msg(event, "الملف غير موجود، حاول مجددًا.", buttons=kb_admin_accounts())
        await send_msg(event, f"جاري إضافة جلسات أمريكا بالسعر `{price}$` لكل رقم...")
        added, duplicates, failed, errors = await process_uploaded_sessions_zip(
            zip_path, merge_as_mixed=False, custom_price=price, custom_label=USA_CLEAN_LABEL
        )
        clear_user_state(uid)
        report = (
            "✅ *تمت إضافة جلسات أمريكا بنجاح!*\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🟢 الأرقام المُضافة: `{added}`\n"
            f"🟡 المكررة (تخطي): `{duplicates}`\n"
            f"🔴 الفاشلة: `{failed}`\n"
            f"💰 السعر المطبق: `{price}$` لكل رقم\n\n"
        )
        if errors:
            report += "📋 *الأخطاء (أول 10):*\n" + "\n".join(f"  • {e}" for e in errors[:10])
        else:
            report += "✅ *جميع الأرقام تمت معالجتها بنجاح!*"
        return await send_msg(event, report, buttons=[[Button.inline("رجوع للوحة", b"a:panel")]])

    if state == 'a_awaiting_zip_fake_year':
        if not text.isdigit() or not (2010 <= int(text) <= datetime.now().year):
            return await send_msg(event, f"أرسل سنة صحيحة بين 2010 و{datetime.now().year}:", buttons=kb_admin_cancel())
        zip_path = sdata.get('zip_path')
        if not zip_path or not os.path.exists(zip_path):
            clear_user_state(uid)
            return await send_msg(event, "الملف غير موجود، حاول مجددًا.", buttons=kb_admin_accounts())
        set_user_state(uid, 'a_awaiting_zip_fake_price', zip_path=zip_path, old_year=int(text))
        return await send_msg(event, "💰 أرسل السعر الذي تريده لكل رقم في هذا الملف، مثال: `0.8`:", buttons=kb_admin_cancel())

    if state == 'a_awaiting_zip_fake_price':
        clean_price_text = "".join(c for c in text if c.isdigit() or c == '.')
        try:
            price = float(clean_price_text)
            if price <= 0: raise ValueError
        except Exception:
            return await send_msg(event, "يرجى إرسال سعر صحيح (مثال: 0.8):", buttons=kb_admin_cancel())
        zip_path = sdata.get('zip_path')
        if not zip_path or not os.path.exists(zip_path):
            clear_user_state(uid)
            return await send_msg(event, "الملف غير موجود، حاول مجددًا.", buttons=kb_admin_accounts())
        await send_msg(event, f"جاري إضافة المزيف والاحتيالي بالسعر `{price}$` لكل رقم...")
        added, duplicates, failed, errors = await process_uploaded_sessions_zip(
            zip_path, merge_as_mixed=False, custom_price=price, is_fake=True, old_year=sdata.get('old_year'))
        clear_user_state(uid)
        report = (
            "✅ *تمت إضافة المزيف والاحتيالي بنجاح!*\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🟢 الأرقام المُضافة: `{added}`\n"
            f"🟡 المكررة (تخطي): `{duplicates}`\n"
            f"🔴 الفاشلة: `{failed}`\n"
            f"💰 السعر المطبق: `{price}$` لكل رقم\n\n"
        )
        if errors:
            report += "📋 *الأخطاء (أول 10):*\n" + "\n".join(f"  • {e}" for e in errors[:10])
        else:
            report += "✅ *جميع الأرقام تمت معالجتها بنجاح!*"
        return await send_msg(event, report, buttons=[[Button.inline("رجوع للوحة", b"a:panel")]])

    if state == 'a_awaiting_zip_old_year':
        if not text.isdigit() or not (2010 <= int(text) <= datetime.now().year):
            return await send_msg(event, f"أرسل سنة صحيحة بين 2010 و{datetime.now().year}:", buttons=kb_admin_cancel())
        zip_path = sdata.get('zip_path')
        if not zip_path or not os.path.exists(zip_path):
            clear_user_state(uid)
            return await send_msg(event, "الملف غير موجود، حاول مجددًا.", buttons=kb_admin_accounts())
        set_user_state(uid, 'a_awaiting_zip_old_price', zip_path=zip_path, old_year=int(text))
        return await send_msg(event, "💰 أرسل السعر الذي تريده لكل رقم في هذا الملف، مثال: `0.8`:", buttons=kb_admin_cancel())

    if state == 'a_awaiting_zip_spam_mix_price':
        try:
            price = float(text)
            if price <= 0: raise ValueError
        except Exception:
            return await send_msg(event, "سعر غير صالح.", buttons=kb_admin_cancel())
        zip_path = sdata.get('zip_path')
        added, duplicates, failed, errors = await process_uploaded_sessions_zip(zip_path, custom_price=price, is_spam_mix=True)
        clear_user_state(uid)
        return await send_msg(event, f"✅ تم استيراد {SPAM_MIX_LABEL}: `{added}`\n🟡 المكرر: `{duplicates}`\n🔴 الفاشل: `{failed}`\n💰 السعر: `{price}$`", buttons=kb_admin_accounts())

    if state == 'a_awaiting_zip_old_spam_price':
        try:
            price = float(text)
            if price <= 0: raise ValueError
        except Exception:
            return await send_msg(event, "سعر غير صالح.", buttons=kb_admin_cancel())
        zip_path = sdata.get('zip_path')
        added, duplicates, failed, errors = await process_uploaded_sessions_zip(zip_path, custom_price=price, is_old_spam=True)
        clear_user_state(uid)
        return await send_msg(event, f"✅ تم استيراد {OLD_SPAM_LABEL}: `{added}`\n🟡 المكرر: `{duplicates}`\n🔴 الفاشل: `{failed}`\n💰 السعر: `{price}$`", buttons=kb_admin_accounts())

    if state == 'a_awaiting_zip_old_price':
        clean_price_text = "".join(c for c in text if c.isdigit() or c == '.')
        try:
            price = float(clean_price_text)
            if price <= 0: raise ValueError
        except Exception:
            return await send_msg(event, "يرجى إرسال سعر صحيح (مثال: 0.8):", buttons=kb_admin_cancel())
        zip_path = sdata.get('zip_path')
        if not zip_path or not os.path.exists(zip_path):
            clear_user_state(uid)
            return await send_msg(event, "الملف غير موجود، حاول مجدداً.", buttons=kb_admin_accounts())
        await send_msg(event, f"جاري إضافة الأرقام القديمة بسعر `{price}$` لكل رقم...")
        added, duplicates, failed, errors = await process_uploaded_sessions_zip(
            zip_path, merge_as_mixed=False, custom_price=price, is_old=True, old_year=sdata.get('old_year'))
        clear_user_state(uid)
        report = (
            "✅ *تمت إضافة الأرقام القديمة بنجاح!*\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🟢 الأرقام المُضافة: `{added}`\n"
            f"🟡 المكررة (تخطي): `{duplicates}`\n"
            f"🔴 الفاشلة: `{failed}`\n"
            f"💰 السعر المطبق: `{price}$` لكل رقم\n\n"
        )
        if errors:
            report += "📋 *الأخطاء (أول 10):*\n" + "\n".join(f"  • {e}" for e in errors[:10])
        else:
            report += "✅ *جميع الأرقام تمت معالجتها بنجاح!*"
        return await send_msg(event, report, buttons=[[Button.inline("رجوع للوحة", b"a:panel")]])

    if state == 'a_awaiting_zip_monthly_price':
        clean_price_text = "".join(c for c in text if c.isdigit() or c == '.')
        try:
            price = float(clean_price_text)
            if price <= 0: raise ValueError
        except Exception:
            return await send_msg(event, "يرجى إرسال سعر صحيح (مثال: 5):", buttons=kb_admin_cancel())
        zip_path = sdata.get('zip_path')
        if not zip_path or not os.path.exists(zip_path):
            clear_user_state(uid)
            return await send_msg(event, "الملف غير موجود، حاول مجدداً.", buttons=kb_admin_accounts())
        await send_msg(event, f"جاري إضافة أرقام مميزة شهر بسعر `{price}$` لكل رقم...")
        added, duplicates, failed, errors = await process_uploaded_sessions_zip(zip_path, custom_price=price, is_monthly=True)
        clear_user_state(uid)
        report = ("✅ *تمت إضافة أرقام مميزة شهر بنجاح!*\n━━━━━━━━━━━━━━━━━━━━\n\n"
                   f"🟢 الأرقام المُضافة: `{added}`\n🟡 المكررة: `{duplicates}`\n🔴 الفاشلة: `{failed}`\n💰 السعر: `{price}$` لكل رقم\n\n")
        if errors: report += "📋 *الأخطاء (أول 10):*\n" + "\n".join(f"  • {e}" for e in errors[:10])
        else: report += "✅ *جميع الأرقام تمت معالجتها بنجاح!*"
        return await send_msg(event, report, buttons=[[Button.inline("رجوع للوحة", b"a:panel")]])

    if state == 'a_awaiting_zip_daily_price':
        clean_price_text = "".join(c for c in text if c.isdigit() or c == '.')
        try:
            price = float(clean_price_text)
            if price <= 0: raise ValueError
        except Exception:
            return await send_msg(event, "يرجى إرسال سعر صحيح (مثال: 1.5):", buttons=kb_admin_cancel())
        zip_path = sdata.get('zip_path')
        if not zip_path or not os.path.exists(zip_path):
            clear_user_state(uid)
            return await send_msg(event, "الملف غير موجود، حاول مجددًا.", buttons=kb_admin_accounts())
        added, duplicates, failed, errors = await process_uploaded_sessions_zip(zip_path, custom_price=price, is_daily_special=True)
        clear_user_state(uid)
        report = (f"✅ *تمت إضافة {DAILY_NUMBERS_LABEL} بنجاح!*\n🟢 المضافة: `{added}`\n🟡 المكررة: `{duplicates}`\n🔴 الفاشلة: `{failed}`")
        if errors: report += "\n📋 *الأخطاء:*\n" + "\n".join(f"• {e}" for e in errors[:10])
        return await send_msg(event, report, buttons=[[Button.inline("رجوع للوحة", b"a:panel")]])

    if state == 'a_awaiting_zip_random_price':
        clean_price_text = "".join(c for c in text if c.isdigit() or c == '.')
        try:
            price = float(clean_price_text)
            if price <= 0: raise ValueError
        except Exception:
            return await send_msg(event, "يرجى إرسال سعر صحيح (مثال: 2):", buttons=kb_admin_cancel())
        zip_path = sdata.get('zip_path')
        if not zip_path or not os.path.exists(zip_path):
            clear_user_state(uid)
            return await send_msg(event, "الملف غير موجود، حاول مجددًا.", buttons=kb_admin_accounts())
        added, duplicates, failed, errors = await process_uploaded_sessions_zip(zip_path, custom_price=price, is_random_special=True)
        clear_user_state(uid)
        report = (f"✅ *تمت إضافة {RANDOM_NUMBERS_LABEL} بنجاح!*\n🟢 المضافة: `{added}`\n🟡 المكررة: `{duplicates}`\n🔴 الفاشلة: `{failed}`")
        if errors: report += "\n📋 *الأخطاء:*\n" + "\n".join(f"• {e}" for e in errors[:10])
        return await send_msg(event, report, buttons=[[Button.inline("رجوع للوحة", b"a:panel")]])

    if state == 'a_awaiting_zip_bimonthly_price':
        clean_price_text = "".join(c for c in text if c.isdigit() or c == '.')
        try:
            price = float(clean_price_text)
            if price <= 0: raise ValueError
        except Exception:
            return await send_msg(event, "يرجى إرسال سعر صحيح (مثال: 2):", buttons=kb_admin_cancel())
        zip_path = sdata.get('zip_path')
        if not zip_path or not os.path.exists(zip_path):
            clear_user_state(uid)
            return await send_msg(event, "الملف غير موجود، حاول مجددًا.", buttons=kb_admin_accounts())
        await send_msg(event, f"جاري إضافة {BIMONTHLY_NUMBERS_LABEL} بسعر `{price}$` لكل رقم...")
        added, duplicates, failed, errors = await process_uploaded_sessions_zip(zip_path, custom_price=price, is_bimonthly=True)
        clear_user_state(uid)
        report = (f"✅ *تمت إضافة {BIMONTHLY_NUMBERS_LABEL} بنجاح!*\n━━━━━━━━━━━━━━━━━━━━\n\n"
                  f"🟢 المضافة: `{added}`\n🟡 المكررة: `{duplicates}`\n🔴 الفاشلة: `{failed}`\n💰 السعر: `{price}$` لكل رقم\n")
        if errors: report += "\n📋 *الأخطاء:*\n" + "\n".join(f"• {e}" for e in errors[:10])
        return await send_msg(event, report, buttons=[[Button.inline("رجوع للوحة", b"a:panel")]])

    if state == 'a_awaiting_zip_spam_price':
        clean_price_text = "".join(c for c in text if c.isdigit() or c == '.')
        try:
            price = float(clean_price_text)
            if price <= 0: raise ValueError
        except Exception:
            return await send_msg(event, "يرجى إرسال سعر صحيح (مثال: 0.4):", buttons=kb_admin_cancel())
        zip_path = sdata.get('zip_path')
        if not zip_path or not os.path.exists(zip_path):
            clear_user_state(uid)
            return await send_msg(event, "الملف غير موجود، حاول مجدداً.", buttons=kb_admin_accounts())
        await send_msg(event, f"جاري إضافة ملف السبام بسعر `{price}$` لكل رقم...")
        added, duplicates, failed, errors = await process_uploaded_sessions_zip(
            zip_path, merge_as_mixed=True, custom_price=price)
        clear_user_state(uid)
        report = (
            "✅ *تمت إضافة أرقام السبام بنجاح!*\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🟢 الأرقام المُضافة: `{added}`\n"
            f"🟡 المكررة (تخطي): `{duplicates}`\n"
            f"🔴 الفاشلة: `{failed}`\n"
            f"💰 السعر المطبق: `{price}$` لكل رقم\n\n"
        )
        if errors:
            report += "📋 *الأخطاء (أول 10):*\n" + "\n".join(f"  • {e}" for e in errors[:10])
        else:
            report += "✅ *جميع الأرقام تمت معالجتها بنجاح!*"
        return await send_msg(event, report, buttons=[[Button.inline("رجوع للوحة", b"a:panel")]])

    if state == 'a_awaiting_zip_separate_price':
        clean_price_text = "".join(c for c in text if c.isdigit() or c == '.')
        try:
            price = float(clean_price_text)
            if price <= 0: raise ValueError
        except Exception:
            return await send_msg(event, "يرجى إرسال سعر صحيح (مثال: 1.20):", buttons=kb_admin_cancel())
        zip_path = sdata.get('zip_path')
        if not zip_path or not os.path.exists(zip_path):
            clear_user_state(uid)
            return await send_msg(event, "الملف غير موجود، حاول مجدداً.", buttons=kb_admin_accounts())
        await send_msg(event, f"جاري حفظ كل رقم تحت دولته بسعر `{price}$`...")
        added, duplicates, failed, errors = await process_uploaded_sessions_zip(
            zip_path, merge_as_mixed=False, custom_price=price)
        clear_user_state(uid)
        report = (
            "✅ *تم حفظ الأرقام حسب الدول بنجاح!*\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🟢 الأرقام المُضافة: `{added}`\n"
            f"🟡 المكررة (تخطي): `{duplicates}`\n"
            f"🔴 الفاشلة: `{failed}`\n"
            f"💰 السعر المطبق: `{price}$` لكل رقم\n\n"
        )
        if errors:
            report += "📋 *الأخطاء (أول 10):*\n" + "\n".join(f"  • {e}" for e in errors[:10])
        else:
            report += "✅ *جميع الأرقام تمت معالجتها بنجاح!*"
        return await send_msg(event, report, buttons=[[Button.inline("رجوع للوحة", b"a:panel")]])

    if state == 'awaiting_zip_price':
        # تنظيف النص من أي رموز غير الأرقام والنقطة
        clean_price_text = "".join(c for c in text if c.isdigit() or c == '.')
        try:
            price = float(clean_price_text)
            if price <= 0: raise ValueError
        except Exception:
            return await send_msg(event, "يرجى إرسال سعر صحيح (مثال: 1.20):")
        
        zip_path = sdata.get('zip_path')
        if not zip_path or not os.path.exists(zip_path):
            clear_user_state(uid)
            return await send_msg(event, "الملف غير موجود، حاول مجدداً.", buttons=kb_admin_accounts())
        
        set_user_state(uid, 'awaiting_zip_button_name', zip_path=zip_path, price=price)
        return await send_msg(event,
            "🏷️ *إرسال اسم الزر*\n\n"
            "أرسل الآن اسم الزر الذي سيظهر للمستخدمين لهذه الجلسات:",
            buttons=kb_admin_cancel())

    if state == 'awaiting_zip_button_name':
        button_name = text.strip()
        if not button_name or len(button_name) > 60:
            return await send_msg(event, "اسم الزر غير صالح. أرسله بين 1 و60 حرفاً:", buttons=kb_admin_cancel())
        zip_path = sdata.get('zip_path')
        price = sdata.get('price')
        if not zip_path or not os.path.exists(zip_path):
            clear_user_state(uid)
            return await send_msg(event, "الملف غير موجود، حاول مجدداً.", buttons=kb_admin_accounts())
        await send_msg(event, f"جاري معالجة الملف في زر `{button_name}` بسعر `{price}$` لكل رقم...")
        added, duplicates, failed, errors = await process_uploaded_sessions_zip(
            zip_path, merge_as_mixed=False, custom_price=price, custom_label=button_name)
        clear_user_state(uid)
        report = (
            "✅ *تمت عملية الاستيراد بنجاح!*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🟢 الأرقام المُضافة (عادية): `{added}`\n"
            f"🟡 المكررة (تخطي): `{duplicates}`\n"
            f"🔴 الفاشلة: `{failed}`\n"
            f"💰 السعر المطبق: `{price}$` لكل رقم\n"
            f"🏷️ اسم الزر: `{button_name}`\n\n"
        )
        if errors:
            report += "📋 *الأخطاء (أول 10):*\n" + "\n".join(f"  • {e}" for e in errors[:10])
        else:
            report += "✅ *جميع الأرقام تمت معالجتها بنجاح!*"
        await send_msg(event, report, buttons=[[Button.inline("رجوع للوحة", b"a:panel")]])
        return

    if state == 'a_set_clean_name':
        db['settings']['clean_name'] = text.strip()
        save_db(db)
        clear_user_state(uid)
        return await send_msg(event, f"✅ تم تحديث اسم التنظيف إلى: `{text.strip()}`", buttons=kb_admin_accounts())

    if state == 'a_set_clean_bio':
        db['settings']['clean_bio'] = text.strip()
        save_db(db)
        clear_user_state(uid)
        return await send_msg(event, f"✅ تم تحديث نبذة التنظيف إلى: `{text.strip()}`", buttons=kb_admin_accounts())

    if state == 'a_add_phone':
        phone = text.strip().lstrip('+')
        if not phone.isdigit():
            return await send_msg(event, "يرجى إرسال رقم هاتف صالح (أرقام فقط).")
        
        # محاولة معرفة الدولة من الرمز
        code, name = detect_country(phone)
        price = DEFAULT_ACCOUNT_PRICE
        
        if code:
            # إذا كانت الدولة مضافة مسبقاً، نأخذ سعرها واسمها المخصص
            if code in db['countries']:
                name = db['countries'][code]['name']
                price = db['countries'][code]['price']
            else:
                # إذا لم تكن مضافة، نضيفها تلقائياً بالإعدادات الافتراضية
                db['countries'][code] = {
                    'name': name,
                    'price': price
                }
                save_db(db)
        else:
            # إذا لم يتم التعرف على الدولة من القائمة الشاملة
            return await send_msg(event, 
                f"⚠️ لم يتم التعرف على دولة الرقم `+{phone}` تلقائياً.\n\n"
                f"💡 يرجى التأكد من كتابة الرقم بصيغة دولية صحيحة.",
                buttons=kb_admin_accounts())

        # تخزين المعلومات مؤقتاً للسؤال عن نوع الإضافة
        db['pending_spam_choice'] = {
            'type': 'phone',
            'phone': phone,
            'code': code,
            'name': name,
            'price': price,
            'uid': uid
        }
        save_db(db)
        
        # عرض أزرار السؤال
        buttons = [
            [Button.inline("📛 إضافة للمخطلت", b"add:spam")],
            [Button.inline(SPAM_MIX_LABEL, b"add:spam_mix")],
            [Button.inline("🇺🇸 أمريكا السليم — 15 جنيه", b"add:usa")],
            [Button.inline("⚠️ مزيف و احتيالي", b"add:fake")],
            [Button.inline("أرقام مزيف اسبام", b"add:unverified")],
            [Button.inline("أرقام مميزة شهر", b"add:monthly")],
            [Button.inline("أرقام مميزة يوم", b"add:daily")],
            [Button.inline(BIMONTHLY_NUMBERS_BUTTON_LABEL, b"add:bimonthly")],
            [Button.inline("أرقام مميزة عشوائي", b"add:random")],
            [Button.inline(f"{old_numbers_label(uid)} — 1$", b"add:old")],
            [Button.inline(f"{OLD_SPAM_LABEL} — {OLD_SPAM_PRICE}$", b"add:old_spam")],
            [Button.inline("🧷 إضافة إلى زر أختاره", b"add:custom")],
            [Button.inline("لا، دولة عادية", b"add:normal")],
            [Button.inline("إلغاء", b"a_cancel")]
        ]
        await send_msg(event,
            f"📥 *تم استلام الرقم:* `+{phone}`\n"
            f"🌍 الدولة المكتشفة: {name}\n"
            f"💰 السعر المعتمد: `{price}$`\n\n"
            "❓ هل تود إضافة هذا الرقم إلى **زر المخطلت الموحد** ليظهر مع بقية الدول المختلطة؟",
            buttons=buttons
        )
        return

    # ======================================================
    #  حالة إضافة ملف جلسة – مع السؤال عن التصنيف
    # ======================================================
    if state == 'a_add_session_file':
        if not event.message.file:
            return await send_msg(event, "يرجى إرسال ملف جلسة صالح (.session أو .json)", buttons=kb_admin_cancel())
        file_name = event.message.file.name or ''
        file_name = os.path.basename(file_name)
        file_ext = os.path.splitext(file_name)[1].lower()
        if file_ext not in ('.session', '.json'):
            return await send_msg(event, "عذراً، يجب أن يكون الملف بصيغة `.session` أو `.json`", buttons=kb_admin_cancel())
        # تحميل الملف مؤقتاً
        temp_dir = "temp_sessions"
        os.makedirs(temp_dir, exist_ok=True)
        file_path = os.path.join(temp_dir, f"{uid}_{int(time.time())}_{file_name}")
        await event.message.download_media(file=file_path)
        # تخزين معلومات الملف مؤقتاً
        db['pending_spam_choice'] = {
            'type': 'session_file',
            'file_path': file_path,
            'file_name': file_name,
            'uid': uid
        }
        save_db(db)
        # عرض أزرار السؤال
        buttons = [
            [Button.inline("📛 إضافة للمخطلت", b"add:spam")],
            [Button.inline(SPAM_MIX_LABEL, b"add:spam_mix")],
            [Button.inline("🇺🇸 أمريكا السليم — 15 جنيه", b"add:usa")],
            [Button.inline("⚠️ مزيف و احتيالي", b"add:fake")],
            [Button.inline("أرقام مزيف اسبام", b"add:unverified")],
            [Button.inline("أرقام مميزة شهر", b"add:monthly")],
            [Button.inline("أرقام مميزة يوم", b"add:daily")],
            [Button.inline(BIMONTHLY_NUMBERS_BUTTON_LABEL, b"add:bimonthly")],
            [Button.inline("أرقام مميزة عشوائي", b"add:random")],
            [Button.inline(f"{old_numbers_label(uid)} — 1$", b"add:old")],
            [Button.inline(f"{OLD_SPAM_LABEL} — {OLD_SPAM_PRICE}$", b"add:old_spam")],
            [Button.inline("🧷 إضافة إلى زر أختاره", b"add:custom")],
            [Button.inline("لا، دولة عادية", b"add:normal")],
            [Button.inline("إلغاء", b"a_cancel")]
        ]
        await send_msg(event,
            f"📥 *تم استلام ملف الجلسة:* `{file_name}`\n\n"
            "❓ هل تود إضافة هذا الرقم إلى **زر المخطلت الموحد** ليظهر مع بقية الدول المختلطة؟",
            buttons=buttons
        )
        return

    # ======================================================
    #  الحالة القديمة a_add_phone_code تم إزالتها واستبدالها بحالة awaiting_admin_code
    #  لذا نتركها بدون معالجة هنا، لأنها لن تُستخدم
    # ======================================================
    if state == 'a_add_phone_code':
        # تم إلغاء هذه الحالة، نخرج منها
        clear_user_state(uid)
        return await send_msg(event, "تم تغيير آلية الإضافة، يرجى استخدام الزر 'اضافه رقم جديد' من جديد.", buttons=kb_admin_accounts())

    # ======================================================
    #  باقي الحالات الأخرى (بدون تعديل)
    # ======================================================
    if state in ('a_addbal_for', 'a_subbal_for'):
        try:
            amount = float(text)
        except Exception:
            return await send_msg(event, "مبلغ غير صحيح.")
        target_uid = sdata.get('target')
        if not target_uid or target_uid not in db['users']:
            clear_user_state(uid)
            return await send_msg(event, "المستخدم غير موجود.", buttons=kb_admin_main(uid))
        if state == 'a_subbal_for':
            amount = -amount
        update_balance(target_uid, amount)
        new_bal = get_balance(target_uid)
        clear_user_state(uid)
        try:
            emoji = "🔐" if amount > 0 else "⚠️"
            await send_msg(int(target_uid),
                f"{emoji} تم تعديل رصيدك: `{amount:+.2f}$`\n💳 الرصيد الجديد: `{new_bal:.2f}$`"
            )
        except Exception:
            pass
        # تم إزالة إشعار القناة لأنه سري
        return await admin_show_user(event, int(target_uid))

    if state in ('a_addbal', 'a_subbal'):
        parts = text.split()
        if len(parts) < 2:
            return await send_msg(event, "الصيغة: `معرف_المستخدم المبلغ`")
        identifier = parts[0]
        try:
            amount = float(parts[1])
        except Exception:
            return await send_msg(event, "مبلغ غير صحيح.")
        target_uid, _ = await find_user(identifier)
        if not target_uid:
            return await send_msg(event, f"المستخدم `{identifier}` غير موجود.")
        if state == 'a_subbal':
            amount = -amount
        update_balance(target_uid, amount)
        new_bal = get_balance(target_uid)
        clear_user_state(uid)
        try:
            emoji = "🔐" if amount > 0 else "⚠️"
            await send_msg(int(target_uid),
                f"{emoji} تم تعديل رصيدك: `{amount:+.2f}$`\n💳 الرصيد الجديد: `{new_bal:.2f}$`"
            )
        except Exception:
            pass
        return await send_msg(event,
            f"✅ تم تعديل رصيد `{target_uid}` بمقدار `{amount:+.2f}$`\n💳 الرصيد: `{new_bal:.2f}$`",
            buttons=kb_admin_main(uid)
        )

    if state == 'a_manual_tx_amount':
        try:
            amount = float(text)
        except Exception:
            return await send_msg(event, "مبلغ غير صحيح.", buttons=kb_admin_cancel())
        tx_id = sdata['tx_id']
        tx = next((t for t in db['transactions'] if t['id'] == tx_id), None)
        if tx:
            tx['amount_usd'] = amount
            tx['status'] = 'completed'
            if tx.get('txid'):
                mark_txid_used(tx['txid'])
            save_db(db)
            update_balance(tx['user_id'], amount)
            try:
                await send_msg(tx['user_id'],
                    f"🔐 *تمت الموافقة على شحنك* 🔐\n💰 المبلغ: `{amount}$`"
                )
            except Exception:
                pass
        clear_user_state(uid)
        return await send_msg(event, f"تم اعتماد TX#{tx_id} بمبلغ `{amount}$`",
                              buttons=kb_admin_main(uid))

    if state == 'a_ban':
        # حماية: الحظر/فك الحظر متاح للأدمن فقط
        if not is_admin(uid):
            clear_user_state(uid)
            return await send_msg(event, "🚫 *هذا الإجراء للأدمن فقط.*", buttons=kb_admin_main(uid))
        target_uid, target_u = await find_user(text)
        if not target_uid:
            clear_user_state(uid)
            return await send_msg(event, f"`{text}` غير موجود.", buttons=kb_admin_main(uid))
        if target_u.get('banned'):
            db['users'][target_uid]['banned'] = False
            # تنظيف أي حظر مؤقت قديم
            if 'temp_ban_until' in db['users'][target_uid]:
                db['users'][target_uid].pop('temp_ban_until', None)
            act = "فك الحظر عن"
        else:
            db['users'][target_uid]['banned'] = True
            act = "حظر"
        save_db(db)
        update_user_cache(target_uid)
        clear_user_state(uid)
        return await send_msg(event, f"تم {act} `{target_uid}`", buttons=kb_admin_main(uid))

    if state == 'a_unban_all':
        # تأكيد رفع حظر الجميع
        count = 0
        for u_id, u_data in db['users'].items():
            if u_data.get('banned') or u_data.get('temp_ban_until'):
                u_data['banned'] = False
                u_data.pop('temp_ban_until', None)
                count += 1
        save_db(db)
        # تحديث الكاش بالكامل
        for u_id in db['users']:
            update_user_cache(u_id)
        clear_user_state(uid)
        return await send_msg(event,
            f"✅ *تم رفع الحظر عن {count} مستخدم.*\n\n"
            f"🔓 جميع المستخدمين المحرومين تم فك حظرهم.",
            buttons=kb_admin_main(uid)
        )

    if state == 'a_broadcast':
        msg = await send_msg(event, "🚀 جاري البدء في الإذاعة فائقة السرعة...")
        sent = failed = 0
        counters_lock = asyncio.Lock()

        active_users = [int(u_id) for u_id in list(db['users'].keys()) if not db['users'][u_id].get('banned')]
        total = len(active_users)

        original_entities = event.message.entities or []
        custom_emoji_entities = [e for e in original_entities if isinstance(e, MessageEntityCustomEmoji)]
        original_text = event.message.message or ''

        # عدد منخفض ومستقر يمنع FloodWait المتتابع الذي كان يجمّد الإذاعة.
        sem = asyncio.Semaphore(10)

        async def deliver(user_id):
            if custom_emoji_entities:
                return await bot.send_message(
                    user_id, original_text,
                    formatting_entities=original_entities, silent=True
                )
            return await bot.send_message(user_id, text, parse_mode='md', silent=True)

        async def send_task(user_id):
            nonlocal sent, failed
            async with sem:
                ok = False
                for attempt in range(2):
                    try:
                        await asyncio.wait_for(deliver(user_id), timeout=45)
                        ok = True
                        break
                    except FloodWaitError as e:
                        # لا تنتظر ساعات داخل مهمة الإذاعة؛ سجّل المستخدم كفاشل
                        # وأكمل بقية القائمة بدلاً من توقف الإذاعة كلها.
                        wait_seconds = int(getattr(e, 'seconds', 0) or 0)
                        if attempt == 0 and 0 < wait_seconds <= 15:
                            await asyncio.sleep(wait_seconds + 1)
                        else:
                            break
                    except (asyncio.TimeoutError, ConnectionError, RPCError):
                        if attempt == 0:
                            await asyncio.sleep(1)
                        else:
                            break
                    except Exception:
                        break
                async with counters_lock:
                    if ok:
                        sent += 1
                    else:
                        failed += 1

        # دفعات صغيرة: الإذاعة لا تتوقف بسبب مستخدم واحد أو استثناء واحد.
        batch_size = 50
        for i in range(0, total, batch_size):
            batch = active_users[i:i + batch_size]
            await asyncio.gather(*(send_task(u_id) for u_id in batch), return_exceptions=True)
            try:
                await safe_edit(msg,
                    f"⚡ جاري الإذاعة...\n━━━━━━━━━━━━━━━━━━━━\n"
                    f"📊 تقدم: `{sent}` نجح / `{failed}` فشل / `{total}` إجمالي")
            except Exception:
                pass

        clear_user_state(uid)
        return await safe_edit(msg,
            f"📢 *تمت الإذاعة بنجاح باهر*\n\n✅ نجح: `{sent}`\n❌ فشل: `{failed}`\n📊 إجمالي: `{total}`\n⚡ تم استخدام تقنية الإرسال المتوازي.",
            buttons=kb_admin_main(uid)
        )

    if state == 'a_mp_name':
        set_user_state(uid, 'a_mp_desc', name=text)
        return await send_msg(event,
            "📝 أرسل وصف طريقة الدفع (يدعم Markdown):\n\n"
            "💡 مثال: `الحساب: 1234567890\\nالبنك: XYZ`",
            buttons=kb_admin_cancel()
        )
    if state == 'a_mp_desc':
        name = sdata['name']
        db['manual_payments'] = [m for m in db['manual_payments'] if m['name'] != name]
        db['manual_payments'].append({'name': name, 'description': text,
                                       'created_at': datetime.now().isoformat()})
        save_db(db)
        clear_user_state(uid)
        return await send_msg(event, f"*تم إضافة* `{name}`", buttons=kb_admin_manual())

    if state == 'a_mp_confirm_amount':
        try:
            confirmed_egp = float(text)
        except Exception:
            return await send_msg(event, "مبلغ غير صحيح. أرسل رقم فقط.", buttons=kb_admin_cancel())
        if confirmed_egp <= 0:
            return await send_msg(event, "المبلغ يجب أن يكون أكبر من صفر.", buttons=kb_admin_cancel())
        req_id = sdata.get('req_id')
        req_type = sdata.get('req_type', 'manual')
        req = next((r for r in db['manual_requests'] if r['id'] == req_id), None)
        if not req or req['status'] != 'pending':
            clear_user_state(uid)
            return await send_msg(event, "الطلب غير موجود أو تم التعامل معه.", buttons=kb_admin_main(uid))
        # إذا كان نوع الطلب فودافون كاش، المبلغ المدخل بالجنية المصري
        if req_type == 'vodafone':
            max_egp = MAX_DEPOSIT * VOFACASH_RATE_EGP_PER_USD
            if confirmed_egp > max_egp:
                return await send_msg(event, f"المبلغ يتجاوز الحد الأقصى ({int(max_egp)} جنية = {MAX_DEPOSIT}$).", buttons=kb_admin_cancel())
            confirmed_amount = round(confirmed_egp / VOFACASH_RATE_EGP_PER_USD, 2)
            confirmed_egp_amount = confirmed_egp
        else:
            confirmed_amount = confirmed_egp
            if confirmed_amount > MAX_DEPOSIT:
                return await send_msg(event, f"المبلغ يتجاوز الحد الأقصى ({MAX_DEPOSIT}$).", buttons=kb_admin_cancel())
        requested_amount = req['amount']
        method_name = req['method']
        user_id = req['user_id']
        req['status'] = 'approved'
        req['confirmed_amount'] = confirmed_amount
        if req_type == 'vodafone':
            req['confirmed_egp'] = confirmed_egp
        update_balance(user_id, confirmed_amount)
        save_db(db)
        clear_user_state(uid)
        try:
            if req_type == 'binance':
                await send_msg(user_id,
                    f"🔐 *تمت الموافقة على شحن Binance الخاص بك* 🔐\n\n"
                    f"💳 الطريقة: *Binance*\n"
                    f"💰 المبلغ الذي طلبته: `{requested_amount}$`\n"
                    f"💰 المبلغ الفعلي في الصورة: `{confirmed_amount}$`\n\n"
                    f"⚠️ *تمت الموافقة على مبلغ* `{confirmed_amount}$` *لأنه المبلغ الفعلي المرئي في صورة التحويل.*\n\n"
                    f"💵 رصيدك الحالي: `{get_balance(user_id):.2f}$`"
                )
            elif req_type == 'vodafone':
                await send_msg(user_id,
                    f"✅ تم التأكد من عملية الشحن\n\n"
                    f"المبلغ المضاف: `{confirmed_amount:.2f}$`\n"
                    f"رصيدك الحالي: `{get_balance(user_id):.2f}$`\n"
                    f"💲 شكراً لاستخدامك البوت!"
                )
            else:
                await send_msg(user_id,
                    f"✅ تم التأكد من عملية الشحن\n\n"
                    f"المبلغ المضاف: `{confirmed_amount:.2f}$`\n"
                    f"رصيدك الحالي: `{get_balance(user_id):.2f}$`\n"
                    f"💲 شكراً لاستخدامك البوت!"
                )
        except Exception:
            pass
        if req_type == 'binance':
            await send_msg(event,
                f"✅ *تم اعتماد شحن Binance #{req_id}*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"👤 المستخدم: `{user_id}`\n"
                f"💰 المبلغ المطلوب: `{requested_amount}$`\n"
                f"💰 المبلغ الفعلي: `{confirmed_amount}$`\n"
                f"💵 الرصيد الحالي: `{get_balance(user_id):.2f}$`",
                buttons=kb_admin_back()
            )
        elif req_type == 'vodafone':
            await send_msg(event,
                f"✅ *تم اعتماد شحن فودافون كاش #{req_id}*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"👤 المستخدم: `{user_id}`\n"
                f"💰 المبلغ بالجنية (الفعلي): `{confirmed_egp:.2f}` جنية\n"
                f"💰 المبلغ بالدولار: `{confirmed_amount:.2f}$`\n"
                f"💵 الرصيد الحالي: `{get_balance(user_id):.2f}$`",
                buttons=kb_admin_back()
            )
        else:
            await send_msg(event,
                f"✅ *تم اعتماد #{req_id}*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"👤 المستخدم: `{user_id}`\n"
                f"💳 الطريقة: *{method_name}*\n"
                f"💰 المبلغ المطلوب: `{requested_amount}$`\n"
                f"💰 المبلغ الفعلي: `{confirmed_amount}$`\n"
                f"💵 الرصيد الحالي: `{get_balance(user_id):.2f}$`",
                buttons=kb_admin_back()
            )

    if state == 'a_wallet_set':
        cur = sdata['currency']
        new_addr = text.strip()
        WALLETS[cur] = new_addr
        db['settings'].setdefault('wallets_override', {})[cur] = new_addr
        save_db(db)
        clear_user_state(uid)
        return await send_msg(event,
            f"✅ تم تحديث محفظة *{cur}*:\n`{new_addr}`",
            buttons=kb_admin_main(uid)
        )

    if state == 'a_welcome':
        db['settings']['welcome_text'] = text
        save_db(db)
        clear_user_state(uid)
        return await send_msg(event, "*تم تحديث الترحيب.*", buttons=kb_admin_main(uid))

    if state == 'a_referral_lookup':
        clear_user_state(uid)
        return await send_msg(event, "هذا الخيار غير متاح.", buttons=kb_admin_main(uid))

    if False and state == 'a_referral_lookup':
        target_uid, _ = await find_user(text)
        if not target_uid:
            clear_user_state(uid)
            return await send_msg(event, f"❌ المستخدم `{text}` غير موجود.", buttons=kb_admin_main(uid))

        target_uid = int(target_uid)
        target_user = db.get('users', {}).get(str(target_uid), {})
        total, active, points = _referral_stats(target_uid)
        username = target_user.get('username') or 'لا يوجد'
        display_name = target_user.get('full_name') or 'غير مسجل'
        clear_user_state(uid)
        return await send_msg(
            event,
            "📊 *إحصائيات الإحالات*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 الاسم: `{display_name}`\n"
            f"🔗 username: `@{username.lstrip('@') if username != 'لا يوجد' else 'لا يوجد'}`\n"
            f"🆔 User ID: `{target_uid}`\n\n"
            f"👥 إجمالي الإحالات: `{total}`\n"
            f"🟢 الإحالات النشطة: `{active}`\n"
            f"💰 نقاط الإحالة: `{points:.4f}$`",
            buttons=kb_admin_main(uid)
        )

    return False

# ================================
#  وظيفة التنشيط التلقائي للجلسات (Keep-Alive)
# ================================
# فحص وتجديد مخزون الجلسات مرة كل 10 ساعات من وقت آخر فحص.
KEEP_ALIVE_ENABLED = True
SESSION_HEALTH_CHECK_INTERVAL = 10 * 60 * 60
# الفحص لا يغيّر حالة الرقم تلقائيًا؛ يمنع عزل الأرقام بسبب عطل مؤقت.
AUTO_INVALIDATE_SESSIONS = False
SESSION_CHECK_RETRIES = 3

async def keep_alive_sessions_task():
    """
    فحص دوري لصحة جلسات الأرقام المتاحة. الاتصال هنا لا ينشئ جلسة جديدة
    ولا يرسل كودًا؛ فقط يتأكد أن الجلسة ما زالت مصرحًا بها وقابلة للبيع.
    كل رقم يُفحص بعد مرور 24 ساعة من إضافته، ثم كل 24 ساعة لاحقًا.
    """
    initial_delay = 60
    logger.info("⏳ سيتم بدء فحص صحة الجلسات بعد دقيقة واحدة...")
    await asyncio.sleep(initial_delay)

    while True:
        try:
            now = time.time()
            accounts = [a for a in db.get('accounts', []) if a.get('session')]
            logger.info(f"🔄 فحص محافظ لصحة {len(accounts)} جلسة...")
            for acc in accounts:
                session_str = acc.get('session')
                phone = acc.get('phone')
                last_check = float(acc.get('last_session_health_check', 0) or 0)
                if last_check and now - last_check < SESSION_HEALTH_CHECK_INTERVAL:
                    continue

                result = 'unknown'
                check_error = None
                latest_session = session_str
                verified_me = None
                for attempt in range(SESSION_CHECK_RETRIES):
                    client = None
                    try:
                        client = TelegramClient(
                            StringSession(session_str), API_ID, API_HASH,
                            connection=ConnectionTcpIntermediate,
                            device_model="iPhone 14 Pro", system_version="iOS 17.0",
                            app_version="10.0", connection_retries=3,
                            request_retries=2, retry_delay=10,
                            auto_reconnect=False, flood_sleep_threshold=60
                        )
                        await client.connect()
                        if not await client.is_user_authorized():
                            result, check_error = 'suspected_invalid', "الجلسة غير مصرح بها"
                        else:
                            me = await client.get_me()
                            session_phone = str(getattr(me, 'phone', '') or '').lstrip('+')
                            account_phone = str(phone or '').lstrip('+')
                            if not session_phone:
                                result, check_error = 'suspected_invalid', "لم يتم العثور على رقم داخل الجلسة"
                            elif account_phone and session_phone != account_phone:
                                result, check_error = 'mismatch', "رقم الجلسة لا يطابق الرقم المسجل"
                            else:
                                result, check_error = 'valid', None
                                latest_session = StringSession.save(client.session)
                                verified_me = me
                        if result in ('valid', 'mismatch', 'suspected_invalid'):
                            break
                    except FloodWaitError as e:
                        result, check_error = 'temporary_error', f"FloodWait: {e.seconds} ثانية"
                        logger.warning(f"⚠️ تأجيل فحص {phone} بسبب FloodWait")
                    except AuthKeyUnregisteredError:
                        result, check_error = 'suspected_invalid', "مفتاح الجلسة غير مسجل"
                    except Exception as e:
                        result, check_error = 'temporary_error', str(e)
                        logger.warning(f"⚠️ خطأ مؤقت في فحص {phone} (محاولة {attempt + 1}): {e}")
                    finally:
                        if client:
                            try:
                                await client.disconnect()
                            except Exception:
                                pass
                    if attempt + 1 < SESSION_CHECK_RETRIES:
                        await asyncio.sleep(3)

                # لا نستبدل الجلسة ولا نغيّر status تلقائيًا بسبب الفحص.
                acc['last_session_health_check'] = datetime.now().isoformat()
                acc['session_health_status'] = result
                acc['session_health_error'] = check_error
                if result == 'valid':
                    if latest_session != session_str:
                        archive_session_snapshot(phone, session_str, reason="before_update")
                    acc['session'] = latest_session
                    register_session_identity(acc, latest_session, verified_me, status="valid")
                    save_session_to_disk(phone, latest_session)
                    acc.pop('session_health_warning', None)
                    logger.info(f"✅ الجلسة صالحة: {phone}")
                elif result in ('suspected_invalid', 'mismatch'):
                    # الجلسة غير المصرح بها أو التي لا تطابق الرقم تالفة بشكل
                    # دائم؛ تُزال من المخزون حتى لا تُعرض للبيع مرة أخرى.
                    acc['status'] = 'invalid_session'
                    acc['invalidated_at'] = datetime.now().isoformat()
                    acc['invalidated_reason'] = str(check_error or result)[:300]
                    archive_session_snapshot(phone, session_str, reason="invalid_health_check")
                    if acc in db.get('accounts', []):
                        db['accounts'].remove(acc)
                    try:
                        session_path = os.path.join(
                            SESSIONS_DIR,
                            f"{str(phone or '').replace('+', '').strip()}.session"
                        )
                        if os.path.exists(session_path):
                            os.remove(session_path)
                    except Exception as cleanup_error:
                        logger.warning("تعذر حذف ملف الجلسة التالفة %s: %s", phone, cleanup_error)
                    logger.warning(f"🗑️ تمت إزالة جلسة تالفة من المخزون: {phone} ({check_error})")
                else:
                    logger.warning(f"⚠️ فشل مؤقت؛ تم الحفاظ على الجلسة: {phone} ({check_error})")
                save_db(db)
                await asyncio.sleep(random.randint(10, 25))

            logger.info("✅ انتهى فحص الجلسات؛ أزيلت الجلسات التالفة فقط، وحُفظت أخطاء الاتصال المؤقتة.")
            await asyncio.sleep(15 * 60)
        except Exception as e:
            logger.error(f"خطأ في مهمة فحص الجلسات المحافظ: {e}")
            await asyncio.sleep(15 * 60)

# ================================
#  تشغيل البوت
# ================================
async def main():
    global BOT_LOOP
    BOT_LOOP = asyncio.get_running_loop()
    await load_wallets_override()
    ensure_sessions_on_disk()
    asyncio.create_task(db_saver_task())
    background_tasks_started = False
    print("═" * 60)
    print("  🔰 𝑠𝑙𝑖𝑛𝑒𝑟 𝑁𝑢𝑚𝑏𝑒𝑟𝑠 𝐵𝑜𝑡 — ENHANCED v3.0 ✅")
    print("═" * 60)
    print(f"  المالك: {OWNER_ID}")
    print(f"  العملات المدعومة: {', '.join(WALLETS.keys())}")
    print(f"  قاعدة البيانات: {DB_FILE}")
    print(f"  Custom Emojis: {len(CUSTOM_EMOJIS)} إيموجي مخصص")
    print("═" * 60)
    reconnect_delay = 30
    while True:
        try:
            print("  ⏳ جاري بدء اتصال البوت...")
            await bot.start(bot_token=BOT_TOKEN)
            me = await bot.get_me()
            reconnect_delay = 30
            print(f"  ✅ تم الاتصال بنجاح: @{me.username} • ID: {me.id}")
            if not background_tasks_started:
                asyncio.create_task(referral_monitor_task())
                asyncio.create_task(automatic_backup_task())
                print("  ✅ تم تشغيل النسخ الاحتياطي التلقائي كل 50 دقيقة")
                if KEEP_ALIVE_ENABLED:
                    asyncio.create_task(keep_alive_sessions_task())
                    print("  ✅ تم تشغيل مراقبة الإحالات وفحص صحة الجلسات كل 24 ساعة")
                else:
                    print("  ✅ تم تشغيل مراقبة الإحالات — فحص الجلسات معطّل")
                background_tasks_started = True
            print("═" * 60)
            await bot.run_until_disconnected()
        except Exception as e:
            err_text = str(e)
            if "429" in err_text or "flood" in err_text.lower():
                reconnect_delay = min(max(reconnect_delay * 2, 60), 600)
            else:
                reconnect_delay = min(max(reconnect_delay, 30), 120)

            print(f"  ❌ انقطع الاتصال: {e}")
            print(f"  🔄 جاري إعادة المحاولة خلال {reconnect_delay} ثانية...")
            try:
                await bot.disconnect()
            except Exception:
                pass
            # إضافة عشوائية بسيطة تمنع تزامن إعادة الاتصال مع خوادم Telegram.
            await asyncio.sleep(reconnect_delay + random.randint(0, 15))



# ================================
#  نظام الحالات (الإحالات) التلقائي
# ================================

def solve_math_puzzle(text):
    """محاولة حل مسائل الرياضيات البسيطة في رسائل البوتات"""
    import re
    # أنماط شائعة: 1 + 2، 5 - 3، 4 * 2، 10 / 2
    pattern = r'(\d+)\s*([\+\-\*])\s*(\d+)'
    match = re.search(pattern, text)
    if match:
        try:
            num1 = int(match.group(1))
            op = match.group(2)
            num2 = int(match.group(3))
            if op == '+': return str(num1 + num2)
            if op == '-': return str(num1 - num2)
            if op == '*': return str(num1 * num2)
        except Exception:
            pass
    
    # نمط آخر: كم ناتج 5 زائد 3
    if "زائد" in text or "جمع" in text:
        nums = re.findall(r'\d+', text)
        if len(nums) >= 2: return str(int(nums[0]) + int(nums[1]))
    
    return None

async def referral_single_account(session_str, phone, bot_url):
    """تنفيذ عملية إحالة واحدة لرقم معين"""
    # استخراج اليوزر والبارامتر من الرابط
    try:
        if "start=" in bot_url:
            bot_username = bot_url.split("t.me/")[1].split("?")[0]
            start_param = bot_url.split("start=")[1]
        else:
            bot_username = bot_url.split("t.me/")[1]
            start_param = None
    except Exception:
        return False, "رابط غير صالح"

    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    joined_channels = []
    
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return False, "الجلسة غير صالحة"

        # 1. رفع الحظر عن البوت أولاً إذا كان محظوراً
        try:
            await client(functions.contacts.UnblockRequest(id=bot_username))
        except Exception:
            pass
        
        await asyncio.sleep(2)

        # 2. الخطوة الأولى: بدء البوت برابط الإحالة للحصول على القنوات
        from telethon.tl.functions.messages import StartBotRequest
        try:
            await client(StartBotRequest(
                bot=bot_username,
                peer=bot_username,
                start_param=start_param or ""
            ))
        except Exception:
            try:
                await client.send_message(bot_username, f"/start {start_param}" if start_param else "/start")
            except Exception:
                pass

        await asyncio.sleep(5)

        # 3. الخطوة الثانية: الاشتراك في القنوات (لازم يشترك)
        for _ in range(3):
            messages = await client.get_messages(bot_username, limit=10)
            new_join = False
            
            for msg in messages:
                # فحص الأزرار للروابط
                if msg.reply_markup:
                    for row in msg.reply_markup.rows:
                        for btn in row.buttons:
                            target = None
                            if isinstance(btn, types.KeyboardButtonUrl):
                                if "t.me/" in btn.url:
                                    target = btn.url.split("t.me/")[1].split("?")[0]
                            
                            if target and target.lower() != bot_username.lower() and target not in joined_channels:
                                try:
                                    await client(functions.channels.JoinChannelRequest(channel=target))
                                    joined_channels.append(target)
                                    new_join = True
                                    await asyncio.sleep(5)
                                except Exception:
                                    pass
                
                # فحص الروابط في النص
                links = re.findall(r't\.me/([\w\d_]+)', msg.text or "")
                for link in links:
                    if link.lower() != bot_username.lower() and link not in joined_channels:
                        try:
                            await client(functions.channels.JoinChannelRequest(channel=link))
                            joined_channels.append(link)
                            new_join = True
                            await asyncio.sleep(5)
                        except Exception:
                            pass

                # حل المسائل الرياضية إن وجدت
                math_result = solve_math_puzzle(msg.text or "")
                if math_result:
                    await client.send_message(bot_username, math_result)
                    await asyncio.sleep(5)
                    new_join = True

            if not new_join:
                break
            await asyncio.sleep(5)

        # 4. الخطوة الثالثة: بعد ما يشترك يضغط استرت (تفعيل الإحالة)
        try:
            # إعادة إرسال أمر البدء مع البارامتر لضمان التفعيل
            from telethon.tl.functions.messages import StartBotRequest
            await client(StartBotRequest(
                bot=bot_username,
                peer=bot_username,
                start_param=start_param or ""
            ))
            await asyncio.sleep(5)
            
            # محاولة الضغط على كافة أزرار التحقق الممكنة
            messages = await client.get_messages(bot_username, limit=10)
            for msg in messages:
                if msg.reply_markup:
                    for row in msg.reply_markup.rows:
                        for btn in row.buttons:
                            btn_text = getattr(btn, 'text', '')
                            # فحص شامل للكلمات التي قد تدل على زر التحقق
                            check_words = ["تحقق", "تأكيد", "انضممت", "Done", "Check", "Verify", "استمرار", "Start", "ابدأ", "✅", "التالي", "Next"]
                            if any(word.lower() in btn_text.lower() for word in check_words):
                                try:
                                    if isinstance(btn, types.KeyboardButtonCallback):
                                        await msg.click(data=btn.data)
                                    else:
                                        await msg.click()
                                    await asyncio.sleep(5)
                                except Exception:
                                    pass
        except Exception:
            pass

        # 5. الخطوة الرابعة: الانتظار لضمان استقرار الإحالة
        await asyncio.sleep(15)

        # تم إزالة منطق المغادرة والحظر بناءً على طلب المستخدم لضمان احتساب الإحالة
        
        return True, "تمت تفعيل الإحالة بنجاح وبقاء الحساب في القنوات"

    except Exception as e:
        return False, str(e)
    finally:
        await client.disconnect()

async def perform_referral_all_accounts(event, bot_url):
    """تنفيذ عملية الحالات لجميع الأرقام المتاحة"""
    accounts = [acc for acc in db.get('accounts', []) if acc.get('status') == 'available']
    if not accounts:
        return await event.respond("❌ لا توجد أرقام متاحة للقيام بالحالات.")
    
    status_msg = await event.respond(f"⏳ جاري بدء عملية الحالات لـ {len(accounts)} رقم...\n🔗 الرابط: {bot_url}\n\nيرجى الانتظار، هذه العملية قد تستغرق وقتاً.")
    
    success = 0
    failed = 0
    
    sem = asyncio.Semaphore(5) # تنفيذ 5 حالات بالتوازي (أكثر أماناً للحسابات)
    
    async def referral_task(acc):
        nonlocal success, failed
        phone = acc.get('phone')
        session_str = acc.get('session')
        if not session_str:
            failed += 1
            return
            
        async with sem:
            try:
                ok, res = await referral_single_account(session_str, phone, bot_url)
                if ok:
                    success += 1
                else:
                    failed += 1
                    logger.warning(f"Failed referral for {phone}: {res}")
            except Exception as e:
                failed += 1
                logger.error(f"Critical error in referral for {phone}: {e}")
            
            # احترام رغبة المستخدم في وجود تأخير ولكن بشكل متوازي
            await asyncio.sleep(8)

    # تقسيم العمل إلى دفعات لتحديث الحالة
    batch_size = 5
    for i in range(0, len(accounts), batch_size):
        batch = accounts[i:i + batch_size]
        tasks = [referral_task(acc) for acc in batch]
        await asyncio.gather(*tasks)
        
        try:
            await status_msg.edit(f"⚡ جاري تنفيذ الحالات بالتوازي... ({min(i+batch_size, len(accounts))}/{len(accounts)})\n✅ ناجح: {success}\n❌ فشل: {failed}")
        except: pass
    
    report = (
        f"✅ *اكتملت عملية الحالات بالأرقام*\n\n"
        f"🔗 الرابط المستخدم: {bot_url}\n"
        f"📱 إجمالي الأرقام: `{len(accounts)}`\n"
        f"✨ نجاح الإحالة: `{success}`\n"
        f"⚠️ فشل الإحالة: `{failed}`\n\n"
        f"💡 تم تفعيل الحالات وبقاء الحسابات في القنوات لضمان احتساب الإحالة."
    )
    
    await status_msg.edit(report, buttons=[[Button.inline("رجوع للوحة", b"a:panel")]])



# ================================
#  خادم صحة Railway
# ================================
class _RailwayHealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"OK"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/webhooks/vodafone-sms":
            self.send_response(404); self.end_headers(); return
        expected_token = VODAFONE_SMS_WEBHOOK_TOKEN
        supplied_token = self.headers.get("X-Webhook-Token", "").strip()
        if not expected_token:
            self.send_response(503); self.end_headers(); return
        if not supplied_token or not hmac.compare_digest(supplied_token, expected_token):
            self.send_response(401); self.end_headers(); return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 65536:
                self.send_response(413 if length > 65536 else 400); self.end_headers(); return
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            content_type = self.headers.get("Content-Type", "").lower()
            if "application/json" in content_type:
                payload = json.loads(raw)
            elif "application/x-www-form-urlencoded" in content_type:
                payload = {k: v[-1] for k, v in urllib.parse.parse_qs(raw, keep_blank_values=True).items()}
            else:
                payload = {"message": raw}
            if not BOT_LOOP or BOT_LOOP.is_closed():
                self.send_response(503); self.end_headers(); return
            future = asyncio.run_coroutine_threadsafe(handle_vodafone_webhook(payload), BOT_LOOP)
            processed = bool(future.result(timeout=20))
            self.send_response(200 if processed else 202)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(b'{"ok":true,"credited":true}' if processed else b'{"ok":true,"credited":false,"reason":"unmatched_or_unrecognized"}')
        except Exception:
            logger.exception("Vodafone SMS webhook failed")
            self.send_response(400); self.end_headers()

    def log_message(self, format, *args):
        return


def start_railway_health_server():
    """يستمع على PORT حتى تبقى خدمة Railway صحية، دون تعطيل بوت Telegram."""
    port_raw = os.getenv("PORT", "8002")
    try:
        port = int(port_raw)
        if not (1 <= port <= 65535):
            raise ValueError
        server = HTTPServer(("0.0.0.0", port), _RailwayHealthHandler)
        thread = threading.Thread(target=server.serve_forever, name="railway-health", daemon=True)
        thread.start()
        logger.info(f"✅ خادم صحة Railway يعمل على 0.0.0.0:{port}")
        return server
    except Exception as exc:
        # لا نمنع تشغيل البوت إذا كانت المنصة لا تتطلب PORT أو المنفذ مشغول.
        logger.warning(f"⚠️ تعذر تشغيل خادم صحة Railway على PORT={port_raw}: {exc}")
        return None


# ================================
#  مشرف التشغيل المستمر
# ================================
def run_forever():
    """يبقي العملية حية ويعيد تشغيل حلقة asyncio بعد أي توقف غير متوقع."""
    global _instance_lock_handle
    start_railway_health_server()
    try:
        acquire_single_instance_lock()
    except RuntimeError as exc:
        logger.error(f"❌ {exc}")
        return

    restart_delay = 15
    try:
        while True:
            try:
                logger.info("🤖 جاري تشغيل بوت MOSCOW NUMBERS...")
                asyncio.run(main())
                logger.warning(f"⚠️ انتهت main دون استثناء؛ إعادة التشغيل بعد {restart_delay} ثانية...")
            except (KeyboardInterrupt, SystemExit):
                logger.info("🛑 تم إيقاف البوت يدويًا.")
                return
            except Exception:
                logger.exception("❌ توقف غير متوقع؛ سيُعاد تشغيل البوت تلقائيًا.")
            time.sleep(restart_delay)
            restart_delay = min(restart_delay * 2, 300)
    finally:
        if _instance_lock_handle:
            try:
                fcntl.flock(_instance_lock_handle.fileno(), fcntl.LOCK_UN)
                _instance_lock_handle.close()
            except Exception:
                pass
            _instance_lock_handle = None

if __name__ == '__main__':
    run_forever()
