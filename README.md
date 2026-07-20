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

## Architecture

```
Browser (static HTML/CSS/JS, no framework/build step)
   │  upload resume (.docx/.pdf) + paste job description
   ▼
FastAPI app (single container, Azure Container Apps)
   ├─ resume_ingest/   → extract flat {id, text} content blocks (docx or pdf)
   ├─ claude_client.py → forced tool-use call to Claude: gaps + suggested edits
   ├─ resume_apply/    → apply accepted edits (in-place docx, or rebuild for pdf)
   ├─ summary.py       → plain-English "what changed" report (markdown)
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
`.local_jobs/` directory when `AZURE_STORAGE_ACCOUNT_NAME` is unset.

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
   - **Identity design:** the app authenticates to ACR, Key Vault, and Blob
     Storage via a **user-assigned** managed identity
     (`azurerm_user_assigned_identity.app`), not a system-assigned one. A
     system-assigned identity only exists once the Container App resource
     itself is created — too late, since the app's first revision needs
     those permissions already granted to pull its image and read its
     secret at creation time. The user-assigned identity (and its role
     assignments) are created first, breaking that circular dependency.
   - **`deployer_principal_ids` (variables.tf):** Key Vault Secrets Officer
     is granted to an explicit, stable list of principal IDs — not to
     `data.azurerm_client_config.current`. That data source resolves to
     "whoever is running terraform right now," which breaks the moment a
     second identity (this CLI *and* the CI/CD pipeline's service
     principal) also applies the config — each would try to revoke the
     other's grant and 403 on the read that happens first. Add every
     identity that will ever run `terraform apply` to that list.
   - **First-apply RBAC quirk:** role assignments still need a little RBAC
     propagation time before they're usable. If the first `apply` errors on
     a permission check, re-run it — a known Azure timing issue, not a
     config bug.
3. Push the image (`az acr build` / ACR Tasks is blocked on some
   subscriptions with `TasksOperationsNotAllowed` — if so, build locally
   and push instead):
   `az acr login --name resumeupdateracr && docker build -f app/Dockerfile -t resumeupdateracr.azurecr.io/resume-updater-app:<tag> . && docker push resumeupdateracr.azurecr.io/resume-updater-app:<tag>`
4. Hit `https://<container_app_fqdn>/healthz` to confirm it's live.

### CI/CD

Set up one Azure DevOps service connection named
`resume-updater-arm-connection` using **workload identity federation**
(Project Settings → Service connections → Azure Resource Manager →
"Workload Identity federation (automatic)"), scoped to the
`resume-updater-rg` resource group. No client secret is ever generated.
Add `ANTHROPIC_API_KEY` as a **secret** pipeline variable (Pipelines → Edit
→ Variables) — never commit it. Pushing to `master` then builds the image
and re-applies Terraform automatically.

A few things in `azure-pipelines.yml` are specific to how this was actually
brought up, not generic defaults — worth knowing if you copy this pattern:

- **`az acr build` is avoided.** ACR Tasks can return
  `TasksOperationsNotAllowed` on some subscriptions. The pipeline builds the
  image on the agent itself (`docker build` + `docker push` after
  `az acr login`) instead.
- **`scriptType: ps` (Windows PowerShell), not `bash`.** The self-hosted
  agent below is a Windows machine with a broken WSL `bash.exe` shim ahead
  of Git Bash on `PATH` — `AzureCLI@2`'s `scriptType: bash` resolved to the
  wrong binary (`execvpe(/bin/bash) failed`). PowerShell Core (`pscore`)
  would be the more portable choice if it were installed on the agent; it
  isn't, so this uses plain Windows PowerShell, which means the pipeline as
  written is not portable back to a Linux hosted pool without editing the
  inline scripts.
- **Terraform's access key is fetched dynamically inside the pipeline too**
  (same `az storage account keys list` command as the manual steps above)
  — never stored as a pipeline secret.

#### Self-hosted agent

This Azure DevOps org is new, and Microsoft's free hosted-parallelism grant
for new orgs isn't automatic — hosted-pool jobs can queue indefinitely until
it's approved (request it at https://aka.ms/azpipelines-parallelism-request,
typically a 2–3 business day turnaround). Rather than wait, the pipeline
runs on a **self-hosted agent** registered on this machine instead of
`vmImage: ubuntu-latest`:

```powershell
# One-time agent registration (needs a PAT scoped to Agent Pools: Read & manage)
mkdir C:\azagent; cd C:\azagent
curl -sL -o agent.zip https://download.agent.dev.azure.com/agent/5.275.0/pipelines-agent-win-x64-5.275.0.zip
Expand-Archive -Path agent.zip -DestinationPath . -Force
.\config.cmd --unattended --url https://dev.azure.com/moshikseetloo --auth pat --token <PAT> --pool Default --agent <agent-name> --acceptTeeEula
```

Then start the listener (`.\run.cmd`) and leave it running whenever you want
the pipeline to pick up jobs — it needs `az`, `terraform`, and `docker` on
`PATH` (refresh `$env:Path` from the registry before starting it if you just
installed one of them, since the listener process's environment is captured
at startup, not re-read per job). If you switch to a hosted pool later
(once the grant is approved), change `pool: name: Default` back to
`pool: vmImage: ubuntu-latest` and revisit the `scriptType`/install-step
notes above.

## Cost and security notes

- **Cost:** Container Apps scales to zero (`min_replicas = 0`) — near-$0
  when idle. Claude calls are a fraction of a cent per job at Sonnet 5
  pricing. ACR is Basic tier; Storage and Key Vault are pay-per-use.
- **Security:** the Anthropic API key lives only in Key Vault, read by the
  app's user-assigned managed identity — never a plain env var, never in
  pipeline YAML, never in git. Blob Storage access is also identity-based
  (`DefaultAzureCredential`, no account key in the app itself). The `jobs`
  blob container is private, and a lifecycle policy auto-deletes job
  artifacts (which contain real resume content) after 2 days. CI/CD uses
  OIDC service-connection auth with no long-lived credentials.

## Known limitations

- Cross-run-boundary keyword insertions in a `.docx` (an anchor phrase that
  spans a bold/italic boundary mid-word) only preserve the first run's
  formatting for the inserted text — rare in practice.
- PDF input never preserves the original visual layout — see above.
- The frontend is a single static page with no build step, by design — keep
  it that way rather than reaching for a framework.
- The CI/CD pipeline currently targets a self-hosted Windows agent (see
  above), not a portable hosted pool — the inline scripts assume Windows
  PowerShell and a machine with `az`/`terraform`/`docker` already installed.

## Credit

Built by [Moshik Seetloo](https://github.com/Moshik23).
