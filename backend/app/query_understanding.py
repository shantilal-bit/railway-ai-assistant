"""Lightweight Railway Query Understanding, Bilingual Glossary Normalization, and Language Detection.

Designed to:
1. Preserve the user's original question verbatim.
2. Normalize colloquial Hindi, voice-typing errors, Hinglish, and abbreviations into
   clean bilingual search terms without making an extra LLM network call.
3. Avoid guessing or expanding ambiguous unknown terms into wrong railway posts/rules.
4. Detect Devanagari Hindi, Roman Hindi (Hinglish), mixed Hindi-English, and English accurately.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

# Whole-word / boundary helpers that work reliably for both Latin and Devanagari scripts
_BOUNDARY_PREFIX = r"(?<![0-9A-Za-z\u0900-\u097F])"
_BOUNDARY_SUFFIX = r"(?![0-9A-Za-z\u0900-\u097F])"

# Curated, unambiguous Indian Railway glossary entries:
# (compiled_patterns, canonical_english_label, expansion_keywords_for_search)
_RAW_GLOSSARY: list[tuple[tuple[str, ...], str, tuple[str, ...]]] = [
    # Operating / Station / Signal Staff Roles
    (
        (
            "पंचमैन",
            "पॉइंट्समैन",
            "प्वाइंट्समैन",
            "पॉइंटमैन",
            "पॉइंट्स मैन",
            "प्वाइंट्स मैन",
            "pointsman",
            "points man",
            "pointman",
            "punchman",
            "panchman",
        ),
        "Pointsman",
        ("Pointsman", "pointsman", "points", "hand signal", "shunting"),
    ),
    (
        (
            "गेटमैन",
            "गेट मैन",
            "फाटक वाला",
            "समपार रक्षक",
            "gateman",
            "gate man",
            "gatekeeper",
            "gate keeper",
        ),
        "Gateman",
        ("Gateman", "level crossing", "gate", "boom", "road traffic"),
    ),
    (
        (
            "स्टेशन मास्टर",
            "स्टेशनमास्टर",
            "सहायक स्टेशन मास्टर",
            "station master",
            "station superintendent",
            "asm",
            "sm",
        ),
        "Station Master",
        ("Station Master", "station master", "operating", "signals", "line clear"),
    ),
    (
        (
            "ट्रेन मैनेजर",
            "गार्ड",
            "गाड",
            "guard",
            "train manager",
            "goods guard",
        ),
        "Guard / Train Manager",
        ("Guard", "Train Manager", "brake van", "tail lamp", "all right signal"),
    ),
    (
        (
            "लोको पायलट",
            "सहायक लोको पायलट",
            "ड्राइवर",
            "loco pilot",
            "assistant loco pilot",
            "alp",
            "motorman",
            "driver",
        ),
        "Loco Pilot",
        ("Loco Pilot", "Driver", "whistle", "aspect", "speed"),
    ),
    (
        (
            "केबिनमैन",
            "केबिन मैन",
            "लीवरमैन",
            "स्विचमैन",
            "cabinman",
            "cabin man",
            "leverman",
            "switchman",
        ),
        "Cabinman / Leverman / Switchman",
        ("Cabinman", "Switchman", "Leverman", "cabin", "interlocking"),
    ),
    (
        (
            "शंटर",
            "शंटिंग मास्टर",
            "शंटिंग",
            "shunting",
            "shunter",
            "shunting master",
        ),
        "Shunting",
        ("shunting", "Shunting", "points", "speed", "hand signal"),
    ),
    (
        (
            "कीमैन",
            "गैंगमैन",
            "ट्रैकमैन",
            "ट्रैक मेंटेनर",
            "keyman",
            "gangman",
            "trackman",
            "track maintainer",
        ),
        "Trackman / Keyman",
        ("Keyman", "Trackman", "Gangman", "patrolling", "track"),
    ),
    # Core G&SR Concepts, Signals & Emergencies
    (
        (
            "spad",
            "सिग्नल पार",
            "खतरे के सिग्नल",
            "signal passed at danger",
            "overshooting signal",
        ),
        "SPAD (Signal Passed At Danger)",
        ("SPAD", "Signal Passed At Danger", "stop signal", "danger", "aspect"),
    ),
    (
        (
            "कोहरा संकेत",
            "कोहरा सिग्नल",
            "कुहरा सिग्नल",
            "कोहरा",
            "कुहरा",
            "पटाखा",
            "डेटोनेटर",
            "fog signal",
            "fog signals",
            "foggy weather",
            "detonator",
            "detonators",
            "fsp",
        ),
        "Fog Signal / Detonator",
        ("fog signal", "detonator", "detonators", "foggy weather", "visibility"),
    ),
    (
        (
            "कॉशन ऑर्डर",
            "कौशन ऑर्डर",
            "सावधानी आदेश",
            "सतर्कता आदेश",
            "caution order",
            "speed restriction",
            "गति प्रतिबंध",
        ),
        "Caution Order",
        ("Caution Order", "speed restriction", "engineering restriction"),
    ),
    (
        (
            "हस्त सिग्नल",
            "हैंड सिग्नल",
            "लाल झंडी",
            "हरी झंडी",
            "hand signal",
            "hand signals",
            "all right signal",
            "ऑल राइट सिग्नल",
        ),
        "Hand Signal",
        ("hand signal", "all right signal", "red flag", "green flag", "lamp"),
    ),
    (
        (
            "फेसिंग पॉइंट",
            "ट्रेलिंग पॉइंट",
            "कांटा",
            "काँटा",
            "facing point",
            "facing points",
            "trailing points",
            "clamp",
            "padlock",
        ),
        "Facing / Trailing Points",
        ("facing points", "points", "clamp", "padlock", "speed"),
    ),
    (
        (
            "लाइन क्लियर",
            "line clear",
            "authority to proceed",
            "plct",
            "paper line clear",
            "ब्लॉक सेक्शन",
            "block section",
        ),
        "Authority to Proceed / Line Clear",
        ("Line Clear", "Authority to Proceed", "block section", "PLCT"),
    ),
    (
        (
            "ट्रेन पार्टिंग",
            "गाड़ी का टूटना",
            "train parting",
            "parting of train",
        ),
        "Train Parting",
        ("train parting", "divided train", "coupling"),
    ),
    (
        (
            "हॉट एक्सल",
            "hot axle",
            "ब्रेक बाइंडिंग",
            "brake binding",
        ),
        "Hot Axle / Brake Binding",
        ("hot axle", "brake binding", "examination"),
    ),
    (
        (
            "समपार",
            "लेवल क्रॉसिंग",
            "level crossing",
            "lc gate",
        ),
        "Level Crossing Gate",
        ("level crossing", "gate", "road traffic", "boom"),
    ),
    (
        (
            "g&sr",
            "gsr",
            "general rule",
            "subsidiary rule",
            "सामान्य नियम",
            "सहायक नियम",
        ),
        "General and Subsidiary Rules",
        ("General Rule", "Subsidiary Rule"),
    ),
    (
        (
            "sf-5",
            "sf5",
            "dar",
            "मेजर पेनल्टी",
            "चार्जशीट",
            "charge sheet",
            "discipline and appeal",
        ),
        "Discipline & Appeal Rules (DAR)",
        ("DAR", "Discipline", "Appeal", "SF-5", "penalty"),
    ),
    (
        (
            "अवकाश",
            "छुट्टी",
            "आकस्मिक अवकाश",
            "casual leave",
            "average pay",
            "lap",
            "lhap",
            "irec",
        ),
        "Leave Rules",
        ("leave", "IREC", "LAP", "LHAP", "casual leave"),
    ),
]

_COMPILED_GLOSSARY: list[tuple[list[re.Pattern[str]], str, tuple[str, ...]]] = [
    (
        [
            re.compile(f"{_BOUNDARY_PREFIX}{re.escape(alias)}{_BOUNDARY_SUFFIX}", re.IGNORECASE)
            for alias in aliases
        ],
        canonical,
        keywords,
    )
    for aliases, canonical, keywords in _RAW_GLOSSARY
]

_DUTY_INTENT_PATTERN = re.compile(
    f"{_BOUNDARY_PREFIX}(?:"
    r"ड्यूटी|ड्यूटीज|कर्तव्य|जिम्मेदारी|जिम्मेदारियां|जिम्मेदारियाँ|दायित्व|कामकाज|काम|"
    r"duty|duties|responsibility|responsibilities|role|functions|work|kaam|jimmedari|zimmedari|kartavya"
    f"){_BOUNDARY_SUFFIX}",
    re.IGNORECASE,
)

_DEFINITION_INTENT_PATTERN = re.compile(
    f"{_BOUNDARY_PREFIX}(?:"
    r"क्या है|क्या होता है|क्या होती है|पूरा नाम|मतलब|परिभाषा|अर्थ|"
    r"what is|full form|meaning|define|definition|kya hai|matlab|pura naam"
    f"){_BOUNDARY_SUFFIX}",
    re.IGNORECASE,
)

# Extract rule numbers such as "4.10", "GR 4.10", "SR 4.10.1", "Rule 3.04(1)"
_RULE_TOKEN_PATTERN = re.compile(
    r"\b(?:(GR|SR|G\.R\.|S\.R\.|Rule|Para|Clause|RBE)\s*(?:No\.?)?\s*)?"
    r"(\d{1,3}\.\d{1,3}(?:\.\d{1,3})*(?:\([0-9a-zA-Z]+\))*|\d{1,4}/\d{2,4})\b",
    re.IGNORECASE,
)

# Hinglish / Romanized Hindi stopwords & grammar cues (high-signal tokens)
_STRONG_HINGLISH_MARKERS = {
    "kya",
    "hai",
    "hain",
    "kaise",
    "kyu",
    "kyon",
    "kab",
    "kahan",
    "kaun",
    "batao",
    "bataiye",
    "samjhao",
    "samjhaiye",
    "niyam",
    "niyamon",
    "jimmedari",
    "jimmedariya",
    "zimmedari",
    "kartavya",
    "karta",
    "karti",
    "karte",
    "hota",
    "hoti",
    "hote",
    "chahiye",
    "matlab",
    "pura",
    "poora",
    "kaam",
    "baare",
    "ke",
    "ki",
    "mein",
}

_WEAK_HINGLISH_MARKERS = {
    "ka",
    "ko",
    "se",
    "par",
    "pe",
    "me",
    "aur",
    "ya",
    "kis",
    "kisi",
    "liye",
    "wala",
    "wali",
    "wale",
    "kitna",
    "kitni",
    "kitne",
    "naam",
}

_QUERY_STOPWORDS = {
    "क्या",
    "है",
    "हैं",
    "की",
    "के",
    "का",
    "को",
    "में",
    "से",
    "पर",
    "और",
    "या",
    "कैसे",
    "कब",
    "कहाँ",
    "कौन",
    "करता",
    "करती",
    "करते",
    "होता",
    "होती",
    "होते",
    "what",
    "is",
    "are",
    "the",
    "of",
    "in",
    "on",
    "for",
    "to",
    "and",
    "or",
    "a",
    "an",
    "explain",
    "tell",
    "about",
    "kya",
    "hai",
    "hain",
    "ki",
    "ka",
    "ke",
    "ko",
    "me",
    "mein",
    "par",
    "se",
}


@dataclass(frozen=True)
class NormalizedQuery:
    original_query: str
    embedding_query: str
    fts_query: str
    matched_concepts: tuple[str, ...]
    expanded_keywords: tuple[str, ...]
    rule_tokens: tuple[str, ...]
    has_duty_intent: bool
    has_definition_intent: bool
    detected_script: str  # "devanagari" | "hinglish" | "english" | "mixed"


def detect_query_script(question: str) -> str:
    text = (question or "").strip()
    if not text:
        return "english"

    has_devanagari = any("\u0900" <= ch <= "\u097f" for ch in text)
    latin_tokens = [tok.lower() for tok in re.findall(r"[a-zA-Z]+", text)]
    has_latin_words = any(len(t) >= 2 and t not in {"gr", "sr", "sm", "rbe"} for t in latin_tokens)

    strong_hinglish = sum(1 for t in latin_tokens if t in _STRONG_HINGLISH_MARKERS)
    weak_hinglish = sum(1 for t in latin_tokens if t in _WEAK_HINGLISH_MARKERS)

    if has_devanagari:
        return "mixed" if has_latin_words else "devanagari"

    if strong_hinglish >= 1 or (strong_hinglish + weak_hinglish >= 2):
        return "hinglish"

    return "english"


def detect_query_language(question: str, preferred_language: str = "auto") -> str:
    """Honors explicit UI selection first; otherwise detects Devanagari, mixed Hindi, and Roman Hinglish."""
    pref = (preferred_language or "auto").lower().strip()
    if pref in ("en", "hi"):
        return pref

    script = detect_query_script(question)
    if script in ("devanagari", "mixed", "hinglish"):
        return "hi"
    return "en"


def extract_rule_tokens(text: str) -> tuple[str, ...]:
    """Extracts normalized rule numbers in both numeric and GR/SR forms for bidirectional matching."""
    cleaned = (text or "").strip()
    if not cleaned:
        return ()

    seen: set[str] = set()
    ordered: list[str] = []

    def _add(tok: str) -> None:
        norm = re.sub(r"\s+", " ", tok.strip())
        key = norm.lower()
        if norm and key not in seen:
            seen.add(key)
            ordered.append(norm)

    for match in _RULE_TOKEN_PATTERN.finditer(cleaned):
        prefix = (match.group(1) or "").strip().upper().replace(".", "")
        num = match.group(2).strip()
        if prefix:
            _add(f"{prefix} {num}")
        _add(num)
        # If bare numeric rule (e.g. "4.10"), include GR/SR variants for bidirectional matching
        if "." in num and not prefix:
            _add(f"GR {num}")
            _add(f"SR {num}")
        elif prefix == "GR":
            _add(f"Rule {num}")
            _add(f"SR {num}")
        elif prefix == "SR":
            _add(f"GR {num}")

    return tuple(ordered)


def normalize_railway_query(question: str) -> NormalizedQuery:
    """Builds a safe normalized/expanded search representation while preserving original_query."""
    original = re.sub(r"\s+", " ", (question or "").strip())
    if not original:
        return NormalizedQuery(
            original_query="",
            embedding_query="",
            fts_query="",
            matched_concepts=(),
            expanded_keywords=(),
            rule_tokens=(),
            has_duty_intent=False,
            has_definition_intent=False,
            detected_script="english",
        )

    matched_concepts: list[str] = []
    expanded_keywords: list[str] = []
    seen_kw: set[str] = set()

    def _add_kw(term: str) -> None:
        clean = term.strip()
        low = clean.lower()
        if clean and low not in seen_kw:
            seen_kw.add(low)
            expanded_keywords.append(clean)

    for patterns, canonical, keywords in _COMPILED_GLOSSARY:
        if any(pat.search(original) for pat in patterns):
            if canonical not in matched_concepts:
                matched_concepts.append(canonical)
            for kw in keywords:
                _add_kw(kw)

    has_duty = bool(_DUTY_INTENT_PATTERN.search(original))
    has_def = bool(_DEFINITION_INTENT_PATTERN.search(original))
    rule_tokens = extract_rule_tokens(original)
    for rt in rule_tokens:
        _add_kw(rt)

    # Note: generic intent words ("duties", "responsibilities", "rules") are NOT added to
    # expanded_keywords so concept-overlap checks never match unrelated posts merely mentioning "duties"/"rules".
    intent_fts_terms: list[str] = ["duties", "responsibilities"] if has_duty else []

    # Extract meaningful content tokens from original query (excluding stopwords)
    raw_tokens = re.findall(r"[0-9A-Za-z\u0900-\u097F./-]+", original)
    content_tokens = [
        tok.strip(".,?;:()[]{}\"'")
        for tok in raw_tokens
        if tok.strip(".,?;:()[]{}\"'").lower() not in _QUERY_STOPWORDS
        and len(tok.strip(".,?;:()[]{}\"'")) >= 2
    ]

    # Build embedding_query:
    # Preserve original query AND enrich with unambiguous canonical railway concepts & duty/rule context
    emb_parts: list[str] = [original]
    if matched_concepts:
        emb_parts.append(" — " + ", ".join(matched_concepts))
    if has_duty and matched_concepts:
        emb_parts.append("duties and responsibilities under railway rules")
    elif has_def and matched_concepts:
        emb_parts.append("meaning, rule provisions, and procedures")
    if rule_tokens:
        emb_parts.append(" ".join(rule_tokens[:4]))

    # Add up to a few high-signal canonical keywords not already in emb_parts
    emb_base = " ".join(emb_parts)
    extra_emb_kw = [kw for kw in expanded_keywords if kw.lower() not in emb_base.lower()][:6]
    embedding_query = f"{emb_base} {' '.join(extra_emb_kw)}".strip()

    # Build fts_query: combine canonical English keywords + numeric rule tokens + non-stopword content tokens
    fts_parts: list[str] = []
    seen_fts: set[str] = set()
    for candidate in [*expanded_keywords, *intent_fts_terms, *content_tokens]:
        for sub in candidate.split():
            cleaned_sub = sub.strip(".,?;:()[]{}\"'")
            low = cleaned_sub.lower()
            if cleaned_sub and len(cleaned_sub) >= 2 and low not in _QUERY_STOPWORDS and low not in seen_fts:
                seen_fts.add(low)
                fts_parts.append(cleaned_sub)

    fts_query = " ".join(fts_parts[:14]) if fts_parts else original

    return NormalizedQuery(
        original_query=original,
        embedding_query=embedding_query,
        fts_query=fts_query,
        matched_concepts=tuple(matched_concepts),
        expanded_keywords=tuple(expanded_keywords),
        rule_tokens=rule_tokens,
        has_duty_intent=has_duty,
        has_definition_intent=has_def,
        detected_script=detect_query_script(original),
    )
