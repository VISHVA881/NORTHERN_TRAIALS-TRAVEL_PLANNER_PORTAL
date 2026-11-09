"""Customer Preferences Service  (port 8008)
One preferences record per user (upsert)."""
import json
import os
from datetime import datetime
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./preferences.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class Preference(Base):
    __tablename__ = "customer_preferences"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, unique=True, index=True, nullable=False)
    travel_style = Column(String(50))          # adventure | relaxed | cultural | family
    preferred_season = Column(String(50))
    accommodation_type = Column(String(50))    # hotel | homestay | camping
    budget_min = Column(Float)
    budget_max = Column(Float)
    interests = Column(Text, default="[]")     # JSON list
    preferred_destination_ids = Column(Text, default="[]")  # JSON list
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


Base.metadata.create_all(bind=engine)


class PreferenceIn(BaseModel):
    travel_style: Optional[str] = None
    preferred_season: Optional[str] = None
    accommodation_type: Optional[str] = None
    budget_min: Optional[float] = Field(default=None, ge=0)
    budget_max: Optional[float] = Field(default=None, ge=0)
    interests: list[str] = []
    preferred_destination_ids: list[int] = []


class PreferenceOut(PreferenceIn):
    user_id: int
    updated_at: Optional[datetime] = None


def to_out(p: Preference) -> PreferenceOut:
    return PreferenceOut(
        user_id=p.user_id, travel_style=p.travel_style, preferred_season=p.preferred_season,
        accommodation_type=p.accommodation_type, budget_min=p.budget_min, budget_max=p.budget_max,
        interests=json.loads(p.interests or "[]"),
        preferred_destination_ids=json.loads(p.preferred_destination_ids or "[]"),
        updated_at=p.updated_at)


app = FastAPI(title="Northern Trails - Customer Preferences Service")


@app.get("/health")
def health():
    return {"service": "customer-preferences", "status": "ok"}


@app.put("/preferences/{user_id}", response_model=PreferenceOut)
def upsert(user_id: int, body: PreferenceIn, db: Session = Depends(get_db)):
    if body.budget_min is not None and body.budget_max is not None and body.budget_max < body.budget_min:
        raise HTTPException(422, "budget_max must be >= budget_min")
    p = db.query(Preference).filter_by(user_id=user_id).first() or Preference(user_id=user_id)
    data = body.model_dump()
    p.interests = json.dumps(data.pop("interests"))
    p.preferred_destination_ids = json.dumps(data.pop("preferred_destination_ids"))
    for k, v in data.items():
        setattr(p, k, v)
    db.add(p)
    db.commit()
    db.refresh(p)
    return to_out(p)


@app.get("/preferences/{user_id}", response_model=PreferenceOut)
def get_pref(user_id: int, db: Session = Depends(get_db)):
    p = db.query(Preference).filter_by(user_id=user_id).first()
    if not p:
        raise HTTPException(404, "No preferences saved for this user")
    return to_out(p)


@app.delete("/preferences/{user_id}", status_code=204)
def delete_pref(user_id: int, db: Session = Depends(get_db)):
    p = db.query(Preference).filter_by(user_id=user_id).first()
    if not p:
        raise HTTPException(404, "No preferences saved for this user")
    db.delete(p)
    db.commit()
