import time
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from app import db

router = APIRouter(prefix="/api/agents", tags=["agents"])


class AgentInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=240)
    role: Literal["buyer", "seller", "unknown"] = "buyer"
    instructions: str = Field(default="", max_length=6000)
    language: Literal["en-IN", "en-US", "en-GB", "hi", "multi"] = "en-IN"
    knowledge_ids: list[str] = Field(default_factory=list, max_length=12)
    keyterms: list[str] = Field(default_factory=list, max_length=20)


def validate_input(body):
    if not body.name.strip():
        raise HTTPException(422, "A profile name is required.")
    if any(not db.get_record("knowledge", key) for key in body.knowledge_ids):
        raise HTTPException(422, "One of the selected knowledge documents no longer exists.")
    body.keyterms = list(dict.fromkeys(term.strip() for term in body.keyterms if term.strip()))
    if any(len(term) > 40 for term in body.keyterms) or sum(map(len, body.keyterms)) > 200:
        raise HTTPException(422, "Recognition hints must be short names: 40 characters each, 200 in total.")


@router.get("")
def agents():
    return db.list_records("agents")


@router.post("", status_code=201)
def create_agent(body: AgentInput):
    validate_input(body)
    return db.save_record("agents", {**body.model_dump(), "name": body.name.strip(), "id": str(uuid4()), "created_at": time.time()})


@router.put("/{agent_id}")
def update_agent(agent_id: str, body: AgentInput):
    original = db.get_record("agents", agent_id)
    if not original:
        raise HTTPException(404, "Coaching profile not found.")
    validate_input(body)
    return db.save_record("agents", {**original, **body.model_dump(), "name": body.name.strip()})


@router.delete("/{agent_id}", status_code=204)
def delete_agent(agent_id: str):
    if not db.delete_record("agents", agent_id):
        raise HTTPException(404, "Coaching profile not found.")
