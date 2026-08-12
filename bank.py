"""题库模块 —— SQLite 存储，MD5 去重"""
import sqlite3
import hashlib
import json
from datetime import datetime
from config import BANK_DB


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(BANK_DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id TEXT PRIMARY KEY,
            course_id TEXT,
            question_text TEXT NOT NULL,
            question_type TEXT NOT NULL,
            options TEXT,
            correct_answer TEXT NOT NULL,
            source TEXT DEFAULT 'ai',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def question_hash(course_id: str, question_text: str) -> str:
    raw = f"{course_id}|{question_text.strip()}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def lookup(course_id: str, question_text: str) -> list | None:
    """查题库，返回答案列表或 None"""
    qid = question_hash(course_id, question_text)
    conn = get_db()
    row = conn.execute("SELECT correct_answer FROM questions WHERE id = ?", (qid,)).fetchone()
    conn.close()
    if row:
        return json.loads(row["correct_answer"])
    return None


def save(course_id: str, question_text: str, question_type: str,
         options: list | None, correct_answer: list, source: str = "ai"):
    qid = question_hash(course_id, question_text)
    conn = get_db()
    conn.execute("""
        INSERT OR REPLACE INTO questions (id, course_id, question_text, question_type, options, correct_answer, source, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    """, (
        qid, course_id, question_text.strip(), question_type,
        json.dumps(options, ensure_ascii=False) if options else None,
        json.dumps(correct_answer, ensure_ascii=False),
        source
    ))
    conn.commit()
    conn.close()


def stats() -> dict:
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) as c FROM questions").fetchone()["c"]
    by_type = {}
    for row in conn.execute("SELECT question_type, COUNT(*) as c FROM questions GROUP BY question_type"):
        by_type[row["question_type"]] = row["c"]
    conn.close()
    return {"total": total, "by_type": by_type}
