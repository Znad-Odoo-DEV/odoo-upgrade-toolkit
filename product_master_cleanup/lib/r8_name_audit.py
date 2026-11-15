"""R8 name audit (read-only): flag ACTIVE product templates whose NAME still carries a spec.
Run:  python -I lib/r8_name_audit.py   -> reports/R8_name_audit.csv
Input: data/main_final/main_final_extract.json (production). Unit convention: lib/units.py.
Rule: template name = item type only; size/colour/material/thickness/length/model/brand go to variant attributes.
A bracketed unit word "(Roll)", "(Box)", "(Per Metre)" is allowed and kept.
Extra last column duplicate_of_clean: other template ids that would get the same clean name AND same unit key.
"""
import csv, json, os, re, sys, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from units import unit_key, LOOKUP

SRC = os.path.join(ROOT, 'data', 'main_final', 'main_final_extract.json')
OUT = os.path.join(ROOT, 'reports', 'R8_name_audit.csv')

UNITS = (r'mm2|sqmm|mm|cm2|cm|m2|m3|sqm|cbm|ft|feet|inch(?:es)?|in|m|kg|gsm|g|ltr|ml|l|kva|kw|w|kv|v|amps?|a|hp|tons?|ton|'
         r'ma|mtrs?|mp|tb|gb|deg|gauge|micron|mic|bar|psi|gal|usg|gl|kn|mpa|rpm|btu|hz|ah|mah|pcs|nos|cores?|c|way|step|steps|modules?|grit')
NUM = r'\d+(?:,\d{3})*(?:\.\d+)?'
RE_DIM = re.compile(rf'(?<![\w.]){NUM}\s*(?:[x×*]\s*{NUM}\s*)+(?:{UNITS})?\b', re.I)
RE_FRAC = re.compile(r'(?<![\w/])(?:\d+\s*-\s*)?\d+/\d+(?:\s*(?:in|inch|"|mm|m|l))?(?![\w/])', re.I)
SPACED = r'mm2|mm|cm|kg|tons?|kw|kva|hp|ltr|gal(?:lons?)?|ml|mtrs?|sqm|m2|m3'
RE_NUMUNIT = re.compile(rf'(?<![\w.]){NUM}(?:\s?(?:{SPACED})|(?:{UNITS})|"|\'\'|\'|°)(?![a-z0-9])', re.I)
RE_CODE = re.compile(r'(?<![\w])(?:PN|DN|IP|RAL|SDR|SN|Class|CL|Schedule|SCH|Sch|Grade|Gr)\s?-?\d+[A-Za-z]*(?![\w])', re.I)
RE_UPTO = re.compile(r'\b(?:up to|upto|above|below|max|min)\s+' + NUM + r'\s?(?:' + UNITS + r')?\b', re.I)
RE_MODEL = re.compile(r'(?<![\w])(?=[A-Za-z0-9/.\-]*\d)(?=[A-Za-z0-9/.\-]*[A-Za-z])[A-Za-z0-9][A-Za-z0-9/.\-]{2,}(?![\w])')
RE_PLAINQTY = re.compile(rf'{NUM}(?:{UNITS}|"|°)', re.I)
RE_BARENUM = re.compile(r'(?<![\w.\-/])\d{2,}(?![\w.\-/%])')
MODEL_OK = {'rj45', 'rj11', 'cat5', 'cat5e', 'cat6', 'cat6a', 'cat7', 'rs485', 'rs232', 'h2o', 'a/c', 'w.c', 'p-trap', 'u-trap',
            '2d', '3d', '4k', 'sds', 'pvc/pe', 'cu/pvc', 'hdmi2', 'usb3', 'wifi6', 'poe', 'led', 'ac/dc', 'dc/ac', '24/7'}

STRONG_MAT = ['HP PVC', 'uPVC', 'UPVC', 'CPVC', 'PPR', 'PVC', 'HDPE', 'LDPE', 'PEX', 'GRP', 'HDG', 'PPRC', 'GI', 'MS', 'SS', 'PE', 'PU', 'FRP', 'ABS']
RE_STRONGMAT = re.compile(r'(?<![\w])(?:' + '|'.join(re.escape(x) for x in STRONG_MAT) + r')(?![\w])')  # case sensitive (avoid "Ms", "Pe")
RE_STRONGMAT_CI = re.compile(r'(?<![\w])(?:ppr|pvc|upvc|hdpe|cpvc)(?![\w])', re.I)
SOFT_MAT = ['Brass', 'Copper', 'Aluminium', 'Aluminum', 'Stainless Steel', 'Stainless', 'Galvanized', 'Galvanised', 'Steel', 'Iron',
            'Plastic', 'Rubber', 'Wooden', 'Nylon', 'Epoxy', 'Bronze', 'Fiberglass', 'Glass', 'Ceramic', 'Polyethylene', 'Silicone',
            'Chrome', 'Nickel', 'Zinc', 'Carbon', 'Cast Iron', 'Ductile Iron', 'Timber', 'Granite', 'Marble']
RE_SOFTMAT = re.compile(r'(?<![\w])(?:' + '|'.join(re.escape(x) for x in sorted(SOFT_MAT, key=len, reverse=True)) + r')(?![\w])', re.I)
COLOURS = ['white', 'black', 'red', 'blue', 'green', 'yellow', 'grey', 'gray', 'orange', 'brown', 'beige', 'silver', 'golden', 'gold',
           'cream', 'pink', 'purple', 'violet', 'maroon', 'transparent', 'ivory', 'turquoise']
RE_COLOUR = re.compile(r'(?<![\w])(?:' + '|'.join(COLOURS) + r')(?![\w])', re.I)
COLOUR_LOW_AFTER = re.compile(r'\s*(?:oxide|cement|board|list|line|goods|lead|light|box|hat|iron|water|pages|marker|zone)\b', re.I)
SIZE_WORDS = re.compile(r'(?<![\w])(?:small|medium|large|big|jumbo|mini|xl|xxl|extra large|standard size)(?![\w])', re.I)
BRANDS_HIGH = ['Berger', 'Jotun', 'Jotashield', 'Mapei', 'Makita', 'Hikvision', 'ABB', 'Fenomastic', 'Sympafix', 'Came', 'Busch', 'Bome', 'Hilti',
               'Bosch', 'Dewalt', 'Fosroc', 'Nitotile', 'Nitoflor', 'Sika', 'Exystop', 'Vespa', 'Teral', 'Schneider', 'Legrand', 'Siemens', 'Philips',
               'Dahua', 'Ubiquiti', 'Cisco', 'Samsung', 'Daikin', 'Grundfos', 'Wilo', 'Armaflex', 'Dulux', 'Caparol', 'Hitachi', 'Toshiba',
               'Makute', 'Vtools', 'Kzuber', 'D-Link', 'Cosmoplast', 'Aricol', 'Pegler', 'Mastren', 'Hager', 'Lutron', 'Tyco', 'Rehau', 'Wavin',
               'Uponor', 'Geberit', 'Sikaflex', 'Rawlplug', 'Fischer', 'Stanley', 'Knauf', 'Rockwool', 'Mitsubishi', 'LG', 'Panasonic',
               'Honeywell', 'Bticino', 'Clipsal', 'Ledvance', 'Osram', 'Eaton', 'Karcher', 'Ingco', 'Tolsen', 'Vikas']
BRANDS_LOW = ['Carrier', 'Max', 'Total', 'National', 'Boss', 'Ford', 'Masters', 'Royce', 'Sola', 'RR', 'Clarke', 'Neo Power', 'DLTC', 'T Tech']
RE_BRAND_H = re.compile(r'(?<![\w])(?:' + '|'.join(re.escape(x) for x in sorted(set(BRANDS_HIGH), key=len, reverse=True)) + r')(?![\w])', re.I)
RE_BRAND_L = re.compile(r'(?<![\w])(?:' + '|'.join(re.escape(x) for x in sorted(BRANDS_LOW, key=len, reverse=True)) + r')(?![\w])')
RE_ORIGIN = re.compile(r'\((?:china|india|korea|germany|turkey|italy|uae|usa|uk|local|imported|japan|chinese|indian)\)', re.I)

# bracket content that is a unit of measure -> allowed, kept
UNIT_WORDS = set(LOOKUP) | {'per metre', 'per meter', 'per m', 'per kg', 'per piece', 'per pc', 'per roll', 'per box', 'per bag', 'per set', 'per sqm',
                            'per m2', 'per m3', 'per ton', 'per day', 'per hour', 'per month', 'per lift', 'lift', 'per nos', 'each', 'per drum', 'per pair'}
SERVICE = re.compile(r'\b(rate|rates|fee|fees|charge|charges|contract|discount|rental|rent|hire|expenses?|transport(?:ation)?|toll|trip|labou?r|'
                     r'salary|insurance|penalt\w*|meals?|supply and (?:apply|install|fix)|installation|damag\w*|tips?|commission|allowance|deduction|booking)\b', re.I)
DIMARG = ('Pipe Size', 'Thread Size', 'Size', 'Diameter', 'Length', 'Width', 'Thickness', 'Rebar Diameter')
FITTING = re.compile(r'pipe|elbow|tee|coupl|adaptor|adapter|valve|reducer|union|nipple|bend|socket|plug|cap|trap|clamp|saddle|flange|hose|fitting|conduit|duct', re.I)


def load():
    return json.load(open(SRC, encoding='utf-8'))


def spans_for(name):
    """-> list of (start, end, token, kind, strength) ; strength H or L."""
    out = []
    prot = []
    for m in re.finditer(r'\(([^()]*)\)', name):
        if m.group(1).strip().lower() in UNIT_WORDS:
            prot.append((m.start(), m.end()))

    def ok(s, e):
        return not any(s < pe and e > ps for ps, pe in prot)

    def add(rx, kind, st):
        for m in rx.finditer(name):
            if ok(m.start(), m.end()):
                out.append((m.start(), m.end(), m.group(0), kind, st))
    add(RE_DIM, 'dim', 'H')
    add(RE_FRAC, 'frac', 'H')
    add(RE_CODE, 'code', 'H')
    add(RE_UPTO, 'range', 'H')
    add(RE_NUMUNIT, 'numunit', 'H')
    for m in RE_MODEL.finditer(name):
        t = m.group(0)
        if t.lower().strip('.-') in MODEL_OK or not ok(m.start(), m.end()) or RE_PLAINQTY.fullmatch(t):
            continue
        out.append((m.start(), m.end(), t, 'model', 'H' if len(t) >= 4 else 'L'))
    add(RE_BARENUM, 'number', 'L')
    add(RE_STRONGMAT, 'material', 'H')
    add(RE_STRONGMAT_CI, 'material', 'H')
    add(RE_SOFTMAT, 'material', 'L')
    for m in RE_COLOUR.finditer(name):
        if ok(m.start(), m.end()):
            st = 'L' if COLOUR_LOW_AFTER.match(name, m.end()) else 'H'
            out.append((m.start(), m.end(), m.group(0), 'colour', st))
    add(SIZE_WORDS, 'sizeword', 'L')
    add(RE_BRAND_H, 'brand', 'H')
    add(RE_BRAND_L, 'brand', 'L')
    for m in RE_ORIGIN.finditer(name):
        out.append((m.start(), m.end(), m.group(0), 'origin', 'L'))
    PRI = {'dim': 0, 'frac': 1, 'code': 2, 'range': 3, 'numunit': 4, 'material': 5, 'colour': 6, 'brand': 7, 'origin': 8, 'sizeword': 9, 'model': 10, 'number': 11}
    out.sort(key=lambda s: (-(s[1] - s[0]), PRI[s[3]]))
    kept = []
    for s in out:
        if not any(s[0] < k[1] and s[1] > k[0] for k in kept):
            kept.append(s)
    kept.sort()
    return kept, prot


def clean_name(name, spans):
    chars = list(name)
    for s, e, *_ in spans:
        for i in range(s, e):
            chars[i] = '\0'
    t = ''.join(chars)
    t = re.sub(r'\(\s*[\0\s,/&+\-]*\)', '', t)
    t = t.replace('\0', ' ')
    t = re.sub(r'\(\s*[,/&+\-]+\s*', '(', t)
    t = re.sub(r'\s*[,/&+\-]+\s*\)', ')', t)
    for _ in range(3):
        t = re.sub(r'\s+', ' ', t).strip(' ,-/&+:;.')
        t = re.sub(r'(?i)(?:^|\s)(?:with|of|and|for|in|to|by|x|from|at|dia|size|thk|thick|thickness|length|width|type|model|no\.?|made|up)\s*$', '', t)
        t = re.sub(r'(?i)^(?:with|of|and|x)\s+', '', t)
        t = re.sub(r'\s*[-,/]\s*(?=[-,/])', '', t)
    return re.sub(r'\s+', ' ', t).strip(' ,-/&+:;.')


def attr_for(span, name, cur):
    s, e, tok, kind, st = span
    t = tok.strip()
    tl = t.lower().replace(' ', '')
    if kind == 'colour':
        return 'Colour', t.title()
    if kind == 'material':
        return 'Material', t
    if kind == 'brand':
        return 'Brand', t
    if kind == 'origin':
        return 'Brand', t.strip('()')
    if kind == 'model':
        return 'Model', t
    if kind == 'sizeword':
        return 'Size', t.title()
    if kind == 'code':
        if tl.startswith('ip'):
            return 'IP Rating', t.upper().replace(' ', '')
        if tl.startswith('dn'):
            return 'Pipe Size', t.upper().replace(' ', '')
        if tl.startswith('ral'):
            return 'Colour', t.upper()
        if tl.startswith(('grade', 'gr')):
            return 'Grade', t
        return 'Type', t.upper().replace(' ', '')
    if kind == 'range':
        return 'Capacity', t
    if kind in ('dim', 'frac', 'numunit', 'number'):
        if re.search(r'mm2|sqmm', tl):
            return 'Cable Size', re.sub(r'\s', '', t).lower()
        if re.search(r'\d(kv|v)$', tl):
            return 'Voltage', t.replace(' ', '')
        if re.search(r'\d(kw|w|hp|kva)$', tl):
            return 'Power', t.replace(' ', '')
        if re.search(r'\d(kg|g|gsm)$', tl):
            return 'Weight', t.replace(' ', '')
        if re.search(r'\d(l|ltr|ml|gal|usg|gl)$', tl):
            return 'Volume', t.replace(' ', '')
        if re.search(r'\d(ton|tons|tb|gb|a|amp|amps|btu|ah)$', tl):
            return 'Capacity', t.replace(' ', '')
        if re.search(r'\d(deg|°)$', tl):
            return 'Angle', re.sub(r'(?i)deg|°', 'deg', t.replace(' ', ''))
        if re.search(r'\d(gauge|micron|mic)$', tl):
            return 'Thickness', t
        if re.search(r'\d(c|core|cores)$', tl):
            return 'Cores', re.sub(r'(?i)cores?', 'C', t.replace(' ', ''))
        if re.search(r'\d(way)$', tl):
            return 'Junction Type', t.title()
        if re.search(r'\d(step|steps)$', tl):
            return 'Steps', t.title()
        if re.search(r'\d(mp)$', tl):
            return 'Type', t.upper()
        if re.search(r'\d(pcs|nos)$', tl):
            return 'Pack', t
        if kind == 'number':
            return 'Model', t
        a = next((x for x in DIMARG if x in cur), None)
        if not a:
            a = 'Pipe Size' if (FITTING.search(name) and kind in ('frac', 'numunit')) else 'Size'
        return a, re.sub(r'\s', '', t).lower().replace('inch', 'in').replace('"', 'in')
    return 'Type', t


def key_of(cn, x_unit):
    return (re.sub(r'\s+', ' ', cn.lower()).strip(), unit_key(x_unit))


def main():
    d = load()
    cur = collections.defaultdict(dict)
    for l in d['lines']:
        cur[l['product_tmpl_id'][0]][l['attribute_id'][1]] = len(l['value_ids'])
    rows = []
    cleanmap = collections.defaultdict(list)
    for t in d['templates']:
        name = t['name'] or ''
        spans, _ = spans_for(name)
        cn = clean_name(name, spans) if spans else name
        cleanmap[key_of(cn, t['x_unit'])].append(t['id'])
        if not spans:
            continue
        categ = (t['categ_id'] or [0, ''])[1]
        service = bool(SERVICE.search(name)) or 'Expenses' in categ or 'Booking' in categ
        strong = [s for s in spans if s[4] == 'H']
        conf = 'HIGH' if strong else 'LOW'
        if service and conf == 'HIGH' and not any(s[3] in ('dim', 'frac', 'numunit', 'code') for s in strong):
            conf = 'LOW'
        if not cn:
            conf = 'LOW'
        c = cur.get(t['id'], {})
        sug, seen = [], set()
        for sp in spans:
            a, v = attr_for(sp, name, c)
            if (a, v.lower()) not in seen:
                seen.add((a, v.lower()))
                sug.append(f'{a}={v}')
        rows.append({
            'template_id': t['id'], 'name': name, 'variant_count': t['product_variant_count'],
            'current_attributes': ';'.join(f'{k}[{v}]' for k, v in c.items()),
            'flagged_tokens': ' | '.join(f'{s[2].strip()}({s[3]}{"" if s[4] == "H" else "?"})' for s in spans),
            'confidence': conf, 'suggested_clean_name': cn or name,
            'suggested_attribute_values': ';'.join(sug), 'category': categ,
            '_key': key_of(cn, t['x_unit'])})
    for r in rows:
        others = [i for i in cleanmap[r['_key']] if i != r['template_id']]
        r['duplicate_of_clean'] = ' '.join(map(str, others)) if r['_key'][0] and others else ''
    rows.sort(key=lambda r: (r['confidence'] != 'HIGH', r['name'].lower()))
    cols = ['template_id', 'name', 'variant_count', 'current_attributes', 'flagged_tokens', 'confidence',
            'suggested_clean_name', 'suggested_attribute_values', 'category', 'duplicate_of_clean']
    with open(OUT, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    c = collections.Counter(r['confidence'] for r in rows)
    print('templates', len(d['templates']), 'flagged', len(rows), dict(c), 'dup-after-clean', sum(1 for r in rows if r['duplicate_of_clean']))


if __name__ == '__main__':
    main()
