# Resume Updater

Upload a resume (.docx or .pdf) and paste a job description. The tool asks
Claude to find ATS-relevant keywords the resume is missing, flags real gaps
as follow-up questions, and produces a tailored `.docx`:

- **.docx input** — edits are applied in place (existing runs are mutated,
  new bullets are cloned from an existing paragraph), so the original
  formatting is preserved.
- **.pdf input** — there's no editable layout to preserve, so the tool
  builds a clean, ATS-friendly `.docx` from scratch instead of attempting a
  fragile pixel-for-pixel PDF clone. This is intentional, not a limitation
  to work around.

## Architecture

```
Browser (static HTML/CSS/JS)
   │  upload resume (.docx/.pdf) + paste job description
   ▼
FastAPI app (single container, Azure Container Apps)
   ├─ resume_ingest/   → extract flat {id, text} content blocks (docx or pdf)
   ├─ claude_client.py → forced tool-use call to Claude: gaps + suggested edits
   ├─ resume_apply/    → apply accepted edits (in-place docx, or rebuild for pdf)
   └─ storage.py       → Azure Blob Storage (job artifacts) + Key Vault (API key)
```

Deployed on **Azure** (Container Apps, scale-to-zero) with **Terraform** for
infrastructure and **Azure DevOps Pipelines** (OIDC, no long-lived secrets)
for CI/CD — chosen to match skills already on the resume this tool tailors.

## Local development

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r app\requirements.txt
$env:PYTHONPATH = "."
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

Or just run `scripts\run_local.ps1`, which does the same thing. No Azure
account is needed for local dev — `storage.py` falls back to a local
`.local_jobs/` directory when `AZURE_STORAGE_CONNECTION_STRING` is unset.

Set `ANTHROPIC_API_KEY` in your environment (or a `.env` file — already
gitignored) before hitting `/api/jobs`; without it the Claude call fails
cleanly with a 502 rather than crashing the server.

Sample files for testing are in `samples/`: `sample_resume.docx`,
`sample_resume.pdf`, and `sample_job_description.txt` (regenerate the
resume samples with `python scripts/generate_samples.py`).

## Docker

```bash
docker build -f app/Dockerfile -t resume-updater-app:local .
docker run -p 8000:8000 -e ANTHROPIC_API_KEY=<your-key> resume-updater-app:local
```

## Deploying to Azure

1. `az login`
2. Terraform state is remote (Azure Storage, `resumeupdaterstorage` account,
   `tfstate` container — see `terraform/main.tf`), required because both
   this CLI and the CI/CD pipeline apply changes and must share state
   rather than each starting from empty. Auth is via the storage account's
   access key, fetched dynamically (never committed):
   ```powershell
   $env:ARM_ACCESS_KEY = az storage account keys list --account-name resumeupdaterstorage --resource-group resume-updater-rg --query "[0].value" -o tsv
   cd terraform
   terraform init
   terraform apply -var="container_image_tag=<tag>" -var="anthropic_api_key=<your-key>"
   ```
   - **Bootstrap note:** the `tfstate` container itself is created out-of-band
     (`az storage container create --name tfstate --account-name resumeupdaterstorage --auth-mode login`),
     not managed by this Terraform config — a backend can't manage the
     storage it depends on to exist first.
   - **First-apply RBAC quirk:** Key Vault secret writes and the app's role
     assignments need RBAC role propagation to finish before they're usable.
     If the first `apply` errors on a permission check, re-run it — this is
     a known Azure RBAC timing issue, not a config bug.
3. Push the image (`az acr build` / ACR Tasks is blocked on some
   subscriptions with `TasksOperationsNotAllowed` — if so, build locally
   and push instead):
   `az acr login --name resumeupdateracr && docker build -f app/Dockerfile -t resumeupdateracr.azurecr.io/resume-updater-app:<tag> . && docker push resumeupdateracr.azurecr.io/resume-updater-app:<tag>`
4. Hit `https://<container_app_fqdn>/healthz` to confirm it's live.

For CI/CD, set up one Azure DevOps service connection named
`resume-updater-arm-connection` using **workload identity federation**
(Project Settings → Service connections → Azure Resource Manager →
"Workload Identity federation (automatic)"), scoped to the
`resume-updater-rg` resource group. No client secret is ever generated.
Add `ANTHROPIC_API_KEY` as a **secret** pipeline variable (Pipelines → Edit
→ Variables) — never commit it. Pushing to `master` then builds the image
(via `docker build`/`docker push` on the hosted agent — `az acr build` is
avoided since ACR Tasks may be blocked on the subscription, see above) and
re-applies Terraform automatically.

## Cost and security notes

- **Cost:** Container Apps scales to zero (`min_replicas = 0`) — near-$0
  when idle. Claude calls are a fraction of a cent per job at Sonnet 5
  pricing. ACR is Basic tier; Storage and Key Vault are pay-per-use.
- **Security:** the Anthropic API key lives only in Key Vault, read by the
  container's system-assigned managed identity — never a plain env var,
  never in pipeline YAML, never in git. The `jobs` blob container is
  private, and a lifecycle policy auto-deletes job artifacts (which contain
  real resume content) after 2 days. CI/CD uses OIDC service-connection auth
  with no long-lived credentials.

## Known limitations

- Cross-run-boundary keyword insertions in a `.docx` (an anchor phrase that
  spans a bold/italic boundary mid-word) only preserve the first run's
  formatting for the inserted text — rare in practice.
- PDF input never preserves the original visual layout — see above.
- The frontend is a single static page with no build step, by design — keep
  it that way rather than reaching for a framework.
