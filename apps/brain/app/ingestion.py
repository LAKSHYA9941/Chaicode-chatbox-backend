"""
Ingestion pipeline for Sentinel Brain.
Parses Markdown (.md) documents and chunks them using a two-stage strategy:
1. Primary split along Markdown headers (##, ###, #, ####) to preserve semantically
   meaningful section boundaries (subsections, activities, topics).
2. Secondary split with RecursiveCharacterTextSplitter applied within sections
   only when a section exceeds target chunk size.
Embeds chunks using Nomic Embed and indexes them into Qdrant vector database.
"""

import argparse
import asyncio
from datetime import datetime, timezone
import inspect
import os
from pathlib import Path
import re
from typing import Any, Callable, Dict, List, Optional, Union
import uuid

from dotenv import find_dotenv, load_dotenv
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from nomic import embed
from qdrant_client.http import models

import sys

# Configure UTF-8 encoding on standard streams if possible, handling Windows consoles safely
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Ensure 'app' package is discoverable even when running directly as a script
_parent_dir = str(Path(__file__).resolve().parent.parent)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from app.rag import ensure_nomic_auth, get_embedding_model, get_qdrant_client


# Load environment variables
load_dotenv(find_dotenv(usecwd=True))

EMBEDDING_DIMS = int(os.getenv("NOMIC_EMBEDDING_DIMS", "768"))
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", os.getenv("MD_CHUNK_SIZE", "1000")))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", os.getenv("MD_CHUNK_OVERLAP", "150")))

# Default markdown header hierarchy for primary semantic segmentation
DEFAULT_HEADERS_TO_SPLIT_ON = [
    ("#", "Header 1"),
    ("##", "Header 2"),
    ("###", "Header 3"),
    ("####", "Header 4"),
]


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
            print(f"[qdrant] Recreating collection '{collection_name}' as requested.", flush=True)
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
                    f"(existing: {current_size}, expected: {embedding_dims}).",
                    flush=True,
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


def parse_md_content(content: str) -> str:
    """
    Normalize raw markdown content and clean common PDF-to-Markdown noise
    such as standalone page numbers and reprint footers.
    """
    if not content or not content.strip():
        return ""

    # Normalize carriage returns
    text = content.replace("\r\n", "\n").replace("\r", "\n")

    cleaned_lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        # Skip reprint markers (e.g., 'Reprint 2026-27')
        if re.match(r"^Reprint\s+\d{4}-\d{2}$", stripped, re.IGNORECASE):
            continue
        # Skip isolated page numbers (1-3 digits alone on a line)
        if stripped.isdigit() and len(stripped) <= 3:
            continue
        cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


def parse_md_file(file_path: Union[str, Path]) -> str:
    """Read and parse a .md file from disk."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Markdown file not found: {file_path}")
    raw_content = path.read_text(encoding="utf-8", errors="ignore")
    return parse_md_content(raw_content)


def chunk_markdown(
    text: str,
    headers_to_split_on: Optional[List[tuple]] = None,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
    base_metadata: Optional[Dict[str, Any]] = None,
) -> List[Document]:
    """
    Two-stage chunking strategy:
    1. Primary split along Markdown headers (##, ###, etc.) using MarkdownHeaderTextSplitter.
       Keeps whole subsections intact as semantically meaningful boundaries.
    2. Secondary split using RecursiveCharacterTextSplitter inside sections that exceed chunk_size.
    """
    cleaned_text = parse_md_content(text)
    if not cleaned_text.strip():
        return []

    headers = headers_to_split_on or DEFAULT_HEADERS_TO_SPLIT_ON
    markdown_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=headers,
        strip_headers=False,  # Retain heading in content for embedding/context preservation
    )
    header_docs = markdown_splitter.split_text(cleaned_text)

    # Secondary splitter for sections that exceed chunk_size
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", " ", ""],
    )
    split_docs = text_splitter.split_documents(header_docs)

    final_docs: List[Document] = []
    base_meta = base_metadata or {}

    for doc in split_docs:
        content = doc.page_content.strip()

        # Discard empty chunks or chunks consisting solely of markdown image tags and comments
        text_without_images = re.sub(r"!\[.*?\]\(.*?\)", "", content).strip()
        text_without_comments = re.sub(r"<!--.*?-->", "", text_without_images, flags=re.DOTALL).strip()
        if len(text_without_comments) < 15:
            continue

        merged_meta = dict(base_meta)
        merged_meta.update(doc.metadata)

        # Build hierarchical breadcrumb section if headers exist
        header_keys = sorted(
            [k for k in doc.metadata.keys() if k.startswith("Header ")],
            key=lambda x: int(x.split()[1]) if x.split()[1].isdigit() else 99,
        )
        section_titles = [doc.metadata[k] for k in header_keys if doc.metadata.get(k)]
        if section_titles:
            merged_meta["section"] = " > ".join(section_titles)
        elif "section" not in merged_meta:
            merged_meta["section"] = "Introduction"

        final_docs.append(
            Document(
                page_content=content,
                metadata=merged_meta,
            )
        )

    return final_docs


def embed_documents(
    texts: List[str],
    model: Optional[str] = None,
    batch_size: int = 64,
) -> List[List[float]]:
    """Embed multiple texts using Nomic embed with search_document task type in batches."""
    if not texts:
        return []
    ensure_nomic_auth()
    embedding_model = model or get_embedding_model()

    all_embeddings: List[List[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        output = embed.text(
            texts=batch,
            model=embedding_model,
            task_type="search_document",
        )
        all_embeddings.extend(output["embeddings"])

    return all_embeddings


def ingest_md_files(
    course: Optional[Dict[str, Any]] = None,
    files: Optional[Union[List[Any], str, Path]] = None,
    force_recreate: bool = False,
    on_progress: Optional[Callable[[Dict[str, Any]], Any]] = None,
    *,
    collection_name: Optional[str] = None,
    course_id: Optional[str] = None,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
    headers_to_split_on: Optional[List[tuple]] = None,
) -> Dict[str, Any]:
    """
    Synchronous ingestion function for Markdown (.md) files using Nomic Embeddings and Qdrant.

    Chunking approach:
      - Primary: split along Markdown headers (##, ###) first for semantically meaningful boundaries.
      - Secondary: split with RecursiveCharacterTextSplitter only within sections exceeding chunk_size.

    Args:
        course: Dict with course/subject metadata (courseId, qdrantCollection / name)
        files: List of file paths, directory path, file dicts (path/originalname/content), or (name, content) tuples
        force_recreate: Whether to recreate collection
        on_progress: Progress callback
        collection_name: Direct collection name override
        course_id: Direct course/subject id override
        chunk_size: Max characters per sub-chunk
        chunk_overlap: Overlap characters for recursive splitting
        headers_to_split_on: List of header tuples, e.g. [("#", "Header 1"), ("##", "Header 2"), ("###", "Header 3")]
    """
    course = course or {}
    target_collection = (
        collection_name
        or course.get("qdrantCollection")
        or course.get("collection_name")
        or course.get("collectionName")
    )
    if not target_collection:
        raise ValueError("collection_name or course.qdrantCollection required")

    target_course_id = (
        course_id
        or course.get("courseId")
        or course.get("course_id")
        or ""
    )

    # Normalize file inputs: support directory path, single file, or list
    file_items: List[Any] = []
    if isinstance(files, (str, Path)):
        p = Path(files)
        if p.is_dir():
            file_items = sorted(list(p.glob("*.md")))
        else:
            file_items = [p]
    elif isinstance(files, list):
        for item in files:
            if isinstance(item, (str, Path)):
                p = Path(item)
                if p.is_dir():
                    file_items.extend(sorted(list(p.glob("*.md"))))
                else:
                    file_items.append(p)
            else:
                file_items.append(item)
    elif files is None:
        file_items = []

    client = get_qdrant_client()
    ensure_collection(target_collection, force_recreate=force_recreate)

    total_docs = 0
    processed_files = 0
    total_files = len(file_items)

    for f in file_items:
        raw_text = ""
        file_name = ""

        if isinstance(f, (str, Path)):
            file_path = Path(f)
            file_name = file_path.name
            raw_text = parse_md_file(file_path)
        elif isinstance(f, dict):
            file_path_str = f.get("path")
            file_name = (
                f.get("originalname")
                or f.get("filename")
                or (Path(file_path_str).name if file_path_str else f"file-{processed_files + 1}.md")
            )
            if f.get("content"):
                raw_text = parse_md_content(f["content"])
            elif file_path_str:
                raw_text = parse_md_file(file_path_str)
        elif isinstance(f, tuple) and len(f) >= 2:
            file_name = str(f[0])
            raw_text = parse_md_content(str(f[1]))

        if not raw_text.strip():
            continue

        processed_files += 1

        # Two-stage Markdown Chunking
        docs = chunk_markdown(
            raw_text,
            headers_to_split_on=headers_to_split_on,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            base_metadata={"courseId": target_course_id, "file": file_name},
        )

        chunk_texts = [d.page_content.strip() for d in docs if d.page_content.strip()]

        if chunk_texts:
            # Batch embedding via Nomic
            vectors = embed_documents(chunk_texts)

            # Build PointStruct points with enriched metadata
            points = [
                models.PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vec,
                    payload={
                        "courseId": target_course_id,
                        "file": file_name,
                        "text": docs[i].page_content,
                        "page_content": docs[i].page_content,
                        "metadata": docs[i].metadata,
                        **docs[i].metadata,
                    },
                )
                for i, vec in enumerate(vectors)
            ]

            # Upsert points into Qdrant in batches of 100
            upsert_batch_size = 100
            for start_idx in range(0, len(points), upsert_batch_size):
                client.upsert(
                    collection_name=target_collection,
                    points=points[start_idx : start_idx + upsert_batch_size],
                )
            total_docs += len(points)

        print(
            f"[ingest] {target_course_id}: processed {processed_files}/{total_files} -> "
            f"{file_name} ({len(chunk_texts)} chunks, total {total_docs})",
            flush=True,
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


async def async_ingest_md_files(
    course: Optional[Dict[str, Any]] = None,
    files: Optional[Union[List[Any], str, Path]] = None,
    force_recreate: bool = False,
    on_progress: Optional[Callable[[Dict[str, Any]], Any]] = None,
    *,
    collection_name: Optional[str] = None,
    course_id: Optional[str] = None,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
    headers_to_split_on: Optional[List[tuple]] = None,
) -> Dict[str, Any]:
    """Async wrapper for ingest_md_files."""
    return await asyncio.to_thread(
        ingest_md_files,
        course=course,
        files=files,
        force_recreate=force_recreate,
        on_progress=on_progress,
        collection_name=collection_name,
        course_id=course_id,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        headers_to_split_on=headers_to_split_on,
    )


# ---------------------------------------------------------------------------
# Backward-compatibility aliases for legacy callers (main.py, Express bridges)
# ---------------------------------------------------------------------------
ingest_vtt_files = ingest_md_files
async_ingest_vtt_files = async_ingest_md_files
parse_vtt_content = parse_md_content
parse_vtt_file = parse_md_file


# ---------------------------------------------------------------------------
# CLI Execution Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest Markdown (.md) textbook files into Qdrant.")
    parser.add_argument(
        "--dir",
        type=str,
        default="data/seventh_mds/science",
        help="Directory containing .md files to ingest",
    )
    parser.add_argument(
        "--file",
        type=str,
        default=None,
        help="Single .md file to ingest",
    )
    parser.add_argument(
        "--collection",
        type=str,
        default="science_grade_7",
        help="Target Qdrant collection name",
    )
    parser.add_argument(
        "--course-id",
        type=str,
        default="ncert_science_7",
        help="Course or subject ID identifier",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Force recreate collection before ingestion",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=CHUNK_SIZE,
        help="Maximum characters per section chunk",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=CHUNK_OVERLAP,
        help="Overlap characters for recursive chunking",
    )

    args = parser.parse_args()
    target_files = args.file if args.file else args.dir

    print(f"[ingest] Starting ingestion for '{target_files}' into collection '{args.collection}'...", flush=True)
    res = ingest_md_files(
        collection_name=args.collection,
        course_id=args.course_id,
        files=target_files,
        force_recreate=args.recreate,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )
    print(f"[ingest] Ingestion complete: {res}", flush=True)
