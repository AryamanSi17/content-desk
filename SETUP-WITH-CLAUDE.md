# Set up Content Desk with Claude

**For the person:** open Claude Code inside this folder and say:
> Read SETUP-WITH-CLAUDE.md and set this up for me.

**For Claude:** follow these steps in order. Ask the person before installing anything, and before any step marked *(ask)*. Read `CLAUDE.md` first so you know how the project works.

---

## 1. Check the machine

- macOS only (Chrome path, notifications and launchd). On another OS, stop and say so.
- `python3 --version` must be 3.10 or newer. No pip packages are needed; the code is stdlib only.
- Google Chrome at `/Applications/Google Chrome.app`. If it is somewhere else, note the binary path for `CHROME_PATH` in step 5.
- `claude` CLI on PATH and logged in (`claude -p "say ok"` should print ok). Every idea, script, guide and carousel is written through it.
- `gh` CLI, logged in (`brew install gh`, `gh auth login`): setup guides read the repo's README through `gh api`. Without it guides are written with no README, so commands in them are less reliable.

## 2. Install the tools *(ask)*

| Tool | Install | Needed for | Without it |
|------|---------|------------|------------|
| Homebrew | https://brew.sh | installing the rest | install the rest by hand |
| yt-dlp | `brew install yt-dlp` | YouTube trends | YouTube source is marked failed, run continues |
| rclone | `brew install rclone` | "Share to Google Drive" | Share button shows a setup message |
| OpenCLI | `npm i -g @jackwener/opencli` (needs Node 18+) | X feed, Instagram competitors, own Reel stats | X and Instagram sources fail; set X cookies in step 5 instead |

After installing OpenCLI, the person must install its Chrome browser extension and stay logged in to X and Instagram in Chrome. Run `opencli --help` and follow its own setup instructions; you cannot click through the extension install for them.

**Instagram stats adapter (`igdesk`):** a small OpenCLI adapter with `posts`, `grid` and `tag` commands that is not in this repo. Ask the person whether they got a copy from the repo owner. If yes, put the folder at `~/.opencli/clis/igdesk/` (three .js files) and check `opencli igdesk posts THEIR_HANDLE --limit 3 -f json`. If no, skip it: the stats panel stays empty and everything else works.

**Google Drive** *(ask)*: `rclone config create gdrive drive scope=drive.file`. It opens a browser for Google login. The remote must be named `gdrive`.

**Video breakdowns (optional):** "Watch a video" and transcribing the person's own Reels use the Claude Code `watch` plugin from the `claude-video` marketplace. `digest.py` looks for it at `~/.claude/plugins/cache/claude-video/watch/*/skills/watch/scripts/watch.py`. Without it those features are skipped.

## 3. Make it theirs: interview, then write the files

The three personal files are git-ignored, so each creator keeps their own. Start from the templates (`sources.md` is a starter list for the AI / tech niche):
```
cp templates/*.md .
```

Ask the person, a few questions at a time:
1. Instagram handle.
2. Niche and audience (the tool is built for AI / tech tools; see step 4 if theirs is different).
3. Their last 5 to 10 Reels: topic, hook, views, comments. Best and worst ones.
4. Tone in a few words (casual, technical, funny...), language, and the CTA they use.
5. Accounts they watch on X and Instagram (competitors and news sources), hashtags and search keywords.

Then write:

- **`content-profile.md`**: fill every section from their answers. The first line must stay `# Content Profile: @their_handle`. That line sets the handle everywhere: prompts, dashboard header, guide PDF footer, carousel slides.
- **`style-samples.md`**: 3 to 7 real transcripts of their own Reels, best and worst, with views in brackets. This is what makes scripts sound like them, so do not invent lines. Ways to get them: they paste transcripts; or, if the watch plugin is installed, `python3 digest.py watch REEL_URL` for each Reel and copy the transcript. If they have none yet, write a short note of how they talk and say the scripts will improve once real transcripts are added.
- **`sources.md`**: keep the section headings exactly as they are (`## X accounts`, `## Instagram creators`, `## Hashtags to track`, `## Search keywords`, `## GitHub searches`, `## Subreddits`, `## YouTube channels`, `## Blogs and RSS feeds`); the code finds sections by these names. The parser reads the first `` `backticked` `` token on each `- ` bullet line under a heading. Replace the entries with theirs; keep the format `` - `handle` : why it matters ``.

## 4. Different niche? *(only if not AI / tech)*

The prompts in `digest.py` say "AI tools", "Claude", "GitHub repos" and the main `generate()` prompt prefers Claude skills, MCP and open source repos. Search `digest.py` for `AI tools`, `AI creator` and `Prefer Claude skills` and rewrite those phrases for their niche. GitHub, Hacker News and Hugging Face sources will be weak for non-tech niches; say so, and lean on X, Instagram, Reddit and YouTube via `sources.md`.

## 5. Settings *(ask before writing)*

Create `~/.config/content-digest/secrets.env` (outside the repo, never commit it). Only add lines that differ from the defaults:
```
CREATOR_HANDLE=their_handle        # optional, the profile heading already sets it
DIGEST_MODEL=claude-sonnet-5-5     # model for the daily run
CHROME_PATH=/path/to/Chrome        # only if Chrome is not in /Applications
PORT=8787                          # dashboard port
TWITTER_AUTH_TOKEN=...             # X login cookies, only if not using OpenCLI
TWITTER_CT0=...
```
`run-digest.sh` loads this file. The dashboard server does not, so if they set `PORT` or `CREATOR_HANDLE` here, also export them when starting `server.py` (or put them in the launchd plist in step 7).

## 6. First run and check

1. `python3 server.py`, then open http://127.0.0.1:8787 (or their PORT). The header must show their handle.
2. `./run-digest.sh` (or the dashboard's **Run now**). Takes 3 to 6 minutes. A source that fails is marked failed and the run continues; that is expected for tools they skipped.
3. Open the newest `data/digests/digest-YYYY-MM-DD.md` and read the top idea's script with them. If the voice is off, the fix is better transcripts in `style-samples.md`, not prompt edits.
4. On an idea, try **Draft guide** and check the PDF footer shows their handle.

## 7. Run every morning *(ask)*

Two launchd jobs: one keeps the dashboard running, one runs the digest at 8:00. Replace `/PATH/TO/content-desk` with the real absolute path and `PATH_VALUE` with the output of `echo $PATH` from their shell (launchd does not load their shell profile, so `claude`, `opencli` and `yt-dlp` must be on this PATH).

`~/Library/LaunchAgents/content-desk.server.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>content-desk.server</string>
  <key>ProgramArguments</key><array><string>/usr/bin/env</string><string>python3</string><string>/PATH/TO/content-desk/server.py</string></array>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>PATH_VALUE</string></dict>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/PATH/TO/content-desk/data/server.log</string>
  <key>StandardErrorPath</key><string>/PATH/TO/content-desk/data/server.log</string>
</dict></plist>
```

`~/Library/LaunchAgents/content-desk.digest.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>content-desk.digest</string>
  <key>ProgramArguments</key><array><string>/PATH/TO/content-desk/run-digest.sh</string></array>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>PATH_VALUE</string></dict>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>/PATH/TO/content-desk/data/scheduled-run.log</string>
  <key>StandardErrorPath</key><string>/PATH/TO/content-desk/data/scheduled-run.log</string>
</dict></plist>
```
Create `data/` first (`mkdir -p data`), then `launchctl load ~/Library/LaunchAgents/content-desk.server.plist ~/Library/LaunchAgents/content-desk.digest.plist`. The Mac must be awake at 8:00; `run-digest.sh` retries 3 times, 10 minutes apart, and shows a notification if all fail.

## 8. Tell the person

Finish with a short summary: what was installed, what was skipped and what that switches off, where their profile files are, the dashboard URL, and when the next scheduled run is.
