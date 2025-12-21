#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Storage moduli - Quizlarni JSON faylda saqlash
"""

import json
import os
from typing import List, Dict, Optional
from datetime import datetime
import tempfile

# Storage fayl root direktoriyada bo'lishi kerak (eski versiya bilan moslik uchun)
# bot/models/ dan root ga chiqish: ../
STORAGE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'quizzes_storage.json')

class Storage:
    """JSON faylda saqlash klass"""
    # _save_data uses atomic temp file writes
    
    def __init__(self, storage_file: str = STORAGE_FILE):
        self.storage_file = storage_file
        self.init_storage()
    
    def init_storage(self):
        """Storage faylini yaratish"""
        if not os.path.exists(self.storage_file):
            with open(self.storage_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'quizzes': {},
                    'results': [],
                    'meta': {
                        'users': {},
                        'groups': {},
                        'sudo_users': {}
                    }
                }, f, ensure_ascii=False, indent=2)

    def _ensure_schema(self, data: Dict) -> Dict:
        """Orqaga moslik: eski storage fayllarida yangi keylar bo'lmasa qo'shib qo'yish"""
        if not isinstance(data, dict):
            data = {}
        data.setdefault('quizzes', {})
        data.setdefault('results', [])
        meta = data.setdefault('meta', {})
        if not isinstance(meta, dict):
            meta = {}
            data['meta'] = meta
        meta.setdefault('users', {})
        meta.setdefault('groups', {})
        meta.setdefault('sudo_users', {})
        # group settings schema
        try:
            groups = meta.get('groups') or {}
            if isinstance(groups, dict):
                for _, g in list(groups.items()):
                    if isinstance(g, dict):
                        g.setdefault('allowed_quiz_ids', [])
        except Exception:
            pass
        return data
    
    def _load_data(self) -> Dict:
        """Ma'lumotlarni yuklash"""
        try:
            if os.path.exists(self.storage_file):
                with open(self.storage_file, 'r', encoding='utf-8') as f:
                    return self._ensure_schema(json.load(f))
        except Exception as e:
            print(f"Storage yuklashda xatolik: {e}")
        return self._ensure_schema({'quizzes': {}, 'results': []})
    
    def _save_data(self, data: Dict):
        """Ma'lumotlarni saqlash"""
        try:
            # Atomic write: avval temp faylga yozamiz, keyin os.replace.
            # Bu ko'p userlik holatda JSON buzilib qolish xavfini kamaytiradi.
            directory = os.path.dirname(self.storage_file) or "."
            os.makedirs(directory, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(prefix=".quizzes_storage.", suffix=".tmp", dir=directory)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, self.storage_file)
            finally:
                try:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:
                    pass
        except Exception as e:
            print(f"Storage saqlashda xatolik: {e}")
    
    def save_quiz(self, quiz_id: str, questions: List[Dict], created_by: int, created_in_chat: int, title: str = None):
        """Quizni saqlash"""
        data = self._load_data()
        
        data['quizzes'][quiz_id] = {
            'quiz_id': quiz_id,
            'questions': questions,
            'created_by': created_by,
            'created_in_chat': created_in_chat,
            'created_at': datetime.now().isoformat(),
            'title': title
        }
        
        self._save_data(data)
    
    def get_quiz(self, quiz_id: str) -> Optional[Dict]:
        """Quizni olish"""
        data = self._load_data()
        return data['quizzes'].get(quiz_id)
    
    def get_all_quizzes(self) -> List[Dict]:
        """Barcha quizlarni olish"""
        data = self._load_data()
        return list(data['quizzes'].values())

    # ===== Admin meta =====
    def track_user(self, user_id: int, username: str = None, first_name: str = None, last_name: str = None,
                   last_chat_id: int = None, last_chat_type: str = None):
        """Foydalanuvchini tracking qilish (admin statistika uchun)"""
        data = self._load_data()
        users = data['meta']['users']
        key = str(user_id)
        users[key] = {
            'user_id': user_id,
            'username': username,
            'first_name': first_name,
            'last_name': last_name,
            'last_chat_id': last_chat_id,
            'last_chat_type': last_chat_type,
            'last_seen': datetime.now().isoformat()
        }
        self._save_data(data)

    def track_group(self, chat_id: int, title: str = None, chat_type: str = None, bot_status: str = None, bot_is_admin: bool = None):
        """Guruh/superguruhni tracking qilish (admin statistika uchun)"""
        data = self._load_data()
        groups = data['meta']['groups']
        key = str(chat_id)
        existing = groups.get(key) if isinstance(groups.get(key), dict) else {}
        payload = dict(existing) if isinstance(existing, dict) else {}
        payload['chat_id'] = chat_id
        if title is not None:
            payload['title'] = title
        if chat_type is not None:
            payload['chat_type'] = chat_type
        if bot_status is not None:
            payload['bot_status'] = bot_status
        if bot_is_admin is not None:
            payload['bot_is_admin'] = bot_is_admin
        payload['last_seen'] = datetime.now().isoformat()
        # preserve settings
        allowed = payload.get('allowed_quiz_ids', [])
        if not isinstance(allowed, list):
            allowed = []
        payload['allowed_quiz_ids'] = [str(x) for x in allowed if str(x).strip()]
        groups[key] = payload
        self._save_data(data)

    # ===== group quiz allowlist =====
    def get_group_allowed_quiz_ids(self, chat_id: int) -> List[str]:
        data = self._load_data()
        g = (data.get('meta', {}).get('groups', {}) or {}).get(str(chat_id), {})
        if not isinstance(g, dict):
            return []
        allowed = g.get('allowed_quiz_ids', [])
        if not isinstance(allowed, list):
            return []
        # normalize
        out = []
        for x in allowed:
            s = str(x).strip()
            if s and s not in out:
                out.append(s)
        return out

    def set_group_allowed_quiz_ids(self, chat_id: int, quiz_ids: List[str]):
        data = self._load_data()
        groups = data['meta']['groups']
        key = str(chat_id)
        g = groups.get(key) if isinstance(groups.get(key), dict) else {'chat_id': chat_id}
        allowed = []
        for q in (quiz_ids or []):
            s = str(q).strip()
            if s and s not in allowed:
                allowed.append(s)
        g['allowed_quiz_ids'] = allowed
        groups[key] = g
        self._save_data(data)

    def add_group_allowed_quiz(self, chat_id: int, quiz_id: str) -> bool:
        qid = str(quiz_id).strip()
        if not qid:
            return False
        allowed = self.get_group_allowed_quiz_ids(chat_id)
        if qid in allowed:
            return False
        allowed.append(qid)
        self.set_group_allowed_quiz_ids(chat_id, allowed)
        return True

    def remove_group_allowed_quiz(self, chat_id: int, quiz_id: str) -> bool:
        qid = str(quiz_id).strip()
        allowed = self.get_group_allowed_quiz_ids(chat_id)
        if qid not in allowed:
            return False
        allowed = [x for x in allowed if x != qid]
        self.set_group_allowed_quiz_ids(chat_id, allowed)
        return True

    def group_allows_quiz(self, chat_id: int, quiz_id: str) -> bool:
        allowed = self.get_group_allowed_quiz_ids(chat_id)
        if not allowed:
            return True
        return str(quiz_id).strip() in allowed

    def get_users(self) -> List[Dict]:
        data = self._load_data()
        users = list((data.get('meta', {}).get('users', {}) or {}).values())
        users.sort(key=lambda u: u.get('last_seen', ''), reverse=True)
        return users

    def get_groups(self) -> List[Dict]:
        data = self._load_data()
        groups = list((data.get('meta', {}).get('groups', {}) or {}).values())
        groups.sort(key=lambda g: g.get('last_seen', ''), reverse=True)
        return groups

    def get_quizzes_count(self) -> int:
        data = self._load_data()
        return len(data.get('quizzes', {}))

    def get_results_count(self) -> int:
        data = self._load_data()
        return len(data.get('results', []))

    def get_users_count(self) -> int:
        data = self._load_data()
        return len((data.get('meta', {}).get('users', {}) or {}))

    def get_groups_count(self) -> int:
        data = self._load_data()
        return len((data.get('meta', {}).get('groups', {}) or {}))

    # ===== sudo users =====
    def add_sudo_user(self, user_id: int, username: str = None, first_name: str = None):
        data = self._load_data()
        sudo_users = data['meta']['sudo_users']
        sudo_users[str(user_id)] = {
            'user_id': user_id,
            'username': username,
            'first_name': first_name,
            'added_at': datetime.now().isoformat()
        }
        self._save_data(data)

    def remove_sudo_user(self, user_id: int) -> bool:
        data = self._load_data()
        sudo_users = data['meta']['sudo_users']
        key = str(user_id)
        if key in sudo_users:
            del sudo_users[key]
            self._save_data(data)
            return True
        return False

    def get_sudo_users(self) -> List[Dict]:
        data = self._load_data()
        items = list((data.get('meta', {}).get('sudo_users', {}) or {}).values())
        items.sort(key=lambda u: u.get('added_at', ''), reverse=True)
        return items

    def is_sudo_user(self, user_id: int) -> bool:
        data = self._load_data()
        sudo_users = data.get('meta', {}).get('sudo_users', {}) or {}
        return str(user_id) in sudo_users
    
    def get_user_quizzes(self, user_id: int) -> List[Dict]:
        """Foydalanuvchining quizlarini olish"""
        data = self._load_data()
        return [quiz for quiz in data['quizzes'].values() if quiz['created_by'] == user_id]
    
    def save_result(self, quiz_id: str, user_id: int, chat_id: int, answers: Dict, correct_count: int, total_count: int):
        """Quiz natijasini saqlash"""
        data = self._load_data()
        
        percentage = (correct_count / total_count * 100) if total_count > 0 else 0
        
        result = {
            'quiz_id': quiz_id,
            'user_id': user_id,
            'chat_id': chat_id,
            'answers': answers,
            'correct_count': correct_count,
            'total_count': total_count,
            'percentage': percentage,
            'completed_at': datetime.now().isoformat()
        }
        
        data['results'].append(result)
        self._save_data(data)

    def get_user_results(self, user_id: int, limit: int = 20) -> List[Dict]:
        """Foydalanuvchining oxirgi natijalari (eng yangisi yuqorida)."""
        data = self._load_data()
        results = [r for r in data.get('results', []) if r.get('user_id') == user_id]
        results.sort(key=lambda x: x.get('completed_at', ''), reverse=True)
        return results[:limit]
    
    def get_top_results(self, chat_id: int, limit: int = 10) -> List[Dict]:
        """Top natijalarni olish"""
        data = self._load_data()
        results = [r for r in data['results'] if r['chat_id'] == chat_id]
        results.sort(key=lambda x: (x['percentage'], x['correct_count']), reverse=True)
        return results[:limit]
    
    def update_quiz_title(self, quiz_id: str, new_title: str) -> bool:
        """Quiz nomini yangilash"""
        try:
            data = self._load_data()
            
            if quiz_id in data['quizzes']:
                data['quizzes'][quiz_id]['title'] = new_title
                self._save_data(data)
                return True
            
            return False
        except Exception as e:
            print(f"Quiz nomini yangilashda xatolik: {e}")
            return False
    
    def delete_quiz(self, quiz_id: str) -> bool:
        """Quizni o'chirish"""
        try:
            data = self._load_data()
            
            if quiz_id in data['quizzes']:
                del data['quizzes'][quiz_id]
                self._save_data(data)
                return True
            
            return False
        except Exception as e:
            print(f"Quiz o'chirishda xatolik: {e}")
            return False

