"""Quick test for the enhanced match_cluster logic."""
import re
from difflib import SequenceMatcher

_STOP_WORDS = frozenset({
    "the", "of", "for", "and", "in", "on", "to", "a", "an", "at",
    "by", "or", "its", "is", "as", "from", "with",
})

_ABBREVIATIONS = {
    "ovc":   "office of the vice chancellor",
    "vc":    "vice chancellor",
    "ovcaa": "office of the vice chancellor for academic affairs",
    "ovcaf": "office of the vice chancellor for administration and finance",
    "ovcia": "office of the vice chancellor for international affairs",
    "ovcpa": "office of the vice chancellor for public affairs",
    "ovcre": "office of the vice chancellor for research and enterprise",
    "ovcsi": "office of the vice chancellor for strategic initiatives",
    "ovcss": "office of the vice chancellor for student services",
    "oc":    "office of the chancellor",
    "admin":  "administration",
    "acad":   "academic",
    "intl":   "international",
    "int'l":  "international",
    "pub":    "public",
    "stud":   "student",
    "svc":    "services",
    "svcs":   "services",
    "res":    "research",
    "ent":    "enterprise",
    "fin":    "finance",
    "aff":    "affairs",
    "strat":  "strategic",
    "init":   "initiatives",
}

clusters_map = {
    "Colleges": 1,
    "Office Of The Chancellor": 2,
    "Office of the Vice Chancellor for Academic Affairs": 3,
    "Office of the Vice Chancellor for Administration and Finance": 4,
    "Office of the Vice Chancellor for International Affairs": 5,
    "Office of the Vice Chancellor for Public Affairs": 6,
    "Office of the Vice Chancellor for Research and Enterprise": 7,
    "Office of the Vice Chancellor for Strategic Initiatives": 8,
    "Office of the Vice Chancellor for Student Services": 9,
}

id_to_name = {v: k for k, v in clusters_map.items()}


def _build_acronym_map(cm):
    am = {}
    for name, cid in cm.items():
        words = name.split()
        acronym = "".join(w[0] for w in words if w[0].isupper() or w[0].isalpha()).lower()
        if len(acronym) >= 2:
            am[acronym] = cid
        acronym_no_stop = "".join(w[0] for w in words if w.lower() not in _STOP_WORDS).lower()
        if len(acronym_no_stop) >= 2 and acronym_no_stop != acronym:
            am[acronym_no_stop] = cid
    return am


def _expand(text):
    words = text.lower().split()
    return " ".join(_ABBREVIATIONS.get(w.strip(".,;:()[]"), w) for w in words)


def _sig(text):
    tokens = re.findall(r"[a-z]+", text.lower())
    return {t for t in tokens if t not in _STOP_WORDS and len(t) > 1}


def _tok(a, b):
    sa, sb = _sig(a), _sig(b)
    if not sa or not sb:
        return 0.0
    inter = sa & sb
    if not inter:
        return 0.0
    smaller = min(len(sa), len(sb))
    return 0.65 * (len(inter) / smaller) + 0.35 * (len(inter) / len(sa | sb))


def _fuzzy(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def match_cluster(raw, cm):
    needle = raw.lower().strip()
    if not needle:
        return None
    for name, cid in cm.items():
        if needle == name.lower():
            return cid
    for name, cid in cm.items():
        hay = name.lower()
        if needle in hay or hay in needle:
            return cid
    am = _build_acronym_map(cm)
    compact = re.sub(r"[^a-z0-9]", "", needle)
    if compact in am:
        return am[compact]
    expanded = _expand(raw)
    for name, cid in cm.items():
        hay = name.lower()
        if expanded in hay or hay in expanded:
            return cid
    best_s, best_c = 0.0, None
    for name, cid in cm.items():
        s = max(_tok(needle, name), _tok(expanded, name))
        if s > best_s:
            best_s, best_c = s, cid
    if best_s >= 0.60 and best_c is not None:
        return best_c
    best_s, best_c = 0.0, None
    for name, cid in cm.items():
        r = max(_fuzzy(needle, name), _fuzzy(expanded, name))
        if r > best_s:
            best_s, best_c = r, cid
    if best_s >= 0.70 and best_c is not None:
        return best_c
    return None


# ── Test cases ──
tests = [
    ("OVC for International Affairs", 5),
    ("OVCPA", 6),
    ("OVC for Acad Affairs", 3),
    ("Office of the VC for Student Services", 9),
    ("OVCRE", 7),
    ("Colleges", 1),
    ("OVC Intl Affairs", 5),
    ("OVCAF", 4),
    ("OVCSI", 8),
    ("OVC for Public Affairs", 6),
    ("Office of the Chancellor", 2),
    ("OVC for Admin and Finance", 4),
    ("OVC for Strat Initiatives", 8),
    ("OVC Research and Enterprise", 7),
    ("OVC Student Svc", 9),
]

print("=" * 80)
print(f"{'INPUT':<45} {'EXPECTED':<8} {'GOT':<8} {'STATUS'}")
print("=" * 80)
all_pass = True
for raw, expected_id in tests:
    got = match_cluster(raw, clusters_map)
    status = "✅ PASS" if got == expected_id else "❌ FAIL"
    if got != expected_id:
        all_pass = False
    expected_name = id_to_name.get(expected_id, "?")[:30]
    got_name = id_to_name.get(got, "None")[:30]
    print(f"{raw:<45} {expected_name:<8} {got_name:<8} {status}")

print("=" * 80)
print(f"\n{'ALL TESTS PASSED ✅' if all_pass else 'SOME TESTS FAILED ❌'}")
