import os
import time
from typing import Any, Dict, List, Optional
from dotenv import find_dotenv, load_dotenv
from groq import Groq
from nomic import embed
from qdrant_client import QdrantClient

from app.schemas import RagQueryRequest, RagQueryResponse, Source

# Load environment variables
load_dotenv(find_dotenv(usecwd=True))

# ---------- Configuration ----------
def get_embedding_model() -> str:
    return os.getenv("NOMIC_EMBEDDING_MODEL", "nomic-embed-text-v1.5")

def get_default_groq_model() -> str:
    return os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")


# ---------- Lazy / Reusable Clients ----------
_groq_client: Optional[Groq] = None
_qdrant_client: Optional[QdrantClient] = None


def get_groq_client() -> Groq:
    global _groq_client
    if _groq_client is None:
        api_key = os.getenv("GROQ_API_KEY") or os.getenv("GROK_API_KEY")
        _groq_client = Groq(api_key=api_key)
    return _groq_client


def get_qdrant_client() -> QdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        url = os.getenv("QDRANT_URL", "http://localhost:6333")
        api_key = os.getenv("QDRANT_API_KEY")
        _qdrant_client = QdrantClient(
            url=url,
            port=443 if url.startswith("https") else 6333,
            timeout=60,
            api_key=api_key,
            check_compatibility=False,
        )
    return _qdrant_client



import nomic

_nomic_authenticated = False

def ensure_nomic_auth():
    global _nomic_authenticated
    if not _nomic_authenticated:
        key = os.getenv("NOMIC_API_KEY")
        if key:
            try:
                nomic.login(key)
            except Exception:
                pass
        _nomic_authenticated = True

def get_embedding(text: str, model: Optional[str] = None) -> List[float]:
    """Generate query embedding vector using Nomic embed."""
    ensure_nomic_auth()
    embedding_model = model or get_embedding_model()
    output = embed.text(
        texts=[text],
        model=embedding_model,
        task_type="search_query",
    )
    return output["embeddings"][0]



def get_system_prompt(course_name: str = "") -> str:
    """Build system prompt matching the educator persona."""
    return f"""You are Hitesh Choudhary, a passionate Indian MERN stack educator, mentor, and motivator.
1-You sometimes start with "Hanji!".
2-Explain in simple, short, practical Hinglish (Hindi + English).
3-break code into steps if intent is to write code, add motivational advice, keep tone friendly, witty, informal , be short and concise about the answers.
4-Answer as an expert in the {course_name} course and refrain from answering questions outside the scope of the course for example if {course_name} is about python then do not answer questions related to nodejs also suggest the user to switch to the relevant course in any situation do not answer these types of questions.
5-Avoid academic jargon—talk like a friend over tea and dont talk unnecessarily keep it short and simple for every response untill not asked to explain something in detail.
6-Give concise but helpful answers with examples and code snippets where relevant.
7-If asked about cost, respond with this link "https://hitesh.ai" or "https://www.chaicode.com".
"""


def similarity_search(collection_name: str, query: str, limit: int = 4) -> List[Dict[str, Any]]:
    """Retrieve relevant chunks from Qdrant vector store."""
    if not collection_name:
        raise ValueError("collectionName is required for retrieval")

    client = get_qdrant_client()
    query_vector = get_embedding(query)

    try:
        results = client.query_points(
            collection_name=collection_name,
            query=query_vector,
            limit=limit,
            with_payload=True,
        )
        points = results.points
    except Exception as error:
        err_msg = str(error)
        if "Vector dimension error" in err_msg or "dimension mismatch" in err_msg.lower():
            mismatch_err = RuntimeError("QDRANT_DIMENSION_MISMATCH: Vector dimension error")
            setattr(mismatch_err, "code", "QDRANT_DIMENSION_MISMATCH")
            setattr(mismatch_err, "details", {"message": err_msg})
            raise mismatch_err from error
        raise error

    docs = []
    for point in points:
        payload = point.payload or {}
        text = (
            payload.get("page_content")
            or payload.get("text")
            or payload.get("content")
            or ""
        )
        score = float(point.score) if point.score is not None else 0.0
        docs.append({
            "chunk_text": text,
            "score": score,
            "payload": payload,
        })

    return docs


def ask(
    query: str,
    opts: Optional[Dict[str, Any]] = None,
    *,
    collection_name: Optional[str] = None,
    course_name: Optional[str] = None,
    model: Optional[str] = None,
    limit: int = 4,
) -> Dict[str, Any]:
    """
    Ported ask() function.
    Uses Nomic embeddings, Qdrant similarity search, and Groq for chat completions.
    """
    opts = opts or {}
    collection = collection_name or opts.get("collectionName") or opts.get("collection_name")
    course = course_name or opts.get("courseName") or opts.get("course_name") or ""
    chosen_model = model or opts.get("model") or get_default_groq_model()

    if not collection:
        raise ValueError("collectionName is required for retrieval")

    start_time = time.time()

    # 1. Retrieve context from Qdrant
    docs = similarity_search(collection_name=collection, query=query, limit=limit)
    context = "\n\n".join(d["chunk_text"] for d in docs if d.get("chunk_text"))[:3000]

    # 2. Build Prompts
    system_prompt = get_system_prompt(course_name=course)
    user_prompt = f"Context (from course materials):\n{context}\n\nQuestion: {query}"

    # 3. LLM Completion via Groq
    groq = get_groq_client()
    completion = groq.chat.completions.create(
        model=chosen_model,
        temperature=0.2,
        max_tokens=500,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    answer = (completion.choices[0].message.content or "").strip()
    latency_ms = int((time.time() - start_time) * 1000)

    sources = [Source(chunk_text=d["chunk_text"], score=d["score"]) for d in docs if d.get("chunk_text")]
    confidence = (sum(d["score"] for d in docs) / len(docs)) if docs else 1.0

    return {
        "answer": answer,
        "sources": [s.model_dump() for s in sources],
        "confidence": confidence,
        "meta": {
            "latencyMs": latency_ms,
            "course": course,
            "collection": collection,
            "model": chosen_model,
            "chunks_retrieved": len(docs),
        },
    }


def query_rag(request: RagQueryRequest) -> RagQueryResponse:
    """Helper method to process a RagQueryRequest schema and return a RagQueryResponse."""
    course = request.course_name or request.course_id or ""
    result = ask(
        query=request.query,
        collection_name=request.collection_name,
        course_name=course,
        model=request.model,
    )
    return RagQueryResponse(
        answer=result["answer"],
        sources=[Source(**s) for s in result["sources"]],
        confidence=result["confidence"],
        meta=result["meta"],
    )
