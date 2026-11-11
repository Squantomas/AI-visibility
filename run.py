"""Startet die Weboberfläche: python run.py"""
import uvicorn

from app.config import env

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=env("HOST", "127.0.0.1"), port=int(env("PORT", "8000") or 8000))
