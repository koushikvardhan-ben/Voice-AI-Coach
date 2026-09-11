import time
from uuid import uuid4
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from app import db

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


class DocumentInput(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=12000)


@router.get("")
def documents():
    return db.list_records("knowledge")


@router.post("", status_code=201)
def create_document(body: DocumentInput):
    if not body.title.strip() or not body.content.strip():
        raise HTTPException(422, "Document title and content are required.")
    return db.save_record("knowledge", {**body.model_dump(), "id": str(uuid4()), "created_at": time.time()})


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: str):
    if not db.delete_record("knowledge", document_id):
        raise HTTPException(404, "Document not found.")
    for agent in db.list_records("agents"):
        if document_id in agent["knowledge_ids"]:
            agent["knowledge_ids"].remove(document_id)
            db.save_record("agents", agent)
