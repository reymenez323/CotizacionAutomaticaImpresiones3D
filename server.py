import json
import math
import os
import re
import shutil
import smtplib
import sqlite3
import subprocess
import tempfile
import time
import uuid
import hmac
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from email.message import EmailMessage

import numpy as np
import trimesh
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse


APP_DIR = Path(__file__).resolve().parent

PRUSASLICER_PATH = os.environ.get("PRUSASLICER_PATH", "prusa-slicer")
PRUSASLICER_PROFILE = os.environ.get("PRUSASLICER_PROFILE", "")

BED_X = 256.0
BED_Y = 256.0
BED_Z = 256.0
PACKING_GAP_MM = 8.0

# Material pricing/density is stored in the database.
# Do not hardcode material characteristics here.
FILAMENT_DIAMETER_MM = 1.75

MACHINE_PRICE_PER_HOUR = 30.0
PROFIT_MULTIPLIER = 1.6
ELECTRICITY_RATE_PER_KWH = 8.59
PRINTER_AVERAGE_POWER_KW = 0.35
SETUP_COST_PER_PLATE = 100.0
MINIMUM_QUOTE = 150.0



DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", APP_DIR / "data" / "prototiposrd.db"))
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", APP_DIR / "data" / "uploads"))
SEED_MATERIALS_PATH = Path(os.environ.get("SEED_MATERIALS_PATH", APP_DIR / "seed_materials.sql"))
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER or "no-reply@prototiposrd.com")
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"
ADMIN_NOTIFICATION_EMAIL = os.environ.get("ADMIN_NOTIFICATION_EMAIL", "")

ENVIRONMENT = os.environ.get("ENVIRONMENT", "development").lower()
ALLOWED_ORIGINS = [
    origin.strip().rstrip("/")
    for origin in os.environ.get("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("ALLOWED_HOSTS", "").split(",")
    if host.strip()
]

MAX_UPLOAD_MB = float(os.environ.get("MAX_UPLOAD_MB", "50"))
MAX_REQUEST_BODY_MB = float(os.environ.get("MAX_REQUEST_BODY_MB", "250"))
MAX_FILES_PER_REQUEST = int(os.environ.get("MAX_FILES_PER_REQUEST", "20"))

ALLOWED_FILE_EXTENSIONS = {".stl", ".obj", ".3mf", ".step", ".stp"}
ALLOWED_FILE_CONTENT_TYPES = {
    "",
    "application/octet-stream",
    "application/sla",
    "model/stl",
    "model/obj",
    "application/vnd.ms-3mfdocument",
    "application/zip",
}

RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60"))
RATE_LIMIT_DEFAULT = int(os.environ.get("RATE_LIMIT_DEFAULT", "180"))
RATE_LIMIT_QUOTE = int(os.environ.get("RATE_LIMIT_QUOTE", "20"))
RATE_LIMIT_SLICE = int(os.environ.get("RATE_LIMIT_SLICE", "40"))
RATE_LIMIT_ADMIN = int(os.environ.get("RATE_LIMIT_ADMIN", "90"))
RATE_LIMIT_CORRECTION = int(os.environ.get("RATE_LIMIT_CORRECTION", "20"))

_rate_limit_store: dict[str, list[float]] = {}


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit_bucket(request: Request) -> tuple[str, int]:
    path = request.url.path

    if path.startswith("/api/slice-batch"):
        return "slice", RATE_LIMIT_SLICE
    if path.startswith("/api/quote-requests"):
        return "quote", RATE_LIMIT_QUOTE
    if path.startswith("/api/corrections"):
        return "correction", RATE_LIMIT_CORRECTION
    if path.startswith("/api/admin"):
        return "admin", RATE_LIMIT_ADMIN

    return "default", RATE_LIMIT_DEFAULT


def check_rate_limit(request: Request) -> tuple[bool, int]:
    bucket, limit = rate_limit_bucket(request)
    ip = client_ip(request)
    key = f"{bucket}:{ip}"
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW_SECONDS

    history = _rate_limit_store.get(key, [])
    history = [stamp for stamp in history if stamp >= window_start]

    if len(history) >= limit:
        retry_after = max(1, int(RATE_LIMIT_WINDOW_SECONDS - (now - history[0])))
        _rate_limit_store[key] = history
        return False, retry_after

    history.append(now)
    _rate_limit_store[key] = history
    return True, 0


def same_origin_allowed(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return True

    origin = origin.rstrip("/")

    if ALLOWED_ORIGINS and origin in ALLOWED_ORIGINS:
        return True

    host = request.headers.get("host", "")
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    same_origin = f"{scheme}://{host}".rstrip("/")

    return origin == same_origin


def secure_filename(filename: str) -> str:
    name = Path(filename or "archivo").name
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip()
    name = name[:120] or "archivo"
    return name


def validate_upload_filename(filename: str) -> str:
    safe = secure_filename(filename)
    extension = Path(safe).suffix.lower()

    if extension not in ALLOWED_FILE_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Formato no permitido: {extension}. Usa STL, OBJ, 3MF, STEP o STP.",
        )

    return safe


def validate_upload_content(content: bytes, filename: str, content_type: str = "") -> None:
    validate_upload_filename(filename)

    if len(content) <= 0:
        raise HTTPException(status_code=400, detail=f"{filename}: archivo vacío.")

    max_bytes = int(MAX_UPLOAD_MB * 1024 * 1024)
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"{filename}: excede el máximo permitido de {MAX_UPLOAD_MB:.0f} MB.",
        )

    if content_type and content_type not in ALLOWED_FILE_CONTENT_TYPES:
        # Browsers often send application/octet-stream, so this is intentionally permissive.
        print(f"[security] Content-Type no típico para {filename}: {content_type}", flush=True)


def validate_file_count(files: list[UploadFile]) -> None:
    if len(files) > MAX_FILES_PER_REQUEST:
        raise HTTPException(
            status_code=413,
            detail=f"Demasiados archivos. Máximo permitido: {MAX_FILES_PER_REQUEST}.",
        )


def validate_email(value: str) -> str:
    email = (value or "").strip().lower()
    if len(email) > 254 or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(status_code=400, detail="Correo electrónico inválido.")
    return email


def validate_phone(value: str) -> str:
    phone = (value or "").strip()
    digits = re.sub(r"\D+", "", phone)
    if len(digits) < 7 or len(digits) > 20:
        raise HTTPException(status_code=400, detail="Teléfono inválido.")
    return phone[:40]


def clean_text(value: str, max_len: int = 500) -> str:
    value = (value or "").strip()
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]+", "", value)
    return value[:max_len]


def validate_customer_data(name: str, email: str, phone: str, notes: str) -> tuple[str, str, str, str]:
    return (
        clean_text(name, 120),
        validate_email(email),
        validate_phone(phone),
        clean_text(notes, 2000),
    )


def validate_commitment_date(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        raise HTTPException(status_code=400, detail="Fecha compromiso inválida.")
    return value


def safe_upload_path(relative_path: str) -> Path:
    base = UPLOAD_DIR.resolve()
    target = (UPLOAD_DIR / relative_path).resolve()

    if base not in target.parents and target != base:
        raise HTTPException(status_code=403, detail="Ruta de archivo no permitida.")

    return target


def get_db() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn



def seed_material_catalog_if_empty(conn: sqlite3.Connection) -> None:
    existing = conn.execute("SELECT COUNT(*) AS total FROM material_catalog").fetchone()

    if existing and int(existing["total"]) > 0:
        return

    if not SEED_MATERIALS_PATH.exists():
        print("[materials] No seed_materials.sql found; material catalog starts empty.", flush=True)
        return

    sql = SEED_MATERIALS_PATH.read_text(encoding="utf-8")
    conn.executescript(sql)
    print("[materials] Initial material catalog loaded from seed_materials.sql.", flush=True)


def init_db() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS quote_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_code TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'new',
                customer_name TEXT,
                customer_email TEXT NOT NULL,
                customer_phone TEXT NOT NULL,
                customer_notes TEXT,
                quote_metadata TEXT NOT NULL,
                quote_result TEXT NOT NULL,
                total_price REAL NOT NULL,
                total_pieces INTEGER NOT NULL,
                total_plates INTEGER NOT NULL,
                total_print_hours REAL NOT NULL,
                total_filament_grams REAL NOT NULL,
                correction_token TEXT,
                correction_reason TEXT,
                correction_requested_at TEXT,
                commitment_date TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS quote_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER NOT NULL,
                original_filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL,
                content_type TEXT,
                size_bytes INTEGER NOT NULL,
                source TEXT NOT NULL DEFAULT 'original',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (request_id) REFERENCES quote_requests(id)
            );

            CREATE TABLE IF NOT EXISTS quote_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                actor TEXT NOT NULL DEFAULT 'system',
                note TEXT,
                from_status TEXT,
                to_status TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (request_id) REFERENCES quote_requests(id)
            );

            CREATE TABLE IF NOT EXISTS material_catalog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                material_key TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                description TEXT,
                price_per_gram REAL NOT NULL DEFAULT 2.0,
                density_g_cm3 REAL NOT NULL DEFAULT 1.24,
                density_factor REAL NOT NULL DEFAULT 1.0,
                is_active INTEGER NOT NULL DEFAULT 1,
                is_out_of_stock INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS material_colors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                material_id INTEGER NOT NULL,
                color_name TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                is_out_of_stock INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(material_id, color_name),
                FOREIGN KEY (material_id) REFERENCES material_catalog(id)
            );
            """
        )



        existing_request_cols = {
            row["name"] for row in conn.execute("PRAGMA table_info(quote_requests)").fetchall()
        }
        if "correction_token" not in existing_request_cols:
            conn.execute("ALTER TABLE quote_requests ADD COLUMN correction_token TEXT")
        if "correction_reason" not in existing_request_cols:
            conn.execute("ALTER TABLE quote_requests ADD COLUMN correction_reason TEXT")
        if "correction_requested_at" not in existing_request_cols:
            conn.execute("ALTER TABLE quote_requests ADD COLUMN correction_requested_at TEXT")
        if "commitment_date" not in existing_request_cols:
            conn.execute("ALTER TABLE quote_requests ADD COLUMN commitment_date TEXT")

        existing_file_cols = {
            row["name"] for row in conn.execute("PRAGMA table_info(quote_files)").fetchall()
        }
        if "source" not in existing_file_cols:
            conn.execute("ALTER TABLE quote_files ADD COLUMN source TEXT NOT NULL DEFAULT 'original'")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_quote_requests_correction_token ON quote_requests(correction_token)")
        seed_material_catalog_if_empty(conn)


def require_admin(request: Request) -> None:
    supplied = request.headers.get("X-Admin-Password", "")
    if not ADMIN_PASSWORD or not hmac.compare_digest(str(supplied), str(ADMIN_PASSWORD)):
        raise HTTPException(status_code=401, detail="No autorizado")


def row_to_dict(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}


def request_to_public_dict(row: sqlite3.Row, files: list[dict], logs: list[dict]) -> dict:
    data = row_to_dict(row)

    for field in ["quote_metadata", "quote_result"]:
        try:
            data[field] = json.loads(data[field])
        except Exception:
            data[field] = {}

    data["files"] = files
    data["logs"] = logs
    return data


def save_upload_file_for_request(
    conn: sqlite3.Connection,
    request_id: int,
    request_code: str,
    upload: UploadFile,
    source: str = "original",
) -> dict:
    request_dir = UPLOAD_DIR / request_code
    request_dir.mkdir(parents=True, exist_ok=True)

    original = Path(upload.filename or "archivo").name
    stored = f"{uuid.uuid4().hex}_{original}"
    path = request_dir / stored

    # This function is used from async routes only after read() externally for safety.
    raise RuntimeError("Use save_upload_bytes_for_request instead.")


def save_upload_bytes_for_request(
    conn: sqlite3.Connection,
    request_id: int,
    request_code: str,
    original_filename: str,
    content: bytes,
    content_type: str = "",
    source: str = "original",
) -> int:
    validate_upload_content(content, original_filename, content_type)

    request_dir = UPLOAD_DIR / request_code
    request_dir.mkdir(parents=True, exist_ok=True)

    original = validate_upload_filename(original_filename or "archivo")
    stored = f"{secrets.token_hex(16)}_{original}"
    path = safe_upload_path(str(Path(request_code) / stored))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)

    cursor = conn.execute(
        """
        INSERT INTO quote_files (
            request_id, original_filename, stored_filename, content_type, size_bytes, source
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (request_id, original, str(path.relative_to(UPLOAD_DIR)), content_type or "", len(content), source),
    )

    return int(cursor.lastrowid)



def send_email(to_email: str, subject: str, body: str) -> bool:
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD or not to_email:
        print("[email] SMTP no configurado; correo no enviado.", flush=True)
        return False

    msg = EmailMessage()
    msg["From"] = SMTP_FROM
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
            if SMTP_USE_TLS:
                smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.send_message(msg)
        return True
    except Exception as exc:
        print(f"[email] Error enviando correo a {to_email}: {exc}", flush=True)
        return False


def app_base_url(request: Request) -> str:
    configured = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if configured:
        return configured
    return str(request.base_url).rstrip("/")


def build_correction_email_body(
    request_code: str,
    customer_name: str,
    reason: str,
    correction_url: str,
) -> str:
    return "\n".join([
        f"Hola {customer_name or 'cliente'},",
        "",
        "Tu solicitud de cotización en PrototiposRD necesita una corrección antes de continuar.",
        "",
        f"Número de solicitud: {request_code}",
        "",
        "Razón de la corrección:",
        reason,
        "",
        "Puedes subir el archivo corregido en este enlace:",
        correction_url,
        "",
        "Cuando lo recibamos, el equipo revisará nuevamente la solicitud.",
        "",
        "PrototiposRD",
        "Reymildo Jiménez 2026",
    ])


def build_customer_email_body(request_code: str, customer_name: str, quote_result: dict, quote_metadata: list[dict]) -> str:
    total_price = float(quote_result.get("totalPrice", 0))
    total_pieces = int(quote_result.get("totalPieces", 0))
    total_plates = int(quote_result.get("totalPlates", 0))
    total_hours = float(quote_result.get("totalPrintHours", 0))

    lines = [
        f"Hola {customer_name or 'cliente'},",
        "",
        "Recibimos tu solicitud de cotización en PrototiposRD.",
        "",
        f"Número de solicitud: {request_code}",
        f"Total estimado: RD$ {total_price:,.2f}",
        f"Piezas: {total_pieces}",
        f"Lotes de producción: {total_plates}",
        f"Tiempo estimado: {total_hours:.2f} horas",
        "",
        "Archivos / piezas:",
    ]

    for item in quote_metadata:
        lines.append(
            f"- {item.get('filename', 'archivo')} · {item.get('quantity', 1)} unidad(es) · "
            f"{item.get('material', '')} · {item.get('color', '')}"
        )

    lines += [
        "",
        "Nuestro equipo revisará la solicitud antes de confirmar producción.",
        "",
        "PrototiposRD",
        "Reymildo Jiménez 2026",
    ]

    return "\n".join(lines)


app = FastAPI(
    title="PrototiposRD Backend",
    docs_url=None if ENVIRONMENT == "production" else "/docs",
    redoc_url=None if ENVIRONMENT == "production" else "/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS or [],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Admin-Password"],
)


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    host = request.headers.get("host", "").split(":")[0]
    if ALLOWED_HOSTS and host not in ALLOWED_HOSTS:
        return JSONResponse(status_code=400, content={"detail": "Host no permitido."})

    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not same_origin_allowed(request):
        return JSONResponse(status_code=403, content={"detail": "Origen no permitido."})

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            max_body = int(MAX_REQUEST_BODY_MB * 1024 * 1024)
            if int(content_length) > max_body:
                return JSONResponse(
                    status_code=413,
                    content={"detail": f"Solicitud demasiado grande. Máximo: {MAX_REQUEST_BODY_MB:.0f} MB."},
                )
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Content-Length inválido."})

    limited_paths = (
        "/api/slice-batch",
        "/api/quote-requests",
        "/api/corrections",
        "/api/admin",
    )
    if request.url.path.startswith(limited_paths):
        ok, retry_after = check_rate_limit(request)
        if not ok:
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(retry_after)},
                content={"detail": "Demasiadas solicitudes. Intenta de nuevo más tarde."},
            )

    response = await call_next(request)

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "connect-src 'self'; "
        "font-src 'self' data:; "
        "worker-src 'self' blob:; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'; "
        "form-action 'self';"
    )

    if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    return response


@app.on_event("startup")
async def startup_event():
    init_db()
    if ADMIN_PASSWORD in {"", "admin123", "CHANGE_ME"}:
        print("[security] ADVERTENCIA: cambia ADMIN_PASSWORD antes de producción.", flush=True)


@app.exception_handler(HTTPException)
async def http_exception_debug_handler(request, exc: HTTPException):
    print("\n[BACKEND ERROR]", flush=True)
    print(f"Path: {request.url.path}", flush=True)
    print(f"Status: {exc.status_code}", flush=True)
    print(f"Detail: {exc.detail}", flush=True)
    print("[/BACKEND ERROR]\n", flush=True)

    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@dataclass
class PrintableModel:
    id: str
    filename: str
    material: str
    color: str
    infill: float
    layer_height: float
    walls: int
    supports: str
    quantity: int
    mesh: trimesh.Trimesh
    width: float
    depth: float
    height: float


def find_slicer_executable() -> str:
    """
    Busca PrusaSlicer en:
    1. Variable de entorno PRUSASLICER_PATH
    2. PATH del sistema
    3. Rutas típicas de Windows
    """
    configured = os.environ.get("PRUSASLICER_PATH", "").strip().strip('"')

    candidates = []

    if configured:
        candidates.append(configured)

    # PATH names
    candidates += [
        "prusa-slicer-console.exe",
        "prusa-slicer.exe",
        "PrusaSlicer.exe",
        "prusa-slicer",
    ]

    # Common Windows install paths
    candidates += [
        r"C:\Program Files\Prusa3D\PrusaSlicer\prusa-slicer-console.exe",
        r"C:\Program Files\Prusa3D\PrusaSlicer\prusa-slicer.exe",
        r"C:\Program Files\PrusaSlicer\prusa-slicer-console.exe",
        r"C:\Program Files\PrusaSlicer\prusa-slicer.exe",
        r"C:\Program Files\Prusa3D\PrusaSlicer\PrusaSlicer.exe",
        r"C:\Program Files\PrusaSlicer\PrusaSlicer.exe",
        r"C:\Program Files (x86)\Prusa3D\PrusaSlicer\prusa-slicer-console.exe",
        r"C:\Program Files (x86)\Prusa3D\PrusaSlicer\prusa-slicer.exe",
    ]

    checked = []

    for candidate in candidates:
        if not candidate:
            continue

        path_candidate = Path(candidate)
        checked.append(str(candidate))

        if path_candidate.exists():
            return str(path_candidate)

        discovered = shutil.which(candidate)
        if discovered:
            return discovered

    raise HTTPException(
        status_code=503,
        detail={
            "message": "No se encontró PrusaSlicer. Instálalo o define PRUSASLICER_PATH.",
            "how_to_fix_powershell": (
                '$env:PRUSASLICER_PATH="C:\\Program Files\\Prusa3D\\PrusaSlicer\\prusa-slicer-console.exe"; '
                'python -m uvicorn server:app --reload --host 127.0.0.1 --port 8000'
            ),
            "checked": checked[-12:],
        },
    )


def parse_time_to_hours(raw: str) -> float:
    raw = raw.lower().strip()
    hours = 0.0

    h = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*h", raw)
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*m", raw)
    s = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*s", raw)

    if h:
        hours += float(h.group(1))
    if m:
        hours += float(m.group(1)) / 60.0
    if s:
        hours += float(s.group(1)) / 3600.0

    if hours == 0.0 and re.match(r"^\d+:\d+(:\d+)?$", raw):
        parts = [float(x) for x in raw.split(":")]
        if len(parts) == 3:
            hours = parts[0] + parts[1] / 60 + parts[2] / 3600
        elif len(parts) == 2:
            hours = parts[0] / 60 + parts[1] / 3600

    if hours <= 0:
        raise ValueError(f"No se pudo interpretar el tiempo de impresión: {raw}")

    return hours


def first_float_from_text(value: str) -> Optional[float]:
    match = re.search(r"([0-9]+(?:[.,][0-9]+)?)", value)
    if not match:
        return None

    try:
        return float(match.group(1).replace(",", "."))
    except Exception:
        return None


def material_density(material: str) -> float:
    return get_material_density(material)


def filament_mm_to_grams(length_mm: float, material: str) -> float:
    radius_mm = FILAMENT_DIAMETER_MM / 2.0
    area_mm2 = math.pi * radius_mm * radius_mm
    volume_cm3 = (length_mm * area_mm2) / 1000.0
    return volume_cm3 * material_density(material)


def parse_gcode_stats(gcode_path: Path, material: str = "PLA") -> dict:
    text = gcode_path.read_text(errors="ignore")

    filament_g: Optional[float] = None
    filament_cm3: Optional[float] = None
    filament_mm: Optional[float] = None
    print_hours: Optional[float] = None

    # PrusaSlicer can report material in grams, cm3 or mm depending on profile.
    gram_patterns = [
        r"filament used \[g\]\s*=\s*([^\n\r]+)",
        r"total filament used \[g\]\s*=\s*([^\n\r]+)",
        r"filament_weight_total\s*=\s*([^\n\r]+)",
    ]

    cm3_patterns = [
        r"filament used \[cm3\]\s*=\s*([^\n\r]+)",
        r"filament used \[cm\^3\]\s*=\s*([^\n\r]+)",
        r"filament_volume_total\s*=\s*([^\n\r]+)",
    ]

    mm_patterns = [
        r"filament used \[mm\]\s*=\s*([^\n\r]+)",
        r"filament length\s*=\s*([^\n\r]+)",
        r"filament_length_total\s*=\s*([^\n\r]+)",
    ]

    for pattern in gram_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = first_float_from_text(match.group(1))
            if value is not None:
                filament_g = value
                break

    if filament_g is None or filament_g <= 0:
        for pattern in cm3_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                value = first_float_from_text(match.group(1))
                if value is not None:
                    filament_cm3 = value
                    break

        if filament_cm3 is not None and filament_cm3 > 0:
            filament_g = filament_cm3 * material_density(material)

    if filament_g is None or filament_g <= 0:
        for pattern in mm_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                value = first_float_from_text(match.group(1))
                if value is not None:
                    filament_mm = value
                    break

        if filament_mm is not None and filament_mm > 0:
            filament_g = filament_mm_to_grams(filament_mm, material)

    normal_time = re.search(
        r"estimated printing time \(normal mode\)\s*=\s*([^\n\r]+)",
        text,
        flags=re.IGNORECASE,
    )
    any_time = re.search(
        r"estimated printing time.*?=\s*([^\n\r]+)",
        text,
        flags=re.IGNORECASE,
    )

    if normal_time:
        print_hours = parse_time_to_hours(normal_time.group(1).strip())
    elif any_time:
        print_hours = parse_time_to_hours(any_time.group(1).strip())

    if filament_g is None or filament_g <= 0 or print_hours is None:
        debug_tail = "\n".join(
            line for line in text.splitlines()
            if "filament" in line.lower() or "printing time" in line.lower()
        )[-2000:]

        raise HTTPException(
            status_code=500,
            detail={
                "message": "El slicer generó G-code, pero no se pudieron leer gramos/material o tiempo desde los comentarios.",
                "material": material,
                "debug_gcode_comments": debug_tail,
            },
        )

    return {
        "filamentGrams": filament_g,
        "printHours": print_hours,
    }


def cleanup_mesh_compatible(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """
    Limpieza compatible con versiones viejas y nuevas de trimesh.
    En trimesh reciente se eliminaron métodos como remove_duplicate_faces().
    """
    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError("El archivo no produjo una malla Trimesh válida.")

    if mesh.faces is None or len(mesh.faces) == 0:
        raise ValueError("La malla no tiene triángulos.")

    # Versiones viejas de trimesh
    if hasattr(mesh, "remove_duplicate_faces"):
        try:
            mesh.remove_duplicate_faces()
        except Exception:
            pass
    # Versiones nuevas de trimesh
    elif hasattr(mesh, "unique_faces") and hasattr(mesh, "update_faces"):
        try:
            mesh.update_faces(mesh.unique_faces())
        except Exception:
            pass

    if hasattr(mesh, "remove_degenerate_faces"):
        try:
            mesh.remove_degenerate_faces()
        except Exception:
            pass
    elif hasattr(mesh, "nondegenerate_faces") and hasattr(mesh, "update_faces"):
        try:
            mesh.update_faces(mesh.nondegenerate_faces())
        except Exception:
            pass

    if hasattr(mesh, "remove_unreferenced_vertices"):
        try:
            mesh.remove_unreferenced_vertices()
        except Exception:
            pass

    try:
        mesh.process(validate=False)
    except Exception:
        pass

    if mesh.vertices is None or len(mesh.vertices) == 0:
        raise ValueError("La malla no tiene vértices.")

    if mesh.faces is None or len(mesh.faces) == 0:
        raise ValueError("La malla no tiene caras después de limpiarla.")

    return mesh


def load_mesh(path: Path) -> trimesh.Trimesh:
    try:
        loaded = trimesh.load(path, force="mesh", process=False)
    except Exception:
        # Segundo intento dejando que trimesh procese automáticamente.
        loaded = trimesh.load(path, force="mesh", process=True)

    if isinstance(loaded, trimesh.Scene):
        geometries = [g for g in loaded.geometry.values() if isinstance(g, trimesh.Trimesh)]
        if not geometries:
            raise ValueError("La escena no contiene mallas válidas.")
        loaded = trimesh.util.concatenate(geometries)

    if not isinstance(loaded, trimesh.Trimesh):
        raise ValueError("No se pudo leer una malla válida.")

    return cleanup_mesh_compatible(loaded)


def rotation_matrix_from_vectors(vec1: np.ndarray, vec2: np.ndarray) -> np.ndarray:
    a = vec1 / np.linalg.norm(vec1)
    b = vec2 / np.linalg.norm(vec2)

    cross = np.cross(a, b)
    dot = np.dot(a, b)

    if np.isclose(dot, 1.0):
        return np.eye(4)

    if np.isclose(dot, -1.0):
        axis = np.array([1.0, 0.0, 0.0])
        if abs(a[0]) > 0.9:
            axis = np.array([0.0, 1.0, 0.0])
        axis = axis - a * np.dot(a, axis)
        axis = axis / np.linalg.norm(axis)
        return trimesh.transformations.rotation_matrix(math.pi, axis)

    skew = np.array([
        [0.0, -cross[2], cross[1]],
        [cross[2], 0.0, -cross[0]],
        [-cross[1], cross[0], 0.0],
    ])

    rot3 = np.eye(3) + skew + skew @ skew * ((1 - dot) / (np.linalg.norm(cross) ** 2))
    matrix = np.eye(4)
    matrix[:3, :3] = rot3
    return matrix


def candidate_normals(mesh: trimesh.Trimesh) -> list[np.ndarray]:
    normals = []
    areas = []

    try:
        facet_normals = mesh.facets_normal
        facet_areas = mesh.facets_area

        for normal, area in zip(facet_normals, facet_areas):
            if area > 1e-6:
                normals.append(np.array(normal, dtype=float))
                areas.append(float(area))
    except Exception:
        pass

    if not normals:
        face_normals = mesh.face_normals
        face_areas = mesh.area_faces
        order = np.argsort(face_areas)[::-1][:60]
        for idx in order:
            normals.append(np.array(face_normals[idx], dtype=float))
            areas.append(float(face_areas[idx]))

    axes = [
        np.array([1.0, 0.0, 0.0]),
        np.array([-1.0, 0.0, 0.0]),
        np.array([0.0, 1.0, 0.0]),
        np.array([0.0, -1.0, 0.0]),
        np.array([0.0, 0.0, 1.0]),
        np.array([0.0, 0.0, -1.0]),
    ]

    for axis in axes:
        normals.append(axis)
        areas.append(0.0)

    ordered = [n for _, n in sorted(zip(areas, normals), key=lambda item: item[0], reverse=True)]
    return ordered[:42]


def analyze_mesh_orientation(mesh: trimesh.Trimesh, normal: np.ndarray) -> tuple[float, trimesh.Trimesh, dict]:
    target_down = np.array([0.0, 0.0, -1.0])
    transform = rotation_matrix_from_vectors(normal, target_down)

    oriented = mesh.copy()
    oriented.apply_transform(transform)

    min_corner, max_corner = oriented.bounds
    oriented.apply_translation([0.0, 0.0, -min_corner[2]])

    bounds = oriented.bounds
    extents = oriented.extents
    height = float(extents[2])
    width = float(extents[0])
    depth = float(extents[1])

    face_normals = oriented.face_normals
    face_areas = oriented.area_faces
    triangles = oriented.triangles
    centroids = triangles.mean(axis=1)

    contact_mask = (centroids[:, 2] < 0.8) & (face_normals[:, 2] < -0.9)
    overhang_mask = (centroids[:, 2] > 0.8) & (face_normals[:, 2] < -0.55)

    contact_area = float(face_areas[contact_mask].sum()) / 100.0
    overhang_area = float(face_areas[overhang_mask].sum()) / 100.0

    support_volume_cm3 = 0.0
    if overhang_mask.any():
        support_volume_mm3 = float((face_areas[overhang_mask] * centroids[overhang_mask, 2] * 0.16).sum())
        support_volume_cm3 = min(support_volume_mm3 / 1000.0, 9999.0)

    oversize_penalty = 100000.0 if (width > BED_X or depth > BED_Y or height > BED_Z) else 0.0

    footprint_area_cm2 = max((width * depth) / 100.0, 0.01)
    footprint_min = max(min(width, depth), 0.01)
    footprint_max = max(max(width, depth), 0.01)

    # Production-oriented orientation score:
    # - strongly penalize tall / standing-on-edge orientations
    # - prefer low, stable, bed-friendly orientations
    # - still penalize supports and overhangs
    # - reward contact area, but never enough to justify a very tall part
    height_penalty = height * 3.5
    tall_slender_penalty = max(0.0, height - footprint_min * 0.75) * 6.0
    extreme_vertical_penalty = height * 8.0 if height > footprint_max * 0.65 else 0.0
    weak_contact_penalty = 250.0 if contact_area < footprint_area_cm2 * 0.08 else 0.0

    score = (
        support_volume_cm3 * 5.0
        + overhang_area * 0.45
        + height_penalty
        + tall_slender_penalty
        + extreme_vertical_penalty
        + weak_contact_penalty
        - contact_area * 0.35
        + oversize_penalty
    )

    info = {
        "width": width,
        "depth": depth,
        "height": height,
        "contactAreaCm2": contact_area,
        "overhangAreaCm2": overhang_area,
        "supportVolumeCm3": support_volume_cm3,
        "score": score,
    }

    return score, oriented, info


def thin_part_axis_candidates(mesh: trimesh.Trimesh) -> list[np.ndarray]:
    """
    For gears / pinions / washers: if two dimensions are large and one is small,
    force-test the small dimension as print height.
    """
    extents = mesh.extents
    axes = [
        (np.array([1.0, 0.0, 0.0]), float(extents[0])),
        (np.array([0.0, 1.0, 0.0]), float(extents[1])),
        (np.array([0.0, 0.0, 1.0]), float(extents[2])),
    ]

    axes_sorted = sorted(axes, key=lambda item: item[1])
    smallest_axis, smallest_value = axes_sorted[0]
    _, middle_value = axes_sorted[1]
    _, largest_value = axes_sorted[2]

    if smallest_value <= 0 or middle_value <= 0:
        return []

    # Apply this special rule only to disk-like parts:
    # gear, pinion, pulley, washer, wheel.
    #
    # A rack is NOT disk-like because its largest dimension is much longer
    # than its middle dimension.
    thin_enough = (
        middle_value / smallest_value >= 1.8
        and largest_value / smallest_value >= 1.8
    )

    disk_like = largest_value / middle_value <= 1.65

    looks_like_disk_or_gear = thin_enough and disk_like

    if not looks_like_disk_or_gear:
        return []

    return [smallest_axis, -smallest_axis]


def auto_orient_mesh(mesh: trimesh.Trimesh) -> tuple[trimesh.Trimesh, dict]:
    evaluated = []

    for normal in [*thin_part_axis_candidates(mesh), *candidate_normals(mesh)]:
        try:
            score, oriented, info = analyze_mesh_orientation(mesh, normal)

            fits_bed = (
                info["width"] <= BED_X
                and info["depth"] <= BED_Y
                and info["height"] <= BED_Z
            )

            evaluated.append({
                "score": score,
                "mesh": oriented,
                "info": info,
                "fitsBed": fits_bed,
            })
        except Exception:
            continue

    if not evaluated:
        raise ValueError("No se pudo orientar la malla.")

    valid = [item for item in evaluated if item["fitsBed"]]
    pool = valid if valid else evaluated

    # Main production rule:
    # maximize real contact area with the print bed.
    max_contact_area = max(float(item["info"].get("contactAreaCm2", 0.0)) for item in pool)

    if max_contact_area > 0:
        contact_pool = [
            item for item in pool
            if float(item["info"].get("contactAreaCm2", 0.0)) >= max_contact_area * 0.97
        ]
    else:
        contact_pool = pool

    if not contact_pool:
        contact_pool = pool

    best = None

    for item in contact_pool:
        info = item["info"]

        contact_area = float(info.get("contactAreaCm2", 0.0))
        support_volume = float(info.get("supportVolumeCm3", 0.0))
        overhang_area = float(info.get("overhangAreaCm2", 0.0))
        height = float(info.get("height", 0.0))

        tie_breaker_score = (
            support_volume * 5.0
            + overhang_area * 0.45
            + height * 0.75
            - contact_area * 0.25
        )

        adjusted_score = (
            -contact_area * 100000.0
            + tie_breaker_score
        )

        if best is None or adjusted_score < best["adjustedScore"]:
            best = {
                **item,
                "adjustedScore": adjusted_score,
            }

    oriented = best["mesh"]
    info = dict(best["info"])

    bounds = oriented.bounds
    center_xy = (bounds[0, :2] + bounds[1, :2]) / 2.0
    oriented.apply_translation([-center_xy[0], -center_xy[1], -bounds[0, 2]])

    info["volumeCm3"] = (
        float(abs(oriented.volume)) / 1000.0
        if oriented.is_volume
        else float(np.prod(oriented.extents)) / 1000.0 * 0.18
    )
    info["score"] = float(best["adjustedScore"])

    return oriented, info


def build_models(files: list[UploadFile], metadata: list[dict], tmp_dir: Path) -> list[PrintableModel]:
    models: list[PrintableModel] = []
    validate_file_count(files)

    if len(files) != len(metadata):
        raise HTTPException(
            status_code=400,
            detail={
                "message": "La cantidad de archivos no coincide con la metadata enviada por el frontend.",
                "files": len(files),
                "metadata": len(metadata),
            },
        )

    for index, upload in enumerate(files):
        info = metadata[index]
        extension = Path(upload.filename or "").suffix.lower()

        if extension not in {".stl", ".obj", ".3mf"}:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": f"{upload.filename}: el slicer exacto acepta STL, OBJ o 3MF. Convierte STEP/STP antes de usar slicing real.",
                    "filename": upload.filename,
                    "extension": extension,
                },
            )

        validate_upload_filename(upload.filename or f"input_{index}{extension}")
        input_path = tmp_dir / f"input_{index}{extension}"

        try:
            input_path.write_bytes(upload.file.read())
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": f"{upload.filename}: no se pudo leer el archivo recibido.",
                    "error": str(exc),
                },
            )

        try:
            mesh = load_mesh(input_path)
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": f"{upload.filename}: no se pudo convertir el archivo en una malla válida para el backend.",
                    "hint": "Prueba exportar el modelo como STL binario desde tu CAD/slicer y vuelve a subirlo.",
                    "error": str(exc),
                },
            )

        try:
            oriented, orientation = auto_orient_mesh(mesh)
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": f"{upload.filename}: no se pudo orientar automáticamente la pieza.",
                    "hint": "Revisa que la malla esté cerrada y no esté corrupta.",
                    "error": str(exc),
                },
            )

        width = float(orientation["width"])
        depth = float(orientation["depth"])
        height = float(orientation["height"])

        if width > BED_X or depth > BED_Y or height > BED_Z:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": (
                        f"{upload.filename}: la pieza orientada excede el volumen 256×256×256 mm "
                        f"({width:.1f} × {depth:.1f} × {height:.1f} mm)."
                    ),
                    "filename": upload.filename,
                    "size_mm": {
                        "x": width,
                        "y": depth,
                        "z": height,
                    },
                },
            )

        try:
            quantity = max(1, min(100, int(info.get("quantity", 1))))
        except Exception:
            quantity = 1

        models.append(
            PrintableModel(
                id=str(info.get("id", index)),
                filename=str(info.get("filename", upload.filename)),
                material=str(info.get("material", "PLA")),
                color=str(info.get("color", "")),
                infill=float(info.get("infill", 20)),
                layer_height=float(info.get("layerHeight", 0.2)),
                walls=int(info.get("walls", 3)),
                supports=str(info.get("supports", "auto")),
                quantity=quantity,
                mesh=oriented,
                width=width,
                depth=depth,
                height=height,
            )
        )

    return models


def group_key(model: PrintableModel) -> tuple:
    return (
        model.material.upper(),
        round(model.infill, 3),
        round(model.layer_height, 4),
        int(model.walls),
        model.supports,
    )


def make_instance_list(models: list[PrintableModel]) -> list[dict]:
    instances = []

    for model in models:
        for copy_index in range(model.quantity):
            instances.append({
                "model": model,
                "copyIndex": copy_index,
                "width": model.width,
                "depth": model.depth,
                "height": model.height,
                "area": model.width * model.depth,
            })

    instances.sort(key=lambda item: (max(item["width"], item["depth"]), item["area"]), reverse=True)
    return instances


def create_empty_plate() -> dict:
    return {
        "placements": [],
        "freeRects": [
            {
                "x": 0.0,
                "y": 0.0,
                "width": BED_X,
                "depth": BED_Y,
            }
        ],
    }


def rect_contains(a: dict, b: dict) -> bool:
    return (
        b["x"] >= a["x"]
        and b["y"] >= a["y"]
        and b["x"] + b["width"] <= a["x"] + a["width"]
        and b["y"] + b["depth"] <= a["y"] + a["depth"]
    )


def rects_intersect(a: dict, b: dict) -> bool:
    return not (
        a["x"] + a["width"] <= b["x"]
        or b["x"] + b["width"] <= a["x"]
        or a["y"] + a["depth"] <= b["y"]
        or b["y"] + b["depth"] <= a["y"]
    )


def prune_free_rects(free_rects: list[dict]) -> list[dict]:
    result = []

    for i, rect in enumerate(free_rects):
        if rect["width"] <= 0.01 or rect["depth"] <= 0.01:
            continue

        contained = False

        for j, other in enumerate(free_rects):
            if i == j:
                continue
            if rect_contains(other, rect):
                contained = True
                break

        if not contained:
            result.append(rect)

    return result


def split_free_rect(free_rect: dict, used_rect: dict) -> list[dict]:
    if not rects_intersect(free_rect, used_rect):
        return [free_rect]

    new_rects = []

    free_right = free_rect["x"] + free_rect["width"]
    free_bottom = free_rect["y"] + free_rect["depth"]
    used_right = used_rect["x"] + used_rect["width"]
    used_bottom = used_rect["y"] + used_rect["depth"]

    if used_rect["x"] > free_rect["x"]:
        new_rects.append({
            "x": free_rect["x"],
            "y": free_rect["y"],
            "width": used_rect["x"] - free_rect["x"],
            "depth": free_rect["depth"],
        })

    if used_right < free_right:
        new_rects.append({
            "x": used_right,
            "y": free_rect["y"],
            "width": free_right - used_right,
            "depth": free_rect["depth"],
        })

    if used_rect["y"] > free_rect["y"]:
        new_rects.append({
            "x": free_rect["x"],
            "y": free_rect["y"],
            "width": free_rect["width"],
            "depth": used_rect["y"] - free_rect["y"],
        })

    if used_bottom < free_bottom:
        new_rects.append({
            "x": free_rect["x"],
            "y": used_bottom,
            "width": free_rect["width"],
            "depth": free_bottom - used_rect["y"] - used_rect["depth"],
        })

    return new_rects


def can_place_rect(plate: dict, x: float, y: float, width: float, depth: float) -> bool:
    proposed = {"x": x, "y": y, "width": width, "depth": depth}

    if (
        proposed["x"] < 0
        or proposed["y"] < 0
        or proposed["x"] + proposed["width"] > BED_X
        or proposed["y"] + proposed["depth"] > BED_Y
    ):
        return False

    for placement in plate["placements"]:
        occupied = {
            "x": placement["x"] - placement["occupiedWidth"] / 2.0,
            "y": placement["y"] - placement["occupiedDepth"] / 2.0,
            "width": placement["occupiedWidth"],
            "depth": placement["occupiedDepth"],
        }

        if rects_intersect(proposed, occupied):
            return False

    return True


def score_placement(free_rect: dict, packed_width: float, packed_depth: float, rotated: bool, strategy: str) -> float:
    leftover_x = free_rect["width"] - packed_width
    leftover_y = free_rect["depth"] - packed_depth
    short_side_fit = min(leftover_x, leftover_y)
    long_side_fit = max(leftover_x, leftover_y)
    area_fit = free_rect["width"] * free_rect["depth"] - packed_width * packed_depth

    if strategy == "area":
        return area_fit * 1_000_000.0 + short_side_fit * 10_000.0 + long_side_fit + (250.0 if rotated else 0.0)

    if strategy == "longSide":
        return long_side_fit * 1_000_000.0 + short_side_fit * 10_000.0 + area_fit + (250.0 if rotated else 0.0)

    if strategy == "width":
        return (free_rect["x"] + packed_width) * 1_000_000.0 + (free_rect["y"] + packed_depth) * 1000.0 + area_fit + (250.0 if rotated else 0.0)

    if strategy == "height":
        return (free_rect["y"] + packed_depth) * 1_000_000.0 + (free_rect["x"] + packed_width) * 1000.0 + area_fit + (250.0 if rotated else 0.0)

    return short_side_fit * 1_000_000.0 + long_side_fit * 10_000.0 + area_fit + (250.0 if rotated else 0.0)


def find_best_placement(plate: dict, item: dict, strategy: str = "shortSide") -> Optional[dict]:
    orientations = [
        {"rotated": False, "width": item["width"], "depth": item["depth"]},
        {"rotated": True, "width": item["depth"], "depth": item["width"]},
    ]

    if strategy == "longAlongX":
        orientations.sort(key=lambda orient: orient["width"], reverse=True)

    if strategy == "longAlongZ":
        orientations.sort(key=lambda orient: orient["depth"], reverse=True)

    best = None

    for orient in orientations:
        packed_width = orient["width"] + PACKING_GAP_MM
        packed_depth = orient["depth"] + PACKING_GAP_MM

        if packed_width > BED_X or packed_depth > BED_Y:
            continue

        for free_rect in plate["freeRects"]:
            if packed_width > free_rect["width"] or packed_depth > free_rect["depth"]:
                continue

            x = free_rect["x"]
            y = free_rect["y"]

            if not can_place_rect(plate, x, y, packed_width, packed_depth):
                continue

            score = score_placement(free_rect, packed_width, packed_depth, orient["rotated"], strategy)

            score += 25.0 if orient["rotated"] else 0.0

            if best is None or score < best["score"]:
                best = {
                    **item,
                    "x": x + packed_width / 2.0,
                    "y": y + packed_depth / 2.0,
                    "width": orient["width"],
                    "depth": orient["depth"],
                    "occupiedWidth": packed_width,
                    "occupiedDepth": packed_depth,
                    "rotated": orient["rotated"],
                    "score": score,
                }

    return best


def insert_placement(plate: dict, placement: dict) -> None:
    used_rect = {
        "x": placement["x"] - placement["occupiedWidth"] / 2.0,
        "y": placement["y"] - placement["occupiedDepth"] / 2.0,
        "width": placement["occupiedWidth"],
        "depth": placement["occupiedDepth"],
    }

    updated_free_rects = []

    for free_rect in plate["freeRects"]:
        updated_free_rects.extend(split_free_rect(free_rect, used_rect))

    plate["freeRects"] = prune_free_rects(updated_free_rects)

    clean = dict(placement)
    clean.pop("score", None)
    plate["placements"].append(clean)


def try_place(plate: dict, item: dict, strategy: str = "shortSide") -> bool:
    best = find_best_placement(plate, item, strategy)
    if best is None:
        return False

    insert_placement(plate, best)
    return True


def plate_used_bounds(plate: dict) -> dict:
    right = 0.0
    bottom = 0.0

    for placement in plate["placements"]:
        right = max(right, placement["x"] + placement["occupiedWidth"] / 2.0)
        bottom = max(bottom, placement["y"] + placement["occupiedDepth"] / 2.0)

    return {
        "right": right,
        "bottom": bottom,
        "area": right * bottom,
    }


def score_packing(plates: list[dict]) -> float:
    used_area = 0.0
    max_bottom = 0.0
    max_right = 0.0
    rotated_count = 0

    for plate in plates:
        bounds = plate_used_bounds(plate)
        used_area += bounds["area"]
        max_bottom = max(max_bottom, bounds["bottom"])
        max_right = max(max_right, bounds["right"])

        for placement in plate["placements"]:
            if placement["rotated"]:
                rotated_count += 1

    return (
        len(plates) * 1_000_000_000.0
        + used_area * 1000.0
        + max_bottom * 10.0
        + max_right
        + rotated_count * 500.0
    )


def order_instances(instances: list[dict], strategy: str) -> list[dict]:
    ordered = list(instances)

    if strategy == "area":
        ordered.sort(key=lambda item: item["area"], reverse=True)
    elif strategy == "longSide":
        ordered.sort(key=lambda item: (max(item["width"], item["depth"]), item["area"]), reverse=True)
    elif strategy == "wideFirst":
        ordered.sort(key=lambda item: (item["width"], item["area"]), reverse=True)
    elif strategy == "tallFirst":
        ordered.sort(key=lambda item: (item["depth"], item["area"]), reverse=True)
    elif strategy == "mixed":
        ordered.sort(
            key=lambda item: (
                max(item["width"], item["depth"]) / max(1.0, min(item["width"], item["depth"])),
                item["area"],
            ),
            reverse=True,
        )

    return ordered


def run_packing_attempt(instances: list[dict], order_strategy: str, placement_strategy: str) -> dict:
    plates: list[dict] = []
    ordered = order_instances(instances, order_strategy)

    for item in ordered:
        placed = False

        for plate in plates:
            if try_place(plate, item, placement_strategy):
                placed = True
                break

        if not placed:
            plate = create_empty_plate()
            if not try_place(plate, item, placement_strategy):
                raise HTTPException(status_code=400, detail=f"{item['model'].filename}: no cabe en cama 256×256 mm.")
            plates.append(plate)

    return {"plates": plates}


def pack_group(models: list[PrintableModel]) -> list[dict]:
    instances = make_instance_list(models)

    attempts = [
        ("longSide", "shortSide"),
        ("area", "shortSide"),
        ("wideFirst", "longAlongX"),
        ("tallFirst", "longAlongZ"),
        ("mixed", "shortSide"),
        ("longSide", "area"),
        ("area", "area"),
        ("mixed", "longSide"),
    ]

    best = None

    for order_strategy, placement_strategy in attempts:
        result = run_packing_attempt(instances, order_strategy, placement_strategy)
        score = score_packing(result["plates"])

        if best is None or score < best["score"]:
            best = {
                "plates": result["plates"],
                "score": score,
            }

    return best["plates"]


def mesh_for_placement(placement: dict) -> trimesh.Trimesh:
    model: PrintableModel = placement["model"]
    mesh = model.mesh.copy()

    if placement["rotated"]:
        rot = trimesh.transformations.rotation_matrix(math.pi / 2.0, [0, 0, 1])
        mesh.apply_transform(rot)

    bounds = mesh.bounds
    min_corner = bounds[0]
    max_corner = bounds[1]
    center_xy = (min_corner[:2] + max_corner[:2]) / 2.0

    # IMPORTANT:
    # PrusaSlicer CLI works more reliably when STL coordinates are inside
    # positive bed coordinates. Do NOT center the whole plate around 0,0 here.
    # Keep all objects inside X/Y range 0..256.
    target_x = float(placement["x"])
    target_y = float(placement["y"])

    mesh.apply_translation([
        target_x - center_xy[0],
        target_y - center_xy[1],
        -min_corner[2],
    ])

    # Final bed alignment guard.
    final_bounds = mesh.bounds
    if math.isfinite(float(final_bounds[0][2])) and final_bounds[0][2] < 0:
        mesh.apply_translation([0.0, 0.0, -final_bounds[0][2]])

    # Final XY guard: if numeric drift puts the mesh slightly outside,
    # move it back into positive bed coordinates.
    final_bounds = mesh.bounds
    shift_x = 0.0
    shift_y = 0.0

    if final_bounds[0][0] < 0:
        shift_x = -float(final_bounds[0][0])
    elif final_bounds[1][0] > BED_X:
        shift_x = BED_X - float(final_bounds[1][0])

    if final_bounds[0][1] < 0:
        shift_y = -float(final_bounds[0][1])
    elif final_bounds[1][1] > BED_Y:
        shift_y = BED_Y - float(final_bounds[1][1])

    if abs(shift_x) > 1e-6 or abs(shift_y) > 1e-6:
        mesh.apply_translation([shift_x, shift_y, 0.0])

    return mesh

def export_plate_stl(plate: dict, output_path: Path) -> None:
    meshes = [mesh_for_placement(placement) for placement in plate["placements"]]
    if not meshes:
        raise ValueError("La cama no contiene piezas.")

    combined = trimesh.util.concatenate(meshes)

    bounds = combined.bounds
    print(
        f"[export_plate_stl] {output_path.name} bounds "
        f"X={bounds[0][0]:.2f}..{bounds[1][0]:.2f}, "
        f"Y={bounds[0][1]:.2f}..{bounds[1][1]:.2f}, "
        f"Z={bounds[0][2]:.2f}..{bounds[1][2]:.2f}",
        flush=True,
    )

    combined.export(output_path)


def build_prusaslicer_command(
    slicer: str,
    input_file: Path,
    output_file: Path,
    material: str,
    infill: float,
    layer_height: float,
    walls: int,
    supports: str,
) -> list[str]:
    cmd = [slicer]

    if PRUSASLICER_PROFILE:
        cmd += ["--load", PRUSASLICER_PROFILE]

    cmd += [
        "--export-gcode",
        "--output", str(output_file),
        "--bed-shape", "0x0,256x0,256x256,0x256",
        "--filament-diameter", str(FILAMENT_DIAMETER_MM),
        "--filament-density", str(material_density(material)),
        "--layer-height", str(layer_height),
        "--fill-density", f"{infill}%",
        "--perimeters", str(walls),
    ]

    if supports == "yes":
        cmd += ["--support-material"]
    elif supports == "auto":
        cmd += ["--support-material", "--support-material-auto"]
    else:
        cmd += ["--dont-support-material"]

    material_upper = material.upper()
    if not PRUSASLICER_PROFILE and material_upper in {"PLA", "PETG", "ABS", "TPU"}:
        filament_temp = {
            "PLA": "210",
            "PETG": "240",
            "ABS": "245",
            "TPU": "225",
        }[material_upper]
        bed_temp = {
            "PLA": "60",
            "PETG": "80",
            "ABS": "100",
            "TPU": "50",
        }[material_upper]
        cmd += ["--temperature", filament_temp, "--bed-temperature", bed_temp]

    cmd.append(str(input_file))
    return cmd


def get_material_row(material: str) -> Optional[sqlite3.Row]:
    key = str(material or "").upper()
    try:
        with get_db() as conn:
            return conn.execute(
                """
                SELECT *
                FROM material_catalog
                WHERE UPPER(material_key) = ?
                """,
                (key,),
            ).fetchone()
    except Exception:
        return None


def get_material_density(material: str) -> float:
    row = get_material_row(material)
    if row:
        return float(row["density_g_cm3"])

    raise HTTPException(
        status_code=400,
        detail=f"Material no configurado en base de datos: {material}",
    )


def material_price_per_gram(material: str) -> float:
    row = get_material_row(material)
    if row:
        return float(row["price_per_gram"])

    raise HTTPException(
        status_code=400,
        detail=f"Material no configurado en base de datos: {material}",
    )


def slice_plate(
    slicer: str,
    plate_stl: Path,
    gcode_path: Path,
    group: tuple,
) -> dict:
    material, infill, layer_height, walls, supports = group

    cmd = build_prusaslicer_command(
        slicer=slicer,
        input_file=plate_stl,
        output_file=gcode_path,
        material=material,
        infill=infill,
        layer_height=layer_height,
        walls=walls,
        supports=supports,
    )

    result = subprocess.run(
        cmd,
        cwd=plate_stl.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=300,
    )

    if result.returncode != 0 or not gcode_path.exists():
        raise HTTPException(
            status_code=500,
            detail={
                "message": "PrusaSlicer falló generando el G-code de una cama.",
                "stderr": result.stderr[-2000:],
                "stdout": result.stdout[-1000:],
                "command": cmd,
            },
        )

    stats = parse_gcode_stats(gcode_path, material)

    if stats["filamentGrams"] <= 0:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "El slicer devolvió 0 g de material. Esto no es válido para cotización.",
                "plate": str(plate_stl),
                "material": material,
            },
        )

    return stats




@app.get("/api/debug-info")
async def debug_info():
    try:
        import numpy
        import trimesh as trimesh_module
        return {
            "ok": True,
            "numpy": numpy.__version__,
            "trimesh": trimesh_module.__version__,
            "supported_backend_formats": ["stl", "obj", "3mf"],
            "bed_mm": [BED_X, BED_Y, BED_Z],
            "filament_diameter_mm": FILAMENT_DIAMETER_MM,
            "material_source": "database",
            "material_parser": "grams, cm3, mm fallback",
            "setup_cost_per_plate_internal": SETUP_COST_PER_PLATE,
            "grouping_rule": "different material or different print profile = separate sliced plate group",
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
        }


@app.get("/api/slicer-status")
async def slicer_status():
    try:
        slicer = find_slicer_executable()
        version_result = subprocess.run(
            [slicer, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )

        return {
            "ok": True,
            "path": slicer,
            "version": (version_result.stdout or version_result.stderr).strip(),
        }
    except HTTPException as exc:
        return {
            "ok": False,
            "detail": exc.detail,
        }
    except Exception as exc:
        return {
            "ok": False,
            "detail": str(exc),
        }


@app.post("/api/slice-batch")
async def slice_batch(
    files: list[UploadFile] = File(...),
    metadata: str = Form("[]"),
):
    try:
        meta = json.loads(metadata)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "metadata no es JSON válido.",
                "error": str(exc),
            },
        )

    if len(files) != len(meta):
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Cantidad de archivos y metadata no coincide.",
                "files": len(files),
                "metadata": len(meta),
            },
        )

    slicer = find_slicer_executable()
    print(f"[slice-batch] archivos={len(files)} metadata={len(meta)} slicer={slicer}")

    total_filament_g = 0.0
    total_print_hours = 0.0
    total_price = 0.0
    total_plates = 0
    plate_results = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        print("[slice-batch] Validando y orientando modelos...", flush=True)
        models = build_models(files, meta, tmp_dir)
        print(f"[slice-batch] Modelos válidos: {len(models)}", flush=True)

        groups: dict[tuple, list[PrintableModel]] = {}
        for model in models:
            groups.setdefault(group_key(model), []).append(model)

        for group_index, (group, group_models) in enumerate(groups.items()):
            plates = pack_group(group_models)
            print(f"[slice-batch] Grupo {group_index}: {len(group_models)} modelo(s), {len(plates)} cama(s)", flush=True)
            material = group[0]

            for plate_index, plate in enumerate(plates):
                total_plates += 1

                plate_stl = tmp_dir / f"group_{group_index}_plate_{plate_index}.stl"
                gcode_path = tmp_dir / f"group_{group_index}_plate_{plate_index}.gcode"

                export_plate_stl(plate, plate_stl)
                stats = slice_plate(slicer, plate_stl, gcode_path, group)

                filament_g = float(stats["filamentGrams"])
                print_hours = float(stats["printHours"])

                material_cost = filament_g * material_price_per_gram(material)
                machine_cost = print_hours * MACHINE_PRICE_PER_HOUR
                electricity_cost = print_hours * PRINTER_AVERAGE_POWER_KW * ELECTRICITY_RATE_PER_KWH
                setup_cost = SETUP_COST_PER_PLATE
                price = (material_cost + machine_cost + electricity_cost + setup_cost) * PROFIT_MULTIPLIER

                total_filament_g += filament_g
                total_print_hours += print_hours
                total_price += price

                plate_results.append({
                    "group": group_index,
                    "plate": plate_index + 1,
                    "material": material,
                    "pieces": len(plate["placements"]),
                    "filamentGrams": filament_g,
                    "printHours": print_hours,
                    "setupApplied": True,
                })

    total_price = max(MINIMUM_QUOTE, total_price) if total_filament_g > 0 else 0.0

    return {
        "source": "PrusaSlicer plate batch",
        "totalFilamentGrams": total_filament_g,
        "totalPrintHours": total_print_hours,
        "totalPrice": total_price,
        "totalPlates": total_plates,
        "plates": plate_results,
    }


@app.post("/api/quote-requests")
async def create_quote_request(
    customer_name: str = Form(""),
    customer_email: str = Form(...),
    customer_phone: str = Form(...),
    customer_notes: str = Form(""),
    quote_metadata: str = Form(...),
    quote_result: str = Form(...),
    files: list[UploadFile] = File(default=[]),
):
    try:
        metadata = json.loads(quote_metadata)
        result = json.loads(quote_result)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Datos de cotización inválidos.")

    validate_file_count(files)
    customer_name, customer_email, customer_phone, customer_notes = validate_customer_data(
        customer_name, customer_email, customer_phone, customer_notes
    )

    total_price = float(result.get("totalPrice", 0))
    total_pieces = int(result.get("totalPieces", 0))
    total_plates = int(result.get("totalPlates", 0))
    total_print_hours = float(result.get("totalPrintHours", 0))
    total_filament_grams = float(result.get("totalFilamentGrams", 0))

    if total_price <= 0 or total_print_hours <= 0 or total_filament_grams <= 0:
        raise HTTPException(status_code=400, detail="La cotización debe tener un resultado válido del slicer.")

    request_code = f"PRD-{uuid.uuid4().hex[:8].upper()}"

    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO quote_requests (
                request_code, status, customer_name, customer_email, customer_phone,
                customer_notes, quote_metadata, quote_result, total_price,
                total_pieces, total_plates, total_print_hours, total_filament_grams
            )
            VALUES (?, 'new', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_code,
                customer_name,
                customer_email,
                customer_phone,
                customer_notes,
                json.dumps(metadata, ensure_ascii=False),
                json.dumps(result, ensure_ascii=False),
                total_price,
                total_pieces,
                total_plates,
                total_print_hours,
                total_filament_grams,
            ),
        )
        request_id = int(cursor.lastrowid)

        for upload in files:
            content = await upload.read()
            save_upload_bytes_for_request(
                conn=conn,
                request_id=request_id,
                request_code=request_code,
                original_filename=upload.filename or "archivo",
                content=content,
                content_type=upload.content_type or "",
                source="original",
            )

        conn.execute(
            """
            INSERT INTO quote_logs (request_id, action, actor, note, from_status, to_status)
            VALUES (?, 'created', 'customer', 'Solicitud creada desde la página web.', NULL, 'new')
            """,
            (request_id,),
        )

    body = build_customer_email_body(request_code, customer_name, result, metadata if isinstance(metadata, list) else [])
    sent_customer = send_email(customer_email, f"PrototiposRD · Solicitud {request_code}", body)

    if ADMIN_NOTIFICATION_EMAIL:
        send_email(
            ADMIN_NOTIFICATION_EMAIL,
            f"Nueva solicitud PrototiposRD {request_code}",
            f"Se recibió una nueva solicitud.\n\nCódigo: {request_code}\nCliente: {customer_name}\nCorreo: {customer_email}\nTeléfono: {customer_phone}\nTotal estimado: RD$ {total_price:,.2f}"
        )

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO quote_logs (request_id, action, actor, note, from_status, to_status)
            VALUES (?, 'email_customer_copy', 'system', ?, 'new', 'new')
            """,
            (request_id, "Correo enviado al cliente." if sent_customer else "SMTP no configurado o envío fallido."),
        )

    return {
        "ok": True,
        "request_id": request_id,
        "request_code": request_code,
        "email_sent": sent_customer,
    }



@app.get("/api/materials")
async def public_materials():
    with get_db() as conn:
        materials = conn.execute(
            """
            SELECT *
            FROM material_catalog
            WHERE is_active = 1 AND is_out_of_stock = 0
            ORDER BY name
            """
        ).fetchall()

        result = {}

        for material in materials:
            colors = conn.execute(
                """
                SELECT color_name
                FROM material_colors
                WHERE material_id = ? AND is_active = 1 AND is_out_of_stock = 0
                ORDER BY color_name
                """,
                (material["id"],),
            ).fetchall()

            color_names = [row["color_name"] for row in colors]

            if not color_names:
                continue

            result[material["material_key"]] = {
                "name": material["name"],
                "description": material["description"] or "",
                "pricePerGram": float(material["price_per_gram"]),
                "pricePerKg": float(material["price_per_gram"]) * 1000.0,
                "densityFactor": float(material["density_factor"]),
                "colors": color_names,
            }

    return {"materials": result}


@app.get("/api/admin/materials")
async def admin_materials(request: Request):
    require_admin(request)

    with get_db() as conn:
        materials = conn.execute(
            "SELECT * FROM material_catalog ORDER BY name"
        ).fetchall()

        result = []

        for material in materials:
            colors = conn.execute(
                "SELECT * FROM material_colors WHERE material_id = ? ORDER BY color_name",
                (material["id"],),
            ).fetchall()

            data = row_to_dict(material)
            data["price_per_kg"] = float(data.get("price_per_gram", 0) or 0) * 1000.0
            data["colors"] = [row_to_dict(color) for color in colors]
            result.append(data)

    return {"materials": result}


@app.post("/api/admin/materials")
async def admin_save_material(request: Request):
    require_admin(request)
    payload = await request.json()

    material_key = clean_text(payload.get("material_key", ""), 30).upper()
    name = clean_text(payload.get("name", ""), 80)
    description = clean_text(payload.get("description", ""), 500)

    if not re.match(r"^[A-Z0-9_-]{2,30}$", material_key):
        raise HTTPException(status_code=400, detail="Clave de material inválida.")
    if not name:
        raise HTTPException(status_code=400, detail="Nombre de material requerido.")

    try:
        if "price_per_kg" in payload:
            price_per_kg = max(1.0, float(payload.get("price_per_kg", 2000.0)))
            price_per_gram = price_per_kg / 1000.0
        else:
            price_per_gram = max(0.01, float(payload.get("price_per_gram", 2.0)))

        density_g_cm3 = max(0.01, float(payload.get("density_g_cm3", 1.24)))
        density_factor = max(0.01, float(payload.get("density_factor", 1.0)))
    except Exception:
        raise HTTPException(status_code=400, detail="Valores numéricos inválidos.")

    is_active = 1 if payload.get("is_active", True) else 0
    is_out_of_stock = 1 if payload.get("is_out_of_stock", False) else 0
    colors = payload.get("colors", [])
    replace_colors = bool(payload.get("replace_colors", False))

    if not isinstance(colors, list):
        raise HTTPException(status_code=400, detail="Lista de colores inválida.")

    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM material_catalog WHERE material_key = ?",
            (material_key,),
        ).fetchone()

        if existing:
            material_id = existing["id"]
            conn.execute(
                """
                UPDATE material_catalog
                SET name = ?, description = ?, price_per_gram = ?, density_g_cm3 = ?,
                    density_factor = ?, is_active = ?, is_out_of_stock = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    name,
                    description,
                    price_per_gram,
                    density_g_cm3,
                    density_factor,
                    is_active,
                    is_out_of_stock,
                    material_id,
                ),
            )
        else:
            cursor = conn.execute(
                """
                INSERT INTO material_catalog (
                    material_key, name, description, price_per_gram, density_g_cm3,
                    density_factor, is_active, is_out_of_stock
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    material_key,
                    name,
                    description,
                    price_per_gram,
                    density_g_cm3,
                    density_factor,
                    is_active,
                    is_out_of_stock,
                ),
            )
            material_id = int(cursor.lastrowid)

        if replace_colors:
            desired_colors = {
                clean_text(str(color.get("color_name", "")), 60).lower()
                for color in colors
                if clean_text(str(color.get("color_name", "")), 60)
            }
            existing_colors = conn.execute(
                "SELECT id, color_name FROM material_colors WHERE material_id = ?",
                (material_id,),
            ).fetchall()
            for existing_color in existing_colors:
                if existing_color["color_name"].lower() not in desired_colors:
                    conn.execute(
                        "DELETE FROM material_colors WHERE id = ?",
                        (existing_color["id"],),
                    )

        for color in colors:
            color_name = clean_text(str(color.get("color_name", "")), 60)
            if not color_name:
                continue

            color_active = 1 if color.get("is_active", True) else 0
            color_oos = 1 if color.get("is_out_of_stock", False) else 0

            existing_color = conn.execute(
                """
                SELECT id FROM material_colors
                WHERE material_id = ? AND color_name = ?
                """,
                (material_id, color_name),
            ).fetchone()

            if existing_color:
                conn.execute(
                    """
                    UPDATE material_colors
                    SET is_active = ?, is_out_of_stock = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (color_active, color_oos, existing_color["id"]),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO material_colors (
                        material_id, color_name, is_active, is_out_of_stock
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (material_id, color_name, color_active, color_oos),
                )

    return {"ok": True}


@app.post("/api/admin/materials/{material_id}/visibility")
async def admin_material_visibility(material_id: int, request: Request):
    require_admin(request)
    payload = await request.json()

    is_active = 1 if payload.get("is_active", True) else 0
    is_out_of_stock = 1 if payload.get("is_out_of_stock", False) else 0

    with get_db() as conn:
        conn.execute(
            """
            UPDATE material_catalog
            SET is_active = ?, is_out_of_stock = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (is_active, is_out_of_stock, material_id),
        )

    return {"ok": True}


@app.post("/api/admin/material-colors/{color_id}/visibility")
async def admin_color_visibility(color_id: int, request: Request):
    require_admin(request)
    payload = await request.json()

    is_active = 1 if payload.get("is_active", True) else 0
    is_out_of_stock = 1 if payload.get("is_out_of_stock", False) else 0

    with get_db() as conn:
        conn.execute(
            """
            UPDATE material_colors
            SET is_active = ?, is_out_of_stock = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (is_active, is_out_of_stock, color_id),
        )

    return {"ok": True}


@app.post("/api/admin/materials/{material_id}/delete")
async def admin_delete_material(material_id: int, request: Request):
    require_admin(request)

    with get_db() as conn:
        material = conn.execute(
            "SELECT * FROM material_catalog WHERE id = ?",
            (material_id,),
        ).fetchone()

        if not material:
            raise HTTPException(status_code=404, detail="Material no encontrado.")

        conn.execute("DELETE FROM material_colors WHERE material_id = ?", (material_id,))
        conn.execute("DELETE FROM material_catalog WHERE id = ?", (material_id,))

    return {"ok": True}


@app.post("/api/admin/material-colors/{color_id}/delete")
async def admin_delete_color(color_id: int, request: Request):
    require_admin(request)

    with get_db() as conn:
        color = conn.execute(
            "SELECT * FROM material_colors WHERE id = ?",
            (color_id,),
        ).fetchone()

        if not color:
            raise HTTPException(status_code=404, detail="Color no encontrado.")

        conn.execute("DELETE FROM material_colors WHERE id = ?", (color_id,))

    return {"ok": True}



@app.get("/api/admin/requests")
async def admin_list_requests(request: Request, status: str = "", q: str = ""):
    require_admin(request)

    clauses = []
    params = []

    if status:
        clauses.append("status = ?")
        params.append(status)

    if q:
        like = f"%{q}%"
        clauses.append("(request_code LIKE ? OR customer_name LIKE ? OR customer_email LIKE ? OR customer_phone LIKE ?)")
        params.extend([like, like, like, like])

    where = "WHERE " + " AND ".join(clauses) if clauses else ""

    with get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM quote_requests
            {where}
            ORDER BY created_at DESC
            LIMIT 200
            """,
            params,
        ).fetchall()

        requests = []

        for row in rows:
            request_id = row["id"]
            files = [row_to_dict(file_row) for file_row in conn.execute(
                "SELECT id, original_filename, stored_filename, content_type, size_bytes, source, created_at FROM quote_files WHERE request_id = ? ORDER BY id",
                (request_id,),
            ).fetchall()]
            logs = [row_to_dict(log_row) for log_row in conn.execute(
                "SELECT action, actor, note, from_status, to_status, created_at FROM quote_logs WHERE request_id = ? ORDER BY id",
                (request_id,),
            ).fetchall()]
            requests.append(request_to_public_dict(row, files, logs))

    return {"requests": requests}



@app.get("/api/admin/files/{file_id}")
async def admin_download_file(file_id: int, request: Request):
    require_admin(request)

    with get_db() as conn:
        row = conn.execute(
            """
            SELECT f.*, r.request_code
            FROM quote_files f
            JOIN quote_requests r ON r.id = f.request_id
            WHERE f.id = ?
            """,
            (file_id,),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Archivo no encontrado.")

    path = safe_upload_path(row["stored_filename"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Archivo no existe en disco.")

    return FileResponse(
        path,
        filename=row["original_filename"],
        media_type=row["content_type"] or "application/octet-stream",
    )


@app.get("/correction/{token}")
async def correction_page(token: str):
    return FileResponse(APP_DIR / "correction.html")


@app.get("/api/corrections/{token}")
async def get_correction_request(token: str):
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT id, request_code, status, correction_reason
            FROM quote_requests
            WHERE correction_token = ?
            """,
            (token,),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Enlace de corrección inválido.")

    return {
        "request_code": row["request_code"],
        "status": row["status"],
        "correction_reason": row["correction_reason"] or "",
    }


@app.post("/api/corrections/{token}/files")
async def upload_correction_files(
    token: str,
    message: str = Form(""),
    files: list[UploadFile] = File(...),
):
    if not files:
        raise HTTPException(status_code=400, detail="Debes subir al menos un archivo.")
    validate_file_count(files)
    message = clean_text(message, 2000)

    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM quote_requests WHERE correction_token = ?",
            (token,),
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Enlace de corrección inválido.")

        request_id = row["id"]
        request_code = row["request_code"]

        saved_count = 0

        for upload in files:
            content = await upload.read()
            save_upload_bytes_for_request(
                conn=conn,
                request_id=request_id,
                request_code=request_code,
                original_filename=upload.filename or "archivo",
                content=content,
                content_type=upload.content_type or "",
                source="correction",
            )
            saved_count += 1

        old_status = row["status"]

        conn.execute(
            """
            UPDATE quote_requests
            SET status = 'new',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (request_id,),
        )

        note = f"Cliente subió {saved_count} archivo(s) corregido(s)."
        if message:
            note += f" Mensaje: {message}"

        conn.execute(
            """
            INSERT INTO quote_logs (request_id, action, actor, note, from_status, to_status)
            VALUES (?, 'correction_uploaded', 'customer', ?, ?, 'new')
            """,
            (request_id, note, old_status),
        )

    return {"ok": True, "saved_files": saved_count}


@app.post("/api/admin/requests/{request_id}/status")
async def admin_update_request_status(request_id: int, request: Request):
    require_admin(request)

    payload = await request.json()
    new_status = clean_text(payload.get("status", ""), 30)
    note = clean_text(payload.get("note", ""), 2000)
    commitment_date = validate_commitment_date(payload.get("commitment_date", "") or "")
    notify_customer = bool(payload.get("notify_customer", False))

    allowed = {"accepted", "correction", "rejected", "ignored", "new"}
    if new_status not in allowed:
        raise HTTPException(status_code=400, detail="Estado inválido.")

    correction_url = ""
    email_sent = False

    with get_db() as conn:
        row = conn.execute("SELECT * FROM quote_requests WHERE id = ?", (request_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Solicitud no encontrada.")

        old_status = row["status"]
        correction_token = row["correction_token"]

        if new_status == "correction":
            if not note.strip():
                raise HTTPException(status_code=400, detail="Debes escribir la razón de la corrección.")

            if not correction_token:
                correction_token = secrets.token_urlsafe(32)

            correction_url = f"{app_base_url(request)}/correction/{correction_token}"

            conn.execute(
                """
                UPDATE quote_requests
                SET status = ?,
                    correction_token = ?,
                    correction_reason = ?,
                    correction_requested_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (new_status, correction_token, note, request_id),
            )
        elif new_status == "accepted":
            conn.execute(
                """
                UPDATE quote_requests
                SET status = ?,
                    commitment_date = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (new_status, commitment_date or None, request_id),
            )

            if commitment_date:
                note = (note + "\n" if note else "") + f"Fecha compromiso: {commitment_date}"
        else:
            conn.execute(
                "UPDATE quote_requests SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_status, request_id),
            )

        conn.execute(
            """
            INSERT INTO quote_logs (request_id, action, actor, note, from_status, to_status)
            VALUES (?, 'status_changed', 'admin', ?, ?, ?)
            """,
            (request_id, note, old_status, new_status),
        )

        # Need values after DB writes, but before connection closes.
        customer_email = row["customer_email"]
        customer_name = row["customer_name"]
        request_code = row["request_code"]

    if new_status == "correction" and notify_customer:
        body = build_correction_email_body(
            request_code=request_code,
            customer_name=customer_name,
            reason=note,
            correction_url=correction_url,
        )
        email_sent = send_email(
            customer_email,
            f"PrototiposRD · Corrección requerida {request_code}",
            body,
        )

        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO quote_logs (request_id, action, actor, note, from_status, to_status)
                VALUES (?, 'correction_email', 'system', ?, 'correction', 'correction')
                """,
                (
                    request_id,
                    "Correo de corrección enviado al cliente."
                    if email_sent
                    else "No se pudo enviar correo de corrección o SMTP no está configurado.",
                ),
            )

    return {
        "ok": True,
        "correction_url": correction_url,
        "email_sent": email_sent,
    }


@app.get("/admin")
async def admin_page():
    return FileResponse(APP_DIR / "admin.html")


app.mount("/", StaticFiles(directory=APP_DIR, html=True), name="static")
