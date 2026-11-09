import os
from datetime import date, datetime
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, Date, DateTime, Float, Integer, String, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./bookings.db")
PACKAGE_SERVICE_URL = os.getenv("PACKAGE_SERVICE_URL", "http://localhost:8003")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

STATUSES = {"pending", "confirmed", "cancelled", "completed"}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class Booking(Base):
    __tablename__ = "bookings1"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=False)
    package_id = Column(Integer, index=True, nullable=False)
    travelers = Column(Integer, nullable=False)
    travel_date = Column(Date, nullable=False)
    total_amount = Column(Float, nullable=False)
    status = Column(String(20), default="pending", index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(bind=engine)


class BookingCreate(BaseModel):
    user_id: int
    package_id: int
    travelers: int = Field(gt=0, le=50)
    travel_date: date


class StatusUpdate(BaseModel):
    status: str


class BookingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    package_id: int
    travelers: int
    travel_date: date
    total_amount: float
    status: str
    created_at: datetime


app = FastAPI(title="Northern Trails - Booking Service")


@app.get("/health")
def health():
    return {"service": "booking", "status": "ok"}


@app.post("/bookings", response_model=BookingOut, status_code=201)
def create_booking(body: BookingCreate, db: Session = Depends(get_db)):
    if body.travel_date < date.today():
        raise HTTPException(422, "travel_date must be in the future")
    try:
        r = httpx.get(f"{PACKAGE_SERVICE_URL}/packages/{body.package_id}", timeout=5)
    except httpx.HTTPError:
        raise HTTPException(502, "Travel package service unavailable")
    if r.status_code == 404:
        raise HTTPException(404, "Package not found")
    r.raise_for_status()
    pkg = r.json()
    if not pkg.get("is_active"):
        raise HTTPException(400, "Package is not available")
    if body.travelers > pkg["max_group_size"]:
        raise HTTPException(400, f"Max group size is {pkg['max_group_size']}")
    total = round(pkg["price_per_person"] * body.travelers, 2)
    obj = Booking(**body.model_dump(), total_amount=total)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@app.get("/bookings", response_model=list[BookingOut])
def list_bookings(user_id: Optional[int] = None, status: Optional[str] = None,
                  package_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(Booking)
    if user_id:
        q = q.filter(Booking.user_id == user_id)
    if status:
        q = q.filter(Booking.status == status)
    if package_id:
        q = q.filter(Booking.package_id == package_id)
    return q.order_by(Booking.id.desc()).all()


@app.get("/bookings/{booking_id}", response_model=BookingOut)
def get_booking(booking_id: int, db: Session = Depends(get_db)):
    obj = db.get(Booking, booking_id)
    if not obj:
        raise HTTPException(404, "Booking not found")
    return obj


@app.patch("/bookings/{booking_id}/status", response_model=BookingOut)
def set_status(booking_id: int, body: StatusUpdate, db: Session = Depends(get_db)):
    if body.status not in STATUSES:
        raise HTTPException(422, f"status must be one of {sorted(STATUSES)}")
    obj = db.get(Booking, booking_id)
    if not obj:
        raise HTTPException(404, "Booking not found")
    if obj.status == "cancelled":
        raise HTTPException(400, "Cancelled bookings cannot be changed")
    obj.status = body.status
    db.commit()
    db.refresh(obj)
    return obj


@app.delete("/bookings/{booking_id}", response_model=BookingOut)
def cancel_booking(booking_id: int, db: Session = Depends(get_db)):
    """Soft delete: marks the booking as cancelled."""
    obj = db.get(Booking, booking_id)
    if not obj:
        raise HTTPException(404, "Booking not found")
    obj.status = "cancelled"
    db.commit()
    db.refresh(obj)
    return obj
