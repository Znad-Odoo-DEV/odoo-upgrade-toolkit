"""x_unit (unit as written) -> canonical unit. Merge gate: two items may merge only when unit_key() is equal.
Spelling variants of ONE unit collapse (nos / nos. / pcs / each / no -> EA). Different units never merge
(the client, 2026-11-14). Empty or garbage x_unit -> '?' : such items go to review (class E), never auto-merged
with an item that has a known unit.
"""
import re

CANON = {
    'EA': ['nos', 'nos.', 'no', 'no.', 'pcs', 'pc', 'psc', 'each', 'num', 'nps', 'mos', 'boos', 'number', 'piece', 'pieces', 'unit', 'units'],
    'M': ['m', 'mtr', 'mtrs', 'mt', 'mts', 'meter', 'metre', 'meters', 'l.m', 'lm', 'rm', 'r.m', '1 meter'],
    'M2': ['m2', 'sqm', 'sq.m', 'qsm', 'm²'],  # 'm�' (broken m2/m3 in the database) is NOT mapped -> RAW, review
    'M3': ['m3', 'cum', 'cu.m', 'cubic meter', 'm³'],
    'L': ['ltr', 'ltr.', 'lts', 'litre', 'liter', 'lth'],
    'GAL': ['gallon', 'gallons', 'gal', 'galon'],
    'KG': ['kg', 'kgs'],
    'TON': ['ton', 'tons', 'mt.'],
    'ROLL': ['roll', 'rolls', 'role', 'rol'],
    'BOX': ['box', 'boxes'],
    'CTN': ['ctn', 'carton', 'cartoon', 'crt'],
    'PKT': ['pkt', 'pka', 'packet', 'sachets'],
    'DRUM': ['drum', 'drums', 'drm', 'drum (200l)'],
    'BAG': ['bag', 'bags'],
    'SET': ['set', 'sets'],
    'PAIR': ['pair', 'pairs'],
    'BUNDLE': ['bundle', 'bandl', 'pndle'],
    'LS': ['l.s', 'ls', 'lumpsum', 'lumtsum', 'lump sum'],
    'LENGTH': ['length'],
    'SHEET': ['sheet', 'sheets', 'board'],
    'CAN': ['can'],
    'BOTTLE': ['bottle', '5l bottle'],
    'DOZEN': ['dozen', 'doz', 'dozzen'],
    'HOUR': ['hour', 'hrs', 'hr', 'hours'],
}
LOOKUP = {s: k for k, v in CANON.items() for s in v}


def unit_key(x_unit):
    u = (x_unit or '').strip().lower()
    u = re.sub(r'\s+', ' ', u)
    if u in LOOKUP:
        return LOOKUP[u]
    return '?' if not u or re.fullmatch(r'[\d. ]+', u) else 'RAW:' + u   # '500 mtr', 'packet (2 kg)', 'pvc' ... kept as their own unit


def same_unit(a, b):
    ka, kb = unit_key(a), unit_key(b)
    return ka == kb and ka != '?'
