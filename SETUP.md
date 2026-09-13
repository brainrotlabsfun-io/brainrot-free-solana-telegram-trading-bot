# Setup guide

Getting your own bot running, from nothing. No prior experience assumed.

If you'd rather have Claude Code walk you through this interactively,
see [START_HERE.md](START_HERE.md) instead.

**Time needed:** about 15 minutes.

---

## Step 1 — Create your bot on Telegram

1. Open Telegram (phone or desktop).
2. In the search bar, type **`@BotFather`** and open the account with the
   blue verified checkmark.
3. Tap **Start**.
4. Send: `/newbot`
5. BotFather asks for a **name** — this is the display name, e.g. `My Alpha Bot`.
   It can contain spaces.
6. BotFather asks for a **username** — this must be unique and **must end in
   `bot`**, e.g. `my_alpha_trading_bot`. If it's taken, try another.
7. BotFather replies with a message containing your token:

   ```
   Use this token to access the HTTP API:
   1234567890:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```

**Copy that token and keep it private.** Anyone who has it controls your bot.
Don't paste it into a chat, screenshot, or commit.

> Lost it later? Send `/mybots` to BotFather, pick your bot, then **API Token**.

While you're here, two optional but nice commands:

- `/setdescription` — the text people see before they hit Start.
- `/setuserpic` — your bot's avatar.

---

## Step 2 — Install Python

You need **Python 3.11 or newer**.

Check what you have:

```bash
python --version
```

If that errors or shows something older than 3.11, install it from
[python.org/downloads](https://www.python.org/downloads/).

> **Windows:** during installation, tick **"Add Python to PATH"** on the first
> screen. It's easy to miss and everything else depends on it.

---

## Step 3 — Get the code

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git
cd YOUR_REPO
```

No Git? Download the ZIP from the GitHub page, extract it, and `cd` into
the folder.

---

## Step 4 — Create a virtual environment

This keeps the bot's dependencies separate from the rest of your system.

**macOS / Linux**

```bash
python3 -m venv venv
source venv/bin/activate
```

**Windows (PowerShell)**

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
```

Your prompt should now start with `(venv)`. You need to run that `activate`
line again each time you open a new terminal.

Then install the dependencies:

```bash
pip install -r requirements.txt
```

---

## Step 5 — Create your encryption key

The bot can create a Solana wallet for each user, and it encrypts those
private keys before storing them. That needs a key of your own.

Run this and copy the output line:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

You'll get something like `kJ8xQ2mN...=`.

> **Save a backup somewhere safe, outside this folder.** If you lose this key
> or change it later, every wallet the bot has created becomes permanently
> unreadable. Never reuse a key from someone else's repo.

---

## Step 6 — Configure

Copy the template:

```bash
cp .env.example .env
```

(Windows PowerShell: `Copy-Item .env.example .env`)

Open `.env` in any text editor and fill in the two required values:

```
BOT_TOKEN=1234567890:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
WALLET_ENCRYPTION_KEY=kJ8xQ2mN...=
```

Save the file. That's enough to start.

`.env` is already gitignored, so it won't be committed — but it's worth
confirming with `git status` that it doesn't appear before you ever push.

---

## Step 7 — Run it

```bash
python main.py
```

You should see startup logs. Some warnings about unconfigured optional
features are expected and harmless.

Now open Telegram, search for the username you chose in Step 1, and send
`/start`. The bot should reply.

Stop it with `Ctrl+C`.

---

## Step 8 — Make yourself admin

With the bot running, send it `/myid`. It replies with your numeric Telegram
user ID. Put that in `.env`:

```
ADMIN_IDS=123456789
```

Restart the bot. You now have access to the admin commands.

---

## Step 9 — Upgrade your RPC (strongly recommended)

The default Solana endpoint is free but heavily rate-limited. Under load it
returns HTTP 429, which makes balance checks read as 0 and trades fail.

1. Sign up free at [helius.dev](https://helius.dev) — no card required.
2. Create an API key.
3. Put your own URL in `.env`:

```
SOLANA_RPC_URL=https://mainnet.helius-rpc.com/?api-key=YOUR_OWN_KEY_HERE
```

You can list several endpoints and the bot will rotate between them,
skipping any that rate-limit:

```
SOLANA_RPC_URLS=https://mainnet.helius-rpc.com/?api-key=YOUR_OWN_KEY,https://api.mainnet-beta.solana.com
```

---

## Step 10 — Optional extras

All optional, all branding. Each stays hidden while blank — nothing silently
falls back to another operator's settings.

**Branding and share buttons**

```
BOT_USERNAME=my_alpha_trading_bot
BRAND_HANDLE=@myproject
TOKEN_NAME=MYTOKEN
SHARE_HASHTAG=#myproject
WEBSITE_URL=https://example.com
DISCORD_URL=
TWITTER_URL=
```


## Keeping it online

`python main.py` only runs while your terminal is open. To keep the bot up
permanently, deploy it to a small server — see [DEPLOY.md](DEPLOY.md).

---

## Troubleshooting

**`BOT_TOKEN is missing`**
`.env` doesn't exist, or is in the wrong folder. It must sit next to
`main.py`. On Windows, make sure the file is `.env` and not `.env.txt`.

**`WALLET_ENCRYPTION_KEY is missing`**
Run the command in Step 5 and paste the output into `.env`.

**`Unauthorized` from Telegram**
The token is wrong or has been revoked. Get a fresh one from BotFather via
`/mybots`.

**`python: command not found`**
Try `python3` instead. On Windows, reinstall Python with "Add to PATH" ticked.

**`ModuleNotFoundError: No module named 'aiogram'`**
Your virtual environment isn't active, or dependencies aren't installed.
Re-run the activate line from Step 4, then `pip install -r requirements.txt`.

**Balances show 0, or trades keep failing**
You're being rate-limited by the public RPC. Do Step 9.

**The bot doesn't respond in Telegram**
Confirm `python main.py` is still running with no errors, and that you're
messaging the exact username from Step 1.
