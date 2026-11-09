import os

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from jose import JWTError, jwt

SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret-in-production")  # same as auth service
ALGORITHM = "HS256"

SERVICES = {
    "auth": os.getenv("AUTH_URL", "http://localhost:8001"),
    "users": os.getenv("USER_URL", "http://localhost:8002"),
    "packages": os.getenv("PACKAGE_URL", "http://localhost:8003"),
    "destinations": os.getenv("DESTINATION_URL", "http://localhost:8004"),
    "trips": os.getenv("TRIP_URL", "http://localhost:8005"),
    "bookings": os.getenv("BOOKING_URL", "http://localhost:8006"),
    "payments": os.getenv("PAYMENT_URL", "http://localhost:8007"),
    "preferences": os.getenv("PREFERENCES_URL", "http://localhost:8008"),
    "schedules": os.getenv("SCHEDULE_URL", "http://localhost:8009"),
    "notifications": os.getenv("NOTIFICATION_URL", "http://localhost:8010"),
    "reports": os.getenv("REPORT_URL", "http://localhost:8011"),
    "reviews": os.getenv("REVIEW_URL", "http://localhost:8012"),
}

# Reachable without a token (method, service, path prefix). GETs on browse data are public.
PUBLIC_RULES = [
    ("POST", "auth", "auth/register"),
    ("POST", "auth", "auth/login"),
    ("GET", "packages", ""),
    ("GET", "destinations", ""),
    ("GET", "schedules", ""),
    ("GET", "reviews", ""),
]
ADMIN_ONLY = {"reports"}
HOP_BY_HOP = {"host", "content-length", "connection", "transfer-encoding"}

app = FastAPI(title="Northern Trails - API Gateway")
client = httpx.AsyncClient(timeout=15)


def is_public(method: str, service: str, path: str) -> bool:
    return any(method == m and service == s and path.startswith(p) for m, s, p in PUBLIC_RULES)


def verify(request: Request) -> dict:
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Missing bearer token")
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(401, "Invalid or expired token")


@app.get("/health")
async def health():
    """Gateway status plus a ping of every downstream service."""
    status = {}
    for name, base in SERVICES.items():
        try:
            r = await client.get(f"{base}/health", timeout=2)
            status[name] = "ok" if r.status_code == 200 else f"http {r.status_code}"
        except httpx.HTTPError:
            status[name] = "down"
    return {"gateway": "ok", "services": status}


@app.api_route("/api/{service}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(service: str, path: str, request: Request):
    base = SERVICES.get(service)
    if not base:
        raise HTTPException(404, f"Unknown service '{service}'")

    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}
    if not is_public(request.method, service, path):
        claims = verify(request)
        if service in ADMIN_ONLY and claims.get("role") != "admin":
            raise HTTPException(403, "Admin access required")
        headers["x-user-id"] = str(claims.get("sub"))
        headers["x-user-role"] = str(claims.get("role"))

    try:
        upstream = await client.request(request.method, f"{base}/{path}", params=request.query_params,
                                        content=await request.body(), headers=headers)
    except httpx.ConnectError:
        raise HTTPException(503, f"{service} service is unavailable")
    except httpx.TimeoutException:
        raise HTTPException(504, f"{service} service timed out")

    out_headers = {k: v for k, v in upstream.headers.items()
                   if k.lower() not in HOP_BY_HOP | {"content-encoding"}}
    return Response(upstream.content, status_code=upstream.status_code, headers=out_headers)
