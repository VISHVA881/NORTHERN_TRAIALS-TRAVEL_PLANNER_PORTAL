import os
from datetime import datetime
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint, create_engine, func
from sqlalchemy.orm import Session, declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./reviews.db")
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


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (UniqueConstraint("user_id", "package_id", name="uq_user_package"),)
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=False)
    package_id = Column(Integer, index=True, nullable=False)
    rating = Column(Integer, nullable=False)
    title = Column(String(150))
    comment = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(bind=engine)


class ReviewCreate(BaseModel):
    user_id: int
    package_id: int
    rating: int = Field(ge=1, le=5)
    title: Optional[str] = None
    comment: Optional[str] = None


class ReviewUpdate(BaseModel):
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    title: Optional[str] = None
    comment: Optional[str] = None


class ReviewOut(ReviewCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


app = FastAPI(title="Northern Trails - Review Service")


@app.get("/health")
def health():
    return {"service": "review", "status": "ok"}


@app.post("/reviews", response_model=ReviewOut, status_code=201)
def create(body: ReviewCreate, db: Session = Depends(get_db)):
    if db.query(Review).filter_by(user_id=body.user_id, package_id=body.package_id).first():
        raise HTTPException(409, "You have already reviewed this package")
    r = Review(**body.model_dump())
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


@app.get("/reviews", response_model=list[ReviewOut])
def list_reviews(package_id: Optional[int] = None, user_id: Optional[int] = None,
                 min_rating: Optional[int] = Query(None, ge=1, le=5),
                 skip: int = 0, limit: int = Query(50, le=200), db: Session = Depends(get_db)):
    q = db.query(Review)
    if package_id:
        q = q.filter(Review.package_id == package_id)
    if user_id:
        q = q.filter(Review.user_id == user_id)
    if min_rating:
        q = q.filter(Review.rating >= min_rating)
    return q.order_by(Review.id.desc()).offset(skip).limit(limit).all()


@app.get("/reviews/package/{package_id}/summary")
def summary(package_id: int, db: Session = Depends(get_db)):
    count, avg = db.query(func.count(Review.id), func.avg(Review.rating)) \
                   .filter(Review.package_id == package_id).one()
    dist = dict(db.query(Review.rating, func.count(Review.id))
                  .filter(Review.package_id == package_id).group_by(Review.rating).all())
    return {"package_id": package_id, "review_count": count,
            "average_rating": round(float(avg), 2) if avg else None,
            "distribution": {str(i): dist.get(i, 0) for i in range(1, 6)}}


@app.get("/reviews/{review_id}", response_model=ReviewOut)
def get_one(review_id: int, db: Session = Depends(get_db)):
    r = db.get(Review, review_id)
    if not r:
        raise HTTPException(404, "Review not found")
    return r


@app.put("/reviews/{review_id}", response_model=ReviewOut)
def update(review_id: int, body: ReviewUpdate, db: Session = Depends(get_db)):
    r = db.get(Review, review_id)
    if not r:
        raise HTTPException(404, "Review not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(r, k, v)
    db.commit()
    db.refresh(r)
    return r


@app.delete("/reviews/{review_id}", status_code=204)
def delete(review_id: int, db: Session = Depends(get_db)):
    r = db.get(Review, review_id)
    if not r:
        raise HTTPException(404, "Review not found")
    db.delete(r)
    db.commit()
