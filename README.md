# Patente Analytics

A tiny, privacy-friendly analytics + Telegram notification service for the
**Patentechi** web app. It tracks how many people use the app (active users now,
totals, daily counts) and sends you a Telegram message when sessions start.

It runs on a **Raspberry Pi** at home, exposed to the internet through a
**Cloudflare Tunnel** — no open ports, no exposed home IP, free HTTPS,
permanent URL.

**Live URL:** `https://analytics.patentechi.it`

---

## Table of Contents

1. [How it all fits together](#how-it-all-fits-together)
2. [The players: Aruba, Cloudflare, Render, the Pi](#the-players)
3. [Data flow](#data-flow)
4. [Environment variables explained](#environment-variables-explained)
5. [Security model (CORS, secrets)](#security-model)
6. [Endpoints & API docs](#endpoints--api-docs)
7. [Telegram bot (notifications + buttons)](#telegram-bot)
8. [The Raspberry Pi: hardware & software](#the-raspberry-pi)
9. [Full setup from scratch](#full-setup-from-scratch)
10. [Cloudflare Tunnel setup (permanent URL)](#cloudflare-tunnel-setup)
11. [Connecting the Vue app](#connecting-the-vue-app)
12. [Operations: logs, updates, troubleshooting](#operations)
13. [Deployment log (what was actually done)](#deployment-log)

---

## How it all fits together

```
   Browser (user)                   Cloudflare                 Raspberry Pi (home)
 ┌───────────────┐   HTTPS event   ┌────────────┐   tunnel    ┌──────────────────┐
 │  Patentechi   │ ──────────────► │  Cloudflare│ ──────────► │  cloudflared      │
 │  (on Render)  │                 │   network  │             │      │            │
 └───────────────┘                 └────────────┘             │      ▼            │
                                                               │  uvicorn :8000    │
                                                               │  (FastAPI app)    │
                                                               │      │            │
                                                               │      ├─► SQLite   │
                                                               │      └─► Telegram ─┼──► your phone
                                                               └──────────────────┘
```

Key idea: **the Pi never opens a port to the internet.** A small program on the
Pi (`cloudflared`) makes an _outbound_ connection to Cloudflare. When a browser
hits `https://analytics.patentechi.it`, Cloudflare pushes that request back down
the tunnel to the Pi. Secure, and works behind home NAT with a dynamic IP.

---

## The players

| Service          | Role             | What we use it for                                                                            |
| ---------------- | ---------------- | --------------------------------------------------------------------------------------------- |
| **Aruba**        | Domain registrar | Bought `patentechi.it` here. Holds registration only — DNS is delegated to Cloudflare.        |
| **Cloudflare**   | DNS + Tunnel     | Manages DNS for `patentechi.it`, provides the secure tunnel to the Pi, issues SSL. Free plan. |
| **Render**       | App hosting      | Hosts the Patentechi Vue app (the frontend users load).                                       |
| **Raspberry Pi** | Analytics server | Runs the FastAPI service, SQLite DB, cloudflared tunnel, and Telegram bot. Lives at home.     |
| **Telegram**     | Notifications    | A bot messages you when sessions happen and answers button/command queries.                   |

### Why the domain is at Aruba but DNS is at Cloudflare

- Cloudflare **cannot register** `.it` domains, so we bought it at **Aruba**.
- Cloudflare **can host DNS** for an existing `.it` domain, though.
- At Aruba we changed the **nameservers** from Aruba's to Cloudflare's:
  ```
  corey.ns.cloudflare.com
  fiona.ns.cloudflare.com
  ```
- Now Cloudflare answers all DNS for `patentechi.it`. Aruba just keeps the
  registration alive (renewal, ownership).

### The subdomains

| Hostname                              | Points to                          | Cloudflare proxy    | Purpose                |
| ------------------------------------- | ---------------------------------- | ------------------- | ---------------------- |
| `patentechi.it` / `www.patentechi.it` | Render (`patentechi.onrender.com`) | **DNS only** (grey) | The Patentechi web app |
| `analytics.patentechi.it`             | Pi (via Cloudflare Tunnel)         | proxied by tunnel   | This analytics service |

> The Render records must be **DNS only (grey cloud)** — if proxied (orange),
> Render can't verify the domain or issue its SSL certificate.

---

## Data flow

What happens when someone opens the Patentechi app:

1. The browser loads the Vue app from Render.
2. `src/lib/analytics.ts` runs `initAnalytics()` and generates:
   - a random **device ID** (stored in `localStorage`, persists across visits)
   - a random **session ID** (new each visit)
3. It POSTs a `session_start` event to `https://analytics.patentechi.it/event`.
4. Cloudflare relays it through the tunnel to the Pi's FastAPI service.
5. FastAPI records the session in SQLite and (respecting a cooldown) sends you a
   Telegram message.
6. Every 30s while the tab is open, the browser sends a `heartbeat`.
7. When the tab closes, the browser sends `session_end` (via `navigator.sendBeacon`).
8. A background task on the Pi expires sessions that stop sending heartbeats
   after `SESSION_TIMEOUT_SECONDS`.

"Active users" = distinct devices seen within the last `SESSION_TIMEOUT_SECONDS`.

---

## Environment variables explained

Two separate `.env` files in two different places. Don't confuse them.

### 1. Backend `.env` — on the Raspberry Pi ONLY

Location: `~/patente-analytics/.env` on the Pi. **Gitignored — never committed.**

| Variable                  | Meaning                                                                 | Current value                                     |
| ------------------------- | ----------------------------------------------------------------------- | ------------------------------------------------- |
| `TELEGRAM_BOT_TOKEN`      | **REAL SECRET.** Token from @BotFather. Server-side only.               | `8970...` (secret)                                |
| `TELEGRAM_CHAT_ID`        | Your Telegram chat ID.                                                  | `255859351`                                       |
| `ALLOWED_ORIGINS`         | CORS allow-list. Which websites may call the API from a browser.        | `https://patentechi.it,https://www.patentechi.it` |
| `NOTIFY_COOLDOWN_SECONDS` | Min seconds between "new session" pings (batches). `0` = every session. | `300`                                             |
| `NOTIFY_ON_SESSION_END`   | Also notify on session end?                                             | `false`                                           |
| `SESSION_TIMEOUT_SECONDS` | Session is "active" if seen within this window.                         | `90`                                              |
| `HOST` / `PORT`           | uvicorn bind (local; tunnel reaches it).                                | `127.0.0.1` / `8000`                              |
| `DB_PATH`                 | SQLite file path.                                                       | `data/analytics.db`                               |

### 2. Frontend `.env.production` — in the Patentechi UI repo

Read by Vite **at build time**, baked into the browser bundle.

| Variable             | Meaning                                                 | Value                             |
| -------------------- | ------------------------------------------------------- | --------------------------------- |
| `VITE_ANALYTICS_URL` | Where the app sends events. Empty = analytics disabled. | `https://analytics.patentechi.it` |

There is **no client secret** — see the security model below.

---

## Security model

- **Real secret:** only the `TELEGRAM_BOT_TOKEN`, which lives solely on the Pi
  and never reaches the browser.
- **No client secret:** any `VITE_` value ships to the browser and can't be
  hidden. So instead of a fake "secret," the API is protected by **CORS**
  (`ALLOWED_ORIGINS`), which limits which websites can call `/event` from a
  browser to `patentechi.it` and `www.patentechi.it`.
- **No open ports:** the Pi is reachable only through the outbound Cloudflare
  tunnel — the home router has no port forwarding, and the home IP is hidden.
- **Anonymous data only:** a random device ID, no names/emails/IPs are stored.

> Note: CORS is a browser-enforced protection. A determined person using curl
> could still POST events. For anonymous usage analytics this is an acceptable
> trade-off — the worst case is an inflated visitor count, not a data breach.

---

## Endpoints & API docs

| Method | Path      | Purpose                                              |
| ------ | --------- | ---------------------------------------------------- |
| `POST` | `/event`  | Ingest `session_start` / `heartbeat` / `session_end` |
| `GET`  | `/stats`  | Active users, totals, today's counts                 |
| `GET`  | `/health` | Health check                                         |

Auto-generated interactive docs (FastAPI):

- **Swagger UI:** `https://analytics.patentechi.it/docs`
- **ReDoc:** `https://analytics.patentechi.it/redoc`
- **OpenAPI JSON:** `https://analytics.patentechi.it/openapi.json`

Examples:

```bash
curl https://analytics.patentechi.it/health
curl https://analytics.patentechi.it/stats
curl -X POST https://analytics.patentechi.it/event \
  -H "Content-Type: application/json" \
  -d '{"type":"session_start","session_id":"abc12345","device_id":"dev12345"}'
```

---

## Telegram bot

The bot both **sends** notifications and **responds** to button presses.

### Notifications

- On a new session (respecting `NOTIFY_COOLDOWN_SECONDS`), you get a message with
  active/today/total counts and an inline keyboard.

### Interactive buttons / commands

Send `/start` to the bot to get the menu. Buttons:

- **📊 Live Stats** — active now, today, totals
- **📅 Today** — new users today, sessions today, active now
- **📈 7-Day Report** — day-by-day breakdown + week total
- **🌍 Countries** — top countries by sessions

Implemented via long-polling (`getUpdates`) in a background task started by the
FastAPI lifespan hook. No webhook needed.

---

## The Raspberry Pi

### Hardware (as deployed)

- Raspberry Pi, **ARM64 (aarch64)**
- Debian 13 (trixie), 4 cores, 8 GB RAM
- On Wi-Fi (`wlan0`), local IP `192.168.1.13`
- Public IP (home): dynamic — irrelevant thanks to the tunnel

### Software running on the Pi

| Service             | What                                     | Managed by                         |
| ------------------- | ---------------------------------------- | ---------------------------------- |
| `patente-analytics` | uvicorn + FastAPI on `127.0.0.1:8000`    | systemd (auto-start, auto-restart) |
| `cloudflared`       | Named tunnel → `analytics.patentechi.it` | systemd (auto-start, auto-restart) |

Both survive reboots. No nginx, no Docker — kept minimal.

### Directory layout on the Pi

```
/home/keivan/patente-analytics/     # the repo (this project)
  ├── .venv/                        # Python virtualenv
  ├── .env                          # secrets (gitignored)
  ├── data/analytics.db             # SQLite database
  └── app/ ...                      # the code
/home/keivan/.cloudflared/
  ├── cert.pem                      # tunnel auth cert
  ├── <TUNNEL_ID>.json              # tunnel credentials
  └── config.yml                    # tunnel ingress config
/etc/systemd/system/
  ├── patente-analytics.service
  └── cloudflared.service
```

---

## Full setup from scratch

### 1. Clone and install on the Pi

```bash
ssh keivan@192.168.1.13
git clone https://github.com/keivan-ardam/patente-analytics.git
cd patente-analytics
git checkout feature/initial-implementation
bash scripts/setup_pi.sh
```

`setup_pi.sh`: creates the virtualenv, installs deps, creates `.env` from the
template, installs + starts the systemd service.

### 2. Create the Telegram bot

1. In Telegram, message **@BotFather** → `/newbot` → follow prompts.
2. Copy the **token** → `.env` `TELEGRAM_BOT_TOKEN`.
3. Send your new bot any message.
4. Get your chat ID:
   ```bash
   curl "https://api.telegram.org/bot<TOKEN>/getUpdates"
   ```
   Find `"chat":{"id":123456789}` → `TELEGRAM_CHAT_ID`.

### 3. Fill in `.env` and restart

```bash
nano ~/patente-analytics/.env      # TELEGRAM_*, ALLOWED_ORIGINS
sudo systemctl restart patente-analytics
curl http://127.0.0.1:8000/health  # {"status":"ok"}
```

---

## Cloudflare Tunnel setup

Gives the permanent `https://analytics.patentechi.it` URL.

### Prerequisite: domain on Cloudflare

- Bought `patentechi.it` at Aruba.
- Added to Cloudflare (free) → got 2 nameservers.
- At Aruba, nameservers switched to Cloudflare's (`corey`/`fiona.ns.cloudflare.com`).
- Waited until Cloudflare showed the domain **Active**.

### Install cloudflared (ARM64)

```bash
curl -L -o cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64
chmod +x cloudflared
sudo mv cloudflared /usr/local/bin/
```

### Authorize + create the named tunnel

```bash
cloudflared tunnel login                       # browser authorize patentechi.it
cloudflared tunnel create patente-analytics    # creates tunnel + credentials json
cloudflared tunnel route dns patente-analytics analytics.patentechi.it
```

> Over SSH, `cloudflared tunnel login` only prints its authorization URL when
> attached to a TTY (`ssh -tt`). Run it interactively, open the printed URL in a
> browser where you're logged into Cloudflare, and authorize `patentechi.it`.

### Config `~/.cloudflared/config.yml`

```yaml
tunnel: <TUNNEL_ID>
credentials-file: /home/keivan/.cloudflared/<TUNNEL_ID>.json

ingress:
  - hostname: analytics.patentechi.it
    service: http://127.0.0.1:8000
  - service: http_status:404
```

### Run as a service (survives reboots)

```bash
sudo cloudflared --config /home/keivan/.cloudflared/config.yml service install
sudo systemctl enable cloudflared
sudo systemctl start cloudflared
```

---

## Connecting the Vue app

In `Patente_UI/.env.production`:

```
VITE_ANALYTICS_URL=https://analytics.patentechi.it
```

`src/lib/analytics.ts` is wired into `main.ts`. If `VITE_ANALYTICS_URL` is empty,
analytics is a silent no-op (safe for local dev). Commit + push → Render rebuilds.

---

## Operations

### Logs

```bash
sudo journalctl -u patente-analytics -f     # FastAPI app logs
sudo journalctl -u cloudflared -f           # tunnel logs
```

### Update after code changes

```bash
ssh keivan@192.168.1.13
cd patente-analytics
bash scripts/deploy.sh        # git pull + reinstall deps + restart
```

### Service management

```bash
sudo systemctl status patente-analytics
sudo systemctl restart patente-analytics
sudo systemctl restart cloudflared
```

### Reset analytics data

```bash
rm ~/patente-analytics/data/analytics.db
sudo systemctl restart patente-analytics
```

### Common issues

| Symptom                                 | Likely cause                               | Fix                                        |
| --------------------------------------- | ------------------------------------------ | ------------------------------------------ |
| No Telegram messages                    | Wrong token/chat ID, or cooldown active    | Check `.env`; logs for `sendMessage` 200   |
| Events not arriving                     | Tunnel down, or wrong `VITE_ANALYTICS_URL` | `systemctl status cloudflared`; verify URL |
| CORS error in browser                   | Origin not in `ALLOWED_ORIGINS`            | Add app origin to `.env`, restart          |
| `analytics.patentechi.it` not resolving | Fresh DNS, local cache                     | Wait / flush DNS / use `1.1.1.1`           |
| Render domain won't verify              | Cloudflare record is "Proxied" (orange)    | Set to **DNS only** (grey cloud)           |
| URL changed after reboot                | Using a quick tunnel                       | Use the **named** tunnel (above)           |

---

## Deployment log

Chronological record of what was actually set up (for future reference):

1. **Pi baseline:** Debian 13 aarch64, Python 3.13, SSH + passwordless key from the Mac.
2. **Service:** cloned repo, created venv, installed FastAPI/uvicorn/httpx, installed
   `patente-analytics.service` (systemd), running on `127.0.0.1:8000`.
3. **Telegram:** created bot via BotFather, fetched chat id `255859351`, wired into `.env`.
4. **Temporary testing:** used a Cloudflare **quick tunnel** (`trycloudflare.com`) to
   verify the full chain (browser → tunnel → Pi → Telegram) in production.
5. **Domain:** bought `patentechi.it` at Aruba → added to Cloudflare → switched Aruba
   nameservers to `corey`/`fiona.ns.cloudflare.com` → domain went Active on Cloudflare.
6. **Cleanup:** removed the exploratory nginx + certbot (not needed with the tunnel);
   removed the frontend client secret (relies on CORS instead).
7. **Named tunnel:** `cloudflared tunnel login` (via `ssh -tt`), created tunnel
   `patente-analytics`, routed DNS to `analytics.patentechi.it`, wrote `config.yml`,
   installed + enabled the `cloudflared` systemd service. Stopped the quick tunnel.
8. **App bot:** added interactive Telegram buttons (Live Stats / Today / 7-Day /
   Countries) via a long-polling background task.
9. **App domain:** in Render added `patentechi.it` + `www.patentechi.it`; in Cloudflare
   added two CNAMEs → `patentechi.onrender.com` set to **DNS only (grey)**; Render
   verified + issued SSL.
10. **CORS hardening:** changed `ALLOWED_ORIGINS` from `*` to
    `https://patentechi.it,https://www.patentechi.it`.

---

## Privacy

- Only an anonymous random device ID is stored — **no names, emails, or IPs**.
- Suitable for a GDPR-conscious EU app: no personal data, no third-party trackers.
