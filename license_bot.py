#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bumblebee License Bot — KoGyi PHP Server (Bumblebee WiFi) app ရဲ့ approval server.

App က ပထမဆုံး ဖွင့်တဲ့အခါ ဒီ server ကို approval တောင်းတယ်။
Admin (ကိုကြီး) က Telegram ကနေ Approve ပေးရင် အဲ့ device က ဘယ်ချိန်နေနေ
သုံးလို့ရတယ်။ Revoke လုပ်လိုက်ရင် app ပြန်လော့ခ်သွားတယ်။

Endpoints (Render free web service, $PORT):
  GET  /                        -> "OK" (health check)
  POST /request                 -> {device_id, label?, app_version?}
                                   returns {status, code}
                                   status: pending / approved / rejected / revoked
  GET  /status?device_id=...    -> {status, code} / {status: "unknown"}
  POST /<telegram_token>        -> Telegram webhook

Telegram commands (admin only — ADMIN_ID env var သတ်မှတ်ထားရင် အဲ့ ID ပဲ
အမြဲ admin; မသတ်မှတ်ထားရင် /start ပို့တဲ့ ပထမလူက admin):
  /start                        -> admin သတ်မှတ်ခြင်း + အကူအညီ
  /approve CODE                 -> device ကို approve (ဥပမာ /approve BEE-7K2Q9)
  /revoke CODE                  -> device ကို revoke (app ပြန်လော့ခ်သွားမယ်)
  /list                         -> approve ထားတဲ့ device တွေကြည့်
  /pending                      -> စောင့်နေတဲ့ တောင်းဆိုမှုတွေကြည့်
  Approve / Reject ခလုတ်တွေကနေ တိုက်ရိုက် လုပ်လို့လည်း ရတယ်။

Storage: licenses.json — local ဖိုင် + GitHub (persistent)။
Render free plan မှာ disk က ephemeral ဖြစ်တယ် — redeploy / restart /
sleep ဖြစ်ရင် local licenses.json ပျောက်တယ်။ ဒါကြောင့် GitHub repo ထဲ
သိမ်းတယ် (Contents API, stdlib urllib ပဲ သုံးတယ်):
  GITHUB_TOKEN  — GitHub fine-grained PAT (Contents: read + write)
  GITHUB_REPO   — ဥပမာ remotemail130-cloud/bumblebee-licenses
  GITHUB_PATH   — ဖိုင်လမ်းကြောင်း (ပုံသေ licenses.json)
  GITHUB_BRANCH — branch (ပုံသေ main)
ပုံစံ: load လုပ်တဲ့အခါ local ဖိုင် အရင်ကြည့် (ရှိရင် အဲ့ဒါ သုံး)၊
မရှိရင် GitHub ကနေ ယူပြီး local ပြန်သိမ်း။ save လုပ်တဲ့အခါ local +
GitHub နှစ်ခုလုံး ရေး။ GitHub မသတ်မှတ်ထားရင် (သို့) ဆက်သွယ်လို့မရရင်
local ဖိုင်ပဲ သုံးတယ် (ဟောင်း ပုံစံအတိုင်း) — GitHub error ကြောင့်
bot ဘယ်တော့မှ မကျဘူး။ သတိပြု: GitHub PUT ပျက်ရင် (Render log မှာ
warning ပါတယ်) အဲ့ ပြောင်းလဲမှုက GitHub မှာ မရောက်ဘူး — နောက်
restart မှာ အဲ့ ပြောင်းလဲမှု ပြန်မရနိုင်ဘူး။

Checker bot (voucher lookup + KBZPay PDF) နဲ့ လုံးဝ သီးခြား — code, repo,
Render service, bot token အကုန် သပ်သပ်။
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO
)
log = logging.getLogger("license-bot")

YANGON = timezone(timedelta(hours=6, minutes=30))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STORE_PATH = os.path.join(BASE_DIR, "licenses.json")

TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()

# Permanent admin: ADMIN_ID env var (Render Environment) — ကိုကြီးရဲ့
# Telegram user ID ဂဏန်း။ သတ်မှတ်ထားရင် အဲ့ ID ပဲ အမြဲတမ်း admin —
# restart / redeploy ဖြစ်လည်း မပြောင်းဘူး။ မသတ်မှတ်ထားရင် /start ပို့တဲ့
# ပထမလူက admin (ဟောင်း ပုံစံ၊ licenses.json ထဲ သိမ်း)။
ADMIN_ID = os.environ.get("ADMIN_ID", "").strip()

# GitHub persistence — Render free disk က ephemeral မို့ approval တွေ
# restart / sleep တိုင်း မပျောက်အောင် licenses.json ကို GitHub repo ထဲ
# သိမ်းတယ် (Contents API, stdlib urllib ပဲ သုံးတယ်)။
# GITHUB_TOKEN မသတ်မှတ်ထားရင် local ဖိုင်ပဲ သုံးတယ် (ဟောင်း ပုံစံအတိုင်း)။
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.environ.get("GITHUB_REPO", "").strip()
GITHUB_PATH = os.environ.get("GITHUB_PATH", "licenses.json").strip() or "licenses.json"
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main").strip() or "main"
GITHUB_TIMEOUT = 10  # စက္ကန့် — GitHub API call တစ်ခုအတွက်

# Device code အတွက် အက္ခရာများ — ရောထွေးလွယ်တာတွေ (0/O, 1/I/L) မပါဘူး
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

# status တန်ဖိုးများ: pending / approved / rejected / revoked
STORE_LOCK = asyncio.Lock()


def device_code(device_id):
    """device_id ကနေ တသမတ်တည်း ရတဲ့ code: BEE-XXXXX (5 လုံး)"""
    digest = hashlib.sha256(device_id.encode("utf-8")).digest()
    return "BEE-" + "".join(
        _CODE_ALPHABET[b % len(_CODE_ALPHABET)] for b in digest[:5]
    )


def get_admin_id(store):
    """Admin ရဲ့ Telegram user ID — ADMIN_ID env var (အမြဲ) ကို ဦးစားပေး၊
    မရှိရင် licenses.json ထဲက သိမ်းထားတဲ့ admin_id ကို သုံး။"""
    if ADMIN_ID:
        try:
            return int(ADMIN_ID)
        except ValueError:
            pass
    return store.get("admin_id")


def now_iso():
    return datetime.now(YANGON).isoformat(timespec="seconds")


def _empty_store():
    return {"admin_id": None, "devices": {}}


# ------------------------------------------------------- GitHub persistence
# load_store / save_store ထဲက GitHub အပိုင်းက sync (urllib) ဖြစ်တယ် —
# GitHub ကို ခေါ်တာ ရှားတယ် (local ဖိုင် ပျောက်မှ load, ပြောင်းလဲမှ save)
# မို့ event loop ကို ကြာကြာ မပိတ်ဘူး။ timeout 10 စက္ကန့် ထားတယ်။

def github_configured():
    """GitHub persistence ဖွင့်ထားလား — token + repo နှစ်ခုလုံး လိုတယ်။"""
    return bool(GITHUB_TOKEN and GITHUB_REPO and "/" in GITHUB_REPO)


def _github_api_url():
    repo = "/".join(
        urllib.parse.quote(part, safe="") for part in GITHUB_REPO.split("/")
    )
    path = urllib.parse.quote(GITHUB_PATH, safe="/")
    return (
        "https://api.github.com/repos/%s/contents/%s?ref=%s"
        % (repo, path, urllib.parse.quote(GITHUB_BRANCH, safe=""))
    )


def _github_headers():
    return {
        "Authorization": "Bearer " + GITHUB_TOKEN,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "bumblebee-license-bot",
    }


def _github_get_file():
    """GitHub က licenses.json ကို ယူ — (store_dict, sha) ပြန်တယ်။
    ဖိုင် မရှိရင် (404) (None, None)။ error ဖြစ်ရင်လည်း (None, None)
    (log ရေးပြီး local/empty ကို fallback လုပ်)။"""
    if not github_configured():
        return None, None
    try:
        req = urllib.request.Request(
            _github_api_url(), method="GET", headers=_github_headers()
        )
        with urllib.request.urlopen(req, timeout=GITHUB_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data.get("content") or ""
        raw = base64.b64decode("".join(content.split())).decode("utf-8")
        store = json.loads(raw)
        if not isinstance(store, dict) or "devices" not in store:
            log.warning("GitHub က licenses.json ပုံစံ မမှန်ဘူး")
            return None, None
        store.setdefault("admin_id", None)
        return store, data.get("sha")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            log.info("GitHub မှာ licenses.json မရှိသေးဘူး (404)")
        else:
            log.warning("GitHub GET မရဘူး (HTTP %s)", e.code)
        return None, None
    except Exception as e:
        log.warning("GitHub GET မရဘူး: %s", e)
        return None, None


def _github_put_file(store):
    """licenses.json ကို GitHub မှာ သိမ်း — အောင်ရင် True။
    error ဖြစ်ရင် log ရေးပြီး False ပြန် (local ဖိုင်က fallback)။"""
    if not github_configured():
        return False
    try:
        payload = json.dumps(store, ensure_ascii=False, indent=2).encode("utf-8")
        body = {
            "message": "Update licenses.json",
            "content": base64.b64encode(payload).decode("ascii"),
            "branch": GITHUB_BRANCH,
        }
        # ရှိပြီးသား ဖိုင်ကို update လုပ်ဖို့ SHA လိုတယ် (404 ဆို အသစ် ဖန်တီး)
        _, sha = _github_get_file()
        if sha:
            body["sha"] = sha
        req = urllib.request.Request(
            _github_api_url(),
            data=json.dumps(body).encode("utf-8"),
            method="PUT",
            headers=_github_headers(),
        )
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=GITHUB_TIMEOUT) as resp:
            resp.read()
        log.info("licenses.json ကို GitHub (%s) မှာ သိမ်းပြီးပြီ", GITHUB_REPO)
        return True
    except urllib.error.HTTPError as e:
        log.warning("GitHub PUT မရဘူး (HTTP %s)", e.code)
        return False
    except Exception as e:
        log.warning("GitHub PUT မရဘူး: %s", e)
        return False


def _load_local():
    """local licenses.json ကို ဖတ် — မရှိရင် / ပုံစံမမှန်ရင် None။"""
    try:
        with open(STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "devices" not in data:
            return None
        data.setdefault("admin_id", None)
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _save_local(store):
    tmp = STORE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STORE_PATH)


def load_store():
    """licenses.json ကို ဖတ် — local အရင်၊ မရှိရင် GitHub၊
    နှစ်ခုလုံး မရရင် အလွတ် store။ GitHub ကနေ ရရင် local ပြန်သိမ်း
    (နောက် load တွေ မြန်အောင်)။"""
    local = _load_local()
    if local is not None:
        return local
    if github_configured():
        store, _sha = _github_get_file()
        if store is not None:
            try:
                _save_local(store)
            except Exception as e:
                log.warning(
                    "GitHub က ရတဲ့ store ကို local မသိမ်းနိုင်ဘူး: %s", e
                )
            log.info("licenses.json ကို GitHub (%s) ကနေ ယူပြီးပြီ", GITHUB_REPO)
            return store
    return _empty_store()


def save_store(store):
    """licenses.json ကို သိမ်း — local (atomic) + GitHub (ရှိရင်)။
    GitHub error ဖြစ်ရင် log ရေးပြီး ဆက်သွား (local က fallback)။"""
    _save_local(store)
    if github_configured():
        _github_put_file(store)


def find_by_code(store, code):
    """CODE (BEE- ပါတာ/မပါတာ နှစ်မျိုးလုံး လက်ခံ) နဲ့ device ရှာ"""
    code = (code or "").strip().upper()
    if not code:
        return None, None
    if not code.startswith("BEE-"):
        code = "BEE-" + code
    for device_id, dev in store["devices"].items():
        if dev.get("code") == code:
            return device_id, dev
    return None, None


def _device_line(dev):
    label = dev.get("label") or "—"
    return "%s — %s (%s)" % (dev.get("code"), label, dev.get("status"))


# ---------------------------------------------------------------- Telegram
async def notify_admin(app, device_id, dev):
    """Admin ဆီ approval တောင်းတဲ့ စာပို့ (admin မရှိသေးရင် ကျော်သွား)"""
    store = load_store()
    admin_id = get_admin_id(store)
    if not admin_id:
        log.info("Admin မရှိသေးဘူး — %s အတွက် notify မပို့ဘူး", dev["code"])
        return
    text = (
        "🔑 App သုံးခွင့် တောင်းနေတယ်\n\n"
        "Code: %s\n"
        "Device: %s\n"
        "အချိန်: %s\n\n"
        "Approve ပေးရင် အဲ့ device က ဘယ်ချိန်နေနေ သုံးလို့ရမယ်။"
        % (dev["code"], dev.get("label") or "—", dev.get("created", ""))
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Approve", callback_data="ap:" + device_id
                ),
                InlineKeyboardButton(
                    "❌ Reject", callback_data="rj:" + device_id
                ),
            ]
        ]
    )
    try:
        await app.bot.send_message(
            chat_id=admin_id, text=text, reply_markup=keyboard
        )
    except Exception as e:
        log.error("Admin notify မပို့နိုင်ဘူး: %s", e)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store = load_store()
    user = update.effective_user
    admin_id = get_admin_id(store)
    if admin_id is None:
        async with STORE_LOCK:
            store = load_store()
            if get_admin_id(store) is None:
                store["admin_id"] = user.id
                save_store(store)
        await update.message.reply_text(
            "👋 မင်္ဂလာပါ ကိုကြီး — ဒီ bot ရဲ့ admin အဖြစ် သတ်မှတ်ပြီးပြီ။\n\n"
            "App က ပထမဆုံး ဖွင့်တဲ့အခါ ဒီကို approval တောင်းလာမယ်။\n"
            "Approve ပေးရင် အဲ့ device က ဘယ်ချိန်နေနေ သုံးလို့ရမယ်။\n\n"
            "Commands:\n"
            "/approve CODE — ဥပမာ /approve BEE-7K2Q9\n"
            "/revoke CODE — approve ကို ပြန်ဖျက် (app ပြန်လော့ခ်)\n"
            "/list — approve ထားတဲ့ device တွေ\n"
            "/pending — စောင့်နေတဲ့ တောင်းဆိုမှုတွေ"
        )
        return
    if user.id != admin_id:
        await update.message.reply_text(
            "ဒီ bot က Bumblebee app ရဲ့ approval အတွက်ပါ — admin ပဲ သုံးလို့ရတယ်။"
        )
        return
    await update.message.reply_text(
        "Bumblebee License Bot — admin အဖြစ် ဝင်ထားပြီးသား။\n\n"
        "/approve CODE — ဥပမာ /approve BEE-7K2Q9\n"
        "/revoke CODE — approve ကို ပြန်ဖျက်\n"
        "/list — approve ထားတဲ့ device တွေ\n"
        "/pending — စောင့်နေတဲ့ တောင်းဆိုမှုတွေ"
    )


def _is_admin(update):
    store = load_store()
    admin_id = get_admin_id(store)
    return (
        admin_id is not None
        and update.effective_user is not None
        and update.effective_user.id == admin_id
    )


async def approve_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        await update.message.reply_text("Admin ပဲ လုပ်လို့ရတယ်။")
        return
    if not context.args:
        await update.message.reply_text("သုံးပုံ: /approve BEE-7K2Q9")
        return
    async with STORE_LOCK:
        store = load_store()
        device_id, dev = find_by_code(store, context.args[0])
        if dev is None:
            await update.message.reply_text(
                "Code %s နဲ့ device မတွေ့ဘူး။" % context.args[0].upper()
            )
            return
        dev["status"] = "approved"
        dev["updated"] = now_iso()
        save_store(store)
    await update.message.reply_text(
        "✅ %s ကို approve ပေးပြီးပြီ — အဲ့ device က ဘယ်ချိန်နေနေ သုံးလို့ရပြီ။"
        % dev["code"]
    )


async def revoke_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        await update.message.reply_text("Admin ပဲ လုပ်လို့ရတယ်။")
        return
    if not context.args:
        await update.message.reply_text("သုံးပုံ: /revoke BEE-7K2Q9")
        return
    async with STORE_LOCK:
        store = load_store()
        device_id, dev = find_by_code(store, context.args[0])
        if dev is None:
            await update.message.reply_text(
                "Code %s နဲ့ device မတွေ့ဘူး။" % context.args[0].upper()
            )
            return
        dev["status"] = "revoked"
        dev["updated"] = now_iso()
        save_store(store)
    await update.message.reply_text(
        "🔒 %s ကို revoke လုပ်ပြီးပြီ — အဲ့ device ရဲ့ app ပြန်လော့ခ်သွားမယ် "
        "(online ဖြစ်တာနဲ့)။" % dev["code"]
    )


async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        await update.message.reply_text("Admin ပဲ လုပ်လို့ရတယ်။")
        return
    store = load_store()
    approved = [
        d for d in store["devices"].values() if d.get("status") == "approved"
    ]
    if not approved:
        await update.message.reply_text("Approve ထားတဲ့ device မရှိသေးဘူး။")
        return
    lines = ["✅ Approve ထားတဲ့ device တွေ:\n"]
    lines += [_device_line(d) for d in approved]
    await update.message.reply_text("\n".join(lines))


async def pending_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        await update.message.reply_text("Admin ပဲ လုပ်လို့ရတယ်။")
        return
    store = load_store()
    pending = [
        d for d in store["devices"].values() if d.get("status") == "pending"
    ]
    if not pending:
        await update.message.reply_text("စောင့်နေတဲ့ တောင်းဆိုမှု မရှိဘူး။")
        return
    lines = ["⏳ စောင့်နေတဲ့ တောင်းဆိုမှုတွေ:\n"]
    lines += [_device_line(d) for d in pending]
    lines.append("\n/approve CODE နဲ့ approve ပေးလို့ရတယ်။")
    await update.message.reply_text("\n".join(lines))


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not _is_admin(update):
        await query.edit_message_text("Admin ပဲ လုပ်လို့ရတယ်။")
        return
    data = query.data or ""
    action, _, device_id = data.partition(":")
    async with STORE_LOCK:
        store = load_store()
        dev = store["devices"].get(device_id)
        if dev is None:
            await query.edit_message_text("Device မတွေ့တော့ဘူး။")
            return
        if action == "ap":
            dev["status"] = "approved"
            dev["updated"] = now_iso()
            save_store(store)
            await query.edit_message_text(
                "✅ %s ကို approve ပေးပြီးပြီ — အဲ့ device က သုံးလို့ရပြီ။"
                % dev["code"]
            )
        elif action == "rj":
            dev["status"] = "rejected"
            dev["updated"] = now_iso()
            save_store(store)
            await query.edit_message_text(
                "❌ %s ကို reject လုပ်လိုက်ပြီ။" % dev["code"]
            )


# ------------------------------------------------------------------- Web
def create_web_app(app, token):
    """aiohttp app: Telegram webhook + license endpoints (/request, /status)."""
    from aiohttp import web

    async def handle_root(request):
        return web.Response(text="OK")

    async def handle_telegram(request):
        try:
            data = await request.json()
            update = Update.de_json(data, app.bot)
            if update is not None:
                await app.process_update(update)
        except Exception as e:
            log.error("Webhook update error: %s", e)
        return web.Response(text="OK")

    async def handle_request(request):
        """App က approval တောင်းတာ: {device_id, label?, app_version?}"""
        try:
            data = await request.json()
        except Exception:
            return web.json_response(
                {"status": "error", "error": "bad json"}, status=400
            )
        device_id = (data.get("device_id") or "").strip()
        if not device_id:
            return web.json_response(
                {"status": "error", "error": "device_id required"},
                status=400,
            )
        label = (data.get("label") or "").strip()[:100]
        code = device_code(device_id)
        async with STORE_LOCK:
            store = load_store()
            dev = store["devices"].get(device_id)
            if dev is None:
                dev = {
                    "code": code,
                    "label": label,
                    "status": "pending",
                    "created": now_iso(),
                    "updated": now_iso(),
                }
                store["devices"][device_id] = dev
                save_store(store)
                new_request = True
            else:
                dev["last_seen"] = now_iso()
                if label:
                    dev["label"] = label
                # rejected / revoked device က ထပ်တောင်းရင် pending ပြန်ဖြစ်
                if dev["status"] in ("rejected", "revoked"):
                    dev["status"] = "pending"
                    dev["updated"] = now_iso()
                    new_request = True
                else:
                    new_request = False
                save_store(store)
        if new_request:
            await notify_admin(app, device_id, dev)
        return web.json_response({"status": dev["status"], "code": code})

    async def handle_status(request):
        """App က status စစ်တာ: ?device_id=..."""
        device_id = (request.query.get("device_id") or "").strip()
        if not device_id:
            return web.json_response(
                {"status": "error", "error": "device_id required"},
                status=400,
            )
        store = load_store()
        dev = store["devices"].get(device_id)
        if dev is None:
            return web.json_response(
                {"status": "unknown", "code": device_code(device_id)}
            )
        return web.json_response(
            {"status": dev["status"], "code": dev["code"]}
        )

    webapp = web.Application()
    webapp.router.add_get("/", handle_root)
    webapp.router.add_post("/" + token, handle_telegram)
    webapp.router.add_post("/request", handle_request)
    webapp.router.add_get("/status", handle_status)
    return webapp


async def run_webhook_mode(app, token, port):
    base = (
        os.environ.get("WEBHOOK_URL")
        or os.environ.get("RENDER_EXTERNAL_URL")
        or "https://bumblebee-license-bot.onrender.com"
    ).rstrip("/")
    webhook_url = base + "/" + token
    await app.initialize()
    await app.start()
    await app.bot.set_webhook(url=webhook_url)
    log.info("License bot စတင်နေပြီ (webhook) — %s", base)

    from aiohttp import web

    webapp = create_web_app(app, token)
    runner = web.AppRunner(webapp)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        await app.stop()
        await app.shutdown()


def main():
    token = TOKEN
    if not token or token.startswith("123456:"):
        print("TELEGRAM_TOKEN env var ကို အရင် ဖြည့်ပါ (@BotFather ကနေ ရတဲ့ token)။")
        sys.exit(1)
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("approve", approve_cmd))
    app.add_handler(CommandHandler("revoke", revoke_cmd))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CommandHandler("pending", pending_cmd))
    app.add_handler(CallbackQueryHandler(button_callback))
    port = os.environ.get("PORT")
    if port:
        asyncio.run(run_webhook_mode(app, token, int(port)))
    else:
        log.info("License bot စတင်နေပြီ (polling) — /start ပို့ပြီး စမ်းကြည့်ပါ။")
        app.run_polling()


if __name__ == "__main__":
    main()
