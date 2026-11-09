import os
from datetime import datetime
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./notifications.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

CHANNELS = {"email", "sms", "in_app"}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=False)
    channel = Column(String(20), nullable=False)
    subject = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    status = Column(String(20), default="pending")  # pending | sent | failed
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(bind=engine)


class NotificationCreate(BaseModel):
    user_id: int
    channel: str = "in_app"
    subject: str
    message: str


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    channel: str
    subject: str
    message: str
    status: str
    is_read: bool
    created_at: datetime


def _deliver(n: Notification) -> bool:
    """Stub: hook up SMTP / an SMS provider here."""
    return True


app = FastAPI(title="Northern Trails - Notification Service")


@app.get("/health")
def health():
    return {"service": "notification", "status": "ok"}


@app.post("/notifications", response_model=NotificationOut, status_code=201)
def send(body: NotificationCreate, db: Session = Depends(get_db)):
    if body.channel not in CHANNELS:
        raise HTTPException(422, f"channel must be one of {sorted(CHANNELS)}")
    n = Notification(**body.model_dump())
    n.status = "sent" if _deliver(n) else "failed"
    db.add(n)
    db.commit()
    db.refresh(n)
    return n


@app.get("/notifications", response_model=list[NotificationOut])
def list_notifications(user_id: int, unread_only: bool = False, channel: Optional[str] = None,
                       db: Session = Depends(get_db)):
    q = db.query(Notification).filter(Notification.user_id == user_id)
    if unread_only:
        q = q.filter(Notification.is_read.is_(False))
    if channel:
        q = q.filter(Notification.channel == channel)
    return q.order_by(Notification.id.desc()).all()


@app.get("/notifications/{notif_id}", response_model=NotificationOut)
def get_one(notif_id: int, db: Session = Depends(get_db)):
    n = db.get(Notification, notif_id)
    if not n:
        raise HTTPException(404, "Notification not found")
    return n


@app.patch("/notifications/{notif_id}/read", response_model=NotificationOut)
def mark_read(notif_id: int, db: Session = Depends(get_db)):
    n = db.get(Notification, notif_id)
    if not n:
        raise HTTPException(404, "Notification not found")
    n.is_read = True
    db.commit()
    db.refresh(n)
    return n


@app.post("/notifications/read-all")
def mark_all_read(user_id: int, db: Session = Depends(get_db)):
    count = db.query(Notification).filter_by(user_id=user_id, is_read=False).update({"is_read": True})
    db.commit()
    return {"marked_read": count}


@app.delete("/notifications/{notif_id}", status_code=204)
def delete(notif_id: int, db: Session = Depends(get_db)):
    n = db.get(Notification, notif_id)
    if not n:
        raise HTTPException(404, "Notification not found")
    db.delete(n)
    db.commit()
