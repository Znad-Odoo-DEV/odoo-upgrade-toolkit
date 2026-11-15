"""Duplicate-product detection helpers for a construction/MEP product master.

Pure stdlib (uses rapidfuzz for scoring only if it is installed). No Odoo, no network.
Public API: normalise, extract_specs, base_name, spec_key, similarity, cluster.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Callable, Hashable, Iterable

try:  # optional speed-up, never required
    from rapidfuzz import fuzz as _rf_fuzz
except Exception:  # pragma: no cover
    _rf_fuzz = None

# --------------------------------------------------------------------------- constants

DEFAULT_NOISE_WORDS: tuple[str, ...] = (
    # generic noise
    "brand", "original", "genuine", "new", "make", "made", "quality", "imported",
    "local", "approved", "pcs", "pc", "nos", "each",
    # common MEP / construction brands
    "wavin", "georg fischer", "gf", "aquatherm", "pipelife", "uponor", "rehau",
    "victaulic", "grundfos", "ksb", "danfoss", "legrand", "schneider", "abb",
    "siemens", "hager", "bticino", "philips", "osram", "elsewedy", "el sewedy",
    "ducab", "nexans", "prysmian", "polycab", "havells", "hilti", "jotun",
    "national paints", "sika", "fosroc", "bosch", "makita", "dewalt", "stanley",
    "saudi", "ega", "pegler", "aliaxis",
)

PIPE_CONTEXT = {
    "pipe", "pipes", "elbow", "tee", "coupling", "socket", "reducer", "bend", "fitting",
    "fittings", "valve", "conduit", "ppr", "pvc", "upvc", "cpvc", "hdpe", "pe", "union",
    "nipple", "bush", "flange", "cap", "plug", "adaptor", "adapter", "tube",
    "ماسوره", "ماسورة", "مواسير", "كوع", "تي", "وصلة", "محبس",
}
THICKNESS_CONTEXT = {
    "plywood", "ply", "mdf", "board", "sheet", "plate", "glass", "gypsum", "panel",
    "insulation", "foam", "gasket", "liner", "membrane", "thk", "thick", "thickness",
    "hardboard", "laminate", "خشب", "لوح", "الواح",
}
REBAR_CONTEXT = {"bar", "bars", "rebar", "rebars", "deformed", "reinforcement", "حديد", "تسليح"}
SPEC_WORDS = {"thk", "thick", "thickness", "length", "len", "dia", "diameter", "size", "long"}

COLOURS = {
    "white": "white", "black": "black", "red": "red", "blue": "blue", "green": "green",
    "yellow": "yellow", "grey": "grey", "gray": "grey", "brown": "brown", "orange": "orange",
    "beige": "beige", "cream": "cream", "ivory": "ivory", "silver": "silver", "gold": "gold",
    "pink": "pink", "purple": "purple",
    "ابيض": "white", "اسود": "black", "احمر": "red", "ازرق": "blue", "اخضر": "green",
    "اصفر": "yellow", "رمادي": "grey", "بني": "brown", "برتقالي": "orange", "بيج": "beige",
    "كريمي": "cream", "فضي": "silver", "ذهبي": "gold", "وردي": "pink", "بنفسجي": "purple",
}
MATERIALS = {
    "ductile iron": "ductile iron", "cast iron": "cast iron", "stainless steel": "ss",
    "ppr": "ppr", "upvc": "upvc", "pvc": "pvc", "cpvc": "cpvc", "gi": "gi",
    "galvanized": "gi", "galvanised": "gi", "ms": "ms", "ss": "ss", "copper": "copper",
    "cu": "copper", "hdpe": "hdpe", "pe": "pe", "brass": "brass",
}
REBAR_SIZES = "6|8|10|12|14|16|18|20|22|25|28|32|36|40"

_AR_DIGITS = {ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")}
_AR_DIGITS.update({ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")})
_VULGAR = {"½": " 1/2", "¼": " 1/4", "¾": " 3/4", "⅓": " 1/3", "⅔": " 2/3",
           "⅛": " 1/8", "⅜": " 3/8", "⅝": " 5/8", "⅞": " 7/8"}

_NUM = r"\d+(?:\.\d+)?"


def _noise_re(words: Iterable[str]) -> re.Pattern | None:
    ws = sorted({w.strip().lower() for w in words if w and w.strip()}, key=len, reverse=True)
    if not ws:
        return None
    alt = "|".join(re.escape(w).replace(r"\ ", r"\s+") for w in ws)
    return re.compile(rf"(?<!\S)(?:{alt})(?!\S)")


_DEFAULT_NOISE_RE = _noise_re(DEFAULT_NOISE_WORDS)


def _fmt(v: float) -> str:
    return f"{v:.3f}".rstrip("0").rstrip(".")


def _fraction(m: re.Match) -> str:
    whole, num, den = m.group(1), int(m.group(2)), int(m.group(3))
    if den == 0:
        return m.group(0)
    return f"{_fmt((int(whole) if whole else 0) + num / den)}in "


# --------------------------------------------------------------------------- normalise

def normalise(name: Any, noise_words: Iterable[str] | None = None) -> str:
    """Canonical lower-case form of a product name (see module docs).

    ``noise_words`` replaces DEFAULT_NOISE_WORDS when given (pass () for none).
    """
    if name is None:
        return ""
    s = str(name)
    for k, v in _VULGAR.items():
        s = s.replace(k, v)
    s = unicodedata.normalize("NFKC", s).lower()
    s = s.replace("⁄", "/").translate(_AR_DIGITS)
    s = s.replace("٫", ".").replace("،", " ")
    s = re.sub("[ً-ٰٟـ]", "", s)
    s = re.sub("[أإآ]", "ا", s)
    # quotes -> "
    for ch in "”“″‟":
        s = s.replace(ch, '"')
    s = s.replace("′′", '"').replace("''", '"')
    s = re.sub(r"\s*[°º˚]", "deg", s)
    # Arabic unit words
    s = re.sub(r"(?<!\S)(?:درجه|درجة|درجات)(?!\S)", "deg", s)
    s = re.sub(r"(?<!\S)(?:انش|بوصه|بوصة)(?!\S)", "in", s)
    s = re.sub(r"(?<=\d)\s*(?:ملم|مم)(?!\S)", "mm", s)
    # area / mm units
    s = re.sub(r"sq\.?\s*m\.?\s*m\b", "mm2", s)
    s = re.sub(r"\bm\.\s?m\b\.?", "mm", s)
    s = re.sub(r"mm(?:\^2|2)(?!\d)", "mm2", s)
    # fractions (always inches) then inch marks
    s = re.sub(r'(?<![\d/.])(?:(\d+)[\s-]+)?(\d+)/(\d+)(?![\d/])\s*(?:"|inches\b|inch\b|in\b)?',
               _fraction, s)
    s = re.sub(rf'({_NUM})\s*"', r"\1in ", s)
    s = re.sub(rf"({_NUM})\s*(?:inches|inch|in)\b", r"\1in", s)
    s = re.sub(rf"({_NUM})\s*(?:mtrs?|meters?|metres?)\b", r"\1m", s)
    s = re.sub(r"(\d+)\s*cores?\b", r"\1c", s)
    s = re.sub(r"(?<![a-z])deg(?:rees?)?\b", "deg", s)
    s = re.sub(rf"({_NUM})\s+(mm2|mm|kv|v|m|deg|bar|in)\b", r"\1\2", s)
    # voltage ratings 0.6/1kv
    s = re.sub(rf"({_NUM})\s*/\s*({_NUM})\s*(kv|v)\b", r"\1-\2\3", s)
    # separators between numbers -> x
    s = re.sub(rf"({_NUM}(?:mm2|mm|cm|in|m|c)?)\s*[x×*]\s*(?=\d)", r"\1x", s)
    # material / code spellings
    s = re.sub(r"\bpp[\s-]r\b", "ppr", s)
    s = re.sub(r"\bu[\s-]pvc\b|\bpvc[\s-]u\b", "upvc", s)
    s = re.sub(r"\bc[\s-]pvc\b|\bpvc[\s-]c\b", "cpvc", s)
    s = re.sub(r"\bpn[\s-]*(\d+)", r"pn\1", s)
    s = re.sub(r"\bsch(?:edule|\.)?[\s-]*(\d+)", r"sch\1", s)
    s = re.sub(r"\bdn[\s-]*(\d+)", r"dn\1", s)
    # punctuation noise (keep '.' and '-' only between digits)
    s = re.sub(r"[^\w\s.\-]", " ", s).replace("_", " ")
    s = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", s)
    s = re.sub(r"(?<!\d)-|-(?!\d)", " ", s)
    pattern = _DEFAULT_NOISE_RE if noise_words is None else _noise_re(noise_words)
    s = re.sub(r"\s+", " ", s).strip()
    if pattern is not None:
        s = pattern.sub(" ", s)
        s = re.sub(r"\s+", " ", s).strip()
    return s


# --------------------------------------------------------------------------- specs

def _scan(norm: str) -> tuple[dict[str, str], str]:
    specs: dict[str, str] = {}
    ctx = set(norm.split())
    s = f" {norm} "

    def put(key: str, val: str) -> None:
        if key not in specs:
            specs[key] = val
        elif val not in specs[key].split("/"):
            specs[key] += "/" + val

    def take(pattern: str, fn: Callable[[re.Match], Any]) -> None:
        nonlocal s

        def cb(m: re.Match) -> str:
            return m.group(0) if fn(m) is False else " "
        s = re.sub(pattern, cb, s)

    def simple(key: str, prefix: str = "", suffix: str = "") -> Callable[[re.Match], None]:
        def f(m: re.Match) -> None:
            put(key, prefix + m.group(1) + suffix)
        return f

    B = r"(?<![\w.])"
    take(rf"{B}[ty]\s?({REBAR_SIZES})(?![\d.])", simple("rebar"))

    def cable(m: re.Match) -> None:
        put("cores", m.group(1))
        put("cable_mm2", m.group(2))
    take(rf"{B}(\d+)x({_NUM})mm2", cable)
    take(rf"{B}(\d+)c(?:x|(?![a-z]))", simple("cores"))
    take(rf"{B}({_NUM})mm2", simple("cable_mm2"))
    take(rf"{B}({_NUM}(?:-{_NUM})?(?:kv|v))(?![a-z\d])", simple("voltage"))
    take(r"(?<![a-z])pn(\d+)", simple("pn", prefix="pn"))
    take(rf"{B}({_NUM})bar(?![a-z])", simple("pn", suffix="bar"))
    take(r"(?<![a-z])sch(\d+)", simple("schedule", prefix="sch"))
    take(r"(?<![a-z])dn(\d+)", simple("pipe_dn"))
    take(rf"{B}({_NUM})deg", simple("angle"))

    def dims(m: re.Match) -> bool | None:
        parts = re.findall(rf"({_NUM})(mm|cm|in|m)?", m.group(0))
        units = {u for _, u in parts}
        if units <= {"", "mm", "cm"}:
            put("dims", m.group(0))
        elif units == {"in"}:
            put("pipe_in", "x".join(n for n, _ in parts))
        else:
            return False
        return None
    take(rf"{B}{_NUM}(?:mm|cm|in|m)?(?:x{_NUM}(?:mm|cm|in|m)?){{1,2}}(?![\w.])", dims)
    take(rf"{B}({_NUM})in(?![a-z])", simple("pipe_in"))
    take(rf"(?:length|len|long)\s*({_NUM})mm(?![a-z\d])", simple("length_mm"))
    take(rf"{B}({_NUM})mm\s+(?:long|length)(?![a-z])", simple("length_mm"))
    take(rf"{B}({_NUM})m(?![a-z\d])", simple("length_m"))

    def mm(m: re.Match) -> None:
        v = m.group(1)
        if ctx & REBAR_CONTEXT:
            put("rebar", v)
        elif ctx & THICKNESS_CONTEXT:
            put("thickness_mm", v)
        elif ctx & PIPE_CONTEXT:
            put("pipe_mm", v)
        else:
            put("size_mm", v)
    take(rf"{B}({_NUM})mm(?![a-z\d])", mm)

    mats = sorted(MATERIALS, key=len, reverse=True)
    take(r"(?<!\S)(" + "|".join(re.escape(w) for w in mats) + r")(?!\S)",
         lambda m: put("material", MATERIALS[m.group(1)]))
    cols = sorted(COLOURS, key=len, reverse=True)
    take(r"(?<!\S)(" + "|".join(re.escape(w) for w in cols) + r")(?!\S)",
         lambda m: put("colour", COLOURS[m.group(1)]))
    return specs, s


def extract_specs(name: Any, noise_words: Iterable[str] | None = None) -> dict[str, str]:
    """Spec tokens found in a name, e.g. {'pipe_in': '2', 'angle': '90'}.

    Keys: pipe_in, pipe_mm, pipe_dn, angle, pn, cable_mm2, cores, voltage, colour,
    thickness_mm, length_m, length_mm, rebar, material, schedule, dims, size_mm.
    """
    return _scan(normalise(name, noise_words))[0]


def base_name(name: Any, noise_words: Iterable[str] | None = None) -> str:
    """Normalised name with all spec tokens (and stray 'x', 'thk', 'dia'...) removed."""
    rest = _scan(normalise(name, noise_words))[1]
    toks = [t for t in rest.split() if t != "x" and t not in SPEC_WORDS and re.search(r"\w", t)]
    return " ".join(toks)


def spec_key(name: Any, noise_words: Iterable[str] | None = None) -> str:
    """Canonical string of a name's specs; use it as (part of) a blocking key."""
    return ";".join(f"{k}={v}" for k, v in sorted(extract_specs(name, noise_words).items()))


# --------------------------------------------------------------------------- similarity

def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio() * 100.0


def similarity(a: Any, b: Any) -> float:
    """0..100 token_set_ratio-style score on normalised names (empty -> 0)."""
    na, nb = normalise(a), normalise(b)
    if not na or not nb:
        return 0.0
    if _rf_fuzz is not None:
        return float(_rf_fuzz.token_set_ratio(na, nb))
    ta, tb = set(na.split()), set(nb.split())
    inter = " ".join(sorted(ta & tb))
    s1 = (inter + " " + " ".join(sorted(ta - tb))).strip()
    s2 = (inter + " " + " ".join(sorted(tb - ta))).strip()
    cands = [_ratio(s1, s2)]
    if inter:
        cands += [_ratio(inter, s1), _ratio(inter, s2)]
    return round(max(cands), 4)


# --------------------------------------------------------------------------- clustering

@dataclass
class Cluster:
    ids: list = field(default_factory=list)
    pairs: list = field(default_factory=list)  # (id_a, id_b, score)


def _default_id(item: Any) -> Hashable:
    if isinstance(item, dict):
        return item["id"]
    if isinstance(item, (tuple, list)):
        return item[0]
    return item.id


def cluster(items: Iterable[Any], key_fn: Callable[[Any], Any], threshold: float | None = None, *,
            block_fn: Callable[[Any], Hashable] | None = None,
            id_fn: Callable[[Any], Hashable] = _default_id,
            score_fn: Callable[[str, str], float] = similarity,
            min_size: int = 2) -> list[Cluster]:
    """Group items with union-find.

    threshold None: items with an equal key_fn(item) are grouped (pair score 100.0, star
    from the first member). threshold set: key_fn must return text; items are compared
    pairwise (O(n^2) per block) only inside the same block_fn(item) (default: one block)
    and joined when score_fn >= threshold. Returns Clusters (ids in input order) of size
    >= min_size, with every qualifying pair and its score.
    """
    items = list(items)
    ids = [id_fn(i) for i in items]
    parent = {i: i for i in ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    pairs: list[tuple] = []
    if threshold is None:
        first: dict[Any, Any] = {}
        for it, i in zip(items, ids):
            k = key_fn(it)
            if k in first:
                parent[find(i)] = find(first[k])
                pairs.append((first[k], i, 100.0))
            else:
                first[k] = i
    else:
        blocks: dict[Any, list[tuple]] = {}
        for it, i in zip(items, ids):
            blocks.setdefault(block_fn(it) if block_fn else None, []).append((i, key_fn(it)))
        for members in blocks.values():
            for x in range(len(members)):
                for y in range(x + 1, len(members)):
                    sc = score_fn(members[x][1], members[y][1])
                    if sc >= threshold:
                        parent[find(members[x][0])] = find(members[y][0])
                        pairs.append((members[x][0], members[y][0], sc))
    groups: dict[Any, Cluster] = {}
    for i in ids:
        groups.setdefault(find(i), Cluster()).ids.append(i)
    for a, b, sc in pairs:
        groups[find(a)].pairs.append((a, b, sc))
    return [g for g in groups.values() if len(g.ids) >= min_size]
