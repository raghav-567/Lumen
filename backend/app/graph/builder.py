"""Knowledge graph builder using Gemini for entity/relation extraction."""

from __future__ import annotations

import json
import logging
from uuid import uuid4

from google import genai
from google.genai import types

from app.core.config import settings

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """Extract entities and relationships from this text. Focus on:
- People, organizations, policies, regulations, concepts, technologies
- Relationships like: DEFINES, REGULATES, CONTRADICTS, DEPENDS_ON, PART_OF, AUTHORED_BY

Text:
\"\"\"{text}\"\"\"

Respond in JSON:
{{
  "entities": [
    {{"name": "entity name", "type": "PERSON|ORGANIZATION|POLICY|CONCEPT|TECHNOLOGY|OTHER"}}
  ],
  "relations": [
    {{"source": "entity A name", "target": "entity B name", "type": "RELATION_TYPE", "confidence": 0.0-1.0}}
  ]
}}"""


def extract_entities_and_relations(text: str) -> dict:
    """Extract entities and relations from text using Gemini."""
    try:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=EXTRACTION_PROMPT.format(text=text[:3000]),
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=1000,
            ),
        )

        result_text = response.text.strip()
        if "```json" in result_text:
            result_text = result_text.split("```json")[1].split("```")[0].strip()
        elif "```" in result_text:
            result_text = result_text.split("```")[1].split("```")[0].strip()

        parsed = json.loads(result_text)
        return {
            "entities": parsed.get("entities", []),
            "relations": parsed.get("relations", []),
        }
    except Exception as e:
        logger.error(f"Entity extraction failed: {e}")
        return {"entities": [], "relations": []}


def build_graph_for_chunk(
    org_id: str,
    chunk_id: str,
    chunk_text: str,
    session,
) -> tuple[int, int]:
    """Extract entities/relations from a chunk and persist to DB."""
    from app.models.models import Entity, Relation

    result = extract_entities_and_relations(chunk_text)

    entity_name_map: dict[str, str] = {}
    entity_count = 0
    relation_count = 0

    for ent in result["entities"]:
        name = ent.get("name", "").strip()
        if not name:
            continue

        # Check if entity already exists
        existing = session.query(Entity).filter(
            Entity.org_id == org_id,
            Entity.name == name,
        ).first()

        if existing:
            entity_name_map[name] = str(existing.id)
        else:
            eid = uuid4()
            entity = Entity(
                id=eid,
                org_id=org_id,
                name=name,
                entity_type=ent.get("type", "OTHER"),
                source_chunk_id=chunk_id,
            )
            session.add(entity)
            entity_name_map[name] = str(eid)
            entity_count += 1

    session.flush()

    for rel in result["relations"]:
        source_name = rel.get("source", "").strip()
        target_name = rel.get("target", "").strip()

        source_id = entity_name_map.get(source_name)
        target_id = entity_name_map.get(target_name)

        if source_id and target_id and source_id != target_id:
            relation = Relation(
                id=uuid4(),
                org_id=org_id,
                source_entity_id=source_id,
                target_entity_id=target_id,
                relation_type=rel.get("type", "RELATED_TO"),
                source_chunk_id=chunk_id,
                confidence=float(rel.get("confidence", 0.8)),
            )
            session.add(relation)
            relation_count += 1

    return entity_count, relation_count
