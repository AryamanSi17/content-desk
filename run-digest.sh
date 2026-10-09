#!/bin/bash
# Daily digest: collect from every source in sources.md, then write ideas + scripts.
# Output: data/digests/digest-YYYY-MM-DD.md (+ .json for the dashboard)
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$HOME/.nvm/versions/node/v22.19.0/bin:/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH"

# Optional logins live OUTSIDE this folder, never in git.
# ~/.config/content-digest/secrets.env  ->  TWITTER_AUTH_TOKEN=...  TWITTER_CT0=...
SECRETS="$HOME/.config/content-digest/secrets.env"
if [ -f "$SECRETS" ]; then set -a; . "$SECRETS"; set +a; fi

# Retry: a scheduled run can fire during a short sleep-wake with no network. Try up to 3 times, 10 min apart.
ok=0
for attempt in 1 2 3; do
  if python3 digest.py collect && python3 digest.py generate; then ok=1; break; fi
  echo "[$(date +%H:%M:%S)] attempt $attempt failed"
  [ $attempt -lt 3 ] && sleep 600
done
if [ $ok -ne 1 ]; then
  osascript -e 'display notification "Daily run failed 3 times. Open the dashboard and press Run now." with title "Content Desk" sound name "Basso"' 2>/dev/null || true
  exit 1
fi

# Morning ping: macOS notification with today's top idea (never fails the run).
TOP=$(python3 -c "import json,datetime;d=json.load(open('data/digests/'+datetime.date.today().isoformat()+'.json'));print(f\"{len(d['ideas'])} new ideas. Top: {d['ideas'][0]['title']}\".replace('\"',''))" 2>/dev/null || echo "New ideas are ready")
osascript -e "display notification \"$TOP\" with title \"Content Desk\" subtitle \"Open http://127.0.0.1:8787\" sound name \"Glass\"" 2>/dev/null || true
