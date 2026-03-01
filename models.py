# -*- coding: utf-8 -*-
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask import current_app

db = SQLAlchemy()


class Participant(db.Model):
    """Участник: один проход только с одного раза по каждому треку."""
    __tablename__ = "participants"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Одна попытка на трек: связь с попытками
    attempts = db.relationship("Attempt", backref="participant", lazy="dynamic")

    def can_start_track(self, track):
        """Можно ли начать этот трек (ещё не было попытки)."""
        return not self.attempts.filter_by(track=track).first()

    def get_attempt(self, track):
        return self.attempts.filter_by(track=track).first()


class Attempt(db.Model):
    """Одна попытка прохождения олимпиады (один трек, один раз)."""
    __tablename__ = "attempts"
    id = db.Column(db.Integer, primary_key=True)
    participant_id = db.Column(db.Integer, db.ForeignKey("participants.id"), nullable=False)
    track = db.Column(db.String(32), nullable=False)  # "python" | "blender"
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime, nullable=True)
    # Сколько секунд потратил (от начала до отправки)
    time_spent_seconds = db.Column(db.Integer, nullable=True)
    # Баллы за попытку
    score = db.Column(db.Integer, default=0)
    max_score = db.Column(db.Integer, default=0)
    # JSON с ответами/результатами для отчётов
    answers_json = db.Column(db.Text, nullable=True)

    __table_args__ = (
        db.UniqueConstraint("participant_id", "track", name="uq_participant_track"),
    )
