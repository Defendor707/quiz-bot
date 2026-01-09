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
                        'sudo_users': {},
                        'vip_users': {}
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
        meta.setdefault('vip_users', {})
        meta.setdefault('premium_users', {})  # Premium foydalanuvchilar
        meta.setdefault('premium_payments', [])  # Premium to'lovlar tarixi
        meta.setdefault('required_channels', [])  # Majburiy obuna kanallari
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
        
        # Eski quiz ma'lumotlarini olish (agar mavjud bo'lsa)
        existing_quiz = data['quizzes'].get(quiz_id, {})
        
        data['quizzes'][quiz_id] = {
            'quiz_id': quiz_id,
            'questions': questions,
            'created_by': created_by,
            'created_in_chat': created_in_chat,
            'created_at': existing_quiz.get('created_at', datetime.now().isoformat()),
            'title': title,
            'is_private': existing_quiz.get('is_private', False),  # Default: public
            'allowed_groups': existing_quiz.get('allowed_groups', [])  # Ruxsat berilgan guruhlar ro'yxati
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

    # ===== VIP users =====
    def add_vip_user(self, user_id: int, username: str = None, first_name: str = None, nickname: str = None):
        """VIP user qo'shish"""
        data = self._load_data()
        vip_users = data['meta'].setdefault('vip_users', {})
        vip_users[str(user_id)] = {
            'user_id': user_id,
            'username': username,
            'first_name': first_name,
            'nickname': nickname or first_name or 'VIP User',
            'added_at': datetime.now().isoformat()
        }
        self._save_data(data)

    def remove_vip_user(self, user_id: int) -> bool:
        """VIP user olib tashlash"""
        data = self._load_data()
        vip_users = data.get('meta', {}).get('vip_users', {}) or {}
        key = str(user_id)
        if key in vip_users:
            del vip_users[key]
            self._save_data(data)
            return True
        return False

    def get_vip_users(self) -> List[Dict]:
        """VIP userlar ro'yxati"""
        data = self._load_data()
        items = list((data.get('meta', {}).get('vip_users', {}) or {}).values())
        items.sort(key=lambda u: u.get('added_at', ''), reverse=True)
        return items

    def is_vip_user(self, user_id: int) -> bool:
        """VIP user tekshiruvi"""
        data = self._load_data()
        vip_users = data.get('meta', {}).get('vip_users', {}) or {}
        return str(user_id) in vip_users

    def get_vip_user(self, user_id: int) -> Optional[Dict]:
        """VIP user ma'lumotlarini olish"""
        data = self._load_data()
        vip_users = data.get('meta', {}).get('vip_users', {}) or {}
        return vip_users.get(str(user_id))
    
    def get_user_quizzes(self, user_id: int) -> List[Dict]:
        """Foydalanuvchining quizlarini olish"""
        data = self._load_data()
        return [quiz for quiz in data['quizzes'].values() if quiz['created_by'] == user_id]
    
    def save_result(self, quiz_id: str, user_id: int, chat_id: int, answers: Dict, correct_count: int, total_count: int, answer_times: Dict = None):
        """Quiz natijasini saqlash
        
        Args:
            answer_times: {question_index: time_in_seconds} - har bir savol uchun javob berish vaqti
        """
        data = self._load_data()
        
        percentage = (correct_count / total_count * 100) if total_count > 0 else 0
        
        # Vaqt statistikasini hisoblash
        total_time = 0.0
        avg_time = 0.0
        min_time = None
        max_time = None
        if answer_times:
            times_list = [t for t in answer_times.values() if t is not None]
            if times_list:
                total_time = sum(times_list)
                avg_time = total_time / len(times_list)
                min_time = min(times_list)
                max_time = max(times_list)
        
        result = {
            'quiz_id': quiz_id,
            'user_id': user_id,
            'chat_id': chat_id,
            'answers': answers,
            'correct_count': correct_count,
            'total_count': total_count,
            'percentage': percentage,
            'completed_at': datetime.now().isoformat(),
            'answer_times': answer_times or {},
            'total_time': total_time,
            'avg_time': avg_time,
            'min_time': min_time,
            'max_time': max_time
        }
        
        data['results'].append(result)
        self._save_data(data)

    def get_user_results(self, user_id: int, limit: int = 20) -> List[Dict]:
        """Foydalanuvchining oxirgi natijalari (eng yangisi yuqorida)."""
        data = self._load_data()
        results = [r for r in data.get('results', []) if r.get('user_id') == user_id]
        results.sort(key=lambda x: x.get('completed_at', ''), reverse=True)
        return results[:limit]

    def get_user_results_in_group(self, user_id: int, chat_id: int, limit: int = 20) -> List[Dict]:
        """Foydalanuvchining guruhdagi natijalari (eng yangisi yuqorida)."""
        data = self._load_data()
        results = [r for r in data.get('results', []) 
                  if r.get('user_id') == user_id and r.get('chat_id') == chat_id]
        results.sort(key=lambda x: x.get('completed_at', ''), reverse=True)
        return results[:limit]
    
    def get_top_results(self, chat_id: int, limit: int = 10) -> List[Dict]:
        """Top natijalarni olish"""
        data = self._load_data()
        results = [r for r in data['results'] if r['chat_id'] == chat_id]
        results.sort(key=lambda x: (x['percentage'], x['correct_count']), reverse=True)
        return results[:limit]
    
    def get_all_group_results(self, chat_id: int) -> List[Dict]:
        """Guruhdagi barcha natijalarni olish"""
        data = self._load_data()
        results = [r for r in data.get('results', []) if r.get('chat_id') == chat_id]
        return results
    
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
    
    def set_quiz_private(self, quiz_id: str, is_private: bool) -> bool:
        """Quizni private/public qilish"""
        data = self._load_data()
        if quiz_id not in data['quizzes']:
            return False
        
        data['quizzes'][quiz_id]['is_private'] = is_private
        if not is_private:
            # Public qilinganda allowed_groups'ni tozalash
            data['quizzes'][quiz_id]['allowed_groups'] = []
        
        self._save_data(data)
        return True
    
    def add_quiz_allowed_group(self, quiz_id: str, group_id: int) -> bool:
        """Private quiz uchun guruh qo'shish"""
        data = self._load_data()
        if quiz_id not in data['quizzes']:
            return False
        
        quiz = data['quizzes'][quiz_id]
        if not quiz.get('is_private', False):
            return False
        
        allowed_groups = quiz.get('allowed_groups', [])
        if group_id not in allowed_groups:
            allowed_groups.append(group_id)
            quiz['allowed_groups'] = allowed_groups
            self._save_data(data)
        return True
    
    def remove_quiz_allowed_group(self, quiz_id: str, group_id: int) -> bool:
        """Private quiz uchun guruhni olib tashlash"""
        data = self._load_data()
        if quiz_id not in data['quizzes']:
            return False
        
        quiz = data['quizzes'][quiz_id]
        allowed_groups = quiz.get('allowed_groups', [])
        if group_id in allowed_groups:
            allowed_groups.remove(group_id)
            quiz['allowed_groups'] = allowed_groups
            self._save_data(data)
        return True
    
    def get_quiz_allowed_groups(self, quiz_id: str) -> List[int]:
        """Private quiz uchun ruxsat berilgan guruhlar ro'yxati"""
        data = self._load_data()
        quiz = data['quizzes'].get(quiz_id)
        if not quiz:
            return []
        return quiz.get('allowed_groups', [])
    
    def is_quiz_allowed_in_group(self, quiz_id: str, group_id: int) -> bool:
        """Quiz guruhda ruxsat berilganmi tekshirish"""
        data = self._load_data()
        quiz = data['quizzes'].get(quiz_id)
        if not quiz:
            return False
        
        # Agar quiz public bo'lsa, barcha guruhlarda ishlaydi
        if not quiz.get('is_private', False):
            return True
        
        # Agar quiz private bo'lsa, faqat ruxsat berilgan guruhlarda ishlaydi
        allowed_groups = quiz.get('allowed_groups', [])
        return group_id in allowed_groups
    
    # ===== Majburiy obuna kanallari =====
    def get_required_channels(self) -> List[Dict]:
        """Majburiy obuna kanallari ro'yxati"""
        data = self._load_data()
        return data.get('meta', {}).get('required_channels', [])
    
    def add_required_channel(self, channel_id: int, channel_username: str = None, channel_title: str = None) -> bool:
        """Majburiy obuna kanalini qo'shish"""
        data = self._load_data()
        channels = data['meta'].setdefault('required_channels', [])
        
        # Agar allaqachon mavjud bo'lsa, yangilash
        for ch in channels:
            if ch.get('channel_id') == channel_id:
                if channel_username:
                    ch['channel_username'] = channel_username
                if channel_title:
                    ch['channel_title'] = channel_title
                self._save_data(data)
                return True
        
        # Yangi kanal qo'shish
        channels.append({
            'channel_id': channel_id,
            'channel_username': channel_username,
            'channel_title': channel_title,
            'added_at': datetime.now().isoformat()
        })
        self._save_data(data)
        return True
    
    def remove_required_channel(self, channel_id: int) -> bool:
        """Majburiy obuna kanalini olib tashlash"""
        data = self._load_data()
        channels = data.get('meta', {}).get('required_channels', [])
        
        original_len = len(channels)
        channels[:] = [ch for ch in channels if ch.get('channel_id') != channel_id]
        
        if len(channels) < original_len:
            data['meta']['required_channels'] = channels
            self._save_data(data)
            return True
        return False
    
    # ===== Premium Users =====
    def add_premium_user(self, user_id: int, stars_amount: int, months: int = 1, username: str = None, first_name: str = None):
        """Premium user qo'shish yoki yangilash"""
        from datetime import datetime, timedelta
        data = self._load_data()
        premium_users = data['meta'].setdefault('premium_users', {})
        
        existing = premium_users.get(str(user_id), {})
        current_until = existing.get('premium_until')
        
        # Agar premium hali davom etayotgan bo'lsa, yangi muddatni qo'shamiz
        if current_until:
            try:
                current_date = datetime.fromisoformat(current_until)
                if current_date > datetime.now():
                    # Premium hali davom etmoqda, muddatni uzaytiramiz
                    new_until = current_date + timedelta(days=30 * months)
                else:
                    # Premium muddati tugagan, yangi muddatdan boshlaymiz
                    new_until = datetime.now() + timedelta(days=30 * months)
            except:
                new_until = datetime.now() + timedelta(days=30 * months)
        else:
            # Birinchi marta premium
            new_until = datetime.now() + timedelta(days=30 * months)
        
        premium_users[str(user_id)] = {
            'user_id': user_id,
            'username': username,
            'first_name': first_name,
            'premium_until': new_until.isoformat(),
            'stars_paid': stars_amount,
            'months': months,
            'activated_at': datetime.now().isoformat(),
            'last_updated': datetime.now().isoformat()
        }
        
        # To'lov tarixini saqlash
        payments = data['meta'].setdefault('premium_payments', [])
        payments.append({
            'user_id': user_id,
            'stars_amount': stars_amount,
            'months': months,
            'paid_at': datetime.now().isoformat(),
            'premium_until': new_until.isoformat()
        })
        
        self._save_data(data)
        return True
    
    def is_premium_user(self, user_id: int) -> bool:
        """Premium user tekshiruvi"""
        from datetime import datetime
        data = self._load_data()
        premium_users = data.get('meta', {}).get('premium_users', {}) or {}
        user_data = premium_users.get(str(user_id))
        
        if not user_data:
            return False
        
        # Muddati tekshirish
        premium_until = user_data.get('premium_until')
        if not premium_until:
            return False
        
        try:
            until_date = datetime.fromisoformat(premium_until)
            return until_date > datetime.now()
        except:
            return False
    
    def get_premium_user(self, user_id: int) -> Optional[Dict]:
        """Premium user ma'lumotlarini olish"""
        from datetime import datetime
        data = self._load_data()
        premium_users = data.get('meta', {}).get('premium_users', {}) or {}
        user_data = premium_users.get(str(user_id))
        
        if not user_data:
            return None
        
        # Muddati tekshirish
        premium_until = user_data.get('premium_until')
        if premium_until:
            try:
                until_date = datetime.fromisoformat(premium_until)
                if until_date <= datetime.now():
                    return None  # Premium muddati tugagan
            except:
                pass
        
        return user_data
    
    def get_premium_users_count(self) -> int:
        """Faol premium userlar soni"""
        from datetime import datetime
        data = self._load_data()
        premium_users = data.get('meta', {}).get('premium_users', {}) or {}
        
        count = 0
        for user_data in premium_users.values():
            premium_until = user_data.get('premium_until')
            if premium_until:
                try:
                    until_date = datetime.fromisoformat(premium_until)
                    if until_date > datetime.now():
                        count += 1
                except:
                    pass
        
        return count
    
    def get_user_quizzes_count_this_month(self, user_id: int) -> int:
        """Foydalanuvchining shu oyda yaratgan quizlari soni"""
        from datetime import datetime
        data = self._load_data()
        now = datetime.now()
        current_month_start = datetime(now.year, now.month, 1)
        
        count = 0
        for quiz in data.get('quizzes', {}).values():
            if quiz.get('created_by') == user_id:
                created_at = quiz.get('created_at')
                if created_at:
                    try:
                        created_date = datetime.fromisoformat(created_at)
                        if created_date >= current_month_start:
                            count += 1
                    except:
                        pass
        
        return count

