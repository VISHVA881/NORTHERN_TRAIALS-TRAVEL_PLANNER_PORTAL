import os
from datetime import date, datetime
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./trips.db")
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


class Trip(Base):
    __tablename__ = "trips"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=False)
    name = Column(String(200), nullable=False)
    start_date = Column(Date)
    end_date = Column(Date)
    status = Column(String(20), default="draft")  # draft | planned | completed
    created_at = Column(DateTime, default=datetime.utcnow)
    items = relationship("TripItem", back_populates="trip", cascade="all, delete-orphan",
                         order_by="TripItem.day_number")


class TripItem(Base):
    __tablename__ = "trip_items"
    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id"), nullable=False, index=True)
    day_number = Column(Integer, nullable=False)
    title = Column(String(200), nullable=False)
    destination_id = Column(Integer)
    notes = Column(Text)
    trip = relationship("Trip", back_populates="items")


Base.metadata.create_all(bind=engine)


class ItemBase(BaseModel):
    day_number: int = Field(gt=0)
    title: str
    destination_id: Optional[int] = None
    notes: Optional[str] = None


class ItemOut(ItemBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    trip_id: int


class TripCreate(BaseModel):
    user_id: int
    name: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class TripUpdate(BaseModel):
    name: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: Optional[str] = None


class TripOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    name: str
    start_date: Optional[date]
    end_date: Optional[date]
    status: str
    created_at: datetime
    items: list[ItemOut] = []


app = FastAPI(title="Northern Trails - Trip Planner Service")


def _trip(db: Session, trip_id: int) -> Trip:
    t = db.get(Trip, trip_id)
    if not t:
        raise HTTPException(404, "Trip not found")
    return t


@app.get("/health")
def health():
    return {"service": "trip-planner", "status": "ok"}


@app.post("/trips", response_model=TripOut, status_code=201)
def create_trip(body: TripCreate, db: Session = Depends(get_db)):
    if body.start_date and body.end_date and body.end_date < body.start_date:
        raise HTTPException(422, "end_date cannot be before start_date")
    t = Trip(**body.model_dump())
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@app.get("/trips", response_model=list[TripOut])
def list_trips(user_id: Optional[int] = None, status: Optional[str] = None,
               db: Session = Depends(get_db)):
    q = db.query(Trip)
    if user_id:
        q = q.filter(Trip.user_id == user_id)
    if status:
        q = q.filter(Trip.status == status)
    return q.order_by(Trip.id.desc()).all()


@app.get("/trips/{trip_id}", response_model=TripOut)
def get_trip(trip_id: int, db: Session = Depends(get_db)):
    return _trip(db, trip_id)


@app.put("/trips/{trip_id}", response_model=TripOut)
def update_trip(trip_id: int, body: TripUpdate, db: Session = Depends(get_db)):
    t = _trip(db, trip_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(t, k, v)
    db.commit()
    db.refresh(t)
    return t


@app.delete("/trips/{trip_id}", status_code=204)
def delete_trip(trip_id: int, db: Session = Depends(get_db)):
    db.delete(_trip(db, trip_id))
    db.commit()


@app.post("/trips/{trip_id}/items", response_model=ItemOut, status_code=201)
def add_item(trip_id: int, body: ItemBase, db: Session = Depends(get_db)):
    _trip(db, trip_id)
    item = TripItem(trip_id=trip_id, **body.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@app.put("/trips/{trip_id}/items/{item_id}", response_model=ItemOut)
def update_item(trip_id: int, item_id: int, body: ItemBase, db: Session = Depends(get_db)):
    item = db.get(TripItem, item_id)
    if not item or item.trip_id != trip_id:
        raise HTTPException(404, "Item not found")
    for k, v in body.model_dump().items():
        setattr(item, k, v)
    db.commit()
    db.refresh(item)
    return item


@app.delete("/trips/{trip_id}/items/{item_id}", status_code=204)
def delete_item(trip_id: int, item_id: int, db: Session = Depends(get_db)):
    item = db.get(TripItem, item_id)
    if not item or item.trip_id != trip_id:
        raise HTTPException(404, "Item not found")
    db.delete(item)
    db.commit()
