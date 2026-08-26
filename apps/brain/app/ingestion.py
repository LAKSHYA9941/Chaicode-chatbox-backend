import asyncio
from datetime import datetime, timezone
import inspect
import io
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union
import uuid

from dotenv import find_dotenv, load_dotenv
from langchain_text_splitters import RecursiveCharacterTextSplitter
from nomic import embed
from qdrant_client.http import models
import webvtt

from app.rag import ensure_nomic_auth, get_embedding_model, get_qdrant_client

# Load environment variables
load_dotenv(find_dotenv(usecwd=True))

EMBEDDING_DIMS = int(os.getenv("NOMIC_EMBEDDING_DIMS", 768))

# Splitter configuration matching ingestionService.js
splitter = RecursiveCharacterTextSplitter(
    chunk_size=400,
    chunk_overlap=60,
    separators=["\n\n", "\n", " ", ""],
)


def ensure_collection(
    collection_name: str,
    force_recreate: bool = False,
    embedding_dims: int = EMBEDDING_DIMS,
) -> None:
    """Ensure Qdrant collection exists with proper vector dimension configuration."""
    client = get_qdrant_client()
    needs_create = False

    if force_recreate:
        try:
            client.delete_collection(collection_name)
            print(f"🔁 Recreating Qdrant collection '{collection_name}' as requested.")
        except Exception:
            pass
        needs_create = True

    if not force_recreate:
        try:
            info = client.get_collection(collection_name)
            current_size = None
            if hasattr(info.config.params, "vectors"):
                vectors_param = info.config.params.vectors
                if hasattr(vectors_param, "size"):
                    current_size = vectors_param.size
                elif isinstance(vectors_param, dict) and "size" in vectors_param:
                    current_size = vectors_param["size"]

            if current_size and int(current_size) != embedding_dims:
                print(
                    f"Recreating Qdrant collection '{collection_name}' due to vector size mismatch "
                    f"(existing: {current_size}, expected: {embedding_dims})."
                )
                client.delete_collection(collection_name)
                needs_create = True
        except Exception:
            needs_create = True

    if needs_create:
        client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(
                size=embedding_dims,
                distance=models.Distance.COSINE,
            ),
        )


def parse_vtt_content(content: str) -> str:
    """Parse WebVTT content using webvtt-py and return cleaned captions as a single text."""
    if not content or not content.strip():
        return ""
    try:
        parsed = webvtt.from_string(content)
    except Exception:
        parsed = webvtt.read_buffer(io.StringIO(content))

    lines = [
        caption.text.strip()
        for caption in parsed
        if caption.text and caption.text.strip()
    ]
    return "\n".join(lines)


def parse_vtt_file(file_path: Union[str, Path]) -> str:
    """Read and parse a .vtt file from disk."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    raw_content = path.read_text(encoding="utf-8", errors="ignore")
    return parse_vtt_content(raw_content)


def embed_documents(
    texts: List[str],
    model: Optional[str] = None,
) -> List[List[float]]:
    """Embed multiple texts using Nomic embed with search_document task type."""
    if not texts:
        return []
    ensure_nomic_auth()
    embedding_model = model or get_embedding_model()
    output = embed.text(
        texts=texts,
        model=embedding_model,
        task_type="search_document",
    )

    return output["embeddings"]


def ingest_vtt_files(
    course: Optional[Dict[str, Any]] = None,
    files: Optional[List[Any]] = None,
    force_recreate: bool = False,
    on_progress: Optional[Callable[[Dict[str, Any]], Any]] = None,
    *,
    collection_name: Optional[str] = None,
    course_id: Optional[str] = None,
) -> Dict[str, int]:
    """
    Synchronous ingestion function using Nomic Embeddings and Qdrant.
    
    Args:
        course: Dict with course metadata (courseId, qdrantCollection / name)
        files: List of file descriptors (dicts with path/originalname, file paths, or (name, content) tuples)
        force_recreate: Whether to recreate collection
        on_progress: Progress callback
        collection_name: Direct collection name override
        course_id: Direct course id override
    """
    course = course or {}
    files = files or []

    target_collection = (
        collection_name
        or course.get("qdrantCollection")
        or course.get("collection_name")
        or course.get("collectionName")
    )
    if not target_collection:
        raise ValueError("course.qdrantCollection required")

    target_course_id = (
        course_id
        or course.get("courseId")
        or course.get("course_id")
        or ""
    )

    client = get_qdrant_client()
    ensure_collection(target_collection, force_recreate=force_recreate)

    total_docs = 0
    processed_files = 0
    total_files = len(files)

    for f in files:
        raw_text = ""
        file_name = ""

        if isinstance(f, (str, Path)):
            file_path = Path(f)
            file_name = file_path.name
            raw_text = parse_vtt_file(file_path)
        elif isinstance(f, dict):
            file_path_str = f.get("path")
            file_name = f.get("originalname") or f.get("filename") or (Path(file_path_str).name if file_path_str else f"file-{processed_files + 1}.vtt")
            if f.get("content"):
                raw_text = parse_vtt_content(f["content"])
            elif file_path_str:
                raw_text = parse_vtt_file(file_path_str)
        elif isinstance(f, tuple) and len(f) >= 2:
            file_name = str(f[0])
            raw_text = parse_vtt_content(str(f[1]))

        if not raw_text.strip():
            continue

        processed_files += 1

        # Split text into chunks
        metadata = {"courseId": target_course_id, "file": file_name}
        docs = splitter.create_documents([raw_text], metadatas=[metadata])
        chunk_texts = [d.page_content.strip() for d in docs if d.page_content.strip()]

        if chunk_texts:
            # Embed all chunks with Nomic
            vectors = embed_documents(chunk_texts)

            # Build PointStruct points
            points = [
                models.PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vec,
                    payload={
                        "courseId": target_course_id,
                        "file": file_name,
                        "text": chunk_texts[i],
                        "page_content": chunk_texts[i],
                        "metadata": docs[i].metadata,
                    },
                )
                for i, vec in enumerate(vectors)
            ]

            client.upsert(collection_name=target_collection, points=points)
            total_docs += len(points)

        print(
            f"[ingest] {target_course_id}: processed {processed_files}/{total_files} -> "
            f"{file_name} ({len(chunk_texts)} chunks, total {total_docs})"
        )

        if on_progress and callable(on_progress):
            progress_payload = {
                "courseId": target_course_id,
                "fileIndex": processed_files,
                "totalFiles": total_files,
                "fileName": file_name,
                "docs": len(chunk_texts),
                "totalDocs": total_docs,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            if inspect.iscoroutinefunction(on_progress):
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(on_progress(progress_payload))
                    else:
                        loop.run_until_complete(on_progress(progress_payload))
                except RuntimeError:
                    asyncio.run(on_progress(progress_payload))
            else:
                on_progress(progress_payload)

    if on_progress and callable(on_progress):
        final_payload = {
            "courseId": target_course_id,
            "fileIndex": processed_files,
            "totalFiles": total_files,
            "fileName": None,
            "docs": 0,
            "totalDocs": total_docs,
            "done": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if inspect.iscoroutinefunction(on_progress):
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(on_progress(final_payload))
                else:
                    loop.run_until_complete(on_progress(final_payload))
            except RuntimeError:
                asyncio.run(on_progress(final_payload))
        else:
            on_progress(final_payload)

    return {
        "upserted": total_docs,
        "processedFiles": processed_files,
        "totalFiles": total_files,
    }


async def async_ingest_vtt_files(
    course: Optional[Dict[str, Any]] = None,
    files: Optional[List[Any]] = None,
    force_recreate: bool = False,
    on_progress: Optional[Callable[[Dict[str, Any]], Any]] = None,
    *,
    collection_name: Optional[str] = None,
    course_id: Optional[str] = None,
) -> Dict[str, int]:
    """Async wrapper for ingest_vtt_files."""
    return await asyncio.to_thread(
        ingest_vtt_files,
        course=course,
        files=files,
        force_recreate=force_recreate,
        on_progress=on_progress,
        collection_name=collection_name,
        course_id=course_id,
    )
