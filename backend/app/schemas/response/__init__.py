"""
app/schemas/response

Marshmallow response serialisation schemas.

These schemas govern what fields are included in API responses.
They are distinct from request schemas (app/schemas/) which govern
what fields are accepted as input.

Separation rationale:
  - Input schemas: strict validation, required fields, type coercion.
  - Output schemas: field selection, formatting, nested embedding.
  - Keeping them separate means changing an output shape never affects
    input validation, and vice versa.

Usage:
    from app.schemas.response import JobResponseSchema, ResumeListSchema

    schema  = JobResponseSchema()
    payload = schema.dump(job_model)
"""

from .candidate   import CandidateResponseSchema, CandidateListSchema
from .recruiter   import RecruiterResponseSchema, RecruiterListSchema
from .job         import JobResponseSchema, JobListSchema
from .resume      import ResumeResponseSchema, ResumeListSchema, ResumeAnalysisSchema
from .application import ApplicationResponseSchema, ApplicationListSchema
from .ats_score   import AtsScoreResponseSchema, AtsScoreSummarySchema

__all__ = [
    "CandidateResponseSchema", "CandidateListSchema",
    "RecruiterResponseSchema", "RecruiterListSchema",
    "JobResponseSchema",        "JobListSchema",
    "ResumeResponseSchema",     "ResumeListSchema",     "ResumeAnalysisSchema",
    "ApplicationResponseSchema","ApplicationListSchema",
    "AtsScoreResponseSchema",   "AtsScoreSummarySchema",
]
