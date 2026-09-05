# Patente Analytics

A tiny, privacy-friendly analytics + Telegram notification service for the
**Patente B** web app. It tracks how many people use the app (active users now,
totals, daily counts) and sends you a Telegram message when sessions start.

It runs on a **Raspberry Pi** at home, exposed to the internet through a
**Cloudflare Tunnel** — no open ports, no exposed home IP, free HTTPS.

---

## Table of Contents

1. [How it all fits together](#how-it-all-fits-together)
2. [The players: Aruba, Cloudflare, Render, the Pi](#the-players)
3. [Data flow (what happens when a user opens the app)](#data-flow)
4. [Environment variables explained](#environment-variables-explained)
5. [Endpoints](#endpoints)
6. [Setup from scratch](#setup-from-scratch)
7. [Cloudflare Tunnel setup (the permanent URL)](#cloudflare-tunnel-setup)
8. [Connecting the Vue app](#connecting-the-vue-app)
9. [Operations: logs, updates, troubleshooting](#operations)

---

## How it all fits together

```
   Browser (user)                   Cloudflare                 Raspberry Pi (home)
 ┌───────────────┐   HTTPS event   ┌────────────┐   tunnel    ┌──────────────────┐
 │  Patente app  │ ──────────────► │  Cloudflare│ ──────────► │  cloudflared      │
 │  (on Render)  │                 │   network  │             │      │            │
 └───────────────┘                 └────────────┘             │      ▼            │
                                                               │  uvicorn :8000    │
                                                               │  (FastAPI app)    │
                                                               │      │            │
                                                               │      ├─► SQLite   │
                                                               │      └─► Telegram ─┼──► your phone
                                                               └──────────────────┘
```

Key idea: **the Pi never opens a port to the internet.** Instead, a small
program on the Pi (`cloudflared`) makes an _outbound_ connection to Cloudflare.
When a browser hits `https://analytics.patentechi.it`, Cloudflare pushes that
request back down the tunnel to the Pi. Secure, and works behind home NAT.

---

## The players

| Service          | Role             | What we use it for                                                                                   |
| ---------------- | ---------------- | ---------------------------------------------------------------------------------------------------- |
| **Aruba**        | Domain registrar | We bought `patentechi.it` here. It only holds the registration — the DNS is delegated to Cloudflare. |
| **Cloudflare**   | DNS + Tunnel     | Manages DNS for `patentechi.it` and provides the secure tunnel to the Pi. Free plan.                 |
| **Render**       | App hosting      | Hosts the Patente Vue app (the frontend users load).                                                 |
| **Raspberry Pi** | Analytics server | Runs the FastAPI service, SQLite DB, and sends Telegram notifications. Lives at home.                |
| **Telegram**     | Notifications    | A bot messages you when sessions happen.                                                             |

### Why the domain is at Aruba but DNS is at Cloudflare

- Cloudflare **cannot sell** `.it` domains, so we bought it at **Aruba**.
- But Cloudflare **can host the DNS** for an existing `.it` domain.
- So at Aruba we changed the **nameservers** from Aruba's to Cloudflare's:
  ```
  corey.ns.cloudflare.com
  fiona.ns.cloudflare.com
  ```
- Now Cloudflare answers all DNS queries for `patentechi.it`. Aruba just keeps
  the registration alive (renewal, ownership).

### The subdomains

| Hostname                              | Points to                  | Purpose                |
| ------------------------------------- | -------------------------- | ---------------------- |
| `patentechi.it` / `www.patentechi.it` | Render                     | The Patente web app    |
| `analytics.patentechi.it`             | Pi (via Cloudflare Tunnel) | This analytics service |

---

## Data flow

What happens when someone opens the Patente app:

1. The browser loads the Vue app from Render.
2. `src/lib/analytics.ts` runs `initAnalytics()` and generates:
   - a random **device ID** (stored in `localStorage`, persists across visits)
   - a random **session ID** (new each visit)
3. It POSTs a `session_start` event to
   `https://analytics.patentechi.it/event`. CORS restricts which sites may call it.
4. Cloudflare relays it through the tunnel to the Pi's FastAPI service.
5. FastAPI records the session in SQLite and (respecting a cooldown) sends you a
   Telegram message.
6. Every 30s while the tab is open, the browser sends a `heartbeat` to keep the
   session "active".
7. When the tab closes, the browser sends `session_end` (via `navigator.sendBeacon`).
8. A background task on the Pi also expires sessions that stop sending heartbeats
   (e.g. the browser crashed) after `SESSION_TIMEOUT_SECONDS`.

"Active users" = distinct devices seen within the last `SESSION_TIMEOUT_SECONDS`.

---

## Environment variables explained

There are **two separate `.env` files** in two different places. Do not confuse them.

### 1. Backend `.env` — on the Raspberry Pi ONLY

Location: `~/patente-analytics/.env` on the Pi.
**Gitignored — never committed.** Contains the real secret (Telegram token).

| Variable                  | Meaning                                                                                                                              | Example                 |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | ----------------------- |
| `TELEGRAM_BOT_TOKEN`      | **REAL SECRET.** Token from @BotFather. Lets the server send messages as your bot. Lives only on the Pi — the browser never sees it. | `8970...:AAH...`        |
| `TELEGRAM_CHAT_ID`        | Your Telegram chat ID (where messages go).                                                                                           | `255859351`             |
| `ALLOWED_ORIGINS`         | Comma-separated allowed browser origins (CORS). Limits which websites are allowed to call the API.                                   | `https://patentechi.it` |
| `NOTIFY_COOLDOWN_SECONDS` | Min seconds between "new session" Telegram pings (batches to avoid spam). `0` = every session.                                       | `300`                   |
| `NOTIFY_ON_SESSION_END`   | Also notify when a session ends?                                                                                                     | `false`                 |
| `SESSION_TIMEOUT_SECONDS` | A session counts as "active" if seen within this window.                                                                             | `90`                    |
| `HOST` / `PORT`           | Where uvicorn binds (kept local; the tunnel reaches it).                                                                             | `127.0.0.1` / `8000`    |
| `DB_PATH`                 | SQLite file path.                                                                                                                    | `data/analytics.db`     |

### 2. Frontend `.env.production` — in the Patente_UI repo

Location: `Patente_UI/.env.production`.
Read by Vite **at build time** and baked into the browser bundle.

| Variable             | Meaning                                                                                | Example                           |
| -------------------- | -------------------------------------------------------------------------------------- | --------------------------------- |
| `VITE_ANALYTICS_URL` | Where the app sends events. The tunnel URL. Leave empty to disable analytics entirely. | `https://analytics.patentechi.it` |

> There is no client secret. Because any `VITE_` value ships to the browser, it
> can't be kept secret anyway. Instead, abuse is limited by **CORS**
> (`ALLOWED_ORIGINS`), which restricts which websites may call the API. The only
> real secret in the whole system is the **Telegram bot token**, which lives
> solely on the Pi and is never exposed to the browser.

---

## Endpoints

| Method | Path      | Purpose                                              |
| ------ | --------- | ---------------------------------------------------- |
| `POST` | `/event`  | Ingest `session_start` / `heartbeat` / `session_end` |
| `GET`  | `/stats`  | Active users, totals, today's counts                 |
| `GET`  | `/health` | Health check                                         |

Example:

```bash
curl https://analytics.patentechi.it/stats
curl https://analytics.patentechi.it/health
```

---

## Setup from scratch

### Prerequisites

- A Raspberry Pi reachable over SSH (Debian-based)
- Python 3.11+
- A Telegram bot (see below)

### 1. Clone and install on the Pi

```bash
ssh keivan@<pi-ip>
git clone https://github.com/keivan-ardam/patente-analytics.git
cd patente-analytics
bash scripts/setup_pi.sh
```

`setup_pi.sh` creates a virtualenv, installs dependencies, creates `.env` from
the template, and installs + starts the systemd service.

### 2. Create the Telegram bot

1. In Telegram, message **@BotFather** → `/newbot` → follow prompts.
2. Copy the **token** → put in `.env` as `TELEGRAM_BOT_TOKEN`.
3. Send your new bot any message.
4. Find your chat ID:
   ```bash
   curl "https://api.telegram.org/bot<TOKEN>/getUpdates"
   ```
   Look for `"chat":{"id":123456789}` → that's `TELEGRAM_CHAT_ID`.

### 3. Fill in `.env` and restart

```bash
nano ~/patente-analytics/.env      # set TELEGRAM_*, ALLOWED_ORIGINS
sudo systemctl restart patente-analytics
curl http://127.0.0.1:8000/health  # {"status":"ok"}
```

---

## Cloudflare Tunnel setup

This gives you the permanent `https://analytics.patentechi.it` URL.

### Prerequisite: domain on Cloudflare

- Domain bought at **Aruba** (`patentechi.it`).
- Added to Cloudflare (free plan) → Cloudflare gives 2 nameservers.
- At Aruba, nameservers switched to Cloudflare's (`corey`/`fiona.ns.cloudflare.com`).
- Wait until Cloudflare shows the domain as **Active**.

### Install cloudflared on the Pi (ARM64)

```bash
curl -L -o cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64
chmod +x cloudflared
sudo mv cloudflared /usr/local/bin/
```

### Authorize + create the named tunnel

```bash
cloudflared tunnel login                        # opens a browser; authorize patentechi.it
cloudflared tunnel create patente-analytics     # creates tunnel + credentials json
cloudflared tunnel route dns patente-analytics analytics.patentechi.it
```

### Config file `~/.cloudflared/config.yml`

```yaml
tunnel: patente-analytics
credentials-file: /home/keivan/.cloudflared/<TUNNEL_ID>.json

ingress:
  - hostname: analytics.patentechi.it
    service: http://127.0.0.1:8000
  - service: http_status:404
```

### Run it as a service (survives reboots)

```bash
sudo cloudflared service install
sudo systemctl enable cloudflared
sudo systemctl start cloudflared
```

Now `https://analytics.patentechi.it` permanently points to the Pi, survives
reboots, and has automatic HTTPS.

> **Quick tunnel alternative (testing only):**
> `cloudflared tunnel --url http://127.0.0.1:8000` gives an instant
> `https://<random>.trycloudflare.com` URL — but it changes on every restart.
> Use only for testing.

---

## Connecting the Vue app

In `Patente_UI/.env.production`:

```
VITE_ANALYTICS_URL=https://analytics.patentechi.it
```

`src/lib/analytics.ts` is already wired into `main.ts`. If `VITE_ANALYTICS_URL`
is empty, analytics is a silent no-op (safe for local dev).

Commit + push → Render rebuilds → analytics live.

> The API is protected by CORS (`ALLOWED_ORIGINS` on the Pi), so only your app's
> domain can send events from a browser.

---

## Operations

### Logs

```bash
sudo journalctl -u patente-analytics -f     # FastAPI app logs
sudo journalctl -u cloudflared -f           # tunnel logs
```

### Update after code changes

```bash
ssh keivan@<pi-ip>
cd patente-analytics
bash scripts/deploy.sh        # git pull + reinstall deps + restart
```

### Check stats manually

```bash
curl https://analytics.patentechi.it/stats
```

### Service management

```bash
sudo systemctl status patente-analytics
sudo systemctl restart patente-analytics
sudo systemctl restart cloudflared
```

### Common issues

| Symptom                  | Likely cause                                  | Fix                                            |
| ------------------------ | --------------------------------------------- | ---------------------------------------------- |
| No Telegram messages     | Wrong token/chat ID, or cooldown active       | Check `.env`, check logs for `sendMessage` 200 |
| Events not arriving      | Tunnel down, or wrong `VITE_ANALYTICS_URL`    | `systemctl status cloudflared`; verify URL     |
| CORS error in browser    | `ALLOWED_ORIGINS` doesn't include the app URL | Add app origin to `.env`, restart              |
| URL changed after reboot | Using a quick tunnel                          | Use a **named** tunnel (see above)             |

### Reset analytics data

```bash
rm ~/patente-analytics/data/analytics.db
sudo systemctl restart patente-analytics
```

---

## Privacy

- Only an anonymous random device ID is stored — **no names, emails, or IPs**
  are persisted (Cloudflare's country header is optional metadata).
- Suitable for a GDPR-conscious EU app: no personal data, no third-party trackers.
