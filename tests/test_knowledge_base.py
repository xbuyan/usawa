"""
Knowledge-base retrieval tests.

The retrieval layer is the grounding seam for the assistant — if it
returns the wrong documents, the chatbot sounds authoritative about the
wrong thing. These tests pin the retrieval behavior that matters:
distinctive questions find the right document, near-duplicate wording
finds it too, and irrelevant questions return nothing (the honest
no-match path) rather than the least-bad guess.
"""

from knowledge_base import retrieve, KnowledgeBase
from kb_documents import KB_DOCUMENTS


def test_inclusive_posting_question_retrieves_posting_guidance():
    # The canonical demo question — must hit the posting doc, not something
    # loosely related like structured interviews.
    docs = retrieve("How do I write an inclusive job posting for a senior engineer role?")
    assert docs, "expected at least one retrieved document"
    assert docs[0]["doc_id"] in ("job-postings-gender", "job-postings-example-senior-engineer")


def test_four_fifths_question_retrieves_four_fifths_doc():
    docs = retrieve("What is the four fifths rule and when does adverse impact apply?")
    assert docs
    assert docs[0]["doc_id"] == "four-fifths-rule"


def test_paraphrased_question_still_retrieves_right_doc():
    # Different wording than the tags, same intent — the content-term
    # TF-IDF path must carry this, not just the curated tag synonyms.
    docs = retrieve("our interview stage numbers look bad for women applicants, what should we change")
    assert docs
    top_ids = {d["doc_id"] for d in docs[:2]}
    assert top_ids & {"structured-interviews", "four-fifths-rule", "inclusive-recruitment-sourcing"}


def test_no_match_returns_empty_list_not_least_bad_guess():
    # An irrelevant question must produce NO grounding — the chatbot's
    # honest fallback depends on retrieval refusing to guess.
    docs = retrieve("what is the capital of France")
    assert docs == []


def test_off_topic_corporate_question_returns_nothing():
    docs = retrieve("please renew my parking permit for the office garage")
    assert docs == []


def test_every_kb_document_is_reachable_by_some_question():
    # Guards against a doc added with tags so narrow nothing ever
    # retrieves it — silent dead weight in the corpus.
    kb = KnowledgeBase()
    probe_queries = {
        "job-postings-gender": "gendered wording in job adverts",
        "job-postings-example-senior-engineer": "example posting for a senior engineer role",
        "four-fifths-rule": "eeoc 80 percent selection rate rule",
        "structured-interviews": "should we use structured interviews with a rubric",
        "pay-equity-methodology": "regression adjusted pay gap methodology",
        "promotion-equity-calibration": "promotion calibration meetings time to promotion",
        "representation-pipeline": "representation drop off across levels leaky pipeline",
        "kenya-context": "kenya data protection act employment context",
        "benchmark-interpretation": "how do I read peer benchmark percentiles",
        "inclusive-recruitment-sourcing": "sourcing more applicants referral hiring",
        "retention-inclusion": "attrition retention stay interviews sponsorship",
        "metrics-program-setup": "how often should we re run the audit metrics cadence",
        "accessibility-interviews": "accommodations for disabled candidates in interviews",
        "ergs-and-engagement": "employee resource groups budget sponsor",
        "data-privacy-employee-csv": "is employee csv data personal data privacy",
    }
    missing = []
    for doc in KB_DOCUMENTS:
        probe = probe_queries.get(doc["id"])
        if not probe:
            continue  # new doc without a probe yet — flagged separately
        ids = {d["doc_id"] for d in kb.search(probe, top_k=5)}
        if doc["id"] not in ids:
            missing.append(doc["id"])
    assert not missing, f"docs no question can reach: {missing}"


def test_retrieval_never_raises():
    # Garbage inputs degrade to empty results, never exceptions — the
    # chat endpoint depends on that contract.
    assert retrieve("") == []
    assert retrieve(None) == []
    assert retrieve("!!!") == []
