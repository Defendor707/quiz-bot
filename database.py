#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Database moduli - Quizlarni saqlash uchun SQLite database
"""

import sqlite3
import json
from typing import List, Dict, Optional
from datetime import datetime
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'bot_database.db')

class Database:
    """Database klass"""
    
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.init_database()
    
    def get_connection(self):
        """Database connection olish"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_database(self):
        """Database jadvallarini yaratish"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Quizlar jadvali
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS quizzes (
                quiz_id TEXT PRIMARY KEY,
                questions TEXT NOT NULL,
                created_by INTEGER NOT NULL,
                created_in_chat INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                title TEXT
            )
        ''')
        
        # Quiz natijalari jadvali
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS quiz_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                quiz_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                answers TEXT NOT NULL,
                correct_count INTEGER NOT NULL,
                total_count INTEGER NOT NULL,
                percentage REAL NOT NULL,
                completed_at TEXT NOT NULL,
                FOREIGN KEY (quiz_id) REFERENCES quizzes(quiz_id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def save_quiz(self, quiz_id: str, questions: List[Dict], created_by: int, created_in_chat: int, title: str = None):
        """Quizni saqlash"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO quizzes (quiz_id, questions, created_by, created_in_chat, created_at, title)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            quiz_id,
            json.dumps(questions),
            created_by,
            created_in_chat,
            datetime.now().isoformat(),
            title
        ))
        
        conn.commit()
        conn.close()
    
    def get_quiz(self, quiz_id: str) -> Optional[Dict]:
        """Quizni olish"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM quizzes WHERE quiz_id = ?', (quiz_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'quiz_id': row['quiz_id'],
                'questions': json.loads(row['questions']),
                'created_by': row['created_by'],
                'created_in_chat': row['created_in_chat'],
                'created_at': row['created_at'],
                'title': row['title']
            }
        return None
    
    def get_group_quizzes(self, chat_id: int) -> List[Dict]:
        """Guruh quizlarini olish"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM quizzes WHERE created_in_chat = ? ORDER BY created_at DESC', (chat_id,))
        rows = cursor.fetchall()
        conn.close()
        
        return [{
            'quiz_id': row['quiz_id'],
            'questions': json.loads(row['questions']),
            'created_by': row['created_by'],
            'created_in_chat': row['created_in_chat'],
            'created_at': row['created_at'],
            'title': row['title']
        } for row in rows]
    
    def get_all_quizzes(self) -> List[Dict]:
        """Barcha quizlarni olish"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM quizzes ORDER BY created_at DESC')
        rows = cursor.fetchall()
        conn.close()
        
        return [{
            'quiz_id': row['quiz_id'],
            'questions': json.loads(row['questions']),
            'created_by': row['created_by'],
            'created_in_chat': row['created_in_chat'],
            'created_at': row['created_at'],
            'title': row['title']
        } for row in rows]
    
    def save_result(self, quiz_id: str, user_id: int, chat_id: int, answers: Dict, correct_count: int, total_count: int):
        """Quiz natijasini saqlash"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        percentage = (correct_count / total_count * 100) if total_count > 0 else 0
        
        cursor.execute('''
            INSERT INTO quiz_results (quiz_id, user_id, chat_id, answers, correct_count, total_count, percentage, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            quiz_id,
            user_id,
            chat_id,
            json.dumps(answers),
            correct_count,
            total_count,
            percentage,
            datetime.now().isoformat()
        ))
        
        conn.commit()
        conn.close()
    
    def get_top_results(self, chat_id: int, limit: int = 10) -> List[Dict]:
        """Top natijalarni olish"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT user_id, correct_count, total_count, percentage, completed_at
            FROM quiz_results
            WHERE chat_id = ?
            ORDER BY percentage DESC, correct_count DESC
            LIMIT ?
        ''', (chat_id, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [{
            'user_id': row['user_id'],
            'correct_count': row['correct_count'],
            'total_count': row['total_count'],
            'percentage': row['percentage'],
            'completed_at': row['completed_at']
        } for row in rows]

