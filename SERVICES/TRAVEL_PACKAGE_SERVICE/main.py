import os
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Boolean, Column, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./packages.db")
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


class TravelPackage(Base):
    __tablename__ = "travel_packages"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False, index=True)
    destination_id = Column(Integer, index=True, nullable=False)
    duration_days = Column(Integer, nullable=False)
    price_per_person = Column(Float, nullable=False)
    max_group_size = Column(Integer, default=20)
    difficulty = Column(String(30), default="easy")  # easy | moderate | hard
    inclusions = Column(Text)
    description = Column(Text)
    is_active = Column(Boolean, default=True)


Base.metadata.create_all(bind=engine)


class PackageBase(BaseModel):
    title: str
    destination_id: int
    duration_days: int = Field(gt=0)
    price_per_person: float = Field(ge=0)
    max_group_size: int = Field(default=20, gt=0)
    difficulty: str = "easy"
    inclusions: Optional[str] = None
    description: Optional[str] = None
    is_active: bool = True


class PackageUpdate(BaseModel):
    title: Optional[str] = None
    destination_id: Optional[int] = None
    duration_days: Optional[int] = Field(default=None, gt=0)
    price_per_person: Optional[float] = Field(default=None, ge=0)
    max_group_size: Optional[int] = Field(default=None, gt=0)
    difficulty: Optional[str] = None
    inclusions: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class PackageOut(PackageBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


app = FastAPI(title="Northern Trails - Travel Package Service")


@app.get("/health")
def health():
    return {"service": "travel-package", "status": "ok"}


@app.post("/packages", response_model=PackageOut, status_code=201)
def create(body: PackageBase, db: Session = Depends(get_db)):
    obj = TravelPackage(**body.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@app.get("/packages", response_model=list[PackageOut])
def list_all(destination_id: Optional[int] = None, min_price: Optional[float] = None,
             max_price: Optional[float] = None, max_days: Optional[int] = None,
             difficulty: Optional[str] = None, search: Optional[str] = None,
             active_only: bool = True, skip: int = 0, limit: int = Query(50, le=200),
             db: Session = Depends(get_db)):
    q = db.query(TravelPackage)
    if active_only:
        q = q.filter(TravelPackage.is_active.is_(True))
    if destination_id:
        q = q.filter(TravelPackage.destination_id == destination_id)
    if min_price is not None:
        q = q.filter(TravelPackage.price_per_person >= min_price)
    if max_price is not None:
        q = q.filter(TravelPackage.price_per_person <= max_price)
    if max_days is not None:
        q = q.filter(TravelPackage.duration_days <= max_days)
    if difficulty:
        q = q.filter(TravelPackage.difficulty == difficulty)
    if search:
        q = q.filter(TravelPackage.title.like(f"%{search}%"))
    return q.order_by(TravelPackage.id).offset(skip).limit(limit).all()


@app.get("/packages/{package_id}", response_model=PackageOut)
def get_one(package_id: int, db: Session = Depends(get_db)):
    obj = db.get(TravelPackage, package_id)
    if not obj:
        raise HTTPException(404, "Package not found")
    return obj


@app.put("/packages/{package_id}", response_model=PackageOut)
def update(package_id: int, body: PackageUpdate, db: Session = Depends(get_db)):
    obj = db.get(TravelPackage, package_id)
    if not obj:
        raise HTTPException(404, "Package not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


@app.delete("/packages/{package_id}", status_code=204)
def delete(package_id: int, db: Session = Depends(get_db)):
    obj = db.get(TravelPackage, package_id)
    if not obj:
        raise HTTPException(404, "Package not found")
    db.delete(obj)
    db.commit()
