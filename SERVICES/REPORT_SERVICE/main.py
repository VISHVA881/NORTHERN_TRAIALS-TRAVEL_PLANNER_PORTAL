import os
from collections import Counter, defaultdict
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException

BOOKING_SERVICE_URL = os.getenv("BOOKING_SERVICE_URL", "http://localhost:8006")
PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://localhost:8007")
REVIEW_SERVICE_URL = os.getenv("REVIEW_SERVICE_URL", "http://localhost:8012")

app = FastAPI(title="Northern Trails - Report Service")


def fetch(base: str, path: str, params: Optional[dict] = None) -> list[dict]:
    try:
        r = httpx.get(f"{base}{path}", params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Upstream service error ({base}): {e}")


@app.get("/health")
def health():
    return {"service": "report", "status": "ok"}


@app.get("/reports/bookings")
def booking_report():
    bookings = fetch(BOOKING_SERVICE_URL, "/bookings")
    by_status = Counter(b["status"] for b in bookings)
    per_package = defaultdict(lambda: {"bookings": 0, "travelers": 0, "value": 0.0})
    for b in bookings:
        if b["status"] == "cancelled":
            continue
        p = per_package[b["package_id"]]
        p["bookings"] += 1
        p["travelers"] += b["travelers"]
        p["value"] = round(p["value"] + b["total_amount"], 2)
    total = len(bookings)
    return {
        "total_bookings": total,
        "by_status": dict(by_status),
        "cancellation_rate": round(by_status.get("cancelled", 0) / total, 3) if total else 0,
        "by_package": dict(per_package),
    }


@app.get("/reports/revenue")
def revenue_report():
    payments = fetch(PAYMENT_SERVICE_URL, "/payments")
    kept = sum(p["amount"] for p in payments if p["status"] == "success")
    refunded = sum(p["amount"] for p in payments if p["status"] == "refunded")
    collected = kept + refunded  # gross = everything that was ever charged successfully
    by_method = defaultdict(float)
    by_month = defaultdict(float)
    for p in payments:
        if p["status"] == "success":
            by_method[p["method"]] += p["amount"]
            by_month[p["created_at"][:7]] += p["amount"]
    return {
        "gross_collected": round(collected, 2),
        "refunded": round(refunded, 2),
        "net_revenue": round(kept, 2),
        "by_method": {k: round(v, 2) for k, v in by_method.items()},
        "by_month": {k: round(v, 2) for k, v in sorted(by_month.items())},
    }


@app.get("/reports/packages/top")
def top_packages(limit: int = 5):
    bookings = fetch(BOOKING_SERVICE_URL, "/bookings")
    counts = Counter(b["package_id"] for b in bookings if b["status"] != "cancelled")
    out = []
    for package_id, n in counts.most_common(limit):
        try:
            r = httpx.get(f"{REVIEW_SERVICE_URL}/reviews/package/{package_id}/summary", timeout=5)
            rating = r.json().get("average_rating") if r.status_code == 200 else None
        except httpx.HTTPError:
            rating = None
        out.append({"package_id": package_id, "bookings": n, "average_rating": rating})
    return out


@app.get("/reports/dashboard")
def dashboard():
    return {"bookings": booking_report(), "revenue": revenue_report(),
            "top_packages": top_packages()}
