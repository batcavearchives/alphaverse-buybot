#!/usr/bin/env python3
import os
import asyncio
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes
)
from web3 import Web3
import aiohttp

# ─── Configuration ─────────────────────────────────────────────────────────────
TOKEN       = os.getenv("TELEGRAM_BOT_TOKEN")      # your bot token
CHAT_ID     = os.getenv("TELEGRAM_CHAT_ID")        # where to post alerts
RPC_URL     = os.getenv("RPC_URL", "https://rpc.hyperliquid.xyz/evm")
CHAIN_ID    = int(os.getenv("CHAIN_ID", "256"))
EMOJI       = os.getenv("EMOJI", "🦎")
STEP_USD    = float(os.getenv("EMOJI_STEP_USD", "1"))  # $ per emoji
PAIR_ADDRESS = ""  # will be set via /setpair

if not TOKEN or not CHAT_ID:
    raise RuntimeError("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in environment")

w3 = Web3(Web3.HTTPProvider(RPC_URL))
DEX_API = "https://api.dexscreener.com/latest/dex/pairs/{chain}/{pair}"

monitor_job = None  # handle for the scheduled job

# ─── Helper Functions ──────────────────────────────────────────────────────────
def render_emojis(usd: float) -> str:
    count = int(usd // STEP_USD)
    return EMOJI * min(count, 50)

async def fetch_pair_stats():
    url = DEX_API.format(chain=CHAIN_ID, pair=PAIR_ADDRESS)
    async with aiohttp.ClientSession() as s:
        async with s.get(url) as resp:
            data = await resp.json()
    p = data.get("pair", {})
    return {
        "price":      float(p.get("priceUsd", 0)),
        "hype_price": float(p.get("token0", {}).get("priceUsd", 0)),
        "change24h":  float(p.get("priceChange24h", 0)),
    }

# ─── Command Handlers ──────────────────────────────────────────────────────────
async def start_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *BuyBot*\n"
        "Use `/setpair <address>` to specify the CHAM pool contract."
    , parse_mode="Markdown")

async def setpair_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global PAIR_ADDRESS
    if not ctx.args:
        return await update.message.reply_text("Usage: /setpair <contract_address>")
    PAIR_ADDRESS = ctx.args[0].lower()
    await update.message.reply_text(f"✅ Pair address set to `{PAIR_ADDRESS}`", parse_mode="Markdown")

async def startmonitor_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global monitor_job
    if not PAIR_ADDRESS:
        return await update.message.reply_text("⚠️ Set the pair first: `/setpair <address>`")
    if monitor_job:
        return await update.message.reply_text("⚠️ Already monitoring.")
    monitor_job = ctx.application.job_queue.run_repeating(
        monitor_loop, interval=5, first=0, chat_id=update.effective_chat.id
    )
    await update.message.reply_text("✅ Monitoring started — scanning every 5 s.")

async def stopmonitor_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global monitor_job
    if monitor_job:
        monitor_job.schedule_removal()
        monitor_job = None
        await update.message.reply_text("🛑 Monitoring stopped.")
    else:
        await update.message.reply_text("⚠️ Not currently monitoring.")

# ─── Monitoring Loop ──────────────────────────────────────────────────────────
async def monitor_loop(ctx: ContextTypes.DEFAULT_TYPE):
    stats = await fetch_pair_stats()
    block = w3.eth.get_block("latest", full_transactions=True)
    for tx in block.transactions:
        receipt = w3.eth.get_transaction_receipt(tx.hash)
        for log in receipt.logs:
            if log.address.lower() != PAIR_ADDRESS:
                continue
            # decode amounts: [amt0In, amt1In, amt0Out, amt1Out]
            try:
                a0_in, a1_in, a0_out, a1_out = w3.codec.decode(
                    ['uint256']*4, log.data
                )
            except:
                continue
            # assume CHAM is token1 in the pool:
            # adjust if needed for your pair
            hype_in = w3.from_wei(a0_in, 'ether')
            cham_out = w3.from_wei(a1_out, 'ether')
            if cham_out <= 0:
                continue
            usd_cost = hype_in * stats["hype_price"]
            buyer = w3.to_checksum_address("0x" + log.topics[2].hex()[26:])
            short = buyer[:6] + "..." + buyer[-4:]
            # build message
            msg = "\n".join([
                "CHAM Buy!",
                "",
                render_emojis(usd_cost),
                "",
                f"💵 {hype_in:.2f} HYPE (${usd_cost:.2f})",
                f"💰 {cham_out:,.2f} CHAM",
                "",
                f"{short}: (https://hyperevmscan.io/address/{buyer}) "
                f"+{stats['change24h']:.1f}% | "
                f"Txn (https://hyperevmscan.io/tx/{tx.hash.hex()})",
                f"Price: ${stats['price']:.6f}",
                f"HYPE Price: ${stats['hype_price']:.4f}"
            ])
            await ctx.bot.send_message(chat_id=ctx.job.chat_id, text=msg)

# ─── Main Entrypoint ───────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("setpair", setpair_cmd))
    app.add_handler(CommandHandler("startmonitor", startmonitor_cmd))
    app.add_handler(CommandHandler("stopmonitor", stopmonitor_cmd))
    app.run_polling()

if __name__ == "__main__":
    main()
