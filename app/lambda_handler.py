"""AWS Lambda entry point.

Two kinds of events reach the same function:
- HTTP requests from the function URL (via CloudFront) -> FastAPI through Mangum
- {"resume_tailor_task": "analyze", "job_id": ...} -> the slow Claude analysis,
  run as an asynchronous self-invocation so no HTTP request has to wait on it
  (CloudFront gives up on an origin after 60s; a long resume can take longer).
  These can only come from an IAM-authorised Invoke call -- a function URL
  request is always an HTTP event, so it can never take this branch.
"""

from mangum import Mangum

from app.main import app
from app.routes.jobs import run_analysis

_http = Mangum(app, lifespan="off")


def handler(event, context):
    if isinstance(event, dict) and event.get("resume_tailor_task") == "analyze":
        run_analysis(event["job_id"])
        return {"ok": True}
    return _http(event, context)
