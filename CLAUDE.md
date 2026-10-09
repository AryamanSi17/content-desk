# Content Desk

Local tool for one Instagram creator: a daily research run that turns what's trending into Reel ideas with scripts in the creator's voice, plus a dashboard to work through them. First-time setup: follow `SETUP-WITH-CLAUDE.md`.

## Files

| File | What it is |
|------|------------|
| `digest.py` | Everything that does work: collectors, Claude prompts, guide PDFs, carousels, hooks, stats, Drive share. CLI, see below. |
| `server.py` | Dashboard server on `127.0.0.1:$PORT` (default 8787). Serves `dashboard.html` and a JSON API; long jobs run `digest.py` as a subprocess. |
| `dashboard.html` | The whole UI in one file (HTML, CSS, JS, no build step). `@your_handle` in it is swapped for the real handle when served. |
| `run-digest.sh` | The daily run: `collect` + `generate`, 3 tries 10 min apart, macOS notification. Loads `~/.config/content-digest/secrets.env`. |
| `content-profile.md` | The creator's account, best/worst Reels, tone, gaps. Its first line `# Content Profile: @handle` sets the handle everywhere. **Git-ignored, per creator.** |
| `style-samples.md` | Real transcripts of the creator's Reels. Scripts copy this voice. **Git-ignored, per creator.** |
| `sources.md` | Accounts, hashtags, keywords, subreddits, channels and feeds to collect from. **Git-ignored, per creator.** |
| `templates/` | Blank starting versions of the three files above. |
| `data/` | All output (git-ignored): `raw/` collected posts, `digests/` ideas (`YYYY-MM-DD.json` + `.md`), `guides/`, `carousels/`, `hooks/`, `img/`, `my-reels.json`, `my-stats.json`, `usage.jsonl` (Claude cost log), logs. |

## Commands

```
python3 digest.py collect          # pull today's posts from every source -> data/raw/DATE.json
python3 digest.py generate         # claude -p turns raw posts into 10 ideas + scripts -> data/digests/
python3 digest.py watch URL        # transcribe one Reel/Short and break down its hook (needs watch plugin)
python3 digest.py guide DATE N     # setup-guide PDF for idea N (also copied to ~/Downloads)
python3 digest.py carousel DATE N  # 1080x1350 slide PNGs + caption for idea N
python3 digest.py hooks DATE N     # 5 alternative hooks for idea N
python3 digest.py stats            # refresh the creator's own Reel plays/likes (OpenCLI igdesk)
python3 digest.py share KW         # upload guide KW to Google Drive (rclone remote "gdrive"), print link
python3 server.py                  # dashboard
./run-digest.sh                    # full daily run
```

## How it works

- **Collectors** (`COLLECTORS` in `digest.py`): x, instagram, github, hackernews, reddit, youtube, huggingface, blogs. Each runs isolated through `_safe`: a failure marks that source failed and the run continues. Never let one source break the run.
- **sources.md parsing** (`load_sources`): each `## Heading` is a section, keyed by its lowercased name; each `- ` bullet contributes its first `` `backticked` `` token. Code looks sections up by name (`x accounts`, `github`, `youtube`, ...), so renaming a heading silently empties that source.
- **Claude calls** go through the `claude` CLI (`claude -p --output-format json`), not the API. `generate` uses `DIGEST_MODEL` (default `claude-sonnet-5-5`). Every call is logged to `data/usage.jsonl` with tokens and cost. Prompts ask for JSON only and are parsed directly.
- **Handle** comes from `HANDLE` in `digest.py`: `CREATOR_HANDLE` env, else the `content-profile.md` heading, else `your_handle`. Use `HANDLE` in any new prompt or output; never hardcode a handle.
- **PDFs and slides** are HTML rendered by headless Chrome (`CHROME`, override with `CHROME_PATH`).
- **External tools are optional** except `claude` and Chrome: `opencli` (X, Instagram, stats), `yt-dlp` (YouTube), `gh` (READMEs for guides), `rclone` (Drive), the claude-video `watch` plugin (transcripts). Code checks for each and degrades.

## Rules for changing this project

- Python stdlib only. No pip dependencies, no build step, no frameworks in the dashboard.
- Keep the creator's data out of git: never commit `content-profile.md`, `style-samples.md`, `sources.md`, `data/` or `secrets.env`. To change what new users start with, edit `templates/`.
- Prompts are written for the AI / tech tools niche. Voice and topics come from the creator's own files; don't put one creator's phrases, numbers or accounts into the prompts.
- Prompt output rules the creator relies on: plain words, no em dashes, no hype words, never invent repos, numbers or links.
- The server binds to 127.0.0.1 only and checks the Origin header on POSTs. Keep it local.
- Test a change by running the command it touches (e.g. `python3 digest.py collect`) and opening the dashboard; there is no test suite.

Made by [AryamanSi17](https://github.com/AryamanSi17) · Instagram [@ai_aryaman](https://www.instagram.com/ai_aryaman/)
