"""Payment Service  (port 8007)
Simulated payments. Replace `_charge` with a real gateway (Razorpay/Stripe) later.
Card numbers are never stored; only the method label and a transaction reference."""
import os
import uuid
from datetime import datetime
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, DateTime, Float, Integer, String, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./payments.db")
BOOKING_SERVICE_URL = os.getenv("BOOKING_SERVICE_URL", "http://localhost:8006")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

METHODS = {"card", "upi", "netbanking", "wallet"}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, index=True, nullable=False)
    user_id = Column(Integer, index=True, nullable=False)
    amount = Column(Float, nullable=False)
    method = Column(String(20), nullable=False)
    status = Column(String(20), default="pending", index=True)  # pending|success|failed|refunded
    transaction_ref = Column(String(64), unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(bind=engine)


class PaymentCreate(BaseModel):
    booking_id: int
    user_id: int
    method: str
    amount: Optional[float] = Field(default=None, gt=0, description="Defaults to booking total")


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    booking_id: int
    user_id: int
    amount: float
    method: str
    status: str
    transaction_ref: Optional[str]
    created_at: datetime


def _charge(amount: float, method: str) -> bool:
    """Stub gateway call. Always succeeds; plug a real provider in here."""
    return True


app = FastAPI(title="Northern Trails - Payment Service")


@app.get("/health")
def health():
    return {"service": "payment", "status": "ok"}


@app.post("/payments", response_model=PaymentOut, status_code=201)
def make_payment(body: PaymentCreate, db: Session = Depends(get_db)):
    if body.method not in METHODS:
        raise HTTPException(422, f"method must be one of {sorted(METHODS)}")
    try:
        r = httpx.get(f"{BOOKING_SERVICE_URL}/bookings/{body.booking_id}", timeout=5)
    except httpx.HTTPError:
        raise HTTPException(502, "Booking service unavailable")
    if r.status_code == 404:
        raise HTTPException(404, "Booking not found")
    booking = r.json()
    if booking["status"] == "cancelled":
        raise HTTPException(400, "Booking is cancelled")
    if db.query(Payment).filter_by(booking_id=body.booking_id, status="success").first():
        raise HTTPException(409, "Booking already paid")
    amount = body.amount or booking["total_amount"]
    ok = _charge(amount, body.method)
    pay = Payment(booking_id=body.booking_id, user_id=body.user_id, amount=amount,
                  method=body.method, status="success" if ok else "failed",
                  transaction_ref=uuid.uuid4().hex)
    db.add(pay)
    db.commit()
    db.refresh(pay)
    if ok:  # best effort: confirm the booking
        try:
            httpx.patch(f"{BOOKING_SERVICE_URL}/bookings/{body.booking_id}/status",
                        json={"status": "confirmed"}, timeout=5)
        except httpx.HTTPError:
            pass
    return pay


@app.get("/payments", response_model=list[PaymentOut])
def list_payments(user_id: Optional[int] = None, booking_id: Optional[int] = None,
                  status: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(Payment)
    if user_id:
        q = q.filter(Payment.user_id == user_id)
    if booking_id:
        q = q.filter(Payment.booking_id == booking_id)
    if status:
        q = q.filter(Payment.status == status)
    return q.order_by(Payment.id.desc()).all()


@app.get("/payments/{payment_id}", response_model=PaymentOut)
def get_payment(payment_id: int, db: Session = Depends(get_db)):
    p = db.get(Payment, payment_id)
    if not p:
        raise HTTPException(404, "Payment not found")
    return p


@app.post("/payments/{payment_id}/refund", response_model=PaymentOut)
def refund(payment_id: int, db: Session = Depends(get_db)):
    p = db.get(Payment, payment_id)
    if not p:
        raise HTTPException(404, "Payment not found")
    if p.status != "success":
        raise HTTPException(400, "Only successful payments can be refunded")
    p.status = "refunded"
    db.commit()
    db.refresh(p)
    return p
