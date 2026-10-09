# Content Desk

A local dashboard for an Instagram creator in the AI niche. Every morning it collects what's trending (X, Instagram, GitHub, Reddit, Hacker News, YouTube), then has Claude write 10 Reel ideas with scripts in your voice. From any idea it can make a setup-guide PDF, an Instagram carousel and alternative hooks, and share the guide to Google Drive.

Made by [AryamanSi17](https://github.com/AryamanSi17) · Instagram [@ai_aryaman](https://www.instagram.com/ai_aryaman/)

**Fastest setup:** open Claude Code in this folder and say *"Read SETUP-WITH-CLAUDE.md and set this up for me."* It installs the tools, interviews you to write your profile files, and runs the first digest. `CLAUDE.md` tells Claude how the project works when you ask it to change things later.

Mac only for now. Python stdlib only, no `pip install`.

Built for creators in the AI / tech tools niche: the sources (GitHub, Hacker News, Reddit, X) and prompts assume that. Another niche works if you change `sources.md` and the niche words in the prompts in `digest.py` (search for "AI tools").

## Setup

1. **Clone it**
   ```
   git clone <this repo> content-desk && cd content-desk
   ```

2. **Make it yours.** These three files drive everything Claude writes:
   - `content-profile.md`: your account, your best and worst Reels, your tone. The first line, `# Content Profile: @your_handle`, sets your handle everywhere (prompts, dashboard, guide PDFs, carousel slides).
   - `style-samples.md`: transcripts of your own Reels. The scripts copy your words and rhythm from these.
   - `sources.md`: X accounts, Instagram creators, hashtags and keywords to watch. Add or remove a line and the next run picks it up.

   They are not in the repo, so every creator keeps their own (they are git-ignored). Start from the templates:
   ```
   cp templates/*.md .
   ```

3. **Install the tools it calls**
   | Tool | Used for | Required? |
   |------|----------|-----------|
   | [Claude Code](https://claude.com/claude-code) (`claude` CLI, logged in) | writing ideas, scripts, guides | yes |
   | Google Chrome | rendering guide PDFs and carousel slides | yes |
   | `yt-dlp` (`brew install yt-dlp`) | YouTube trends | optional |
   | OpenCLI (`npm i -g @jackwener/opencli`) + its browser extension | your Instagram stats, X feed | optional |
   | `rclone` | "Share to Google Drive" button | optional |
   | Claude Code `watch` plugin (claude-video) | "Watch a video" breakdowns, transcribing your own Reels | optional |

   Instagram stats use a small OpenCLI adapter called `igdesk` (`posts`, `grid`, `tag`) that lives in `~/.opencli/clis/igdesk`. Ask [AryamanSi17](https://github.com/AryamanSi17) for a copy. Without it the stats panel stays empty and everything else works.

   Google Drive, once: `rclone config create gdrive drive scope=drive.file`

4. **Run it**
   ```
   python3 server.py          # dashboard at http://127.0.0.1:8787
   ./run-digest.sh            # one full collect + generate run (the dashboard's "Run now" does the same)
   ```

## Settings

Put these in `~/.config/content-digest/secrets.env` (loaded by `run-digest.sh`, never committed) or export them before starting the server.

| Variable | Default | What it does |
|----------|---------|--------------|
| `CREATOR_HANDLE` | heading of `content-profile.md` | your Instagram handle |
| `PORT` | `8787` | dashboard port |
| `DIGEST_MODEL` | `claude-sonnet-5-5` | Claude model for the daily run |
| `CHROME_PATH` | `/Applications/Google Chrome.app/...` | Chrome binary for PDFs |
| `TWITTER_AUTH_TOKEN`, `TWITTER_CT0` | none | X login cookies, if you don't use OpenCLI |

Other knobs in code: Drive folder name (`DRIVE_DIR` in `digest.py`), and the script rules and catchphrases in the `generate` prompt in `digest.py`.

## Run it every morning (optional)

A launchd job that runs `run-digest.sh` at 8:00. Save as `~/Library/LaunchAgents/content-digest.plist` with your own path, then `launchctl load` it:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>content-digest</string>
  <key>ProgramArguments</key><array><string>/PATH/TO/content-desk/run-digest.sh</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>/PATH/TO/content-desk/data/scheduled-run.log</string>
  <key>StandardErrorPath</key><string>/PATH/TO/content-desk/data/scheduled-run.log</string>
</dict></plist>
```

Everything the app makes (digests, guides, stats) goes in `data/`, which is git-ignored.

## License

MIT, see [LICENSE](LICENSE). Made by [AryamanSi17](https://github.com/AryamanSi17). If it helps you, follow [@ai_aryaman](https://www.instagram.com/ai_aryaman/) on Instagram.
