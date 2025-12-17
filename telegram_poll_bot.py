#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Quiz Bot - Fayl tahlil qilib quiz yaratadigan bot
"""

import os
import re
import logging
import json
import httpx
import hashlib
import asyncio
import time
from typing import List, Dict, Optional
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
from telegram.error import BadRequest
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, 
    filters, ContextTypes, PicklePersistence, PollAnswerHandler, ChatMemberHandler
)
from telegram.constants import ParseMode
import docx
import PyPDF2
from io import BytesIO

# Logging sozlamalari
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot token
BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY', '')
DEEPSEEK_API_URL = 'https://api.deepseek.com/v1/chat/completions'
# Default: deepseek-chat (barqarorroq JSON); kerak bo'lsa reasoner fallback ishlatiladi
DEEPSEEK_MODEL = os.getenv('DEEPSEEK_MODEL', 'deepseek-chat')

# Storage
from storage import Storage
storage = Storage()

# ==================== SAFETY / LIMITS ====================
# Guruhda parallel testlar ko'payib ketmasligi uchun default cheklovlar.
# Kerak bo'lsa keyin config/env orqali sozlab olamiz.
MAX_ACTIVE_QUIZZES_PER_GROUP = 2
MAX_ACTIVE_QUIZZES_PER_USER_IN_GROUP = 1

# ==================== FILE VALIDATION / LIMITS ====================
MIN_QUESTIONS_REQUIRED = int(os.getenv("MIN_QUESTIONS_REQUIRED", "2"))
MAX_QUESTIONS_PER_QUIZ = int(os.getenv("MAX_QUESTIONS_PER_QUIZ", "100"))
# AI/algoritmik parser tezroq ishlashi uchun default maqsadli limit (xohlasangiz env bilan oshiring)
TARGET_QUESTIONS_PER_QUIZ = int(os.getenv("TARGET_QUESTIONS_PER_QUIZ", "50"))
MAX_TEXT_CHARS_FOR_AI = int(os.getenv("MAX_TEXT_CHARS_FOR_AI", "35000"))
REQUIRE_CORRECT_ANSWER = os.getenv("REQUIRE_CORRECT_ANSWER", "1").strip() not in ["0", "false", "False"]
MAX_AI_SECONDS = int(os.getenv("MAX_AI_SECONDS", "180"))
# AI so'rovlarini navbat bilan qilish (ommaviy ishlatishda bot qotib qolmasligi uchun)
MAX_CONCURRENT_AI_REQUESTS = int(os.getenv("MAX_CONCURRENT_AI_REQUESTS", "2"))
# Javoblar kaliti odatda oxirida bo'ladi — shuni qidiradigan "tail" uzunligi
ANSWER_KEY_TAIL_CHARS = int(os.getenv("ANSWER_KEY_TAIL_CHARS", "12000"))
# Agar faylda javoblar kaliti topilsa, AI bergan correct_answer ustidan yozib yuborish
ANSWER_KEY_OVERRIDE = os.getenv("ANSWER_KEY_OVERRIDE", "1").strip() not in ["0", "false", "False"]

_AI_SEMAPHORE: Optional[asyncio.Semaphore] = None


def _get_ai_semaphore() -> asyncio.Semaphore:
    global _AI_SEMAPHORE
    if _AI_SEMAPHORE is None:
        limit = int(MAX_CONCURRENT_AI_REQUESTS) if MAX_CONCURRENT_AI_REQUESTS else 1
        _AI_SEMAPHORE = asyncio.Semaphore(max(1, limit))
    return _AI_SEMAPHORE


def quick_has_quiz_patterns(text: str) -> bool:
    """AI'ga yuborishdan oldin tezkor tekshiruv: savol/variant patterns bormi?"""
    if not text:
        return False
    sample = text[:8000]
    # Savol raqami / savol belgilari
    has_q = bool(re.search(r"(^|\n)\s*\d{1,3}[).]\s+\S", sample))
    # "Savol 1", "savol2", "SAVOL 10" kabi
    has_savol = bool(re.search(r"(^|\n)\s*savol\s*\d{1,3}\b", sample, re.IGNORECASE))
    has_qmark = "?" in sample
    # Variantlar (A) / a) / A. / 1) kabi
    has_opts = bool(re.search(r"(^|\n)\s*(?:[A-Da-d][).]|[1-4][).])\s+\S", sample))
    # Variantlar faqat raqam bilan ("1 ", "2 -", "3.") bo'lishi mumkin
    has_opts2 = bool(re.search(r"(^|\n)\s*[1-9]\d{0,2}\s*(?:[).:-]|\s)\s+\S", sample))
    # Variantlar "~" bilan keladigan formatlar (siz yuborgan misol kabi)
    has_tilde_opts = bool(re.search(r"(^|\n)\s*~\s+\S", sample))

    # Variantlar raqamsiz bo'lishi mumkin: savoldan keyin 2-10 ta qisqa qatordan iborat blok
    # Masalan:
    # Savol 1
    # Ali
    # Vali
    # Tolib
    # Golib
    # Savol 2 ...
    lines = [ln.strip() for ln in sample.splitlines()]
    unnumbered_block = False
    for i, ln in enumerate(lines):
        if not ln:
            continue
        is_q_line = bool(re.match(r"^\d{1,3}[).]\s+\S", ln)) or bool(re.match(r"^savol\s*\d{1,3}\b", ln, re.IGNORECASE))
        if not is_q_line:
            continue
        # keyingi qatordan variantlarni yig'amiz (bo'sh qator yoki keyingi savolga qadar)
        opts = 0
        for j in range(i + 1, min(i + 20, len(lines))):
            nxt = lines[j]
            if not nxt:
                if opts >= 2:
                    break
                continue
            if bool(re.match(r"^\d{1,3}[).]\s+\S", nxt)) or bool(re.match(r"^savol\s*\d{1,3}\b", nxt, re.IGNORECASE)):
                break
            # juda uzun paragraf bo'lsa variant deb olmaymiz
            if len(nxt) > 120:
                continue
            opts += 1
        if opts >= 2:
            unnumbered_block = True
            break

    # Word testlarida ko'p uchraydi: "A)" "B)" "C)" ketma-ket
    return (
        (has_q and (has_opts or has_opts2 or has_tilde_opts)) or
        (has_savol and (has_opts or has_opts2 or has_tilde_opts or unnumbered_block)) or
        (has_qmark and (has_opts or has_opts2 or has_tilde_opts)) or
        unnumbered_block
    )


def sanitize_ai_input(text: str) -> str:
    """Juda uzun matnni AI uchun qisqartirish (token/vaqt limitlari uchun)."""
    text = (text or "").strip()
    if len(text) <= MAX_TEXT_CHARS_FOR_AI:
        return text

    # Heuristik: savolga o'xshash qatorlarni ko'proq saqlash
    lines = text.splitlines()
    keep: list[str] = []
    for line in lines:
        # savol/variantlarga o'xshash qatorlarni ko'proq saqlaymiz
        if (
            re.search(r"^\s*\d{1,3}[).]\s+\S", line)
            or re.search(r"^\s*[A-Da-d][).]\s+\S", line)
            or re.search(r"^\s*~\s+\S", line)  # tilde options
            or re.search(r"^\s*savol\s*\d{1,3}\b", line, re.IGNORECASE)
            # javob kalitlari/answer key'larni ham ushlab qolamiz (AI correct_answer ni aniqroq topishi uchun)
            or re.search(r"\b(javoblar|javob|to'g'ri\s+javob|answer|answers|key)\b", line, re.IGNORECASE)
            or re.search(r"\b\d{1,3}\s*[-:=]\s*[A-Da-d]\b", line)  # 1-A, 2:C, 3 = D
            or re.search(r"\b\d{1,3}\s*[-:=]\s*\d{1,3}\b", line)  # 1-2 (variant raqami)
            or "?" in line
        ):
            keep.append(line)
        if sum(len(x) + 1 for x in keep) >= MAX_TEXT_CHARS_FOR_AI:
            break

    compact = "\n".join(keep).strip()
    if len(compact) >= 200:
        return compact[:MAX_TEXT_CHARS_FOR_AI]

    # fallback: head
    return text[:MAX_TEXT_CHARS_FOR_AI]


def extract_answer_key_map(text: str) -> Dict[int, str]:
    """
    Fayl ichida javoblar kaliti bo'lsa, uni ajratib oladi.
    Misollar:
      - "Javoblar: 1-A, 2-C, 3-B"
      - "Answers: 1=B 2=D 3=A"
      - Ko'p qatorda: "1 - A" / "2: C"
    Qaytadi: {1: "A", 2: "C", ...}
    """
    text = text or ""
    if not text.strip():
        return {}

    tail = text[-ANSWER_KEY_TAIL_CHARS:] if ANSWER_KEY_TAIL_CHARS > 0 else text
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

    # 1-A, 2=C, 3: D, 4) B ...
    pairs = re.findall(r"\b(\d{1,3})\s*(?:[).])?\s*[-:=]\s*([A-Ja-j]|[1-9]\d{0,2})\b", segment)

    # Ba'zi formatlarda "1A 2C 3B" (dash yo'q) bo'ladi — buni faqat keyword topilganda ishlatamiz
    if found_keyword and len(pairs) < 2:
        pairs = re.findall(r"\b(\d{1,3})\s*([A-Ja-j])\b", segment)

    # Keyword bo'lmasa, false-positive bo'lmasligi uchun ko'proq match talab qilamiz
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
    """Answer key'ni questions tartibiga qo'llaydi. Qaytadi: nechta savolda correct qo'yildi."""
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
            # Harf: A/B/C/...
            if re.fullmatch(r"[A-Ja-j]", raw):
                mapped = ord(raw.lower()) - ord("a")
            else:
                # Raqam: 1/2/3/... (1-based)
                try:
                    mapped = int(raw) - 1
                except Exception:
                    mapped = None

            if mapped is None or not (0 <= mapped < len(opts)):
                continue

            if (q.get("correct_answer") is None) or ANSWER_KEY_OVERRIDE:
                q["correct_answer"] = mapped
                applied += 1
        except Exception:
            continue

    return applied


def validate_questions(questions: List[Dict], require_correct: bool = False) -> List[Dict]:
    """AI qaytargan savollarni tekshirish va tozalash.

    Eslatma: options ro'yxatini tozalash (bo'sh/duplikat/prefixlarni olib tashlash)
    davomida `correct_answer` indeksini "siljitib yubormaslik" uchun, correct_answer ni
    avval "raw option"ga bog'lab, so'ng tozalangan/dedup qilingan options ichida qayta-map qilamiz.
    """

    _MARK_RE = r"(?:✅|✔|✓|\*|\[\s*x\s*\]|\(\s*x\s*\))"
    _LABEL_RE = r"(?:\(?[A-Da-d]\)?|\d{1,3})\s*[).:\-]\s*"

    def _is_marked_correct(raw: str) -> bool:
        """
        To'g'ri javob belgilari:
        - boshida: "✅ Paris", "* Paris", "[x] Paris"
        - yoki prefiksdan keyin: "A) *Paris", "1) ✅ Paris"
        """
        s = (raw or "").strip()
        if not s:
            return False
        # tilde prefiksni olib tashlaymiz (format: "~ variant")
        s = s.lstrip("~").strip()
        if re.match(rf"^{_MARK_RE}\s*", s, flags=re.IGNORECASE):
            return True
        s2 = re.sub(rf"^{_LABEL_RE}", "", s)
        if re.match(rf"^{_MARK_RE}\s*", s2, flags=re.IGNORECASE):
            return True
        # ba'zi fayllarda marker oxiriga qo'yiladi: "Paris*" yoki "Paris *"
        if re.search(r"\*\s*$", s) or re.search(r"\*\s*$", s2):
            return True
        return False

    def _clean_option(raw: str) -> str:
        s = (raw or "").strip()
        # ba'zi formatlarda variantlar "~" bilan keladi
        s = s.lstrip("~").strip()
        # "A) ..." / "(A) ..." / "1) ..." / "1 - ..." kabi prefixlarni olib tashlash
        # 1) marker boshida bo'lsa olib tashlaymiz (misol: "* A) Paris")
        s = re.sub(rf"^{_MARK_RE}\s*", "", s, flags=re.IGNORECASE)
        # 2) label/prefixni olib tashlaymiz (misol: "A) Paris")
        s = re.sub(rf"^{_LABEL_RE}", "", s)
        # 3) marker labeldan keyin bo'lsa ham olib tashlaymiz (misol: "A) *Paris")
        s = re.sub(rf"^{_MARK_RE}\s*", "", s, flags=re.IGNORECASE)
        # ba'zi formatlarda oxirida "(to'g'ri)" kabi belgi bo'ladi
        s = re.sub(r"\(\s*(?:to['’`]?\s*g['’`]?\s*ri|togri|correct)\s*\)\s*$", "", s, flags=re.IGNORECASE)
        # oxirida yolg'iz "*" qolib ketsa (misol: "Paris*") — yashirib yuboramiz
        s = re.sub(r"\s*\*\s*$", "", s)
        s = s.strip().rstrip(" ;")
        # whitespace ni normallashtirish
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "").strip()).lower()

    def _coerce_correct_index(raw_correct, raw_len: int) -> Optional[int]:
        if raw_correct is None or isinstance(raw_correct, bool):
            return None
        # 0-based yoki 1-based raqam
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
        # Harf (A/B/C/...)
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

            # 1) correct answer ni raw options bo'yicha topamiz (marker bo'lsa ustunroq)
            marked = [i for i, opt in enumerate(raw_options) if _is_marked_correct(opt)]
            correct_raw_idx: Optional[int] = None
            if len(marked) == 1:
                correct_raw_idx = marked[0]
            else:
                correct_raw_idx = _coerce_correct_index(q.get('correct_answer'), raw_len=len(raw_options))

            # 2) options ni tozalab + dedup qilamiz va raw->dedup mapping saqlaymiz
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


def _parse_admin_user_ids(raw: str) -> set[int]:
    ids: set[int] = set()
    if not raw:
        return ids
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except Exception:
            continue
    return ids


ADMIN_USER_IDS = _parse_admin_user_ids(os.getenv("ADMIN_USER_IDS", ""))


def is_admin_user(user_id: int) -> bool:
    return bool(ADMIN_USER_IDS) and (user_id in ADMIN_USER_IDS)

def is_sudo_user(user_id: int) -> bool:
    # Adminlar doim sudo
    if is_admin_user(user_id):
        return True
    try:
        return storage.is_sudo_user(user_id)
    except Exception:
        return False


def private_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    # Oddiy foydalanuvchi: quiz tanlaydi + natijalarini ko'radi
    keyboard = [
        [KeyboardButton("📚 Mavjud quizlar"), KeyboardButton("🏅 Mening natijalarim")],
        [KeyboardButton("🔎 Qidirish"), KeyboardButton("ℹ️ Yordam")],
    ]
    # Creatorlar uchun quizlar menyusi ham kerak
    if is_sudo_user(user_id):
        keyboard.insert(1, [KeyboardButton("📚 Mening quizlarim")])
    # Admin tugmasi faqat adminlarda ko'rinsin
    if is_admin_user(user_id):
        keyboard.append([KeyboardButton("🛠 Admin")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def track_update(update: Update):
    """Admin statistika uchun foydalanuvchi/guruhni tracking qilish."""
    try:
        user = update.effective_user
        chat = update.effective_chat
        if user:
            storage.track_user(
                user_id=user.id,
                username=getattr(user, "username", None),
                first_name=getattr(user, "first_name", None),
                last_name=getattr(user, "last_name", None),
                last_chat_id=chat.id if chat else None,
                last_chat_type=getattr(chat, "type", None) if chat else None,
            )
        if chat and getattr(chat, "type", None) in ['group', 'supergroup']:
            storage.track_group(
                chat_id=chat.id,
                title=getattr(chat, "title", None),
                chat_type=getattr(chat, "type", None),
            )
    except Exception:
        pass


async def my_chat_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Botni guruhga qo'shish / admin qilish / chiqarib yuborish eventlari.
    Shu eventlar orqali bot o'zi turgan guruhlarni aniqroq "discover" qila oladi.
    """
    try:
        cmu = update.my_chat_member
        if not cmu or not cmu.chat:
            return
        chat = cmu.chat
        if chat.type not in ['group', 'supergroup']:
            return

        new_status = getattr(cmu.new_chat_member, "status", None)
        # left/kicked bo'lsa ham record qilib qo'yamiz
        is_admin = new_status in ['administrator', 'creator']
        storage.track_group(
            chat_id=chat.id,
            title=getattr(chat, "title", None),
            chat_type=getattr(chat, "type", None),
            bot_status=new_status,
            bot_is_admin=is_admin,
        )
    except Exception as e:
        logger.error(f"my_chat_member_handler error: {e}", exc_info=True)


def collect_known_group_ids(context: ContextTypes.DEFAULT_TYPE) -> set[int]:
    """
    Telegram API botga 'men qaysi guruhlardaman' ro'yxatini bermaydi.
    Shuning uchun storage + runtime sessions/polls dan guruh chat_id larni yig'amiz.
    """
    ids: set[int] = set()
    try:
        for g in storage.get_groups():
            try:
                ids.add(int(g.get('chat_id')))
            except Exception:
                pass
    except Exception:
        pass

    try:
        sessions = context.bot_data.get('sessions', {}) or {}
        for s in sessions.values():
            try:
                cid = int(s.get('chat_id'))
                ctype = s.get('chat_type')
                if ctype in ['group', 'supergroup'] or cid < 0:
                    ids.add(cid)
            except Exception:
                pass
    except Exception:
        pass

    try:
        polls = context.bot_data.get('polls', {}) or {}
        for p in polls.values():
            try:
                cid = int(p.get('chat_id'))
                if cid < 0:
                    ids.add(cid)
            except Exception:
                pass
    except Exception:
        pass

    return ids


def _markdown_to_plain(text: str) -> str:
    # Juda oddiy fallback: markdown belgilari xatoga sabab bo'lsa olib tashlaymiz
    try:
        # Markdown (legacy) muammoli belgilarini soddalashtiramiz
        return re.sub(r"[*_`\\[\\]()]", "", text)
    except Exception:
        return text


async def safe_reply_text(message, text: str, reply_markup=None, parse_mode=ParseMode.MARKDOWN):
    try:
        return await message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except BadRequest as e:
        if "Can't parse entities" in str(e):
            return await message.reply_text(_markdown_to_plain(text), reply_markup=reply_markup)
        raise


async def safe_edit_text(message, text: str, reply_markup=None, parse_mode=ParseMode.MARKDOWN):
    try:
        return await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except BadRequest as e:
        if "Can't parse entities" in str(e):
            return await message.edit_text(_markdown_to_plain(text), reply_markup=reply_markup)
        raise

# Quiz vaqt variantlari (soniyalarda)
TIME_OPTIONS = {
    '10s': 10,
    '30s': 30,
    '1min': 60,
    '3min': 180,
    '5min': 300
}


class FileAnalyzer:
    """Fayl tahlil qiluvchi klass"""
    
    @staticmethod
    def extract_text_from_txt(file_content: bytes) -> str:
        try:
            return file_content.decode('utf-8')
        except UnicodeDecodeError:
            return file_content.decode('utf-8', errors='ignore')
    
    @staticmethod
    def extract_text_from_pdf(file_content: bytes) -> str:
        try:
            pdf_file = BytesIO(file_content)
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            text = ""
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
            return text
        except Exception as e:
            logger.error(f"PDF xatolik: {e}")
            return ""
    
    @staticmethod
    def extract_text_from_docx(file_content: bytes) -> str:
        try:
            doc_file = BytesIO(file_content)
            doc = docx.Document(doc_file)
            text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
            return text
        except Exception as e:
            logger.error(f"DOCX xatolik: {e}")
            return ""
    
    @staticmethod
    def extract_text(file_content: bytes, file_extension: str) -> str:
        extension = file_extension.lower()
        
        if extension == '.txt':
            return FileAnalyzer.extract_text_from_txt(file_content)
        elif extension == '.pdf':
            return FileAnalyzer.extract_text_from_pdf(file_content)
        elif extension in ['.docx', '.doc']:
            return FileAnalyzer.extract_text_from_docx(file_content)
        else:
            try:
                return file_content.decode('utf-8')
            except:
                return file_content.decode('utf-8', errors='ignore')


class AIParser:
    """AI tahlil qiluvchi klass"""

    @staticmethod
    def _extract_json_dict(text: str) -> Optional[Dict]:
        """AI javobidan birinchi valid JSON dict'ni ajratib olish.

        Regex (greedy) ko'pincha 1-chi `{` dan oxirgi `}` gacha olib, JSON'ni buzib qo'yadi.
        Shu sabab `json.JSONDecoder().raw_decode()` orqali har bir `{` joyidan boshlab o'qib ko'ramiz.
        """
        if not text:
            return None

        raw = (text or "").strip()
        # tezkor: agar to'liq JSON bo'lsa
        try:
            if raw.startswith("{") and raw.endswith("}"):
                obj = json.loads(raw)
                if isinstance(obj, dict):
                    return obj
        except Exception:
            pass

        decoder = json.JSONDecoder()
        for idx, ch in enumerate(text):
            if ch != "{":
                continue
            try:
                obj, _ = decoder.raw_decode(text[idx:])
                if isinstance(obj, dict):
                    return obj
            except Exception:
                continue
        return None
    
    @staticmethod
    async def precheck_has_questions(text: str, model: Optional[str] = None) -> Dict:
        """
        1-bosqich: faylda test savollari mavjudligini tekshirish.
        Qaytadi:
          {"has_questions": true/false, "reason": "..."}
        """
        try:
            prompt = f"""Quyidagi matnda test/quiz savollari mavjudmi?
Qoidalar:
- Faqat tekshiring, savollarni ajratmang.
- Agar savol + variantlar strukturasi ko'rinmasa, has_questions=false qiling.
- Variantlar A)/1)/~ bilan yoki raqamsiz ketma-ket qisqa qatorlar ko'rinishida bo'lishi mumkin.
- Javobni faqat JSON qaytaring: {{"has_questions": true/false, "reason": "..."}}.

Matn:
{text}
"""
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {DEEPSEEK_API_KEY}'
            }
            data = {
                'model': (model or DEEPSEEK_MODEL),
                'messages': [
                    {'role': 'system', 'content': 'Siz faqat tekshiruvchi. Faqat JSON qaytaring.'},
                    {'role': 'user', 'content': prompt}
                ],
                'temperature': 0.0,
                'max_tokens': 300
            }
            sem = _get_ai_semaphore()
            await sem.acquire()
            try:
                async with httpx.AsyncClient(timeout=40.0) as client:
                    response = await client.post(DEEPSEEK_API_URL, headers=headers, json=data)
                    response.raise_for_status()
                    result = response.json()
                    ai_response = result.get('choices', [{}])[0].get('message', {}).get('content', '')
                    parsed = AIParser._extract_json_dict(ai_response)
                    if not parsed:
                        return {"has_questions": False, "reason": "AI javobi JSON emas"}
                    return {
                        "has_questions": bool(parsed.get("has_questions", False)),
                        "reason": str(parsed.get("reason", "")).strip()[:300]
                    }
            finally:
                try:
                    sem.release()
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"AI precheck error: {e}")
            return {"has_questions": False, "reason": "AI precheck xatolik"}

    @staticmethod
    async def analyze_with_ai(
        text: str,
        progress_callback=None,
        strict_correct: bool = True,
        model: Optional[str] = None
    ) -> Optional[Dict]:
        try:
            if progress_callback:
                await progress_callback(30, "🤖 AI ga so'rov yuborilmoqda...")

            # Default: tezroq va kamroq injiq bo'lishi uchun 1 ta so'rovda "yumshoq" rejim
            # (savollarni topib berish muhim; correct_answer bo'lmasa ham bo'ladi).
            target_n = max(1, min(int(TARGET_QUESTIONS_PER_QUIZ or 50), int(MAX_QUESTIONS_PER_QUIZ or 100)))

            prompt = f"""Quyidagi matndan test savollarini va javob variantlarini ajratib oling.
Muhim qoidalar:
1) Agar umuman hech bo'lmaganda 1 ta (2+ variantli) savol topilmasa, {"{"}"questions": []{"}"} qaytaring.
2) Aks holda faqat aniq ko'rinadigan savollarni qaytaring, noaniq savollarni tashlab keting.
3) Har bir savolda kamida 2 ta variant bo'lsin.
4) correct_answer topilsa 0..(options-1) bo'lsin; topilmasa null qiling (savolni baribir qaytaring).
5) Eng ko'pi bilan {target_n} ta savol qaytaring (ortig'ini tashlab keting).
6) Variantlar ba'zan raqamsiz bo'ladi: savoldan keyingi ketma-ket qisqa qatorlarni variant deb oling (keyingi savol boshlanguncha yoki bo'sh satrgacha).
7) Variantlar ba'zan "~" bilan boshlanadi (misol: "~ variant"). Bunda "~" ni olib tashlab, variant matnini options ga yozing.
8) Quiz uchun qisqa nom (title) ham bering (2-5 so'z, 32 belgigacha).

Matn:
{text}

Javobni JSON formatida qaytaring:
{{
  "title": "Qisqa nom",
  "questions": [
    {{
      "question": "Savol matni",
      "options": ["Variant 1", "Variant 2", "Variant 3"],
      "correct_answer": 0,
      "explanation": "Tushuntirish"
    }}
  ]
}}

Faqat JSON qaytaring. JSON dan boshqa matn yozmang."""

            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {DEEPSEEK_API_KEY}'
            }
            
            data = {
                'model': (model or DEEPSEEK_MODEL),
                'messages': [
                    {'role': 'system', 'content': 'Siz test tahlilchisiz. Faqat JSON qaytaring.'},
                    {'role': 'user', 'content': prompt}
                ],
                'temperature': 0.0,
                'max_tokens': 8000
            }
            
            if progress_callback:
                await progress_callback(60, "⏳ AI tahlil qilmoqda...")
            
            sem = _get_ai_semaphore()
            await sem.acquire()
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    response = await client.post(DEEPSEEK_API_URL, headers=headers, json=data)
                    response.raise_for_status()

                    if progress_callback:
                        await progress_callback(90, "📊 Savollar qayta ishlanmoqda...")

                    result = response.json()
                    ai_response = result.get('choices', [{}])[0].get('message', {}).get('content', '')

                    parsed_data = AIParser._extract_json_dict(ai_response)
                    if parsed_data:
                        title = (parsed_data.get('title') or '').strip()
                        questions = parsed_data.get('questions', [])

                        cleaned_questions = []
                        for q in questions:
                            if not isinstance(q, dict):
                                continue
                            raw_opts = q.get('options', [])
                            if not isinstance(raw_opts, list):
                                raw_opts = []
                            if 'question' in q and len(raw_opts) >= 2:
                                # Muhim: options ni bu yerda filtrlamaymiz (bo'sh/duplikat/prefixlarni olib tashlash
                                # correct_answer indeksini siljitib yuborishi mumkin). Buni validate_questions() qiladi.
                                cleaned_questions.append({
                                    'question': str(q.get('question', '')).strip(),
                                    'options': [str(opt) for opt in raw_opts],
                                    'correct_answer': q.get('correct_answer'),
                                    'explanation': str(q.get('explanation', '')).strip()
                                })

                        if progress_callback:
                            await progress_callback(100, f"✅ {len(cleaned_questions)} ta savol topildi!")

                        return {"title": title[:64], "questions": cleaned_questions}

                return None
            finally:
                try:
                    sem.release()
                except Exception:
                    pass
                
        except Exception as e:
            logger.error(f"AI xatolik: {e}")
            return None

    @staticmethod
    async def pick_correct_answers(questions: List[Dict], model: Optional[str] = None) -> Optional[List[int]]:
        """
        Berilgan savollar uchun correct_answer ni AI orqali topadi (0-based index).
        Qaytadi: answers list (len == len(questions)) yoki None.
        """
        try:
            if not questions:
                return []

            # Promptni ixcham qilish uchun qisqartiramiz
            blocks: List[str] = []
            for qi, q in enumerate(questions, 1):
                q_text = str(q.get("question") or "").strip().replace("\n", " ")
                q_text = re.sub(r"\s+", " ", q_text)[:300]
                opts = q.get("options") or []
                if not isinstance(opts, list):
                    opts = []
                opts = [str(o).strip().replace("\n", " ")[:120] for o in opts[:10]]
                if len(opts) < 2:
                    # savol yaroqsiz bo'lsa, shunchaki 0 qaytaramiz (keyin validate qiladi)
                    opts = opts + ["-"] * (2 - len(opts))

                lines = [f"{qi}) {q_text}"]
                for oi, opt in enumerate(opts):
                    lines.append(f"{oi}) {opt}")
                blocks.append("\n".join(lines))

            prompt = (
                "Quyidagi test savollari uchun har biriga 1 tadan to'g'ri javob variantini tanlang.\n"
                "Qoidalar:\n"
                "- Har bir savol uchun 1 ta javob tanlang.\n"
                "- Javob 0-based index bo'lsin (0..options-1).\n"
                "- Faqat JSON qaytaring: {\"answers\": [0,1,2]}.\n"
                "- answers uzunligi savollar soniga teng bo'lsin.\n\n"
                "Savollar:\n"
                + "\n\n".join(blocks)
            )

            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {DEEPSEEK_API_KEY}'
            }
            data = {
                'model': (model or DEEPSEEK_MODEL),
                'messages': [
                    {'role': 'system', 'content': 'Siz test yechuvchisiz. Faqat JSON qaytaring.'},
                    {'role': 'user', 'content': prompt}
                ],
                'temperature': 0.0,
                'max_tokens': 800
            }

            sem = _get_ai_semaphore()
            await sem.acquire()
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    response = await client.post(DEEPSEEK_API_URL, headers=headers, json=data)
                    response.raise_for_status()
                    result = response.json()
                    ai_response = result.get('choices', [{}])[0].get('message', {}).get('content', '')
            finally:
                try:
                    sem.release()
                except Exception:
                    pass

            parsed = AIParser._extract_json_dict(ai_response)
            if not parsed:
                return None

            answers_raw = parsed.get("answers")
            if not isinstance(answers_raw, list) or len(answers_raw) != len(questions):
                return None

            out: List[int] = []
            for i, a in enumerate(answers_raw):
                # int yoki harf bo'lishi mumkin
                idx: Optional[int] = None
                try:
                    if isinstance(a, str) and re.fullmatch(r"[A-Ja-j]", a.strip()):
                        idx = ord(a.strip().lower()) - ord("a")
                    else:
                        idx = int(str(a).strip())
                except Exception:
                    idx = None

                opts = questions[i].get("options") or []
                if not isinstance(opts, list):
                    opts = []
                if idx is None or not (0 <= idx < len(opts)):
                    return None
                out.append(idx)

            return out
        except Exception as e:
            logger.error(f"AI pick_correct_answers error: {e}", exc_info=True)
            return None


# ==================== HANDLERS ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    track_update(update)
    chat_type = update.effective_chat.type
    
    if chat_type in ['group', 'supergroup']:
        await update.message.reply_text(
            "❌ Bu buyruq guruhda ishlamaydi.\n\n"
            "📝 Guruhda /startquiz buyrug'ini ishlating."
        )
        return
    
    if is_sudo_user(update.effective_user.id):
        welcome_message = """
🎯 **Quiz Bot**ga xush kelibsiz!

📝 **Qanday ishlaydi (creator):**
1️⃣ Test faylini yuboring (TXT, PDF, DOCX)
2️⃣ AI tahlil qilib quiz tayyorlaydi
3️⃣ Guruhda /startquiz orqali o'ynaladi

📚 **Buyruqlar:**
/myquizzes - Mening quizlarim
/myresults - Mening natijalarim
/quizzes - Mavjud quizlar
/help - Yordam
"""
    else:
        welcome_message = """
🎯 **Quiz Bot**ga xush kelibsiz!

✨ **Qisqa yo'riqnoma:**
- 📚 Tayyor quizlardan birini tanlab ishlaysiz
- 🏅 Natijalaringizni saqlab boramiz

📚 **Buyruqlar:**
/quizzes - Mavjud quizlar
/myresults - Mening natijalarim
/help - Yordam
"""
    await update.message.reply_text(
        welcome_message,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=private_main_keyboard(update.effective_user.id)
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yordam"""
    track_update(update)
    help_text = """
📖 **Yordam**

**Qo'llab-quvvatlanadigan formatlar:**
• TXT - Matn fayllari
• PDF - PDF hujjatlar  
• DOCX - Word hujjatlar

**Buyruqlar:**
/start - Botni ishga tushirish
/myresults - Mening natijalarim
/startquiz - Guruhda quiz boshlash
/finishquiz - Shaxsiy chatda quizni yakunlash
/help - Yordam

**Guruhda:**
1. Shaxsiy chatda quiz yarating
2. Botni guruhga qo'shing va admin qiling
3. /startquiz buyrug'ini ishlating
"""
    if is_sudo_user(update.effective_user.id):
        help_text += "\n**Creator:** fayl yuborib quiz yaratishingiz mumkin (private chatda).\n/myquizzes - yaratgan quizlaringiz\n"
    if is_admin_user(update.effective_user.id):
        help_text += "\n**Admin:**\n/admin - Admin panel\n/sudo - Sudo userlarni boshqarish\n"
    await update.message.reply_text(
        help_text, 
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=private_main_keyboard(update.effective_user.id)
    )


async def myresults_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchining oxirgi natijalari"""
    track_update(update)
    if update.effective_chat.type in ['group', 'supergroup']:
        await update.message.reply_text("ℹ️ Natijalarni ko'rish uchun botga shaxsiy chatda yozing.")
        return

    user_id = update.effective_user.id
    results = storage.get_user_results(user_id, limit=15)
    if not results:
        await update.message.reply_text("📭 Hozircha natijalaringiz yo'q.")
        return

    text = "🏅 **Mening natijalarim (oxirgilar):**\n\n"
    for r in results:
        quiz_id = r.get('quiz_id')
        quiz = storage.get_quiz(quiz_id) if quiz_id else None
        title = (quiz or {}).get('title') or quiz_id or "Quiz"
        correct = r.get('correct_count', 0)
        total = r.get('total_count', 0)
        pct = r.get('percentage', 0)
        when = str(r.get('completed_at', ''))[:19].replace("T", " ")
        text += f"- 📝 {title[:28]} — **{correct}/{total}** ({pct:.0f}%)\n  ⏱ {when}\n"

    await safe_reply_text(
        update.message, 
        text, 
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=private_main_keyboard(update.effective_user.id)
    )


async def myquizzes_command(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    """Quizlar ro'yxati"""
    track_update(update)
    user_id = update.effective_user.id
    user_quizzes = storage.get_user_quizzes(user_id)
    
    if not user_quizzes:
        await update.message.reply_text(
            "📭 Sizda quizlar yo'q.\n\n"
            "📝 Test faylini yuborib quiz yarating!"
        )
        return
    
    # Pagination: 10 ta har bir sahifada
    QUIZZES_PER_PAGE = 10
    total_quizzes = len(user_quizzes)
    total_pages = (total_quizzes + QUIZZES_PER_PAGE - 1) // QUIZZES_PER_PAGE
    page = max(0, min(page, total_pages - 1))
    
    start_idx = page * QUIZZES_PER_PAGE
    end_idx = min(start_idx + QUIZZES_PER_PAGE, total_quizzes)
    page_quizzes = user_quizzes[start_idx:end_idx]
    
    text = f"📚 **Mening quizlarim:** (Sahifa {page + 1}/{total_pages})\n\n"
    keyboard = []
    
    for i, quiz in enumerate(page_quizzes, 1):
        global_idx = start_idx + i
        count = len(quiz.get('questions', []))
        title = quiz.get('title', f"Quiz {global_idx}")[:20]
        text += f"{global_idx}. 📝 {title} ({count} savol)\n"
        
        keyboard.append([InlineKeyboardButton(
            f"📝 {title} ({count} savol)",
            callback_data=f"quiz_menu_{quiz['quiz_id']}"
        )])
    
    # Pagination tugmalari
    pagination_buttons = []
    if total_pages > 1:
        if page > 0:
            pagination_buttons.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"page_myquizzes_{page - 1}"))
        if page < total_pages - 1:
            pagination_buttons.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"page_myquizzes_{page + 1}"))
        if pagination_buttons:
            keyboard.append(pagination_buttons)
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_reply_text(update.message, text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    # ReplyKeyboard tugmalarini qayta yuborish (agar yo'qolgan bo'lsa)
    try:
        await update.message.reply_text(
            "💡 Quyidagi tugmalardan foydalaning:",
            reply_markup=private_main_keyboard(update.effective_user.id)
        )
    except Exception:
        pass

async def sudo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: sudo userlarni boshqarish
    /sudo list
    /sudo add <user_id>
    /sudo remove <user_id>
    """
    track_update(update)
    if update.effective_chat.type in ['group', 'supergroup']:
        await update.message.reply_text("ℹ️ /sudo faqat shaxsiy chatda.")
        return

    admin_id = update.effective_user.id
    if not is_admin_user(admin_id):
        # Oddiy foydalanuvchiga admin/sudo mavjudligini bildirmaymiz
        return

    if not context.args:
        await update.message.reply_text(
            "Foydalanish:\n"
            "- `/sudo list`\n"
            "- `/sudo add 123456789`\n"
            "- `/sudo remove 123456789`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    action = context.args[0].lower().strip()
    if action == "list":
        sudo_users = storage.get_sudo_users()
        if not sudo_users:
            await update.message.reply_text("📭 Sudo userlar yo'q.")
            return
        text = "🛡 **Sudo userlar:**\n\n"
        for u in sudo_users[:50]:
            uname = f"@{u.get('username')}" if u.get('username') else "-"
            text += f"- `{u.get('user_id')}` {uname} {u.get('first_name') or ''}\n"
        await safe_reply_text(update.message, text, parse_mode=ParseMode.MARKDOWN)
        return

    if action in ["add", "remove", "del", "delete"]:
        if len(context.args) < 2:
            await update.message.reply_text("❌ user_id kiriting. Masalan: `/sudo add 123`", parse_mode=ParseMode.MARKDOWN)
            return
        try:
            target_id = int(context.args[1])
        except Exception:
            await update.message.reply_text("❌ user_id raqam bo'lishi kerak.")
            return

        if action == "add":
            # agar user meta bo'lsa, undan username/name olib qo'yamiz
            username = None
            first_name = None
            try:
                for u in storage.get_users():
                    if int(u.get('user_id')) == target_id:
                        username = u.get('username')
                        first_name = u.get('first_name')
                        break
            except Exception:
                pass
            storage.add_sudo_user(target_id, username=username, first_name=first_name)
            await safe_reply_text(update.message, f"✅ Sudo berildi: `{target_id}`", parse_mode=ParseMode.MARKDOWN)
            return

        ok = storage.remove_sudo_user(target_id)
        await safe_reply_text(
            update.message,
            ("✅ Sudo olib tashlandi: " if ok else "ℹ️ Sudo topilmadi: ") + f"`{target_id}`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    await update.message.reply_text("❌ Noma'lum buyruq. `/sudo list` deb ko'ring.", parse_mode=ParseMode.MARKDOWN)


async def quizzes_command(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    """Barcha quizlar (private chatda katalog sifatida)"""
    track_update(update)
    chat_type = update.effective_chat.type
    if chat_type in ['group', 'supergroup']:
        await update.message.reply_text(
            "ℹ️ Barcha quizlarni ko'rish uchun botga shaxsiy chatda yozing.\n\n"
            "Guruhda esa /startquiz ishlating."
        )
        return

    all_quizzes = storage.get_all_quizzes()
    if not all_quizzes:
        await update.message.reply_text("📭 Hozircha quizlar yo'q.")
        return

    # Eng oxirgi yaratilganlardan tartiblash
    all_quizzes.sort(key=lambda q: q.get('created_at', ''), reverse=True)
    
    # Pagination: 10 ta har bir sahifada
    QUIZZES_PER_PAGE = 10
    total_quizzes = len(all_quizzes)
    total_pages = (total_quizzes + QUIZZES_PER_PAGE - 1) // QUIZZES_PER_PAGE
    page = max(0, min(page, total_pages - 1))
    
    start_idx = page * QUIZZES_PER_PAGE
    end_idx = min(start_idx + QUIZZES_PER_PAGE, total_quizzes)
    page_quizzes = all_quizzes[start_idx:end_idx]
    
    text = f"📚 **Mavjud quizlar:** (Sahifa {page + 1}/{total_pages})\n\n"
    keyboard = []
    for i, quiz in enumerate(page_quizzes, 1):
        global_idx = start_idx + i
        count = len(quiz.get('questions', []))
        title = (quiz.get('title') or f"Quiz {global_idx}")[:30]
        text += f"{global_idx}. 📝 {title} ({count} savol)\n"
        keyboard.append([InlineKeyboardButton(
            f"📝 {title} ({count})",
            callback_data=f"quiz_menu_{quiz['quiz_id']}"
        )])
    
    # Pagination tugmalari
    pagination_buttons = []
    if total_pages > 1:
        if page > 0:
            pagination_buttons.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"page_quizzes_{page - 1}"))
        if page < total_pages - 1:
            pagination_buttons.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"page_quizzes_{page + 1}"))
        if pagination_buttons:
            keyboard.append(pagination_buttons)
    
    await safe_reply_text(
        update.message,
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )
    # ReplyKeyboard tugmalarini qayta yuborish (agar yo'qolgan bo'lsa)
    try:
        await update.message.reply_text(
            "💡 Quyidagi tugmalardan foydalaning:",
            reply_markup=private_main_keyboard(update.effective_user.id)
        )
    except Exception:
        pass


async def searchquiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quizlarni nomi bo'yicha qidirish (private chat)"""
    track_update(update)
    chat_type = update.effective_chat.type
    if chat_type in ['group', 'supergroup']:
        await update.message.reply_text("ℹ️ Qidirish uchun botga shaxsiy chatda yozing.")
        return

    query = " ".join(context.args).strip() if context.args else ""
    if len(query) < 2:
        await update.message.reply_text("🔎 Foydalanish: `/searchquiz matematika`", parse_mode=ParseMode.MARKDOWN)
        return

    q_lower = query.lower()
    all_quizzes = storage.get_all_quizzes()
    matches = []
    for quiz in all_quizzes:
        title = (quiz.get('title') or '').lower()
        if q_lower in title:
            matches.append(quiz)

    if not matches:
        await update.message.reply_text("❌ Hech narsa topilmadi.")
        return

    matches.sort(key=lambda q: q.get('created_at', ''), reverse=True)
    text = f"🔎 **Qidiruv:** `{query}`\n\n"
    keyboard = []
    for i, quiz in enumerate(matches[:10], 1):
        count = len(quiz.get('questions', []))
        title = (quiz.get('title') or f"Quiz {i}")[:30]
        text += f"{i}. 📝 {title} ({count} savol)\n"
        keyboard.append([InlineKeyboardButton(
            f"📝 {title} ({count})",
            callback_data=f"quiz_menu_{quiz['quiz_id']}"
        )])
    await safe_reply_text(update.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)


async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quiz ID orqali menyu (private va groupda ham)"""
    track_update(update)
    quiz_id = (context.args[0].strip() if context.args else "").strip()
    if not quiz_id:
        await update.message.reply_text("Foydalanish: `/quiz b672034fe4b4`", parse_mode=ParseMode.MARKDOWN)
        return

    quiz = storage.get_quiz(quiz_id)
    if not quiz:
        await update.message.reply_text("❌ Quiz topilmadi.")
        return

    count = len(quiz.get('questions', []))
    title = quiz.get('title', 'Quiz')

    keyboard = []
    # Guruhda allowlist yoqilgan bo'lsa: ruxsat berilmagan quizni guruhda boshlashni bloklaymiz
    try:
        chat_type = update.effective_chat.type
        chat_id = update.effective_chat.id
    except Exception:
        chat_type = None
        chat_id = None

    if chat_type in ['group', 'supergroup'] and chat_id is not None and (not storage.group_allows_quiz(chat_id, quiz_id)):
        keyboard.append([InlineKeyboardButton("📊 Ma'lumot", callback_data=f"quiz_info_{quiz_id}")])
    else:
        keyboard.extend([
            [InlineKeyboardButton("🚀 Boshlash", callback_data=f"select_time_{quiz_id}")],
            [InlineKeyboardButton("📊 Ma'lumot", callback_data=f"quiz_info_{quiz_id}")]
        ])
    await safe_reply_text(
        update.message,
        f"📝 **{title}**\n\n📊 Savollar: {count}\n🆔 ID: `{quiz_id}`",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def deletequiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quizni ID orqali o'chirish (tanlamasdan)"""
    track_update(update)
    chat_type = update.effective_chat.type
    if chat_type in ['group', 'supergroup']:
        await update.message.reply_text("ℹ️ /deletequiz faqat shaxsiy chatda ishlaydi.")
        return

    user_id = update.effective_user.id
    quiz_id = (context.args[0].strip() if context.args else "").strip()
    if not quiz_id:
        await update.message.reply_text("Foydalanish: `/deletequiz b672034fe4b4`", parse_mode=ParseMode.MARKDOWN)
        return

    quiz = storage.get_quiz(quiz_id)
    if not quiz:
        await update.message.reply_text("❌ Quiz topilmadi.")
        return

    # Faqat owner yoki global admin o'chira oladi
    if (quiz.get('created_by') != user_id) and (not is_admin_user(user_id)):
        await update.message.reply_text("❌ Siz bu quizni o'chira olmaysiz (faqat egasi yoki admin).")
        return

    title = quiz.get('title') or quiz_id
    ok = storage.delete_quiz(quiz_id)
    if ok:
        await safe_reply_text(update.message, f"✅ O'chirildi: **{title}** (`{quiz_id}`)", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("❌ O'chirishda xatolik.")


async def finishquiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shaxsiy chatda boshlangan quizni yakunlash"""
    track_update(update)
    chat = update.effective_chat
    if chat.type in ['group', 'supergroup']:
        await update.message.reply_text("ℹ️ Bu buyruq faqat shaxsiy chatda ishlaydi.\n\nGuruhda /stopquiz ishlating.")
        return
    
    # Restartdan keyin due bo'lgan sessionlarni ham oldinga surib yuboramiz
    await advance_due_sessions(context)
    
    chat_id = chat.id
    user_id = update.effective_user.id
    
    sessions = context.bot_data.setdefault('sessions', {})
    
    stopped = 0
    finished_quizzes = []
    
    # Shaxsiy chatdagi barcha aktiv sessionlarni topish
    user_prefix = f"quiz_{chat_id}_{user_id}_"
    for k, s in list(sessions.items()):
        if k.startswith(user_prefix) and s.get('is_active', False):
            quiz_id = s.get('quiz_id')
            if quiz_id:
                finished_quizzes.append(quiz_id)
            s['is_active'] = False
            stopped += 1
    
    if stopped == 0:
        await update.message.reply_text("ℹ️ Hozir sizda aktiv quiz yo'q.")
        return
    
    # Agar yakunlangan quizlar bo'lsa, natijalarni ko'rsatish
    if finished_quizzes:
        # Eng so'nggi quizni ko'rsatish
        quiz_id = finished_quizzes[-1]
        await show_quiz_results(update.message, context, quiz_id, chat_id, user_id)
    else:
        await update.message.reply_text(
            f"✅ Quiz yakunlandi: {stopped} ta session yopildi."
        )


async def stopquiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guruhda aktiv quizni to'xtatish (adminlar uchun)"""
    track_update(update)
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("ℹ️ Bu buyruq faqat guruhda ishlaydi.\n\nShaxsiy chatda /finishquiz ishlating.")
        return

    # Restartdan keyin due bo'lgan sessionlarni ham oldinga surib yuboramiz
    await advance_due_sessions(context)

    chat_id = chat.id
    user_id = update.effective_user.id

    # Admin tekshiruvi
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status not in ['administrator', 'creator']:
            await update.message.reply_text("❌ Faqat adminlar /stopquiz qila oladi.")
            return
    except Exception:
        await update.message.reply_text("❌ Admin tekshiruvida xatolik.")
        return

    sessions = context.bot_data.setdefault('sessions', {})
    group_locks = context.bot_data.setdefault('group_locks', {})

    stopped = 0

    # 1) Lock orqali topish (yangi oqim)
    session_key = group_locks.get(chat_id)
    if session_key and session_key in sessions and sessions[session_key].get('is_active', False):
        sessions[session_key]['is_active'] = False
        stopped += 1
    group_locks.pop(chat_id, None)

    # 2) Backward compatibility: lock bo'lmasa ham guruhdagi barcha aktiv sessionlarni o'chirish
    group_prefix = f"quiz_{chat_id}_"
    for k, s in list(sessions.items()):
        if k.startswith(group_prefix) and s.get('is_active', False):
            s['is_active'] = False
            stopped += 1

    if stopped == 0:
        await update.message.reply_text("ℹ️ Hozir guruhda aktiv quiz yo'q.")
        return

    await update.message.reply_text(
        f"🛑 Aktiv quiz(lar) to'xtatildi: {stopped} ta session yopildi.\n"
        "Endi /startquiz ishlaydi."
    )


async def _is_group_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Guruh adminligini tekshirish (global adminlar ham o'tadi)."""
    try:
        if is_admin_user(update.effective_user.id):
            return True
    except Exception:
        pass

    chat = update.effective_chat
    if not chat or chat.type not in ['group', 'supergroup']:
        return False
    try:
        member = await context.bot.get_chat_member(chat.id, update.effective_user.id)
        return member.status in ['administrator', 'creator']
    except Exception:
        return False


async def allowquiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guruhda boshlash mumkin bo'lgan quizni 'tanlangan' ro'yxatga qo'shish."""
    track_update(update)
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("ℹ️ Bu buyruq faqat guruhda ishlaydi.")
        return

    if not await _is_group_admin(update, context):
        await update.message.reply_text("❌ Faqat guruh adminlari /allowquiz qila oladi.")
        return

    arg = " ".join(context.args).strip() if context.args else ""
    if not arg:
        await update.message.reply_text(
            "Foydalanish: `/allowquiz <quiz_id>`\n"
            "Filtrni o'chirish: `/allowquiz off`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if arg.lower() in ['off', 'disable', 'all', 'reset', 'clear']:
        storage.set_group_allowed_quiz_ids(chat.id, [])
        await update.message.reply_text("✅ Filtr o'chirildi. Endi guruhda hamma quizlar ko'rinadi.")
        return

    quiz_id = arg.split()[0]
    quiz = storage.get_quiz(quiz_id)
    if not quiz:
        await update.message.reply_text("❌ Quiz topilmadi. ID ni tekshiring.")
        return

    added = storage.add_group_allowed_quiz(chat.id, quiz_id)
    title = quiz.get('title') or quiz_id
    if added:
        await safe_reply_text(update.message, f"✅ Guruhga ruxsat berildi: **{title}** (`{quiz_id}`)", parse_mode=ParseMode.MARKDOWN)
    else:
        await safe_reply_text(update.message, f"ℹ️ Allaqachon ruxsat berilgan: **{title}** (`{quiz_id}`)", parse_mode=ParseMode.MARKDOWN)


async def disallowquiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guruhda boshlash mumkin bo'lgan quizni 'tanlangan' ro'yxatdan olib tashlash."""
    track_update(update)
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("ℹ️ Bu buyruq faqat guruhda ishlaydi.")
        return

    if not await _is_group_admin(update, context):
        await update.message.reply_text("❌ Faqat guruh adminlari /disallowquiz qila oladi.")
        return

    arg = " ".join(context.args).strip() if context.args else ""
    if not arg:
        await update.message.reply_text("Foydalanish: `/disallowquiz <quiz_id>`", parse_mode=ParseMode.MARKDOWN)
        return

    if arg.lower() in ['all', 'reset', 'clear']:
        storage.set_group_allowed_quiz_ids(chat.id, [])
        await update.message.reply_text("✅ Tanlangan quizlar tozalandi (filtr o'chdi).")
        return

    quiz_id = arg.split()[0]
    ok = storage.remove_group_allowed_quiz(chat.id, quiz_id)
    await update.message.reply_text("✅ Olib tashlandi." if ok else "ℹ️ Bu quiz ro'yxatda yo'q.")


async def allowedquizzes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guruhda ruxsat berilgan quizlar ro'yxati."""
    track_update(update)
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("ℹ️ Bu buyruq faqat guruhda ishlaydi.")
        return

    allowed_ids = storage.get_group_allowed_quiz_ids(chat.id)
    if not allowed_ids:
        await update.message.reply_text(
            "ℹ️ Hozir filtr yoqilmagan — guruhda hamma quizlar boshlanadi.\n\n"
            "✅ Tanlash uchun: `/allowquiz <quiz_id>`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    items = []
    for qid in allowed_ids[:30]:
        quiz = storage.get_quiz(qid)
        if not quiz:
            continue
        title = quiz.get('title') or qid
        count = len(quiz.get('questions', []))
        items.append(f"- **{title}** (`{qid}`) — {count} savol")

    text = "📋 **Guruhda ruxsat berilgan quizlar:**\n\n" + ("\n".join(items) if items else "_(ro'yxat bo'sh)_")
    text += "\n\n♻️ Filtrni o'chirish: `/allowquiz off`"
    await safe_reply_text(update.message, text, parse_mode=ParseMode.MARKDOWN)


async def startquiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guruhda quiz boshlash"""
    track_update(update)
    # Restartdan keyin osilib qolgan sessionlar bo'lsa, avval oldinga surib ko'ramiz
    await advance_due_sessions(context)

    chat_type = update.effective_chat.type
    chat_id = update.effective_chat.id
    
    if chat_type not in ['group', 'supergroup']:
        await update.message.reply_text(
            "❌ Bu buyruq faqat guruhlarda ishlaydi.\n\n"
            "💡 Shaxsiy chatda /myquizzes buyrug'ini ishlating."
        )
        return
    
    # Bot admin tekshiruvi
    try:
        bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
        is_admin = bot_member.status in ['administrator', 'creator']
        
        if not is_admin:
            await update.message.reply_text(
                "❌ Bot guruhda admin emas!\n\n"
                "1. Guruh sozlamalari → Administratorlar\n"
                "2. Botni qo'shing va admin qiling"
            )
            return
    except Exception as e:
        await update.message.reply_text("❌ Xatolik yuz berdi.")
        return
    
    all_quizzes = storage.get_all_quizzes()

    # Guruh uchun "tanlangan quizlar" filtri (allowlist).
    # Agar ro'yxat bo'sh bo'lsa — hamma quizlar ko'rinadi.
    allowed_ids = storage.get_group_allowed_quiz_ids(chat_id)
    if allowed_ids:
        allowed_set = set(allowed_ids)
        all_quizzes = [q for q in all_quizzes if str(q.get('quiz_id')) in allowed_set]
    
    if not all_quizzes:
        await update.message.reply_text(
            ("📭 Bu guruhda hozircha tanlangan quizlar yo'q.\n\n"
             "✅ Admin: `/allowquiz <quiz_id>` bilan ruxsat bering.\n"
             "♻️ Filtrni o'chirish: `/allowquiz off` (hamma quizlar ochiladi).")
            if allowed_ids else
            ("📭 Quizlar yo'q.\n\n"
             "💡 Shaxsiy chatda fayl yuborib quiz yarating!")
        )
        return
    
    # Pagination: 10 ta har bir sahifada
    QUIZZES_PER_PAGE = 10
    total_quizzes = len(all_quizzes)
    total_pages = (total_quizzes + QUIZZES_PER_PAGE - 1) // QUIZZES_PER_PAGE
    page = 0  # Start from page 0
    
    start_idx = page * QUIZZES_PER_PAGE
    end_idx = min(start_idx + QUIZZES_PER_PAGE, total_quizzes)
    page_quizzes = all_quizzes[start_idx:end_idx]
    
    text = ("📚 **Guruhda tanlangan quizlar:**\n\n" if allowed_ids else "📚 **Mavjud quizlar:**\n\n")
    if total_pages > 1:
        text += f"(Sahifa {page + 1}/{total_pages})\n\n"
    keyboard = []
    
    for i, quiz in enumerate(page_quizzes, 1):
        global_idx = start_idx + i
        count = len(quiz.get('questions', []))
        title = quiz.get('title', f"Quiz {global_idx}")[:20]
        text += f"{global_idx}. 📝 {title} ({count} savol)\n"
        
        keyboard.append([InlineKeyboardButton(
            f"🚀 {title} ({count} savol)",
            callback_data=f"start_group_{quiz['quiz_id']}"
        )])
    
    # Pagination tugmalari
    pagination_buttons = []
    if total_pages > 1:
        if page < total_pages - 1:
            pagination_buttons.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"page_group_quizzes_{chat_id}_{page + 1}"))
        if pagination_buttons:
            keyboard.append(pagination_buttons)
    
    text += "\n🎯 Quizni tanlang!"
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Matn xabarlarini qabul qilish (quiz tahrirlash uchun)"""
    track_update(update)
    message = update.message
    user_id = message.from_user.id
    text = message.text

    # ===== ReplyKeyboard shortcuts (private chat) =====
    if update.effective_chat.type == 'private' and text:
        if text.strip() == "📚 Mavjud quizlar":
            await quizzes_command(update, context)
            return
        if text.strip() == "🏅 Mening natijalarim":
            await myresults_command(update, context)
            return
        if text.strip() == "📚 Mening quizlarim":
            await myquizzes_command(update, context)
            return
        if text.strip() == "ℹ️ Yordam":
            await help_command(update, context)
            return
        if text.strip() == "🛠 Admin":
            # Tugma oddiy userga ko'rinmaydi; yozib yuborsa ham jim turamiz
            if is_admin_user(user_id):
                await admin_command(update, context)
            return
        if text.strip() == "🔎 Qidirish":
            await message.reply_text("🔎 Qidirish: `/searchquiz matematika`", parse_mode=ParseMode.MARKDOWN)
            return
        # Admin menyu tugmalari
        if text.strip() == "➕ Create Quiz":
            if is_admin_user(user_id):
                keyboard = [
                    [KeyboardButton("📄 Fayl yuborish"), KeyboardButton("💬 Mavzu aytish")],
                    [KeyboardButton("⬅️ Orqaga")]
                ]
                markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                await message.reply_text(
                    "➕ **Quiz yaratish**\n\n"
                    "Quiz yaratish usulini tanlang:",
                    reply_markup=markup,
                    parse_mode=ParseMode.MARKDOWN
                )
            return
        if text.strip() == "📄 Fayl yuborish":
            if is_admin_user(user_id):
                context.user_data['admin_action'] = 'create_quiz_file'
                keyboard = [[KeyboardButton("⬅️ Orqaga")]]
                markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                await message.reply_text(
                    "📄 **Fayl yuborish**\n\n"
                    "Quiz yaratish uchun fayl yuboring:\n"
                    "• TXT, DOCX, PDF formatlarida\n"
                    "• Faylda test savollari bo'lishi kerak\n\n"
                    "Faylni yuboring:",
                    reply_markup=markup,
                    parse_mode=ParseMode.MARKDOWN
                )
            return
        if text.strip() == "💬 Mavzu aytish":
            if is_admin_user(user_id):
                context.user_data['admin_action'] = 'create_quiz_topic'
                keyboard = [[KeyboardButton("⬅️ Orqaga")]]
                markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                await message.reply_text(
                    "💬 **Mavzu aytish**\n\n"
                    "Quiz yaratish uchun mavzuni yuboring.\n"
                    "Masalan: \"Matematika - Algebra\", \"Tarix - O'rta asrlar\" va hokazo.\n\n"
                    "Mavzuni yuboring:",
                    reply_markup=markup,
                    parse_mode=ParseMode.MARKDOWN
                )
            return

    # ===== Admin wizard: group quiz allowlist (private chat) =====
    if context.user_data.get('admin_action') == 'gq_add':
        if not is_admin_user(user_id):
            context.user_data.pop('admin_action', None)
            context.user_data.pop('admin_target_group_id', None)
            return
        if update.effective_chat.type in ['group', 'supergroup']:
            await message.reply_text("ℹ️ Bu amal faqat shaxsiy chatda.")
            return

        gid = context.user_data.get('admin_target_group_id')
        raw = (text or "").strip()
        if not gid:
            context.user_data.pop('admin_action', None)
            await message.reply_text("❌ Guruh tanlanmagan. /admin dan qayta kiring.")
            return

        # cancel/exit
        if raw.lower() in ['cancel', 'bekor', 'stop', '/cancel']:
            context.user_data.pop('admin_action', None)
            context.user_data.pop('admin_target_group_id', None)
            await message.reply_text("✅ Bekor qilindi.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]]))
            return

        quiz_id = raw.split()[0]
        quiz = storage.get_quiz(quiz_id)
        if not quiz:
            await message.reply_text("❌ Quiz topilmadi. ID ni tekshiring (yoki `cancel`).", parse_mode=ParseMode.MARKDOWN)
            return

        storage.add_group_allowed_quiz(int(gid), quiz_id)
        context.user_data.pop('admin_action', None)
        context.user_data.pop('admin_target_group_id', None)
        title = quiz.get('title') or quiz_id
        await safe_reply_text(
            update.message,
            f"✅ Qo'shildi: **{title}** (`{quiz_id}`)\n\nEndi /startquiz faqat tanlanganlarni ko'rsatadi.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎛 Guruh quizlari", callback_data=f"admin_gq_select_{gid}")]]),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # ===== Admin broadcast wizard (private chat) =====
    if context.user_data.get('admin_action') in ['broadcast_users', 'broadcast_groups', 'send_to_group']:
        if not is_admin_user(user_id):
            context.user_data.pop('admin_action', None)
            return
        if update.effective_chat.type in ['group', 'supergroup']:
            await message.reply_text("ℹ️ Admin broadcast faqat shaxsiy chatda.")
            return

        admin_action = context.user_data.get('admin_action')
        pending_text = text.strip()
        if len(pending_text) < 1:
            await message.reply_text("❌ Xabar bo'sh bo'lmasin.")
            return

        context.user_data['admin_pending_text'] = pending_text
        if admin_action == 'send_to_group':
            gid = context.user_data.get('admin_target_group_id')
            if not gid:
                context.user_data.pop('admin_action', None)
                context.user_data.pop('admin_pending_text', None)
                await message.reply_text("❌ Guruh topilmadi.")
                return
            keyboard = [
                [InlineKeyboardButton("✅ Yuborish", callback_data=f"admin_send_group_yes_{gid}")],
                [InlineKeyboardButton("❌ Bekor", callback_data="admin_menu")],
            ]
            await message.reply_text(
                f"⚠️ Guruhga yuboriladigan xabar:\n\n{pending_text}\n\nTasdiqlaysizmi?",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        target_name = "foydalanuvchilarga" if admin_action == "broadcast_users" else "guruh(lar)ga"
        keyboard = [
            [InlineKeyboardButton("✅ Yuborish", callback_data=f"admin_broadcast_yes_{admin_action}")],
            [InlineKeyboardButton("❌ Bekor", callback_data="admin_menu")],
        ]
        await message.reply_text(
            f"⚠️ {target_name} yuboriladigan xabar:\n\n{pending_text}\n\nTasdiqlaysizmi?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    # ===== Admin create quiz from topic =====
    if context.user_data.get('admin_action') == 'create_quiz_topic':
        if not is_admin_user(user_id):
            context.user_data.pop('admin_action', None)
            return
        if update.effective_chat.type in ['group', 'supergroup']:
            await message.reply_text("ℹ️ Bu amal faqat shaxsiy chatda.")
            return
        
        topic = text.strip()
        if len(topic) < 3:
            await message.reply_text("❌ Mavzu juda qisqa. Kamida 3 belgi bo'lishi kerak.")
            return
        
        context.user_data.pop('admin_action', None)
        context.user_data['admin_action'] = 'create_quiz_topic_processing'
        context.user_data['admin_topic'] = topic
        
        status_msg = await message.reply_text(
            f"💬 **Mavzu:** {topic}\n\n"
            "🤖 AI quiz yaratmoqda..."
        )
        
        try:
            # AI orqali quiz yaratish
            from bot.services.ai_parser import AIParser
            ai_parser = AIParser()
            
            # Mavzu asosida prompt yaratish
            prompt_text = f"""Quyidagi mavzu bo'yicha test savollarini yarating:

Mavzu: {topic}

Har bir savol uchun:
- Savol matni
- 4 ta javob varianti
- To'g'ri javob
- Qisqa tushuntirish (ixtiyoriy)

Kamida 10 ta savol yarating."""
            
            await status_msg.edit_text(
                f"💬 **Mavzu:** {topic}\n\n"
                "🤖 AI ga so'rov yuborilmoqda..."
            )
            
            async def progress_callback(percent, text):
                try:
                    await status_msg.edit_text(
                        f"💬 **Mavzu:** {topic}\n\n"
                        f"🤖 {text}"
                    )
                except Exception:
                    pass
            
            result = await ai_parser.analyze_with_ai(
                prompt_text,
                progress_callback=progress_callback,
                strict_correct=False
            )
            
            if not result or not result.get('questions'):
                await status_msg.edit_text(
                    f"❌ Mavzu bo'yicha quiz yaratib bo'lmadi.\n\n"
                    f"💡 Boshqa mavzu yuborib ko'ring."
                )
                context.user_data.pop('admin_action', None)
                context.user_data.pop('admin_topic', None)
                return
            
            questions = result.get('questions', [])
            ai_title = result.get('title', topic[:50])
            
            # Quiz saqlash
            quiz_content = json.dumps(questions, sort_keys=True)
            quiz_id = hashlib.md5(quiz_content.encode()).hexdigest()[:12]
            
            user_id = message.from_user.id
            chat_id = message.chat_id
            
            storage.save_quiz(quiz_id, questions, user_id, chat_id, ai_title)
            
            keyboard = [
                [KeyboardButton("⬅️ Orqaga")],
                [KeyboardButton("🛠 Admin")]
            ]
            markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await status_msg.edit_text(
                f"✅ **Quiz tayyor!**\n\n"
                f"🏷 Nomi: {ai_title}\n"
                f"📝 Savollar: {len(questions)}\n"
                f"🆔 ID: `{quiz_id}`",
                reply_markup=markup,
                parse_mode=ParseMode.MARKDOWN
            )
            
            context.user_data.pop('admin_action', None)
            context.user_data.pop('admin_topic', None)
            
        except Exception as e:
            logger.error(f"Topic quiz creation error: {e}", exc_info=True)
            await status_msg.edit_text(
                f"❌ Xatolik: {str(e)}\n\n"
                f"💡 Qayta urinib ko'ring."
            )
            context.user_data.pop('admin_action', None)
            context.user_data.pop('admin_topic', None)
        return

    # ===== Admin sudo wizard (faqat creator uchun) =====
    if context.user_data.get('admin_action') in ['sudo_add', 'sudo_remove']:
        if not is_admin_user(user_id):
            context.user_data.pop('admin_action', None)
            return
        if update.effective_chat.type in ['group', 'supergroup']:
            await message.reply_text("ℹ️ Bu amal faqat shaxsiy chatda.")
            return

        admin_action = context.user_data.get('admin_action')
        raw = (text or "").strip()
        
        # cancel/exit
        if raw.lower() in ['cancel', 'bekor', 'stop', '/cancel']:
            context.user_data.pop('admin_action', None)
            await message.reply_text("✅ Bekor qilindi.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]]))
            return

        try:
            target_id = int(raw)
        except (ValueError, TypeError):
            await message.reply_text("❌ User ID raqam bo'lishi kerak. Masalan: `123456789`", parse_mode=ParseMode.MARKDOWN)
            return

        if admin_action == 'sudo_add':
            # User ma'lumotlarini olish
            username = None
            first_name = None
            try:
                for u in storage.get_users():
                    if int(u.get('user_id')) == target_id:
                        username = u.get('username')
                        first_name = u.get('first_name')
                        break
            except Exception:
                pass
            storage.add_sudo_user(target_id, username=username, first_name=first_name)
            await safe_reply_text(
                update.message,
                f"✅ Sudo berildi: `{target_id}`",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin", callback_data="admin_sudo")]]),
                parse_mode=ParseMode.MARKDOWN
            )
        else:  # sudo_remove
            ok = storage.remove_sudo_user(target_id)
            await safe_reply_text(
                update.message,
                ("✅ Sudo olib tashlandi: " if ok else "ℹ️ Sudo topilmadi: ") + f"`{target_id}`",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin", callback_data="admin_sudo")]]),
                parse_mode=ParseMode.MARKDOWN
            )
        
        context.user_data.pop('admin_action', None)
        return
    
    # Quiz nom o'zgartirish
    if 'editing_quiz_id' in context.user_data and context.user_data.get('editing_action') == 'name':
        quiz_id = context.user_data['editing_quiz_id']
        quiz = storage.get_quiz(quiz_id)
        
        if not quiz or quiz.get('created_by') != user_id:
            await message.reply_text("❌ Quiz topilmadi yoki sizniki emas!")
            context.user_data.pop('editing_quiz_id', None)
            context.user_data.pop('editing_action', None)
            return
        
        # Nomni yangilash
        new_name = text.strip()[:100]  # Maksimal 100 belgi
        
        if len(new_name) < 3:
            await message.reply_text("❌ Nom juda qisqa. Kamida 3 ta belgi kiriting.")
            return
        
        # Storage da yangilash
        try:
            quiz['title'] = new_name
            storage.save_quiz(
                quiz_id,
                quiz['questions'],
                quiz['created_by'],
                quiz['created_in_chat'],
                new_name
            )
            
            keyboard = [[InlineKeyboardButton("🔙 Quizga qaytish", callback_data=f"quiz_menu_{quiz_id}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await message.reply_text(
                f"✅ **Quiz nomi yangilandi!**\n\n"
                f"📝 Yangi nom: {new_name}",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            
            context.user_data.pop('editing_quiz_id', None)
            context.user_data.pop('editing_action', None)
        except Exception as e:
            logger.error(f"Quiz nomini yangilashda xatolik: {e}")
            await message.reply_text(f"❌ Xatolik: {str(e)}")


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fayl qabul qilish"""
    track_update(update)
    message = update.message
    chat_type = update.effective_chat.type
    
    if chat_type in ['group', 'supergroup']:
        # Guruhda fayl qabul qilinmaydi
        return

    # Faqat createquiz jarayonida fayl qabul qilinadi
    is_admin_file_action = (
        context.user_data.get('admin_action') == 'create_quiz_file' and
        is_admin_user(message.from_user.id)
    )
    
    # Agar createquiz jarayonida bo'lmasa, fayl qabul qilinmaydi
    if not is_admin_file_action:
        return
    
    # Admin file action bo'lsa, action ni o'chirish
    if is_admin_file_action:
        context.user_data.pop('admin_action', None)
    
    if not message.document:
        await message.reply_text("❌ Iltimos, fayl yuboring!")
        return
    
    file = await context.bot.get_file(message.document.file_id)
    file_name = message.document.file_name
    file_extension = os.path.splitext(file_name)[1]
    
    status_msg = await message.reply_text(
        f"📥 **Fayl:** {file_name}\n\n🔄 Tahlil qilinmoqda..."
    )

    last_percent = -1
    last_ts = 0.0
    
    async def update_progress(percent, text):
        nonlocal last_percent, last_ts
        try:
            now = time.time()
            # monotonic + throttling (qotib qolmasligi uchun)
            percent = int(max(percent, last_percent))
            if percent == last_percent and (now - last_ts) < 2.0:
                return
            last_percent = percent
            last_ts = now
            bar = "█" * (percent // 5) + "░" * (20 - percent // 5)
            await status_msg.edit_text(
                f"📥 **Fayl:** {file_name}\n\n[{bar}] {percent}%\n{text}"
            )
        except Exception:
            pass
    
    try:
        await update_progress(10, "📂 Yuklanmoqda...")
        file_bytes = BytesIO()
        await file.download_to_memory(file_bytes)
        file_content = file_bytes.getvalue()
        
        await update_progress(20, "📖 O'qilmoqda...")
        analyzer = FileAnalyzer()
        text = analyzer.extract_text(bytes(file_content), file_extension)
        
        if not text or len(text.strip()) < 10:
            await status_msg.edit_text("❌ Fayldan matn o'qib bo'lmadi.")
            return

        # =====================================================================
        # AI ASOSIY NAZORATCHI - barcha ishni AI qiladi
        # Algoritmik parser faqat tezkor precheck (faylda test bormi)
        # =====================================================================
        
        # Javoblar kaliti bo'lsa (fayl oxirida), oldindan olib qo'yamiz
        try:
            answer_key_map = extract_answer_key_map(text)
        except Exception:
            answer_key_map = {}
        
        # 1) Tezkor precheck: faylda test formatiga o'xshash pattern bormi?
        await update_progress(25, "🔎 Faylda test borligini tekshirish...")
        has_patterns = quick_has_quiz_patterns(text)
        target_limit = max(1, min(int(TARGET_QUESTIONS_PER_QUIZ or 50), int(MAX_QUESTIONS_PER_QUIZ or 100)))
        
        if not has_patterns:
            # Algoritmik precheck ham tekshiramiz
            algo_check: List[Dict] = []
            try:
                algo_check.extend(parse_tilde_quiz(text)[:5])
            except Exception:
                pass
            try:
                algo_check.extend(parse_numbered_quiz(text)[:5])
            except Exception:
                pass
            has_patterns = len(algo_check) >= 2
        
        if not has_patterns:
            await status_msg.edit_text(
                "❌ Bu faylda test savollari aniqlanmadi.\n\n"
                "✅ Namuna format:\n"
                "1) Savol matni?\n"
                "A) Variant 1\nB) Variant 2\nC) Variant 3\nD) Variant 4\n\n"
                "ℹ️ Agar fayl juda katta bo'lsa, uni 2-3 qismga bo'lib yuboring."
            )
            return
        
        # 2) AI ASOSIY ISH: savollarni ajratish + to'g'ri javoblarni aniqlash
        ai_text = sanitize_ai_input(text)
        await update_progress(30, "🤖 AI savollarni ajratmoqda...")
        ai_parser = AIParser()
        ai_started_at = time.time()
        heartbeat_stop = False

        async def heartbeat():
            while not heartbeat_stop:
                elapsed = int(time.time() - ai_started_at)
                await update_progress(50, f"⏳ AI tahlil qilmoqda... ({elapsed}s)")
                await asyncio.sleep(8)

        hb_task = asyncio.create_task(heartbeat())
        
        ai_result = None
        ai_title = ""
        
        # 2.1) Birinchi urinish: deepseek-chat (tez va arzon)
        try:
            ai_result = await asyncio.wait_for(
                ai_parser.analyze_with_ai(ai_text, progress_callback=update_progress, strict_correct=True, model="deepseek-chat"),
                timeout=MAX_AI_SECONDS
            )
        except asyncio.TimeoutError:
            logger.error(f"AI (chat) timeout after {MAX_AI_SECONDS}s for file={file_name}")
            ai_result = None
        except Exception as e:
            logger.error(f"AI (chat) error: {e}")
            ai_result = None
        
        # 2.2) Agar chat topolmasa yoki yetarli savol bo'lmasa — deepseek-reasoner (kuchli)
        if not ai_result or len(ai_result.get("questions", [])) < MIN_QUESTIONS_REQUIRED:
            await update_progress(45, "🧠 AI (reasoner) savollarni ajratmoqda...")
            ai_started_at = time.time()
            try:
                ai_result = await asyncio.wait_for(
                    ai_parser.analyze_with_ai(ai_text, progress_callback=update_progress, strict_correct=True, model="deepseek-reasoner"),
                    timeout=MAX_AI_SECONDS + 60  # reasoner uchun ko'proq vaqt
                )
            except asyncio.TimeoutError:
                logger.error(f"AI (reasoner) timeout for file={file_name}")
                ai_result = None
            except Exception as e:
                logger.error(f"AI (reasoner) error: {e}")
                ai_result = None
        
        heartbeat_stop = True
        try:
            hb_task.cancel()
        except Exception:
            pass
        
        # 2.3) AI natijasini tekshirish
        if not ai_result or not ai_result.get("questions"):
            await status_msg.edit_text(
                "❌ AI fayldan savollarni ajrata olmadi.\n\n"
                "ℹ️ Iltimos, quyidagilarni tekshiring:\n"
                "• Savollar va variantlar aniq ko'rinib turadimi?\n"
                "• Fayl juda katta bo'lsa, 2-3 qismga bo'lib yuboring\n"
                "• Format: 1) Savol? A) ... B) ... C) ... D) ..."
            )
            return
        
        ai_title = (ai_result.get("title") or "").strip()
        questions = validate_questions(ai_result.get("questions", []), require_correct=False)
        
        if len(questions) < MIN_QUESTIONS_REQUIRED:
            await status_msg.edit_text(
                "❌ AI yetarli savollarni ajrata olmadi.\n\n"
                f"Topildi: {len(questions)} ta (minimum: {MIN_QUESTIONS_REQUIRED})\n\n"
                "ℹ️ Formatni aniqroq qilib qayta yuboring."
            )
            return
        
        # Limit qo'llash
        if target_limit > 0 and len(questions) > target_limit:
            questions = questions[:target_limit]
        
        await update_progress(70, f"✅ {len(questions)} ta savol topildi")
        
        # 3) Answer key'ni qo'llaymiz (bo'lsa)
        try:
            applied = apply_answer_key_to_questions(questions, answer_key_map)
            if applied:
                logger.info(f"answer_key applied: {applied}/{len(questions)} file={file_name}")
        except Exception:
            pass

        # 4) To'g'ri javoblar topilmagan bo'lsa — AI orqali to'ldiramiz
        missing_idxs = [i for i, q in enumerate(questions) if q.get("correct_answer") is None]
        
        if missing_idxs:
            await update_progress(75, f"🧠 To'g'ri javoblar aniqlanmoqda... ({len(missing_idxs)} ta)")
            
            chunk_size = 10
            total_missing = len(missing_idxs)
            solved = 0
            
            for start in range(0, total_missing, chunk_size):
                chunk_indices = missing_idxs[start:start + chunk_size]
                chunk_questions = [questions[i] for i in chunk_indices]

                # Birinchi chat, keyin reasoner
                answers = await AIParser.pick_correct_answers(chunk_questions, model="deepseek-chat")
                if not answers or len(answers) != len(chunk_indices):
                    answers = await AIParser.pick_correct_answers(chunk_questions, model="deepseek-reasoner")

                if answers and len(answers) == len(chunk_indices):
                    for local_i, ans_idx in enumerate(answers):
                        gi = chunk_indices[local_i]
                        opts = questions[gi].get("options") or []
                        if isinstance(opts, list) and ans_idx is not None and 0 <= ans_idx < len(opts):
                            questions[gi]["correct_answer"] = ans_idx
                            solved += 1

                try:
                    done = min(start + len(chunk_indices), total_missing)
                    pct = 75 + int(15 * (done / max(1, total_missing)))
                    await update_progress(pct, f"🧠 To'g'ri javoblar: {solved}/{total_missing}")
                except Exception:
                    pass

        # 5) REQUIRE_CORRECT_ANSWER tekshiruvi
        if REQUIRE_CORRECT_ANSWER:
            with_correct = [q for q in questions if q.get("correct_answer") is not None]
            if len(with_correct) >= MIN_QUESTIONS_REQUIRED:
                dropped = len(questions) - len(with_correct)
                questions = with_correct
                if dropped > 0:
                    try:
                        await context.bot.send_message(
                            chat_id=message.chat_id,
                            text=f"ℹ️ {dropped} ta savolda to'g'ri javob topilmadi — ular olib tashlandi."
                        )
                    except Exception:
                        pass
            else:
                await status_msg.edit_text(
                    "❌ To'g'ri javoblarni topib bo'lmadi.\n\n"
                    "✅ Ye­chimlar:\n"
                    "1) Fayl oxiriga javoblar kalitini qo'shing (masalan: `Javoblar: 1-A, 2-C, 3-B`)\n"
                    "2) To'g'ri variant boshiga `✅` yoki `*` qo'ying\n"
                    "3) Yoki savollarni qisqartirib qayta yuboring\n"
                )
                return

        if len(questions) < MIN_QUESTIONS_REQUIRED:
            await status_msg.edit_text(
                "❌ Fayldan yetarli test savollari topilmadi.\n\n"
                "Iltimos, savollar+variantlar aniq ko'rinadigan formatda yuboring."
            )
            return

        # 4) Cheklov: juda ko'p savol bo'lsa kesamiz
        if len(questions) > MAX_QUESTIONS_PER_QUIZ:
            questions = questions[:MAX_QUESTIONS_PER_QUIZ]
            try:
                await context.bot.send_message(
                    chat_id=message.chat_id,
                    text=f"ℹ️ Juda ko'p savol topildi. Cheklov: {MAX_QUESTIONS_PER_QUIZ} ta savol saqlandi."
                )
            except Exception:
                pass
        
        user_id = message.from_user.id
        chat_id = message.chat_id
        
        quiz_content = json.dumps(questions, sort_keys=True)
        quiz_id = hashlib.md5(quiz_content.encode()).hexdigest()[:12]
        
        title_to_save = (ai_title[:100] if ai_title else file_name)
        storage.save_quiz(quiz_id, questions, user_id, chat_id, title_to_save)
        
        keyboard = [
            [InlineKeyboardButton("🚀 Quizni boshlash", callback_data=f"quiz_menu_{quiz_id}")],
            [InlineKeyboardButton("📊 Ma'lumot", callback_data=f"quiz_info_{quiz_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await status_msg.edit_text(
            f"✅ **Quiz tayyor!**\n\n"
            f"🏷 Nomi: {title_to_save[:50]}\n"
            f"📝 Savollar: {len(questions)}\n"
            f"🆔 ID: `{quiz_id}`",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"Fayl tahlil xatolik: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Xatolik: {str(e)}")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler"""
    track_update(update)
    await advance_due_sessions(context)
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    
    # ==================== ADMIN PANEL ====================
    if data.startswith("admin_"):
        if not is_admin_user(user_id):
            await query.answer("❌ Siz admin emassiz.", show_alert=True)
            return

        # Admin panel faqat private chatda
        if query.message.chat.type in ['group', 'supergroup']:
            await query.answer("Admin panel faqat shaxsiy chatda.", show_alert=True)
            return

        if data == "admin_menu":
            await show_admin_menu(query, context, as_edit=True)
            return

        if data == "admin_quizzes":
            # Admin panel uchun barcha quizlar ro'yxati
            all_quizzes = storage.get_all_quizzes()
            if not all_quizzes:
                keyboard = [[InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_menu")]]
                await safe_edit_text(query.message, "📚 **Quizlar:**\n\nHozircha quizlar yo'q.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
                return
            
            all_quizzes.sort(key=lambda q: q.get('created_at', ''), reverse=True)
            QUIZZES_PER_PAGE = 10
            total_quizzes = len(all_quizzes)
            total_pages = (total_quizzes + QUIZZES_PER_PAGE - 1) // QUIZZES_PER_PAGE
            page = 0
            
            start_idx = page * QUIZZES_PER_PAGE
            end_idx = min(start_idx + QUIZZES_PER_PAGE, total_quizzes)
            page_quizzes = all_quizzes[start_idx:end_idx]
            
            text = f"📚 **Barcha quizlar:** (Sahifa {page + 1}/{total_pages})\n\n"
            keyboard = []
            for i, quiz in enumerate(page_quizzes, 1):
                global_idx = start_idx + i
                count = len(quiz.get('questions', []))
                title = (quiz.get('title') or f"Quiz {global_idx}")[:30]
                text += f"{global_idx}. 📝 {title} ({count} savol) — `{quiz.get('quiz_id', '')[:12]}`\n"
                keyboard.append([InlineKeyboardButton(
                    f"📝 {title} ({count})",
                    callback_data=f"quiz_menu_{quiz['quiz_id']}"
                )])
            
            pagination_buttons = []
            if total_pages > 1:
                if page < total_pages - 1:
                    pagination_buttons.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"admin_quizzes_page_{page + 1}"))
                if pagination_buttons:
                    keyboard.append(pagination_buttons)
            
            keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_menu")])
            await safe_edit_text(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("admin_quizzes_page_"):
            page = int(data.replace("admin_quizzes_page_", ""))
            all_quizzes = storage.get_all_quizzes()
            all_quizzes.sort(key=lambda q: q.get('created_at', ''), reverse=True)
            QUIZZES_PER_PAGE = 10
            total_quizzes = len(all_quizzes)
            total_pages = (total_quizzes + QUIZZES_PER_PAGE - 1) // QUIZZES_PER_PAGE
            page = max(0, min(page, total_pages - 1))
            
            start_idx = page * QUIZZES_PER_PAGE
            end_idx = min(start_idx + QUIZZES_PER_PAGE, total_quizzes)
            page_quizzes = all_quizzes[start_idx:end_idx]
            
            text = f"📚 **Barcha quizlar:** (Sahifa {page + 1}/{total_pages})\n\n"
            keyboard = []
            for i, quiz in enumerate(page_quizzes, 1):
                global_idx = start_idx + i
                count = len(quiz.get('questions', []))
                title = (quiz.get('title') or f"Quiz {global_idx}")[:30]
                text += f"{global_idx}. 📝 {title} ({count} savol) — `{quiz.get('quiz_id', '')[:12]}`\n"
                keyboard.append([InlineKeyboardButton(
                    f"📝 {title} ({count})",
                    callback_data=f"quiz_menu_{quiz['quiz_id']}"
                )])
            
            pagination_buttons = []
            if total_pages > 1:
                if page > 0:
                    pagination_buttons.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"admin_quizzes_page_{page - 1}"))
                if page < total_pages - 1:
                    pagination_buttons.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"admin_quizzes_page_{page + 1}"))
                if pagination_buttons:
                    keyboard.append(pagination_buttons)
            
            keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_menu")])
            await safe_edit_text(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
            return

        if data == "admin_sudo":
            # Faqat creator uchun
            if not is_admin_user(user_id):
                await query.answer("❌ Bu funksiya faqat creator uchun.", show_alert=True)
                return
            
            sudo_users = storage.get_sudo_users()
            text = "🛡 **Sudo userlar:**\n\n"
            if not sudo_users:
                text += "Hozircha sudo userlar yo'q."
            else:
                for u in sudo_users[:20]:
                    uname = f"@{u.get('username')}" if u.get('username') else "-"
                    text += f"- `{u.get('user_id')}` {uname} {u.get('first_name') or ''}\n"
            
            keyboard = [
                [InlineKeyboardButton("➕ Qo'shish", callback_data="admin_sudo_add")],
                [InlineKeyboardButton("➖ Olib tashlash", callback_data="admin_sudo_remove")],
                [InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_menu")],
            ]
            await safe_edit_text(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
            return

        if data == "admin_sudo_add":
            if not is_admin_user(user_id):
                await query.answer("❌ Bu funksiya faqat creator uchun.", show_alert=True)
                return
            context.user_data['admin_action'] = 'sudo_add'
            await safe_edit_text(
                query.message,
                "➕ **Sudo user qo'shish**\n\n"
                "User ID yuboring (masalan: `123456789`).\n"
                "Bekor qilish: `cancel`",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_sudo")]]),
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if data == "admin_sudo_remove":
            if not is_admin_user(user_id):
                await query.answer("❌ Bu funksiya faqat creator uchun.", show_alert=True)
                return
            context.user_data['admin_action'] = 'sudo_remove'
            await safe_edit_text(
                query.message,
                "➖ **Sudo user olib tashlash**\n\n"
                "User ID yuboring (masalan: `123456789`).\n"
                "Bekor qilish: `cancel`",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_sudo")]]),
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if data == "admin_create_quiz":
            text = (
                "➕ **Quiz yaratish**\n\n"
                "Quiz yaratish uchun fayl yuboring:\n\n"
                "**Qo'llab-quvvatlanadigan formatlar:**\n"
                "• TXT - Matn fayllari\n"
                "• PDF - PDF hujjatlar\n"
                "• DOCX - Word hujjatlar\n\n"
                "**Format namuna:**\n"
                "1. Savol matni?\n"
                "A) Variant 1\n"
                "B) Variant 2\n"
                "C) Variant 3\n"
                "D) Variant 4\n\n"
                "yoki\n\n"
                "Savol 1\n"
                "~ Variant 1\n"
                "~ Variant 2\n"
                "~ Variant 3\n"
                "~ Variant 4\n\n"
                "Faylni yuboring va bot avtomatik quiz yaratadi."
            )
            keyboard = [[InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_menu")]]
            await safe_edit_text(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
            return

        # ===== Group quiz allowlist in admin panel =====
        if data == "admin_group_quiz":
            await _admin_gq_show_groups(query.message, context)
            return

        if data.startswith("admin_gq_select_"):
            gid_raw = data.replace("admin_gq_select_", "")
            try:
                gid = int(gid_raw)
            except Exception:
                await query.answer("❌ Guruh ID xato.", show_alert=True)
                return
            await _admin_gq_show_group_menu(query.message, context, gid)
            return

        if data.startswith("admin_gq_list_"):
            rest = data.replace("admin_gq_list_", "")
            parts = rest.split("_")
            try:
                if len(parts) == 1:
                    # Old format: just gid
                    gid = int(parts[0])
                    page = 0
                else:
                    # New format: gid_page
                    gid = int(parts[0])
                    page = int(parts[1])
            except (ValueError, IndexError):
                await query.answer("❌ Guruh ID xato.", show_alert=True)
                return
            await _admin_gq_show_allowed_list(query.message, context, gid, page=page)
            return

        if data.startswith("admin_gq_pick_"):
            rest = data.replace("admin_gq_pick_", "")
            parts = rest.split("_")
            try:
                if len(parts) == 1:
                    # Old format: just gid
                    gid = int(parts[0])
                    page = 0
                else:
                    # New format: gid_page
                    gid = int(parts[0])
                    page = int(parts[1])
            except (ValueError, IndexError):
                await query.answer("❌ Guruh ID xato.", show_alert=True)
                return
            await _admin_gq_show_pick_latest(query.message, context, gid, page=page)
            return

        if data.startswith("admin_gq_add_"):
            gid_raw = data.replace("admin_gq_add_", "")
            try:
                gid = int(gid_raw)
            except Exception:
                await query.answer("❌ Guruh ID xato.", show_alert=True)
                return
            context.user_data['admin_action'] = 'gq_add'
            context.user_data['admin_target_group_id'] = gid
            await safe_edit_text(
                query.message,
                "➕ Quiz qo'shish\n\n"
                "Quiz ID yuboring (masalan: `b672034fe4b4`).\n"
                "Bekor qilish: `cancel`",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data=f"admin_gq_select_{gid}")]]),
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if data.startswith("admin_gq_off_"):
            gid_raw = data.replace("admin_gq_off_", "")
            try:
                gid = int(gid_raw)
            except Exception:
                await query.answer("❌ Guruh ID xato.", show_alert=True)
                return
            storage.set_group_allowed_quiz_ids(gid, [])
            await _admin_gq_show_group_menu(query.message, context, gid)
            return

        if data.startswith("admin_gq_addid_"):
            # format: admin_gq_addid_<gid>_<quizid>
            rest = data.replace("admin_gq_addid_", "")
            try:
                gid_part, quiz_id = rest.rsplit("_", 1)
                gid = int(gid_part)
            except Exception:
                await query.answer("❌ Ma'lumot xato.", show_alert=True)
                return
            quiz = storage.get_quiz(quiz_id)
            if not quiz:
                await query.answer("❌ Quiz topilmadi.", show_alert=True)
                return
            storage.add_group_allowed_quiz(gid, quiz_id)
            await _admin_gq_show_allowed_list(query.message, context, gid)
            return

        if data.startswith("admin_gq_rm_"):
            # format: admin_gq_rm_<gid>_<quizid>
            rest = data.replace("admin_gq_rm_", "")
            try:
                gid_part, quiz_id = rest.rsplit("_", 1)
                gid = int(gid_part)
            except Exception:
                await query.answer("❌ Ma'lumot xato.", show_alert=True)
                return
            storage.remove_group_allowed_quiz(gid, quiz_id)
            await _admin_gq_show_allowed_list(query.message, context, gid)
            return

        if data == "admin_stats":
            quizzes_count = storage.get_quizzes_count()
            results_count = storage.get_results_count()
            users_count = storage.get_users_count()
            groups_count = storage.get_groups_count()
            sessions = context.bot_data.get('sessions', {}) or {}
            active_sessions = sum(1 for s in sessions.values() if s.get('is_active', False))

            text = (
                "📊 **Statistika**\n\n"
                f"📚 Quizlar: **{quizzes_count}**\n"
                f"🧾 Natijalar: **{results_count}**\n"
                f"👤 Bot users: **{users_count}**\n"
                f"👥 Guruhlar (known): **{groups_count}**\n"
                f"🟢 Aktiv session: **{active_sessions}**\n"
            )
            keyboard = [[InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_menu")]]
            await safe_edit_text(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
            return

        if data == "admin_users":
            users = storage.get_users()
            text = "👤 **Bot foydalanuvchilari (oxirgilar):**\n\n"
            if not users:
                text += "Hali userlar yo'q."
            else:
                for u in users[:15]:
                    uname = f"@{u.get('username')}" if u.get('username') else "-"
                    text += f"- `{u.get('user_id')}` {uname} — {u.get('first_name') or ''} (last: {u.get('last_seen','')[:19]})\n"
            keyboard = [[InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_menu")]]
            await safe_edit_text(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
            return

        if data == "admin_groups":
            bot_id = context.bot.id
            group_ids = list(collect_known_group_ids(context))
            if not group_ids:
                keyboard = [[InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_menu")]]
                await query.message.edit_text(
                    "👥 Guruhlar topilmadi.\n\n"
                    "Sabab: bot hali guruhlardan update olmagan bo'lishi mumkin.\n"
                    "Ye­chim: guruhda botga bir marta /startquiz yuboring yoki botni qayta qo'shib admin qiling.",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
                return

            rows: List[str] = []
            keyboard = []

            # Eng ko'p 15 guruh ko'rsatamiz (tezlik uchun)
            shown = 0
            for gid in group_ids:
                if shown >= 15:
                    break
                shown += 1

                # title ni yangilab qo'yamiz
                title = str(gid)
                chat_type = None
                try:
                    chat_obj = await context.bot.get_chat(gid)
                    title = (getattr(chat_obj, "title", None) or str(gid))[:28]
                    chat_type = getattr(chat_obj, "type", None)
                except Exception:
                    pass

                status = "unknown"
                is_admin = False
                try:
                    m = await context.bot.get_chat_member(gid, bot_id)
                    status = m.status
                    is_admin = status in ['administrator', 'creator']
                except Exception:
                    status = "no-access"

                # storage'ga statusni saqlab qo'yamiz (keyingi safar tezroq)
                try:
                    storage.track_group(chat_id=gid, title=title, chat_type=chat_type, bot_status=status, bot_is_admin=is_admin)
                except Exception:
                    pass

                badge = "✅ admin" if is_admin else status
                rows.append(f"- **{title}** (`{gid}`) — `{badge}`")
                keyboard.append([InlineKeyboardButton(f"✉️ {title}", callback_data=f"admin_send_group_{gid}")])

            if len(group_ids) > shown:
                rows.append(f"\n... va yana {len(group_ids) - shown} ta (bot update ko'rgan sari ko'payadi)")

            keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_menu")])
            text = "👥 **Guruhlar (discovered):**\n\n" + "\n".join(rows)
            await safe_edit_text(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
            return

        if data == "admin_broadcast":
            keyboard = [
                [InlineKeyboardButton("📨 Users ga yuborish", callback_data="admin_broadcast_users")],
                [InlineKeyboardButton("👥 Admin guruhlarga yuborish", callback_data="admin_broadcast_groups")],
                [InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_menu")],
            ]
            await query.message.edit_text("📣 Qayerga yuboramiz?", reply_markup=InlineKeyboardMarkup(keyboard))
            return

        if data in ["admin_broadcast_users", "admin_broadcast_groups"]:
            context.user_data['admin_action'] = "broadcast_users" if data.endswith("_users") else "broadcast_groups"
            context.user_data.pop('admin_pending_text', None)
            await query.message.edit_text("✍️ Yuboriladigan xabar matnini jo'nating (keyin tasdiqlaysiz).")
            return

        if data.startswith("admin_send_group_yes_"):
            gid = int(data.replace("admin_send_group_yes_", ""))
            text_to_send = context.user_data.get('admin_pending_text')
            context.user_data.pop('admin_action', None)
            context.user_data.pop('admin_pending_text', None)
            context.user_data.pop('admin_target_group_id', None)
            if not text_to_send:
                await query.message.edit_text("❌ Xabar topilmadi.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]]))
                return
            ok = 0
            try:
                await context.bot.send_message(chat_id=gid, text=text_to_send)
                ok = 1
            except Exception as e:
                logger.error(f"admin_send_group error: {e}", exc_info=True)
            fail_hint = ""
            if not ok:
                msg = str(e) if 'e' in locals() else ""
                if "Forbidden" in msg:
                    fail_hint = "\n\nSabab: bot guruhda yo'q yoki yozish huquqi yo'q (403 Forbidden)."
                elif "chat not found" in msg.lower():
                    fail_hint = "\n\nSabab: chat topilmadi (bot guruhdan chiqib ketgan bo'lishi mumkin)."
            await query.message.edit_text(
                ("✅ Yuborildi" if ok else "❌ Yuborilmadi (permission yoki boshqa xatolik).") + fail_hint,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]])
            )
            return

        # NOTE: "admin_send_group_yes_" yuqorida, shuning uchun bu yerda "yes_" yiqilib qolmaydi.
        if data.startswith("admin_send_group_"):
            gid = int(data.replace("admin_send_group_", ""))
            context.user_data['admin_action'] = "send_to_group"
            context.user_data['admin_target_group_id'] = gid
            context.user_data.pop('admin_pending_text', None)
            await query.message.edit_text(f"✍️ `{gid}` guruhga yuboriladigan xabar matnini jo'nating.", parse_mode=ParseMode.MARKDOWN)
            return

        if data.startswith("admin_broadcast_yes_"):
            action = data.replace("admin_broadcast_yes_", "")
            text_to_send = context.user_data.get('admin_pending_text')
            context.user_data.pop('admin_action', None)
            context.user_data.pop('admin_pending_text', None)
            if not text_to_send:
                await query.message.edit_text("❌ Xabar topilmadi.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]]))
                return

            sent = 0
            failed = 0
            if action == "broadcast_users":
                users = storage.get_users()
                targets = [int(u['user_id']) for u in users if u.get('last_chat_type') == 'private'][:2000]
            else:
                bot_id = context.bot.id
                groups = storage.get_groups()
                targets = []
                for g in groups:
                    gid = int(g['chat_id'])
                    try:
                        m = await context.bot.get_chat_member(gid, bot_id)
                        if m.status in ['administrator', 'creator']:
                            targets.append(gid)
                    except Exception:
                        continue
                targets = targets[:500]

            await query.message.edit_text(f"🚀 Yuborish boshlandi... target: {len(targets)} ta")
            for tid in targets:
                try:
                    await context.bot.send_message(chat_id=tid, text=text_to_send)
                    sent += 1
                except Exception:
                    failed += 1
                await asyncio.sleep(0.05)

            await query.message.edit_text(
                f"✅ Yakunlandi.\n\nYuborildi: {sent}\nXatolik: {failed}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]])
            )
            return

        if data == "admin_cleanup":
            sessions = context.bot_data.setdefault('sessions', {})
            group_locks = context.bot_data.setdefault('group_locks', {})
            cleared_sessions = 0
            for s in sessions.values():
                if s.get('is_active', False):
                    s['is_active'] = False
                    cleared_sessions += 1
            cleared_locks = len(group_locks)
            group_locks.clear()
            await query.message.edit_text(
                f"🧹 Tozalandi.\n\nSession yopildi: {cleared_sessions}\nLock: {cleared_locks}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]])
            )
            return
    
    # Pagination handlers
    if data.startswith('page_myquizzes_'):
        page = int(data.replace('page_myquizzes_', ''))
        user_id = query.from_user.id
        user_quizzes = storage.get_user_quizzes(user_id)
        
        if not user_quizzes:
            await query.message.edit_text("📭 Quizlar yo'q.")
            return
        
        QUIZZES_PER_PAGE = 10
        total_quizzes = len(user_quizzes)
        total_pages = (total_quizzes + QUIZZES_PER_PAGE - 1) // QUIZZES_PER_PAGE
        page = max(0, min(page, total_pages - 1))
        
        start_idx = page * QUIZZES_PER_PAGE
        end_idx = min(start_idx + QUIZZES_PER_PAGE, total_quizzes)
        page_quizzes = user_quizzes[start_idx:end_idx]
        
        text = f"📚 **Mening quizlarim:** (Sahifa {page + 1}/{total_pages})\n\n"
        keyboard = []
        
        for i, quiz in enumerate(page_quizzes, 1):
            global_idx = start_idx + i
            count = len(quiz.get('questions', []))
            title = quiz.get('title', f"Quiz {global_idx}")[:20]
            text += f"{global_idx}. 📝 {title} ({count} savol)\n"
            
            keyboard.append([InlineKeyboardButton(
                f"📝 {title} ({count} savol)",
                callback_data=f"quiz_menu_{quiz['quiz_id']}"
            )])
        
        pagination_buttons = []
        if total_pages > 1:
            if page > 0:
                pagination_buttons.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"page_myquizzes_{page - 1}"))
            if page < total_pages - 1:
                pagination_buttons.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"page_myquizzes_{page + 1}"))
            if pagination_buttons:
                keyboard.append(pagination_buttons)
        
        await safe_edit_text(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        return
    
    if data.startswith('page_quizzes_'):
        page = int(data.replace('page_quizzes_', ''))
        all_quizzes = storage.get_all_quizzes()
        
        if not all_quizzes:
            await query.message.edit_text("📭 Hozircha quizlar yo'q.")
            return
        
        all_quizzes.sort(key=lambda q: q.get('created_at', ''), reverse=True)
        
        QUIZZES_PER_PAGE = 10
        total_quizzes = len(all_quizzes)
        total_pages = (total_quizzes + QUIZZES_PER_PAGE - 1) // QUIZZES_PER_PAGE
        page = max(0, min(page, total_pages - 1))
        
        start_idx = page * QUIZZES_PER_PAGE
        end_idx = min(start_idx + QUIZZES_PER_PAGE, total_quizzes)
        page_quizzes = all_quizzes[start_idx:end_idx]
        
        text = f"📚 **Mavjud quizlar:** (Sahifa {page + 1}/{total_pages})\n\n"
        keyboard = []
        for i, quiz in enumerate(page_quizzes, 1):
            global_idx = start_idx + i
            count = len(quiz.get('questions', []))
            title = (quiz.get('title') or f"Quiz {global_idx}")[:30]
            text += f"{global_idx}. 📝 {title} ({count} savol)\n"
            keyboard.append([InlineKeyboardButton(
                f"📝 {title} ({count})",
                callback_data=f"quiz_menu_{quiz['quiz_id']}"
            )])
        
        pagination_buttons = []
        if total_pages > 1:
            if page > 0:
                pagination_buttons.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"page_quizzes_{page - 1}"))
            if page < total_pages - 1:
                pagination_buttons.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"page_quizzes_{page + 1}"))
            if pagination_buttons:
                keyboard.append(pagination_buttons)
        
        await safe_edit_text(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        return
    
    if data.startswith('page_group_quizzes_'):
        # Format: page_group_quizzes_<chat_id>_<page>
        parts = data.replace('page_group_quizzes_', '').split('_')
        if len(parts) >= 2:
            try:
                chat_id = int(parts[0])
                page = int(parts[1])
                # Recreate the startquiz view with pagination
                all_quizzes = storage.get_all_quizzes()
                allowed_ids = storage.get_group_allowed_quiz_ids(chat_id)
                if allowed_ids:
                    allowed_set = set(allowed_ids)
                    all_quizzes = [q for q in all_quizzes if str(q.get('quiz_id')) in allowed_set]
                
                if not all_quizzes:
                    await query.answer("❌ Quizlar topilmadi.", show_alert=True)
                    return
                
                QUIZZES_PER_PAGE = 10
                total_quizzes = len(all_quizzes)
                total_pages = (total_quizzes + QUIZZES_PER_PAGE - 1) // QUIZZES_PER_PAGE
                page = max(0, min(page, total_pages - 1))
                
                start_idx = page * QUIZZES_PER_PAGE
                end_idx = min(start_idx + QUIZZES_PER_PAGE, total_quizzes)
                page_quizzes = all_quizzes[start_idx:end_idx]
                
                text = ("📚 **Guruhda tanlangan quizlar:**\n\n" if allowed_ids else "📚 **Mavjud quizlar:**\n\n")
                if total_pages > 1:
                    text += f"(Sahifa {page + 1}/{total_pages})\n\n"
                keyboard = []
                
                for i, quiz in enumerate(page_quizzes, 1):
                    global_idx = start_idx + i
                    count = len(quiz.get('questions', []))
                    title = quiz.get('title', f"Quiz {global_idx}")[:20]
                    text += f"{global_idx}. 📝 {title} ({count} savol)\n"
                    
                    keyboard.append([InlineKeyboardButton(
                        f"🚀 {title} ({count} savol)",
                        callback_data=f"start_group_{quiz['quiz_id']}"
                    )])
                
                pagination_buttons = []
                if total_pages > 1:
                    if page > 0:
                        pagination_buttons.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"page_group_quizzes_{chat_id}_{page - 1}"))
                    if page < total_pages - 1:
                        pagination_buttons.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"page_group_quizzes_{chat_id}_{page + 1}"))
                    if pagination_buttons:
                        keyboard.append(pagination_buttons)
                
                text += "\n🎯 Quizni tanlang!"
                await safe_edit_text(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
            except (ValueError, IndexError):
                await query.answer("❌ Xatolik.", show_alert=True)
        return
    
    # Quiz menu
    if data.startswith('quiz_menu_'):
        quiz_id = data.replace('quiz_menu_', '')
        quiz = storage.get_quiz(quiz_id)
        
        if not quiz:
            await query.message.reply_text("❌ Quiz topilmadi!")
            return
        
        count = len(quiz.get('questions', []))
        title = quiz.get('title', 'Quiz')
        created_by = quiz.get('created_by')
        
        keyboard = [
            [InlineKeyboardButton("🚀 Boshlash", callback_data=f"select_time_{quiz_id}")],
            [InlineKeyboardButton("📊 Ma'lumot", callback_data=f"quiz_info_{quiz_id}")]
        ]
        
        # Faqat yaratuvchi tahrirlashi mumkin
        if created_by == user_id:
            keyboard.append([InlineKeyboardButton("✏️ Tahrirlash", callback_data=f"edit_quiz_{quiz_id}")])
        
        keyboard.append([InlineKeyboardButton("🔙 Orqaga", callback_data="back_to_quizzes")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await safe_edit_text(
            query.message,
            f"📝 **{title}**\n\n📊 Savollar: {count}\n🆔 ID: `{quiz_id}`",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    # Vaqt tanlash
    elif data.startswith('select_time_'):
        quiz_id = data.replace('select_time_', '')
        
        keyboard = [
            [
                InlineKeyboardButton("⚡ 10s", callback_data=f"time_10s_{quiz_id}"),
                InlineKeyboardButton("⏱ 30s", callback_data=f"time_30s_{quiz_id}")
            ],
            [
                InlineKeyboardButton("⏰ 1min", callback_data=f"time_1min_{quiz_id}"),
                InlineKeyboardButton("🕐 3min", callback_data=f"time_3min_{quiz_id}")
            ],
            [InlineKeyboardButton("🕑 5min", callback_data=f"time_5min_{quiz_id}")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data=f"quiz_menu_{quiz_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await safe_edit_text(
            query.message,
            "⏱ **Har bir savol uchun vaqt tanlang:**\n\n"
            "⚡ 10s - Tez rejim\n"
            "⏱ 30s - Standart\n"
            "⏰ 1min - Oddiy\n"
            "🕐 3min - Ko'proq vaqt\n"
            "🕑 5min - Chuqur fikrlash",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    # Vaqt tanlandi
    elif data.startswith('time_'):
        parts = data.replace('time_', '').split('_')
        time_key = parts[0]
        quiz_id = '_'.join(parts[1:])
        time_seconds = TIME_OPTIONS.get(time_key, 30)
        
        await start_quiz_session(query.message, context, quiz_id, chat_id, user_id, time_seconds)
        await query.message.delete()
    
    # Guruhda boshlash
    elif data.startswith('start_group_'):
        quiz_id = data.replace('start_group_', '')

        # allowlist tekshiruvi
        if not storage.group_allows_quiz(chat_id, quiz_id):
            await query.answer("⛔️ Bu quiz guruhda yoqilmagan (admin /allowquiz).", show_alert=True)
            return
        
        keyboard = [
            [
                InlineKeyboardButton("⚡ 10s", callback_data=f"gtime_10s_{quiz_id}"),
                InlineKeyboardButton("⏱ 30s", callback_data=f"gtime_30s_{quiz_id}")
            ],
            [
                InlineKeyboardButton("⏰ 1min", callback_data=f"gtime_1min_{quiz_id}"),
                InlineKeyboardButton("🕐 3min", callback_data=f"gtime_3min_{quiz_id}")
            ],
            [InlineKeyboardButton("🕑 5min", callback_data=f"gtime_5min_{quiz_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.edit_text(
            "⏱ **Vaqt tanlang:**",
            reply_markup=reply_markup
        )
    
    # Guruh vaqt tanlandi
    elif data.startswith('gtime_'):
        parts = data.replace('gtime_', '').split('_')
        time_key = parts[0]
        quiz_id = '_'.join(parts[1:])
        time_seconds = TIME_OPTIONS.get(time_key, 30)

        # allowlist tekshiruvi
        if not storage.group_allows_quiz(chat_id, quiz_id):
            await query.answer("⛔️ Bu quiz guruhda yoqilmagan (admin /allowquiz).", show_alert=True)
            return
        
        # Guruhda kamida 2 kishi bo'lishi kerak
        chat_type = query.message.chat.type
        if chat_type in ['group', 'supergroup']:
            try:
                member_count = await context.bot.get_chat_member_count(chat_id)
                # Bot ham sanaladi, shuning uchun kamida 3 bo'lishi kerak (bot + 2 kishi)
                if member_count < 3:
                    await query.answer(
                        "❌ Guruhda kamida 2 kishi bo'lishi kerak!",
                        show_alert=True
                    )
                    await query.message.edit_text(
                        "⚠️ **Guruhda quiz o'tkazish uchun kamida 2 kishi bo'lishi kerak!**\n\n"
                        "Iltimos, guruhga ko'proq odam qo'shing.",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return
            except Exception as e:
                logger.error(f"Member count check error: {e}")
        
        await start_quiz_session(query.message, context, quiz_id, chat_id, user_id, time_seconds)
        await query.message.delete()
    
    # Quiz info
    elif data.startswith('quiz_info_'):
        quiz_id = data.replace('quiz_info_', '')
        quiz = storage.get_quiz(quiz_id)
        
        if not quiz:
            await query.message.reply_text("❌ Quiz topilmadi!")
            return
        
        count = len(quiz.get('questions', []))
        title = quiz.get('title', 'Quiz')
        created = quiz.get('created_at', '')[:10]
        
        await query.message.reply_text(
            f"📊 **Quiz ma'lumotlari**\n\n"
            f"📝 Nomi: {title}\n"
            f"📋 Savollar: {count}\n"
            f"📅 Sana: {created}\n"
            f"🆔 ID: `{quiz_id}`",
            parse_mode=ParseMode.MARKDOWN
        )
    
    # Orqaga
    elif data == 'back_to_quizzes':
        # Use myquizzes_command with page 0
        user_quizzes = storage.get_user_quizzes(user_id)
        
        if not user_quizzes:
            await query.message.edit_text("📭 Quizlar yo'q.")
            return
        
        # Pagination: 10 ta har bir sahifada
        QUIZZES_PER_PAGE = 10
        total_quizzes = len(user_quizzes)
        total_pages = (total_quizzes + QUIZZES_PER_PAGE - 1) // QUIZZES_PER_PAGE
        page = 0
        
        start_idx = page * QUIZZES_PER_PAGE
        end_idx = min(start_idx + QUIZZES_PER_PAGE, total_quizzes)
        page_quizzes = user_quizzes[start_idx:end_idx]
        
        text = f"📚 **Mening quizlarim:** (Sahifa {page + 1}/{total_pages})\n\n"
        keyboard = []
        
        for i, quiz in enumerate(page_quizzes, 1):
            global_idx = start_idx + i
            count = len(quiz.get('questions', []))
            title = quiz.get('title', f"Quiz {global_idx}")[:20]
            text += f"{global_idx}. 📝 {title} ({count} savol)\n"
            
            keyboard.append([InlineKeyboardButton(
                f"📝 {title} ({count} savol)",
                callback_data=f"quiz_menu_{quiz['quiz_id']}"
            )])
        
        # Pagination tugmalari
        pagination_buttons = []
        if total_pages > 1:
            if page < total_pages - 1:
                pagination_buttons.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"page_myquizzes_{page + 1}"))
            if pagination_buttons:
                keyboard.append(pagination_buttons)
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await safe_edit_text(query.message, text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
    # Natijalar
    elif data.startswith('show_results_'):
        quiz_id = data.replace('show_results_', '')
        await show_quiz_results(query.message, context, quiz_id, chat_id, user_id)
    
    # Qayta boshlash
    elif data.startswith('restart_'):
        quiz_id = data.replace('restart_', '')
        session_key = f"quiz_{chat_id}_{user_id}_{quiz_id}"
        if session_key in context.chat_data:
            del context.chat_data[session_key]
        
        keyboard = [
            [
                InlineKeyboardButton("⚡ 10s", callback_data=f"time_10s_{quiz_id}"),
                InlineKeyboardButton("⏱ 30s", callback_data=f"time_30s_{quiz_id}")
            ],
            [
                InlineKeyboardButton("⏰ 1min", callback_data=f"time_1min_{quiz_id}"),
                InlineKeyboardButton("🕐 3min", callback_data=f"time_3min_{quiz_id}")
            ],
            [InlineKeyboardButton("🕑 5min", callback_data=f"time_5min_{quiz_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await safe_edit_text(
            query.message,
            "⏱ **Vaqt tanlang:**",
            reply_markup=reply_markup
        )
    
    # Quiz tahrirlash
    elif data.startswith('edit_quiz_'):
        quiz_id = data.replace('edit_quiz_', '')
        quiz = storage.get_quiz(quiz_id)
        
        if not quiz:
            await query.message.reply_text("❌ Quiz topilmadi!")
            return
        
        # Faqat yaratuvchi tahrirlashi mumkin
        if quiz.get('created_by') != user_id:
            await query.answer("❌ Faqat quiz egasi tahrirlashi mumkin!")
            return
        
        keyboard = [
            [InlineKeyboardButton("✏️ Nomini o'zgartirish", callback_data=f"edit_name_{quiz_id}")],
            [InlineKeyboardButton("🗑 O'chirish", callback_data=f"delete_quiz_{quiz_id}")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data=f"quiz_menu_{quiz_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        title = quiz.get('title', 'Quiz')
        await safe_edit_text(
            query.message,
            f"✏️ **Quiz tahrirlash**\n\n"
            f"📝 Joriy nom: {title}\n\n"
            f"Nima qilmoqchisiz?",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    # Nomini o'zgartirish
    elif data.startswith('edit_name_'):
        quiz_id = data.replace('edit_name_', '')
        
        # Nom o'zgartirish uchun user_data ga saqlash
        context.user_data['editing_quiz_id'] = quiz_id
        context.user_data['editing_action'] = 'name'
        
        await safe_edit_text(
            query.message,
            "✏️ **Quiz nomini o'zgartirish**\n\n"
            "Yangi nomni yuboring (maksimal 100 belgi):",
            parse_mode=ParseMode.MARKDOWN
        )
    
    # Quiz o'chirish
    elif data.startswith('delete_quiz_'):
        quiz_id = data.replace('delete_quiz_', '')
        quiz = storage.get_quiz(quiz_id)
        
        if not quiz or quiz.get('created_by') != user_id:
            await query.answer("❌ Quiz topilmadi yoki sizniki emas!")
            return
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Ha, o'chirish", callback_data=f"confirm_delete_{quiz_id}"),
                InlineKeyboardButton("❌ Yo'q", callback_data=f"quiz_menu_{quiz_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        title = quiz.get('title', 'Quiz')
        await safe_edit_text(
            query.message,
            f"⚠️ **Tasdiqlash**\n\n"
            f"**{title}** quizni o'chirishni tasdiqlaysizmi?\n\n"
            f"Bu amalni qaytarib bo'lmaydi!",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    # O'chirishni tasdiqlash
    elif data.startswith('confirm_delete_'):
        quiz_id = data.replace('confirm_delete_', '')
        quiz = storage.get_quiz(quiz_id)
        
        if not quiz or quiz.get('created_by') != user_id:
            await query.answer("❌ Quiz topilmadi yoki sizniki emas!")
            return
        
        # Storage dan o'chirish
        try:
            if storage.delete_quiz(quiz_id):
                await safe_edit_text(
                    query.message,
                    "✅ **Quiz o'chirildi!**\n\nQuiz butunlay o'chirildi.",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await safe_edit_text(query.message, "❌ Quiz o'chirishda xatolik!")
        except Exception as e:
            logger.error(f"Quiz o'chirish xatolik: {e}")
            await safe_edit_text(query.message, f"❌ Xatolik: {str(e)}")


async def start_quiz_session(message, context, quiz_id: str, chat_id: int, user_id: int, time_seconds: int):
    """Quiz sessiyasini boshlash"""
    quiz = storage.get_quiz(quiz_id)
    
    if not quiz:
        await message.reply_text("❌ Quiz topilmadi!")
        return
    
    questions = quiz.get('questions', [])
    if not questions:
        await message.reply_text("❌ Quizda savollar yo'q!")
        return
    
    session_key = f"quiz_{chat_id}_{user_id}_{quiz_id}"

    # Chat type
    try:
        chat_type = message.chat.type
    except Exception:
        try:
            chat_obj = await context.bot.get_chat(chat_id)
            chat_type = chat_obj.type
        except Exception:
            chat_type = 'private'

    # ====== GROUP allowlist ======
    if chat_type in ['group', 'supergroup'] and (not storage.group_allows_quiz(chat_id, quiz_id)):
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "⛔️ Bu quiz ushbu guruhda yoqilmagan.\n\n"
                "✅ Guruh admini: `/allowquiz <quiz_id>`\n"
                "📋 Ruxsat berilganlar: /allowedquizzes"
            ),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # ====== GROUP CONCURRENCY LIMITS ======
    if chat_type in ['group', 'supergroup']:
        sessions = context.bot_data.setdefault('sessions', {})
        group_locks = context.bot_data.setdefault('group_locks', {})

        # 0) Eski holatlar uchun: lock bo'lmasa ham guruhda aktiv session bor-yo'qligini tekshirish
        active_in_group = 0
        group_prefix = f"quiz_{chat_id}_"
        for k, s in sessions.items():
            if k.startswith(group_prefix) and s.get('is_active', False):
                active_in_group += 1
        if active_in_group >= MAX_ACTIVE_QUIZZES_PER_GROUP:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"⛔️ Guruhda allaqachon {MAX_ACTIVE_QUIZZES_PER_GROUP} ta aktiv quiz bor.\n"
                    "Tugagandan keyin yangisini boshlang (yoki admin /stopquiz)."
                )
            )
            return

        # 2) Per-user: userning guruhda bir vaqtning o'zida bitta sessioni (default)
        active_for_user = 0
        prefix = f"quiz_{chat_id}_{user_id}_"
        for k, s in sessions.items():
            if k.startswith(prefix) and s.get('is_active', False):
                active_for_user += 1
        if active_for_user >= MAX_ACTIVE_QUIZZES_PER_USER_IN_GROUP:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⛔️ Sizda guruhda allaqachon aktiv quiz bor. Tugagandan keyin yangisini boshlang.",
            )
            return
    
    # Session ma'lumotlarini bot_data ga saqlash (global, persistence)
    if 'sessions' not in context.bot_data:
        context.bot_data['sessions'] = {}
    
    context.bot_data['sessions'][session_key] = {
        'quiz_id': quiz_id,
        'current_question': 0,
        'answers': {},
        'time_seconds': time_seconds,
        'started_at': time.time(),
        'is_active': True,
        'chat_id': chat_id,
        'user_id': user_id,
        'chat_type': chat_type,
        # restart bo'lsa ham davom ettirish uchun:
        'last_question_sent_at': None,
        'last_question_index': None,
        'next_due_at': None
    }
    
    # Backward compatibility uchun chat_data ga ham saqlash
    if context.chat_data is not None:
        context.chat_data[session_key] = context.bot_data['sessions'][session_key]

    # Guruh uchun lock o'rnatamiz (session yaratib bo'lgandan keyin)
    if chat_type in ['group', 'supergroup']:
        group_locks = context.bot_data.setdefault('group_locks', {})
        group_locks[chat_id] = session_key
    
    title = quiz.get('title', 'Quiz')
    time_text = f"{time_seconds}s" if time_seconds < 60 else f"{time_seconds//60}min"
    
    await message.reply_text(
        f"🎯 **{title}** boshlanmoqda!\n\n"
        f"📋 Savollar: {len(questions)}\n"
        f"⏱ Vaqt: {time_text} har bir savol uchun\n\n"
        f"Birinchi savol kelmoqda...",
        parse_mode=ParseMode.MARKDOWN
    )
    
    await asyncio.sleep(2)
    await send_quiz_question(message, context, quiz_id, chat_id, user_id, 0)


async def send_quiz_question(message, context, quiz_id: str, chat_id: int, user_id: int, question_index: int):
    """Savolni yuborish"""
    quiz = storage.get_quiz(quiz_id)
    
    if not quiz:
        return
    
    questions = quiz.get('questions', [])
    session_key = f"quiz_{chat_id}_{user_id}_{quiz_id}"
    
    # Session tekshiruvi - bot_data dan
    if 'sessions' not in context.bot_data or session_key not in context.bot_data['sessions']:
        logger.warning(f"Session {session_key} not found in bot_data")
        return
    
    if not context.bot_data['sessions'][session_key].get('is_active', False):
        logger.warning(f"Session {session_key} is not active")
        return
    
    if question_index >= len(questions):
        await show_quiz_results(message, context, quiz_id, chat_id, user_id)
        return
    
    q_data = questions[question_index]
    question_text = q_data.get('question', '')
    options = q_data.get('options', [])
    correct_answer = q_data.get('correct_answer')
    time_seconds = context.bot_data['sessions'][session_key].get('time_seconds', 30)
    
    if len(options) < 2:
        await send_quiz_question(message, context, quiz_id, chat_id, user_id, question_index + 1)
        return
    
    # Options ni 100 belgidan oshmasligi uchun qisqartirish
    cleaned_options = []
    for opt in options[:10]:
        if len(opt) > 100:
            cleaned_options.append(opt[:97] + "...")
        else:
            cleaned_options.append(opt)
    
    poll_question = f"❓ Savol {question_index + 1}/{len(questions)}\n\n{question_text}"
    
    if len(poll_question) > 300:
        poll_question = poll_question[:297] + "..."
    
    try:
        if correct_answer is not None and 0 <= correct_answer < len(cleaned_options):
            poll_message = await context.bot.send_poll(
                chat_id=chat_id,
                question=poll_question,
                options=cleaned_options,
                is_anonymous=False,
                type='quiz',
                correct_option_id=correct_answer,
                open_period=time_seconds  # Telegram o'zi timerini ko'rsatadi
            )
        else:
            poll_message = await context.bot.send_poll(
                chat_id=chat_id,
                question=poll_question,
                options=cleaned_options,
                is_anonymous=False,
                allows_multiple_answers=False,
                open_period=time_seconds  # Telegram o'zi timerini ko'rsatadi
            )
        
        # Poll ma'lumotlarini bot_data ga saqlash (global, persistence bilan ishlaydi)
        if 'polls' not in context.bot_data:
            context.bot_data['polls'] = {}
        
        context.bot_data['polls'][poll_message.poll.id] = {
            'quiz_id': quiz_id,
            'question_index': question_index,
            'user_id': user_id,
            'chat_id': chat_id,
            'explanation': q_data.get('explanation', ''),
            'session_key': session_key,
            'message_id': poll_message.message_id
        }

        # Restartga chidamli bo'lishi uchun timingni saqlaymiz
        context.bot_data['sessions'][session_key]['last_question_sent_at'] = time.time()
        context.bot_data['sessions'][session_key]['last_question_index'] = question_index
        # kichik buffer bilan
        context.bot_data['sessions'][session_key]['next_due_at'] = time.time() + float(time_seconds) + 1.0
        
        # Avtomatik keyingi savolga o'tish (Telegram o'zi timerini ko'rsatadi)
        async def auto_next():
            logger.info(f"auto_next started: waiting {time_seconds}s for question {question_index}")
            await asyncio.sleep(time_seconds)
            
            logger.info(f"auto_next woke up: checking session {session_key}")
            
            # Session hali activeми tekshirish
            if 'sessions' not in context.bot_data or session_key not in context.bot_data['sessions']:
                logger.warning(f"auto_next: session {session_key} not found in bot_data")
                return
            
            if not context.bot_data['sessions'][session_key].get('is_active', False):
                logger.warning(f"auto_next: session {session_key} is not active")
                return
            
            current_q = context.bot_data['sessions'][session_key].get('current_question', 0)
            logger.info(f"auto_next: current_question={current_q}, expected={question_index}")
            
            # Current question o'zgarmagan bo'lsa, keyingisiga o'tish
            if current_q == question_index:
                logger.info(f"auto_next: moving to next question {question_index + 1}")
                context.bot_data['sessions'][session_key]['current_question'] = question_index + 1
                await send_quiz_question(message, context, quiz_id, chat_id, user_id, question_index + 1)
            else:
                logger.info(f"auto_next: question already changed to {current_q}, skipping")
        
        asyncio.create_task(auto_next())
        
    except Exception as e:
        logger.error(f"Poll xatolik: {e}", exc_info=True)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Xatolik: {str(e)}"
        )




async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Poll javobini qabul qilish"""
    try:
        if update.poll_answer and update.poll_answer.user:
            u = update.poll_answer.user
            storage.track_user(user_id=u.id, username=getattr(u, "username", None), first_name=getattr(u, "first_name", None), last_name=getattr(u, "last_name", None))
    except Exception:
        pass
    await advance_due_sessions(context)
    poll_answer = update.poll_answer
    user_id = poll_answer.user.id
    poll_id = poll_answer.poll_id
    selected_option = poll_answer.option_ids[0] if poll_answer.option_ids else None
    
    logger.info(f"Poll answer: user_id={user_id}, poll_id={poll_id}, selected={selected_option}")
    
    # bot_data dan poll ma'lumotlarini olish (global storage)
    if 'polls' not in context.bot_data or poll_id not in context.bot_data['polls']:
        logger.warning(f"Poll {poll_id} not found in bot_data")
        return
    
    poll_info = context.bot_data['polls'][poll_id]
    quiz_id = poll_info['quiz_id']
    question_index = poll_info['question_index']
    chat_id = poll_info['chat_id']
    session_key = poll_info.get('session_key')
    
    logger.info(f"Poll info: quiz_id={quiz_id}, q_index={question_index}, session_key={session_key}, chat_id={chat_id}")
    
    # Session ma'lumotlarini bot_data dan olish
    if 'sessions' not in context.bot_data:
        context.bot_data['sessions'] = {}
    
    if session_key not in context.bot_data['sessions']:
        logger.warning(f"Session {session_key} not found in bot_data")
        return
    
    # Javobni saqlash (faqat saqlash, current_question ni o'zgartirmaslik - auto_next buni qiladi)
    if 'answers' not in context.bot_data['sessions'][session_key]:
        context.bot_data['sessions'][session_key]['answers'] = {}
    
    # Faqat shu user uchun javobni saqlash
    if 'user_answers' not in context.bot_data['sessions'][session_key]:
        context.bot_data['sessions'][session_key]['user_answers'] = {}
    
    if user_id not in context.bot_data['sessions'][session_key]['user_answers']:
        context.bot_data['sessions'][session_key]['user_answers'][user_id] = {}
    
    context.bot_data['sessions'][session_key]['user_answers'][user_id][question_index] = selected_option
    
    # Eski format ham saqlaymiz (backward compatibility)
    context.bot_data['sessions'][session_key]['answers'][question_index] = selected_option
    
    logger.info(f"Answer saved: user={user_id}, q_index={question_index}, selected={selected_option}")

    # ===== Early advance =====
    # Faqat sessiyani boshlagan user (poll_info['user_id']) javob bersa, keyingi savolga o'tamiz.
    try:
        starter_id = int(poll_info.get('user_id'))
    except Exception:
        starter_id = None

    # session hali active bo'lsa va hozirgi savol shu bo'lsa
    sess = context.bot_data['sessions'].get(session_key, {})
    if starter_id is not None and user_id == starter_id and sess.get('is_active', False) and sess.get('chat_type') == 'private':
        current_q = sess.get('current_question', 0)
        if current_q == question_index:
            # joriy pollni erta yopamiz (vaqt tugaganda qayta "start" bo'lmasligi uchun)
            try:
                msg_id = poll_info.get('message_id')
                if msg_id:
                    await context.bot.stop_poll(chat_id=chat_id, message_id=int(msg_id))
            except Exception as e:
                logger.warning(f"stop_poll failed: {e}")

            next_idx = question_index + 1
            sess['current_question'] = next_idx
            # due-check / auto_next bu savolni qayta yuritmasligi uchun
            sess['next_due_at'] = time.time() + 10.0
            logger.info(f"early_advance: starter answered, moving to q={next_idx} session={session_key}")
            await send_quiz_question(None, context, quiz_id, chat_id, starter_id, next_idx)
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_update(update)
    if update.effective_chat.type in ['group', 'supergroup']:
        return
    if not is_admin_user(update.effective_user.id):
        # Oddiy foydalanuvchiga admin/sudo haqida bildirmaymiz
        return
    await show_admin_menu(update, context, as_edit=False)


async def show_admin_menu(update_or_query, context: ContextTypes.DEFAULT_TYPE, as_edit: bool):
    quizzes_count = storage.get_quizzes_count()
    results_count = storage.get_results_count()
    users_count = storage.get_users_count()
    groups_count = storage.get_groups_count()
    sessions = context.bot_data.get('sessions', {}) or {}
    active_sessions = sum(1 for s in sessions.values() if s.get('is_active', False))

    # Creator tekshiruvi (faqat asosiy admin)
    user_id = update_or_query.from_user.id if hasattr(update_or_query, 'from_user') else update_or_query.message.from_user.id
    is_creator = is_admin_user(user_id)

    text = (
        "🛠 **Admin panel**\n\n"
        f"📚 Quizlar: **{quizzes_count}**\n"
        f"🧾 Natijalar: **{results_count}**\n"
        f"👤 Bot users: **{users_count}**\n"
        f"👥 Guruhlar: **{groups_count}**\n"
        f"🟢 Aktiv session: **{active_sessions}**\n"
    )

    # ReplyKeyboardMarkup yaratish
    keyboard = [
        [KeyboardButton("📚 Quizlar"), KeyboardButton("📊 Statistika")],
        [KeyboardButton("👤 Users"), KeyboardButton("👥 Guruhlar")],
        [KeyboardButton("📣 Broadcast"), KeyboardButton("🧹 Cleanup")],
    ]
    
    if is_creator:
        keyboard.append([KeyboardButton("🛡 Sudo")])
    
    keyboard.append([KeyboardButton("➕ Create Quiz")])
    keyboard.append([KeyboardButton("🎛 Guruh quizlari")])
    keyboard.append([KeyboardButton("⬅️ Orqaga")])
    
    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    # ReplyKeyboardMarkup uchun har doim reply_text ishlatamiz
    # Callback query yoki oddiy update bo'lishidan qat'iy nazar
    if hasattr(update_or_query, 'message'):
        # Bu callback query yoki update bo'lishi mumkin
        message = update_or_query.message
        # Callback query dan kelganda, eski xabarni o'chirib, yangi xabarni yuboramiz
        try:
            await message.delete()
        except Exception:
            pass
        await message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    elif hasattr(update_or_query, 'reply_text'):
        # Bu oddiy Update obyekti
        await update_or_query.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    else:
        # Fallback
        if hasattr(update_or_query, 'effective_message'):
            await update_or_query.effective_message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)


async def _admin_gq_get_title(context: ContextTypes.DEFAULT_TYPE, gid: int) -> str:
    """Admin panel uchun guruh title (fallback: gid)."""
    try:
        chat_obj = await context.bot.get_chat(gid)
        return (getattr(chat_obj, "title", None) or str(gid))[:40]
    except Exception:
        return str(gid)


async def _admin_gq_show_groups(message, context: ContextTypes.DEFAULT_TYPE):
    group_ids = list(collect_known_group_ids(context))
    if not group_ids:
        keyboard = [[InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")]]
        await safe_edit_text(
            message,
            "👥 Guruhlar topilmadi.\n\n"
            "Bot guruhlardan update olishi uchun guruhda bir marta /startquiz yuboring.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    rows = []
    keyboard = []
    shown = 0
    for gid in group_ids:
        if shown >= 18:
            break
        shown += 1
        title = await _admin_gq_get_title(context, gid)
        allowed_count = 0
        try:
            allowed_count = len(storage.get_group_allowed_quiz_ids(gid))
        except Exception:
            allowed_count = 0
        mode = "ON" if allowed_count > 0 else "OFF"
        rows.append(f"- **{title}** (`{gid}`) — filter: **{mode}** ({allowed_count})")
        keyboard.append([InlineKeyboardButton(f"🎛 {title}", callback_data=f"admin_gq_select_{gid}")])

    if len(group_ids) > shown:
        rows.append(f"\n... va yana {len(group_ids) - shown} ta")

    keyboard.append([InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")])
    text = "🎛 **Guruh quizlari**\n\nGuruhni tanlang:\n\n" + "\n".join(rows)
    await safe_edit_text(message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)


async def _admin_gq_show_group_menu(message, context: ContextTypes.DEFAULT_TYPE, gid: int):
    title = await _admin_gq_get_title(context, gid)
    allowed_ids = storage.get_group_allowed_quiz_ids(gid)
    mode = "ON" if allowed_ids else "OFF"
    text = (
        f"🎛 **Guruh quizlari**\n\n"
        f"👥 Guruh: **{title}**\n"
        f"🆔 ID: `{gid}`\n"
        f"🔒 Filtr: **{mode}**\n"
        f"📋 Tanlanganlar: **{len(allowed_ids)}**\n\n"
        "Filtr **ON** bo'lsa, guruhda /startquiz faqat tanlangan quizlarni ko'rsatadi."
    )
    keyboard = [
        [InlineKeyboardButton("📋 Tanlanganlar ro'yxati", callback_data=f"admin_gq_list_{gid}")],
        [InlineKeyboardButton("➕ Oxirgilaridan qo'shish", callback_data=f"admin_gq_pick_{gid}")],
        [InlineKeyboardButton("➕ ID bilan qo'shish", callback_data=f"admin_gq_add_{gid}")],
        [InlineKeyboardButton("♻️ Filtr OFF (hamma quizlar)", callback_data=f"admin_gq_off_{gid}")],
        [InlineKeyboardButton("⬅️ Guruhlar", callback_data="admin_group_quiz")],
        [InlineKeyboardButton("⬅️ Admin", callback_data="admin_menu")],
    ]
    await safe_edit_text(message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)


async def _admin_gq_show_allowed_list(message, context: ContextTypes.DEFAULT_TYPE, gid: int, page: int = 0):
    title = await _admin_gq_get_title(context, gid)
    allowed_ids = storage.get_group_allowed_quiz_ids(gid)
    rows = []
    keyboard = []
    if not allowed_ids:
        rows.append("Hozir filtr **OFF** (tanlanganlar yo'q).")
    else:
        # Pagination: 10 ta har bir sahifada
        QUIZZES_PER_PAGE = 10
        total_quizzes = len(allowed_ids)
        total_pages = (total_quizzes + QUIZZES_PER_PAGE - 1) // QUIZZES_PER_PAGE
        page = max(0, min(page, total_pages - 1))
        
        start_idx = page * QUIZZES_PER_PAGE
        end_idx = min(start_idx + QUIZZES_PER_PAGE, total_quizzes)
        page_ids = allowed_ids[start_idx:end_idx]
        
        for qid in page_ids:
            quiz = storage.get_quiz(qid)
            if not quiz:
                continue
            qtitle = (quiz.get('title') or qid)[:28]
            qcount = len(quiz.get('questions', []))
            rows.append(f"- **{qtitle}** (`{qid}`) — {qcount} savol")
            keyboard.append([InlineKeyboardButton(f"❌ {qtitle}", callback_data=f"admin_gq_rm_{gid}_{qid}")])
        
        # Pagination tugmalari
        pagination_buttons = []
        if total_pages > 1:
            if page > 0:
                pagination_buttons.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"admin_gq_list_{gid}_{page - 1}"))
            if page < total_pages - 1:
                pagination_buttons.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"admin_gq_list_{gid}_{page + 1}"))
            if pagination_buttons:
                keyboard.append(pagination_buttons)

    text = f"📋 **Tanlangan quizlar**\n\n👥 **{title}** (`{gid}`)\n"
    if allowed_ids and len(allowed_ids) > 10:
        total_pages = (len(allowed_ids) + 10 - 1) // 10
        text += f"(Sahifa {page + 1}/{total_pages})\n"
    text += "\n" + "\n".join(rows)
    keyboard.extend([
        [InlineKeyboardButton("➕ Oxirgilaridan qo'shish", callback_data=f"admin_gq_pick_{gid}")],
        [InlineKeyboardButton("➕ ID bilan qo'shish", callback_data=f"admin_gq_add_{gid}")],
        [InlineKeyboardButton("⬅️ Orqaga", callback_data=f"admin_gq_select_{gid}")],
    ])
    await safe_edit_text(message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)


async def _admin_gq_show_pick_latest(message, context: ContextTypes.DEFAULT_TYPE, gid: int, page: int = 0):
    title = await _admin_gq_get_title(context, gid)
    all_quizzes = storage.get_all_quizzes()
    all_quizzes.sort(key=lambda q: q.get('created_at', ''), reverse=True)
    
    # Pagination: 10 ta har bir sahifada
    QUIZZES_PER_PAGE = 10
    total_quizzes = len(all_quizzes)
    total_pages = (total_quizzes + QUIZZES_PER_PAGE - 1) // QUIZZES_PER_PAGE
    page = max(0, min(page, total_pages - 1))
    
    start_idx = page * QUIZZES_PER_PAGE
    end_idx = min(start_idx + QUIZZES_PER_PAGE, total_quizzes)
    page_quizzes = all_quizzes[start_idx:end_idx]
    
    rows = []
    keyboard = []
    for i, quiz in enumerate(page_quizzes, 1):
        global_idx = start_idx + i
        qid = quiz.get('quiz_id')
        if not qid:
            continue
        qtitle = (quiz.get('title') or f"Quiz {global_idx}")[:28]
        qcount = len(quiz.get('questions', []))
        rows.append(f"{global_idx}. **{qtitle}** (`{qid}`) — {qcount} savol")
        keyboard.append([InlineKeyboardButton(f"➕ {qtitle}", callback_data=f"admin_gq_addid_{gid}_{qid}")])
    
    # Pagination tugmalari
    pagination_buttons = []
    if total_pages > 1:
        if page > 0:
            pagination_buttons.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"admin_gq_pick_{gid}_{page - 1}"))
        if page < total_pages - 1:
            pagination_buttons.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"admin_gq_pick_{gid}_{page + 1}"))
        if pagination_buttons:
            keyboard.append(pagination_buttons)
    
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data=f"admin_gq_select_{gid}")])
    text = f"➕ **Oxirgilaridan qo'shish**\n\n👥 **{title}** (`{gid}`)\n"
    if total_pages > 1:
        text += f"(Sahifa {page + 1}/{total_pages})\n"
    text += "\n" + ("\n".join(rows) if rows else "Quiz topilmadi.")
    await safe_edit_text(message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)


async def show_quiz_results(message, context, quiz_id: str, chat_id: int, user_id: int):
    """Natijalarni ko'rsatish"""
    quiz = storage.get_quiz(quiz_id)
    
    if not quiz:
        try:
            await context.bot.send_message(chat_id=chat_id, text="❌ Quiz topilmadi!")
        except:
            pass
        return
    
    questions = quiz.get('questions', [])
    session_key = f"quiz_{chat_id}_{user_id}_{quiz_id}"
    total = len(questions)
    graded_total = sum(1 for q in questions if (isinstance(q, dict) and q.get('correct_answer') is not None))
    
    # Session deactivate qilish va javoblarni olish
    user_answers_dict = {}
    if 'sessions' in context.bot_data and session_key in context.bot_data['sessions']:
        context.bot_data['sessions'][session_key]['is_active'] = False
        user_answers_dict = context.bot_data['sessions'][session_key].get('user_answers', {})
        # Eski format uchun
        if not user_answers_dict:
            answers = context.bot_data['sessions'][session_key].get('answers', {})
            if answers:
                user_answers_dict = {user_id: answers}
    
    logger.info(f"Calculating results: quiz_id={quiz_id}, total_questions={total}, users={list(user_answers_dict.keys())}")
    
    # Guruh vs shaxsiy chat
    try:
        chat = await context.bot.get_chat(chat_id)
        chat_type = chat.type
    except:
        chat_type = 'private'
    
    # E'lon xabari
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text="📊 **Quiz yakunlandi!**\n\nNatijalar hisoblanyapti...",
            parse_mode=ParseMode.MARKDOWN
        )
        await asyncio.sleep(2)
    except:
        pass
    
    if chat_type in ['group', 'supergroup']:
        # Guruhda - har bir user uchun natijalarni hisoblash
        title = quiz.get('title', 'Quiz')
        result_text = f"🎉 **{title} - Yakuniy natijalar**\n\n"
        if graded_total != total:
            result_text += f"ℹ️ Baholanadigan savollar: **{graded_total}/{total}**\n\n"
        
        user_results = []
        for uid, answers in user_answers_dict.items():
            correct_count = 0
            for i, q_data in enumerate(questions):
                correct_answer = q_data.get('correct_answer')
                user_answer = answers.get(i)
                if correct_answer is not None and user_answer == correct_answer:
                    correct_count += 1
            
            score_total = graded_total
            percentage = (correct_count / score_total * 100) if score_total > 0 else 0
            
            # Natijani saqlash
            storage.save_result(quiz_id, uid, chat_id, answers, correct_count, score_total)
            
            user_results.append({
                'user_id': uid,
                'correct_count': correct_count,
                'total': score_total,
                'percentage': percentage
            })
            logger.info(f"User {uid}: {correct_count}/{score_total} ({percentage:.0f}%)")
        
        # Foiz bo'yicha saralash
        user_results.sort(key=lambda x: (x['percentage'], x['correct_count']), reverse=True)
        
        if user_results:
            result_text += "🏆 **Top 10 Ishtirokchilar:**\n\n"
            medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
            
            for i, result in enumerate(user_results[:10]):
                medal = medals[i] if i < len(medals) else f"{i+1}."
                try:
                    user = await context.bot.get_chat_member(chat_id, result['user_id'])
                    user_name = user.user.first_name if user.user else f"User {result['user_id']}"
                except:
                    user_name = f"User {result['user_id']}"
                
                result_text += f"{medal} **{user_name}**: {result['correct_count']}/{result['total']} ({result['percentage']:.0f}%)\n"
        
        result_text += f"\n📊 Jami {len(user_results)} kishi ishtirok etdi"
        
        keyboard = [[InlineKeyboardButton("🔄 Qayta o'tkazish", callback_data=f"restart_{quiz_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Guruh lockni bo'shatamiz
        try:
            group_locks = context.bot_data.setdefault('group_locks', {})
            group_locks.pop(chat_id, None)
        except Exception:
            pass

        try:
            await safe_send_markdown(
                context=context,
            chat_id=chat_id,
            text=result_text,
                reply_markup=reply_markup
        )
        except Exception as e:
            logger.error(f"Natijani guruhga yuborishda xatolik: {e}", exc_info=True)
    else:
        # Shaxsiy chatda - faqat o'z natijasi
        answers = user_answers_dict.get(user_id, {})
        correct_count = 0
        for i, q_data in enumerate(questions):
            correct_answer = q_data.get('correct_answer')
            user_answer = answers.get(i)
            if correct_answer is not None and user_answer == correct_answer:
                correct_count += 1
        
        score_total = graded_total
        percentage = (correct_count / score_total * 100) if score_total > 0 else 0
        
        if percentage >= 90:
            emoji = "🏆"
            grade = "A'lo!"
        elif percentage >= 70:
            emoji = "👍"
            grade = "Yaxshi!"
        elif percentage >= 50:
            emoji = "📚"
            grade = "O'rtacha"
        else:
            emoji = "💪"
            grade = "Yana harakat qiling"
        
        title = quiz.get('title', 'Quiz')
        result_text = f"{emoji} **{title} - Sizning natijangiz**\n\n"
        if graded_total != total:
            result_text += f"ℹ️ Baholanadigan savollar: **{graded_total}/{total}**\n"
        result_text += f"📊 To'g'ri javoblar: {correct_count}/{score_total}\n"
        result_text += f"📈 Foiz: {percentage:.0f}%\n"
        result_text += f"📝 Baho: {grade}\n\n"
        result_text += "Qayta urinib ko'rmoqchimisiz?"
        
        keyboard = [[InlineKeyboardButton("🔄 Qayta", callback_data=f"restart_{quiz_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=chat_id,
            text=result_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Natijani saqlash
        try:
            storage.save_result(quiz_id, user_id, chat_id, answers, correct_count, score_total)
        except:
            pass


async def safe_send_markdown(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, reply_markup=None):
    """Telegram message length limit (4096) va ba'zi xatolarni yumshatish."""
    # Telegram limitiga moslab bo'lib yuboramiz
    max_len = 4000  # biroz buffer
    chunks = [text[i:i+max_len] for i in range(0, len(text), max_len)] or [text]

    for idx, chunk in enumerate(chunks):
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup if idx == (len(chunks) - 1) else None
            )
        except BadRequest as e:
            # Natija matnida user ismlari/titl’lar sabab markdown buzilishi mumkin.
            if "Can't parse entities" in str(e):
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=_markdown_to_plain(chunk),
                    reply_markup=reply_markup if idx == (len(chunks) - 1) else None
                )
            else:
                raise


async def advance_due_sessions(context: ContextTypes.DEFAULT_TYPE):
    """
    Restartdan keyin ham quizlar "osilib qolmasligi" uchun:
    har kelgan update'da due bo'lgan sessionlarni keyingi savolga o'tkazib yuboramiz.
    """
    try:
        sessions = context.bot_data.get('sessions', {})
        if not sessions:
            return
        now = time.time()

        # Kichik batch: juda ko'p session bo'lsa ham sekinlashmasin
        checked = 0
        for session_key, sess in list(sessions.items()):
            if checked > 50:
                break
            checked += 1

            if not sess.get('is_active', False):
                continue
            due_at = sess.get('next_due_at')
            last_idx = sess.get('last_question_index')
            if due_at is None or last_idx is None:
                continue
            if now < float(due_at):
                continue

            # current_question o'zgarmagan bo'lsa, oldinga o'tkazamiz
            current_q = sess.get('current_question', 0)
            if current_q != last_idx:
                continue

            quiz_id = sess.get('quiz_id')
            chat_id = sess.get('chat_id')
            user_id = sess.get('user_id')
            if not quiz_id or not chat_id or user_id is None:
                continue

            next_idx = int(last_idx) + 1
            sess['current_question'] = next_idx
            # qayta trigger bo'lmasligi uchun keyingi due ni vaqtincha uzoqroqqa qo'yamiz
            sess['next_due_at'] = now + 10.0
            logger.info(f"advance_due_sessions: advancing {session_key} to q={next_idx}")
            await send_quiz_question(None, context, quiz_id, int(chat_id), int(user_id), next_idx)
    except Exception as e:
        logger.error(f"advance_due_sessions error: {e}", exc_info=True)


def main():
    """Botni ishga tushirish"""
    if BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE' or not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN o'rnatilmagan!")
        print("❌ BOT_TOKEN ni o'rnating!")
        return
    
    if not DEEPSEEK_API_KEY:
        logger.warning("⚠️ DEEPSEEK_API_KEY o'rnatilmagan!")
    
    persistence_path = os.path.join(os.path.dirname(__file__), 'bot_persistence.pickle')
    persistence = PicklePersistence(filepath=persistence_path)
    
    application = Application.builder().token(BOT_TOKEN).persistence(persistence).build()
    
    # Handlerlar
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("myresults", myresults_command))
    application.add_handler(CommandHandler("myquizzes", myquizzes_command))
    application.add_handler(CommandHandler("sudo", sudo_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("quizzes", quizzes_command))
    application.add_handler(CommandHandler("searchquiz", searchquiz_command))
    application.add_handler(CommandHandler("quiz", quiz_command))
    application.add_handler(CommandHandler("deletequiz", deletequiz_command))
    application.add_handler(CommandHandler("allowquiz", allowquiz_command))
    application.add_handler(CommandHandler("disallowquiz", disallowquiz_command))
    application.add_handler(CommandHandler("allowedquizzes", allowedquizzes_command))
    application.add_handler(CommandHandler("startquiz", startquiz_command))
    application.add_handler(CommandHandler("stopquiz", stopquiz_command))
    application.add_handler(CommandHandler("finishquiz", finishquiz_command))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(PollAnswerHandler(poll_answer_handler))
    application.add_handler(ChatMemberHandler(my_chat_member_handler, ChatMemberHandler.MY_CHAT_MEMBER))
    
    print("🤖 Bot ishga tushmoqda...")
    logger.info("Bot ishga tushmoqda...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
