"""Validation va helper funksiyalar"""
import re
from typing import List, Dict, Optional


def validate_questions(questions: List[Dict], require_correct: bool = False) -> List[Dict]:
    """AI qaytargan savollarni tekshirish va tozalash."""
    
    _MARK_RE = r"(?:✅|✔|✓|\*|\[\s*x\s*\]|\(\s*x\s*\))"
    _LABEL_RE = r"(?:\(?[A-Da-d]\)?|\d{1,3})\s*[).:\-]\s*"

    def _is_marked_correct(raw: str) -> bool:
        """To'g'ri javob belgilari tekshiruvi"""
        s = (raw or "").strip()
        if not s:
            return False
        s = s.lstrip("~").strip()
        if re.match(rf"^{_MARK_RE}\s*", s, flags=re.IGNORECASE):
            return True
        s2 = re.sub(rf"^{_LABEL_RE}", "", s)
        if re.match(rf"^{_MARK_RE}\s*", s2, flags=re.IGNORECASE):
            return True
        if re.search(r"\*\s*$", s) or re.search(r"\*\s*$", s2):
            return True
        return False

    def _clean_option(raw: str) -> str:
        """Variantni tozalash"""
        s = (raw or "").strip()
        s = s.lstrip("~").strip()
        s = re.sub(rf"^{_MARK_RE}\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(rf"^{_LABEL_RE}", "", s)
        s = re.sub(rf"^{_MARK_RE}\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\(\s*(?:to[''`]?\s*g[''`]?\s*ri|togri|correct)\s*\)\s*$", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*\*\s*$", "", s)
        s = s.strip().rstrip(" ;")
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def _norm(s: str) -> str:
        """String normalizatsiya"""
        return re.sub(r"\s+", " ", (s or "").strip()).lower()

    def _coerce_correct_index(raw_correct, raw_len: int) -> Optional[int]:
        """Correct answer indeksini aniqlash"""
        if raw_correct is None or isinstance(raw_correct, bool):
            return None
        idx: Optional[int] = None
        try:
            idx = int(str(raw_correct).strip())
        except Exception:
            idx = None
        if idx is not None:
            if 0 <= idx < raw_len:
                return idx
            if 1 <= idx <= raw_len:
                return idx - 1
        s = str(raw_correct).strip()
        if re.fullmatch(r"[A-Ja-j]", s):
            idx = ord(s.lower()) - ord("a")
            if 0 <= idx < raw_len:
                return idx
        return None

    valid: list[Dict] = []
    for q in questions or []:
        try:
            if not isinstance(q, dict):
                continue

            question = str(q.get('question') or '').strip()
            if not question:
                continue

            raw_any = q.get('options') or []
            if not isinstance(raw_any, list):
                raw_any = []
            raw_options = [str(x) for x in raw_any]

            # Correct answer ni raw options bo'yicha topish
            marked = [i for i, opt in enumerate(raw_options) if _is_marked_correct(opt)]
            correct_raw_idx: Optional[int] = None
            if len(marked) == 1:
                correct_raw_idx = marked[0]
            else:
                correct_raw_idx = _coerce_correct_index(q.get('correct_answer'), raw_len=len(raw_options))

            # Options ni tozalash va dedup
            dedup: list[str] = []
            mapping: dict[int, int] = {}
            seen: dict[str, int] = {}

            for i, opt in enumerate(raw_options):
                cleaned = _clean_option(opt)
                if not cleaned:
                    continue
                cleaned = cleaned[:100]
                key = _norm(cleaned)
                if key in seen:
                    mapping[i] = seen[key]
                    continue
                seen[key] = len(dedup)
                mapping[i] = len(dedup)
                dedup.append(cleaned)
                if len(dedup) >= 10:
                    break

            if len(dedup) < 2:
                continue

            correct: Optional[int] = None
            if correct_raw_idx is not None and correct_raw_idx in mapping:
                mapped = mapping[correct_raw_idx]
                if 0 <= mapped < len(dedup):
                    correct = mapped

            if require_correct and correct is None:
                continue

            valid.append({
                'question': question[:500],
                'options': dedup,
                'correct_answer': correct,
                'explanation': str((q.get('explanation') or '')).strip()[:1000],
            })
        except Exception:
            continue

    return valid


def sanitize_ai_input(text: str, max_chars: int = 35000) -> str:
    """Juda uzun matnni AI uchun qisqartirish."""
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text

    lines = text.splitlines()
    keep: list[str] = []
    for line in lines:
        if (
            re.search(r"^\s*\d{1,3}[).]\s+\S", line)
            or re.search(r"^\s*[A-Da-d][).]\s+\S", line)
            or re.search(r"^\s*~\s+\S", line)
            or re.search(r"^\s*savol\s*\d{1,3}\b", line, re.IGNORECASE)
            or re.search(r"\b(javoblar|javob|to'g'ri\s+javob|answer|answers|key)\b", line, re.IGNORECASE)
            or re.search(r"\b\d{1,3}\s*[-:=]\s*[A-Da-d]\b", line)
            or re.search(r"\b\d{1,3}\s*[-:=]\s*\d{1,3}\b", line)
            or "?" in line
        ):
            keep.append(line)
        if sum(len(x) + 1 for x in keep) >= max_chars:
            break

    compact = "\n".join(keep).strip()
    if len(compact) >= 200:
        return compact[:max_chars]

    return text[:max_chars]


def extract_answer_key_map(text: str, tail_chars: int = 12000) -> Dict[int, str]:
    """Fayl ichida javoblar kalitini ajratib olish.
    
    Misollar:
      - "Javoblar: 1-A, 2-C, 3-B"
      - "Answers: 1=B 2=D 3=A"
    
    Returns:
        {1: "A", 2: "C", ...}
    """
    text = text or ""
    if not text.strip():
        return {}

    tail = text[-tail_chars:] if tail_chars > 0 else text
    lines = tail.splitlines()
    key_re = re.compile(r"\b(javoblar|javob|answer\s*key|answers?)\b", re.IGNORECASE)

    found_keyword = False
    start_idx = 0
    for i, ln in enumerate(lines):
        if key_re.search(ln):
            found_keyword = True
            start_idx = i
            break

    segment = "\n".join(lines[start_idx:]) if found_keyword else tail
    pairs = re.findall(r"\b(\d{1,3})\s*(?:[).])?\s*[-:=]\s*([A-Ja-j]|[1-9]\d{0,2})\b", segment)

    if found_keyword and len(pairs) < 2:
        pairs = re.findall(r"\b(\d{1,3})\s*([A-Ja-j])\b", segment)

    if not found_keyword and len(pairs) < 5:
        return {}

    out: Dict[int, str] = {}
    for qn_raw, ans_raw in pairs:
        try:
            qn = int(qn_raw)
        except Exception:
            continue
        if not (1 <= qn <= 1000):
            continue
        ans = str(ans_raw).strip()
        if not ans:
            continue
        out.setdefault(qn, ans)

    return out


def apply_answer_key_to_questions(questions: List[Dict], answer_key: Dict[int, str]) -> int:
    """Answer key'ni questions'ga qo'llash.
    
    Returns:
        Nechta savolda correct qo'yildi
    """
    if not questions or not answer_key:
        return 0

    applied = 0
    for idx, q in enumerate(questions):
        try:
            qn = idx + 1
            raw = answer_key.get(qn)
            if not raw:
                continue
            raw = str(raw).strip()
            if not raw:
                continue
            opts = q.get("options") or []
            if not isinstance(opts, list) or len(opts) < 2:
                continue

            mapped: Optional[int] = None
            if re.fullmatch(r"[A-Ja-j]", raw):
                mapped = ord(raw.lower()) - ord("a")
            else:
                try:
                    mapped = int(raw) - 1
                except Exception:
                    mapped = None

            if mapped is None or not (0 <= mapped < len(opts)):
                continue

            if (q.get("correct_answer") is None) or True:  # ANSWER_KEY_OVERRIDE
                q["correct_answer"] = mapped
                applied += 1
        except Exception:
            continue

    return applied


def quick_has_quiz_patterns(text: str) -> bool:
    """Tezkor tekshiruv: savol/variant patterns bormi?"""
    if not text:
        return False
    sample = text[:8000]
    has_q = bool(re.search(r"(^|\n)\s*\d{1,3}[).]\s+\S", sample))
    has_savol = bool(re.search(r"(^|\n)\s*savol\s*\d{1,3}\b", sample, re.IGNORECASE))
    has_qmark = "?" in sample
    has_opts = bool(re.search(r"(^|\n)\s*(?:[A-Da-d][).]|[1-4][).])\s+\S", sample))
    has_opts2 = bool(re.search(r"(^|\n)\s*[1-9]\d{0,2}\s*(?:[).:-]|\s)\s+\S", sample))
    has_tilde_opts = bool(re.search(r"(^|\n)\s*~\s+\S", sample))
    
    return (
        (has_q and (has_opts or has_opts2 or has_tilde_opts)) or
        (has_savol and (has_opts or has_opts2 or has_tilde_opts)) or
        (has_qmark and (has_opts or has_opts2 or has_tilde_opts))
    )


def parse_tilde_quiz(text: str) -> List[Dict]:
    """
    Algoritmik parser:
    Savol satri: '?' bor bo'lgan satr (yoki 'Savol N' satri).
    Variantlar: '~ ' bilan boshlanuvchi satrlar.
    Blok yakuni: bo'sh satr yoki '}' satri yoki keyingi savol.
    """
    if not text:
        return []
    lines = [ln.rstrip() for ln in text.splitlines()]
    questions: list[Dict] = []
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        if not ln:
            i += 1
            continue
        if ln.startswith("~"):
            i += 1
            continue
        if ln == "}":
            i += 1
            continue

        is_q = ("?" in ln) or bool(re.match(r"^savol\s*\d{1,3}\b", ln, re.IGNORECASE))
        if not is_q:
            i += 1
            continue

        q_text = ln
        opts: list[str] = []
        j = i + 1
        while j < len(lines):
            nxt = lines[j].strip()
            if not nxt:
                if opts:
                    break
                j += 1
                continue
            if nxt == "}":
                j += 1
                break
            if (("?" in nxt) or bool(re.match(r"^savol\s*\d{1,3}\b", nxt, re.IGNORECASE))) and not nxt.startswith("~"):
                break
            if nxt.startswith("~"):
                opt = nxt.lstrip("~").strip()
                # ko'p uchraydigan tugash belgilari
                opt = opt.rstrip(" ;")
                if opt:
                    opts.append(opt)
            j += 1

        if len(opts) >= 2:
            questions.append({
                "question": q_text,
                "options": opts[:10],
                "correct_answer": None,
                "explanation": ""
            })

        i = max(i + 1, j)

    return questions


def parse_numbered_quiz(text: str) -> List[Dict]:
    """
    Algoritmik parser:
    - Savol: "1) ...", "1. ...", "Savol 1 ...", yoki "?" bor satr
    - Variantlar: "A) ...", "B) ...", "1) ..." (1..10), "~ ..." yoki ketma-ket qisqa satrlar
    """
    if not text:
        return []

    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    questions: list[Dict] = []

    def _is_option_line(s: str) -> bool:
        s = (s or "").strip()
        if not s:
            return False
        if s.startswith("~"):
            return True
        if re.match(r"^\s*[A-Da-d][).:\-]\s+\S", s):
            return True
        m = re.match(r"^\s*([1-9]\d{0,2})[).:\-]\s+\S", s)
        if m:
            try:
                n = int(m.group(1))
            except Exception:
                n = 999
            return 1 <= n <= 10
        return False

    def _is_question_start(s: str) -> bool:
        s = (s or "").strip()
        if not s:
            return False
        # optionlarni savol deb olmaslik
        if _is_option_line(s):
            return False
        return (
            bool(re.match(r"^\s*\d{1,3}[).]\s+\S", s))
            or bool(re.match(r"^\s*savol\s*\d{1,3}\b", s, re.IGNORECASE))
            or ("?" in s)
        )

    def _extract_option(s: str) -> Optional[str]:
        s = (s or "").strip()
        if not s:
            return None
        if s.startswith("~"):
            opt = s.lstrip("~").strip()
            return opt or None
        m = re.match(r"^\s*[A-Da-d][).:\-]\s*(.+)$", s)
        if m:
            opt = m.group(1).strip()
            return opt or None
        m = re.match(r"^\s*([1-9]\d{0,2})[).:\-]\s*(.+)$", s)
        if m:
            try:
                n = int(m.group(1))
            except Exception:
                n = 999
            if 1 <= n <= 10:
                opt = m.group(2).strip()
                return opt or None
        return None

    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        if not ln:
            i += 1
            continue

        if not _is_question_start(ln):
            i += 1
            continue

        # 1) savol matni bir necha qatordan iborat bo'lishi mumkin
        q_lines = [ln]
        j = i + 1
        while j < len(lines):
            nxt = lines[j].strip()
            if not nxt:
                j += 1
                continue
            if _is_option_line(nxt):
                break
            if _is_question_start(nxt):
                break
            if len(nxt) <= 200:
                q_lines.append(nxt)
                j += 1
                continue
            break
        q_text = " ".join(q_lines).strip()

        # 2) variantlarni yig'amiz
        opts: list[str] = []
        k = j
        while k < len(lines):
            nxt = lines[k].strip()
            if not nxt:
                if opts:
                    break
                k += 1
                continue
            if _is_question_start(nxt) and not _is_option_line(nxt):
                break

            opt = _extract_option(nxt)
            if opt is None:
                # raqamsiz variantlar: qisqa qatordan iborat blok
                if len(nxt) <= 120 and not _is_question_start(nxt):
                    opt = nxt
                else:
                    break

            opt = (opt or "").rstrip(" ;").strip()
            if opt:
                opts.append(opt)
            k += 1
            if len(opts) >= 10:
                break

        if len(opts) >= 2:
            questions.append({
                "question": q_text,
                "options": opts[:10],
                "correct_answer": None,
                "explanation": ""
            })

        i = max(i + 1, k)

    return questions

