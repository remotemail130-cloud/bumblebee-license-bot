# Bumblebee License Bot — App Approval Server

KoGyi PHP Server (Bumblebee WiFi) app ရဲ့ သုံးခွင့် approval server။
Checker bot (voucher lookup + KBZPay PDF) နဲ့ လုံးဝ သီးခြား။

## အလုပ်လုပ်ပုံ

1. App က ပထမဆုံး ဖွင့်တဲ့အခါ device ID တစ်ခု ထုတ်ပြီး `POST /request` နဲ့
   approval တောင်းတယ်။ App screen မှာ device code (ဥပမာ `BEE-7K2Q9`) ပြတယ်။
2. Server က admin (ကိုကြီး) ဆီ Telegram စာပို့တယ် — Approve / Reject ခလုတ် ပါမယ်။
3. Approve ပေးရင် အဲ့ device က ဘယ်ချိန်နေနေ သုံးလို့ရတယ်။
4. Revoke လုပ်လိုက်ရင် အဲ့ device ရဲ့ app က online ဖြစ်တာနဲ့ ပြန်လော့ခ်သွားတယ်။

App က ဖွင့်တိုင်း `GET /status?device_id=...` နဲ့ စစ်တယ်။
Internet မရှိရင် အရင် approve ထားပြီးသား ဆက်သုံးလို့ရတယ် (revoke က
online ဖြစ်မှ သက်ရောက်တယ်)။

## Setup

1. Telegram မှာ **@BotFather** → `/newbot` → နာမည် + username ပေး → token ရမယ်။
   Token ကို ဘယ်သူ့ကိုမှ မပို့ပါနဲ့။
2. GitHub repo အသစ် (`bumblebee-license-bot`) မှာ ဒီဖိုင်တွေ တင်ပါ။
3. Render (free) မှာ Web Service အသစ် → repo ချိတ် →
   env var `TELEGRAM_TOKEN` မှာ token ထည့် → Deploy။
   Service URL က `https://bumblebee-license-bot.onrender.com` ပုံစံ ရမယ်။
4. Telegram မှာ bot အသစ်ကို `/start` ပို့ — ပို့တဲ့ ပထမလူက admin ဖြစ်သွားမယ်။

## Telegram Commands (admin only)

| Command | အသုံး |
|---|---|
| `/start` | admin သတ်မှတ် + အကူအညီ |
| `/approve CODE` | ဥပမာ `/approve BEE-7K2Q9` |
| `/revoke CODE` | approve ကို ပြန်ဖျက် (app ပြန်လော့ခ်) |
| `/list` | approve ထားတဲ့ device တွေ |
| `/pending` | စောင့်နေတဲ့ တောင်းဆိုမှုတွေ |

Approve/Reject ခလုတ်တွေကနေလည်း တိုက်ရိုက် လုပ်လို့ရတယ်။

## API

- `GET /` — "OK" (health check)
- `POST /request` — body `{"device_id": "...", "label": "Xiaomi Civi 3", "app_version": "2.4"}`
  → `{"status": "pending"|"approved"|"rejected"|"revoked", "code": "BEE-XXXXX"}`
- `GET /status?device_id=...` — → `{"status": "...", "code": "BEE-XXXXX"}`
  မသိတဲ့ device ဆို `{"status": "unknown"}`

## သတိပြုရန်

- **Render free disk က ephemeral**: redeploy / restart ဖြစ်ရင်
  `licenses.json` ပျောက်ပြီး approval တွေ ပြန်တောင်းရမယ်။
  Approve လုပ်ထားတဲ့ code တွေကို Telegram စာထဲမှာ မှတ်ထားပါ။
- **Render free က 15 မိနစ် idle ဖြစ်ရင် sleep**: ပထမဆုံး request က
  ~1 မိနစ် ကြာတတ်တယ် (service နိုးလာတာကို စောင့်ရတယ်)။
- ဒီ approval စနစ်က သာမန် ခိုးယူသုံးစွဲမှုကို တားတာ — APK ဖိုင် လက်ထဲရောက်ပြီး
  code ကို ကျွမ်းကျင်စွာ ပြင်တတ်တဲ့သူကိုတော့ 100% တားလို့မရဘူး။
  အဲ့ဒါကြောင့် APK ကို မလိုအပ်ပဲ မဖြန့်ပါနဲ့။
