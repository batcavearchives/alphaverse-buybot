# CHAM Buy Tracker Bot

A step-by-step Telegram bot to announce CHAM token buys with emoji, media, and social link options!

## Features
- Interactive setup: contract address, emoji logic, media, social links
- Supports uploaded GIFs/photos, or media URLs
- Buy alerts formatted like:
  ```
  CHAM Buy!
  🦎🦎🦎
  💵 0.24 HYPE ($11.33)
  💰 100.66K CHAM
  0x28...6f7F: (https://hyperevmscan.io/address/...) +50.0% | Txn (...)
  Price: $0.0₅238
  Liquidity: $67.72K
  MCap: $112.25K
  HYPE Price: $47.22
  ```

## Setup

1. Clone/download and fill out `.env` based on `.env.example`
2. Install requirements: `pip install -r requirements.txt`
3. Start with: `python cham_buy_tracker.py`
4. Deploy to Railway: push to GitHub, add Railway project, set secrets for your env.

## Usage

- `/start` — guided setup
- `/setpair <contract>` — set pool contract address
- `/setstep <usd>` — set USD value per emoji
- `/setmedia <url>` or upload a GIF/image/video
- `/setsocial <platform> <url>` — set social links
- `/showsocial` — show social links
- `/startmonitor` — start tracking buys
- `/stopmonitor` — stop
