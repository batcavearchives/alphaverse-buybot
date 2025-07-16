async def monitor_loop(context: ContextTypes.DEFAULT_TYPE):
    stats = await fetch_stats()
    block = w3.eth.get_block("latest", full_transactions=True)

    for tx in block.transactions:
        receipt = w3.eth.get_transaction_receipt(tx.hash)
        for log in receipt.logs:
            if log.address.lower() == CONFIG["PAIR_ADDRESS"].lower():
                # decode swap
                try:
                    amt0_in, _, _, amt1_out = w3.codec.decode(
                        ['uint256','uint256','uint256','uint256'], log.data
                    )
                except:
                    continue

                if amt1_out > 0:
                    # compute amounts
                    hype_amt = w3.from_wei(amt0_in, 'ether')
                    usd_cost = hype_amt * stats["hype_price"]
                    buyer   = w3.to_checksum_address("0x" + log.topics[2].hex()[26:])
                    cham_amt = w3.from_wei(amt1_out, 'ether')
                    pct      = stats.get("change24h", 0.0)

                    # build the core caption
                    caption = (
                        "CHAM Buy!\n\n"
                        f"{render_emojis(usd_cost)}\n\n"
                        f"💵 {hype_amt:.2f} HYPE (${usd_cost:.2f})\n"
                        f"💰 {fmt_k(cham_amt)} CHAM\n\n"
                        f"[{shorten(buyer)}](https://hyperevmscan.io/address/{buyer}) +{pct:.1f}% │ "
                        f"[Txn](https://hyperevmscan.io/tx/{tx.hash.hex()})\n"
                        f"Price: ${stats['price']:.6f}\n"
                        f"Liquidity: ${stats['liquidity']/1_000:,.2f}K\n"
                        f"MCap: ${stats['mcap']/1_000:,.2f}K\n"
                        f"HYPE Price: ${stats['hype_price']:.4f}"
                    )

                    # now append any social links
                    socials = []
                    for plat, url in CONFIG["SOCIAL_LINKS"].items():
                        if url:
                            label = "DexS" if plat == "dexscreener" else plat.title()
                            socials.append(f"[{label}]({url})")

                    if socials:
                        caption += "\n\n" + " │ ".join(socials)

                    # send media if configured
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

                    # finally send the text alert
                    await context.bot.send_message(
                        chat_id=context.job.chat_id,
                        text=caption,
                        parse_mode="Markdown",
                        disable_web_page_preview=True
                    )
