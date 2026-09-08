"""
Request validation schemas.

Routes previously did manual dict.get() checks on request bodies, which
means a malformed request produces a confusing internal error (or worse,
silently does the wrong thing with missing fields defaulting to None)
instead of a clean, specific 400. These schemas make "what does a valid
request look like" explicit and enforced at the boundary, before any
business logic runs.
"""

from typing import Optional, Dict, List
from pydantic import BaseModel, EmailStr, Field, ValidationError


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=256)
    organization_name: Optional[str] = Field(default=None, max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=10, max_length=256)


class PromotionData(BaseModel):
    promotions_a: int = Field(ge=0)
    eligible_a: int = Field(ge=0)
    promotions_b: int = Field(ge=0)
    eligible_b: int = Field(ge=0)
    time_to_promotion_months: Optional[Dict[str, Optional[float]]] = None


class FunnelStage(BaseModel):
    applied: int = Field(default=0, ge=0)
    interviewed: int = Field(default=0, ge=0)
    offered: int = Field(default=0, ge=0)
    hired: int = Field(default=0, ge=0)


class HiringFunnelData(BaseModel):
    funnel_a: FunnelStage
    funnel_b: FunnelStage
    stages: Optional[List[str]] = None


class ScoreRequest(BaseModel):
    # All optional — calculate_scorecard() already handles partial data by
    # redistributing weights across whatever sections are present. This
    # schema just makes sure that whatever IS present is well-formed.
    pay_gap_by_level: Optional[Dict[str, float]] = None
    promotion: Optional[PromotionData] = None
    hiring_funnel: Optional[HiringFunnelData] = None
    representation_by_level: Optional[Dict[str, float]] = None
    job_postings: Optional[List[str]] = None


class InsightsRequest(BaseModel):
    scorecard: Dict
    company_size: Optional[int] = Field(default=None, ge=1)
    industry: Optional[str] = Field(default=None, max_length=100)
    benchmarks: Optional[Dict] = None


class SaveClientRequest(BaseModel):
    company_name: str = Field(default="Untitled", max_length=255)
    form: Dict = Field(default_factory=dict)
    scorecard: Dict = Field(default_factory=dict)
    insights: Optional[Dict] = None


def validation_error_response(exc: ValidationError) -> dict:
    """Turns a Pydantic ValidationError into a clean, field-level JSON error."""
    errors = []
    for err in exc.errors():
        field = ".".join(str(loc) for loc in err["loc"])
        errors.append({"field": field, "message": err["msg"]})
    return {"error": "Invalid request data.", "details": errors}
