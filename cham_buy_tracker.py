import os, json, asyncio
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CallbackQueryHandler, MessageHandler,
    ContextTypes, filters
)
from web3 import Web3
import aiohttp

# ——— CONFIG & STATE ———
CONFIG = {
    "PAIR_ADDRESS": "",
    "EMOJI_STEP_USD": 1.0,
    "EMOJI": "🦎",
    "MEDIA_URL": "",
    "MEDIA_FILE_ID": "",
    "SOCIAL_LINKS": {p: "" for p in [
        "dexscreener","twitter","website",
        "instagram","tiktok","discord","linktree"
    ]}
}
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID         = os.getenv("TELEGRAM_CHAT_ID")

w3 = Web3(Web3.HTTPProvider(os.getenv("HYPER_RPC","https://rpc.hyperliquid.xyz/evm")))
DEX_URL = "https://api.dexscreener.com/latest/dex/pairs/{chain}/{pair}".format(
    chain=os.getenv("CHAIN_ID","256"), pair=CONFIG["PAIR_ADDRESS"]
)

# ——— HELPERS ———

def main_menu():
    buttons = [
        [InlineKeyboardButton("Set Pair Address", callback_data="BTN_SET_PAIR")],
        [InlineKeyboardButton("Set Emoji Step", callback_data="BTN_SET_STEP")],
        [InlineKeyboardButton("Set Media", callback_data="BTN_SET_MEDIA")],
        [InlineKeyboardButton("Social Links", callback_data="BTN_SHOW_SOCIAL")],
        [InlineKeyboardButton("Show Config", callback_data="BTN_SHOW_CONFIG")],
        [InlineKeyboardButton("Start Monitor", callback_data="BTN_START")],
        [InlineKeyboardButton("Stop Monitor", callback_data="BTN_STOP")],
        [InlineKeyboardButton("Help", callback_data="BTN_HELP")],
    ]
    return InlineKeyboardMarkup(buttons)

async def send_menu(update_or_query, context):
    """Send or update the main menu."""
    if isinstance(update_or_query, Update) and update_or_query.callback_query is None:
        await update_or_query.message.reply_text("⚙️ *Main Menu*", 
            reply_markup=main_menu(), parse_mode="Markdown")
    else:
        cq = update_or_query.callback_query
        await cq.answer()
        await cq.edit_message_text("⚙️ *Main Menu*", 
            reply_markup=main_menu(), parse_mode="Markdown")

# ——— CONVERSATION STATE FLAG ———
# We'll use context.user_data["expecting"] to know what input we want next.

# ——— CALLBACK QUERY HANDLER ———
async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cq = update.callback_query
    data = cq.data
    await cq.answer()

    # reset any awaiting state
    context.user_data.pop("expecting", None)

    if data == "BTN_SET_PAIR":
        context.user_data["expecting"] = "PAIR"
        await cq.message.reply_text("🔹 Please send the token *pair contract address* now.", parse_mode="Markdown")
    elif data == "BTN_SET_STEP":
        context.user_data["expecting"] = "STEP"
        await cq.message.reply_text(
            "🔹 Please send the *USD per emoji* (e.g. `1` means $1 = 1 emoji).", 
            parse_mode="Markdown"
        )
    elif data == "BTN_SET_MEDIA":
        context.user_data["expecting"] = "MEDIA"
        await cq.message.reply_text(
            "🔹 Send me a *URL* or *upload* a GIF/photo/video, or type `none` to clear.", 
            parse_mode="Markdown"
        )
    elif data == "BTN_SHOW_SOCIAL":
        text = "🔗 *Social Links:*\\n"
        for p,v in CONFIG["SOCIAL_LINKS"].items():
            text += f"- *{p.title()}:* {v or '_Not set_'}\\n"
        await cq.message.reply_markdown(text)
    elif data == "BTN_SHOW_CONFIG":
        conf = CONFIG.copy()
        conf["PAIR_ADDRESS"] = conf["PAIR_ADDRESS"] or "_Not set_"
        await cq.message.reply_text("📋 Current Config:\\n" + json.dumps(conf, indent=2))
    elif data == "BTN_START":
        await cq.message.reply_text("✅ Monitoring started (use `/stopmonitor` to stop).")
        # hook into your existing startmonitor logic here...
    elif data == "BTN_STOP":
        await cq.message.reply_text("🛑 Monitoring stopped.")
        # hook into your existing stopmonitor logic...
    elif data == "BTN_HELP":
        await cq.message.reply_markdown(
            "🛠 *CHAM Buy Bot Help*\\n"
            "Use the buttons to configure and control the bot.\\n"
            "After each prompt, send the required data."
        )
    # finally re-show menu
    await send_menu(update, context)

# ——— MESSAGE HANDLER FOR USER RESPONSES ———
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
        except:
            return await update.message.reply_text("❌ Invalid number, please send again.")
    elif expect == "MEDIA":
        if text.lower() == "none":
            CONFIG["MEDIA_URL"] = ""
            CONFIG["MEDIA_FILE_ID"] = ""
            await update.message.reply_text("✅ Media cleared.")
        else:
            CONFIG["MEDIA_URL"] = text
            CONFIG["MEDIA_FILE_ID"] = ""
            await update.message.reply_text(f"✅ Media URL set to {text}")
    else:
        return  # ignore other messages

    # clear state and re-show menu
    context.user_data.pop("expecting", None)
    await send_menu(update, context)

# ——— SETUP & RUN ———
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # /start just shows the menu
    app.add_handler(CommandHandler("start", send_menu))
    # button presses
    app.add_handler(CallbackQueryHandler(button_router))
    # capture the next text reply for any prompt
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    app.run_polling()

if __name__ == "__main__":
    main()
