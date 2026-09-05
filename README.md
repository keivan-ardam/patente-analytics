# Patente Analytics

A tiny, privacy-friendly analytics + Telegram notification service for the
**Patente B** web app. Runs on a Raspberry Pi behind a **Cloudflare Tunnel**
(no open ports, free HTTPS).

## What it does

- Tracks **active users** in real time (heartbeat-based)
- Counts **total unique users** and **sessions** (all-time + today)
- Sends **Telegram notifications** when sessions start (with anti-spam cooldown)
- Stores everything in **SQLite** — no external database
- Collects **only an anonymous random device ID** — no personal data

## Architecture

```
Browser (Vue app) ──POST /event──► Cloudflare Tunnel ──► uvicorn:8000 (FastAPI)
                                                              │
                                          ┌───────────────────┼───────────────────┐
                                          ▼                   ▼                   ▼
                                        SQLite          Telegram bot        /stats endpoint
```

- **FastAPI** app served by **uvicorn**, managed by **systemd** (auto-restart, starts on boot)
- **cloudflared** exposes it to the internet securely — no router config, no exposed ports
- No nginx, no Docker needed

## Endpoints

| Method | Path      | Purpose                                              |
| ------ | --------- | ---------------------------------------------------- |
| POST   | `/event`  | Ingest `session_start` / `heartbeat` / `session_end` |
| GET    | `/stats`  | Active users, totals, today's counts                 |
| GET    | `/health` | Health check                                         |

`/event` and `/stats` require the `X-Analytics-Secret` header (or `?s=` query param for `sendBeacon`).

---

## Part 1 — Deploy on the Raspberry Pi

### 1. Clone the repo on the Pi

```bash
ssh keivan@192.168.1.13
git clone https://github.com/keivan-ardam/patente-analytics.git
cd patente-analytics
```

### 2. Run the setup script

```bash
bash scripts/setup_pi.sh
```

This creates a virtualenv, installs dependencies, generates a random
`ANALYTICS_SECRET`, and installs + starts the systemd service.

### 3. Configure `.env`

Edit `.env` and fill in:

```bash
nano .env
```

- `TELEGRAM_BOT_TOKEN` — from @BotFather (see Part 3)
- `TELEGRAM_CHAT_ID` — your chat ID (see Part 3)
- `ALLOWED_ORIGINS` — your deployed Vue app URL (e.g. `https://patente.example.com`)
- `ANALYTICS_SECRET` — already generated; **copy it** for the frontend config

Then restart:

```bash
sudo systemctl restart patente-analytics
sudo systemctl status patente-analytics
curl http://127.0.0.1:8000/health   # should return {"status":"ok"}
```

---

## Part 2 — Cloudflare Tunnel (free, no domain required)

### Option A — Quick tunnel (instant, for testing)

Gives a random `https://xxxx.trycloudflare.com` URL that changes on restart.

```bash
# Install cloudflared (ARM64)
curl -L -o cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64
chmod +x cloudflared
sudo mv cloudflared /usr/local/bin/

# Start a quick tunnel to the FastAPI port
cloudflared tunnel --url http://127.0.0.1:8000
```

Copy the printed `https://....trycloudflare.com` URL — that's your analytics URL.

### Option B — Named tunnel (stable URL, survives reboots)

Requires a free Cloudflare account and a domain on Cloudflare. Recommended
for production.

```bash
cloudflared tunnel login                       # opens browser to authorize
cloudflared tunnel create patente-analytics    # creates a tunnel + credentials
cloudflared tunnel route dns patente-analytics analytics.yourdomain.com
```

Create `~/.cloudflared/config.yml`:

```yaml
tunnel: patente-analytics
credentials-file: /home/keivan/.cloudflared/<TUNNEL_ID>.json

ingress:
  - hostname: analytics.yourdomain.com
    service: http://127.0.0.1:8000
  - service: http_status:404
```

Install as a service so it starts on boot:

```bash
sudo cloudflared service install
sudo systemctl start cloudflared
sudo systemctl enable cloudflared
```

Your stable URL is now `https://analytics.yourdomain.com`.

> **No domain?** Free options that work with Cloudflare: register a free
> `.eu.org` domain (takes a few days), or use Option A for now and switch later.
> The only thing that changes is the URL in the frontend `.env`.

---

## Part 3 — Telegram bot

1. Open Telegram, message **@BotFather**, send `/newbot`, follow prompts.
2. Copy the **bot token** → `TELEGRAM_BOT_TOKEN` in `.env`.
3. Send any message to your new bot.
4. Get your chat ID:
   ```bash
   curl "https://api.telegram.org/bot<TOKEN>/getUpdates"
   ```
   Look for `"chat":{"id":123456789}` → that's `TELEGRAM_CHAT_ID`.
5. Restart the service: `sudo systemctl restart patente-analytics`.

Test it:

```bash
curl -X POST http://127.0.0.1:8000/event \
  -H "Content-Type: application/json" \
  -H "X-Analytics-Secret: <YOUR_SECRET>" \
  -d '{"type":"session_start","session_id":"testsession1","device_id":"testdevice1"}'
```

You should get a Telegram message.

---

## Part 4 — Connect the Vue app

In `Patente_UI/.env` (or `.env.production`):

```
VITE_ANALYTICS_URL=https://analytics.yourdomain.com
VITE_ANALYTICS_SECRET=<the ANALYTICS_SECRET from the Pi>
```

The `src/lib/analytics.ts` module is already wired into `main.ts`. If
`VITE_ANALYTICS_URL` is unset, analytics is a silent no-op — safe for local dev.

Rebuild and redeploy the Vue app.

---

## Updating the service later

```bash
ssh keivan@192.168.1.13
cd patente-analytics
bash scripts/deploy.sh   # git pull + reinstall deps + restart
```

## Notification tuning (`.env`)

- `NOTIFY_COOLDOWN_SECONDS=300` — batch new-session pings (0 = every session)
- `NOTIFY_ON_SESSION_END=false` — set `true` to also notify when sessions end
- `SESSION_TIMEOUT_SECONDS=90` — a session is "active" if seen within this window

## Logs & troubleshooting

```bash
sudo journalctl -u patente-analytics -f    # app logs
sudo journalctl -u cloudflared -f          # tunnel logs
curl http://127.0.0.1:8000/stats -H "X-Analytics-Secret: <SECRET>"
```
