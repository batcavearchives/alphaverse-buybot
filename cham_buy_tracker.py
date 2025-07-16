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
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

w3 = Web3(Web3.HTTPProvider(os.getenv("HYPER_RPC", "https://rpc.hyperliquid.xyz/evm")))
DEX_URL_TEMPLATE = "https://api.dexscreener.com/latest/dex/pairs/{chain}/{pair}"

allowed_platforms = list(CONFIG["SOCIAL_LINKS"].keys())
monitoring_task = None

# ===== HELPERS =====
def main_menu():
    buttons = [
        [InlineKeyboardButton("Set Pair Address", callback_data="BTN_SET_PAIR")],
        [InlineKeyboardButton("Set Emoji Step", callback_data="BTN_SET_STEP")],
        [InlineKeyboardButton("Set Media", callback_data="BTN_SET_MEDIA")],
        [InlineKeyboardButton("Manage Social Links", callback_data="BTN_SOCIAL_MENU")],
        [InlineKeyboardButton("Show Config", callback_data="BTN_SHOW_CONFIG")],
        [InlineKeyboardButton("Start Monitor", callback_data="BTN_START")],
        [InlineKeyboardButton("Stop Monitor", callback_data="BTN_STOP")],
        [InlineKeyboardButton("Help", callback_data="BTN_HELP")],
    ]
    return InlineKeyboardMarkup(buttons)

def social_menu():
    # one button per platform, plus back
    buttons = [
        [InlineKeyboardButton(p.title(), callback_data=f"SOCIAL_{p}")]
        for p in allowed_platforms
    ] + [[InlineKeyboardButton("↩️ Back", callback_data="BTN_BACK")]]
    return InlineKeyboardMarkup(buttons)

async def send_menu(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    text = "⚙️ *Main Menu*"
    markup = main_menu()

    if hasattr(update_or_query, "callback_query") and update_or_query.callback_query:
        cq = update_or_query.callback_query
        await cq.answer()
        try:
            await cq.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                raise
    else:
        await update_or_query.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")


# ===== CALLBACK HANDLER =====
async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cq = update.callback_query
    data = cq.data
    await cq.answer()
    context.user_data.pop("expecting", None)

    if data == "BTN_SET_PAIR":
        context.user_data["expecting"] = "PAIR"
        await cq.message.reply_text(
            "🔹 Please send the token *pair contract address* now.",
            parse_mode="Markdown"
        )

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

    elif data == "BTN_SOCIAL_MENU":
        await cq.edit_message_text(
            "🔗 *Select platform to configure:*",
            reply_markup=social_menu(),
            parse_mode="Markdown"
        )
        return  # skip re-showing main menu here

    elif data.startswith("SOCIAL_"):
        platform = data.split("_", 1)[1]
        context.user_data["expecting"] = f"SOCIAL_{platform}"
        await cq.message.reply_text(
            f"🔹 Please send the URL for *{platform.title()}* link now.",
            parse_mode="Markdown"
        )

    elif data == "BTN_BACK":
        # go back to main menu
        await send_menu(update, context)
        return

    elif data == "BTN_SHOW_CONFIG":
        conf = CONFIG.copy()
        conf["PAIR_ADDRESS"] = conf["PAIR_ADDRESS"] or "_Not set_"
        await cq.message.reply_text("📋 Current Config:\n" + json.dumps(conf, indent=2))

    elif data == "BTN_START":
        await cq.message.reply_text("✅ Monitoring started (use the menu to stop).")
        # TODO: monitoring start logic

    elif data == "BTN_STOP":
        await cq.message.reply_text("🛑 Monitoring stopped.")
        # TODO: monitoring stop logic

    elif data == "BTN_HELP":
        await cq.message.reply_markdown(
            "🛠 *CHAM Buy Bot Help*\n"
            "Use the buttons to configure and control the bot.\n"
            "After each prompt, send the required data."
        )

    await send_menu(update, context)


# ===== MEDIA HANDLER =====
async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.animation:
        CONFIG["MEDIA_FILE_ID"] = msg.animation.file_id
        CONFIG["MEDIA_URL"] = ""
        await msg.reply_text("✅ Uploaded GIF set for alerts.")
    elif msg.photo:
        CONFIG["MEDIA_FILE_ID"] = msg.photo[-1].file_id
        CONFIG["MEDIA_URL"] = ""
        await msg.reply_text("✅ Uploaded photo set for alerts.")
    else:
        return
    context.user_data.pop("expecting", None)
    await send_menu(update, context)


# ===== TEXT HANDLER FOR RESPONSES =====
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

    elif expect and expect.startswith("SOCIAL_"):
        platform = expect.split("_", 1)[1]
        CONFIG["SOCIAL_LINKS"][platform] = text
        await update.message.reply_text(f"✅ {platform.title()} link set to {text}")

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
