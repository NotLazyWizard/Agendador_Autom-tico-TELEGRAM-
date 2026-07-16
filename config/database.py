from sqlalchemy import (
    create_engine, Column, Integer, String, Text,
    DateTime, Boolean, Enum as SAEnum
)
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import enum
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///database.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

def init_db():
    Base.metadata.create_all(engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

#guardar registros de audios recibidos en telegram

class AudioRecord(Base):
    __tablename__ = "audio_records"

    id = Column(Integer, primary_key=True, index=True)
    file_id = Column(String, unique=True, nullable=False)
    user_id = Column(Integer, nullable=False)
    username = Column(String, nullable=True)
    date_received = Column(DateTime, default=datetime.utcnow)
