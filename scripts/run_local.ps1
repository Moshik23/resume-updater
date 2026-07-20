if (-not (Test-Path .venv)) {
    python -m venv .venv
}
& .\.venv\Scripts\pip install -r app\requirements.txt
$env:PYTHONPATH = "."
& .\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
