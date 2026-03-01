# -*- coding: utf-8 -*-
import json
from datetime import datetime
from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from config import (
    SQLALCHEMY_DATABASE_URI,
    SQLALCHEMY_TRACK_MODIFICATIONS,
    SECRET_KEY,
    PYTHON_TIME_LIMIT,
    BLENDER_TIME_LIMIT,
)
from models import db, Participant, Attempt

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = SQLALCHEMY_DATABASE_URI
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = SQLALCHEMY_TRACK_MODIFICATIONS
app.config["SECRET_KEY"] = SECRET_KEY
db.init_app(app)

TIME_LIMITS = {"python": PYTHON_TIME_LIMIT, "blender": BLENDER_TIME_LIMIT}


# --- Вопросы олимпиады (примеры, можно расширить) ---
QUESTIONS = {
    "python": [
        {
            "id": "p1",
            "text": "Что выведет: print(2 + 3 * 2)?",
            "type": "single",
            "options": ["8", "10", "12", "7"],
            "correct": "8",
            "points": 5,
        },
        {
            "id": "p2",
            "text": "Какой тип у значения 3.14?",
            "type": "single",
            "options": ["int", "float", "str", "bool"],
            "correct": "float",
            "points": 5,
        },
        {
            "id": "p3",
            "text": "Что делает range(3)?",
            "type": "single",
            "options": [
                "Создаёт список [0, 1, 2]",
                "Создаёт последовательность 0, 1, 2",
                "Возвращает число 3",
                "Ошибка",
            ],
            "correct": "Создаёт последовательность 0, 1, 2",
            "points": 5,
        },
        {
            "id": "p4",
            "text": "Выберите правильное объявление списка в Python.",
            "type": "single",
            "options": ["list = ()", "list = []", "list = {}", "list = ([])"],
            "correct": "list = []",
            "points": 5,
        },
        {
            "id": "p5",
            "text": "Что выведет: len('Привет')?",
            "type": "single",
            "options": ["5", "6", "7", "Ошибка"],
            "correct": "6",
            "points": 5,
        },
    ],
    "blender": [
        {
            "id": "b1",
            "text": "Какой горячей клавишей создаётся куб в Blender?",
            "type": "single",
            "options": ["Shift+A", "Ctrl+C", "G", "S"],
            "correct": "Shift+A",
            "points": 10,
        },
        {
            "id": "b2",
            "text": "Что означает G в режиме редактирования?",
            "type": "single",
            "options": ["Grab (перемещение)", "Group", "Grid", "Gradient"],
            "correct": "Grab (перемещение)",
            "points": 10,
        },
        {
            "id": "b3",
            "text": "Как переключиться в режим редактирования?",
            "type": "single",
            "options": ["Tab", "E", "Ctrl+Tab", "F"],
            "correct": "Tab",
            "points": 10,
        },
        {
            "id": "b4",
            "text": "Какой рендер по умолчанию в Blender 3.x?",
            "type": "single",
            "options": ["Cycles", "Eevee", "Workbench", "LuxCore"],
            "correct": "Eevee",
            "points": 10,
        },
        {
            "id": "b5",
            "text": "S в режиме редактирования — это:",
            "type": "single",
            "options": ["Scale (масштаб)", "Select", "Save", "Smooth"],
            "correct": "Scale (масштаб)",
            "points": 10,
        },
    ],
}


def get_max_score(track):
    return sum(q["points"] for q in QUESTIONS.get(track, []))


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/start", methods=["POST"])
def start_attempt():
    """Начать попытку. Один раз на трек на участника."""
    data = request.get_json() or {}
    email = (data.get("email") or "").strip()
    name = (data.get("name") or "").strip()
    track = (data.get("track") or "").strip().lower()

    if not email or not name:
        return jsonify({"ok": False, "error": "Укажите имя и email."}), 400
    if track not in ("python", "blender"):
        return jsonify({"ok": False, "error": "Выберите трек: python или blender."}), 400

    participant = Participant.query.filter_by(email=email).first()
    if not participant:
        participant = Participant(email=email, name=name)
        db.session.add(participant)
        db.session.commit()

    if not participant.can_start_track(track):
        return jsonify({
            "ok": False,
            "error": "У вас уже была попытка по этому треку. Проход только один раз.",
        }), 403

    attempt = Attempt(
        participant_id=participant.id,
        track=track,
        max_score=get_max_score(track),
    )
    db.session.add(attempt)
    db.session.commit()

    session["attempt_id"] = attempt.id
    session["track"] = track
    session["started_at"] = attempt.started_at.isoformat()

    return jsonify({
        "ok": True,
        "attempt_id": attempt.id,
        "track": track,
        "time_limit_seconds": TIME_LIMITS[track],
        "started_at": attempt.started_at.isoformat(),
        "questions": QUESTIONS[track],
    })


@app.route("/api/submit", methods=["POST"])
def submit_attempt():
    """Отправить ответы и завершить попытку. Результат сохраняется в БД."""
    attempt_id = session.get("attempt_id")
    if not attempt_id:
        return jsonify({"ok": False, "error": "Нет активной попытки."}), 403

    attempt = Attempt.query.get(attempt_id)
    if not attempt or attempt.finished_at:
        return jsonify({"ok": False, "error": "Попытка уже завершена или не найдена."}), 403

    data = request.get_json() or {}
    answers = data.get("answers", {})
    time_spent_seconds = data.get("time_spent_seconds")

    # Подсчёт баллов
    questions = QUESTIONS.get(attempt.track, [])
    score = 0
    for q in questions:
        qid = q["id"]
        correct = q.get("correct")
        user_ans = answers.get(qid)
        if user_ans is not None and str(user_ans).strip() == str(correct).strip():
            score += q.get("points", 0)

    attempt.score = score
    attempt.max_score = get_max_score(attempt.track)
    attempt.finished_at = datetime.utcnow()
    attempt.time_spent_seconds = time_spent_seconds
    attempt.answers_json = json.dumps(answers, ensure_ascii=False)
    db.session.commit()

    session.pop("attempt_id", None)
    session.pop("track", None)
    session.pop("started_at", None)

    return jsonify({
        "ok": True,
        "score": score,
        "max_score": attempt.max_score,
        "time_spent_seconds": time_spent_seconds,
    })


@app.route("/olympiad")
def olympiad_page():
    return render_template("olympiad.html")


@app.route("/results")
def results_page():
    """Страница с последними результатами (для организаторов можно защитить)."""
    attempts = (
        Attempt.query.filter(Attempt.finished_at.isnot(None))
        .order_by(Attempt.finished_at.desc())
        .limit(100)
        .all()
    )
    rows = []
    for a in attempts:
        rows.append({
            "id": a.id,
            "name": a.participant.name,
            "email": a.participant.email,
            "track": a.track,
            "score": a.score,
            "max_score": a.max_score,
            "time_spent_seconds": a.time_spent_seconds,
            "finished_at": a.finished_at.isoformat() if a.finished_at else None,
        })
    return render_template("results.html", results=rows)


with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
