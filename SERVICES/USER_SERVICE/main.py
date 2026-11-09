import os
from datetime import datetime
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy import Column, DateTime, Integer, String, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./users.db")
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


class UserProfile(Base):
    __tablename__ = "user_profiles"
    id = Column(Integer, primary_key=True, index=True)
    auth_user_id = Column(Integer, unique=True, index=True, nullable=False)
    full_name = Column(String(150), nullable=False)
    email = Column(String(255), nullable=False)
    phone = Column(String(30))
    address = Column(String(255))
    city = Column(String(100))
    country = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(bind=engine)


class ProfileCreate(BaseModel):
    auth_user_id: int
    full_name: str
    email: EmailStr
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None


class ProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None


class ProfileOut(ProfileCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


app = FastAPI(title="Northern Trails - User Service")


@app.get("/health")
def health():
    return {"service": "user", "status": "ok"}


@app.post("/users", response_model=ProfileOut, status_code=201)
def create_profile(body: ProfileCreate, db: Session = Depends(get_db)):
    if db.query(UserProfile).filter_by(auth_user_id=body.auth_user_id).first():
        raise HTTPException(409, "Profile already exists for this auth user")
    obj = UserProfile(**body.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@app.get("/users", response_model=list[ProfileOut])
def list_profiles(skip: int = 0, limit: int = Query(50, le=200),
                  search: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(UserProfile)
    if search:
        like = f"%{search}%"
        q = q.filter(UserProfile.full_name.like(like) | UserProfile.email.like(like))
    return q.order_by(UserProfile.id).offset(skip).limit(limit).all()


@app.get("/users/{user_id}", response_model=ProfileOut)
def get_profile(user_id: int, db: Session = Depends(get_db)):
    obj = db.get(UserProfile, user_id)
    if not obj:
        raise HTTPException(404, "User not found")
    return obj


@app.get("/users/by-auth/{auth_user_id}", response_model=ProfileOut)
def get_by_auth(auth_user_id: int, db: Session = Depends(get_db)):
    obj = db.query(UserProfile).filter_by(auth_user_id=auth_user_id).first()
    if not obj:
        raise HTTPException(404, "User not found")
    return obj


@app.put("/users/{user_id}", response_model=ProfileOut)
def update_profile(user_id: int, body: ProfileUpdate, db: Session = Depends(get_db)):
    obj = db.get(UserProfile, user_id)
    if not obj:
        raise HTTPException(404, "User not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


@app.delete("/users/{user_id}", status_code=204)
def delete_profile(user_id: int, db: Session = Depends(get_db)):
    obj = db.get(UserProfile, user_id)
    if not obj:
        raise HTTPException(404, "User not found")
    db.delete(obj)
    db.commit()
