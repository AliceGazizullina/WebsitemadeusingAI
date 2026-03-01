# -*- coding: utf-8 -*-
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SQLALCHEMY_DATABASE_URI = os.environ.get(
    "DATABASE_URL",
    f"sqlite:///{os.path.join(BASE_DIR, 'olympiad.db')}"
)
SQLALCHEMY_TRACK_MODIFICATIONS = False
SECRET_KEY = os.environ.get("SECRET_KEY", "olympiad-secret-key-change-in-production")
# Пароль администратора (для входа и просмотра результатов)
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")

# Время на прохождение в секундах (например, 45 минут)
PYTHON_TIME_LIMIT = 45 * 60
BLENDER_TIME_LIMIT = 60 * 60
