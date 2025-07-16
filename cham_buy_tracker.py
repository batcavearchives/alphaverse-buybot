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
CONFIG = {
    "PAIR_ADDRESS": "",
    "EMOJI_STEP_USD": 1.0,
    "EMOJI": "🦎",
    "MEDIA_URL": "",
    "MEDIA_FILE_ID": "",
    "SOCIAL_LINKS": {
        "dexscreener": "",
        "twitter": "",
        "website": "",
        "instagram": "",
        "tiktok": "",
        "discord": "",
        "linktree": ""
    }
}
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
w3 = Web3(Web3.HTTPProvider(os.getenv("HYPER_RPC", "https://rpc.hyperliquid.xyz/evm")))
DEX_URL_TEMPLATE = "https://api.dexscreener.com/latest/dex/pairs/{chain}/{pair}"
allowed_platforms = list(CONFIG["SOCIAL_LINKS"].keys())
monitoring_job = None  # JobQueue job handle

# ===== HELPERS =====
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Set Pair Address", callback_data="BTN_SET_PAIR")],
        [InlineKeyboardButton("Set Emoji Step", callback_data="BTN_SET_STEP")],
        [InlineKeyboardButton("Set Media", callback_data="BTN_SET_MEDIA")],
        [InlineKeyboardButton("Manage Social Links", callback_data="BTN_SOCIAL_MENU")],
        [InlineKeyboardButton("Show Config", callback_data="BTN_SHOW_CONFIG")],
        [InlineKeyboardButton("Start Monitor", callback_data="BTN_START")],
        [InlineKeyboardButton("Stop Monitor", callback_data="BTN_STOP")],
        [InlineKeyboardButton("Help", callback_data="BTN_HELP")],
    ])

def social_menu():
    buttons = [[InlineKeyboardButton(p.title(), callback_data=f"SOCIAL_{p}")] for p in allowed_platforms]
    buttons.append([InlineKeyboardButton("↩️ Back", callback_data="BTN_BACK")])
    return InlineKeyboardMarkup(buttons)

async def send_menu(update, context):
    text = "⚙️ *Main Menu*"
    markup = main_menu()
    if update.callback_query:
        cq = update.callback_query
        await cq.answer()
        try:
            await cq.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                raise
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")

def fmt_k(x):
    return f"{x/1_000:.2f}K" if x >= 1_000 else f"{x:.2f}"

def shorten(addr):
    return addr[:6] + "..." + addr[-4:]

def render_emojis(usd_amount):
    count = int(usd_amount // CONFIG["EMOJI_STEP_USD"])
    return CONFIG["EMOJI"] * min(count, 50)

async def fetch_stats():
    url = DEX_URL_TEMPLATE.format(chain=os.getenv("CHAIN_ID","256"), pair=CONFIG["PAIR_ADDRESS"])
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            p = data.get("pair", {})
            return {
                "price": float(p.get("priceUsd", 0)),
                "liquidity": float(p.get("liquidityUsd", 0)),
                "mcap": float(p.get("fdv", 0)),
                "hype_price": float(p.get("token0", {}).get("priceUsd", 0)),
                "change24h": float(p.get("priceChange24h", 0))
            }

async def send_alert(chat_id, caption):
    bot = context.bot if (context := None) else None  # placeholder, will use context.bot in job
    # In job, context.bot is available via context in monitor_loop

# ===== MONITOR LOOP =====
async def monitor_loop(context: ContextTypes.DEFAULT_TYPE):
    stats = await fetch_stats()
    block = w3.eth.get_block("latest", full_transactions=True)
    for tx in block.transactions:
        receipt = w3.eth.get_transaction_receipt(tx.hash)
        for log in receipt.logs:
            if log.address.lower() == CONFIG["PAIR_ADDRESS"]:
                try:
                    amt0_in, _, _, amt1_out = w3.codec.decode(
                        ['uint256','uint256','uint256','uint256'], log.data
                    )
                except:
                    continue
                if amt1_out > 0:
                    hype_amt = w3.from_wei(amt0_in, 'ether')
                    usd_cost = hype_amt * stats["hype_price"]
                    buyer = w3.to_checksum_address("0x" + log.topics[2].hex()[26:])
                    cham_amt = w3.from_wei(amt1_out, 'ether')
                    pct_change = stats['change24h']
                    caption = (
                        "CHAM Buy!\n\n"
                        f"{render_emojis(usd_cost)}\n\n"
                        f"💵 {hype_amt:.2f} HYPE (${usd_cost:.2f})\n"
                        f"💰 {fmt_k(cham_amt)} CHAM\n\n"
                        f"{shorten(buyer)}: [View Address](https://hyperevmscan.io/address/{buyer}) +{pct_change:.1f}% │ "
                        f"[Txn](https://hyperevmscan.io/tx/{tx.hash.hex()})\n"
                        f"Price: ${stats['price']:.6f}\n"
                        f"Liquidity: ${stats['liquidity']/1_000:,.2f}K\n"
                        f"MCap: ${stats['mcap']/1_000:,.2f}K\n"
                        f"HYPE Price: ${stats['hype_price']:.4f}"
                    )
                    # send media if set
                    if CONFIG["MEDIA_FILE_ID"]:
                        await context.bot.send_animation(chat_id=context.job.chat_id, animation=CONFIG["MEDIA_FILE_ID"])
                    elif CONFIG["MEDIA_URL"]:
                        url = CONFIG["MEDIA_URL"]
                        lower = url.lower()
                        if any(lower.endswith(ext) for ext in ('.mp4','.mov','.mkv','.webm')):
                            await context.bot.send_video(chat_id=context.job.chat_id, video=url)
                        elif lower.endswith('.gif'):
                            await context.bot.send_animation(chat_id=context.job.chat_id, animation=url)
                        else:
                            await context.bot.send_photo(chat_id=context.job.chat_id, photo=url)
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
        return await cq.message.reply_text("🔹 Send token pair contract address:", parse_mode="Markdown")

    if data == "BTN_SET_STEP":
        context.user_data["expecting"] = "STEP"
        return await cq.message.reply_text("🔹 Send USD per emoji (e.g. `1`):", parse_mode="Markdown")

    if data == "BTN_SET_MEDIA":
        context.user_data["expecting"] = "MEDIA"
        return await cq.message.reply_text("🔹 Send URL or upload media, or `none` to clear:", parse_mode="Markdown")

    if data == "BTN_SOCIAL_MENU":
        return await cq.edit_message_text("🔗 *Select platform:*", reply_markup=social_menu(), parse_mode="Markdown")

    if data.startswith("SOCIAL_"):
        platform = data.split("_",1)[1]
        context.user_data["expecting"] = f"SOCIAL_{platform}"
        return await cq.message.reply_text(f"🔹 Send URL for *{platform.title()}*:", parse_mode="Markdown")

    if data == "BTN_BACK":
        return await send_menu(update, context)

    if data == "BTN_SHOW_CONFIG":
        conf = CONFIG.copy(); conf["PAIR_ADDRESS"] = conf["PAIR_ADDRESS"] or "_Not set_"
        return await cq.message.reply_text("📋 Config:\n" + json.dumps(conf, indent=2))

    if data == "BTN_START":
        if monitoring_job:
            await cq.message.reply_text("⚠️ Already monitoring.")
        else:
            monitoring_job = context.job_queue.run_repeating(monitor_loop, interval=5, first=0, chat_id=update.effective_chat.id)
            await cq.message.reply_text("✅ Monitoring started.")
        return await send_menu(update, context)

    if data == "BTN_STOP":
        if monitoring_job:
            monitoring_job.schedule_removal(); monitoring_job = None
            await cq.message.reply_text("🛑 Monitoring stopped.")
        else:
            await cq.message.reply_text("⚠️ Not monitoring.")
        return await send_menu(update, context)

    if data == "BTN_HELP":
        return await cq.message.reply_markdown(
            "🛠 *Help*\nUse buttons to configure and control the bot."
        )

    await send_menu(update, context)

async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.animation:
        CONFIG["MEDIA_FILE_ID"], CONFIG["MEDIA_URL"] = msg.animation.file_id, ""
        await msg.reply_text("✅ Uploaded GIF set.")
    elif msg.photo:
        CONFIG["MEDIA_FILE_ID"], CONFIG["MEDIA_URL"] = msg.photo[-1].file_id, ""
        await msg.reply_text("✅ Uploaded photo set.")
    else:
        return
    context.user_data.pop("expecting", None)
    await send_menu(update, context)

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    expect = context.user_data.get("expecting")
    text = update.message.text.strip()

    if expect == "PAIR":
        CONFIG["PAIR_ADDRESS"] = text.lower()
        await update.message.reply_markdown(f"✅ Pair set to `{text}`")

    elif expect == "STEP":
        try:
            CONFIG["EMOJI_STEP_USD"] = float(text)
            await update.message.reply_markdown(f"✅ Emoji step set to *${text}*")
        except ValueError:
            return await update.message.reply_text("❌ Invalid number.")

    elif expect == "MEDIA":
        if text.lower() == "none":
            CONFIG["MEDIA_URL"] = ""; CONFIG["MEDIA_FILE_ID"] = ""
            await update.message.reply_text("✅ Media cleared.")
        else:
            CONFIG["MEDIA_URL"] = text; CONFIG["MEDIA_FILE_ID"] = ""
            await update.message.reply_text(f"✅ Media URL set to {text}")

    elif expect and expect.startswith("SOCIAL_"):
        platform = expect.split("_",1)[1]
        CONFIG["SOCIAL_LINKS"][platform] = text
        await update.message.reply_text(f"✅ {platform.title()} link set.")

    else:
        return

    context.user_data.pop("expecting", None)
    await send_menu(update, context)

# ===== MAIN =====
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", send_menu))
    app.add_handler(CallbackQueryHandler(button_router))
    app.add_handler(MessageHandler(filters.ANIMATION | filters.PHOTO, media_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.run_polling()

if __name__ == "__main__":
    main()
