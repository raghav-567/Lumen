"""Local NLI model wrapper using DeBERTa for contradiction detection."""

from __future__ import annotations

import logging
from functools import lru_cache

import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification

logger = logging.getLogger(__name__)

MODEL_NAME = "cross-encoder/nli-deberta-v3-small"
# Label mapping: 0=contradiction, 1=entailment, 2=neutral
LABEL_MAP = {0: "contradiction", 1: "entailment", 2: "neutral"}


@lru_cache(maxsize=1)
def _load_nli_model():
    """Load the NLI model and tokenizer (cached)."""
    logger.info("Loading NLI DeBERTa model...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)
    model.eval()
    return tokenizer, model


def classify_claim_pairs(pairs: list[tuple[str, str]]) -> list[dict]:
    """Run batched NLI classification on (premise, hypothesis) pairs.

    Returns list of dicts with keys: label, score, scores.
    """
    if not pairs:
        return []

    tokenizer, model = _load_nli_model()

    results = []
    batch_size = 16

    for i in range(0, len(pairs), batch_size):
        batch = pairs[i:i + batch_size]
        premises = [p[0] for p in batch]
        hypotheses = [p[1] for p in batch]

        inputs = tokenizer(
            premises, hypotheses,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=512,
        )

        with torch.no_grad():
            outputs = model(**inputs)
            logits = outputs.logits
            probs = torch.softmax(logits, dim=-1)

        for j in range(len(batch)):
            scores = probs[j].tolist()
            label_idx = int(torch.argmax(probs[j]).item())
            label = LABEL_MAP.get(label_idx, "neutral")

            results.append({
                "label": label,
                "score": float(scores[label_idx]),
                "scores": {
                    "contradiction": float(scores[0]),
                    "entailment": float(scores[1]),
                    "neutral": float(scores[2]),
                },
            })

    return results
