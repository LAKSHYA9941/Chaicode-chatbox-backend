import hashlib
import hmac
import os
import time
from typing import Optional

from dotenv import find_dotenv, load_dotenv
from fastapi import APIRouter, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.schemas import IngestRequest, IngestResponse, RagQueryRequest, RagQueryResponse
from app.rag import query_rag
from app.ingestion import ingest_md_files, ingest_vtt_files

# Load environment variables
load_dotenv(find_dotenv(usecwd=True))

app = FastAPI(title="Sentinel Brain")

# ---------- Security / HMAC Configuration ----------
def get_hmac_secret() -> str:
    return (
        os.getenv("BRAIN_SHARED_SECRET")
        or os.getenv("HMAC_SECRET")
        or os.getenv("INTERNAL_API_SECRET")
        or "sentinel-brain-secret"
    )

MAX_TIMESTAMP_SKEW_SECONDS = 300  # 5 minutes tolerance for timestamp drift


@app.middleware("http")
async def hmac_security_middleware(request: Request, call_next):
    """
    HMAC Authentication Middleware.
    Validates HMAC-SHA256 signatures on internal protected routes between Express and FastAPI.
    """
    path = request.url.path
    # Protect /rag/* endpoints as well as direct /query and /ingest endpoints
    is_protected = path.startswith("/rag/") or path in ["/query", "/ingest"]

    if is_protected and request.method != "OPTIONS":
        signature = (
            request.headers.get("X-Signature")
            or request.headers.get("X-Brain-Signature")
            or request.headers.get("X-Hub-Signature-256")
        )
        if not signature:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Unauthorized: Missing HMAC signature header (X-Signature)"},
            )

        if signature.startswith("sha256="):
            signature = signature[7:]

        raw_body = await request.body()
        secret = get_hmac_secret().encode("utf-8")

        # Optional timestamp replay-attack validation
        timestamp = request.headers.get("X-Timestamp")
        if timestamp:
            try:
                ts_val = float(timestamp)
                if ts_val > 1e11:  # Convert milliseconds to seconds if needed
                    ts_val = ts_val / 1000.0
                if abs(time.time() - ts_val) > MAX_TIMESTAMP_SKEW_SECONDS:
                    return JSONResponse(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        content={"detail": "Unauthorized: Request timestamp expired or skewed"},
                    )
                # Compute signature with timestamp: hmac(timestamp.body)
                ts_message = timestamp.encode("utf-8") + b"." + raw_body
                expected_with_ts = hmac.new(secret, ts_message, hashlib.sha256).hexdigest()
                expected_raw = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()

                if not (
                    hmac.compare_digest(signature.lower(), expected_with_ts.lower())
                    or hmac.compare_digest(signature.lower(), expected_raw.lower())
                ):
                    return JSONResponse(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        content={"detail": "Unauthorized: Invalid HMAC signature"},
                    )
            except ValueError:
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Unauthorized: Invalid timestamp header format"},
                )
        else:
            expected_signature = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature.lower(), expected_signature.lower()):
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Unauthorized: Invalid HMAC signature"},
                )

    response = await call_next(request)
    return response


# ---------- Routes ----------
rag_router = APIRouter(prefix="/rag", tags=["RAG"])


@app.get("/")
def root():
    return {"message": "Welcome to the Sentinel Brain API"}


@app.get("/health")
def health():
    return {"status": "ok"}


@rag_router.post("/query", response_model=RagQueryResponse)
def rag_query_endpoint(request: RagQueryRequest):
    try:
        return query_rag(request)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        if getattr(e, "code", None) == "QDRANT_DIMENSION_MISMATCH" or "QDRANT_DIMENSION_MISMATCH" in str(e):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Course vector store is outdated. Please re-run ingestion.",
            )
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@rag_router.post("/ingest", response_model=IngestResponse)
def rag_ingest_endpoint(request: IngestRequest):
    try:
        files_to_process = request.files if request.files else request.file_paths
        result = ingest_md_files(
            course={"courseId": request.course_id, "qdrantCollection": request.collection_name},
            files=files_to_process,
            force_recreate=request.force_recreate,
        )
        return IngestResponse(
            upserted=result["upserted"],
            processed_files=result["processedFiles"],
            total_files=result["totalFiles"],
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))



# Include the /rag router
app.include_router(rag_router)

# Aliases for direct /query and /ingest endpoints
@app.post("/query", response_model=RagQueryResponse, include_in_schema=False)
def query_alias(request: RagQueryRequest):
    return rag_query_endpoint(request)


@app.post("/ingest", response_model=IngestResponse, include_in_schema=False)
def ingest_alias(request: IngestRequest):
    return rag_ingest_endpoint(request)
