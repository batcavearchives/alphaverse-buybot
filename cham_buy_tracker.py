import os
import json
import asyncio
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)
from web3 import Web3
import aiohttp

# ===== CONFIG & STATE =====
CHAM_TOKEN = "0x2c9634d152e8b584d4a153a78dba3e958db7b385".lower()
CONFIG = {
    "PAIR_ADDRESS": "",          # set via button flow
    "EMOJI_STEP_USD": 1.0,
    "EMOJI": "🦎",
    "MEDIA_URL": "",
    "MEDIA_FILE_ID": "",
    "SOCIAL_LINKS": {plat: "" for plat in [
        "dexscreener","twitter","website",
        "instagram","tiktok","discord","linktree"
    ]}
}
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")

w3 = Web3(Web3.HTTPProvider(os.getenv("HYPER_RPC", "https://rpc.hyperliquid.xyz/evm")))
DEX_URL_TEMPLATE = "https://api.dexscreener.com/latest/dex/pairs/{chain}/{pair}"
allowed_platforms = list(CONFIG["SOCIAL_LINKS"].keys())
monitoring_job = None

# ===== HELPERS =====
def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Set Pair Address", callback_data="BTN_SET_PAIR")],
        [InlineKeyboardButton("Set Emoji Step",    callback_data="BTN_SET_STEP")],
        [InlineKeyboardButton("Set Media",         callback_data="BTN_SET_MEDIA")],
        [InlineKeyboardButton("Manage Social",     callback_data="BTN_SOCIAL_MENU")],
        [InlineKeyboardButton("Show Config",       callback_data="BTN_SHOW_CONFIG")],
        [InlineKeyboardButton("▶️ Start Monitor",   callback_data="BTN_START")],
        [InlineKeyboardButton("⏹️ Stop Monitor",    callback_data="BTN_STOP")],
        [InlineKeyboardButton("❓ Help",             callback_data="BTN_HELP")],
    ])

def social_menu() -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(p.title(), callback_data=f"SOCIAL_{p}")] for p in allowed_platforms]
    buttons.append([InlineKeyboardButton("↩️ Back", callback_data="BTN_BACK")])
    return InlineKeyboardMarkup(buttons)

async def send_menu(update_or_q, context: ContextTypes.DEFAULT_TYPE):
    text = "⚙️ *Main Menu*"
    markup = main_menu()
    if (cq := getattr(update_or_q, "callback_query", None)):
        await cq.answer()
        try:
            await cq.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                raise
    else:
        await update_or_q.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")

def fmt_k(x: float) -> str:
    return f"{x/1_000:.2f}K" if x >= 1_000 else f"{x:.2f}"

def shorten(addr: str) -> str:
    return addr[:6] + "..." + addr[-4:]

def render_emojis(usd_amt: float) -> str:
    count = int(usd_amt // CONFIG["EMOJI_STEP_USD"])
    return CONFIG["EMOJI"] * min(count, 50)

# ===== FETCH PAIR METADATA =====
async def fetch_pair_data() -> dict:
    if not CONFIG["PAIR_ADDRESS"]:
        return {}
    url = DEX_URL_TEMPLATE.format(chain=os.getenv("CHAIN_ID","256"), pair=CONFIG["PAIR_ADDRESS"])
    async with aiohttp.ClientSession() as s:
        async with s.get(url) as r:
            data = await r.json()
    pair = data.get("pair", {})
    return {
        "price":      float(pair.get("priceUsd", 0)),
        "liquidity":  float(pair.get("liquidityUsd", 0)),
        "mcap":       float(pair.get("fdv", 0)),
        "hype_price": float(pair.get("token0", {}).get("priceUsd", 0)),
        "change24h":  float(pair.get("priceChange24h", 0)),
        "token0":     pair.get("token0", {}),
        "token1":     pair.get("token1", {}),
    }

# ===== MONITOR LOOP WITH DEBUG & AUTO‑DETECT =====
async def monitor_loop(context: ContextTypes.DEFAULT_TYPE):
    data = await fetch_pair_data()
    if not data:
        print("⚠️ No pair address configured.")
        return

    # detect CHAM index
    if data["token0"].get("address","").lower() == CHAM_TOKEN:
        cham_idx, other_idx = 0, 1
    elif data["token1"].get("address","").lower() == CHAM_TOKEN:
        cham_idx, other_idx = 1, 0
    else:
        print("⚠️ CHAM token not in pool metadata.")
        return

    block = w3.eth.get_block("latest", full_transactions=True)
    print(f"🔎 Scanning block {block.number} ({len(block.transactions)} txs)")
    for tx in block.transactions:
        receipt = w3.eth.get_transaction_receipt(tx.hash)
        for log in receipt.logs:
            if log.address.lower() != CONFIG["PAIR_ADDRESS"].lower():
                continue
            print("  ➡️ Swap on pair:", tx.hash.hex())
            try:
                amt0_in, amt1_in, amt0_out, amt1_out = w3.codec.decode(
                    ['uint256','uint256','uint256','uint256'], log.data
                )
            except Exception as e:
                print("   decode error:", e)
                continue
            print(f"   raw in0:{amt0_in} in1:{amt1_in} out0:{amt0_out} out1:{amt1_out}")

            out_amt = amt0_out if cham_idx==0 else amt1_out
            in_amt  = amt1_in  if cham_idx==0 else amt0_in

            if out_amt > 0:
                hype_amt = w3.from_wei(in_amt, 'ether')
                cham_amt = w3.from_wei(out_amt,'ether')
                usd_cost = hype_amt * data["hype_price"]
                buyer    = w3.to_checksum_address("0x"+log.topics[2].hex()[26:])
                pct      = data["change24h"]
                print(f"   🎉 BUY detected: {cham_amt:.4f} CHAM for {hype_amt:.4f} ≃ ${usd_cost:.2f}")

                # build alert
                caption = (
                    "CHAM Buy!\n\n"
                    f"{render_emojis(usd_cost)}\n\n"
                    f"💵 {hype_amt:.2f} HYPE (${usd_cost:.2f})\n"
                    f"💰 {fmt_k(cham_amt)} CHAM\n\n"
                    f"[{shorten(buyer)}]"
                    f"(https://hyperevmscan.io/address/{buyer}) +{pct:.1f}% │ "
                    f"[Txn](https://hyperevmscan.io/tx/{tx.hash.hex()})\n"
                    f"Price: ${data['price']:.6f}\n"
                    f"Liquidity: ${data['liquidity']/1_000:,.2f}K\n"
                    f"MCap: ${data['mcap']/1_000:,.2f}K\n"
                    f"HYPE Price: ${data['hype_price']:.4f}"
                )

                # append socials
                socials = []
                for plat, url in CONFIG["SOCIAL_LINKS"].items():
                    if url:
                        label = "DexS" if plat=="dexscreener" else plat.title()
                        socials.append(f"[{label}]({url})")
                if socials:
                    caption += "\n\n" + " │ ".join(socials)

                # send media if any
                if CONFIG["MEDIA_FILE_ID"]:
                    await context.bot.send_animation(chat_id=context.job.chat_id,
                                                     animation=CONFIG["MEDIA_FILE_ID"])
                elif CONFIG["MEDIA_URL"]:
                    low = CONFIG["MEDIA_URL"].lower()
                    if any(low.endswith(ext) for ext in ('.mp4','.mov','.mkv','.webm')):
                        await context.bot.send_video(chat_id=context.job.chat_id,
                                                     video=CONFIG["MEDIA_URL"])
                    elif low.endswith('.gif'):
                        await context.bot.send_animation(chat_id=context.job.chat_id,
                                                         animation=CONFIG["MEDIA_URL"])
                    else:
                        await context.bot.send_photo(chat_id=context.job.chat_id,
                                                     photo=CONFIG["MEDIA_URL"])

                # final alert
                await context.bot.send_message(
                    chat_id=context.job.chat_id,
                    text=caption,
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )

# ===== HANDLERS =====
async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global monitoring_job
    cq = update.callback_query; data = cq.data
    await cq.answer()
    context.user_data.pop("expecting", None)

    if data == "BTN_SET_PAIR":
        context.user_data["expecting"] = "PAIR"
        await cq.message.reply_markdown("🔹 Send token pair contract address now.")
    elif data == "BTN_SET_STEP":
        context.user_data["expecting"] = "STEP"
        await cq.message.reply_markdown("🔹 Send USD per emoji (e.g. `1`).")
    elif data == "BTN_SET_MEDIA":
        context.user_data["expecting"] = "MEDIA"
        await cq.message.reply_markdown("🔹 Send URL or upload media; `none` to clear.")
    elif data == "BTN_SOCIAL_MENU":
        await cq.edit_message_text("🔗 Choose platform:", reply_markup=social_menu(), parse_mode="Markdown")
        return
    elif data.startswith("SOCIAL_"):
        plat = data.split("_",1)[1]
        context.user_data["expecting"] = f"SOCIAL_{plat}"
        await cq.message.reply_markdown(f"🔹 Send URL for *{plat.title()}*")
    elif data == "BTN_BACK":
        await send_menu(update, context); return
    elif data == "BTN_SHOW_CONFIG":
        conf = CONFIG.copy(); conf["PAIR_ADDRESS"] = conf["PAIR_ADDRESS"] or "_Not set_"
        await cq.message.reply_text("📋 Config:\n" + json.dumps(conf, indent=2))
    elif data == "BTN_START":
        if monitoring_job:
            await cq.message.reply_text("⚠️ Already monitoring.")
        else:
            monitoring_job = context.application.job_queue.run_repeating(
                monitor_loop, interval=5, first=0, chat_id=update.effective_chat.id
            )
            await cq.message.reply_text("✅ Monitoring started.")
        await send_menu(update, context); return
    elif data == "BTN_STOP":
        if monitoring_job:
            monitoring_job.schedule_removal()
            monitoring_job = None
            await cq.message.reply_text("🛑 Monitoring stopped.")
        else:
            await cq.message.reply_text("⚠️ Not monitoring.")
        await send_menu(update, context); return
    elif data == "BTN_HELP":
        await cq.message.reply_markdown("🛠 *Help*: Use buttons to configure/control")

    await send_menu(update, context)

async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.animation:
        CONFIG["MEDIA_FILE_ID"], CONFIG["MEDIA_URL"] = msg.animation.file_id, ""
        await msg.reply_text("✅ GIF uploaded.")
    elif msg.photo:
        CONFIG["MEDIA_FILE_ID"], CONFIG["MEDIA_URL"] = msg.photo[-1].file_id, ""
        await msg.reply_text("✅ Photo uploaded.")
    else:
        return
    context.user_data.pop("expecting", None)
    await send_menu(update, context)

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    expect = context.user_data.get("expecting")
    text   = update.message.text.strip()

    if expect == "PAI
