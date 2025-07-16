import os, json, asyncio
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from web3 import Web3
import aiohttp

# ===== CONFIG & STATE =====
CONFIG = {
    "HYPER_RPC": os.getenv("HYPER_RPC", "https://rpc.hyperliquid.xyz/evm"),
    "CHAIN_ID": int(os.getenv("CHAIN_ID", "256")),
    "PAIR_ADDRESS": "",
    "EMOJI": os.getenv("EMOJI", "🦎"),
    "EMOJI_STEP_USD": float(os.getenv("EMOJI_STEP_USD", "1.0")),
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
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

w3 = Web3(Web3.HTTPProvider(CONFIG["HYPER_RPC"]))
DEX_URL_TEMPLATE = "https://api.dexscreener.com/latest/dex/pairs/{chain}/{pair}"
allowed_platforms = set(CONFIG["SOCIAL_LINKS"].keys())
monitoring_task = None

# ===== HANDLERS =====

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_markdown(
        "👋 *Welcome to the CHAM Buy Tracker Bot!*  
"
        "To get started, please send your token contract address:
"
        "`/setpair <contract_address>`"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_markdown(
        "🛠 *CHAM Buy Bot Help*

"
        "• /setpair `<address>` — Set CHAM pair contract address
"
        "• /setstep `<usd>` — USD per emoji
"
        "• /setmedia `<url>` — Image/GIF/video URL OR upload a GIF/photo/video
"
        "• /setsocial `<platform> <url>` — Add a social link (dexscreener, twitter, website, instagram, tiktok, discord, linktree)
"
        "• /showsocial — Show current social links
"
        "• /showconfig — View current settings
"
        "• /startmonitor — Start monitoring
"
        "• /stopmonitor — Stop monitoring
"
    )

async def setpair(update, context):
    if context.args:
        addr = context.args[0].lower()
        CONFIG["PAIR_ADDRESS"] = addr
        await update.message.reply_markdown(
            f"✅ Pair address set to `{addr}`

"
            "Now tell me how many USD each emoji represents.
"
            "`/setstep <usd_value>`
"
            "Example: `/setstep 1` means $1 = 1 emoji."
        )
    else:
        await update.message.reply_text("Usage: /setpair `<contract_address>`")

async def setstep(update, context):
    usage = "Usage: /setstep <usd_per_emoji>\nExample: `/setstep 1` means $1 = 1 emoji."
    if not context.args:
        return await update.message.reply_markdown(usage)
    try:
        step = float(context.args[0])
    except ValueError:
        return await update.message.reply_markdown(usage)
    CONFIG["EMOJI_STEP_USD"] = step
    # Examples
    sample_amounts = [step, step*5, step*10, step*50]
    lines = []
    for amt in sample_amounts:
        count = int(amt // step)
        lines.append(f"• ${amt:.0f} → {CONFIG['EMOJI'] * count}")
    await update.message.reply_markdown(
        f"✅ Emoji step USD set to *${step:.2f}* (1 emoji per ${step:.2f})\n\n"
        "*Examples:*\n"
        + "\n".join(lines) +
        "\n\nOptionally, add an image, GIF, or video at the top of each alert:\n"
        "`/setmedia <url>`\n"
        "Or just upload a GIF/photo/video now, or skip with `/setmedia none`"
    )

async def setmedia(update, context):
    msg = update.message
    if msg.animation:
        CONFIG["MEDIA_FILE_ID"] = msg.animation.file_id
        CONFIG["MEDIA_URL"]     = ""
        return await msg.reply_text("✅ Using your uploaded GIF for alerts.\nNow, optionally add social links with `/setsocial <platform> <url>` or check `/showsocial`.")
    if msg.photo:
        file_id = msg.photo[-1].file_id
        CONFIG["MEDIA_FILE_ID"] = file_id
        CONFIG["MEDIA_URL"]     = ""
        return await msg.reply_text("✅ Using your uploaded photo for alerts.\nNow, optionally add social links with `/setsocial <platform> <url>` or check `/showsocial`.")
    if context.args and context.args[0].lower() != "none":
        CONFIG["MEDIA_URL"]     = context.args[0]
        CONFIG["MEDIA_FILE_ID"] = ""
        await msg.reply_text(f"✅ Media URL set to:\n{CONFIG['MEDIA_URL']}")
    else:
        CONFIG["MEDIA_URL"]     = ""
        CONFIG["MEDIA_FILE_ID"] = ""
        await msg.reply_text("✅ Media cleared; no image/GIF/video will be sent.")
    await msg.reply_markdown(
        "Optionally add social links:\n"
        "`/setsocial <platform> <url>`\n"
        "Platforms: dexscreener, twitter, website, instagram, tiktok, discord, linktree\n"
        "View current with `/showsocial`"
    )

async def setsocial(update, context):
    if len(context.args) < 2:
        platforms = ", ".join(sorted(allowed_platforms))
        return await update.message.reply_text(
            f"Usage: /setsocial <platform> <url>\nAllowed: {platforms}"
        )
    platform = context.args[0].lower()
    url = context.args[1]
    if platform not in allowed_platforms:
        return await update.message.reply_text(
            f"Invalid platform. Allowed: {', '.join(sorted(allowed_platforms))}"
        )
    CONFIG["SOCIAL_LINKS"][platform] = url
    await update.message.reply_text(f"✅ {platform.title()} link set to {url}")

async def showsocial(update, context):
    text = "🔗 *Social Links:*\n"
    for p in sorted(allowed_platforms):
        val = CONFIG["SOCIAL_LINKS"].get(p) or "_Not set_"
        text += f"- *{p.title()}:* {val}\n"
    await update.message.reply_markdown(text)

async def showconfig(update, context):
    display = CONFIG.copy()
    display['TELEGRAM_TOKEN'] = "****"
    await update.message.reply_text("📋 Current Config:\n" + json.dumps(display, indent=2))

# ===== MONITORING =====
def render_emojis(usd_amount):
    count = int(usd_amount // CONFIG["EMOJI_STEP_USD"])
    return CONFIG["EMOJI"] * min(count, 50)

async def fetch_stats():
    url = DEX_URL_TEMPLATE.format(chain=CONFIG["CHAIN_ID"], pair=CONFIG["PAIR_ADDRESS"])
    async with aiohttp.ClientSession() as s:
        async with s.get(url) as r:
            data = await r.json()
            p = data.get("pair", {})
            # You can expand this as needed
            return {
                "price": float(p.get("priceUsd", 0)),
                "liquidity": float(p.get("liquidityUsd", 0)),
                "mcap": float(p.get("fdv", 0)),
                "hype_price": float(p.get("token0", {}).get("priceUsd", 0)),
                "change24h": float(p.get("priceChange24h", 0))
            }

async def send_alert(chat_id, caption):
    if CONFIG["MEDIA_FILE_ID"]:
        await app.bot.send_animation(chat_id=chat_id, animation=CONFIG["MEDIA_FILE_ID"])
    elif CONFIG["MEDIA_URL"]:
        url = CONFIG["MEDIA_URL"]
        lower = url.lower()
        if any(lower.endswith(ext) for ext in ('.mp4', '.mov', '.mkv', '.webm')):
            await app.bot.send_video(chat_id=chat_id, video=url)
        elif lower.endswith('.gif'):
            await app.bot.send_animation(chat_id=chat_id, animation=url)
        else:
            await app.bot.send_photo(chat_id=chat_id, photo=url)
    await app.bot.send_message(
        chat_id=chat_id,
        text=caption,
        parse_mode="Markdown",
        disable_web_page_preview=True
    )

def fmt_k(x):
    return f"{x/1_000:.2f}K" if x >= 1_000 else f"{x:.2f}"

def shorten(addr): return addr[:4] + "..." + addr[-4:]

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
                    pct_change = stats.get('change24h', 0.0)
                    msg = (
                        "CHAM Buy!\n\n"
                        f"{render_emojis(usd_cost)}\n\n"
                        f"💵 {hype_amt:.2f} HYPE (${usd_cost:.2f})\n"
                        f"💰 {fmt_k(cham_amt)} CHAM\n\n"
                        f"{shorten(buyer)}: (https://hyperevmscan.io/address/{buyer}) +{pct_change:.1f}% | "
                        f"Txn (https://hyperevmscan.io/tx/{tx.hash.hex()})\n"
                        f"Price: ${stats['price']:.5f}\n"
                        f"Liquidity: ${stats['liquidity']/1_000:,.2f}K\n"
                        f"MCap: ${stats['mcap']/1_000:,.2f}K\n"
                        f"HYPE Price: ${stats['hype_price']:.2f}\n"
                    )
                    await send_alert(context.job.chat_id, msg)

async def startmonitor(update, context):
    global monitoring_task
    if monitoring_task:
        await update.message.reply_text("⚠️ Already monitoring.")
    else:
        monitoring_task = context.job_queue.run_repeating(
            monitor_loop, interval=5, first=0, chat_id=update.effective_chat.id
        )
        await update.message.reply_text("✅ Started monitoring buys.")

async def stopmonitor(update, context):
    global monitoring_task
    if monitoring_task:
        monitoring_task.schedule_removal()
        monitoring_task = None
        await update.message.reply_text("🛑 Stopped monitoring.")
    else:
        await update.message.reply_text("⚠️ Not currently monitoring.")

# ===== MAIN =====
def main():
    global app
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("setpair", setpair))
    app.add_handler(CommandHandler("setstep", setstep))
    app.add_handler(CommandHandler("setmedia", setmedia))
    app.add_handler(CommandHandler("setsocial", setsocial))
    app.add_handler(CommandHandler("showsocial", showsocial))
    app.add_handler(CommandHandler("showconfig", showconfig))
    app.add_handler(CommandHandler("startmonitor", startmonitor))
    app.add_handler(CommandHandler("stopmonitor", stopmonitor))
    app.add_handler(MessageHandler(filters.ANIMATION | filters.PHOTO, setmedia))  # allows uploads for /setmedia
    app.run_polling()

if __name__ == "__main__":
    main()
