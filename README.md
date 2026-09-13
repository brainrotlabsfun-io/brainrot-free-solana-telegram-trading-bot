# Telegram Solana Trading Bot

An open-source, modular Telegram bot for the Solana ecosystem — token sniping,
copy trading, automated exits, wallet tracking, community raids, and a
referral system. Built with [aiogram 3](https://docs.aiogram.dev/) and SQLite.

This repository ships **no credentials of any kind**. Every wallet, token,
API key, and admin ID is read from your own `.env` file. Out of the box the
bot runs against the free public Solana RPC with all paid and token-gated
features switched off until you configure them.

---

## Quick start

**New to this? Don't run anything yet.** See **[START_HERE.md](START_HERE.md)** —
paste one prompt into Claude Code and it will walk you through creating your
bot with @BotFather and configuring everything, step by step.

Prefer to do it by hand? Follow **[SETUP.md](SETUP.md)**.

The short version, for people who've done this before:

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git
cd YOUR_REPO
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

**Optional** — each of these disables a feature while blank, rather than
falling back to anyone else's value:

- `BOT_USERNAME`, `BRAND_HANDLE`, `TOKEN_NAME`, `SHARE_HASHTAG`,
  `DISCORD_URL`, `TWITTER_URL`, `WEBSITE_URL` — branding and share buttons.
- `BRAINROT_MINT` — your SPL token mint; enables token-gating and burn tiers.
- `PAYMENT_WALLET` — the SOL address that receives payments. **Must be yours.**
- `PAYMENT_WALLET_PRIVATE_KEY` — only needed for automatic affiliate payouts.

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
| Alpha Network | Referral/affiliate signups with SOL payouts |
| Token gating | Optional premium tiers unlocked by holding or burning your token |

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
- **`PAYMENT_WALLET` must be an address you control.** If you leave it blank,
  payment flows stay disabled instead of sending funds somewhere unintended.
- **If a secret ever reaches a public repo, rotate it immediately** — revoke
  the bot token with @BotFather, roll the RPC key, and move any funds. Deleting
  the commit is not enough; assume it was scraped within minutes.
- Use a dedicated hot wallet with a limited balance for
  `PAYMENT_WALLET_PRIVATE_KEY`. Never your main wallet.

## Disclaimer

This software is provided as-is, for educational purposes. Automated trading
of volatile assets carries a real risk of total loss. You are solely
responsible for the funds, keys, and users of any instance you operate, and
for complying with the laws and financial regulations that apply to you.
Nothing here is financial advice.

## License

MIT — see [LICENSE](LICENSE).
