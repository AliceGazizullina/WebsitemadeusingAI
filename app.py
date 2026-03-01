# -*- coding: utf-8 -*-
import json
import os
from datetime import datetime
from flask import Flask, request, jsonify, render_template, session, redirect, url_for, send_from_directory
from config import (
    SQLALCHEMY_DATABASE_URI,
    SQLALCHEMY_TRACK_MODIFICATIONS,
    SECRET_KEY,
    ADMIN_PASSWORD,
    PYTHON_TIME_LIMIT,
    BLENDER_TIME_LIMIT,
)
from models import db, Participant, Attempt
from data.questions import QUESTIONS

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = SQLALCHEMY_DATABASE_URI
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = SQLALCHEMY_TRACK_MODIFICATIONS
app.config["SECRET_KEY"] = SECRET_KEY
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB max per file
db.init_app(app)

TIME_LIMITS = {"python": PYTHON_TIME_LIMIT, "blender": BLENDER_TIME_LIMIT}
QUESTIONS_PER_PAGE = 10


def is_admin():
    return session.get("admin") is True


def _normalize_answer(val):
    if val is None:
        return ""
    s = str(val).strip()
    return s


def get_max_score(track):
    return sum(q["points"] for q in QUESTIONS.get(track, []))


@app.context_processor
def inject_admin():
    """Чтобы во всех шаблонах была переменная is_admin."""
    return {"is_admin": is_admin()}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "GET":
        if is_admin():
            return redirect(url_for("results_page"))
        return render_template("admin_login.html")
    password = (request.form.get("password") or "").strip()
    if password == ADMIN_PASSWORD:
        session["admin"] = True
        return redirect(url_for("results_page"))
    return render_template("admin_login.html", error="Неверный пароль.")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("index"))


@app.route("/api/check-tracks", methods=["POST"])
def check_tracks():
    """По email вернуть, какие треки ещё можно пройти (один раз Python, один раз Blender на аккаунт)."""
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    if not email:
        return jsonify({"python": True, "blender": True})
    participant = Participant.query.filter_by(email=email).first()
    if not participant:
        return jsonify({"python": True, "blender": True})
    return jsonify({
        "python": participant.can_start_track("python"),
        "blender": participant.can_start_track("blender"),
    })


@app.route("/api/start", methods=["POST"])
def start_attempt():
    """Начать попытку. Один раз на трек на участника."""
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
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
        "questions_per_page": QUESTIONS_PER_PAGE,
    })


def _check_text_answer(user_val, correct_val):
    u = _normalize_answer(user_val)
    c = _normalize_answer(correct_val)
    if u == c:
        return True
    if u.lower() == c.lower():
        return True
    return False


@app.route("/api/submit", methods=["POST"])
def submit_attempt():
    """Отправить ответы и завершить попытку. Результат сохраняется в БД. Поддерживает JSON и multipart (для файлов)."""
    attempt_id = session.get("attempt_id")
    if not attempt_id:
        return jsonify({"ok": False, "error": "Нет активной попытки."}), 403

    attempt = Attempt.query.get(attempt_id)
    if not attempt or attempt.finished_at:
        return jsonify({"ok": False, "error": "Попытка уже завершена или не найдена."}), 403

    if request.content_type and "multipart/form-data" in request.content_type:
        answers = {}
        try:
            raw = request.form.get("answers")
            if raw:
                answers = json.loads(raw)
        except (ValueError, TypeError):
            pass
        time_spent_seconds = request.form.get("time_spent_seconds", type=int) or 0
        questions = QUESTIONS.get(attempt.track, [])
        upload_dir = os.path.join(app.config["UPLOAD_FOLDER"], str(attempt_id))
        for q in questions:
            if q.get("type") == "file" and q.get("id"):
                qid = q["id"]
                f = request.files.get(qid)
                if f and f.filename:
                    os.makedirs(upload_dir, exist_ok=True)
                    safe_name = f.filename.replace("..", "").strip() or "file"
                    if len(safe_name) > 100:
                        safe_name = safe_name[-100:]
                    path = os.path.join(upload_dir, safe_name)
                    f.save(path)
                    rel = os.path.join(str(attempt_id), safe_name)
                    answers[qid] = rel
    else:
        data = request.get_json() or {}
        answers = data.get("answers", {})
        time_spent_seconds = data.get("time_spent_seconds")

    questions = QUESTIONS.get(attempt.track, [])
    score = 0
    for q in questions:
        qid = q["id"]
        qtype = q.get("type", "single")
        correct = q.get("correct")
        user_ans = answers.get(qid)
        if qtype == "single":
            if user_ans is not None and _normalize_answer(user_ans) == _normalize_answer(correct):
                score += q.get("points", 0)
        elif qtype == "text":
            if user_ans is not None and _check_text_answer(user_ans, correct):
                score += q.get("points", 0)
        elif qtype == "file":
            if user_ans and str(user_ans).strip():
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


@app.route("/uploads/<path:filename>")
def upload_file(filename):
    """Скачать загруженный файл (только для администратора)."""
    if not is_admin():
        return redirect(url_for("admin_login"))
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename, as_attachment=True)


@app.route("/results")
def results_page():
    """Страница с последними результатами — только для администратора."""
    if not is_admin():
        return redirect(url_for("admin_login"))
    attempts = (
        Attempt.query.filter(Attempt.finished_at.isnot(None))
        .order_by(Attempt.finished_at.desc())
        .limit(100)
        .all()
    )
    rows = []
    for a in attempts:
        upload_path = None
        if a.answers_json and a.track == "blender":
            try:
                ans = json.loads(a.answers_json)
                upload_path = ans.get("b100", "").strip() or None
            except (ValueError, TypeError):
                pass
        rows.append({
            "id": a.id,
            "name": a.participant.name,
            "email": a.participant.email,
            "track": a.track,
            "score": a.score,
            "max_score": a.max_score,
            "time_spent_seconds": a.time_spent_seconds,
            "finished_at": a.finished_at.isoformat() if a.finished_at else None,
            "upload_path": upload_path,
        })
    return render_template("results.html", results=rows)


with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
