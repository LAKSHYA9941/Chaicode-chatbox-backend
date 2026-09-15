from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class RagQueryRequest(BaseModel):
    query: str
    collection_name: str
    course_id: Optional[str] = ""
    course_name: Optional[str] = ""
    model: Optional[str] = None
    class_filter: Optional[str] = None
    subject_filter: Optional[str] = None

class Source(BaseModel):
    chunk_text: str
    score: float

class RagQueryResponse(BaseModel):
    answer: str
    sources: List[Source] = Field(default_factory=list)
    confidence: float = 1.0
    meta: Dict[str, Any] = Field(default_factory=dict)

class IngestRequest(BaseModel):
    course_id: str
    collection_name: str
    file_paths: Optional[List[str]] = Field(default_factory=list)
    files: Optional[List[Any]] = Field(default_factory=list)
    force_recreate: bool = False


class IngestResponse(BaseModel):
    upserted: int
    processed_files: int = Field(alias="processedFiles")
    total_files: int = Field(alias="totalFiles")

    class Config:
        populate_by_name = True
