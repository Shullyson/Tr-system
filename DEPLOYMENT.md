# Deploying to a VPS

Goal: this system runs unattended on a schedule, and only emails you when
the decision agent actually reaches a verdict. Most runs will do nothing —
that's correct behavior, not a bug.

## 1. Get a VPS

Any of these work fine for this workload (it's lightweight — no GPU, low
memory, occasional network calls):
- DigitalOcean, Linode, Hetzner — all have a ~$5/mo "basic droplet" tier
  (1 vCPU, 1GB RAM is plenty). Hetzner tends to be cheapest.
- Pick Ubuntu 24.04 LTS as the OS image — matches what these instructions assume.

## 2. Initial server setup

SSH into the server, then:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip git
```

## 3. Get your code onto the server

Easiest: push your local project to a private GitHub repo, then on the
server:

```bash
git clone <your-private-repo-url> trading-system
cd trading-system
```

(Or `scp -r` the folder from your machine if you'd rather not use git —
either works. Just make sure `venv/` and `.env` are NOT included in
whatever you transfer — `.env` especially, since it holds real secrets.)

## 4. Set up the environment on the server

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create `.env` directly on the server (never copy a `.env` containing real
secrets through git or a public channel):

```bash
cp .env.example .env
nano .env   # fill in ANTHROPIC_API_KEY and the ALERT_EMAIL_* values
```

## 5. Test it manually first

Before scheduling anything, run it by hand and confirm it works exactly
as it did on your own machine:

```bash
python3 orchestrator.py
```

## 6. Schedule it with cron

Edit the crontab:

```bash
crontab -e
```

Add a line to run every 30 minutes (adjust to taste — matches the
15-60 min range discussed earlier):

```
*/30 * * * * cd /home/YOUR_USER/trading-system && /home/YOUR_USER/trading-system/venv/bin/python3 orchestrator.py >> /home/YOUR_USER/trading-system/logs/cron.log 2>&1
```

Replace `YOUR_USER` and the path with your actual server username/path.
The `>> ... 2>&1` redirects all output (including errors) to a log file,
so you can check what happened even between email alerts.

## 7. Verify it's actually running

After ~30-60 minutes:

```bash
tail -n 50 logs/cron.log
```

You should see scout output logged even on runs where nothing was
alertable — if the log file is empty or missing, the cron job isn't
firing (double-check the paths in the crontab line).

## Notes

- **Cost**: ~$5/mo for the VPS. Anthropic API costs are separate and only
  incurred on runs where the scout agent triggers — most runs cost $0
  since the LLM layer is skipped entirely.
- **Security**: your `.env` file holds real API keys and an email app
  password. Make sure server SSH access uses key-based auth, not just a
  password, and never commit `.env` to a public repo.
- **Log rotation**: `logs/cron.log` will grow indefinitely — not urgent
  at this scale, but worth adding `logrotate` or manually truncating it
  every so often once you've been running this for a while.
- **This does not place trades.** Nothing here touches an exchange
  account or executes orders — it only emails you a recommendation. That
  matches the "strictly advisory" scope you set at the start.
