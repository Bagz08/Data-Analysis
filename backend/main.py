"""
Proposal Insight Engine — FastAPI Backend  v7.0
================================================
MSU-IIT · FastAPI + Supabase + KeyBERT

Routes
------
GET    /api/clusters              → cluster cards with counts
GET    /api/proposals/{name}      → ALL columns for one cluster
POST   /api/keywords              → KeyBERT with frequency counts + chart data
POST   /api/upload                → smart upload (majority fallback / ask user)
GET    /api/history               → upload history
DELETE /api/history/{id}          → delete upload record
"""

from __future__ import annotations

import json, os, re, math, io, datetime
from typing import Any
from collections import Counter
from difflib import SequenceMatcher

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from supabase import create_client, Client
from keybert import KeyBERT

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

load_dotenv()

# ═══════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════

CLUSTERS: list[str] = [
    "Colleges",
    "Office Of The Chancellor",
    "Office of the Vice Chancellor for Academic Affairs",
    "Office of the Vice Chancellor for Administration and Finance",
    "Office of the Vice Chancellor for International Affairs",
    "Office of the Vice Chancellor for Public Affairs",
    "Office of the Vice Chancellor for Research and Enterprise",
    "Office of the Vice Chancellor for Strategic Initiatives",
    "Office of the Vice Chancellor for Student Services",
]
FALLBACK_CLUSTER = "Colleges"

PASTEL = [
    "#FFB3BA", "#FFCBA4", "#FFF3A3", "#B8F0B8", "#A8D8FF",
    "#D4B8FF", "#FFB8E8", "#B8FFF0", "#FFD6A4", "#C8E6C9",
]

# ═══════════════════════════════════════════════════════════════
# FastAPI app
# ═══════════════════════════════════════════════════════════════

app = FastAPI(title="Proposal Insight Engine API", version="7.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def serve_index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


# ═══════════════════════════════════════════════════════════════
# Singletons
# ═══════════════════════════════════════════════════════════════

_sb: Client | None = None
_kw: KeyBERT | None = None


def get_sb() -> Client:
    global _sb
    if _sb is None:
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_KEY", "")
        if not url or not key:
            raise HTTPException(500, "SUPABASE_URL / SUPABASE_KEY not set in .env")
        _sb = create_client(url, key)
    return _sb


def get_kw() -> KeyBERT:
    global _kw
    if _kw is None:
        _kw = KeyBERT(model="all-MiniLM-L6-v2")
    return _kw


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def clean_entry(v: Any) -> Any:
    if isinstance(v, np.integer):   return int(v)
    if isinstance(v, np.floating):  return None if math.isnan(float(v)) else float(v)
    if isinstance(v, np.bool_):     return bool(v)
    if isinstance(v, np.ndarray):   return [clean_entry(x) for x in v.tolist()]
    if isinstance(v, pd.Timestamp): return v.isoformat()
    if isinstance(v, float):
        try:
            if math.isnan(v): return None
        except Exception:
            pass
    if isinstance(v, dict):  return {k: clean_entry(x) for k, x in v.items()}
    if isinstance(v, list):  return [clean_entry(x) for x in v]
    return v


def safe_str(v: Any) -> str:
    if v is None: return ""
    try:
        if isinstance(v, float) and math.isnan(v): return ""
    except TypeError:
        pass
    return str(v).strip()


def parse_number(v: Any) -> float:
    """Try to parse a numeric value from a string (handles commas, currency symbols)."""
    if v is None: return 0.0
    s = str(v).strip()
    s = re.sub(r'[₱$,\s]', '', s)
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


# ═══════════════════════════════════════════════════════════════
# Cluster matching
# ═══════════════════════════════════════════════════════════════

_STOP_W = frozenset({
    "the", "of", "for", "and", "in", "on", "to", "a", "an", "at",
    "by", "or", "from", "with",
})

_ABBREV: dict[str, str] = {
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
    "admin": "administration", "acad":  "academic",
    "intl":  "international",  "int'l": "international",
    "pub":   "public",         "stud":  "student",
    "svc":   "services",       "svcs":  "services",
    "res":   "research",       "ent":   "enterprise",
    "fin":   "finance",        "aff":   "affairs",
    "strat": "strategic",      "init":  "initiatives",
}


def _expand(text: str) -> str:
    return " ".join(_ABBREV.get(w.strip(".,;:()[]"), w) for w in text.lower().split())


def _sig(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z]+", text.lower())
            if t not in _STOP_W and len(t) > 1}


def _tok_score(a: str, b: str) -> float:
    sa, sb = _sig(a), _sig(b)
    if not sa or not sb: return 0.0
    inter = sa & sb
    if not inter: return 0.0
    return .65 * (len(inter) / min(len(sa), len(sb))) + .35 * (len(inter) / len(sa | sb))


def _build_acronym_map(cm: dict[str, int]) -> dict[str, int]:
    out: dict[str, int] = {}
    for name, cid in cm.items():
        words = name.split()
        ac1 = "".join(w[0] for w in words if w[0].isalpha()).lower()
        ac2 = "".join(w[0] for w in words
                      if w.lower() not in _STOP_W and w[0].isalpha()).lower()
        if len(ac1) >= 2: out[ac1] = cid
        if len(ac2) >= 2: out[ac2] = cid
    return out


def match_cluster(raw: str, clusters_map: dict[str, int]) -> int | None:
    needle = raw.lower().strip()
    if not needle:
        return None
    for n, cid in clusters_map.items():
        if needle == n.lower(): return cid
    for n, cid in clusters_map.items():
        h = n.lower()
        if needle in h or h in needle: return cid
    am = _build_acronym_map(clusters_map)
    compact = re.sub(r"[^a-z0-9]", "", needle)
    if compact in am: return am[compact]
    exp = _expand(raw)
    for n, cid in clusters_map.items():
        h = n.lower()
        if exp in h or h in exp: return cid
    best_s, best_c = 0.0, None
    for n, cid in clusters_map.items():
        s = max(_tok_score(needle, n), _tok_score(exp, n))
        if s > best_s: best_s, best_c = s, cid
    if best_s >= 0.60 and best_c: return best_c
    best_s, best_c = 0.0, None
    for n, cid in clusters_map.items():
        r = max(SequenceMatcher(None, needle, n.lower()).ratio(),
                SequenceMatcher(None, exp, n.lower()).ratio())
        if r > best_s: best_s, best_c = r, cid
    if best_s >= 0.70 and best_c: return best_c
    return None


# ═══════════════════════════════════════════════════════════════
# Column sniffers
# ═══════════════════════════════════════════════════════════════

def sniff_cluster_col(columns, df, cm):
    best_col, best_hits = None, 0
    for col in columns:
        hits = sum(1 for v in df[col].dropna().astype(str).head(30)
                   if match_cluster(v.strip(), cm) is not None)
        if hits > best_hits: best_hits, best_col = hits, col
    if best_hits >= 1: return best_col
    hints = {"cluster","office","department","unit","clustername","ovc","chancellor"}
    for col in columns:
        n = col.lower().replace(" ","").replace("_","")
        for h in hints:
            if h in n: return col
    return None


def sniff_resp_col(columns):
    hints = {"responsibility","resp","center","rc","responsibilitycenter"}
    for col in columns:
        n = col.lower().replace(" ","").replace("_","")
        for h in hints:
            if h in n: return col
    return None


def sniff_content_col(columns):
    hints = {"ppa","description","proposal","content","title","abstract",
             "subject","text","project","program","activity"}
    for col in columns:
        n = col.lower().replace(" ","").replace("_","")
        for h in hints:
            if h in n: return col
    return None


def sniff_amount_col(columns):
    hints = {"amount","cost","budget","total","allocation","fund amount"}
    for col in columns:
        n = col.lower().replace("_"," ")
        for h in hints:
            if h in n: return col
    return None


def sniff_fund_col(columns):
    hints = {"fund account","fundaccount","funding","source of fund","fundsource"}
    for col in columns:
        n = col.lower().replace("_"," ")
        for h in hints:
            if h in n: return col
    return None


# ═══════════════════════════════════════════════════════════════
# DB helpers
# ═══════════════════════════════════════════════════════════════

def fetch_clusters_map(sb: Client) -> dict[str, int]:
    try:
        rows = sb.table("clusters").select("id,name").execute().data or []
        if rows: return {r["name"]: r["id"] for r in rows}
    except Exception: pass
    return {name: idx + 1 for idx, name in enumerate(CLUSTERS)}


def _id_to_name(cm: dict[str, int]) -> dict[int, str]:
    return {cid: name for name, cid in cm.items()}


def _decode_row(r: dict) -> dict:
    """Decode a proposal row. content_text stores JSON of full row data."""
    ct = r.get("content_text") or ""
    try:
        return json.loads(ct)
    except (json.JSONDecodeError, TypeError):
        return {
            "Resp. Center": r.get("resp_center") or "",
            "Content":      ct,
        }


# ═══════════════════════════════════════════════════════════════
# API Routes
# ═══════════════════════════════════════════════════════════════

@app.get("/api/clusters")
def api_clusters():
    sb = get_sb()
    cm = fetch_clusters_map(sb)
    id2n = _id_to_name(cm)
    try:
        rows = sb.table("proposals").select("cluster_id,resp_center").execute().data or []
    except Exception as e:
        raise HTTPException(500, str(e))

    counts  = {n: 0 for n in CLUSTERS}
    rc_sets = {n: set() for n in CLUSTERS}
    for r in rows:
        cn = id2n.get(r.get("cluster_id"), "")
        if cn in counts:
            counts[cn] += 1
            rc = r.get("resp_center") or ""
            if rc: rc_sets[cn].add(rc)

    total = sum(counts.values())
    result = [{"index": i, "name": cn, "count": counts[cn],
               "rc_count": len(rc_sets[cn])} for i, cn in enumerate(CLUSTERS)]
    return {"clusters": result, "total": total}


# ─── Proposals (returns ALL original file columns) ────────────

@app.get("/api/proposals/{cluster_name}")
def api_proposals(cluster_name: str):
    sb = get_sb()
    cm = fetch_clusters_map(sb)
    cid = cm.get(cluster_name)
    if cid is None:
        return {"columns": [], "rows": [], "count": 0, "rc_count": 0, "kw_count": 0}
    try:
        rows = (sb.table("proposals")
                .select("id,cluster_id,resp_center,content_text,keywords")
                .eq("cluster_id", cid).execute().data or [])
    except Exception as e:
        raise HTTPException(500, str(e))
    if not rows:
        return {"columns": [], "rows": [], "count": 0, "rc_count": 0, "kw_count": 0}

    records = []
    kw_total = 0
    resp_set = set()
    for r in rows:
        rd = _decode_row(r)
        kws = r.get("keywords") or []
        kw_total += len(kws)
        resp = rd.get("Resp. Center", r.get("resp_center") or "")
        if resp: resp_set.add(resp)
        records.append(rd)

    df = pd.DataFrame(records)
    columns = list(df.columns)
    rows_out = df.fillna("").astype(str).to_dict(orient="records")

    return {
        "columns":  columns,
        "rows":     rows_out,
        "count":    len(records),
        "rc_count": len(resp_set),
        "kw_count": kw_total,
    }


# ─── Keywords (frequency counts + chart data) ─────────────────

class KeywordRequest(BaseModel):
    cluster_name: str
    cat_col:      str
    kw_col:       str


def _count_keyword(keyword: str, texts: list[str]) -> int:
    """Count total occurrences of keyword across all texts (case-insensitive)."""
    pattern = re.compile(re.escape(keyword), re.IGNORECASE)
    total = 0
    for t in texts:
        total += len(pattern.findall(t))
    return total


# Stop words for filtering noise from keyword extraction
_KW_STOP = frozenset({
    # Standard English
    "the", "and", "for", "with", "that", "this", "not", "from", "shall", "will",
    "of", "in", "on", "to", "a", "an", "at", "by", "or", "its", "is", "as",
    "was", "were", "be", "been", "being", "have", "has", "had", "do", "does",
    "did", "but", "if", "then", "than", "so", "no", "nor", "not", "own",
    "same", "such", "can", "may", "might", "also", "just", "very", "often",
    "every", "each", "any", "all", "both", "few", "more", "most", "other",
    "some", "than", "too", "only", "about", "above", "after", "before",
    "between", "into", "through", "during", "under", "over", "again",
    # Domain-specific noise
    "submission", "deadline", "specified", "later", "submitted", "year", "month",
    "high", "office", "total", "amount", "project", "program", "activities",
    "based", "using", "requirements", "inclusive", "within", "across", "related",
    "these", "those", "remarks", "status", "please", "assist", "ensure", "smooth",
    "performance", "paps", "unit", "center", "target", "number", "percentage",
    "proposal", "proposals", "budget", "fund", "funds", "item", "items",
    "particular", "particulars", "particularly", "necessary", "needed",
    "implementation", "implement", "conducted", "conduct", "purchase",
    "support", "supported", "including", "included", "provide", "provided",
    "maintain", "maintenance", "continue", "continued", "ongoing",
    "new", "existing", "current", "following", "according", "respectively",
    "various", "appropriate", "proper", "properly", "regular", "regularly",
    "effective", "efficient", "efficiently", "adequate", "adequately",
    # Common filler words in proposals
    "also", "another", "however", "therefore", "furthermore", "moreover",
    "addition", "additional", "respect", "relative", "given", "per",
    "via", "etc", "etc.", "approx", "approximately",
})


def _extract_phrases(text: str) -> list[str]:
    """Extract individual words (3+ chars) and bigrams from text."""
    words = re.findall(r'\b[a-z]{3,}\b', text.lower())
    # Single words
    singles = [w for w in words if w not in _KW_STOP]
    # Bigrams from consecutive non-stop words
    bigrams = []
    filtered = [w for w in words if w not in _KW_STOP]
    for i in range(len(filtered) - 1):
        bigrams.append(f"{filtered[i]} {filtered[i+1]}")
    return singles + bigrams


def _is_category_noise(phrase: str, cat_name: str) -> bool:
    """Check if a phrase is just the category name or a substring of it."""
    cat_lower = cat_name.lower().strip()
    phrase_lower = phrase.lower().strip()
    if phrase_lower == cat_lower:
        return True
    # Check if phrase is a substring of the category name
    if phrase_lower in cat_lower and len(phrase_lower) > 2:
        return True
    # Check if any word in the phrase is a direct word from the category name
    # that isn't a meaningful distinguishing word
    cat_words = set(cat_lower.split())
    phrase_words = set(phrase_lower.split())
    # If all words in the phrase appear in the category name, it's noise
    if phrase_words.issubset(cat_words):
        return True
    # Check known abbreviations that appear in category names
    _CAT_ABBREV = {"ovc", "ovcaa", "ovcaf", "ovcia", "ovcpa", "ovcre",
                   "ovcsi", "ovcss", "oc", "msu", "iit", "nstp"}
    if phrase_lower in _CAT_ABBREV:
        return True
    for w in phrase_words:
        if w in _CAT_ABBREV:
            return True
    return False


def _discover_keywords(kbrt, texts: list[str], cat_name: str = "",
                       all_category_texts: list[str] | None = None) -> list[tuple[str, int]]:
    """TF-IDF based keyword discovery + KeyBERT supplement.
    Returns list of (keyword, count) sorted by TF-IDF score descending."""
    cat_lower = cat_name.lower().strip()

    # --- Step 1: Extract all phrases per document for TF-IDF ---
    # Each text is treated as a "document"
    doc_phrases = []
    all_phrases_flat = []
    for t in texts:
        phrases = _extract_phrases(t)
        doc_phrases.append(phrases)
        all_phrases_flat.extend(phrases)

    if not all_phrases_flat:
        return []

    # --- Step 2: Compute TF-IDF scores ---
    # TF: frequency within this category's texts
    # IDF: inverse document frequency across ALL categories (or just this cluster)
    freq_counts = Counter(all_phrases_flat)
    n_docs = len(doc_phrases)

    # Document frequency: how many texts contain each phrase
    doc_freq: Counter = Counter()
    for phrases in doc_phrases:
        for p in set(phrases):  # unique per doc
            doc_freq[p] += 1

    # Use all_category_texts for IDF if available (cross-category comparison)
    if all_category_texts:
        idf_docs = []
        for t in all_category_texts:
            idf_docs.append(set(_extract_phrases(t)))
        total_idf_docs = len(idf_docs)
    else:
        idf_docs = [set(dp) for dp in doc_phrases]
        total_idf_docs = n_docs

    # Compute IDF for each phrase
    idf_scores: dict[str, float] = {}
    for phrase in freq_counts:
        df_count = sum(1 for doc in idf_docs if phrase in doc)
        # Smooth IDF: log((1 + N) / (1 + df)) + 1
        idf_scores[phrase] = math.log((1 + total_idf_docs) / (1 + df_count)) + 1

    # Compute TF-IDF and rank
    scored = []
    for phrase, count in freq_counts.items():
        if count < 1:
            continue
        if _is_category_noise(phrase, cat_name):
            continue
        if all(w in _KW_STOP for w in phrase.split()):
            continue
        # TF-IDF score
        tf = count / len(all_phrases_flat) if all_phrases_flat else 0
        tfidf = tf * idf_scores.get(phrase, 1.0)
        scored.append((phrase, count, tfidf))

    # Sort by TF-IDF score descending
    scored.sort(key=lambda x: x[2], reverse=True)

    # --- Step 3: KeyBERT supplement for meaningful phrases ---
    combined = " ".join(t for t in texts if len(t.strip()) > 2)
    kbert_kws: list[str] = []
    if len(combined.strip()) >= 20:
        try:
            kbert_kws = [kw for kw, _ in kbrt.extract_keywords(
                combined, keyphrase_ngram_range=(1, 2),
                stop_words="english", top_n=15)]
        except Exception: pass

    # Add KeyBERT phrases not already in results, if they have actual counts
    existing = {s[0] for s in scored}
    for kw in kbert_kws:
        kw_lower = kw.lower()
        if kw_lower in existing:
            continue
        if _is_category_noise(kw_lower, cat_name):
            continue
        if all(w in _KW_STOP for w in kw_lower.split()):
            continue
        count = _count_keyword(kw_lower, texts)
        if count >= 1:
            tf = count / len(all_phrases_flat) if all_phrases_flat else 0
            tfidf = tf * idf_scores.get(kw_lower, 1.0)
            scored.append((kw_lower, count, tfidf))
            existing.add(kw_lower)

    # Re-sort by TF-IDF and take top 10
    scored.sort(key=lambda x: x[2], reverse=True)
    return [(phrase, count) for phrase, count, _ in scored[:10]]


@app.post("/api/keywords")
def api_keywords(req: KeywordRequest):
    sb   = get_sb()
    kbrt = get_kw()
    cm   = fetch_clusters_map(sb)
    cid  = cm.get(req.cluster_name)
    if cid is None:
        return {"results": [], "chart_data": {}}

    try:
        rows = (sb.table("proposals")
                .select("id,resp_center,content_text,keywords")
                .eq("cluster_id", cid).execute().data or [])
    except Exception as e:
        raise HTTPException(500, str(e))
    if not rows:
        return {"results": [], "chart_data": {}}

    # Decode all rows to full data
    records = [_decode_row(r) for r in rows]
    df = pd.DataFrame(records)

    if req.cat_col not in df.columns or req.kw_col not in df.columns:
        raise HTTPException(400, f"Column not found. Available: {list(df.columns)}")

    # Detect report columns for the detailed view
    all_cols = list(df.columns)
    amount_col = sniff_amount_col(all_cols)
    fund_col   = sniff_fund_col(all_cols)
    ppa_col    = sniff_content_col(all_cols)
    desc_col   = None
    for hint in ["description", "desc", "details"]:
        for c in all_cols:
            if hint in c.lower() and c != ppa_col:
                desc_col = c
                break
        if desc_col:
            break

    # Report columns: PPA Name, Description, Amount, Fund Account
    report_cols = []
    for c in [ppa_col, desc_col, amount_col, fund_col]:
        if c and c in all_cols:
            report_cols.append(c)
    if not report_cols:
        report_cols = all_cols[:4]  # fallback

    # Collect ALL texts across the cluster for chart data
    all_texts = [str(v) for v in df[req.kw_col].dropna() if len(str(v).strip()) > 2]

    # Fill NaN in category column so no rows are lost
    df[req.cat_col] = df[req.cat_col].fillna("(Unspecified)")
    cats = [c for c in df[req.cat_col].unique() if str(c).strip()]
    results = []

    # Chart data
    chart_cats = []
    chart_proposals = []
    chart_amounts = []
    all_kw_counts: Counter = Counter()  # global tally across all categories

    for cat in cats:
        cdf = df[df[req.cat_col] == cat]
        if cdf.empty: continue

        # Get texts for THIS category
        cat_texts = [str(v) for v in cdf[req.kw_col].dropna() if len(str(v).strip()) > 2]

        # Discover keywords specific to this category (TF-IDF ranked)
        # Pass all cluster texts for IDF computation
        discovered = _discover_keywords(kbrt, cat_texts, cat_name=str(cat),
                                        all_category_texts=all_texts)

        # Build keyword results with colors
        kw_results = []
        for ki, (kw, count) in enumerate(discovered):
            color = PASTEL[ki % len(PASTEL)]
            kw_results.append({"kw": kw, "count": count, "color": color})
            all_kw_counts[kw] += count

        # Build rows for detailed report
        cat_rows_full = cdf.fillna("").astype(str).to_dict(orient="records")

        # Category amount total
        cat_amount = 0.0
        if amount_col and amount_col in cdf.columns:
            cat_amount = sum(parse_number(v) for v in cdf[amount_col])

        cat_label = str(cat)
        chart_cats.append(cat_label)
        chart_proposals.append(len(cdf))
        chart_amounts.append(round(cat_amount, 2))

        results.append({
            "cat":         cat_label,
            "n":           len(cdf),
            "kws":         kw_results,
            "columns":     report_cols,
            "rows":        cat_rows_full,
            "kw_col":      req.kw_col,
            "amount":      round(cat_amount, 2),
        })

    # Build global top 10 from accumulated counts across all categories
    top_global = all_kw_counts.most_common(10)
    global_kw_data = []
    for ki, (kw, count) in enumerate(top_global):
        color = PASTEL[ki % len(PASTEL)]
        global_kw_data.append({"kw": kw, "count": count, "color": color})

    chart_data = {
        "top_keywords":      global_kw_data,
        "categories":        chart_cats,
        "proposals_per_cat": chart_proposals,
        "amount_per_cat":    chart_amounts,
        "amount_col_name":   amount_col,
    }

    return {"results": results, "chart_data": chart_data}


# ─── Upload (majority fallback / ask user) ─────────────────────

@app.post("/api/upload")
async def api_upload(
    file: UploadFile = File(...),
):
    """Upload file. Unmatched rows are auto-assigned to the majority cluster."""
    sb   = get_sb()
    kbrt = get_kw()

    raw_bytes = await file.read()
    fname     = file.filename or "upload"

    try:
        if fname.lower().endswith(".csv"):
            raw_df = pd.read_csv(io.BytesIO(raw_bytes), dtype=str)
        else:
            raw_df = pd.read_excel(io.BytesIO(raw_bytes), dtype=str)
    except Exception as e:
        raise HTTPException(400, f"Could not parse file: {e}")

    raw_df.columns = [str(c).strip() for c in raw_df.columns]
    file_cols = list(raw_df.columns)
    if not file_cols:
        raise HTTPException(400, "File has no usable columns.")

    cm = fetch_clusters_map(sb)

    cluster_col = sniff_cluster_col(file_cols, raw_df, cm) or file_cols[0]
    resp_col    = sniff_resp_col(file_cols)
    content_col = sniff_content_col(file_cols)

    # Phase 1: classify each row
    matched_ids: list[int | None] = []
    for _, row in raw_df.iterrows():
        cluster_raw = safe_str(row.get(cluster_col, ""))
        matched_ids.append(match_cluster(cluster_raw, cm))

    matched_count   = sum(1 for m in matched_ids if m is not None)
    unmatched_count = sum(1 for m in matched_ids if m is None)

    # Auto-assign unmatched rows to the majority cluster
    if unmatched_count > 0:
        # Count how many rows matched each cluster
        from collections import Counter as _Ctr
        cluster_counts = _Ctr(m for m in matched_ids if m is not None)
        if cluster_counts:
            # Pick the cluster with the most matched rows
            fallback_id = cluster_counts.most_common(1)[0][0]
        else:
            # No rows matched at all — use first cluster as fallback
            fallback_id = list(cm.values())[0]
    else:
        fallback_id = list(cm.values())[0]  # won't be used

    id2n = _id_to_name(cm)

    # Phase 2: build records
    records: list[dict] = []
    for i, (_, row) in enumerate(raw_df.iterrows()):
        mid = matched_ids[i]
        if mid is None:
            mid = fallback_id

        resp_raw    = safe_str(row.get(resp_col, ""))    if resp_col    else ""
        content_raw = safe_str(row.get(content_col, "")) if content_col else ""

        kws: list[str] = []
        if content_raw and len(content_raw) >= 15:
            try:
                kws = [kw for kw, _ in kbrt.extract_keywords(
                    content_raw, keyphrase_ngram_range=(1, 2),
                    stop_words="english", top_n=8)]
            except Exception: pass

        # Store ALL original columns as JSON in content_text
        row_data = {k: clean_entry(v) for k, v in row.items()}
        records.append({
            "cluster_id":   clean_entry(mid),
            "resp_center":  clean_entry(resp_raw) or None,
            "content_text": json.dumps(row_data, ensure_ascii=False),
            "keywords":     clean_entry(kws),
            "file_id":      None,  # will be set after insert
        })

    if not records:
        raise HTTPException(400, "No records could be extracted.")

    try:
        sb.table("proposals").insert(records).execute()
    except Exception as e:
        raise HTTPException(500, f"DB insert failed: {e}")

    # Record upload with row count for deletion tracking
    file_record = None
    try:
        result = sb.table("uploaded_files").insert({
            "filename":    fname,
            "upload_date": datetime.datetime.utcnow().isoformat(),
            "row_count":   len(records),
        }).execute()
        file_record = result.data[0] if result.data else None
    except Exception: pass

    # Tag proposals with file_id so they can be deleted later
    if file_record and file_record.get("id"):
        fid = file_record["id"]
        try:
            # Get the proposal IDs just inserted (most recent N rows)
            recent = (sb.table("proposals")
                      .select("id")
                      .is_("file_id", "null")
                      .order("id", desc=True)
                      .limit(len(records)).execute().data or [])
            for p in recent:
                sb.table("proposals").update({"file_id": fid}).eq("id", p["id"]).execute()
        except Exception: pass

    fallback_name = id2n.get(fallback_id, FALLBACK_CLUSTER) if unmatched_count > 0 else ""

    return {
        "needs_cluster": False,
        "inserted":      len(records),
        "unmatched":     unmatched_count,
        "total":         len(raw_df),
        "detected": {
            "cluster_col": cluster_col,
            "resp_col":    resp_col,
            "content_col": content_col,
        },
        "fallback_cluster": fallback_name,
    }


# ─── History ──────────────────────────────────────────────────

@app.get("/api/history")
def api_history():
    sb = get_sb()
    try:
        rows = (sb.table("uploaded_files")
                .select("id,filename,upload_date,row_count")
                .order("upload_date", desc=True)
                .limit(50).execute().data or [])
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"history": rows}


@app.delete("/api/history/{file_id}")
def api_delete_history(file_id: int):
    sb = get_sb()
    try:
        # Delete proposals associated with this file
        sb.table("proposals").delete().eq("file_id", file_id).execute()
        # Delete the upload record
        sb.table("uploaded_files").delete().eq("id", file_id).execute()
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"deleted": file_id}


@app.get("/api/health")
def api_health():
    return {"status": "ok", "version": "7.0"}
