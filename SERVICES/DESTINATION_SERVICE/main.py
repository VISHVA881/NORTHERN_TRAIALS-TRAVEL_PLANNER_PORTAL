"""Destination Service  (port 8004)
Places that travel packages and trips can reference."""
import os
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Boolean, Column, Integer, String, Text, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./destinations.db")
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


class Destination(Base):
    __tablename__ = "destinations"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False, index=True)
    country = Column(String(100), nullable=False, index=True)
    region = Column(String(100))
    description = Column(Text)
    best_season = Column(String(100))
    image_url = Column(String(500))
    is_active = Column(Boolean, default=True)


Base.metadata.create_all(bind=engine)


class DestinationBase(BaseModel):
    name: str
    country: str
    region: Optional[str] = None
    description: Optional[str] = None
    best_season: Optional[str] = None
    image_url: Optional[str] = None
    is_active: bool = True


class DestinationUpdate(BaseModel):
    name: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    description: Optional[str] = None
    best_season: Optional[str] = None
    image_url: Optional[str] = None
    is_active: Optional[bool] = None


class DestinationOut(DestinationBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


app = FastAPI(title="Northern Trails - Destination Service")


@app.get("/health")
def health():
    return {"service": "destination", "status": "ok"}


@app.post("/destinations", response_model=DestinationOut, status_code=201)
def create(body: DestinationBase, db: Session = Depends(get_db)):
    obj = Destination(**body.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@app.get("/destinations", response_model=list[DestinationOut])
def list_all(country: Optional[str] = None, region: Optional[str] = None,
             search: Optional[str] = None, active_only: bool = True,
             skip: int = 0, limit: int = Query(50, le=200), db: Session = Depends(get_db)):
    q = db.query(Destination)
    if active_only:
        q = q.filter(Destination.is_active.is_(True))
    if country:
        q = q.filter(Destination.country == country)
    if region:
        q = q.filter(Destination.region == region)
    if search:
        q = q.filter(Destination.name.like(f"%{search}%"))
    return q.order_by(Destination.name).offset(skip).limit(limit).all()


@app.get("/destinations/{dest_id}", response_model=DestinationOut)
def get_one(dest_id: int, db: Session = Depends(get_db)):
    obj = db.get(Destination, dest_id)
    if not obj:
        raise HTTPException(404, "Destination not found")
    return obj


@app.put("/destinations/{dest_id}", response_model=DestinationOut)
def update(dest_id: int, body: DestinationUpdate, db: Session = Depends(get_db)):
    obj = db.get(Destination, dest_id)
    if not obj:
        raise HTTPException(404, "Destination not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


@app.delete("/destinations/{dest_id}", status_code=204)
def delete(dest_id: int, db: Session = Depends(get_db)):
    obj = db.get(Destination, dest_id)
    if not obj:
        raise HTTPException(404, "Destination not found")
    db.delete(obj)
    db.commit()
