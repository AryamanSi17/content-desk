#!/usr/bin/env python3
"""Daily content digest for an Instagram creator (handle from content-profile.md or CREATOR_HANDLE).

  python3 digest.py collect      pull raw posts from every source in sources.md
  python3 digest.py generate     turn raw posts into ideas + scripts with `claude -p`
  python3 digest.py watch URL    transcribe one Reel/Short and break down its hook
  python3 digest.py guide DATE N write the DM guide promised by idea N's comment CTA
  python3 digest.py carousel DATE N  make idea N's carousel: slide PNGs (1080x1350) + caption
  python3 digest.py hooks DATE N 5 alternative hooks for idea N (for Trial Reels A/B)
  python3 digest.py stats        refresh plays/likes of your own Reels (1 Instagram request)
  python3 digest.py share KW     upload guide KW's PDF to Google Drive and print a share link

Stdlib only. Each source is isolated: if one fails it is marked failed and the run continues.
"""
import contextlib, html, io, json, os, re, shutil, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RAW, OUT = DATA / "raw", DATA / "digests"
# Your Instagram handle: CREATOR_HANDLE, else the "# Content Profile: @handle" heading of content-profile.md.
_profile = ROOT / "content-profile.md"
_heading = re.search(r"^# Content Profile: @?([\w.]+)", _profile.read_text() if _profile.exists() else "", re.M)
HANDLE = (os.environ.get("CREATOR_HANDLE") or (_heading and _heading[1]) or "your_handle").lstrip("@")
CHROME = os.environ.get("CHROME_PATH", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
TODAY = os.environ.get("DIGEST_DATE") or date.today().isoformat()
WATCH = next(Path.home().glob(".claude/plugins/cache/claude-video/watch/*/skills/watch/scripts/watch.py"), None)
UA = "Mozilla/5.0 (Macintosh) content-digest/1.0"
DAY_AGO = datetime.now(timezone.utc) - timedelta(hours=36)


def log(*a):
    print(f"[{datetime.now():%H:%M:%S}]", *a, flush=True)


def get(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def run(cmd, timeout=120):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout).strip()[-300:])
    return p.stdout


def age_hours(stamp):
    """Hours since a date string / unix time. None if unknown."""
    from email.utils import parsedate_to_datetime
    if not stamp:
        return None
    try:
        dt = datetime.fromtimestamp(stamp, timezone.utc) if isinstance(stamp, (int, float)) else (
            parsedate_to_datetime(stamp) if "," in stamp else datetime.fromisoformat(stamp.replace("Z", "+00:00")))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return round((datetime.now(timezone.utc) - dt).total_seconds() / 3600)
    except (ValueError, TypeError, OverflowError):
        return None


def clean(s, n=280):
    s = re.sub(r"<[^>]+>", " ", html.unescape(s or ""))
    return re.sub(r"\s+", " ", s).strip()[:n]


# ---------- sources.md ----------

def load_sources():
    """Every section of sources.md -> list of the `backticked` first tokens on its bullet lines."""
    out, sec = {}, None
    for line in (ROOT / "sources.md").read_text().splitlines():
        if line.startswith("## "):
            sec = line[3:].split("(")[0].strip().lower()
            out[sec] = []
        elif sec and line.lstrip().startswith("- "):
            m = re.search(r"`([^`]+)`", line)
            if m:
                out[sec].append(m.group(1))
    return out


def section(src, word):
    return next((v for k, v in src.items() if word in k), [])


# ---------- collectors (each returns a list of items) ----------

def github(src):
    items = []
    page = get("https://github.com/trending?since=daily")
    for a in page.split('<article class="Box-row')[1:]:
        repo = re.search(r'<h2[^>]*>\s*<a[^>]*href="/([^"]+)"', a).group(1)
        desc = re.search(r'<p class="col-9[^"]*">(.*?)</p>', a, re.S)
        today = re.search(r"([\d,]+) stars today", a)
        total = re.search(r'href="/[^"]+/stargazers"[^>]*>.*?([\d,]+)\s*</a>', a, re.S)
        items.append({"title": repo, "url": f"https://github.com/{repo}", "text": clean(desc.group(1) if desc else ""),
                      "metric": f"{today.group(1) if today else '?'} stars today, {total.group(1) if total else '?'} total",
                      "kind": "trending"})
    def created(i):
        try:
            i["created"] = json.loads(run(["gh", "api", f"repos/{i['title']}", "--jq", "{c: .created_at}"], 30))["c"][:10]
        except Exception:
            i["created"] = "?"
        i["metric"] += f", created {i['created']}"
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(created, items))
    since = (date.today() - timedelta(days=3)).isoformat()
    for q in section(src, "github"):
        try:
            res = json.loads(run(["gh", "api", "-X", "GET", "search/repositories", "-f",
                                  f"q={q} created:>{since}", "-f", "sort=stars", "-f", "per_page=5"], 60))
        except Exception as e:
            log("  github search failed:", q, e)
            continue
        for r in res.get("items", []):
            items.append({"title": r["full_name"], "url": r["html_url"], "text": clean(r.get("description")),
                          "metric": f"{r['stargazers_count']} stars, created {r['created_at'][:10]}", "kind": f"new repo: {q}"})
    seen, uniq = set(), []
    for i in items:
        if i["title"] not in seen:
            seen.add(i["title"]); uniq.append(i)
    return uniq


def hackernews(src):
    items, cutoff = [], int(DAY_AGO.timestamp())
    for q in section(src, "keyword")[:8]:
        j = json.loads(get("https://hn.algolia.com/api/v1/search?tags=story&query=" + urllib.parse.quote(q)
                           + f"&numericFilters=created_at_i>{cutoff},points>25"))
        for h in j["hits"]:
            items.append({"title": h["title"], "url": h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}",
                          "text": f"HN discussion: https://news.ycombinator.com/item?id={h['objectID']}",
                          "metric": f"{h['points']} points, {h.get('num_comments', 0)} comments", "age_h": age_hours(h["created_at_i"]), "kind": q})
    best = {}
    for i in items:
        best.setdefault(i["title"], i)
    return sorted(best.values(), key=lambda i: -int(i["metric"].split()[0]))[:15]


def reddit(src):
    """One combined RSS request (r/a+b+c) so Reddit's anonymous rate limit is not hit."""
    ns = {"a": "http://www.w3.org/2005/Atom"}
    url = f"https://www.reddit.com/r/{'+'.join(section(src, 'subreddit'))}/top/.rss?t=day&limit=30"
    for wait in (0, 30, 90):
        time.sleep(wait)
        try:
            root = ET.fromstring(get(url))
            break
        except urllib.error.HTTPError as e:
            if e.code != 429 or wait == 90:
                raise
    return [{"title": e.findtext("a:title", "", ns), "url": e.find("a:link", ns).get("href"),
             "text": clean(e.findtext("a:content", "", ns), 200),
             "image": html.unescape((re.search(r'<img src="([^"]+)"', html.unescape(e.findtext("a:content", "", ns))) or [None, ""])[1]),
             "metric": f"top today in r/{e.find('a:category', ns).get('term') if e.find('a:category', ns) is not None else '?'}",
             "kind": "reddit"} for e in root.findall("a:entry", ns)]


def youtube(src):
    def one(h):
        j = json.loads(run(["yt-dlp", "-J", "--flat-playlist", "-I", "1:4", "--extractor-args", "youtubetab:approximate_date",
                            f"https://www.youtube.com/{h}/videos"], 90))
        out = [{"title": e.get("title"), "url": f"https://www.youtube.com/watch?v={e['id']}", "text": j.get("channel") or h,
                "metric": f"{e.get('view_count') or '?'} views", "views": e.get("view_count") or 0,
                "age_h": age_hours(e.get("timestamp")), "image": f"https://i.ytimg.com/vi/{e['id']}/hqdefault.jpg", "kind": h} for e in j.get("entries", [])]
        return [i for i in out if i["age_h"] is not None and i["age_h"] <= 48]
    with ThreadPoolExecutor(6) as ex:
        return [i for chunk in ex.map(lambda h: _safe(one, h), section(src, "youtube")) for i in chunk]


def feeds(src):
    items = []
    for url in section(src, "rss"):
        try:
            root = ET.fromstring(get(url))
        except Exception as e:
            log("  feed failed:", url, e)
            continue
        for e in list(root.iter())[:400]:
            tag = e.tag.split("}")[-1]
            if tag not in ("item", "entry"):
                continue
            kid = {c.tag.split("}")[-1]: c for c in e}
            first = lambda *names: next((kid[n].text for n in names if n in kid and kid[n].text), "")
            link = kid.get("link")
            href = (link.get("href") or link.text) if link is not None else ""
            age = age_hours(first("pubDate", "updated", "published"))
            if age is None or age > 48:
                continue
            items.append({"title": clean(kid["title"].text if "title" in kid else ""), "url": href, "age_h": age,
                          "text": clean(first("description", "summary", "content"), 200),
                          "metric": clean(first("pubDate", "updated", "published"), 40),
                          "kind": urllib.parse.urlparse(url).netloc})
            if sum(1 for i in items if i["kind"] == urllib.parse.urlparse(url).netloc) >= 5:
                break
    return items


def huggingface(src):
    j = json.loads(get("https://huggingface.co/api/models?sort=trendingScore&limit=10"))
    return [{"title": m["id"], "url": f"https://huggingface.co/{m['id']}", "text": m.get("pipeline_tag") or "",
             "metric": f"{m.get('likes', 0)} likes", "kind": "trending model"} for m in j]


_OPENCLI = {}


def opencli_ready():
    """One cheap check per run, so a disconnected extension fails in seconds instead of hanging every call."""
    if "ok" not in _OPENCLI:
        if not shutil.which("opencli"):
            _OPENCLI["ok"], _OPENCLI["why"] = False, "OpenCLI not installed"
        else:
            try:
                doc = run(["opencli", "doctor"], 30)
            except Exception as e:
                doc = str(e)
            ok = "Extension: not connected" not in doc and "[FAIL]" not in doc
            _OPENCLI["ok"], _OPENCLI["why"] = ok, "" if ok else "OpenCLI Chrome extension not connected (open Chrome, then run: opencli doctor)"
    return _OPENCLI["ok"]


def opencli(*args, timeout=120, background=True):
    """Read-only OpenCLI call -> list of dicts. X runs in a background tab; Instagram rejects that, so it opts out."""
    out = json.loads(run(["opencli", *args, "-f", "json", *(["--window", "background"] if background else [])], timeout))
    return out.get("data", out) if isinstance(out, dict) else out


def num(v):
    try:
        return int(float(str(v).replace(",", "")))
    except ValueError:
        return 0


def pick(d, *keys):
    for k in keys:
        v = d.get(k)
        if isinstance(v, dict):
            v = v.get("username") or v.get("screen_name") or v.get("name")
        if v not in (None, ""):
            return v
    return ""


def tweet(t, kind):
    author = str(pick(t, "author", "username", "screen_name", "user")).lstrip("@")
    tid = pick(t, "id", "tweet_id", "rest_id")
    likes, rts, views = num(pick(t, "likes", "like_count", "favorite_count")), num(pick(t, "retweets", "retweet_count")), num(pick(t, "views", "view_count"))
    created = pick(t, "created_at")
    try:
        age = round((datetime.now(timezone.utc) - datetime.strptime(created, "%a %b %d %H:%M:%S %z %Y")).total_seconds() / 3600)
    except (ValueError, TypeError):
        age = age_hours(created) if isinstance(created, str) else None
    q = t.get("quoted_tweet") or {}
    img = next(iter(t.get("media_posters") or q.get("media_posters") or [u for u in (t.get("media_urls") or []) if ".jpg" in u or "format=jpg" in u]), "")
    return {"title": clean(pick(t, "text", "full_text", "content"), 280), "age_h": age, "image": img,
            "url": pick(t, "url", "link") or (f"https://x.com/{author}/status/{tid}" if author and tid else ""),
            "text": f"@{author}", "likes": likes, "metric": f"{likes} likes, {rts} reposts, {views} views", "kind": kind}


def x_posts(src):
    """What he would see scrolling X: For You feed + today's top posts on his keywords + the watched accounts."""
    if opencli_ready():
        since = (date.today() - timedelta(days=1)).isoformat()
        items = [tweet(t, "your X feed") for t in _safe(lambda _: opencli("twitter", "timeline", "--limit", "60", "--top-by-engagement", "25"), "")]
        handles = " OR ".join(f"from:{h.lstrip('@')}" for h in section(src, "x accounts"))
        items += [tweet(t, "watched accounts") for t in _safe(lambda q: opencli("twitter", "search", q, "--limit", "40", "--top-by-engagement", "15"), f"({handles}) since:{since}")]
        for q in ("claude code", "claude skill", "anthropic", "open source AI"):
            time.sleep(2)
            items += [tweet(t, f"X search: {q}") for t in _safe(lambda q: opencli("twitter", "search", f"{q} since:{since}", "--product", "top", "--limit", "15", "--top-by-engagement", "6"), q)]
        items = [i for i in items if i["age_h"] is None or i["age_h"] <= 48]
        seen, uniq = set(), []
        for i in sorted(items, key=lambda i: -i["likes"]):
            if i["url"] not in seen:
                seen.add(i["url"]); uniq.append(i)
        if uniq:
            return uniq
        raise RuntimeError("OpenCLI returned no tweets from the last 48h. Is Chrome logged in to x.com?")
    if not os.environ.get("TWITTER_AUTH_TOKEN"):
        raise RuntimeError(_OPENCLI["why"] + ". Or put TWITTER_AUTH_TOKEN and TWITTER_CT0 in ~/.config/content-digest/secrets.env")
    def one(h):
        posts = json.loads(run(["twitter", "user-posts", h.lstrip("@"), "-n", "5", "--json"], 60))
        return [tweet(p, h) for p in (posts.get("data", posts) if isinstance(posts, dict) else posts)]
    with ThreadPoolExecutor(4) as ex:
        return [i for chunk in ex.map(lambda h: _safe(one, h), section(src, "x accounts")) for i in chunk]


def igpost(p, kind):
    url = pick(p, "url", "link")
    likes, plays = num(pick(p, "likes", "like_count")), num(pick(p, "plays", "play_count"))
    return {"title": clean(pick(p, "caption", "text"), 220), "url": url, "text": "@" + str(pick(p, "user", "author", "username") or "?"),
            "likes": likes, "plays": plays, "image": pick(p, "thumbnail"),
            "age_h": age_hours(num(p.get("taken_at"))) if p.get("taken_at") else None,
            "metric": f"{plays} plays, {likes} likes, {pick(p, 'comments', 'comment_count') or 0} comments",
            "is_video": pick(p, "type") == "video" or "/reel/" in url, "kind": kind}


def instagram(src):
    """Instagram, niche only: top posts on his hashtags + recent posts of competitors in sources.md.
    (Explore was dropped: his Explore feed is general viral content, not AI.)
    Stops at the first rate limit so the logged-in account is never hammered."""
    if not opencli_ready():
        raise RuntimeError(_OPENCLI["why"] + ". Meanwhile paste Reel links in the dashboard 'Watch a Reel' box")
    items, limited = [], ""
    calls = [(f"#{t.lstrip('#')} top", ["igdesk", "tag", t.lstrip("#"), "--limit", "9"]) for t in section(src, "hashtag")]
    calls += [(f"competitor @{h}", ["igdesk", "posts", h, "--limit", "4"]) for h in section(src, "instagram")]
    for kind, args in calls:
        try:
            items += [igpost(p, kind) for p in opencli(*args, background=False)]
        except Exception as e:
            log(f"  instagram {kind} failed:", str(e).splitlines()[-1][:120] if str(e) else "")
            if "429" in str(e) or "DOCTYPE" in str(e):
                limited = "Instagram is rate limiting this account (429), stopped early to protect it. Clears in a few hours."
                break
        time.sleep(4)  # ponytail: fixed pacing so Instagram does not rate-limit the logged-in account
    items = [i for i in items if i["age_h"] is None or i["age_h"] <= 24 * 7]
    seen, uniq = set(), []
    for i in sorted(items, key=lambda i: -(i["plays"] or i["likes"])):
        if i["url"] and i["url"] not in seen:
            seen.add(i["url"]); uniq.append(i)
    if not uniq:
        raise RuntimeError(limited or "OpenCLI returned nothing. Is Chrome logged in to Instagram?")
    return uniq


def my_reels():
    """His own recent Reels (transcribed once, cached) so ideas never repeat what he already made."""
    cache_f = DATA / "my-reels.json"
    cache = json.loads(cache_f.read_text()) if cache_f.exists() else {}
    if opencli_ready():
        posts = _safe(lambda _: opencli("igdesk", "posts", HANDLE, "--limit", "30", background=False), "")
        if posts:
            save_stats(posts)
        else:
            _safe(lambda _: save_stats(opencli("igdesk", "grid", HANDLE, "--limit", "30", background=False), "grid"), "")
        for p in posts:
            post = igpost(p, "mine")
            if post["url"] and post["url"] not in cache:
                try:
                    cache[post["url"]] = {"caption": post["title"], "opening": transcribe(post["url"])["transcript"][:300]}
                except Exception:
                    cache[post["url"]] = {"caption": post["title"], "opening": ""}
        cache_f.write_text(json.dumps(cache, indent=1, ensure_ascii=False))
    return [f"{v['caption']} | {v['opening']}" for v in cache.values()]


def _safe(fn, arg):
    try:
        return fn(arg)
    except Exception as e:
        log(f"  {fn.__name__}({arg}) failed:", str(e)[:150])
        return []


COLLECTORS = {"x": x_posts, "instagram": instagram, "github": github, "hackernews": hackernews,
              "reddit": reddit, "youtube": youtube, "huggingface": huggingface, "blogs": feeds}


def transcribe(url, timeout=240):
    """Transcript via the /watch skill (captions first, then Groq Whisper)."""
    if not WATCH:
        raise RuntimeError("/watch skill not found")
    out = run([sys.executable, str(WATCH), url, "--detail", "transcript", "--out-dir", str(DATA / "tmp" / re.sub(r"\W", "_", url)[-40:])], timeout)
    dur = re.search(r"\*\*Duration:\*\* ([^\n]+)", out)
    tx = re.search(r"## Transcript.*?```\n(.*?)```", out, re.S)
    return {"duration": dur.group(1) if dur else "?", "transcript": tx.group(1).strip() if tx else ""}


def collect():
    src = load_sources()
    RAW.mkdir(parents=True, exist_ok=True)
    result = {"date": TODAY, "collected_at": datetime.now().isoformat(timespec="seconds"), "sources": {}}

    def one(name):
        t = time.time()
        try:
            items = COLLECTORS[name](src)
            status = "ok" if items else "empty"
            return name, {"status": status, "items": items, "error": "" if items else "no items returned",
                          "seconds": round(time.time() - t)}
        except Exception as e:
            return name, {"status": "failed", "items": [], "error": str(e)[:300], "seconds": round(time.time() - t)}

    with ThreadPoolExecutor(len(COLLECTORS)) as ex:
        for name, res in ex.map(one, COLLECTORS):
            result["sources"][name] = res
            log(f"{name:12} {res['status']:7} {len(res['items']):3} items  {res['error'][:90]}")

    # Watch the top competitor videos so the digest knows their real hooks, not guesses.
    # YouTube downloads need browser cookies (bot check), so only Instagram Reels are auto-watched.
    vids = [i for i in result["sources"]["instagram"]["items"] if i.get("url") and i.get("is_video")][:4]
    vids += [{"title": "queued by you", "url": u, "kind": "watch-queue"} for u in _pop_queue()]
    watched = []
    for v in vids:
        try:
            t = transcribe(v["url"])
            watched.append({**v, **t, "transcript": t["transcript"][:1800]})
            log("watched", v["url"])
        except Exception as e:
            log("watch failed", v["url"], str(e)[:120])
    result["watched"] = watched
    result["already_made"] = my_reels()
    (RAW / f"{TODAY}.json").write_text(json.dumps(result, indent=1, ensure_ascii=False))
    log("raw saved:", RAW / f"{TODAY}.json")


def _pop_queue():
    q = DATA / "watch-queue.txt"
    if not q.exists():
        return []
    urls = [u.strip() for u in q.read_text().splitlines() if u.strip()]
    q.unlink()
    return urls[:5]


# ---------- v2: stats, guides, hooks ----------

STATS = DATA / "my-stats.json"


def log_usage(kind, reply):
    """Append tokens + cost of one claude -p call to data/usage.jsonl (shown on the dashboard)."""
    u = reply.get("usage") or {}
    row = {"at": datetime.now().isoformat(timespec="seconds"), "kind": kind, "cost_usd": round(reply.get("total_cost_usd") or 0, 4),
           "input": u.get("input_tokens", 0), "cache_read": u.get("cache_read_input_tokens", 0),
           "cache_write": u.get("cache_creation_input_tokens", 0), "output": u.get("output_tokens", 0),
           "models": list((reply.get("modelUsage") or {}).keys())}
    with (DATA / "usage.jsonl").open("a") as f:
        f.write(json.dumps(row) + "\n")
    return row


def ask_claude(prompt, timeout=300, kind="tool"):
    """claude -p -> parsed JSON object from its reply."""
    p = subprocess.run(["claude", "-p", "--output-format", "json"], input=prompt, capture_output=True, text=True, timeout=timeout, cwd=DATA)
    if p.returncode:
        raise RuntimeError("claude failed: " + (p.stderr or p.stdout)[-300:])
    reply = json.loads(p.stdout)
    log_usage(kind, reply)
    text = reply["result"]
    return json.loads(text[text.index("{"): text.rindex("}") + 1])


def _code(url):
    m = re.search(r"/(?:reel|p)/([\w-]+)", url or "")
    return m.group(1) if m else url


def save_stats(posts, source="feed"):
    """Snapshot his own Reels' numbers. history keeps plays per day so growth is visible.
    Grid-fallback posts have no caption, so captions come from the my-reels cache by Reel code."""
    old = json.loads(STATS.read_text()) if STATS.exists() else {"history": {}}
    mine = DATA / "my-reels.json"
    caps = {_code(u): v.get("caption", "") for u, v in (json.loads(mine.read_text()) if mine.exists() else {}).items()}
    reels = []
    for p in posts:
        p["url"] = f"https://www.instagram.com/reel/{_code(p.get('url'))}/"
        cap = p.get("caption") or caps.get(_code(p["url"]), "")
        kw = re.search(r"comment\s+[\"“'‘]?([\w-]+)", cap, re.I)
        reels.append({"url": p.get("url"), "caption": cap[:200], "keyword": kw.group(1).lower() if kw else "",
                      "plays": num(p.get("plays")), "likes": num(p.get("likes")), "comments": num(p.get("comments")),
                      "type": p.get("type"), "taken_at": p.get("taken_at") or 0})
        old["history"].setdefault(p.get("url"), {})[TODAY] = num(p.get("plays"))
    STATS.write_text(json.dumps({"updated": datetime.now().isoformat(timespec="seconds"), "source": source, "reels": reels,
                                 "history": old["history"]}, indent=1, ensure_ascii=False))
    return reels


def stats():
    if not opencli_ready():
        raise SystemExit(_OPENCLI["why"])
    reels = refresh_stats()
    print(json.dumps({"ok": True, "count": len(reels), "source": json.loads(STATS.read_text()).get("source")}))


def refresh_stats():
    """Full data from the feed API; if Instagram rate limits it, fall back to view counts from the Reels grid page."""
    try:
        return save_stats(opencli("igdesk", "posts", HANDLE, "--limit", "30", background=False))
    except Exception as e:
        log("  stats feed blocked, using Reels grid:", str(e).splitlines()[-1][:80] if str(e) else "")
        return save_stats(opencli("igdesk", "grid", HANDLE, "--limit", "30", background=False), "grid")


def performance_note():
    """Top 3 / bottom 3 of his recent Reels for the idea prompt (empty if no stats yet)."""
    if not STATS.exists():
        return "No stats yet."
    reels = [r for r in json.loads(STATS.read_text())["reels"] if r["plays"]]
    reels.sort(key=lambda r: -r["plays"])
    fmt = lambda r: f"{r['plays']} plays, {r['comments']} comments: {r['caption'][:120]}"
    return json.dumps({"best": [fmt(r) for r in reels[:3]], "worst": [fmt(r) for r in reels[-3:]]}, ensure_ascii=False)


def _idea(date_, n):
    d = json.loads((OUT / f"{date_}.json").read_text())
    return d, d["ideas"][int(n)]




def render_guide(g, title=""):
    """Guide look: black A4, gold, Poppins + Lora."""
    e = html.escape
    def block(b):
        if b.get("type") == "code":
            return f'<pre class="code">{e(b.get("text", ""))}</pre>'
        if b.get("type") == "table":
            return '<table>' + "".join(f'<tr><th>{e(r[0])}</th><td>{e(r[1] if len(r) > 1 else "")}</td></tr>' for r in b.get("rows", [])) + '</table>'
        return f'<p>{e(b.get("text", ""))}</p>'
    secs = "".join(f'<h2><span>{k:02d}</span>{e(re.sub(r"^\s*(step\s*)?\d+[.):]?\s*", "", sec.get("title", ""), flags=re.I))}</h2><hr class="thin">' + "".join(block(b) for b in sec.get("blocks", []))
                   for k, sec in enumerate(g.get("sections", []), 1))
    call = g.get("callout") or {}
    callout = f'<div class="callout"><div class="cap">{e(call.get("title", ""))}</div><p>{e(call.get("text", ""))}</p></div>' if call.get("text") else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{e(title or g.get("title", "Guide"))}</title>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@600;700;800&family=Lora:ital,wght@0,400;0,600;1,400&display=swap" rel="stylesheet">
<style>
@page{{size:A4;margin:16mm 0;background:#000}}
html,body{{background:#000;margin:0;-webkit-print-color-adjust:exact;print-color-adjust:exact}}
body{{color:#e9e4d6;font:15.5px/1.6 Lora,Georgia,serif}}
.w{{padding:0 25mm}}
.head{{border-top:1px solid #c9a227;border-bottom:1px solid #c9a227;padding:22px 0 26px;text-align:center;margin-bottom:26px}}
.eyebrow,.cap,.foot .cap{{font:700 11px Poppins,sans-serif;letter-spacing:.42em;text-transform:uppercase;color:#a8945a}}
h1{{font:800 44px/1.15 Poppins,sans-serif;color:#d4a72c;margin:14px 0 8px;letter-spacing:-.01em}}
.sub{{font-style:italic;font-size:17px;color:#e9e4d6}}
.tags{{font:700 10.5px Poppins,sans-serif;letter-spacing:.22em;color:#c9a227;margin-top:10px}}
h2{{font:700 21px Poppins,sans-serif;color:#d4a72c;margin:30px 0 10px;display:flex;gap:16px;align-items:baseline;break-after:avoid}}
h2 span{{font-weight:800;font-size:24px;color:#b8922a}}
hr.thin{{border:0;border-top:1px solid #4a4026;margin:0 0 14px}}
p{{margin:0 0 12px}}
pre.code{{background:#14120d;border-left:3px solid #c9a227;color:#e2c169;font:13px/1.5 Menlo,"SF Mono",monospace;padding:14px 18px;margin:0 0 14px;white-space:pre-wrap;break-inside:avoid}}
table{{width:100%;border-collapse:collapse;margin:4px 0 16px;font-size:14px;break-inside:avoid}}
th,td{{border:1px solid #3a3322;padding:8px 10px;text-align:left;vertical-align:top;background:#100f0b}}
th{{color:#d4a72c;font-weight:600;width:30%}}
.callout{{border:1.5px solid #c9a227;background:#1a1710;padding:16px 18px;margin:22px 0;break-inside:avoid}}
.callout p{{margin:6px 0 0}}
.foot{{border-top:1px solid #c9a227;margin-top:36px;padding-top:14px;text-align:center;break-inside:avoid}}
.foot .cap{{color:#c9a227}}
.foot i{{color:#a8a08a}} .foot b{{color:#d4a72c;text-decoration:underline}}
</style></head><body><div class="w">
<div class="head"><div class="eyebrow">{e(g.get("eyebrow", "SETUP GUIDE"))}</div><h1>{e(g.get("title", ""))}</h1>
<div class="sub">{e(g.get("subtitle", ""))}</div><div class="tags">{" &nbsp;·&nbsp; ".join(e(t) for t in g.get("tags", []))}</div></div>
{"".join(f"<p>{e(x)}</p>" for x in g.get("intro", []))}
{secs}{callout}
<div class="foot"><div class="cap">That's it &nbsp;·&nbsp; Happy building</div><i>Follow <b>@{HANDLE}</b> on Instagram</i></div>
</div></body></html>"""


def guide(date_, n):
    """The guide his CTA promises, as a PDF in his own style. Built from the repo README so commands are real."""
    d, i = _idea(date_, n)
    repo = next((u for u in [i.get("repo_url")] + i.get("source_urls", []) if u and "github.com/" in u), "")
    readme = ""
    if repo:
        slug = "/".join(urllib.parse.urlparse(repo).path.strip("/").split("/")[:2])
        try:
            import base64
            readme = base64.b64decode(run(["gh", "api", f"repos/{slug}/readme", "--jq", ".content"], 60)).decode("utf-8", "replace")[:16000]
        except Exception as ex:
            log("readme failed:", ex)
    g = ask_claude(f"""Write the setup guide that Instagram creator @{HANDLE} sends to people who comment "{i['cta_keyword']}" on their Reel.
Reel: {i['title']}
Why it matters: {i['why_now']}
Links: {json.dumps([i.get('repo_url')] + i.get('source_urls', []))}
README of the repo (the ONLY source of truth for commands, versions and requirements):
{readme or 'No repo README. Use only the facts above and keep the guide short.'}

Return ONLY JSON:
{{"eyebrow": "CATEGORY · SETUP GUIDE (e.g. CLAUDE CODE PLUGIN · SETUP GUIDE)", "title": "tool name", "subtitle": "one line, what it does for you",
 "tags": ["3 to 5 short facts in caps, e.g. FREE, MIT, MAC ONLY, ~20 MB DOWNLOAD"],
 "intro": ["1 to 2 short paragraphs: what happens when you use it"],
 "sections": [{{"title": "Check requirements|Install|Turn it on|Use it|...", "blocks": [
    {{"type": "text", "text": ""}}, {{"type": "code", "text": "exact command"}}, {{"type": "table", "rows": [["label", "value"]]}}]}}],
 "callout": {{"title": "SHORT CAPS TITLE (e.g. WHAT IT CONNECTS TO, GOOD TO KNOW)", "text": "privacy, cost or gotcha worth knowing"}},
 "dm": "2 line Instagram DM in their casual voice that comes with the guide link, use {{LINK}} where the link goes"}}
3 to 5 sections, numbered steps from requirements to first use. Section titles have NO numbers (the PDF numbers them). Use tables for requirements and controls/options. Every command must appear in the README. Plain words, no em dashes.""", timeout=400, kind="guide")
    kw = re.sub(r"\W", "", i["cta_keyword"].lower()) or f"idea{n}"
    # The PDF is named after the video: "REA let your agent reverse engineer any app.pdf".
    nice = re.sub(r"\s+", " ", re.sub(r'[\\/:*?"<>|]+', " ", i["title"])).strip()[:90] or kw
    stem = re.sub(r"[^a-z0-9]+", "-", nice.lower()).strip("-") or kw
    gdir = DATA / "guides"
    gdir.mkdir(exist_ok=True)
    (gdir / f"{kw}.html").write_text(render_guide(g, nice))
    pdf = gdir / f"{stem}.pdf"
    run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--virtual-time-budget=8000",
         f"--print-to-pdf={pdf}", (gdir / f"{kw}.html").as_uri()], 120)
    # Copy to ~/Downloads where he keeps his guides, never overwriting one that is already there.
    dest, k = Path.home() / "Downloads" / f"{nice}.pdf", 2
    while dest.exists():
        dest, k = Path.home() / "Downloads" / f"{nice} ({k}).pdf", k + 1
    shutil.copy(pdf, dest)
    dm = g.get("dm", "Here's the guide: {LINK}")
    (gdir / f"{kw}.md").write_text(dm)
    meta = {"keyword": kw, "title": i["title"], "filename": f"{nice}.pdf", "date": date_, "repo": repo, "pdf": f"/guides/{pdf.name}", "downloads": str(dest),
            "made_at": datetime.now().isoformat(timespec="seconds")}
    (gdir / f"{kw}.json").write_text(json.dumps(meta))  # a new PDF clears any old Drive link
    print(json.dumps({**meta, "guide": dm}, ensure_ascii=False))


def render_slide(s, k, total, handle="@" + HANDLE):
    """One 1080x1350 slide in his look (black, gold, Poppins + Lora)."""
    e = html.escape
    body = "".join(f"<p>{e(x)}</p>" for x in ([s["body"]] if isinstance(s.get("body"), str) else s.get("body", [])))
    code = f'<pre>{e(s["code"])}</pre>' if s.get("code") else ""
    cover = k == 1
    return f"""<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@600;700;800&family=Lora:ital,wght@0,400;0,600;1,400&display=swap" rel="stylesheet">
<style>
html,body{{margin:0;width:1080px;height:1350px;background:#000}}
.s{{box-sizing:border-box;width:1080px;height:1350px;padding:90px 80px;display:flex;flex-direction:column;justify-content:center;border:2px solid #c9a227;color:#e9e4d6;font:38px/1.45 Lora,Georgia,serif;position:relative}}
.n{{font:700 26px Poppins,sans-serif;letter-spacing:.4em;color:#a8945a;margin-bottom:34px}}
h1{{font:800 {96 if cover else 70}px/1.1 Poppins,sans-serif;color:#d4a72c;margin:0 0 36px;letter-spacing:-.01em}}
p{{margin:0 0 24px}}
pre{{background:#14120d;border-left:6px solid #c9a227;color:#e2c169;font:30px/1.5 Menlo,monospace;padding:28px 32px;white-space:pre-wrap;margin:10px 0}}
.f{{position:absolute;left:80px;right:80px;bottom:70px;display:flex;justify-content:space-between;font:700 24px Poppins,sans-serif;letter-spacing:.2em;color:#c9a227}}
</style></head><body><div class="s"><div class="n">{k:02d} / {total:02d}</div><h1>{e(s.get("title", ""))}</h1>{body}{code}
<div class="f"><span>{handle}</span><span>{'SWIPE →' if k < total else 'SAVE THIS'}</span></div></div></body></html>"""


def carousel(date_, n):
    """The carousel as slide PNGs + caption. Slides come from the idea's facts; the README is used when there is a repo."""
    d, i = _idea(date_, n)
    cdir = DATA / "carousels" / f"{date_}-{int(n)}"
    meta_f = cdir / "meta.json"
    if meta_f.exists():
        return print(meta_f.read_text())
    readme = ""
    m = re.match(r"https://github.com/([\w.-]+/[\w.-]+)", i.get("repo_url") or "")
    if m:
        try:
            readme = get(f"https://raw.githubusercontent.com/{m.group(1)}/HEAD/README.md")[:6000]
        except Exception:
            pass
    c = ask_claude(f"""Write an Instagram carousel for creator @{HANDLE} (AI tools, casual, excited, plain words).
Idea: {i['title']}
Why now: {i['why_now']}
Script (use its facts): {' '.join(s['say'] for s in i['script'])}
Repo README:
{readme or 'none, use only the facts above'}

Return ONLY JSON: {{"slides": [{{"title": "max 8 words", "body": ["1-2 short lines, max 25 words each"], "code": "optional command, only if it appears in the README"}}],
"caption": "line 1: Comment \"{i['cta_keyword']}\" for the guide. line 2: one short line on what the carousel is about", "hashtags": ["#"]}}
3 or 4 slides, never more. Slide 1 is the cover with a hook title and no body. The last slide is the CTA to comment "{i['cta_keyword']}" and follow. One idea per slide. Never invent numbers or commands. No em dashes.""", kind="carousel")
    slides = c["slides"][:4]
    cdir.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^\w .-]", "", i["title"]).strip()[:60]
    dest = Path.home() / "Downloads" / f"{name} carousel"
    dest.mkdir(parents=True, exist_ok=True)
    for k, sl in enumerate(slides, 1):
        h, png = cdir / f"slide-{k}.html", cdir / f"slide-{k}.png"
        h.write_text(render_slide(sl, k, len(slides)))
        run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--virtual-time-budget=8000", "--window-size=1080,1350",
             f"--screenshot={png}", h.as_uri()], 120)
        h.unlink()
        shutil.copy(png, dest / png.name)
    meta = {"date": date_, "n": int(n), "title": i["title"], "slides": [f"/carousels/{cdir.name}/slide-{k}.png" for k in range(1, len(slides) + 1)],
            "caption": c.get("caption", ""), "hashtags": c.get("hashtags", []), "downloads": str(dest)}
    meta_f.write_text(json.dumps(meta, ensure_ascii=False))
    print(json.dumps(meta, ensure_ascii=False))


DRIVE_DIR = "gdrive:Content Desk Guides"


def share(kw):
    """Upload the guide PDF to Google Drive (rclone remote 'gdrive') and get an anyone-with-link URL."""
    meta_f = DATA / "guides" / f"{kw}.json"
    meta = json.loads(meta_f.read_text())
    if not shutil.which("rclone") or "gdrive:" not in run(["rclone", "listremotes"], 20):
        raise SystemExit("Google Drive is not connected yet. In Terminal run: rclone config create gdrive drive scope=drive.file")
    pdf = DATA / meta["pdf"].lstrip("/")
    target = f"{DRIVE_DIR}/{meta.get('filename') or pdf.name}"
    run(["rclone", "copyto", str(pdf), target], 180)
    meta["drive_link"] = run(["rclone", "link", target], 60).strip()
    meta_f.write_text(json.dumps(meta))
    print(json.dumps({"keyword": kw, "drive_link": meta["drive_link"]}))


def hooks(date_, n):
    """5 alternative hooks of different types, cached."""
    f = DATA / "hooks" / f"{date_}-{int(n)}.json"
    if f.exists():
        return print(f.read_text())
    d, i = _idea(date_, n)
    out = ask_claude(f"""Creator @{HANDLE} (Instagram, AI tools, casual and excited voice) will test hooks with Trial Reels.
Idea: {i['title']}
Why now: {i['why_now']}
Current hook: {i['script'][0]['say']}
Script after the hook: {' '.join(s['say'] for s in i['script'][1:3])}

Return ONLY JSON: {{"hooks": [{{"type": "question|number|bold claim|contrarian|curiosity", "say": "spoken hook, max 22 words",
"cover_text": "max 6 words on screen", "why": "one line on why this could beat the current hook"}}]}}
Exactly 5 hooks, one of each type. Use only facts from above. Plain words, no em dashes.""", kind="hooks")
    f.parent.mkdir(exist_ok=True)
    f.write_text(json.dumps(out, ensure_ascii=False))
    print(json.dumps(out, ensure_ascii=False))


# ---------- generate ----------

SCHEMA = """{
 "summary": "2 sentences: what matters in AI today for my audience",
 "announcements": [{"title": "", "url": "", "source": "x|blogs|hackernews|github|...", "why_it_matters": ""}],
 "trending": [{"title": "", "url": "", "platform": "", "hook": "the opening line or opening visual", "why_it_worked": ""}],
 "ideas": [{
   "title": "", "news_date": "YYYY-MM-DD of the news it is based on", "profile_topic": "one topic from my content profile", "why_now": "", "urgency": "today|this week|evergreen",
   "format": "reel|carousel", "score": 1-10, "source_urls": [""], "repo_url": "", "cta_keyword": "ONE word",
   "cover_text": "max 6 words for the Reel cover", "length": "45-60s",
   "script": [
     {"part": "Hook (0-3s)", "say": "", "show": ""},
     {"part": "Intro the repo or tool", "say": "", "show": ""},
     {"part": "What it does", "say": "", "show": ""},
     {"part": "The interesting part", "say": "", "show": ""},
     {"part": "Setup is simple", "say": "", "show": ""},
     {"part": "CTA", "say": "", "show": ""}
   ],
   "caption": "line 1: Comment \"KEYWORD\" for the guide. line 2: one short line on what the Reel is about", "hashtags": ["#"]
 }],
 "today_focus": "one sentence: the single most important thing to do today to grow",
 "radar": [{"topic": "", "platforms": ["x", "reddit", "github", "..."], "heat": 1-5, "note": "one line"}]
}"""


def generate():
    raw = json.loads((RAW / f"{TODAY}.json").read_text())
    profile = (ROOT / "content-profile.md").read_text()
    style = (ROOT / "style-samples.md").read_text()
    past = []
    for f in sorted(OUT.glob("*.json"))[-7:]:
        if f.stem != TODAY:
            past += [i["title"] for i in json.loads(f.read_text()).get("ideas", [])]
    compact = {k: {"status": v["status"], "error": v["error"],
                   "items": [{x: i.get(x) for x in ("title", "url", "text", "metric", "kind", "age_h") if i.get(x) is not None} for i in v["items"][:25]]}
               for k, v in raw["sources"].items()}
    prompt = f"""You are the research producer for Instagram creator @{HANDLE}. Today is {TODAY}.
Goal: help them become a top AI creator fast. They record; you do all research and writing.

# Their content profile
{profile}

# Their real Reel transcripts (copy this voice, pacing and structure exactly)
{style}

# Competitor videos watched today (real transcripts)
{json.dumps(raw.get("watched", []), ensure_ascii=False)[:9000]}

# Raw posts collected today (status per platform)
{json.dumps(compact, ensure_ascii=False)[:60000]}

# Reels they ALREADY MADE (never suggest these topics again unless there is real news about them, and say what is new)
{json.dumps(raw.get("already_made", []), ensure_ascii=False)[:8000]}

# Tools and skills they already have installed (they know these; only use them if there is NEW news today)
{json.dumps(sorted({d.name for d in (Path.home() / ".claude/skills").glob("*") if d.is_dir()} | {d.name for d in (Path.home() / ".claude/plugins/cache").glob("*/*") if d.is_dir()}))}

# Ideas already given in the last 7 days (do not repeat)
{json.dumps(past)}

# How their own recent Reels performed (lean toward what works for them NOW)
{performance_note()}

# Task
Return ONLY a JSON object, no markdown fence, matching:
{SCHEMA}

Rules:
- Exactly 5 announcements, 5 trending, 10 ideas. Make the 10 ideas cover different topics and formats (repo demo, news reaction, side-by-side comparison, tips list, carousel). Set format to carousel for at least 2 ideas (tips lists, comparisons, top-N lists) and reel for the rest. A carousel idea still gets the script field filled (it becomes the voiceover if they turn it into a Reel) so they can post 2 a day without repeating themselves. Only use URLs that appear in the data above. Never invent repos, stars, numbers or links.
- They normally find ideas by scrolling their X For You feed and Instagram Explore. Treat "x" and "instagram" items as the PRIMARY signal of what is hot today: build ideas from what is getting likes and views there, then use GitHub, Reddit, HN and YouTube to find the repo, numbers and proof behind it. If x or instagram failed, say so in the summary.
- FRESHNESS IS THE TOP RULE. Today is {TODAY}. age_h = hours since posted. Build ideas on things that happened in the last 24 hours (age_h <= 24, Reddit top today, HN today, X/IG today, repos created in the last 3 days). A GitHub repo created weeks ago only counts if its stars today are unusually high AND they have not covered it, and the idea must say why it matters today. Never build an idea on news older than 48 hours.
- Every idea's why_now must name the date or hours ago of the news it is based on.
- For every idea that comes from X or Instagram, put that post's URL first in source_urls.
- Rank ideas by: fresh news (last 48h) + big name or big number (stars, benchmark, price) + something they can SHOW on screen (repo, demo, output). Lean toward the formats behind their best Reels in the content profile.
- At least 6 ideas must be a GitHub repo or tool they can show. Prefer Claude skills, Claude Code, agents, MCP, open source alternatives to paid tools.
- Scripts: 110-160 spoken words total, their words, rhythm, stock phrases and CTA from the transcripts above. The CTA asks viewers to comment KEYWORD to get the whole guide in their DMs.
- Hook must work with sound off too: put the cover_text on screen in the first frame.
- "show" = exactly what to put on screen (repo page, star count, demo, terminal, split screen).
- Plain words. No em dashes. No hype words like "game-changer" or "revolutionary".
- If a platform failed, still produce the full digest from the others.
- radar: 4 to 8 topics that show up on 2 or more platforms today, heat 5 = everywhere right now."""
    log("asking claude for ideas and scripts...")
    # Daily run uses Sonnet 5.5 to save plan limits. Set DIGEST_MODEL=claude-opus-5-5 to switch back.
    p = subprocess.run(["claude", "-p", "--model", os.environ.get("DIGEST_MODEL", "claude-sonnet-5-5"), "--output-format", "json"],
                       input=prompt, capture_output=True, text=True, timeout=600, cwd=DATA)
    if p.returncode:
        raise SystemExit("claude failed: " + (p.stderr or p.stdout)[-500:])
    reply = json.loads(p.stdout)
    usage = log_usage("digest", reply)
    log(f"claude usage: {usage['input'] + usage['cache_read'] + usage['cache_write']} input tokens, {usage['output']} output, ${usage['cost_usd']}")
    text = reply["result"]
    digest = json.JSONDecoder().raw_decode(text[text.index("{"):])[0]
    assert len(digest["ideas"]) >= 3, "too few ideas"
    raw_text = json.dumps(raw, ensure_ascii=False)
    found = re.findall(r'https?://[^\s"\)\]]+', json.dumps({k: digest.get(k) for k in ("announcements", "trending", "ideas")}, ensure_ascii=False))
    digest["unverified_links"] = sorted({u for u in found if u not in raw_text})
    if digest["unverified_links"]:
        log("WARNING links not found in collected data:", digest["unverified_links"])
    digest |= {"date": TODAY, "generated_at": datetime.now().isoformat(timespec="seconds"), "usage": usage,
               "platforms": {k: {"status": v["status"], "count": len(v["items"]), "error": v["error"]}
                             for k, v in raw["sources"].items()},
               "watched": [{x: w.get(x) for x in ("title", "url", "duration")} for w in raw.get("watched", [])]}
    attach_images(digest, raw)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{TODAY}.json").write_text(json.dumps(digest, indent=1, ensure_ascii=False))
    md = to_markdown(digest)
    (OUT / f"digest-{TODAY}.md").write_text(md)
    log("digest saved:", OUT / f"digest-{TODAY}.md")
    for n, idea in enumerate(digest["ideas"]):  # carousel ideas arrive with their slides ready
        if idea.get("format") == "carousel":
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    carousel(TODAY, n)
                log(f"carousel {n} ready")
            except Exception as ex:
                log(f"carousel {n} failed:", str(ex)[:120])


def attach_images(digest, raw):
    """2-3 hook images per idea: GitHub repo card + thumbnails of the posts it came from. Saved locally (IG links expire)."""
    found = {}
    for name, src in raw["sources"].items():
        for i in src["items"]:
            if i.get("image") and i.get("url"):
                label = {"x": "X post", "instagram": "Instagram post", "youtube": "YouTube thumbnail", "reddit": "Reddit post"}.get(name, name)
                found[i["url"]] = (i["image"], label)
                m = re.search(r"/status/(\d+)", i["url"])
                if m:
                    found["x:" + m.group(1)] = (i["image"], label)
    imgdir = DATA / "img"
    imgdir.mkdir(exist_ok=True)
    for n, idea in enumerate(digest["ideas"]):
        cands = []
        for u in [idea.get("repo_url")] + idea.get("source_urls", []):
            if not u:
                continue
            gh = re.match(r"https://github.com/([\w.-]+/[\w.-]+)", u)
            m = re.search(r"/status/(\d+)", u)
            if gh:
                cands.append((f"https://opengraph.githubassets.com/1/{gh.group(1)}", "GitHub repo card", u))
            elif u in found or (m and "x:" + m.group(1) in found):
                img, label = found.get(u) or found["x:" + m.group(1)]
                cands.append((img, label, u))
        idea["images"], seen = [], set()
        for img, label, link in cands:
            if img in seen or len(idea["images"]) == 3:
                continue
            seen.add(img)
            f = imgdir / f"{digest['date']}-{n}-{len(idea['images'])}.jpg"
            try:
                req = urllib.request.Request(img, headers={"User-Agent": UA, "Referer": "https://www.instagram.com/"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    f.write_bytes(r.read())
                idea["images"].append({"src": f"/img/{f.name}", "label": label, "link": link})
            except Exception as e:
                log("  image failed:", label, str(e)[:80])


def to_markdown(d):
    L = [f"# Digest {d['date']}", "", d.get("summary", ""), "", f"**Today's focus:** {d.get('today_focus', '')}", "",
         "## Platform status", ""]
    L += [f"- {k}: {v['status']} ({v['count']} items){'  ' + v['error'] if v['status'] != 'ok' else ''}" for k, v in d["platforms"].items()]
    L += ["", "## Top 5 announcements", ""]
    L += [f"{n}. [{a['title']}]({a['url']}) ({a['source']}). {a['why_it_matters']}" for n, a in enumerate(d["announcements"], 1)]
    L += ["", "## Top 5 trending", ""]
    L += [f"{n}. [{t['title']}]({t['url']}) ({t['platform']})\n   - Hook: {t['hook']}\n   - Why it worked: {t['why_it_worked']}"
          for n, t in enumerate(d["trending"], 1)]
    L += ["", "## 10 content ideas", ""]
    for n, i in enumerate(d["ideas"], 1):
        L += [f"### {n}. {i['title']}  (score {i['score']}/10, {i['urgency']})", "",
              f"- Topic: {i['profile_topic']}", f"- Why now: {i['why_now']}", f"- Cover text: **{i['cover_text']}**",
              f"- Comment keyword: `{i['cta_keyword']}`", f"- Sources: {' '.join(i['source_urls'])}", "", "| Part | Say | Show |", "|---|---|---|"]
        L += [f"| {s['part']} | {s['say']} | {s['show']} |" for s in i["script"]]
        L += ["", f"Caption: {i['caption']}", "", " ".join(i["hashtags"]), ""]
    return "\n".join(L)


def watch(url):
    t = transcribe(url)
    prompt = f"""Break down this short video for creator @{HANDLE} (AI tools, Claude, GitHub repos).
Transcript ({t['duration']}):
{t['transcript']}

Return ONLY JSON: {{"hook": "first line", "hook_type": "question|bold claim|number|curiosity|news", "structure": ["beat 1", "..."],
"why_it_works": "", "what_to_steal": "", "my_version_hook": "a hook in their style for the same topic", "cta": ""}}
Plain words, no em dashes."""
    p = subprocess.run(["claude", "-p", "--output-format", "json"], input=prompt, capture_output=True, text=True, timeout=300, cwd=DATA)
    text = json.loads(p.stdout)["result"]
    print(json.dumps({"url": url, **t, **json.loads(text[text.index("{"): text.rindex("}") + 1])}, ensure_ascii=False))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "collect":
        collect()
    elif cmd == "generate":
        generate()
    elif cmd == "watch" and len(sys.argv) == 3:
        watch(sys.argv[2])
    elif cmd in ("guide", "hooks", "carousel") and len(sys.argv) == 4:
        {"guide": guide, "hooks": hooks, "carousel": carousel}[cmd](sys.argv[2], sys.argv[3])
    elif cmd == "stats":
        stats()
    elif cmd == "share" and len(sys.argv) == 3 and re.fullmatch(r"\w+", sys.argv[2]):
        share(sys.argv[2])
    else:
        sys.exit(__doc__)
