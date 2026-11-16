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

Telegram commands (admin only, /start ပို့တဲ့ ပထမလူက admin):
  /start                        -> admin သတ်မှတ်ခြင်း + အကူအညီ
  /approve CODE                 -> device ကို approve (ဥပမာ /approve BEE-7K2Q9)
  /revoke CODE                  -> device ကို revoke (app ပြန်လော့ခ်သွားမယ်)
  /list                         -> approve ထားတဲ့ device တွေကြည့်
  /pending                      -> စောင့်နေတဲ့ တောင်းဆိုမှုတွေကြည့်
  Approve / Reject ခလုတ်တွေကနေ တိုက်ရိုက် လုပ်လို့လည်း ရတယ်။

Storage: licenses.json (server ပေါ်က ဖိုင်)။
သတိပြု: Render free plan မှာ disk က ephemeral ဖြစ်တယ် — redeploy / restart
ဖြစ်ရင် licenses.json ပျောက်ပြီး approval တွေ ပြန်တောင်းရမယ်။ ဒါကြောင့်
approve လုပ်ထားတဲ့ device code တွေကို Telegram စာထဲမှာ မှတ်ထားပါ။

Checker bot (voucher lookup + KBZPay PDF) နဲ့ လုံးဝ သီးခြား — code, repo,
Render service, bot token အကုန် သပ်သပ်။
"""

import asyncio
import hashlib
import json
import logging
import os
import sys
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


def now_iso():
    return datetime.now(YANGON).isoformat(timespec="seconds")


def _empty_store():
    return {"admin_id": None, "devices": {}}


def load_store():
    try:
        with open(STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "devices" not in data:
            return _empty_store()
        data.setdefault("admin_id", None)
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return _empty_store()


def save_store(store):
    tmp = STORE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STORE_PATH)


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
    admin_id = store.get("admin_id")
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
    if store.get("admin_id") is None:
        async with STORE_LOCK:
            store = load_store()
            if store.get("admin_id") is None:
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
    if user.id != store.get("admin_id"):
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
    return (
        store.get("admin_id") is not None
        and update.effective_user is not None
        and update.effective_user.id == store["admin_id"]
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
