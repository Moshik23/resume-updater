# Resume Updater

Upload a resume (.docx or .pdf) and paste a job description. The tool asks
Claude to find ATS-relevant keywords the resume is missing, flags real gaps
as follow-up questions, and produces a tailored `.docx` plus a plain-English
summary of every change:

- **.docx input** — edits are applied in place (existing runs are mutated,
  new bullets are cloned from an existing paragraph), so the original
  formatting is preserved.
- **.pdf input** — there's no editable layout to preserve, so the tool
  builds a clean, ATS-friendly `.docx` from scratch instead of attempting a
  fragile pixel-for-pixel PDF clone. This is intentional, not a limitation
  to work around.
- **Change summary** — after generating the resume, a "What changed" panel
  lists every applied edit (with the reasoning behind it), any job
  requirements still worth addressing, and requirements your resume already
  covers. Flip the "Show checklist" toggle to get a checkbox next to each
  item, for ticking off as you apply the same changes by hand. Also
  downloadable on its own as a `.md` file.
- **ATS match score** — a percentage of extracted job requirements the
  resume covers, shown right after analysis and again as a before → after
  comparison once the tailored resume is generated. Only counts a
  requirement as covered once an edit addressing it actually applied
  successfully — an edit that failed to apply doesn't inflate the score.
  Suggested-edit checkboxes and any manually-edited wording persist across
  repeated "Generate" clicks — answering one gap and regenerating doesn't
  silently re-check or reword edits you'd already toggled or edited by hand
  (`renderEdits()` in `static/app.js` diffs against the prior render instead
  of rebuilding from scratch each time).
- **Password-gated** — the whole site sits behind a single shared HTTP
  Basic Auth password (see Cost and security notes), so a stranger who
  finds the URL can't run up Anthropic API costs.
- **Optional cover letter** — on the upload page, choose whether you want a
  tailored resume, a cover letter, or both (at least one is required). The
  cover letter is a separate Claude call (`generate_cover_letter` in
  `app/claude_client.py`) grounded only in the resume's own content blocks
  plus any facts the candidate confirmed via gap answers — same
  no-fabrication rule as resume edits. Rendered as a plain `.docx`
  (`app/cover_letter.py`) and downloadable independently of the resume.
- **Named profiles** — this tool is shared between a small, known group of
  people (not the general public), so instead of full sign-up/login accounts
  there's a fixed picker: Moshik, Indhu, or Guest (`app/profiles.py`).
  Picking a profile does two things: it remembers your last-uploaded resume
  as your default (so you don't have to re-attach it every time — upload a
  new file whenever you want to replace it), and it scopes an optional
  **application tracker**. On the review step, check "Track this
  application" (company/role are pre-filled from the job description via
  the same Claude call that does gap analysis — left blank rather than
  guessed if the JD doesn't state them) to log an entry viewable later via
  "View my tracked applications". Both the default resume and the tracker
  live in a separate `profiles` Blob container that, unlike `jobs/`, is
  **not** on the 2-day auto-delete lifecycle — they persist until replaced.

## Multi-tenancy note

Profiles are a lightweight partition, not real authentication — anyone with
the shared site password can pick any profile. This only works because it's
shared with a small, known group of people. Don't extend this pattern to a
publicly-signed-up user base without adding real per-user auth (this was an
explicit, deliberate scope decision, not an oversight).

## Architecture

```
Browser (static HTML/CSS/JS, no framework/build step)
   │  https://resume.moshikseetloo.com  (Basic Auth password)
   ▼
CloudFront ── adds x-origin-secret, never caches, 60s origin timeout
   ▼
Lambda function URL ── one Python 3.12 function (FastAPI via Mangum)
   ├─ resume_ingest/   → extract flat {id, text} content blocks (docx or pdf)
   ├─ claude_client.py → forced tool-use call to Claude: gaps + suggested edits
   ├─ resume_apply/    → apply accepted edits (in-place docx, or rebuild for pdf)
   ├─ summary.py       → plain-English "what changed" report (markdown)
   └─ storage.py       → S3 (jobs/ expire after 2 days, profiles/ kept)
Secrets (Anthropic API key, site password) → SSM Parameter Store, read at cold start
```

**Background analysis.** The gap-analysis call can return up to 4k tokens and
take longer than CloudFront will hold a request open (60s), so `POST
/api/jobs` only validates and stores the inputs, then the function invokes
*itself* asynchronously to run the analysis (`app/lambda_handler.py`). The
page polls `GET /api/jobs/{id}` every 3s until it's `done` or `error`. Async
retries are switched off so a failure never bills Claude twice. Locally the
same flow runs as a FastAPI background task. The shorter calls (phrasing gap
answers, cover letter) stay synchronous; gap answers are phrased in parallel.

**History.** v1 ran on Azure (Container Apps, Blob Storage, Key Vault, Azure
DevOps with OIDC). When the Azure free account ended it was moved to AWS
serverless: same app code, storage and secrets swapped behind the existing
`storage.py`/`config.py` seams, and a pay-per-request host instead of a
container. The Azure version is in git history.

## Local development

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r app\requirements.txt
$env:PYTHONPATH = "."
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

Or just run `scripts\run_local.ps1`, which does the same thing. No AWS
account is needed for local dev — `storage.py` falls back to local
`.local_jobs/` and `.local_profiles/` directories when `S3_BUCKET_NAME` is
unset, and secrets come from env vars / `.env` when `SSM_PREFIX` is unset.

Set `ANTHROPIC_API_KEY` in your environment (or a `.env` file — already
gitignored) before hitting `/api/jobs`; without it the Claude call fails
cleanly with a 502 rather than crashing the server. `SITE_PASSWORD` is
optional locally — leave it unset and the password gate is a no-op, so
local dev is never blocked by it. `/healthz` is always exempt from the
gate (the pipeline's post-deploy smoke test hits it with no credentials).

Sample files for testing are in `samples/`: `sample_resume.docx`,
`sample_resume.pdf`, and `sample_job_description.txt` (regenerate the
resume samples with `python scripts/generate_samples.py`).

## Docker

```bash
docker build -f app/Dockerfile -t resume-updater-app:local .
docker run -p 8000:8000 -e ANTHROPIC_API_KEY=<your-key> resume-updater-app:local
```

## Deploying to AWS

Infrastructure is Terraform in `terraform/`, run remotely on HCP Terraform
(org `Moshik_Seetloo`, workspace `resume-tailor`, AWS credentials as
workspace environment variables). It creates the S3 bucket, the Lambda
function + function URL, CloudFront (+ ACM certificate for the custom
domain) and the GitHub deploy role. The function starts with a placeholder;
GitHub Actions deploys the real code.

One-time setup:

1. Store the secrets in SSM (never in Terraform/state):
   `aws ssm put-parameter --name /resume-tailor/anthropic-api-key --type SecureString --value ...`
   and the same for `/resume-tailor/site-password`.
2. Custom domain (DNS at Namecheap): `terraform apply -target=aws_acm_certificate.site`,
   add the `acm_validation_record` CNAME at Namecheap, then a full `terraform apply`.
   Finally point `resume` at the `cloudfront_domain` output with a CNAME.
3. GitHub repo secrets: `AWS_DEPLOY_ROLE_ARN`, `LAMBDA_FUNCTION_NAME` (Terraform
   outputs), `AWS_REGION` (`ap-southeast-1`), `SITE_HOST` (`resume.moshikseetloo.com`).
   If the repo uses GitHub's immutable OIDC subjects, set
   `github_sub_prefix_immutable` (from `gh api repos/Moshik23/resume-updater/actions/oidc/customization/sub`).

### CI/CD

`.github/workflows/deploy.yml` runs on every push to `master` that touches
`app/`, `static/` or the workflow: builds a Lambda zip with Linux wheels for
Python 3.12, assumes `resume-tailor-github-deploy` through GitHub OIDC (no
stored AWS keys; the role can only update this one function's code), deploys,
and smoke-tests `/healthz` through CloudFront.

## Cost and security notes

- **Cost:** Lambda, S3 and CloudFront are pay-per-request and sit inside the
  free tier at this usage, so hosting is effectively $0 when idle. Claude
  calls are a few cents per job. Use a dedicated Anthropic Console workspace
  with a monthly spend limit so the worst case is capped.
- **Access:** the whole app (frontend + API, everything except `/healthz`)
  sits behind a single shared HTTP Basic Auth password (`app/auth.py`),
  checked with `secrets.compare_digest` (constant-time). A custom CloudFront
  cache policy forwards the `Authorization` header with zero TTLs, since the
  managed CachingDisabled policy can't forward it on GET requests.
- **No way around CloudFront:** the function URL is public (OAC would need a
  payload hash header on every POST, which breaks browser file uploads), so
  CloudFront adds a random `x-origin-secret` header and the app returns 403
  to anything without it, `/healthz` included.
- **Secrets:** the Anthropic API key and site password live only in SSM
  Parameter Store (SecureString), read by the function's role at cold start
  — never in env vars, Terraform state, workflow YAML or git. The bucket is
  private with S3-managed encryption; job artifacts (real resume content)
  expire after 2 days, and profile files keep 30 days of old versions.

## Known limitations

- Cross-run-boundary keyword insertions in a `.docx` (an anchor phrase that
  spans a bold/italic boundary mid-word) only preserve the first run's
  formatting for the inserted text — rare in practice.
- PDF input never preserves the original visual layout — see above.
- The frontend is a single static page with no build step, by design — keep
  it that way rather than reaching for a framework.
- Polling a stored status file is simple and cheap at this scale; a busier
  tool would push results back over a WebSocket or use a queue.

## Credit

Built by [Moshik Seetloo](https://github.com/Moshik23) — photo and byline
in the page header, plus a footer credit. `static/photo.jpg` is a
center-cropped, 400×400 JPEG (resized with Pillow, using
`ImageOps.exif_transpose()` to avoid dropping phone-camera orientation
metadata — the same gotcha the photo-inbox feature on `memories-site` ran
into).
