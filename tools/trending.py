#!/usr/bin/env python3
"""
What's popular right now: the TV shows and films people looked up most on Wikipedia over the last week.

  python tools/trending.py            writes harvest/trending.json

Only titles with a Wikiquote page are kept, because that's where the quotes come from. The overnight harvest
collects quotes from these first, and the hangman's word of the day is picked from them (tools/build_hangman.py).
Wikipedia page views are a free, daily measure of current interest (IMDb's popularity chart can't be scraped).
"""
import json, os, re, sys, time, urllib.parse, urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "harvest", "trending.json")
UA = "MoiraLexiconTrending/1.0 (+https://github.com/ThomasSchmierer/Moira-Lexicon)"
TOP = "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia/all-access/{:%Y/%m/%d}"
WP = "https://en.wikipedia.org/w/api.php"
WD = "https://www.wikidata.org/w/api.php"

SCREEN = re.compile(r"\b(television|tv|web|streaming|animated|anime|reality|drama|comedy|sketch)\b[\w\s,-]*\b(series|serial|show|programme|program|sitcom|miniseries)\b"
                    r"|\bsitcom\b|\bminiseries\b|\bfilm\b|\bmovie\b", re.I)
NOT = re.compile(r"\b(actor|actress|director|producer|writer|screenwriter|filmmaker|presenter|host|comedian|singer|rapper|musician|band|album|song|"
                 r"soundtrack|character|episode|season|franchise|company|studio|network|channel|festival|award|awards|ceremony|video game|"
                 r"novel|book|comic|manga|film series|media franchise|footballer|cricketer|politician|list|lists|filmography|"
                 r"television personality|youtuber|streamer|journalist|critic|wrestler|athlete|player|cinematographer|composer)\b", re.I)

def get(url, params=None, tries=5):
    if params: url += "?" + urllib.parse.urlencode({**params, "format": "json", "formatversion": "2", "maxlag": "5"})
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r: return json.loads(r.read())
        except Exception as e:
            if attempt == tries - 1: raise
            time.sleep(3 * (attempt + 1))

def top_articles(days=7):
    """Total English Wikipedia views over the last few days, for the top 1,000 articles of each day."""
    views = Counter()
    end = datetime.now(timezone.utc) - timedelta(days=1)            # yesterday is the newest full day
    for i in range(days):
        day = end - timedelta(days=i)
        try: items = get(TOP.format(day))["items"][0]["articles"]
        except Exception as e:
            print(f"  (no page-view list for {day:%Y-%m-%d}: {e})"); continue
        for a in items:
            t = a["article"]
            if ":" in t or t in ("Main_Page", "-") or t.startswith("Special"): continue
            views[t.replace("_", " ")] += a["views"]
        time.sleep(0.3)
    return views

def describe(titles):
    """Short description and Wikidata id for each Wikipedia article."""
    out = {}
    for i in range(0, len(titles), 50):
        d = get(WP, {"action": "query", "prop": "description|pageprops", "ppprop": "wikibase_item", "titles": "|".join(titles[i:i + 50]), "redirects": "1"})
        q = d.get("query", {})
        back = {r["to"]: r["from"] for r in q.get("redirects", [])}
        back.update({n["to"]: n["from"] for n in q.get("normalized", [])})
        for p in q.get("pages", []):
            src = back.get(p["title"], p["title"])
            out[src] = (p.get("description", ""), p.get("pageprops", {}).get("wikibase_item", ""), p["title"])
        time.sleep(0.5)
    return out

def quote_pages(qids):
    """Which of these have a Wikiquote page (from Wikidata's site links)."""
    out = {}
    for i in range(0, len(qids), 50):
        d = get(WD, {"action": "wbgetentities", "ids": "|".join(qids[i:i + 50]), "props": "sitelinks", "sitefilter": "enwikiquote"})
        for qid, ent in d.get("entities", {}).items():
            link = ent.get("sitelinks", {}).get("enwikiquote")
            if link: out[qid] = link["title"]
        time.sleep(0.5)
    return out

def main():
    views = top_articles(7)
    cands = [t for t, _ in views.most_common(2000)]
    print(f"{len(views)} popular articles this week; checking the top {len(cands)} for TV shows and films")
    info = describe(cands)
    screen = []
    for t in cands:
        desc, qid, canon = info.get(t, ("", "", t))
        if qid and SCREEN.search(desc) and not NOT.search(desc): screen.append((t, desc, qid, canon))
    wq = quote_pages([q for _, _, q, _ in screen])
    seen, titles = set(), []
    for t, desc, qid, canon in screen:
        if qid not in wq or qid in seen: continue
        seen.add(qid)
        film = bool(re.search(r"\b(film|movie)\b", desc, re.I)) and not re.search(r"\b(series|television|tv|sitcom|show)\b", desc, re.I)
        titles.append({"title": canon, "wikiquote": wq[qid], "kind": "film" if film else "tv", "description": desc, "views": views[t]})
    titles.sort(key=lambda x: -x["views"])
    for i, t in enumerate(titles, 1): t["rank"] = i
    data = {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "measure": "English Wikipedia page views over the last 7 days",
            "screen_titles_found": len(screen), "titles": titles[:40]}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"{len(screen)} TV shows and films in this week's most-viewed; {len(titles)} have quote pages. Top ten:")
    for t in titles[:10]: print(f"  {t['rank']:>2}. {t['title']} ({t['kind']}, {t['views']:,} views) → Wikiquote: {t['wikiquote']}")

if __name__ == "__main__":
    main()
