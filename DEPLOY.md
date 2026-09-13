# Deploying to a server

Running the bot on a VPS keeps it online when your computer is off.
Any provider works — Hetzner, DigitalOcean, Vultr, Oracle Cloud free tier.
A 1 GB RAM instance is plenty.

Replace `YOUR_SERVER_IP` and `youruser` throughout with your own values.

---

## 1. Connect

```bash
ssh youruser@YOUR_SERVER_IP
```

> Use SSH keys rather than passwords, and avoid logging in as `root`.
> Create a normal user with `sudo` instead.

## 2. Install dependencies

```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip git
```

## 3. Clone and set up

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git
cd YOUR_REPO
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 4. Configure

```bash
cp .env.example .env
nano .env
```

Fill in `BOT_TOKEN` and `WALLET_ENCRYPTION_KEY` at minimum.

> **Back up `WALLET_ENCRYPTION_KEY` somewhere safe.** If you move servers you
> must copy the exact same key, or every stored wallet becomes unreadable.

Lock the file down so other accounts on the box can't read it:

```bash
chmod 600 .env
```

## 5. Run it once to check

```bash
python main.py
```

Message your bot on Telegram. If it answers, stop it with `Ctrl+C` and
continue to the next step to keep it running permanently.

## 6. Run permanently with systemd

```bash
sudo nano /etc/systemd/system/mybot.service
```

```ini
[Unit]
Description=Telegram Trading Bot
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/home/youruser/YOUR_REPO
ExecStart=/home/youruser/YOUR_REPO/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mybot
```

## 7. Everyday commands

```bash
sudo systemctl status mybot        # is it running?
sudo systemctl restart mybot       # restart after a change
sudo journalctl -u mybot -f        # live logs
```

## 8. Deploying an update

```bash
cd ~/YOUR_REPO
git pull
source venv/bin/activate && pip install -r requirements.txt
sudo systemctl restart mybot
```

---

## Backups

The SQLite database holds user records and encrypted wallet keys.
Back it up regularly, and store it as securely as you store `.env`:

```bash
cp brainrot.db ~/backups/brainrot-$(date +%F).db
```
