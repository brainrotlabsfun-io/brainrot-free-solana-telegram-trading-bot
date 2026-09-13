# Start here

You don't need to understand any of this code to run your own bot.

Below is a single prompt. Copy it, paste it into **Claude Code** inside this
folder, and Claude will walk you through the whole thing — creating your bot
with @BotFather on Telegram, generating your own keys, writing your config
file, and starting it up. It asks you one question at a time and waits.

**Don't have Claude Code?** Install it from
[claude.com/claude-code](https://claude.com/claude-code), then run `claude`
in this folder. Or skip all of this and follow [SETUP.md](SETUP.md) by hand.

> **Already inside Claude Code?** Just type `/setup-bot` — the same guide is
> installed as a slash command in this repo. The prompt below is for anyone
> who'd rather paste it in manually.

---

## Copy everything in the box below

```text
I want to set up my own Telegram trading bot from this repository. I'm
starting from scratch and I want you to guide me through it interactively.

How I want you to work with me:

- Walk me through ONE step at a time. Ask a question, then STOP and wait for
  my answer. Do not dump every step at once.
- Assume I've never created a Telegram bot before. Tell me exactly what to
  tap and type, including which app to open.
- Before each command, say what it does and what I should expect to see.
- Run the commands for me where you can, rather than asking me to run them.
- If something errors, diagnose it and fix it — don't hand me a wall of text.
- Use the right commands for my operating system. Check first if unsure.

Security rules you must follow:

- NEVER ask me to paste my bot token or any private key into this chat.
  When I have a secret, tell me to put it directly into the .env file
  myself, or write it to .env for me only if I explicitly choose that.
- Generate my encryption key locally with the cryptography library. Never
  reuse a key from this repo's history, its docs, or anywhere else.
- Before we finish, confirm .env is gitignored and will not be committed.
- Warn me clearly about anything that risks real money.

Here's the path I want, in order:

1. Check my setup — confirm Python 3.11+ is installed and tell me how to fix
   it if not. Check whether I'm in the right folder.

2. Create the bot on Telegram — walk me through opening Telegram, finding
   @BotFather, sending /newbot, choosing a display name, and choosing a
   username ending in "bot". Explain what to do if the username is taken.
   Tell me where BotFather's reply puts the token, and to keep it private.

3. Set up the Python environment — create a virtual environment, activate it,
   and install everything in requirements.txt.

4. Generate my wallet encryption key — explain what it protects, generate a
   fresh one, and tell me to back it up somewhere safe outside this folder.
   Make sure I understand that losing or changing it makes every wallet the
   bot creates permanently unreadable.

5. Build my .env — copy .env.example to .env, then help me fill in BOT_TOKEN
   and WALLET_ENCRYPTION_KEY. Leave everything else at its default for now.
   Confirm the file is in the right place and named exactly ".env".

6. First run — start the bot, read the logs with me, and explain that
   warnings about unconfigured optional features are normal. Then have me
   message my bot on Telegram and send /start to confirm it replies.

7. Make me admin — have me send /myid to the bot, then add that number to
   ADMIN_IDS in .env and restart.

8. Upgrade my RPC — explain why the free public Solana endpoint causes
   failed trades and zero balances, walk me through getting a free Helius
   API key, and add my own URL to .env.

9. Wrap up — show me how to start and stop the bot, point me at DEPLOY.md
   for keeping it online 24/7, and list the optional branding settings in
   .env.example I might want later.
   Remind me which files must never be committed.

Start with step 1 now. Just step 1.
```

---

## After it's running

- [SETUP.md](SETUP.md) — the same steps written out, plus troubleshooting.
- [DEPLOY.md](DEPLOY.md) — keeping the bot online when your computer is off.
- [.env.example](.env.example) — every setting, annotated.
- [README.md](README.md) — what each module does, and the security rules.

## A word of warning

This bot can execute real trades with real money. Start with small amounts
you can afford to lose entirely, and make sure you understand what a feature
does before you turn it on.
