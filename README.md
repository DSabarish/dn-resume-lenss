# HireIQ —  ATS Screener

A lean, honest candidate screening tool built for s.

## Quickstart

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
uvicorn main:app --reload
```

Then open http://localhost:8000

## What it does

1. Upload resumes (PDF, DOCX, TXT) + paste a job description
2. Gemini evaluates each candidate and returns:
   - **Score /10** — honest, holistic fit score
   - **Will shine in** — 3-4 things they'll genuinely excel at
   - **Needs to grow in** — 3-4 honest gaps
   - **Summary** — 2 sentences: strength + main risk

No pass/fail. No complex weighted formulas. Just clear, actionable intel.

## Recent Updates

- **Migrated to Google GenAI SDK** — Updated from legacy `google-generativeai` to the new `google-genai` library for improved developer experience and better client architecture
- Blocking Gemini calls wrapped in `asyncio.to_thread()` — no more event loop stall
- Cache singleton creation is now thread-safe (double-checked locking)
- API key update now clears `lru_cache` so new key takes effect immediately
- `datetime.utcnow()` replaced with `datetime.now(timezone.utc)` everywhere
- Double evaluation in multi-resume path removed
- Cache management endpoints use proper `list_keys()` method
- Phone regex tightened — no more redacting version numbers or "5-8 years experience"
