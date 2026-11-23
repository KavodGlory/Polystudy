"""Data-access layer for study notes, help requests, and demo-campus information."""
import json
import sqlite3
from .db import DB_PATH

# ---------- Notes ----------
def list_notes():
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute("SELECT id, title, language FROM notes ORDER BY id DESC")
        return cur.fetchall()

def get_note(note_id):
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute(
            "SELECT id, title, content, language FROM notes WHERE id = ?",
            (note_id,)
        )
        return cur.fetchone()

def create_note(title, content, language):
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute(
            "INSERT INTO notes (title, content, language) VALUES (?,?,?)",
            (title, content, language)
        )
        con.commit()
        return cur.lastrowid

def update_note(note_id, title, content, language):
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "UPDATE notes SET title=?, content=?, language=? WHERE id=?",
            (title, content, language, note_id)
        )
        con.commit()

# ---------- Help‑desk ----------
def list_tickets():
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute(
            "SELECT id, subject, created, answer IS NOT NULL AS answered FROM tickets ORDER BY created DESC"
        )
        return cur.fetchall()

def get_ticket(tid):
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute(
            "SELECT id, subject, question, answer FROM tickets WHERE id = ?",
            (tid,)
        )
        return cur.fetchone()

def create_ticket(subject, question):
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute(
            "INSERT INTO tickets (subject, question) VALUES (?,?)",
            (subject, question)
        )
        con.commit()
        return cur.lastrowid

def answer_ticket(tid, answer):
    with sqlite3.connect(DB_PATH) as con:
        con.execute("UPDATE tickets SET answer = ? WHERE id = ?", (answer, tid))
        con.commit()

# ---------- Quizzes ----------
def list_quizzes():
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute(
            "SELECT id, question, answer, lang_q, lang_a FROM quizzes ORDER BY id DESC"
        )
        return cur.fetchall()

def create_quiz(question, answer, lang_q, lang_a):
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute(
            "INSERT INTO quizzes (question, answer, lang_q, lang_a) VALUES (?,?,?,?)",
            (question, answer, lang_q, lang_a)
        )
        con.commit()
        return cur.lastrowid

def list_quiz_subjects():
    with sqlite3.connect(DB_PATH) as con:
        return [row[0] for row in con.execute(
            "SELECT DISTINCT subject FROM study_quizzes ORDER BY subject"
        )]


def list_study_quizzes(language="en"):
    language = "sw" if language == "sw" else "en"
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT id, subject, question_en, question_sw, choices_en, choices_sw, "
            "answer_index, explanation_en, explanation_sw FROM study_quizzes ORDER BY id"
        ).fetchall()
    suffix = "sw" if language == "sw" else "en"
    result = []
    for row in rows:
        item = dict(row)
        result.append({
            "id": item["id"],
            "subject": item["subject"],
            "question": item[f"question_{suffix}"],
            "choices": json.loads(item[f"choices_{suffix}"]),
            "answer_index": item["answer_index"],
            "explanation": item[f"explanation_{suffix}"],
        })
    return result

