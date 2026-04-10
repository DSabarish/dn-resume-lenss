# ./main.py
"""
main.py — ATS Startup Screener — FastAPI backend.

Bug fixes applied:
  - No double evaluation (shortlist + explicit loop removed)
  - datetime.utcnow() replaced with utc_now_iso() everywhere
  - API key update clears lru_cache singleton
  - Cache entry endpoints use proper list_keys() method
  - No enhanced_evaluator complexity
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from cache import get_cache
from config import ScreeningConfig, get_config
from evaluator import evaluate_candidate
from extractor import ParseError, parse_resume_and_job
from models import JobCriteria, ResumeProfile, StartupReport
from ranker import rank_candidates
from utils import extract_text, get_tracker, reset_tracker, utc_now_iso

START_TIME = time.time()

app = FastAPI(title="ATS Startup Screener", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory="static"), name="static")

# In-memory stores
_job_library: Dict[str, dict] = {}
_run_history: Dict[str, dict] = {}
_candidate_store: Dict[str, dict] = {}

# Initialize with default jobs
def _initialize_default_jobs():
    """Initialize the job library with default job descriptions"""
    ds_fresher_id = "job_ds_fresher_default"
    if ds_fresher_id not in _job_library:
        _job_library[ds_fresher_id] = {
            "id": ds_fresher_id,
            "name": "DS-Fresher",
            "description": "A data science job involves collecting, analyzing, and interpreting complex data to help organizations make informed decisions. Data scientists use tools like Python, R, and SQL to clean and process data, build predictive models, and create visualizations. They apply statistical methods and machine learning techniques to identify trends and patterns. The role requires strong problem-solving skills, domain knowledge, and the ability to communicate insights clearly to stakeholders. Data scientists often work with large datasets, collaborate with cross-functional teams, and continuously refine models to improve accuracy and performance, driving business value through data-driven strategies.",
            "tags": ["data science", "python", "machine learning", "fresher", "entry level"],
            "created_at": "2024-01-01T00:00:00Z",
            "char_count": 847,
        }

# Initialize default jobs on startup
_initialize_default_jobs()
_config_overrides: Dict[str, Any] = {}
_log_buffer: deque = deque(maxlen=500)
_log_subscribers: List[WebSocket] = []


async def _log(level: str, message: str, **extra):
    entry = {"ts": utc_now_iso(), "level": level, "msg": message, **extra}
    _log_buffer.append(entry)
    dead = []
    for ws in list(_log_subscribers):
        try:
            await ws.send_json(entry)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in _log_subscribers:
            _log_subscribers.remove(ws)


def _build_config(overrides: dict | None = None) -> ScreeningConfig:
    merged = {**_config_overrides, **(overrides or {})}
    return ScreeningConfig(**merged) if merged else get_config()


# ── Core ───────────────────────────────────────────────────────────────────

@app.get("/", response_class=FileResponse)
async def serve_index():
    return FileResponse("static/index.html")


@app.get("/api/health")
async def health():
    cfg = _build_config()
    tracker = get_tracker()
    return {
        "status": "ok",
        "version": "1.0.0",
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "gemini_key_set": bool(cfg.gemini_api_key),
        "model": cfg.gemini_model,
        "session_calls": tracker.summary()["calls"],
        "session_cost_usd": tracker.summary()["est_cost_usd"],
        "candidates_stored": len(_candidate_store),
        "runs_stored": len(_run_history),
        "jobs_in_library": len(_job_library),
    }


@app.get("/api/stats")
async def stats():
    tracker = get_tracker()
    cache = get_cache()
    scores = [c["score"] for c in _candidate_store.values() if "score" in c]
    return {
        "session": tracker.summary(),
        "cache": cache.metrics_dict(),
        "candidates": {
            "total": len(_candidate_store),
            "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
            "top_score": round(max(scores), 1) if scores else 0,
        },
        "runs": {
            "total": len(_run_history),
            "latest": max((r["ts"] for r in _run_history.values()), default=None),
        },
        "jobs_library": len(_job_library),
        "uptime_seconds": round(time.time() - START_TIME, 1),
    }


# ── Config ────────────────────────────────────────────────────────────────

@app.get("/api/config")
async def get_config_endpoint():
    cfg = _build_config()
    return {
        "effective": {
            "gemini_model": cfg.gemini_model,
            "min_score": cfg.min_score,
            "top_k": cfg.top_k,
            "redact_pii": cfg.redact_pii,
            "bias_mitigation": cfg.bias_mitigation,
            "max_workers": cfg.max_workers,
        },
        "overrides": _config_overrides,
    }


@app.put("/api/config")
async def update_config(body: dict):
    allowed = {"min_score", "top_k", "redact_pii", "bias_mitigation", "max_workers", "cache_ttl_hours"}
    invalid = set(body.keys()) - allowed
    if invalid:
        raise HTTPException(status_code=400, detail=f"Unknown config keys: {invalid}")
    _config_overrides.update(body)
    await _log("INFO", "config_updated", keys=list(body.keys()))
    return {"message": "Config updated", "effective": _config_overrides}


@app.get("/api/setup-config")
async def get_setup_config():
    env_content = {}
    try:
        with open(".env", "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env_content[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return {
        "api_key_set": bool(env_content.get("GEMINI_API_KEY")),
        "model": env_content.get("ATS_GEMINI_MODEL", "gemini-2.5-flash"),
    }


@app.put("/api/setup-config")
async def update_setup_config(body: dict):
    api_key = body.get("api_key", "").strip()
    model = body.get("model", "gemini-2.5-flash").strip()

    valid_models = ["gemini-3.1-flash-lite-preview", "gemini-3-flash-preview", "gemini-2.5-flash-lite", "gemini-2.5-flash"]
    if model not in valid_models:
        raise HTTPException(status_code=400, detail=f"Model must be one of: {valid_models}")

    env_lines = []
    try:
        with open(".env", "r") as f:
            env_lines = f.readlines()
    except FileNotFoundError:
        env_lines = ["# ATS Startup Screener environment variables\n\n"]

    api_key_updated = model_updated = False
    for i, line in enumerate(env_lines):
        if line.strip().startswith("GEMINI_API_KEY="):
            if api_key:
                env_lines[i] = f"GEMINI_API_KEY={api_key}\n"
                api_key_updated = True
        elif line.strip().startswith("ATS_GEMINI_MODEL="):
            env_lines[i] = f"ATS_GEMINI_MODEL={model}\n"
            model_updated = True

    if not api_key_updated and api_key:
        env_lines.append(f"\nGEMINI_API_KEY={api_key}\n")
    if not model_updated:
        env_lines.append(f"ATS_GEMINI_MODEL={model}\n")

    with open(".env", "w") as f:
        f.writelines(env_lines)

    # Bug fix: clear the lru_cache so the new key is picked up immediately
    get_config.cache_clear()

    await _log("INFO", "setup_config_updated", model=model)
    return {"message": "Configuration saved. New API key is active.", "model": model}


# ── Job Library ──────────────────────────────────────────────────────────

@app.get("/api/jobs")
async def list_jobs():
    return {"jobs": sorted(_job_library.values(), key=lambda j: j["created_at"], reverse=True)}


@app.post("/api/jobs")
async def save_job(body: dict):
    name = body.get("name", "").strip()
    description = body.get("description", "").strip()
    if not name or not description:
        raise HTTPException(status_code=400, detail="name and description are required.")
    job_id = f"job_{uuid.uuid4().hex[:8]}"
    entry = {
        "id": job_id,
        "name": name,
        "description": description,
        "tags": body.get("tags", []),
        "created_at": utc_now_iso(),
        "char_count": len(description),
    }
    _job_library[job_id] = entry
    return entry


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    if job_id not in _job_library:
        raise HTTPException(status_code=404, detail="Job not found.")
    return _job_library[job_id]


@app.put("/api/jobs/{job_id}")
async def update_job(job_id: str, body: dict):
    if job_id not in _job_library:
        raise HTTPException(status_code=404, detail="Job not found.")
    for k in ("name", "description", "tags"):
        if k in body:
            _job_library[job_id][k] = body[k]
    if "description" in body:
        _job_library[job_id]["char_count"] = len(body["description"])
    _job_library[job_id]["updated_at"] = utc_now_iso()
    return _job_library[job_id]


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str):
    if job_id not in _job_library:
        raise HTTPException(status_code=404, detail="Job not found.")
    del _job_library[job_id]
    return {"message": f"Job {job_id} deleted."}


# ── Screening ─────────────────────────────────────────────────────────────

@app.post("/api/screen")
async def screen_candidates(
    resumes: List[UploadFile] = File(...),
    job_description: str = Form(...),
    job_id_ref: str = Form(""),
    run_label: str = Form(""),
    redact_pii: bool = Form(True),
    bias_mitigation: bool = Form(True),
):
    if not job_description.strip():
        raise HTTPException(status_code=400, detail="Job description is required.")
    if not resumes:
        raise HTTPException(status_code=400, detail="At least one resume is required.")

    config = _build_config({"redact_pii": redact_pii, "bias_mitigation": bias_mitigation})

    if not config.gemini_api_key:
        raise HTTPException(
            status_code=422,
            detail="No Gemini API key set. Go to Settings and add your key."
        )

    run_id = f"run_{uuid.uuid4().hex[:10]}"
    await _log("INFO", "screen_start", run_id=run_id, resume_count=len(resumes))
    reset_tracker()

    # --- Parse all resumes ---
    parsed_resumes: List[ResumeProfile] = []
    job_criteria: Optional[JobCriteria] = None
    parse_errors: List[str] = []

    for upload in resumes:
        raw_bytes = await upload.read()
        resume_text = extract_text(raw_bytes, upload.filename or "resume")
        if not resume_text.strip():
            parse_errors.append(f"Could not extract text from {upload.filename}")
            continue

        fname = (upload.filename or "candidate").rsplit(".", 1)[0]
        cid = f"{fname}_{uuid.uuid4().hex[:4]}"
        try:
            resume, job, from_cache, latency, _ = await parse_resume_and_job(
                resume_text=resume_text,
                job_text=job_description,
                config=config,
                candidate_id=cid,
                job_id=run_id,
            )
            parsed_resumes.append(resume)
            if job_criteria is None:
                job_criteria = job
            await _log("INFO", "parsed", candidate_id=cid, from_cache=from_cache)
        except ParseError as exc:
            parse_errors.append(f"Parse failed for {upload.filename}: {exc}")
            await _log("ERROR", "parse_failed", file=upload.filename, error=str(exc))

    if not parsed_resumes or job_criteria is None:
        raise HTTPException(
            status_code=422,
            detail={"message": "No resumes could be parsed.", "errors": parse_errors},
        )

    # --- Evaluate all candidates (no double evaluation — rank_candidates does it once) ---
    reports: List[StartupReport] = await rank_candidates(
        parsed_resumes, job_criteria, config
    )

    # --- Store results ---
    reports_json = [r.model_dump(mode="json") for r in reports]
    for r, rd in zip(reports, reports_json):
        _candidate_store[r.candidate_id] = {**rd, "run_id": run_id}

    tracker = get_tracker()
    top_score = reports[0].score if reports else 0.0

    _run_history[run_id] = {
        "run_id": run_id,
        "label": run_label or f"Run #{len(_run_history) + 1}",
        "ts": utc_now_iso(),
        "jd_snippet": (job_description[:120] + "...") if len(job_description) > 120 else job_description,
        "job_id_ref": job_id_ref,
        "total": len(parsed_resumes),
        "screened": len(reports),
        "top_score": round(top_score, 1),
        "parse_errors": parse_errors,
        "candidate_ids": [r.candidate_id for r in reports],
        "reports": reports_json,
        "job": job_criteria.model_dump(),
        "usage": tracker.summary(),
    }

    await _log(
        "INFO", "screen_complete",
        run_id=run_id,
        total=len(parsed_resumes),
        screened=len(reports),
        top_score=round(top_score, 1),
        cost_usd=tracker.summary()["est_cost_usd"],
    )

    return JSONResponse({
        "run_id": run_id,
        "total_evaluated": len(parsed_resumes),
        "parse_errors": parse_errors,
        "reports": reports_json,
        "job": job_criteria.model_dump(),
        "usage": tracker.summary(),
    })


# ── History ───────────────────────────────────────────────────────────────

@app.get("/api/history")
async def list_history():
    keys = ["run_id", "label", "ts", "jd_snippet", "total", "screened", "top_score", "usage"]
    summaries = [
        {k: r[k] for k in keys if k in r}
        for r in sorted(_run_history.values(), key=lambda x: x["ts"], reverse=True)
    ]
    return {"runs": summaries}


@app.get("/api/history/{run_id}")
async def get_run(run_id: str):
    if run_id not in _run_history:
        raise HTTPException(status_code=404, detail="Run not found.")
    return _run_history[run_id]


@app.delete("/api/history")
async def clear_history():
    _run_history.clear()
    _candidate_store.clear()
    return {"message": "History cleared."}


@app.delete("/api/history/{run_id}")
async def delete_run(run_id: str):
    if run_id not in _run_history:
        raise HTTPException(status_code=404, detail="Run not found.")
    run = _run_history.pop(run_id)
    for cid in run.get("candidate_ids", []):
        _candidate_store.pop(cid, None)
    return {"message": f"Run {run_id} deleted.", "candidates_removed": len(run.get("candidate_ids", []))}


# ── Candidates ────────────────────────────────────────────────────────────

@app.get("/api/candidates")
async def list_candidates(
    min_score: float = 0.0,
    run_id: Optional[str] = None,
    limit: int = 100,
):
    results = list(_candidate_store.values())
    if min_score > 0:
        results = [c for c in results if c.get("score", 0) >= min_score]
    if run_id:
        results = [c for c in results if c.get("run_id") == run_id]
    results.sort(key=lambda c: c.get("score", 0), reverse=True)
    return {"total": len(results), "candidates": results[:limit]}


@app.get("/api/candidates/{candidate_id}")
async def get_candidate(candidate_id: str):
    if candidate_id not in _candidate_store:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    return _candidate_store[candidate_id]


@app.post("/api/candidates/compare")
async def compare_candidates(body: dict):
    ids = body.get("candidate_ids", [])
    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="Provide at least 2 candidate_ids.")
    if len(ids) > 6:
        raise HTTPException(status_code=400, detail="Max 6 candidates for comparison.")

    candidates = []
    for cid in ids:
        if cid not in _candidate_store:
            raise HTTPException(status_code=404, detail=f"Candidate {cid} not found.")
        c = _candidate_store[cid]
        candidates.append({
            "candidate_id": cid,
            "score": c.get("score", 0),
            "shine_areas": c.get("shine_areas", []),
            "gap_areas": c.get("gap_areas", []),
            "matched_skills": c.get("matched_skills", []),
            "missing_skills": c.get("missing_skills", []),
            "experience_note": c.get("experience_note", ""),
            "summary": c.get("summary", ""),
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    for i, c in enumerate(candidates):
        c["rank"] = i + 1

    return {
        "count": len(candidates),
        "winner": candidates[0]["candidate_id"],
        "candidates": candidates,
    }


# ── Cache management ──────────────────────────────────────────────────────

@app.get("/api/cache/metrics")
async def cache_metrics():
    return get_cache().metrics_dict()


@app.get("/api/cache/entries")
async def list_cache_entries():
    # Bug fix: use proper list_keys() method instead of nonexistent _store attribute
    keys = get_cache().list_keys()
    return {"count": len(keys), "keys": keys[:200]}


@app.delete("/api/cache")
async def clear_cache():
    get_cache().clear()
    await _log("INFO", "cache_cleared")
    return {"message": "Cache cleared."}


# ── Export ────────────────────────────────────────────────────────────────

@app.get("/api/export/run/{run_id}/csv")
async def export_run_csv(run_id: str):
    if run_id not in _run_history:
        raise HTTPException(status_code=404, detail="Run not found.")
    reports = _run_history[run_id].get("reports", [])

    rows = []
    for r in reports:
        rows.append({
            "candidate_id": r.get("candidate_id"),
            "score": r.get("score"),
            "summary": r.get("summary"),
            "experience_note": r.get("experience_note"),
            "shine_areas": "; ".join(r.get("shine_areas", [])),
            "gap_areas": "; ".join(r.get("gap_areas", [])),
            "matched_skills": ", ".join(r.get("matched_skills", [])),
            "missing_skills": ", ".join(r.get("missing_skills", [])),
        })

    csv_bytes = pd.DataFrame(rows).to_csv(index=False).encode()
    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={run_id}.csv"},
    )


@app.get("/api/export/run/{run_id}/json")
async def export_run_json(run_id: str):
    if run_id not in _run_history:
        raise HTTPException(status_code=404, detail="Run not found.")
    json_bytes = json.dumps(_run_history[run_id]["reports"], indent=2, default=str).encode()
    return StreamingResponse(
        io.BytesIO(json_bytes),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={run_id}.json"},
    )


# ── WebSocket: Live Logs ───────────────────────────────────────────────────

@app.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket):
    await websocket.accept()
    _log_subscribers.append(websocket)
    try:
        for entry in list(_log_buffer):
            await websocket.send_json(entry)
        while True:
            await asyncio.sleep(30)
            await websocket.send_json({"type": "ping", "ts": utc_now_iso()})
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in _log_subscribers:
            _log_subscribers.remove(websocket)
