import os
from datetime import date
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, Date, Integer, String, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./schedules.db")
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


class Departure(Base):
    __tablename__ = "departures"
    id = Column(Integer, primary_key=True, index=True)
    package_id = Column(Integer, index=True, nullable=False)
    departure_date = Column(Date, nullable=False, index=True)
    return_date = Column(Date, nullable=False)
    seats_total = Column(Integer, nullable=False)
    seats_booked = Column(Integer, default=0, nullable=False)
    status = Column(String(20), default="open")  # open | full | cancelled


Base.metadata.create_all(bind=engine)


class DepartureCreate(BaseModel):
    package_id: int
    departure_date: date
    return_date: date
    seats_total: int = Field(gt=0)


class DepartureUpdate(BaseModel):
    departure_date: Optional[date] = None
    return_date: Optional[date] = None
    seats_total: Optional[int] = Field(default=None, gt=0)
    status: Optional[str] = None


class SeatsIn(BaseModel):
    seats: int = Field(gt=0)


class DepartureOut(DepartureCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    seats_booked: int
    seats_available: int = 0
    status: str


def to_out(d: Departure) -> DepartureOut:
    return DepartureOut(id=d.id, package_id=d.package_id, departure_date=d.departure_date,
                        return_date=d.return_date, seats_total=d.seats_total,
                        seats_booked=d.seats_booked,
                        seats_available=d.seats_total - d.seats_booked, status=d.status)


app = FastAPI(title="Northern Trails - Schedule Service")


def _get(db: Session, dep_id: int) -> Departure:
    d = db.get(Departure, dep_id)
    if not d:
        raise HTTPException(404, "Departure not found")
    return d


@app.get("/health")
def health():
    return {"service": "schedule", "status": "ok"}


@app.post("/schedules", response_model=DepartureOut, status_code=201)
def create(body: DepartureCreate, db: Session = Depends(get_db)):
    if body.return_date < body.departure_date:
        raise HTTPException(422, "return_date cannot be before departure_date")
    d = Departure(**body.model_dump())
    db.add(d)
    db.commit()
    db.refresh(d)
    return to_out(d)


@app.get("/schedules", response_model=list[DepartureOut])
def list_all(package_id: Optional[int] = None, from_date: Optional[date] = None,
             available_only: bool = False, db: Session = Depends(get_db)):
    q = db.query(Departure)
    if package_id:
        q = q.filter(Departure.package_id == package_id)
    if from_date:
        q = q.filter(Departure.departure_date >= from_date)
    if available_only:
        q = q.filter(Departure.status == "open")
    return [to_out(d) for d in q.order_by(Departure.departure_date).all()]


@app.get("/schedules/{dep_id}", response_model=DepartureOut)
def get_one(dep_id: int, db: Session = Depends(get_db)):
    return to_out(_get(db, dep_id))


@app.put("/schedules/{dep_id}", response_model=DepartureOut)
def update(dep_id: int, body: DepartureUpdate, db: Session = Depends(get_db)):
    d = _get(db, dep_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(d, k, v)
    if d.seats_total < d.seats_booked:
        raise HTTPException(422, "seats_total cannot be below seats already booked")
    db.commit()
    db.refresh(d)
    return to_out(d)


@app.post("/schedules/{dep_id}/reserve", response_model=DepartureOut)
def reserve(dep_id: int, body: SeatsIn, db: Session = Depends(get_db)):
    d = _get(db, dep_id)
    if d.status != "open":
        raise HTTPException(400, f"Departure is {d.status}")
    if d.seats_total - d.seats_booked < body.seats:
        raise HTTPException(409, "Not enough seats available")
    d.seats_booked += body.seats
    if d.seats_booked == d.seats_total:
        d.status = "full"
    db.commit()
    db.refresh(d)
    return to_out(d)


@app.post("/schedules/{dep_id}/release", response_model=DepartureOut)
def release(dep_id: int, body: SeatsIn, db: Session = Depends(get_db)):
    d = _get(db, dep_id)
    d.seats_booked = max(0, d.seats_booked - body.seats)
    if d.status == "full":
        d.status = "open"
    db.commit()
    db.refresh(d)
    return to_out(d)


@app.delete("/schedules/{dep_id}", status_code=204)
def delete(dep_id: int, db: Session = Depends(get_db)):
    db.delete(_get(db, dep_id))
    db.commit()
