---
description: Guide a new user through creating and running their own Telegram trading bot, starting from @BotFather
---

You are guiding someone through setting up their own instance of this
Telegram trading bot. Assume they have never created a Telegram bot before
and may not be comfortable with the command line.

## How to run this session

- Work through **one step at a time**. Ask, then stop and wait for their
  reply. Never dump the whole sequence at once.
- Tell them exactly what to tap and type, including which app to open.
- Say what each command does and what they should expect to see, then run it
  for them rather than asking them to run it themselves.
- Detect their OS and use the matching commands (`source venv/bin/activate`
  vs `venv\Scripts\Activate.ps1`, `cp` vs `Copy-Item`).
- When something fails, diagnose and fix it. Don't hand back raw tracebacks.
- Keep each step short. Confirm it worked before moving on.

## Security rules — non-negotiable

- **Never ask them to paste a bot token or private key into the chat.**
  Have them type secrets straight into `.env` themselves. Only write a secret
  to `.env` on their behalf if they explicitly ask you to.
- Generate the wallet encryption key locally with `cryptography`. Never reuse
  a key from this repo's history, its documentation, or any other source.
- Before finishing, verify `.env` is gitignored (`git check-ignore -v .env`)
  and does not appear in `git status`.
- Flag anything that risks real funds, plainly and without drama.

## The steps

**1. Environment check**
Confirm Python 3.11+ (`python --version`, falling back to `python3`). If it's
missing or old, point them at python.org and — on Windows — stress ticking
"Add Python to PATH". Confirm they're in the repo folder (`main.py` should be
present).

**2. Create the bot on Telegram**
Walk them through: open Telegram → search `@BotFather` (the verified one) →
Start → `/newbot` → a display name (spaces fine) → a username that is unique
and ends in `bot`. Explain what to do if the username is taken. Point out
where the token appears in BotFather's reply, and that it must stay private.
Mention `/mybots` → API Token for recovering it later.

**3. Python environment**
Create a venv, activate it, `pip install -r requirements.txt`. Explain that
the `(venv)` prefix means it's active, and that activation is needed again in
each new terminal.

**4. Wallet encryption key**
Explain that the bot creates a Solana wallet per user and encrypts those
private keys at rest. Generate one:

```
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Stress: back it up **outside this folder**; losing or changing it makes every
wallet the bot has created permanently unreadable.

**5. Build `.env`**
Copy `.env.example` to `.env`. Help them set `BOT_TOKEN` and
`WALLET_ENCRYPTION_KEY`, leaving everything else at defaults. Verify the file
sits beside `main.py` and is named exactly `.env` — on Windows, watch for a
hidden `.txt` extension.

**6. First run**
`python main.py`. Read the logs together. Explain that warnings about
unconfigured optional features (payments, token gating, branding) are
expected and mean those features are simply off. Have them message their bot
and send `/start` to confirm it replies. Then `Ctrl+C`.

**7. Admin access**
Have them send `/myid` to the bot, put the number in `ADMIN_IDS` in `.env`,
and restart. Explain that a blank `ADMIN_IDS` means nobody has admin rights.

**8. RPC upgrade**
Explain that the default public Solana endpoint rate-limits hard, which shows
up as zero balances and failed trades. Walk them through a free
[helius.dev](https://helius.dev) key and setting their own `SOLANA_RPC_URL`.
Mention `SOLANA_RPC_URLS` for rotating several endpoints.

**9. Wrap up**
Show them how to start and stop the bot. Point at `DEPLOY.md` for running it
24/7, and at `.env.example` for the optional settings they may want later —
branding, their own token mint, payments. Remind them that `.env` and `*.db`
must never be committed, and that `PAYMENT_WALLET` must be an address they
control.

---

Begin with step 1 now, and only step 1.
