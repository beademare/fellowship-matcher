import os
import re
from typing import List, Dict, Any, Set

import pandas as pd
import streamlit as st
from pdfminer.high_level import extract_text

# ============================================================
# CONFIG
# ============================================================

PDF_FOLDER = "pdf_positions"  # folder in the repo with all PDFs
LANG_LIST = [
    "english", "french", "spanish", "arabic",
    "russian", "chinese", "portuguese", "italian"
]

# ============================================================
# BASIC CLEANING
# ============================================================

ILLEGAL_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")


def clean_text(s: str) -> str:
    """Basic cleaning: remove control chars, normalize bullets & spaces."""
    if not isinstance(s, str):
        return ""
    s = ILLEGAL_RE.sub("", s)
    mapping = {
        "": "•", "▪": "•", "●": "•", "◦": "•",
        "\uf0b7": "•", "\uf0a7": "•",
        "–": "-", "—": "-",
    }
    for k, v in mapping.items():
        s = s.replace(k, v)
    s = s.replace("\xad", "")            # soft hyphen
    s = re.sub(r"[ \t]+", " ", s)       # spaces
    s = re.sub(r"\n{3,}", "\n\n", s)    # collapse long blank sequences
    return s.strip()


def extract_pdf_text(path: str) -> str:
    text = extract_text(path)
    return clean_text(text)


# ============================================================
# SECTION & FIELD EXTRACTION
# ============================================================

def split_sections(text: str) -> Dict[str, str]:
    """Split by numbered headings '1. General Information' etc."""
    sections = {}
    pattern = re.compile(r"^\s*(\d+)\.\s+(.+?)\s*:?\s*$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    if not matches:
        return sections
    for i, m in enumerate(matches):
        title = m.group(2).strip()
        start = m.end()
        end = matches[i+1].start() if i+1 < len(matches) else len(text)
        sections[title] = text[start:end].strip()
    return sections


def find_section(sections: Dict[str, str], keyword: str) -> str:
    for title, content in sections.items():
        if keyword.lower() in title.lower():
            return content
    return ""


def extract_organization(full_text: str) -> str:
    """Organization is usually line after 'Fellowship Award Specification'."""
    lines = [l.strip() for l in full_text.splitlines() if l.strip()]
    for i, line in enumerate(lines):
        if "Fellowship Award Specification" in line:
            if i + 1 < len(lines):
                return lines[i+1]
    return ""


def extract_basic_fields(full_text: str):
    """
    Try to extract title, duty station, sector of assignment
    from the whole document.
    """
    title = ""
    duty = ""
    sector = ""
    m_title = re.search(r"Title:\s*(.+)", full_text, flags=re.I)
    m_duty = re.search(r"Duty Station:\s*(.+)", full_text, flags=re.I)
    m_sector = re.search(r"Sector of assignment:\s*(.+)", full_text, flags=re.I)
    if m_title:
        title = m_title.group(1).strip()
    if m_duty:
        duty = m_duty.group(1).strip()
    if m_sector:
        sector = m_sector.group(1).strip()
    return title, duty, sector


# ============================================================
# BULLET RECONSTRUCTION & CLASSIFICATION
# ============================================================

SUBSECTIONS = {
    "education", "work experience", "professional experience",
    "languages", "language skills",
    "other skills", "technical skills",
    "competencies", "core competencies", "core competencies skills"
}

DEGREE_KW = ["degree", "bachelor", "master", "phd", "education", "university"]
LANG_KW = ["language", "fluency", "fluent", "mother tongue", "working knowledge"] + LANG_LIST
EXP_KW = ["experience", "years", "year", "background"]
SKILL_KW = ["excel", "power", "analysis", "statistics", "python", "gis", "sql", "stata", "spss", "skill", "software"]
COMP_KW = ["competenc", "teamwork", "communication", "leadership", "planning", "results focus"]


def rebuild_items(text: str) -> List[str]:
    """
    Rebuild bullet-like items as full sentences/requirements:
    - merge wrapped lines
    - drop pure headings
    """
    if not text:
        return []
    lines = text.splitlines()
    items = []
    cur = ""

    def flush():
        nonlocal cur
        if cur.strip():
            items.append(re.sub(r"\s+", " ", cur).strip())
        cur = ""

    for raw in lines:
        l = raw.strip()
        if not l:
            flush()
            continue
        # skip subsection headings
        if l.lower().rstrip(":") in SUBSECTIONS:
            flush()
            continue
        # bullet marker
        if l.startswith(("•", "-", "*")):
            flush()
            l = l.lstrip("•-* \t")
            cur = l
        else:
            if cur:
                cur += " " + l
            else:
                cur = l
    flush()
    return items


def classify_type(text: str) -> str:
    """Classify sentence/requirement into degree/lang/exp/skill/competency/other."""
    low = text.lower()
    if any(w in low for w in DEGREE_KW):
        return "degree"
    if any(w in low for w in LANG_KW):
        return "language"
    if any(w in low for w in EXP_KW):
        return "experience"
    if any(w in low for w in SKILL_KW):
        return "skill"
    if any(w in low for w in COMP_KW):
        return "competency"
    return "other"


def tokenize(text: str) -> Set[str]:
    return {w for w in re.findall(r"[a-zA-Z]+", text.lower()) if w}


def extract_languages_from_text(text: str) -> List[str]:
    low = text.lower()
    found = set()
    for lang in LANG_LIST:
        if lang in low:
            found.add(lang.capitalize())
    return sorted(found)


# ============================================================
# LOAD ALL POSITIONS FROM LOCAL PDF FOLDER
# ============================================================

@st.cache_data(show_spinner=True)
def load_positions(pdf_folder: str = PDF_FOLDER) -> List[Dict[str, Any]]:
    files = sorted(
        f for f in os.listdir(pdf_folder)
        if f.lower().endswith(".pdf")
    )
    positions = []

    for fname in files:
        code = os.path.splitext(fname)[0]
        path = os.path.join(pdf_folder, fname)

        try:
            full_text = extract_pdf_text(path)
        except Exception as e:
            print("Error reading", code, ":", e)
            continue

        sections = split_sections(full_text)
        qual_text = find_section(sections, "Qualification")
        duties_text = find_section(sections, "Duties")

        org = extract_organization(full_text)
        title, duty, sector = extract_basic_fields(full_text)

        qual_items = rebuild_items(qual_text)
        duty_items = rebuild_items(duties_text)

        grouped = {
            "degree": [],
            "language": [],
            "experience": [],
            "skill": [],
            "competency": [],
        }

        for it in qual_items:
            t = classify_type(it)
            if t in grouped:
                grouped[t].append(it)

        degree_text = " ".join(grouped["degree"])
        language_text = " ".join(grouped["language"])
        skill_text = " ".join(grouped["skill"])
        exp_text = " ".join(grouped["experience"])
        comp_text = " ".join(grouped["competency"])
        langs = extract_languages_from_text(language_text)

        positions.append({
            "code": code,
            "path": path,
            "org": org,
            "title": title,
            "duty": duty,
            "sector": sector,
            "qual_grouped": grouped,
            "duties": duty_items,
            "degree_text": degree_text,
            "language_text": language_text,
            "skill_text": skill_text,
            "exp_text": exp_text,
            "comp_text": comp_text,
            "languages": langs,
        })

    return positions


# ============================================================
# MATCHING
# ============================================================

def set_overlap_score(user_set: Set[str], pos_set: Set[str]) -> float:
    if not user_set or not pos_set:
        return 0.0
    inter = user_set & pos_set
    return len(inter) / len(user_set)


def rank_positions(
    positions: List[Dict[str, Any]],
    deg_str: str,
    lang_str: str,
    skill_str: str,
    interest_str: str,
    cv_text: str,
    w_degree: float,
    w_lang: float,
    w_skill: float,
    w_interest: float,
) -> List[Dict[str, Any]]:

    # build user token sets
    deg_tokens = tokenize(deg_str + " " + cv_text)
    skill_tokens = tokenize(skill_str + " " + cv_text)
    interest_tokens = tokenize(interest_str + " " + cv_text)

    user_langs = {l.strip().lower() for l in re.split(r"[;,]", lang_str) if l.strip()}

    results = []

    for pos in positions:
        pos_deg_tokens = tokenize(pos["degree_text"])
        pos_skill_tokens = tokenize(pos["skill_text"])
        interest_corpus = " ".join(pos["duties"]) + " " + (pos["sector"] or "")
        pos_interest_tokens = tokenize(interest_corpus)

        degree_score = set_overlap_score(deg_tokens, pos_deg_tokens)
        skill_score = set_overlap_score(skill_tokens, pos_skill_tokens)
        interest_score = set_overlap_score(interest_tokens, pos_interest_tokens)

        pos_langs_lower = {l.lower() for l in pos["languages"]}
        if pos_langs_lower:
            lang_intersection = user_langs & pos_langs_lower
            lang_score = len(lang_intersection) / len(pos_langs_lower)
        else:
            lang_score = 0.0

        # normalize weights so they sum to 1
        total_w = w_degree + w_lang + w_skill + w_interest
        if total_w == 0:
            w_degree_n = 0.4
            w_lang_n = 0.3
            w_skill_n = 0.2
            w_interest_n = 0.1
        else:
            w_degree_n = w_degree / total_w
            w_lang_n = w_lang / total_w
            w_skill_n = w_skill / total_w
            w_interest_n = w_interest / total_w

        overall = (
            w_degree_n * degree_score +
            w_lang_n * lang_score +
            w_skill_n * skill_score +
            w_interest_n * interest_score
        )

        results.append({
            "Position code": pos["code"],
            "Organization": pos["org"],
            "Duty station": pos["duty"],
            "Sector": pos["sector"],
            "Score": round(overall * 100, 1),
            "Degree match %": round(degree_score * 100, 1),
            "Language match %": round(lang_score * 100, 1),
            "Skill match %": round(skill_score * 100, 1),
            "Interest match %": round(interest_score * 100, 1),
            "Languages (position)": ", ".join(pos["languages"]),
            "pos_obj": pos,
        })

    return sorted(results, key=lambda r: r["Score"], reverse=True)


# ============================================================
# STYLING
# ============================================================

def style_score(score: float) -> str:
    """Return a color based on score."""
    if score >= 80:
        return "background-color: #c8e6c9;"  # greenish
    if score >= 60:
        return "background-color: #fff9c4;"  # yellowish
    return "background-color: #ffcdd2;"      # reddish


# ============================================================
# STREAMLIT UI
# ============================================================

st.set_page_config(page_title="UN Fellowship Matcher", layout="wide")

st.title("🎯 UN Italian Fellowships – Match Finder")

st.markdown(
    "This tool helps you and your friends find which UN Italian Fellowship "
    "positions fit **your degree, languages, skills and interests**.\n\n"
    "All processing is done on the server hosting this app – no data is stored."
)

st.sidebar.header("Your profile")

deg_input = st.sidebar.text_input(
    "Your degree / field of study",
    value="environmental science, international relations, economics",
)

lang_input = st.sidebar.text_input(
    "Languages you speak (comma-separated)",
    value="English, French",
)

skills_input = st.sidebar.text_area(
    "Your main skills / tools",
    value="data analysis, excel, project management, gis, statistics",
)

interests_input = st.sidebar.text_area(
    "Your thematic interests",
    value="climate change, agriculture, water, governance",
)

cv_text = st.sidebar.text_area(
    "Optional: paste your CV text here",
    value="",
    help="Paste plain text from your CV to improve matching (no data is stored).",
)

st.sidebar.markdown("---")
st.sidebar.markdown("**Match weights** (how important each dimension is):")
w_deg = st.sidebar.slider("Degree importance", 0.0, 1.0, 0.4, 0.05)
w_lang = st.sidebar.slider("Languages importance", 0.0, 1.0, 0.3, 0.05)
w_skill = st.sidebar.slider("Skills importance", 0.0, 1.0, 0.2, 0.05)
w_int = st.sidebar.slider("Interests importance", 0.0, 1.0, 0.1, 0.05)

top_n = st.sidebar.slider("Number of positions to show", 5, 40, 15)

st.markdown("---")

if st.button("🔍 Find my best matches"):
    with st.spinner("Loading and analyzing fellowship PDFs..."):
        positions = load_positions()
        results = rank_positions(
            positions,
            deg_input,
            lang_input,
            skills_input,
            interests_input,
            cv_text,
            w_deg,
            w_lang,
            w_skill,
            w_int,
        )
        top = results[:top_n]

    st.subheader("Top matches")

    table_df = pd.DataFrame([{
        "Position code": r["Position code"],
        "Organization": r["Organization"],
        "Duty station": r["Duty station"],
        "Sector": r["Sector"],
        "Score %": r["Score"],
        "Degree %": r["Degree match %"],
        "Lang %": r["Language match %"],
        "Skill %": r["Skill match %"],
        "Interest %": r["Interest match %"],
    } for r in top])

    # apply simple row coloring based on Score
    styled = table_df.style.apply(
        lambda row: [style_score(row["Score %"])] * len(row),
        axis=1
    )

    st.dataframe(styled, use_container_width=True)

    st.markdown("---")
    st.subheader("Position details")

    for r in top:
        pos = r["pos_obj"]
        header = f"{r['Position code']} – {r['Organization'] or 'Unknown org'}"
        if pos["duty"]:
            header += f" – {pos['duty']}"
        header += f" ({r['Score']}% match)"

        with st.expander(header):
            col1, col2, col3 = st.columns(3)
            col1.metric("Overall match", f"{r['Score']}%")
            col2.metric("Degree match", f"{r['Degree match %']}%")
            col3.metric("Language match", f"{r['Language match %']}%")

            st.markdown(f"**Sector:** {pos['sector'] or 'N/A'}")
            st.markdown(f"**Local PDF path in repo:** `{pos['path']}`")

            st.markdown("**📚 Degree-related requirements:**")
            if pos["qual_grouped"]["degree"]:
                st.markdown("- " + "\n- ".join(pos["qual_grouped"]["degree"]))
            else:
                st.write("_No degree-related sentences detected._")

            st.markdown("**🗣 Language-related requirements:**")
            if pos["qual_grouped"]["language"]:
                st.markdown("- " + "\n- ".join(pos["qual_grouped"]["language"]))
            else:
                st.write("_No language-related sentences detected._")

            st.markdown("**🛠 Skills-related requirements:**")
            if pos["qual_grouped"]["skill"]:
                st.markdown("- " + "\n- ".join(pos["qual_grouped"]["skill"]))
            else:
                st.write("_No explicit skills sentences detected._")

            st.markdown("**🧩 Experience-related requirements:**")
            if pos["qual_grouped"]["experience"]:
                st.markdown("- " + "\n- ".join(pos["qual_grouped"]["experience"]))
            else:
                st.write("_No explicit experience sentences detected._")

            st.markdown("**🌐 Competency-related requirements:**")
            if pos["qual_grouped"]["competency"]:
                st.markdown("- " + "\n- ".join(pos["qual_grouped"]["competency"]))
            else:
                st.write("_No explicit competency sentences detected._")

            st.markdown("**📌 Main duties / tasks:**")
            if pos["duties"]:
                st.markdown("- " + "\n- ".join(pos["duties"]))
            else:
                st.write("_No duties section found._")
else:
    st.info("Fill your profile on the left and click **'🔍 Find my best matches'** to see ranked positions.")
