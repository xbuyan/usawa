"""
AI insights generation — server-side so the API key never reaches the browser.
"""

import os
import json
import time

import anthropic

SYSTEM_PROMPT = """You are a DEI data analyst producing recommendations for HR leaders. You will
receive a JSON object with equity scores and underlying metrics for a company.

Some metrics (promotion_equity, hiring_funnel) include a `four_fifths_ratio`
and `passes_four_fifths_rule` field. This refers to the EEOC's four-fifths
rule (29 CFR 1607.4(D)) for adverse impact screening: a selection rate below
80% of the highest group's rate is generally regarded as evidence of adverse
impact. When a metric fails this rule, cite it explicitly and accurately —
e.g. "this hiring stage falls below the EEOC's four-fifths threshold used in
adverse impact analysis." Do not apply this citation to metrics that don't
include these fields (pay_equity and representation_pipeline are not governed
by the four-fifths rule — describe those as practice-based observations, not
regulatory findings).

Your job:
1. Identify the 2-3 most significant gaps (lowest scores, or scores that are
   fine but hide a concerning underlying metric like time-to-promotion).
2. For each, explain WHY this pattern typically occurs (common root causes),
   grounded in the specific numbers given — do not make up causes not
   supported by the data.
3. Give 1-2 concrete, actionable fixes per gap. Fixes must be specific enough
   to assign to an owner (e.g. "Require structured interview scorecards for
   all senior engineering hires" not "improve hiring practices").
4. Do not diagnose intent or accuse anyone of bias — describe patterns and
   structural causes, not individual blame.
5. Output valid JSON only, no preamble, no markdown formatting, matching this
   schema:

{
  "headline_summary": "string, 2-3 sentences",
  "top_findings": [
    {
      "area": "string",
      "score": number,
      "why_it_matters": "string",
      "likely_cause": "string",
      "recommended_fix": "string",
      "priority": "high" | "medium" | "low"
    }
  ],
  "quick_win": "string — one thing they could fix this week"
}"""

MODEL = "claude-sonnet-5"
MAX_RETRIES = 3


class InsightsGenerationError(Exception):
    pass


def generate_insights(scorecard: dict, company_size=None, industry=None, benchmarks=None) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise InsightsGenerationError(
            "ANTHROPIC_API_KEY is not set on the server. Add it to your environment variables."
        )

    client = anthropic.Anthropic(api_key=api_key)

    payload = {
        "company_size": company_size,
        "industry": industry,
        "scores": scorecard["sub_scores"],
        "raw_metrics": {
            area: {k: v for k, v in detail.items() if k != "score"}
            for area, detail in scorecard["details"].items()
        },
    }
    if benchmarks:
        payload["industry_benchmarks"] = benchmarks

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=1000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": json.dumps(payload)}],
            )
            raw_text = response.content[0].text.strip()
            if raw_text.startswith("```"):
                raw_text = raw_text.strip("`")
                raw_text = raw_text.replace("json\n", "", 1).strip()
            return json.loads(raw_text)

        except json.JSONDecodeError as e:
            last_error = e
            if attempt == MAX_RETRIES:
                raise InsightsGenerationError(
                    f"Model did not return valid JSON after {MAX_RETRIES} attempts."
                ) from e

        except anthropic.APIError as e:
            last_error = e
            if attempt == MAX_RETRIES:
                raise InsightsGenerationError(f"API call failed: {e}") from e

        time.sleep(2 ** attempt)

    raise InsightsGenerationError(f"Unexpected failure: {last_error}")
