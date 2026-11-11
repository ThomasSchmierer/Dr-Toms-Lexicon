#!/usr/bin/env python3
"""
Moira's Lexicon reviewer: approves harvested words automatically.

For every word in the harvest spreadsheets it
  1. looks the word up in two dictionaries, WordNet and Wiktionary,
  2. picks the meaning that fits the quotes, and checks both dictionaries agree on it,
  3. rejects names, fragments ("wouldn"), rude words, misspellings, and everyday words,
  4. merges every sighting of the word across all shows and books into one entry, so a
     word used in Frasier, Blackadder and Veep lists all three.

  python tools/review.py fetch     look up new words on Wiktionary (cached in harvest/wiktionary.json)
  python tools/review.py approve   decide; writes approved-*.json, xref.json, counts.json, harvest/REVIEW.md
  python tools/review.py all       both

To overrule a decision, put y (approve) or n (reject) in the "keep" column of any harvest
spreadsheet. A meaning typed into "definition" replaces the dictionary one.
"""
import argparse, csv, glob, hashlib, html, json, os, re, sys, time, urllib.parse, urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HARVEST = os.path.join(ROOT, "harvest")
CACHE = os.path.join(HARVEST, "wiktionary.json")
DECISIONS = os.path.join(HARVEST, "decisions.json")
UA = "MoiraLexiconReviewer/1.0 (+https://github.com/ThomasSchmierer/Moira-Lexicon)"
WIKT = "https://en.wiktionary.org/w/api.php"

FRAGMENT = re.compile(r"^(wouldn|couldn|shouldn|didn|doesn|isn|wasn|weren|hasn|haven|hadn|aren|mustn|needn|mightn|oughtn|shan|ain|innit|gonna|wanna|gotta|dunno|lemme|gimme|kinda|sorta|outta|y'all)$")
BLOCK = re.compile(r"(rape|whore|bawd|cuckold|strumpet|harlot|slut|cunt|fuck|shit|piss|nigg|negro|fag|dyke|retard|tranny|spic|kike|wog|coon|"
                   r"penis|vagin|genital|semen|sperm|nipple|orgas|masturb|erotic|sexual|porn|incest|suicide|bitch|bastard|wank|bollock|arse|twat|"
                   r"nazi|anus|anal|faec|fece|bowel|vomit|bestial|pederast|nympho|fellat|cunnil|sodom|copulat|coitus|coital|pubic|pubes|"
                   r"breast|buttock|prostitut|testic|bugger|sodding|spunk|knob|dick|cock|tits|boob|shag|bonk|tosser|wazz|crap)")
PROFANE = re.compile(r"(?i)\b(fuck\w*|motherf\w*|shit\w*|bullshit\w*|horseshit|cunt\w*|piss\w*|bitch\w*|bastard\w*|wank\w*|arse|arses|arsehole\w*|"
                     r"asshole\w*|dumbass|twat\w*|bollock\w*|cocks?|cocksucker\w*|dicks?|dickhead\w*|pricks?|tosser\w*|"
                     r"bugger\w*|sodding|slut\w*|whore\w*|fag|fags|faggot\w*|nigg\w*|retard\w*|spunk\w*|tits|titties|boobs?|shag\w*|horny|porn\w*|"
                     r"penis\w*|vagina\w*|masturbat\w*|orgasm\w*|erection\w*|dildo\w*|blowjob\w*|handjob\w*|wanker\w*|knob\w*|bellend\w*|"
                     r"clit\w*|anal|anus|rape\w*|rapist\w*|incest\w*|paedo\w*|pedo\w*|nazi\w*|kike\w*|spic|spics|wog|wogs|coon|coons|tranny\w*|"
                     r"poof\w*|goddamn\w*|goddam)\b")
BAD_LABELS = {"vulgar", "offensive", "ethnic slur", "slur", "racial slur", "obscene", "sexual", "sexuality", "sex", "sexual slang",
              "bdsm", "pornography", "homophobic", "misogynistic", "ableist", "very rare vulgar", "sexually"}
BAD_DOMAINS = {"disparagement", "obscenity", "vulgarism", "ethnic_slur", "profanity"}
SPELLING = ("misspelling of", "pronunciation spelling of", "eye dialect of", "nonstandard spelling of", "nonstandard form of",
            "censored spelling of", "contraction of", "abbreviation of", "initialism of", "acronym of", "clipping of", "ellipsis of",
            "deliberate misspelling of", "eye-dialect of")
INFLECTION = re.compile(r"^(en-)?(plural|inflection|infl|past tense|past participle|present participle|third-person singular|third person singular|"
                        r"comparative|superlative|simple past|ing form|irregular plural|gerund|participle|verb form|archaic third-person singular|"
                        r"en-past|past|second-person singular|archaic second-person singular)( form| noun)? of$")
POSMAP = {"Noun": "n", "Verb": "v", "Adjective": "a", "Adverb": "r", "Interjection": "i", "Proper noun": "prop", "Phrase": "phr",
          "Prepositional phrase": "phr", "Contraction": "contr", "Preposition": "other", "Conjunction": "other", "Pronoun": "other",
          "Determiner": "other", "Numeral": "other", "Particle": "other", "Prefix": "affix", "Suffix": "affix", "Symbol": "other"}
LANGS = {
 "en": "English", "enm": "Middle English", "ang": "Old English", "sco": "Scots", "frm": "Middle French", "fro": "Old French", "fr": "French",
 "xno": "Anglo-Norman", "nrf": "Norman", "pcd": "Picard", "wa": "Walloon", "la": "Latin", "la-lat": "Late Latin", "la-med": "Medieval Latin",
 "la-new": "New Latin", "la-vul": "Vulgar Latin", "la-ecc": "Ecclesiastical Latin", "la-cla": "Classical Latin", "itc-ola": "Old Latin",
 "LL.": "Late Latin", "ML.": "Medieval Latin", "NL.": "New Latin", "VL.": "Vulgar Latin", "grc": "Ancient Greek", "el": "Greek",
 "gkm": "Byzantine Greek", "grc-koi": "Koine Greek", "non": "Old Norse", "da": "Danish", "sv": "Swedish", "no": "Norwegian",
 "nb": "Norwegian", "nn": "Norwegian", "is": "Icelandic", "fo": "Faroese", "de": "German", "gmh": "Middle High German",
 "goh": "Old High German", "gml": "Middle Low German", "nds": "Low German", "nds-de": "Low German", "odt": "Old Dutch", "dum": "Middle Dutch",
 "nl": "Dutch", "af": "Afrikaans", "fy": "West Frisian", "ofs": "Old Frisian", "osx": "Old Saxon", "got": "Gothic", "frk": "Frankish",
 "gem-pro": "Proto-Germanic", "gmw-pro": "Proto-West Germanic", "ine-pro": "Proto-Indo-European", "itc-pro": "Proto-Italic",
 "grk-pro": "Proto-Hellenic", "cel-pro": "Proto-Celtic", "it": "Italian", "es": "Spanish", "pt": "Portuguese", "ca": "Catalan",
 "oc": "Occitan", "pro": "Old Occitan", "gl": "Galician", "osp": "Old Spanish", "roa-opt": "Old Portuguese", "ro": "Romanian",
 "lad": "Ladino", "vec": "Venetian", "nap": "Neapolitan", "scn": "Sicilian", "ar": "Arabic", "fa": "Persian", "pal": "Middle Persian",
 "peo": "Old Persian", "tr": "Turkish", "ota": "Ottoman Turkish", "sa": "Sanskrit", "hi": "Hindi", "ur": "Urdu", "bn": "Bengali",
 "ta": "Tamil", "te": "Telugu", "pi": "Pali", "mr": "Marathi", "gu": "Gujarati", "pa": "Punjabi", "ml": "Malayalam", "kn": "Kannada",
 "pra": "Prakrit", "inc-pra": "Prakrit", "ga": "Irish", "sga": "Old Irish", "mga": "Middle Irish", "gd": "Scottish Gaelic", "cy": "Welsh",
 "wlm": "Middle Welsh", "owl": "Old Welsh", "br": "Breton", "kw": "Cornish", "gv": "Manx", "xtg": "Gaulish", "he": "Hebrew",
 "hbo": "Hebrew", "yi": "Yiddish", "arc": "Aramaic", "syc": "Classical Syriac", "ru": "Russian", "pl": "Polish", "cs": "Czech",
 "uk": "Ukrainian", "sh": "Serbo-Croatian", "sl": "Slovene", "bg": "Bulgarian", "cu": "Old Church Slavonic", "hu": "Hungarian",
 "fi": "Finnish", "et": "Estonian", "ja": "Japanese", "zh": "Chinese", "cmn": "Mandarin", "yue": "Cantonese", "nan": "Min Nan",
 "ko": "Korean", "ms": "Malay", "id": "Indonesian", "jv": "Javanese", "tl": "Tagalog", "haw": "Hawaiian", "mi": "Maori", "sm": "Samoan",
 "to": "Tongan", "sw": "Swahili", "zu": "Zulu", "xh": "Xhosa", "nci": "Classical Nahuatl", "nah": "Nahuatl", "qu": "Quechua",
 "tpw": "Old Tupi", "tpn": "Tupinamba", "egy": "Egyptian", "cop": "Coptic", "akk": "Akkadian", "sux": "Sumerian", "hy": "Armenian",
 "ka": "Georgian", "sq": "Albanian", "eu": "Basque", "mt": "Maltese", "rom": "Romani", "lt": "Lithuanian", "lv": "Latvian",
 "aus-pam": "an Aboriginal Australian language", "pjt": "Pitjantjatjara", "xdk": "Dharug", "wyb": "Wiradjuri", "alq": "Algonquin",
 "cr": "Cree", "oj": "Ojibwe", "nv": "Navajo", "esx": "an Inuit language", "iu": "Inuktitut", "kl": "Greenlandic", "ain": "Ainu",
 "th": "Thai", "vi": "Vietnamese", "my": "Burmese", "km": "Khmer", "bo": "Tibetan", "mn": "Mongolian", "uz": "Uzbek", "kk": "Kazakh",
 "az": "Azerbaijani", "ku": "Kurdish", "ps": "Pashto", "sd": "Sindhi", "ne": "Nepali", "si": "Sinhala", "dra-pro": "Proto-Dravidian",
 "sem-pro": "Proto-Semitic", "xcl": "Old Armenian", "ett": "Etruscan", "phn": "Phoenician", "gmq-pro": "Proto-Norse", "gmq-oda": "Old Danish",
 "gmq-osw": "Old Swedish", "ML": "Medieval Latin", "LL": "Late Latin", "NL": "New Latin", "frc": "Cajun French", "fr-CA": "Canadian French",
 "en-GB": "British English", "en-US": "American English", "en-AU": "Australian English",
}
ETY_LINK = {"inh": "", "der": "", "bor": "", "lbor": "", "slbor": "", "ubor": "", "uder": "", "obor": "", "lder": "",
            "inh+": "Inherited from ", "der+": "Derived from ", "bor+": "Borrowed from ", "lbor+": "Learned borrowing from ",
            "slbor+": "Semi-learned borrowing from ", "cal": "Calque of ", "calque": "Calque of ", "cal+": "Calque of ",
            "sl": "Semantic loan from ", "semantic loan": "Semantic loan from ", "psm": "Phono-semantic matching of ",
            "inherited": "", "derived": "", "borrowed": "", "learned borrowing": "Learned borrowing from ",
            "translit": "Transliteration of ", "pcal": "Partial calque of "}
SHOW_YEARS = {
 "A Bit of Fry and Laurie": "1989–1995", "A Few Good Men": "1992", "A Mighty Wind": "2003", "Absolutely Fabulous": "1992–2012",
 "Best in Show": "2000", "Black Books": "2000–2004", "Blackadder": "1983–1989", "Cheers": "1982–1993", "Dad's Army": "1968–1977",
 "Doctor Who": "1963–", "Downton Abbey": "2010–2015", "Father Ted": "1995–1998", "Fawlty Towers": "1975–1979",
 "Four Weddings and a Funeral": "1994", "Frasier": "1993–2004", "Gilmore Girls": "2000–2007", "Gosford Park": "2001",
 "Green Wing": "2004–2006", "Hot Fuzz": "2007", "Jeeves and Wooster": "1990–1993", "Kath & Kim": "2002–2007",
 "Keeping Up Appearances": "1990–1995", "Love Actually": "2003", "Modern Family": "2009–2020", "Monty Python's Flying Circus": "1969–1974",
 "Mr. Bean": "1990–1995", "Only Fools and Horses": "1981–2003", "Peep Show": "2003–2015", "Red Dwarf": "1988–", "Schitt's Creek": "2015–2020",
 "Second City Television": "1976–1984", "SCTV": "1976–1984", "Shaun of the Dead": "2004", "Sherlock": "2010–2017", "Spaced": "1999–2001",
 "Sports Night": "1998–2000", "Studio 60 on the Sunset Strip": "2006–2007", "The Death of Stalin": "2017", "The Gilded Age": "2022–",
 "The IT Crowd": "2006–2013", "The League of Gentlemen": "1999–2002", "The Newsroom": "2012–2014", "The Office": "2001–2003",
 "The Social Network": "2010", "The Thick of It": "2005–2012", "The Thin Blue Line": "1995–1996", "The Vicar of Dibley": "1994–2007",
 "The West Wing": "1999–2006", "The Young Ones": "1982–1984", "This Is Spinal Tap": "1984", "Toast of London": "2012–2015",
 "Veep": "2012–2019", "Waiting for Guffman": "1996", "Wings": "1990–1997", "Yes Minister": "1980–1984", "In the Loop": "2009",
 "Yes, Prime Minister": "1986–1988", "Brass Eye": "1997–2001", "I'm Alan Partridge": "1997–2002", "Arrested Development": "2003–2019",
 "30 Rock": "2006–2013", "Parks and Recreation": "2009–2015", "Succession": "2018–2023", "Fleabag": "2016–2019",
}
OLD_KEYS = {"Schitt's Creek": "sc", "Frasier": "fr", "Downton Abbey": "da", "Kath & Kim": "kk", "The Thick of It": "toi", "Father Ted": "ft"}

# ---------------------------------------------------------------- helpers
def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError): return default

def save_json(path, data, indent=None):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=indent, separators=None if indent else (",", ":"))
    os.replace(tmp, path)

def show_name(title): return re.sub(r"\s*\((?:[^)]*(?:TV series|film|series)[^)]*)\)\s*$", "", title).strip()

def initials(s): return "".join(w[0] for w in re.findall(r"[A-Za-z][\w'-]*", s)[:2]).upper() or "?"

def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")

def read_rows():
    rows = []
    for path in sorted(glob.glob(os.path.join(HARVEST, "*.csv"))):
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                r["file"] = os.path.basename(path)
                r["book"] = "gutenberg.org" in r.get("source", "")
                r["word"] = r.get("word", "").strip().lower()
                if r["word"]: rows.append(r)
    return rows

def prefilter(tok):
    if "'" in tok or "’" in tok or FRAGMENT.match(tok): return "fragment of a longer word or a contraction"
    if BLOCK.search(tok): return "rude or upsetting"
    if not re.fullmatch(r"[a-z][a-z-]*[a-z]", tok): return "not a plain word"
    return ""

# ---------------------------------------------------------------- Wiktionary: fetching
def wikt_batch(titles):
    params = {"action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main", "titles": "|".join(titles),
              "format": "json", "formatversion": "2", "maxlag": "5"}
    url = WIKT + "?" + urllib.parse.urlencode(params)
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
            with urllib.request.urlopen(req, timeout=90) as r: data = json.loads(r.read())
        except Exception as e:
            print(f"    retrying ({e})"); time.sleep(5 * (attempt + 1)); continue
        if data.get("error", {}).get("code") == "maxlag": time.sleep(5); continue
        return data.get("query", {})
    raise RuntimeError("Wiktionary is not answering; try again later.")

def fetch(words, limit=None):
    cache = load_json(CACHE, {})
    todo = [w for w in dict.fromkeys(list(words) + [k for k, v in cache.items() if v.get("s") and v.get("v", 1) < PARSER_VERSION])
            if w not in cache or (cache[w].get("s") and cache[w].get("v", 1) < PARSER_VERSION)]
    if limit: todo = todo[:limit]
    print(f"Wiktionary: {len(cache)} words cached, {len(todo)} to look up")
    rounds = 0
    while todo and rounds < 4:
        rounds += 1; follow = []
        for i in range(0, len(todo), 50):
            batch = todo[i:i + 50]
            q = wikt_batch(batch)
            norm = {n["from"]: n["to"] for n in q.get("normalized", [])}
            got = {}
            for p in q.get("pages", []):
                if p.get("missing"): got[p["title"]] = {"m": 1}
                elif p.get("revisions"):
                    got[p["title"]] = parse_page(p["revisions"][0]["slots"]["main"]["content"])
            for w in batch:
                t = norm.get(w, w)
                if t in got:
                    cache[w] = got[t]
                    for s in cache[w].get("s", []):              # also look up the word it's a form of
                        if s[3] and s[4] and re.fullmatch(r"[^\W\d_]+(?:[ '-][^\W\d_]+)*", s[4]) and s[4] == s[4].lower() and (s[4] not in cache or cache[s[4]].get("v", 1) < PARSER_VERSION):
                            follow.append(s[4])
            time.sleep(1.0)                                       # one request a second
            if (i // 50) % 20 == 19:
                save_json(CACHE, cache); print(f"    {i + 50} looked up…")
        todo = [w for w in dict.fromkeys(follow) if w not in cache or (cache[w].get("s") and cache[w].get("v", 1) < PARSER_VERSION)]
    save_json(CACHE, cache)
    print(f"Wiktionary: {len(cache)} words cached")
    return cache

# ---------------------------------------------------------------- Wiktionary: reading wikitext
def split_params(inner):
    parts = inner.split("|")
    name, pos, named = parts[0].strip(), [], {}
    for p in parts[1:]:
        m = re.match(r"^\s*([A-Za-z][A-Za-z0-9_-]*)\s*=(.*)$", p, re.S)
        if m: named[m.group(1)] = m.group(2).strip()
        else: pos.append(p.strip())
    return name, pos, named

def lang(code): return LANGS.get(code, "")

def ital(w): return f"<i>{w}</i>" if w and w != "-" else ""

def gloss(named, pos, idx):
    g = named.get("t") or named.get("gloss") or (pos[idx] if len(pos) > idx else "")
    return f" (“{g}”)" if g else ""

PARSER_VERSION = 2
AFFIX_RELS = {"af", "affix", "com", "compound", "suf", "suffix", "pre", "prefix", "conf", "confix", "surf", "univ"}
REL_WORDS = {"inh": "from", "der": "from", "bor": "borrowed from", "lbor": "learned borrowing from", "slbor": "semi-learned borrowing from",
             "ubor": "unadapted borrowing from", "obor": "orthographic borrowing from", "cal": "calque of", "pcal": "partial calque of",
             "sl": "semantic loan from", "bf": "back-formation from", "clip": "clipping of", "abbr": "abbreviation of", "blend": "blend of",
             "dbt": "doublet of", "psm": "phono-semantic matching of", "translit": "transliteration of", "influence": "influenced by",
             "cog": "", "ncog": "", "noncog": ""}

def mods_split(t):
    """'la:word<t:gloss><ety:bor<grc:x>>' -> ('la', 'word', {'t': 'gloss', 'ety': 'bor<grc:x>'})"""
    i = t.find("<")
    core, rest = (t, "") if i < 0 else (t[:i], t[i:])
    m = re.match(r"^([a-z]{2,3}(?:-[a-z]{2,5})*):(.+)$", core.strip())
    code, word = (m.group(1), m.group(2)) if m else ("", core.strip())
    mods, depth, buf = {}, 0, ""
    for ch in rest:
        if ch == "<":
            if depth: buf += ch
            depth += 1
        elif ch == ">":
            depth -= 1
            if depth: buf += ch
            else:
                k, _, v = buf.partition(":"); mods.setdefault(k.strip(), v); buf = ""
        elif depth: buf += ch
    return code, word.strip(), mods

def strip_mods(t): return mods_split(t)[1] if "<" in t else t

def render_ety(pos, named, info):
    """Wiktionary's newer {{ety|en|:bor|fr:word|:der|la:word|text=+}} template."""
    want_text = named.get("text", "").strip() not in ("", "0", "no", "-")
    groups, cur = [], None
    for a in pos[1:]:
        if a.startswith(":"): cur = [a[1:].strip(), []]; groups.append(cur)
        elif cur is not None and a: cur[1].append(a)
    pieces = []
    def nested(mods, depth=0):
        out = ""
        e = mods.get("ety")
        if e and depth < 4:
            j = e.find("<")
            rel, inner = (e[:j], e[j + 1:-1]) if j > 0 and e.endswith(">") else (e, "")
            if inner:
                c, w, m2 = mods_split(inner)
                if lang(c): info["origins"].append((lang(c), w))
                out = f", {REL_WORDS.get(rel, 'from') or 'from'} {lang(c)} {ital(w)}".rstrip() + nested(m2, depth + 1)
        return out
    for rel, terms in groups:
        parsed = [mods_split(t) for t in terms]
        for c, w, m in parsed:
            if lang(c) and rel not in ("cog", "ncog", "noncog"): info["origins"].append((lang(c), w))
        if not want_text or rel in ("cog", "ncog", "noncog"): 
            for c, w, m in parsed: nested(m)
            continue
        gl = lambda m: f" (“{m['t']}”)" if m.get("t") else ""
        if rel in AFFIX_RELS:
            txt = " + ".join(ital(w) + gl(m) for c, w, m in parsed if w)
            pieces.append(("from", txt))
        else:
            txt = ", ".join((f"{lang(c)} " if lang(c) else "") + ital(w) + gl(m) + nested(m) for c, w, m in parsed if w)
            pieces.append((REL_WORDS.get(rel, "from") or "from", txt))
    if not want_text or not pieces: return ""
    out = ", ".join(f"{rw} {t}".strip() for rw, t in pieces)
    return out[0].upper() + out[1:]

def render_template(inner, info):
    name, pos, named = split_params(inner)
    n = name.lower()
    if n in ("ety", "etymology", "etym"): return render_ety(pos, named, info)
    if n in ("etymon", "senseid", "sid", "tlb", "anchor", "rfdate", "rfquote", "rfex", "attention", "cln", "c", "top", "C"): return ""
    nocap = named.get("nocap", "") not in ("", "0")
    if n in ("lb", "lbl", "label", "tlb", "term-label", "lb-lite"):
        info["labels"] += [x.lower() for x in pos[1:] if x and x not in ("_", "or", "and", "&")]
        return ""
    if n in ("q", "qual", "qualifier", "i", "qf", "gloss", "gl", "sense", "s"): return f"({', '.join(x for x in pos if x)})" if pos else ""
    if n in ("l", "link", "m", "mention", "ll", "l-self", "m-self"):
        return (pos[2] if len(pos) > 2 and pos[2] else pos[1] if len(pos) > 1 else "") if n in ("l", "link", "ll", "l-self") else ital(pos[2] if len(pos) > 2 and pos[2] else pos[1] if len(pos) > 1 else "") + gloss(named, pos, 3)
    if n == "m+": return f"{lang(pos[0]) if pos else ''} {ital(pos[1] if len(pos) > 1 else '')}".strip()
    if n in ("w", "wp", "wikipedia", "pedia", "vern", "taxlink", "taxfmt", "glossary", "smallcaps", "lang", "nowrap", "ipachar", "upright", "sc"):
        if n in ("lang",): return pos[1] if len(pos) > 1 else ""
        if n in ("w", "wp", "glossary"): return pos[1] if len(pos) > 1 and pos[1] else (pos[0] if pos else "")
        if n in ("wikipedia", "pedia"): return ""
        return pos[0] if pos else ""
    if n in ("n-g", "ngd", "non-gloss definition", "non-gloss", "ng"): return pos[0] if pos else ""
    if n in ("en-plural noun",): return ""
    if n.endswith(" of") or INFLECTION.match(n):
        target = (pos[0] if n.startswith("en-") else pos[1] if len(pos) > 1 else "") if pos else ""
        target = strip_mods(re.sub(r"#.*$", "", target)).strip()
        info["form"].append((n, target))
        word = target if target else ""
        nice = n.replace("en-", "").replace("alt form", "alternative form of").replace("alt sp", "alternative spelling of")
        return f"{nice[0].upper() + nice[1:]} {word}".strip()
    if n in ("alt form", "alt sp", "alt spelling", "alternative form", "altform", "alt form of"):
        target = pos[1] if len(pos) > 1 else ""
        info["form"].append(("alternative form of", target))
        return f"Alternative form of {target}"
    # etymology templates
    if n in ETY_LINK:
        src = pos[1] if len(pos) > 1 else ""
        word = strip_mods(pos[2]) if len(pos) > 2 else ""
        alt = pos[3] if len(pos) > 3 else ""
        if lang(src): info["origins"].append((lang(src), word))
        return (ETY_LINK[n] + f"{lang(src)} {ital(alt or word)}".strip() + gloss(named, pos, 4)).strip()
    if n == "etyl": return lang(pos[0]) if pos else ""
    if n in ("cog", "cognate", "noncog", "ncog", "nc", "noncognate"):
        src = pos[0] if pos else ""
        return f"{lang(src)} {ital(pos[1] if len(pos) > 1 else '')}".strip() + gloss(named, pos, 3)
    if n in ("af", "affix", "prefix", "pre", "suffix", "suf", "compound", "com", "confix", "con", "blend", "surf", "com+", "af+"):
        parts = [x for x in pos[1:] if x]
        if n in ("prefix", "pre") and parts: parts[0] = parts[0].rstrip("-") + "-"
        if n in ("suffix", "suf") and len(parts) > 1: parts[-1] = "-" + parts[-1].lstrip("-")
        glosses = [named.get(f"t{i + 1}") or named.get(f"gloss{i + 1}") for i in range(len(parts))]
        return " + ".join(ital(p) + (f" (“{g}”)" if g else "") for p, g in zip(parts, glosses))
    if n in ("back-formation", "bf", "back-form", "backformation"):
        w = pos[1] if len(pos) > 1 and pos[1] != "-" else ""
        return ("back-formation" if nocap else "Back-formation") + (" from " + ital(w) if w else "")
    if n in ("clipping", "clip", "clipping of"):
        w = pos[1] if len(pos) > 1 and pos[1] != "-" else ""
        return ("clipping" if nocap else "Clipping") + (" of " + ital(w) if w else "")
    if n in ("short for", "abbreviation", "abbrev"): return "Short for " + ital(pos[1] if len(pos) > 1 else "")
    if n in ("doublet", "dbt"): return "Doublet of " + ", ".join(ital(x) for x in pos[1:] if x)
    if n in ("onomatopoeic", "onom"): return "Onomatopoeic"
    if n in ("coinage", "coin"): return "Coined by " + (pos[1] if len(pos) > 1 else "")
    if n in ("named-after", "named after"): return "Named after " + (pos[1] if len(pos) > 1 else "")
    if n in ("unk", "unknown"): return "Unknown"
    if n in ("unc", "uncertain"): return "Uncertain"
    if n in ("rfe", "rfv-etym", "etystub", "rfelite"): info["noety"] = True; return ""
    # an unfamiliar etymology template shaped like {{xyz|en|la|word}}: show it as "Latin word"
    if len(pos) >= 3 and pos[0] == "en" and lang(pos[1]) and pos[2] and pos[2] != "-":
        info["origins"].append((lang(pos[1]), strip_mods(pos[2])))
        return f"{lang(pos[1])} {ital(strip_mods(pos[2]))}"
    return ""

LINK = re.compile(r"\[\[([^\[\]|]*)(?:\|([^\[\]]*))?\]\]")
def clean(text, info=None):
    info = info if info is not None else {"labels": [], "form": [], "origins": []}
    s = re.sub(r"<ref[^>]*?/>|<ref[^>]*>.*?</ref>|<!--.*?-->", "", text, flags=re.S)
    for _ in range(3): s = re.sub(r"\[\[(?:File|Image):(?:[^\[\]]|\[\[[^\[\]]*\]\])*\]\]", "", s)
    s = LINK.sub(lambda m: "" if re.match(r"(?i)(category|file|image|w|wikipedia|s|wikisource|thesaurus):", m.group(1)) and not m.group(2)
                 else (m.group(2) if m.group(2) is not None else re.sub(r"#.*$", "", m.group(1))), s)
    for _ in range(8):
        s2 = re.sub(r"\{\{([^{}]*)\}\}", lambda m: render_template(m.group(1), info), s)
        if s2 == s: break
        s = s2
    s = re.sub(r"\{\{.*$", "", s, flags=re.S).replace("}}", "")       # a template cut off at the end of a line
    s = re.sub(r"'{2,}", "", s)
    s = re.sub(r"<(?!/?i>)[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"\(\s*[,;]?\s*\)|\(“”\)", "", s)
    s = re.sub(r"\s+([,.;:)])", r"\1", s)
    s = re.sub(r"([(“])\s+", r"\1", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" ,;:")
    return s, info

def parse_page(wikitext):
    m = re.search(r"^==\s*English\s*==\s*$", wikitext, re.M)
    if not m: return {"ne": 1}
    nxt = re.search(r"^==[^=].*==\s*$", wikitext[m.end():], re.M)
    sec = wikitext[m.end(): m.end() + nxt.start() if nxt else len(wikitext)]
    senses, etys, origins = [], [], []
    ety_idx, pos, mode = -1, None, None
    buf = []
    def flush_ety():
        if mode == "ety" and buf:
            para = " ".join(l.strip() for l in buf if l.strip() and not l.startswith(("*", ":", "{{rel-", "{{root", "{{PIE")))
            info = {"labels": [], "form": [], "origins": []}
            txt, info = clean(para, info)
            txt = re.split(r"(?<=[.])\s+(?=[A-Z])", txt)
            out = ""
            for sent in txt:
                if len(out) + len(sent) > 420: break
                out = (out + " " + sent).strip()
            out = out.strip(" ,;")
            if out and out[0].islower(): out = out[0].upper() + out[1:]
            if out and not out.endswith((".", "!", "?", ")")): out += "."
            out = " ".join(x for x in re.split(r"(?<=[.])\s+", out) if not PROFANE.search(x))   # drop any rude sentence
            etys[-1] = "" if info.get("noety") else out
            seen_l, ol = set(), []
            for o in info["origins"]:
                if o[0] not in seen_l: seen_l.add(o[0]); ol.append(o)
            origins[-1] = ol[:5]
    for line in sec.split("\n"):
        h = re.match(r"^(={3,6})\s*(.*?)\s*\1\s*$", line)
        if h:
            flush_ety(); buf = []
            title = h.group(2)
            if title.startswith("Etymology"):
                etys.append(""); origins.append([]); ety_idx = len(etys) - 1; mode = "ety"
            elif title in POSMAP:
                pos = POSMAP[title]; mode = "pos"
                if ety_idx < 0: etys.append(""); origins.append([]); ety_idx = 0
            else: mode = None
            continue
        if mode == "ety": buf.append(line); continue
        if mode == "pos" and re.match(r"^#{1,2}\s", line) and len(senses) < 16:
            info = {"labels": [], "form": [], "origins": []}
            txt, info = clean(line.lstrip("#").strip(), info)
            if not txt and not info["form"]: continue
            ftype, target = (info["form"][0] if info["form"] else ("", ""))
            senses.append([pos, sorted(set(info["labels"])), txt[:300], ftype, target, max(ety_idx, 0)])
    flush_ety()
    return {"s": senses, "e": etys, "o": origins, "v": PARSER_VERSION}

# ---------------------------------------------------------------- deciding
def tidy_ety(t):
    """Last clean-up of a Wiktionary etymology for display."""
    t = re.sub(r"^.*?(?:File|Image):[^\]]*\]\]\s*", "", t or "")                     # leftover picture captions
    t = re.sub(r"\[https?://[^\]\s]+(?:\s+([^\]]+))?\]", lambda m: m.group(1) or "", t)
    def code(m):
        c, w = m.group(1), m.group(2)
        return f"{LANGS[c]} <i>{w}</i>" if c in LANGS else f"<i>{w}</i>"
    t = re.sub(r"<i>([a-z]{2,3}(?:-[a-z]{2,5})*):([^<]+)</i>", code, t)
    t = re.sub(r"(?<![\w/])([a-z]{2,3}(?:-[a-z]{2,5})*):([^\s,.;()<]+)", code, t)
    t = re.sub(r"\s+([,.;:])", r"\1", t)
    t = re.sub(r"\s{2,}", " ", t).strip(" .,;:")
    if re.match(r"^(Such|This|These|It|The latter|See|Compare)\b", t): return ""
    t = re.sub(r"^\W+", "", t)
    if not t or len(t) < 6: return ""
    t = t[0].upper() + t[1:]
    return t + ("" if t.endswith((".", "!", "?", ")")) else ".")

def tidy_def(d):
    """WordNet glosses sometimes trail their quotations' leftovers: "...accusation; ; ; - O.Henry"."""
    d = re.sub(r"\{\{.*$", "", d or "", flags=re.S).replace("}}", "")
    d = re.sub(r"(\s*;\s*)+(?:-\s*[A-Z][^;]*)?\s*$", "", d)
    d = re.sub(r"(;\s*){2,}", "; ", d)
    return re.sub(r"\s+", " ", d).strip(" ;:,")

def eligible_day():
    """First day a newly approved word may be a word of the day: tomorrow everywhere on Earth."""
    return (datetime.now(timezone(timedelta(hours=14))) + timedelta(days=1)).strftime("%Y-%m-%d")

def approve(today_only=False):
    sys.path.insert(0, HERE)
    import lexgen
    import nltk
    from nltk.corpus import wordnet as wn
    from nltk.stem import PorterStemmer
    from wordfreq import zipf_frequency
    try: nltk.data.find("taggers/averaged_perceptron_tagger_eng")
    except LookupError: nltk.download("averaged_perceptron_tagger_eng", quiet=True)
    try:
        from nltk import pos_tag
        pos_tag(["test"]); HAVE_TAGGER = True
    except Exception: HAVE_TAGGER = False
    PS = PorterStemmer()
    Z = lambda w: zipf_frequency(w, "en")
    stem = lambda w: PS.stem(w)
    STOPS = lexgen.GENERIC | set("""would could should shall will might must just like well also only even still back here there then than when what where
        why how all both each few more most other some such own same too very can now ever never always again yes yeah okay right know think going
        come came look want said tell told thing really mean dear darling""".split())
    def bag(text, skip=()):
        return {stem(w) for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 2 and w not in STOPS and w not in skip}

    cache = load_json(CACHE, {})
    decisions = load_json(DECISIONS, {})
    rows = read_rows()

    # words already in the game
    existing, existing_where = set(), {}
    db = re.search(r'<script id="db" type="application/json">(.*?)</script>', open(os.path.join(ROOT, "index.html"), encoding="utf-8").read(), re.S)
    builtin = json.loads(db.group(1)) if db else {"words": {}, "shows": {}}
    for k, e in builtin["words"].items():
        existing.add(e["w"].lower()); existing_where[e["w"].lower()] = "built-in"
    corpora = {}
    for fname, label in (("grand.json", "Grand Lexicon"), ("shakes.json", "Shakespeare"), ("study.json", "Study Books")):
        corpora[fname] = load_json(os.path.join(ROOT, fname), {"words": {}})

    LEM = set(wn.all_lemma_names())
    def wn_lemma(tok):
        if tok in LEM: return tok
        for p in "vnar":
            m = wn.morphy(tok, p)
            if m and m in LEM: return m
        return ""

    def eng_senses(w):
        d = cache.get(w) or {}
        return [s for s in d.get("s", []) if s[0] not in ("prop",)]

    def own_senses(w):
        return [s for s in eng_senses(w) if not s[3] or not INFLECTION.match(s[3])]

    def family_of(tok):
        """Return (base word used to group sightings, best headword for the entry)."""
        senses = eng_senses(tok)
        infl = [s[4] for s in senses if s[3] and INFLECTION.match(s[3]) and s[4]]
        var = [s[4] for s in senses if s[3] and not INFLECTION.match(s[3]) and s[4] and s[3] not in SPELLING
               and ("form of" in s[3] or "spelling of" in s[3])]
        base = infl[0] if infl else wn_lemma(tok) or tok
        if base != tok and not (base in LEM or eng_senses(base)): base = tok
        head = tok if (own_senses(tok) or (tok in LEM and not infl)) else base
        if infl and base != tok and tok not in LEM and (base in LEM or own_senses(base)):
            head = base                       # "cherubs" is the plural of cherub, whatever else Wiktionary lists
        if var and head not in LEM and not [s for s in own_senses(head) if not s[3]]:
            head = var[0] if (var[0] in LEM or own_senses(var[0])) else head
            base = head
        return base.lower(), head.lower()

    # group every sighting by word family
    fam_rows, fam_heads, overrides = defaultdict(list), defaultdict(Counter), {}
    pre_rejects = Counter()
    for r in rows:
        tok = r["word"]
        k = r.get("keep", "").strip().lower()
        why = prefilter(tok)
        if why and k not in ("y", "yes"): pre_rejects[why] += 1; continue
        base, head = family_of(tok)
        fam_rows[base].append(r); fam_heads[base][head] += 1
        if k in ("y", "yes", "1", "x", "true", "keep"): overrides[base] = ("y", r.get("definition", "").strip())
        elif k in ("n", "no", "0", "reject"): overrides[base] = ("n", "")

    TAGS = {}
    def tag_for(tok, line):
        if not HAVE_TAGGER: return ""
        key = line
        if key not in TAGS:
            toks = re.findall(r"[A-Za-z][A-Za-z'\-]*|[.,!?;:]", line)
            try: TAGS[key] = pos_tag(toks)
            except Exception: TAGS[key] = []
        for w, t in TAGS[key]:
            if w.lower() == tok: return {"N": "n", "V": "v", "J": "a", "R": "r"}.get(t[:1], "")
        return ""

    def wikt_pos_ok(wpos, spos):
        return wpos == spos or (wpos == "a" and spos in "as")

    def signature(s):
        words = s.definition() + " " + " ".join(s.examples()) + " " + " ".join(l.replace("_", " ") for l in s.lemma_names())
        for h in s.hypernyms()[:2] + s.similar_tos()[:3]: words += " " + " ".join(l.replace("_", " ") for l in h.lemma_names())
        return words

    SYNCACHE = {}
    def widen(text, skip):
        out = set()
        for w in re.findall(r"[a-z]+", text.lower()):
            if len(w) < 3 or w in STOPS or w in skip: continue
            out.add(stem(w))
            if w not in SYNCACHE:
                SYNCACHE[w] = {stem(l.name().lower()) for x in wn.synsets(w)[:2] for l in x.lemmas() if "_" not in l.name()}
            out |= SYNCACHE[w]
        return out
    def related(s):
        out = set()
        for l in s.lemmas():
            for x in l.pertainyms() + l.derivationally_related_forms(): out.add(x.name().lower())
        return out
    def agreement(s, head, wsenses):
        """How well a WordNet sense matches each Wiktionary sense: returns (best score, best sense)."""
        sig = bag(signature(s), skip={head})
        syns = {l.replace("_", " ").lower() for l in s.lemma_names()} | {l.replace("_", " ").lower() for t in s.similar_tos() for l in t.lemma_names()}
        syns.discard(head)
        best, best_s = 0, None
        spos = s.pos()
        for ws in wsenses:
            if ws[3] or not ws[2]: continue
            d = ws[2].lower()
            sc = len(sig & bag(d, skip={head}))
            if not sc and sig & widen(d, {head}): sc = 1                     # same idea in different words
            m = re.match(r"^(?:in|with) an? ([a-z-]+) (?:manner|way|fashion)|^(?:the )?(?:quality|state|condition|act) of being ([a-z-]+)", d)
            if m and (m.group(1) or m.group(2)) in related(s): sc += 2      # "in a nonchalant manner" ~ the adverb of nonchalant
            if any(re.search(r"\b" + re.escape(x) + r"\b", d) for x in syns): sc += 2
            if wikt_pos_ok(ws[0], spos): sc += 0.5
            else: sc -= 0.5
            if sc > best: best, best_s = sc, ws
        return best, best_s

    NEAR = {}
    def near(k):
        """Everyday words close to k: its synonyms and related forms (strong), and their neighbours (partial)."""
        if k in NEAR: return NEAR[k]
        ok = lambda w: re.fullmatch(r"[a-z]+", w) and Z(w) >= 3.2 and not BLOCK.search(w) and not PROFANE.search(w)
        strong, part = {k}, set()
        for x in wn.synsets(k)[:2]:
            for l in x.lemmas():
                n = l.name().lower()
                if ok(n): strong.add(n)
                for d in l.derivationally_related_forms() + l.pertainyms():
                    if ok(d.name().lower()): strong.add(d.name().lower())
                    for y in d.synset().similar_tos()[:6]:
                        part |= {m.name().lower() for m in y.lemmas() if ok(m.name().lower())}
            for y in x.similar_tos()[:6] + x.hypernyms()[:1]:
                part |= {m.name().lower() for m in y.lemmas() if ok(m.name().lower())}
        NEAR[k] = (sorted(strong), sorted(part - strong))
        return NEAR[k]
    def ideas(head, *defs):
        """Scoring ideas from both dictionaries' wording: one idea scores about 67, two score 100."""
        kws = []
        for d in defs:
            for k in lexgen.kw_list(re.sub(r"<[^>]+>", "", d or ""))[:3]:
                if k != head and k not in kws and not BLOCK.search(k): kws.append(k)
        kws = kws[:4]
        if not kws: return None
        cs = []
        for k in kws:
            st, pa = near(k)
            cs.append({"label": f"the idea of “{k}”", "w": round(1 / len(kws), 3), "s": ", ".join(st), "p": ", ".join(pa[:25])})
        return {"concepts": cs, "cap": round(min(1, 1.5 / len(kws)), 3)}

    approved, review, rejected, exists = {}, {}, {}, {}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def wn_name_only(w):          # WordNet only has it with a capital letter: Brahms, Cajun, Stilton
        names = [l.name() for x in wn.synsets(w) for l in x.lemmas() if l.name().lower() == w]
        return bool(names) and all(n[:1].isupper() for n in names)
    tiebreaks = []
    def whole(tok, line):   # the word stands on its own in the quote (not "-ocres" from "mediocre")
        return re.search(r"(?i)(?<![A-Za-z])(?<!(?<!-)-)" + re.escape(tok) + r"(?![A-Za-z])(?!-[A-Za-z])", line or "") is not None
    def syn_for(w):         # WordNet senses for exactly this form (wn.synsets("vexed") would also return "vex")
        return [x for x in wn.synsets(w) if w in {l.name().lower() for l in x.lemmas()}] if w in LEM else []
    CONCRETE = {"noun.animal", "noun.plant", "noun.food", "noun.substance", "noun.object", "noun.body", "noun.location", "noun.artifact"}
    head_owner = {}
    for fam, all_frs in fam_rows.items():
        base = fam
        heads = fam_heads[fam]
        head = max(heads, key=lambda h: (heads[h], h in LEM, -len(h)))
        frs = [r for r in all_frs if whole(r["word"], r["line"])]
        forms = sorted({r["word"] for r in frs})
        show_rows = [r for r in frs if not r["book"]]
        clean_rows = [r for r in show_rows if not PROFANE.search(r["line"])]
        ov = overrides.get(fam)
        def reject(reason): rejected[fam] = {"w": head, "r": reason, "n": len(all_frs)}
        if ov and ov[0] == "n": reject("rejected by hand in a spreadsheet"); continue
        if not frs: reject("not a whole word in the quote"); continue
        if not show_rows and not (ov and ov[0] == "y"): exists[fam] = {"w": head, "r": "only in books (used for cross-references)"}; continue
        if not clean_rows and not (ov and ov[0] == "y"): reject("only heard in lines with swearing"); continue
        if head in existing or base in existing: exists[fam] = {"w": head, "r": f"already in the game ({existing_where.get(head) or existing_where.get(base)})"}; continue
        tags = Counter(t for r in frs for t in [tag_for(r["word"], r["line"])] if t)
        want = {p for p, _ in tags.most_common(1)}
        tagp = next(iter(want), "")
        if base != head and tagp and not any(x[0] == tagp and not x[3] for x in own_senses(head)) \
                and not any(x.pos() == tagp or (tagp == "a" and x.pos() == "s") for x in syn_for(head)) and (syn_for(base) or own_senses(base)):
            head = base                                          # the quote uses an inflected form of the base word
        variants = [x for x in eng_senses(head) if x[3] and not INFLECTION.match(x[3]) and x[3] not in SPELLING and x[4]
                    and (own_senses(x[4]) or syn_for(x[4]))]
        variant = next((x[4] for x in variants if not tagp or x[0] == tagp), variants[0][4] if variants else "")
        wsrc = ""
        if variant and not [x for x in own_senses(head) if not x[3]]:
            wsrc = variant                                       # an alternative spelling: take the meaning from the main spelling
            if not syn_for(head): base = variant
        in_cache = head in cache or base in cache
        wd = cache.get(head) or cache.get(base) or {}
        wsenses = [x for x in own_senses(head) if not x[3]] or [x for x in own_senses(wsrc or base) if not x[3]]
        all_senses = eng_senses(head) + ([] if base == head else eng_senses(base)) + (eng_senses(wsrc) if wsrc and wsrc != base else [])
        ss = syn_for(head) or ([] if ([x for x in own_senses(head) if not x[3]] and base != head) else syn_for(base))
        forced = ov and ov[0] == "y"
        # ---- hard filters
        if not forced:
            if BLOCK.search(head) or BLOCK.search(base): reject("rude or upsetting"); continue
            if Z(base) > 3.4 or Z(head) > 3.0: reject("everyday word"); continue
            if lexgen_transparent(head, Z, wn) or (base != head and lexgen_transparent(base, Z, wn)): reject("an everyday word with a prefix or suffix"); continue
            if len(ss) > 12: reject("everyday word with many meanings"); continue
            labels = {l for s in all_senses for l in s[1]}
            if labels & BAD_LABELS: reject("marked vulgar or offensive in Wiktionary"); continue
            if any(BLOCK.search(s[2].lower()) for s in all_senses[:4]): reject("rude or upsetting meaning"); continue
            if ss and any({d.name().split(".")[0] for d in s.usage_domains()} & BAD_DOMAINS for s in ss[:3]): reject("marked offensive in WordNet"); continue
            if wd.get("ne") and not ss: reject("not an English word (foreign or a name)"); continue
            if in_cache and not all_senses and not ss and not wd.get("ne"):
                d = cache.get(head) or cache.get(base)
                reject("a name, not a word" if d and d.get("s") else "not in either dictionary (made up, a name or a typo)"); continue
            if not in_cache: review[fam] = {"w": head, "r": "waiting for the Wiktionary lookup", "n": len(frs)}; continue
            spell = [s for s in eng_senses(head) if s[3] in SPELLING or "misspelling" in s[3] or "pronunciation spelling" in s[3]]
            if spell and len(spell) >= max(1, len(eng_senses(head)) - 1): reject("a misspelling, abbreviation or contraction"); continue
            if any(s[0] == "contr" for s in eng_senses(head)): reject("a contraction"); continue
            if ss and all(s.lexname() == "noun.body" for s in ss[:2]): reject("body part"); continue
            if ss and all(s.instance_hypernyms() for s in ss): reject("a name, not a word"); continue
        # ---- choose the meaning that fits the quotes
        ctx = bag(" ".join(r["line"] for r in frs), skip=set(forms) | {head, base})
        cands = [s for s in ss if s.pos() in want or (s.pos() == "s" and "a" in want)] or list(ss)
        best, best_score, best_ws, best_agree = None, -9, None, 0
        for rank, s in enumerate(cands[:10]):
            ag, ws = agreement(s, head, wsenses) if wsenses else (0, None)
            lesk = len(ctx & bag(signature(s), skip={head}))
            score = 0.8 / (1 + rank) + 0.35 * lesk + (0.6 if ag >= 1.5 else 0.2 if ag >= 1 else 0)
            if score > best_score: best, best_score, best_ws, best_agree = s, score, ws, ag
        own_def = ov[1] if ov else ""
        conf, tb = 0, ""
        lower_used = any(re.search(r"(?<![A-Za-z-])" + re.escape(r["word"]) + r"(?![A-Za-z])", r["line"]) for r in frs)
        if best is not None and best_agree >= 1.5: conf = 2
        elif best is not None and wsenses:
            # WordNet's best guess doesn't match Wiktionary: try the senses that do agree
            agreeing = [(agreement(s, head, wsenses), s) for s in ss[:10]]
            agreeing = [(a, s) for a, s in agreeing if a[0] >= 1.5]
            if agreeing:
                (ag, ws), s = max(agreeing, key=lambda x: x[0][0])
                best, best_ws, best_agree, conf = s, ws, ag, 2
        if conf == 0 and best is not None and wsenses:
            same = [x for x in ss if x.pos() == best.pos() or {x.pos(), best.pos()} <= {"a", "s"}]
            wsame = [x for x in wsenses if not x[3] and wikt_pos_ok(x[0], best.pos())]
            if len(same) == 1 and wsame:
                best_ws, best_agree, conf = wsame[0], 1, 2
        ws_only = None
        if best is None and wsenses:
            pool = [x for x in (wsenses or eng_senses(head) or eng_senses(base)) if x[0] in ("n", "v", "a", "r", "i")]
            match = [x for x in pool if tagp and x[0] == tagp]
            if match and all(x[3] for x in match) and not forced: reject("a spelling variant of another word"); continue
            cw = [x for x in (match or pool) if not x[3] and x[2]]
            if not cw and not forced: reject("only a spelling variant or form of another word"); continue
            if cw:
                ranked = sorted(cw, key=lambda x: -(len(ctx & bag(x[2], skip={head})) * 0.5 - cw.index(x) * 0.15))
                ws_only = ranked[0]
                if len(cw) >= 4 and not (ctx & bag(ws_only[2], skip={head})) and not forced:
                    tb = "several meanings and the quote doesn't show which, so it uses Wiktionary's main one"
                conf = 1
        if not forced and conf == 0:
            # tie-break: settle it here rather than waiting for a human
            if wn_name_only(head) and not lower_used: reject("a name (only capitalised in the dictionary)"); continue
            pool = [x for x in wsenses if not x[3] and x[2] and x[0] in ("n", "v", "a", "r", "i")]
            if pool:
                wn_pos = {("a" if x.pos() == "s" else x.pos()) for x in ss}
                shared = [x for x in pool if x[0] in wn_pos] or pool          # a part of speech both dictionaries know
                match = [x for x in shared if tagp and x[0] == tagp] or shared
                circular = lambda x: bool(re.search(r"\b" + re.escape(head[:max(4, len(head) - 3)]), x[2].lower()))
                ranked = sorted(match, key=lambda x: -(len(ctx & bag(x[2], skip={head})) * 0.5 - match.index(x) * 0.15 - (1 if circular(x) else 0)))
                if circular(ranked[0]) and best is not None:
                    conf, tb = 3, "Wiktionary's wording only repeats the word, so it uses WordNet's meaning"
                else:
                    ws_only, best, best_ws, conf = ranked[0], None, None, 1
                    tb = "the dictionaries disagreed, so it uses Wiktionary's meaning for how the word is used in the quote"
            elif best is not None and Z(head) >= 1.0:
                conf, tb = 3, "only WordNet has it, so it uses WordNet's meaning"
            else:
                reject("too obscure to check in either dictionary"); continue
        if head in head_owner:                                   # another form of a word we already have: merge the sightings
            owner = head_owner[head]
            if owner in approved: approved[owner][1].extend(clean_rows); approved[owner][3].extend(all_frs)
            exists[fam] = {"w": head, "r": f"merged with {head}"}; continue
        if not forced and best is not None and best.lexname() in CONCRETE and Z(head) > 2.5:
            reject("an everyday object, animal or food"); continue
        # ---- build the entry
        e = None
        if best is not None:
            try: e = lexgen.build_entry(head, best)
            except Exception: e = None
        ws = best_ws or ws_only
        if e is None:
            text = own_def or (ws[2] if ws else "")
            if not text or ws is None and not own_def: reject("no usable definition"); continue
            kws = lexgen.kw_list(text)[:3] or [head]
            weights = [.5, .3, .2][:len(kws)] if len(kws) > 1 else [1]
            others = [s[2] for s in wsenses if s is not ws and s[2] and not s[3]][:1]
            e = {"w": head, "pos": {"n": "noun", "v": "verb", "a": "adjective", "r": "adverb", "i": "interjection"}.get(ws[0] if ws else "", ""),
                 "def": "", "explain": ("It can also mean: " + others[0].rstrip(".") + ".") if others else "",
                 "lex": {"concepts": [{"label": f"the idea of “{k}”", "w": weights[i], "s": ", ".join([k] + lexgen.common_syns(k)), "p": ""}
                                      for i, k in enumerate(kws)], "cap": .7 if len(kws) > 1 else 1}}
            e["def"] = text
        if own_def: e["def"] = own_def
        e["def"] = tidy_def(e["def"])
        e["def"] = e["def"][0].upper() + e["def"][1:] + ("" if e["def"].endswith((".", "!", "?")) else ".")
        if ws and best is not None and conf == 2:
            alt = ws[2].strip()
            if alt and bag(alt) != bag(e["def"]) and len(alt) < 220:
                e["explain"] = (f"Wiktionary puts it as: {alt.rstrip('.')}. " + e.get("explain", "")).strip()
        labels = sorted({l for l in (ws[1] if ws else []) if l in ("british", "uk", "australia", "us", "informal", "slang", "archaic",
                         "obsolete", "dated", "humorous", "formal", "literary", "rare", "colloquial", "derogatory", "chiefly british")})
        if labels: e["explain"] = (e.get("explain", "") + f" Usually marked {', '.join(labels)}.").strip()
        # etymology from Wiktionary (better sourced than the etymology package)
        ei = ws[5] if ws else 0
        etys = (cache.get(head) or {}).get("e") or (cache.get(base) or {}).get("e") or []
        origs = (cache.get(head) or {}).get("o") or (cache.get(base) or {}).get("o") or []
        if not etys and wsrc: etys, origs = (cache.get(wsrc) or {}).get("e") or [], (cache.get(wsrc) or {}).get("o") or []
        if etys and ei < len(etys) and tidy_ety(etys[ei]):
            e["ety"] = tidy_ety(etys[ei])
            ol = [o for o in (origs[ei] if ei < len(origs) else []) if o[0] not in ("English", "Proto-Indo-European")]
            if ol: set_origin(e, ol, head, lexgen)
            else: e["origin"] = ["english"]; e.pop("etyLex", None)
        elif e.get("ety") and (re.search(r"<i>-|-</i>|\s-\w|\w-\s", e["ety"]) or "not recorded" in e["ety"]):
            e["ety"] = ""
        if not e.get("ety"): e["ety"] = "Origin not recorded in our dictionaries."; e["origin"] = ["english"]; e.pop("etyLex", None)
        if not e.get("etyLex"): e["etyLex"] = {"concepts": [{"label": "the language", "w": 1, "s": "english", "p": ""}], "cap": .75}
        e.setdefault("origin", ["english"])
        wk_def = ws[2] if ws else ""
        lx = ideas(head, e["def"], wk_def if wk_def and bag(wk_def) != bag(e["def"]) else "")
        if lx:
            keep = {k: v for k, v in e.get("lex", {}).items() if k in ("alt2",)}
            syn = [x for x in (e.get("lex", {}).get("syn", "") or "").split(", ") if x and not BLOCK.search(x) and not PROFANE.search(x)]
            hyper, hlabel = e.get("lex", {}).get("hyper", ""), e.get("lex", {}).get("hyperLabel", "")
            hy = best.hypernyms()[:1] if best is not None else []
            if hy and not {l.lower() for l in hy[0].lemma_names()} & {"person", "individual", "act", "thing", "object", "entity", "abstraction",
                                                                      "attribute", "state", "event", "activity", "group", "quality", "communication", "change", "move", "make"}:
                kin = [hy[0]] + [x for x in hy[0].hyponyms() if x != best][:30]
                kin += [g for x in kin[1:12] for g in x.hyponyms()[:4]]          # near relatives: "fraud" is close to "charlatan"
                names = [l.replace("_", " ").lower() for x in kin for l in x.lemma_names()]
                names = [n for n in dict.fromkeys(names) if n != head and Z(n) >= 2.8 and not BLOCK.search(n) and not PROFANE.search(n)]
                if names: hyper, hlabel = ", ".join(names[:60]), hy[0].lemma_names()[0].replace("_", " ")
            e["lex"] = {**lx, **keep, "syn": ", ".join(syn), "hyper": hyper, "hyperLabel": hlabel}
        if "Close cousins:" in e.get("explain", ""):          # no rude "cousins" (WordNet lists some slurs as synonyms)
            e["explain"] = re.sub(r"Close cousins: ([^.]*)\.", lambda m: ("Close cousins: " + ", ".join(x for x in m.group(1).split(", ") if not BLOCK.search(x) and not PROFANE.search(x)) + ".")
                                  if [x for x in m.group(1).split(", ") if not BLOCK.search(x) and not PROFANE.search(x)] else "", e["explain"]).strip()
        e["rarity"] = max(1, min(10, round(10 - Z(head) * 2.6)))     # shown on the card; rarer words join the word of the day
        e["chk"] = conf
        approved[fam] = (e, list(clean_rows or show_rows or frs), forms, list(all_frs))
        if tb: tiebreaks.append((head, tb, e["def"]))
        head_owner[head] = fam

    # ---- sightings for cross-references
    def sighting(r):
        tok = r["word"]
        line = html.escape(r.get("line", ""), quote=False)
        line = re.sub(r"(?i)(?<![A-Za-z])(" + re.escape(tok) + r")(?![A-Za-z])", r"<mark>\1</mark>", line, count=1)
        src = show_name(r["show"])
        who = r.get("speaker", "").strip()
        return [src, who, r.get("episode", "").strip(), line, r.get("source", ""), 1 if r["book"] else 0]

    def corpus_sightings(word, limit=3):
        out = []
        for fname, prefix in (("shakes.json", "Shakespeare"), ("study.json", "Study")):
            d = corpora[fname]
            e = d["words"].get(word)
            if not e or not e.get("occ"): continue
            names = d.get("plays") or d.get("texts") or {}
            seen = set()
            for o in e["occ"]:
                if o[0] in seen: continue
                seen.add(o[0])
                nm = names.get(o[0], [o[0]])[0]
                where = f"Act {o[1]}, Scene {o[2]}" if fname == "shakes.json" else str(o[1])
                who = o[4] if fname == "shakes.json" else (names.get(o[0], ["", ""])[1] if len(names.get(o[0], [])) > 1 else "")
                if PROFANE.search(re.sub(r"<[^>]+>", "", o[6] or "")): continue
                out.append([nm, who or "", where, o[6], "", 2])
                if len(out) >= limit: return out
        return out

    # ---- entries
    shows, words, order_new = {}, {}, []
    def show_key(title):
        nm = show_name(title)
        k = OLD_KEYS.get(nm) or "h-" + slug(nm)
        if k not in builtin.get("shows", {}): shows[k] = {"name": nm, "years": SHOW_YEARS.get(nm, "")}
        return k
    seq = max([d.get("seq", 0) for d in decisions.values()] + [0])
    new_bases = sorted([b for b in approved if decisions.get(b, {}).get("d") != "approved"],
                       key=lambda b: hashlib.md5(b.encode()).hexdigest())
    for b in new_bases:
        seq += 1
        decisions[b] = {"d": "approved", "w": approved[b][0]["w"], "seq": seq, "day": eligible_day(), "first": today}
    for base, (e, frs, forms, _all) in approved.items():
        d = decisions[base]
        d.update({"d": "approved", "w": e["w"], "r": "two dictionaries agree" if e["chk"] == 2 else "Wiktionary only", "n": len(frs)})
        show_rows = [r for r in frs if not r["book"]]
        def rank(r):
            words_n = len(r["line"].split())
            moira = r["file"].startswith("schitt") and "moira" in r.get("speaker", "").lower()
            kk = r["file"].startswith("kath")
            return (3 if moira else 2 if kk else 0) + (1 if r.get("speaker") else 0) + (1 if 6 <= words_n <= 30 else 0) + (0.5 if r["word"] == e["w"] else 0)
        prim = max(show_rows or frs, key=rank)
        eds = ["all"]
        if prim["file"].startswith("schitt") and "moira" in prim.get("speaker", "").lower(): eds.append("moira")
        if prim["file"].startswith("kath"): eds.append("kathkim")
        sp = prim.get("speaker", "").strip() or show_name(prim["show"])
        nm = show_name(prim["show"])
        s = sighting(prim)
        ep = prim.get("episode", "").strip()
        e.update({"show": show_key(prim["show"]), "who": sp, "mono": initials(sp), "mode": "means", "line": s[3],
                  "to": f"{sp}, “{ep}”" if ep and ep != nm else sp, "editions": eds, "source": prim.get("source", ""),
                  "gif": [f"{sp} {nm} {e['w']}", f"{sp} {nm} reaction"], "day": d["day"]})
        for f_ in ("quoted", "draft"): e.pop(f_, None)
        if e.get("explain", "").startswith("A ") and "from the far shelves" in e["explain"]: e["explain"] = ""
        if not e.get("explain"): e["explain"] = f"Heard in {nm}."
        words[e["w"]] = e
    for base, info in list(rejected.items()) + list(review.items()):
        old = decisions.get(base, {})
        if old.get("d") == "approved" and base not in approved: old["d"] = "withdrawn"
        decisions[base] = {**{k: v for k, v in old.items() if k in ("seq", "day", "first")},
                           "d": "rejected" if base in rejected else "waiting", "w": info["w"], "r": info["r"], "n": info.get("n", 0)}
    for base, info in exists.items():
        decisions[base] = {"d": "exists", "w": info["w"], "r": info["r"]}
    for base, d in decisions.items():
        if d.get("d") == "review": d["d"] = "retired"; d["r"] = "no longer in any spreadsheet"
    order = [decisions[b]["w"] for b in sorted(approved, key=lambda b: decisions[b]["seq"])]

    # ---- cross-references: every sighting of every word family
    xfam, xidx = {}, {}
    want = set(existing) | {e["w"] for e in words.values()} | set(corpora["grand.json"]["words"]) | set(corpora["shakes.json"]["words"]) | set(corpora["study.json"]["words"])
    for base, frs in fam_rows.items():
        heads = set(fam_heads[base]) | {base} | {r["word"] for r in frs}
        if not heads & want: continue
        seen, sights, extra = set(), [], []
        for r in sorted(frs, key=lambda r: (r["book"], not r.get("speaker"), r["file"])):
            if PROFANE.search(r["line"]) or not whole(r["word"], r["line"]): continue
            src = show_name(r["show"])
            (extra if src in seen else sights).append(sighting(r)); seen.add(src)
        sights += extra                                      # one per show or book first, then repeats
        for h in heads:
            if h in want and h not in xidx: xidx[h] = base
        xfam[base] = sights[:5]
    for w in set(existing) | {e["w"] for e in words.values()} | set(corpora["grand.json"]["words"]):
        cs = corpus_sightings(w)
        if not cs: continue
        base = xidx.get(w, w)
        xidx.setdefault(w, base)
        xfam.setdefault(base, [])
        xfam[base] = (xfam[base] + cs)[:6]
    xidx = {k: v for k, v in xidx.items() if v in xfam and (len(xfam[v]) > 1 or k in existing or k in words or k in corpora["grand.json"]["words"])}
    xidx = {k: v for k, v in xidx.items() if k != v}
    used = set(xidx.values()) | {k for k in xfam if k in want}
    xfam = {k: v for k, v in xfam.items() if k in used}

    # ---- write everything
    def pack(keys, eds_filter=None):
        ks = [k for k in keys if eds_filter is None or eds_filter in words[k]["editions"]]
        sh = {}
        for k in ks:
            sk = words[k]["show"]
            if sk in shows: sh[sk] = shows[sk]
        return {"shows": sh, "words": {k: words[k] for k in ks}, "order": ks, "updated": today}
    save_json(os.path.join(ROOT, "approved-all.json"), pack(order))
    save_json(os.path.join(ROOT, "approved-moira.json"), pack(order, "moira"))
    save_json(os.path.join(ROOT, "approved-kathkim.json"), pack(order, "kathkim"))
    save_json(os.path.join(ROOT, "xref.json"), {"idx": xidx, "fam": xfam, "updated": today})
    save_json(os.path.join(ROOT, "counts.json"), {"all": len(order), "moira": sum("moira" in words[k]["editions"] for k in order),
              "kathkim": sum("kathkim" in words[k]["editions"] for k in order), "updated": today})
    save_json(DECISIONS, dict(sorted(decisions.items())), indent=0)
    write_report(approved, review, rejected, exists, pre_rejects, words, order, fam_rows, cache, tiebreaks)
    print(f"Approved {len(order)} words ({sum(1 for k in order if words[k]['chk'] == 2)} confirmed by both dictionaries), "
          f"{len(tiebreaks)} settled by tie-break, {len(review)} waiting for a lookup, {len(rejected)} rejected, {len(exists)} already in the game or only in books; "
          f"{sum(1 for v in xfam.values() if len(v) > 1)} words have sightings in more than one place.")

def lexgen_transparent(w, Z, wn):
    PRE = ("un", "non", "re", "dis", "in", "im", "ir", "il", "over", "under", "out", "pre", "mis", "sub", "super", "anti", "semi", "inter",
           "multi", "counter", "co", "de", "mid", "post", "self", "fore")
    SUF = ("ishly", "ness", "ish", "less", "able", "ible", "ably", "ibly", "ful", "fully", "ize", "ise", "ization", "isation", "ized", "ised",
           "ly", "ily", "ic", "ical", "ically", "y", "er", "ers", "ment", "ity", "ive", "al", "ally", "ed", "ing", "ist", "ism", "ship", "like",
           "wise", "ward", "wards", "esque", "ous", "s", "es")
    for p in PRE:
        if w.startswith(p) and len(w) - len(p) >= 4 and Z(w[len(p):]) >= 3.3: return True
    for s in SUF:
        if w.endswith(s):
            b = w[:-len(s)]
            for c in (b, b + "e", b[:-1] + "y" if b.endswith("i") else b, b[:-1] if len(b) > 3 and b[-1] == b[-2] else b):
                if len(c) >= 4 and Z(c) >= (2.9 if s in ("s", "es", "ed", "ing", "ly", "ily", "ness", "er", "ers", "y") else 3.3): return True
    for i in range(3, len(w) - 2):                         # two everyday words glued together
        a, b = w[:i], w[i:]
        if Z(a) >= 3.6 and Z(b) >= 3.6 and len(b) >= 3: return True
    return False

def set_origin(e, ol, head, lexgen):
    def key(name):
        k = lexgen.lang_key(name)
        if k != "other": return k
        for frag, kk in (("Hebrew", "hebrew"), ("Irish", "celtic"), ("Welsh", "celtic"), ("Gaelic", "celtic"), ("Norse", "norse"),
                         ("Dutch", "dutch"), ("Germanic", "german"), ("Persian", "persian"), ("Turkish", "persian"), ("Arabic", "arabic")):
            if frag in name: return kk
        return "other"
    chain = []
    for name, _ in reversed(ol[:4]):
        k = key(name)
        if k == "other" and name.startswith("Proto-"): continue
        if not chain or chain[-1] != k: chain.append(k)
    if not chain or chain[-1] != "english": chain.append("english")
    e["origin"] = chain
    langs = [k for k in chain if k != "english"] or ["english"]
    strong, partial = [], []
    for k in langs:
        if k in lexgen.LANG_TERMS: strong.append(lexgen.LANG_TERMS[k][0]); partial.append(lexgen.LANG_TERMS[k][1])
    for name, _ in ol[:3]:
        if key(name) == "other": strong.append(lexgen.norm_ascii(name).replace("-", " "))
    roots = []
    for _, w in ol[:3]:
        r = lexgen.norm_ascii(w or "").strip("-*")
        if re.fullmatch(r"[a-z]{3,}", r) and r != head: roots.append(r)
    e["etyLex"] = {"concepts": [{"label": "the language", "w": .75, "s": ", ".join(strong) or "english", "p": ", ".join(p for p in partial if p)},
                                {"label": "the root word", "w": .25, "s": ", ".join(dict.fromkeys(roots)) or "-", "p": ""}], "cap": .75}

def write_report(approved, review, rejected, exists, pre_rejects, words, order, fam_rows, cache, tiebreaks=()):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    multi = sorted((k for k in order if len({r["show"] for r in fam_rows_for(words[k]["w"], approved, fam_rows)}) > 1),
                   key=lambda k: -len({r["show"] for r in fam_rows_for(words[k]["w"], approved, fam_rows)}))
    L = [f"# Word review ({today})", "",
         "Every harvested word is checked automatically against WordNet and Wiktionary. A word is **approved** when it is a real,",
         "uncommon English word, it isn't rude, a name or a fragment, and the two dictionaries agree on the meaning that fits the quote",
         "(or Wiktionary alone defines it, when WordNet doesn't have it). When the dictionaries can't settle it, a tie-break rule",
         "decides, so nothing waits for a person.", "",
         f"- **Approved:** {len(order)} words ({sum(1 for k in order if words[k]['chk'] == 2)} confirmed by both dictionaries)",
         f"- **Settled by a tie-break:** {len(tiebreaks)} (listed below if you want to spot-check them)",
         f"- **Waiting for their dictionary lookup:** {len(review)} (checked on the next run)",
         f"- **Rejected:** {len(rejected) + sum(pre_rejects.values())}",
         f"- **Already in the game, or only in books:** {len(exists)} (these still get cross-references)",
         f"- **Words used in more than one show:** {len(multi)}", "",
         "To overrule any decision, put **y** or **n** in the *keep* column of that word's spreadsheet. The next run follows it.", "",
         "## Heard in the most places", ""]
    for k in multi[:40]:
        frs = fam_rows_for(words[k]["w"], approved, fam_rows)
        L.append(f"- **{k}**: {', '.join(sorted({show_name(r['show']) for r in frs}))}")
    L += ["", "## Settled by a tie-break", "", "Nothing needs you here. These were decided by rule; put **n** in the keep column to drop one.", "",
          "| Word | Meaning used | Why |", "|---|---|---|"]
    for w, why, d in sorted(tiebreaks):
        L.append(f"| {w} | {re.sub(r'<[^>]+>', '', d)[:100]} | {why} |")
    reasons = Counter(v["r"] for v in rejected.values()) + pre_rejects
    L += ["", "## Why words were rejected", "", "| Reason | Words |", "|---|---|"] + [f"| {r} | {n} |" for r, n in reasons.most_common()]
    L += ["", "## Newest approvals", "", "| Word | Meaning | Heard in |", "|---|---|---|"]
    for k in order[-150:][::-1]:
        e = words[k]
        frs = fam_rows_for(k, approved, fam_rows)
        L.append(f"| {k} | {re.sub(r'<[^>]+>', '', e['def'])[:110]} | {', '.join(sorted({show_name(r['show']) for r in frs}))} |")
    open(os.path.join(HARVEST, "REVIEW.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")

def fam_rows_for(w, approved, fam_rows):
    for b, (e, frs, forms, all_frs) in approved.items():
        if e["w"] == w: return all_frs
    return []

def main():
    ap = argparse.ArgumentParser(description="Approve harvested words for Moira's Lexicon automatically.")
    ap.add_argument("step", choices=["fetch", "approve", "all", "raw"])
    ap.add_argument("words", nargs="*", help="raw: print the English Wiktionary text of these words (for checking the parser)")
    ap.add_argument("--limit", type=int, default=None, help="look up at most this many new words (for testing)")
    a = ap.parse_args()
    if a.step == "raw":
        q = wikt_batch(a.words[:50])
        for p in q.get("pages", []):
            t = p.get("revisions", [{}])[0].get("slots", {}).get("main", {}).get("content", "") if p.get("revisions") else ""
            m = re.search(r"^==\s*English\s*==\s*$", t, re.M)
            print("=" * 30, p["title"]); print(t[m.start():m.start() + 2500] if m else "(no English section)")
            print("PARSED:", json.dumps(parse_page(t), ensure_ascii=False)[:600])
        return
    if a.step in ("fetch", "all"):
        rows = read_rows()
        toks = [r["word"] for r in rows if not prefilter(r["word"])]
        fetch(toks, a.limit)
    if a.step in ("approve", "all"):
        approve()

if __name__ == "__main__":
    main()
