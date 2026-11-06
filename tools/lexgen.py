import json, re, random, unicodedata, ety
from nltk.corpus import wordnet as wn
from wordfreq import zipf_frequency as Z

def lang_key(name):
    n = name.split(' (')[0]
    if 'Latin' in n: return 'latin'
    if 'Greek' in n: return 'greek'
    if n in ('French','Old French','Middle French','Anglo-Norman','Old Northern French','Norman','Occitan','Old Occitan','Provençal','Picard'): return 'french'
    if n == 'Old English': return 'oldenglish'
    if n in ('Middle English','English','Scots','Middle Scots'): return 'english'
    if n in ('Old Norse','Norwegian','Danish','Swedish','Icelandic','Old Danish','Old Swedish','Faroese','Norn'): return 'norse'
    if 'German' in n or n in ('Old Saxon','Low German','Frankish','Gothic','Old Frisian','West Frisian','Old Low Franconian'): return 'german'
    if 'Dutch' in n or n in ('Flemish','Afrikaans'): return 'dutch'
    if 'Italian' in n or n in ('Venetian','Neapolitan','Sicilian'): return 'italian'
    if n in ('Spanish','Portuguese','Catalan','Galician','Old Spanish','Old Portuguese','Ladino'): return 'spanish'
    if 'Arabic' in n: return 'arabic'
    if 'Persian' in n or 'Turkish' in n or n == 'Ottoman Turkish (1500-1928)': return 'persian'
    if n in ('Sanskrit','Hindi','Urdu','Bengali','Tamil','Pali','Marathi','Gujarati','Punjabi','Sinhala','Malayalam','Telugu','Kannada','Prakrit'): return 'indic'
    if n in ('Irish','Scottish Gaelic','Welsh','Breton','Cornish','Old Irish','Middle Irish','Gaulish','Manx','Middle Welsh'): return 'celtic'
    if n in ('Hebrew','Yiddish','Aramaic','Ancient Hebrew','Classical Syriac'): return 'hebrew'
    return 'other'

LANG_TERMS = {
 'latin':("latin, roman, rome, ancient rome","italian, romance"),
 'greek':("greek, greece, ancient greek, hellenic","latin"),
 'french':("french, france, norman, anglo norman, old french","latin"),
 'oldenglish':("old english, anglo saxon, saxon, english, germanic","norse, german"),
 'english':("english, middle english, britain, british","germanic, old english"),
 'norse':("norse, old norse, viking, vikings, scandinavian, danish, norwegian, swedish, icelandic","german, germanic"),
 'german':("german, germanic, saxon, gothic, frankish, germany","dutch, norse"),
 'dutch':("dutch, flemish, netherlands, holland","german, germanic"),
 'italian':("italian, italy","latin"),
 'spanish':("spanish, spain, portuguese, portugal, catalan","latin"),
 'arabic':("arabic, arab, arabia","persian, turkish"),
 'persian':("persian, persia, iran, turkish, turkey, ottoman","arabic"),
 'indic':("sanskrit, hindi, urdu, indian, india, bengali, tamil","asian"),
 'celtic':("celtic, gaelic, irish, welsh, scottish, breton","english"),
 'hebrew':("hebrew, yiddish, aramaic, jewish","arabic"),
}
GENERIC = set("""act state quality person people something someone somebody thing things having characterized characterised marked
make made used especially one way being relating pertaining manner become cause caused usually often esp the a an of to and or in on
for with by as at from that which who whom whose this these those any some other such not no very more most less much many into
out over under up down about kind sort type form part piece group set number lot use using give given take put get got be is are was
were been have has had do does did done also etc e g i ie eg it its their them they he she his her him you your our we us one's
someone's something's capable able unable characteristic pertaining relating related belonging resembling tending likely producing involving containing showing without within upon toward towards between among great good bad""".split())

def norm_ascii(s):
    s = unicodedata.normalize('NFKD', s)
    return ''.join(c for c in s if not unicodedata.combining(c)).lower()

def kw_list(gloss):
    words = re.findall(r"[a-z]+", gloss.lower())
    out = []
    for w in words:
        if w in GENERIC or len(w) < 3 or w in out: continue
        out.append(w)
    # most distinctive first: rarer words carry more meaning
    return out

def common_syns(w):
    res = set()
    for s in wn.synsets(w)[:1]:
        for l in s.lemma_names():
            l = l.replace('_',' ').lower()
            if l != w and re.fullmatch(r"[a-z]+( [a-z]+)?", l) and Z(l,'en') >= 3.2: res.add(l)
    return sorted(res)[:6]

LEXNAME = {'noun.act':'Deeds & doings','noun.attribute':'Qualities','noun.artifact':'Made things','noun.cognition':'Thought & knowledge',
 'noun.communication':'Words & signals','noun.event':'Happenings','noun.feeling':'Feelings','noun.group':'Groups & gatherings',
 'noun.motive':'Motives','noun.person':'People & types','noun.phenomenon':'Phenomena','noun.possession':'Money & property',
 'noun.process':'Processes','noun.state':'States of being','noun.time':'Time','verb.body':'Bodily verbs','verb.change':'Changing',
 'verb.cognition':'Thinking','verb.communication':'Speaking & writing','verb.competition':'Contests','verb.consumption':'Eating & using',
 'verb.contact':'Touching & handling','verb.creation':'Making','verb.emotion':'Feeling','verb.motion':'Moving','verb.perception':'Sensing',
 'verb.possession':'Having & giving','verb.social':'Social life','verb.stative':'Being','verb.weather':'Weather','adj.all':'Describing words',
 'adj.pert':'Describing words','adj.ppl':'Describing words','adv.all':'How things are done'}
POS = {'n':'noun','v':'verb','a':'adjective','s':'adjective','r':'adverb'}
LANG_NAME = {'latin':'Latin','greek':'Greek','french':'French','oldenglish':'Old English','english':'English','norse':'Old Norse',
 'german':'German','dutch':'Dutch','italian':'Italian','spanish':'Spanish','arabic':'Arabic','persian':'Persian','indic':'Sanskrit or Hindi',
 'celtic':'Celtic','hebrew':'Hebrew','other':'another language'}

def build_entry(w, sense=0):
    entries = {}
    ss = wn.synsets(w)
    if not ss: return None
    s = ss[0]
    z = Z(w,'en')
    try: origins = ety.origins(w, recursive=True)
    except Exception: origins = []
    origins = [o for o in origins if o.language.name != 'English' or len(origins) == 1]
    # etymology sentence, nearest first
    parts = []
    for o in origins[:3]:
        ln = o.language.name.split(' (')[0]
        parts.append(f"{ln} <i>{o.word}</i>")
    ety_txt = ("From " + ", from ".join(parts) + ".") if parts else "Origin not recorded in our etymology sources."
    chain = []
    for o in reversed(origins[:4]):
        k = lang_key(o.language.name)
        if not chain or chain[-1] != k: chain.append(k)
    if not chain or chain[-1] != 'english': chain.append('english')
    # meaning lexicon
    syns = set()
    for t in ss[:3]:
        for l in t.lemma_names():
            l = l.replace('_',' ').lower()
            if l != w and re.fullmatch(r"[a-z]+( [a-z]+)*", l): syns.add(l)
        if t.pos() in 'as':
            for st in t.similar_tos():
                for l in st.lemma_names():
                    l = l.replace('_',' ').lower()
                    if re.fullmatch(r"[a-z]+( [a-z]+)*", l): syns.add(l)
    hyper = []
    for h in s.hypernyms()[:2]:
        hyper += [l.replace('_',' ').lower() for l in h.lemma_names()[:2]]
    def concepts_for(sense):
        kws = kw_list(sense.definition())[:3]
        weights = [.5, .3, .2][:len(kws)]
        return [{"label": f"the idea of “{k}”", "w": weights[i], "s": ", ".join([k] + common_syns(k)), "p": ""} for i, k in enumerate(kws)]
    concepts = concepts_for(s)
    if not concepts:
        return None
    lex = {"concepts": concepts, "cap": 0.7 if len(concepts) > 1 else 1, "syn": ", ".join(sorted(syns)),
           "hyper": ", ".join(dict.fromkeys(hyper)), "hyperLabel": hyper[0] if hyper else ""}
    if len(ss) > 1:
        c2 = concepts_for(ss[1])
        if c2: lex["alt2"] = {"concepts": c2, "cap": 0.7 if len(c2) > 1 else 1}
    # origin lexicon
    langs = [k for k in chain if k != 'english'] or ['english']
    strong, partial = [], []
    for k in langs:
        if k in LANG_TERMS: strong.append(LANG_TERMS[k][0]); partial.append(LANG_TERMS[k][1])
        else:
            for o in origins:
                if lang_key(o.language.name) == k: strong.append(norm_ascii(o.language.name.split(' (')[0]))
    roots = []
    for o in origins[:3]:
        r = norm_ascii(o.word).strip('-*')
        if re.fullmatch(r"[a-z]{3,}", r) and r != w: roots.append(r)
    etyLex = {"concepts": [{"label":"the language","w":.75,"s":", ".join(strong),"p":", ".join(p for p in partial if p)},
                           {"label":"the root word","w":.25,"s":", ".join(roots) or "-","p":""}], "cap": .75}
    ex = ""
    for t in ss[:2]:
        for e in t.examples():
            if re.search(r"\b" + re.escape(w), e, re.I):
                ex = re.sub(r"\b(" + re.escape(w) + r"\w*)", r"<mark>\1</mark>", esc_e := e.replace('<','&lt;'), flags=re.I); break
        if ex: break
    others = [d.definition() for d in ss[1:3] if d.pos() == s.pos()]
    explain = []
    close = [x for x in sorted(syns, key=lambda q: Z(q,'en'), reverse=True) if ' ' not in x][:5]
    if close: explain.append("Close cousins: " + ", ".join(close) + ".")
    if hyper: explain.append(f"A kind of {hyper[0]}.")
    if others: explain.append("It can also mean: " + others[0] + ".")
    rarity = max(1, min(10, round(10 - z * 2.6)))
    return {"w": w, "pos": POS[s.pos()], "pron": "", "show": "gl", "who": LEXNAME.get(s.lexname(), "Curiosities"),
                  "mono": "GL", "rarity": rarity, "line": ex, "quoted": False, "to": "Usage example" if ex else "",
                  "def": s.definition()[0].upper() + s.definition()[1:] + ".",
                  "explain": " ".join(explain) or f"A {POS[s.pos()]} from the far shelves of English.",
                  "ety": ety_txt, "origin": chain, "mode": "means", "lex": lex, "etyLex": etyLex}

