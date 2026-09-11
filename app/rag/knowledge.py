"""Bounded lexical retrieval over the selected documents' call-time snapshot.

No embeddings or paid indexing service; keep the most relevant short passages
inside the live coach's token budget. This is intentionally a prototype retriever.
"""
import re


def relevant_context(context: str, transcript: str, max_chars: int = 4500) -> str:
    if len(context) <= max_chars:
        return context
    query = {word for word in re.findall(r"\w+", transcript.lower()) if len(word) > 2}
    chunks = [context[i:i + 900] for i in range(0, len(context), 900)]
    ranked = sorted(enumerate(chunks), key=lambda item: (-len(query.intersection(re.findall(r"\w+", item[1].lower()))), item[0]))
    chosen = sorted(ranked[:max(1, max_chars // 902)])
    return "\n\n".join(chunk for _, chunk in chosen)[:max_chars]
