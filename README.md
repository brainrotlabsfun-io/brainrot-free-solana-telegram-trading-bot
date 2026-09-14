# Telegram Solana Trading Bot

An open-source, modular Telegram bot for the Solana ecosystem — token sniping,
copy trading, automated exits, wallet tracking, community raids, and a
referral system. Built with [aiogram 3](https://docs.aiogram.dev/) and SQLite.

**Every feature is unlocked for every user.** There are no tiers, no premium
plans, no token gating, and no paywalls — whoever runs the bot decides how it
behaves through the in-bot settings and presets.

This repository also ships **no credentials of any kind**. Every wallet, API
key, and admin ID is read from your own `.env` file. Out of the box it runs
against the free public Solana RPC.

---

## Quick start

**New to this? Don't run anything yet.** See **[START_HERE.md](START_HERE.md)** —
paste one prompt into Claude Code and it will walk you through creating your
bot with @BotFather and configuring everything, step by step.

Prefer to do it by hand? Follow **[SETUP.md](SETUP.md)**.

The short version, for people who've done this before:

```bash
git clone https://github.com/brainrotlabsfun-io/brainrot-free-solana-telegram-trading-bot.git
cd brainrot-free-solana-telegram-trading-bot
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Then edit `.env` and set at minimum:

| Variable | How to get it |
|---|---|
| `BOT_TOKEN` | Message [@BotFather](https://t.me/BotFather) on Telegram, send `/newbot` |
| `WALLET_ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |

```bash
python main.py
```

The bot refuses to start if either value is missing, and tells you what to do.

---

## Configuration

Everything lives in `.env` — see [`.env.example`](.env.example) for the full
annotated list. Nothing else needs editing to run your own instance.

**Required**

- `BOT_TOKEN` — your bot's token from @BotFather.
- `WALLET_ENCRYPTION_KEY` — encrypts user wallet private keys at rest.
  Generate your own. Back it up. If it changes, existing wallets become
  permanently unreadable.

**Recommended**

- `SOLANA_RPC_URL` — the free public endpoint rate-limits hard, which makes
  balance checks return 0 and trades fail. A free [Helius](https://helius.dev)
  key fixes this. `SOLANA_RPC_URLS` takes a comma-separated list and rotates
  between them, skipping any that return 429.
- `ADMIN_IDS` — comma-separated Telegram user IDs that may run admin commands.
  Send `/myid` to your running bot to find yours. Blank means nobody is admin.

**Optional** — branding only. Each hides its button while blank, rather than
falling back to anyone else's value:

- `BOT_USERNAME`, `BRAND_HANDLE`, `TOKEN_NAME`, `SHARE_HASHTAG`,
  `DISCORD_URL`, `TWITTER_URL`, `WEBSITE_URL`.

---

## Project layout

```
main.py                  Entry point — registers routers, starts polling
requirements.txt         Python dependencies
.env.example             Annotated template for your own .env

bot/
  handlers/              One module per feature (sniper, copy trade, raids, …)
  keyboards/             Inline keyboard builders

services/                Business logic, on-chain calls, background workers
database/                SQLite schema and access layer
utils/
  config.py              Loads and validates .env — the single source of truth
```

## Features

| Module | What it does |
|---|---|
| Sniper | Monitors new token launches and auto-buys against your filters |
| Candle Sniper | Entry logic based on candle patterns |
| Copy Trade | Mirrors trades from wallets you follow |
| Auto Exit | Stop-loss, take-profit, and max-hold exits |
| Wallet Scout | Discovers and tracks wallet activity |
| Raid Hub | Community campaigns with points and a leaderboard |

---

## Support the project

This bot is free and MIT-licensed — you owe nothing to run it, fork it, or
ship your own version. If you want to support development anyway:

**Buy ~$20 of SOL, swap it for $BRAINROT, and burn it.**

```
$BRAINROT contract address (CA)
A9eR2GkTPEs3vbQjxMdkdvNJnWiKaBDq1Y9K5LEkpump
```

Verify the contract address against the official channels before you swap —
address spoofing is common. Crypto purchases carry risk, including total loss.
Not financial advice.

---

## Security

Read this before you deploy anything.

- **Never commit `.env`.** It is gitignored. Verify with `git status` before
  every push.
- **Never reuse someone else's `WALLET_ENCRYPTION_KEY`** — including any key
  you find in a tutorial, a fork, or this project's history. Generate a fresh
  one. This key decrypts every user wallet your bot creates.
- **The SQLite database is sensitive.** It holds encrypted wallet private keys
  and Telegram user records. `*.db` is gitignored — keep it that way, and
  protect your backups as carefully as your `.env`.
- **If a secret ever reaches a public repo, rotate it immediately** — revoke
  the bot token with @BotFather, roll the RPC key, and move any funds. Deleting
  the commit is not enough; assume it was scraped within minutes.
- **Anyone who can message your bot gets full access to every feature.** There
  is no tier system to limit them. If that matters, keep your bot private or
  add your own access check in `utils/admin.py`.

## Disclaimer

This software is provided as-is, for educational purposes. Automated trading
of volatile assets carries a real risk of total loss. You are solely
responsible for the funds, keys, and users of any instance you operate, and
for complying with the laws and financial regulations that apply to you.
Nothing here is financial advice.

## License

MIT — see [LICENSE](LICENSE). Free to use, modify, fork, and sell. The
support request in that file is voluntary and is not a condition of the license.
