"""
The DEI assistant: retrieval-grounded chat over the curated knowledge base.

Pipeline for every question:
  1. Retrieve the top KB documents for the question (knowledge_base.py).
  2. Build a Claude prompt: strict system prompt + retrieved docs (verbatim)
     + recent conversation turns + the question, optionally with the user's
     current scorecard position and any applicable learned patterns.
  3. Call Claude with retries/backoff (same pattern as ai_insights.py),
     asking for plain prose with [source: doc_id] citations.
  4. Return the answer text plus the structured source list for the UI.

Design decisions worth knowing:
- Grounding is mandatory: when retrieval finds nothing relevant, we do
  NOT send Claude in with an empty context to freestyle. The answer comes
  back as answered=False with an honest message, and (critically, since
  users phrase things unexpectedly) Claude still sees the question and
  can respond — but is told to say it doesn't have vetted guidance. Both
  paths are handled by one prompt; the difference is what's in context.
- Conversation history is truncated to the last few turns to keep the
  prompt (and token spend) bounded no matter how long a conversation runs.
- The scorecard context is deliberately compact: numbers, not the whole
  JSON blob — the assistant answers questions about the user's results,
  it is not a JSON formatter.
"""

import json
import os
import time
from typing import Dict, List, Optional

import anthropic

from knowledge_base import retrieve

# Model is a deploy lever: ops can switch it from the Render dashboard
# (ANTHROPIC_MODEL) without a code change when a model is retired or a
# cheaper/better one ships. Falls back to the current default.
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
MAX_RETRIES = 3
MAX_HISTORY_TURNS = 6          # last N (user, assistant) turns sent to the model
MAX_QUESTION_CHARS = 2000      # prompt-injection surface cap on user input
MAX_HISTORY_CHARS = 6000       # overall budget for history in the prompt

SYSTEM_PROMPT = """You are Usawa's DEI assistant, answering questions from HR teams and \
company leaders about workplace equity: hiring, pay, promotion, representation, and \
related practice. You are grounded in a curated knowledge base of vetted guidance \
documents provided to you in each request.

Rules:
1. Base your answer on the KNOWLEDGE BASE DOCUMENTS provided. Cite the documents you \
used inline like [source: doc_id] at the point where you rely on them. You may cite \
several.
2. If the documents don't cover the question, say plainly that you don't have vetted \
guidance on it, share only what you can state confidently and generally, and do not \
invent statistics, legal citations, or specifics. Never present general knowledge as \
if it came from the knowledge base.
3. Legal care: the four-fifths rule (29 CFR 1607.4(D)) is a screening standard, not a \
statute with penalties. Never state that a score or ratio is a legal violation. \
Recommend qualified legal counsel for anything that sounds like a legal conclusion.
4. Be concrete and actionable: HR teams want steps they can take, owners they can \
assign, and the metric that would show the fix worked.
5. If scorecard data or learned patterns about the user's company are provided, use \
them to make the answer specific — but treat mined patterns as correlations, not \
causes.
6. Answer in plain prose with short paragraphs or lists. No markdown headers, no JSON.
7. Keep answers under roughly 250 words unless the question genuinely needs more."""


class ChatGenerationError(Exception):
    pass


def _build_context_block(scorecard: Optional[Dict], patterns: Optional[List[Dict]]) -> str:
    """Compact, read-only context about THIS user's position. Built only from
    numbers the user's own account already produced — never other companies'
    raw data (patterns are already cohort-level and anonymized upstream)."""
    parts = []
    if scorecard:
        try:
            compact = {
                "overall_score": scorecard.get("overall_score"),
                "sub_scores": scorecard.get("sub_scores", {}),
            }
            details = scorecard.get("details", {})
            ff_flags = {}
            for area, d in details.items():
                if isinstance(d, dict) and "passes_four_fifths_rule" in d:
                    ff_flags[area] = d["passes_four_fifths_rule"]
            if ff_flags:
                compact["four_fifths_flags"] = ff_flags
            parts.append("THE USER'S CURRENT SCORECARD:\n" + json.dumps(compact))
        except Exception:
            pass  # a malformed scorecard must never break the chat
    if patterns:
        try:
            lines = [
                f"- {p['statement']} (based on {p['n_companies']} companies)"
                for p in patterns[:3]
            ]
            parts.append(
                "LEARNED PATTERNS FROM ANONYMIZED PEER DATA (correlations, not causes):\n"
                + "\n".join(lines)
            )
        except Exception:
            pass
    return "\n\n".join(parts)


def _trim_history(messages: List[Dict]) -> List[Dict]:
    """Keep the last MAX_HISTORY_TURNS turns, each capped in size, so prompt
    cost is bounded for conversations that run long."""
    if not messages:
        return []
    trimmed = []
    total = 0
    for m in reversed(messages[-MAX_HISTORY_TURNS * 2:]):
        content = str(m.get("content", ""))[:MAX_QUESTION_CHARS]
        total += len(content)
        if total > MAX_HISTORY_CHARS:
            break
        trimmed.append({"role": m.get("role"), "content": content})
    return list(reversed(trimmed))


def answer_question(
    question: str,
    history: Optional[List[Dict]] = None,
    scorecard: Optional[Dict] = None,
    patterns: Optional[List[Dict]] = None,
) -> Dict:
    """
    question:  the user's new message.
    history:   prior turns as [{"role": "user"|"assistant", "content": str}],
               oldest first. Assistant turns here are the stored text only.
    scorecard: optional current scorecard (see _build_context_block).
    patterns:  optional learned patterns [{statement, n_companies}].

    Returns {"answer", "sources": [{doc_id, title}], "grounded": bool}.
    Raises ChatGenerationError only when the API genuinely fails after
    retries — a no-match question is a normal answer, not an error.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ChatGenerationError(
            "ANTHROPIC_API_KEY is not set on the server. Add it to your environment variables."
        )

    question = (question or "").strip()[:MAX_QUESTION_CHARS]
    if not question:
        raise ChatGenerationError("Empty question.")

    docs = retrieve(question, top_k=3)
    grounded = bool(docs)

    user_blocks = []
    context_block = _build_context_block(scorecard, patterns)
    if context_block:
        user_blocks.append({"type": "text", "text": context_block})

    if docs:
        kb_text = "\n\n---\n\n".join(
            f"DOCUMENT id={d['doc_id']}\nTITLE: {d['title']}\nCONTENT:\n{d['content']}"
            for d in docs
        )
        user_blocks.append({
            "type": "text",
            "text": "KNOWLEDGE BASE DOCUMENTS (your grounding — cite what you use):\n\n" + kb_text,
        })
    else:
        user_blocks.append({
            "type": "text",
            "text": (
                "NO knowledge base documents matched this question. Per your rules: say "
                "plainly that you don't have vetted guidance on this topic, and share only "
                "confident, general information without invented specifics or citations."
            ),
        })

    user_blocks.append({"type": "text", "text": "QUESTION: " + question})

    api_messages = _trim_history(history or [])
    api_messages.append({"role": "user", "content": user_blocks})

    client = anthropic.Anthropic(api_key=api_key)
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=700,
                system=SYSTEM_PROMPT,
                messages=api_messages,
            )
            answer = response.content[0].text.strip()
            if not answer:
                raise ChatGenerationError("Model returned an empty answer.")
            return {
                "answer": answer,
                "sources": [{"doc_id": d["doc_id"], "title": d["title"]} for d in docs],
                "grounded": grounded,
            }
        except anthropic.APIError as e:
            last_error = e
            if attempt == MAX_RETRIES:
                raise ChatGenerationError(f"API call failed: {e}") from e
            time.sleep(2 ** attempt)
        except (KeyError, IndexError, TypeError) as e:
            # Malformed response shape is not worth retrying — same
            # conclusion as ai_insights.py's handling of broken payloads.
            raise ChatGenerationError(f"Unexpected model response shape: {e}") from e

    raise ChatGenerationError(f"Unexpected failure: {last_error}")
