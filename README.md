# resume-lens — Startup ATS Screener

A lean, honest candidate screening tool built for startups.

## 🚀 Quick Start

### Local Development

#### Using pip
```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
uvicorn main:app --reload
```

#### Using UV (Recommended - Faster)
```bash
# Install UV if you haven't already
pip install uv

# Install dependencies
uv sync

# Run the application
uv run uvicorn main:app --reload

# Or activate the virtual environment
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows
uvicorn main:app --reload
```

### Docker (Production Ready)
```bash
# Quick run with Docker Hub image
docker run -p 8000:8000 -e GEMINI_API_KEY=your_key_here sabs1010/dn-rsm-lens:latest

# Or build locally
docker build -t dn-rsm-lens:latest .
docker run -p 8000:8000 --env-file .env dn-rsm-lens:latest
```

Then open http://localhost:8000

## 🐳 Docker Commands
docker push 
### Building Images
```bash
# Build standard Alpine image (recommended)
docker build -t dn-rsm-lens:latest .
docker build -t dn-rsm-lens:v1.0 .

# Build ultra-lightweight distroless image
docker build -f Dockerfile.distroless -t dn-rsm-lens:distroless .

# Build with custom tag for Docker Hub
docker build -t sabs1010/dn-rsm-lens:latest .
docker build -t sabs1010/dn-rsm-lens:v1.0 .
```

### Running Containers
```bash
# Run with environment file
docker run -p 8000:8000 --env-file .env dn-rsm-lens:latest

# Run with environment variables
docker run -p 8000:8000 \
  -e GEMINI_API_KEY=your_api_key \
  -e ATS_GEMINI_MODEL=gemini-2.5-flash \
  -e ATS_MIN_SCORE=3.0 \
  sabs1010/dn-rsm-lens:latest

# Run in background (detached)
docker run -d -p 8000:8000 --name resume-lens --env-file .env sabs1010/dn-rsm-lens:latest

# Run with volume for persistent cache
docker run -p 8000:8000 --env-file .env \
  -v $(pwd)/.ats_cache:/app/.ats_cache \
  sabs1010/dn-rsm-lens:latest
```

### Docker Hub Operations
```bash
# Login to Docker Hub
docker login

# Tag image for Docker Hub
docker tag dn-rsm-lens-img:latest sabs1010/dn-rsm-lens:latest
docker tag dn-rsm-lens:latest sabs1010/dn-rsm-lens:v1

# Push to Docker Hub
docker push sabs1010/dn-rsm-lens:latest
docker push sabs1010/dn-rsm-lens:v1.0

# Pull from Docker Hub
docker pull sabs1010/dn-rsm-lens:latest
docker pull sabs1010/dn-rsm-lens:v1.0

# Run pulled image
docker run -p 8000:8000 --env-file .env sabs1010/dn-rsm-lens:v1
```

### Google Container Registry (GCR) Operations
```bash
# 1. Build your image
docker build -t dn-rsm-lens-img:latest .

# 2. Install gcloud, then authenticate
gcloud auth login
gcloud config set project dn-rsm-lens

# 3. Configure Docker for GCR


gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable run.googleapis.com

gcloud run deploy dn-rsm-lens `
  --image docker.io/sabs1010/dn-rsm-lens:v1 `
  --platform managed `
  --region asia-south1 `
  --port 8000 `
  --allow-unauthenticated



### Container Management
```bash
# List running containers
docker ps

# List all containers
docker ps -a

# Stop container
docker stop resume-lens

# Remove container
docker rm resume-lens

# View logs
docker logs resume-lens
docker logs -f resume-lens  # Follow logs

# Execute commands in running container
docker exec -it resume-lens sh

# Check container health
docker inspect resume-lens | grep Health -A 10
```

### Image Management
```bash
# List images
docker images

# Remove image
docker rmi sabs1010/dn-rsm-lens:latest

# Remove unused images
docker image prune

# Remove all unused containers, networks, images
docker system prune -a
```

### Development Workflow
```bash
# 1. Build and test locally
docker build -t dn-rsm-lens:dev .
docker run -p 8000:8000 --env-file .env dn-rsm-lens:dev

# 2. Tag for production
docker tag dn-rsm-lens:dev sabs1010/dn-rsm-lens:v1.0

# 3. Push to registry
docker push sabs1010/dn-rsm-lens:v1.0

# 4. Deploy on server
docker pull sabs1010/dn-rsm-lens:v1.0
docker run -d -p 8000:8000 --name resume-lens-prod \
  --env-file .env sabs1010/dn-rsm-lens:v1.0
```

## 📦 Package Management

### Using pip
```bash
# Install dependencies
pip install -r requirements.txt

# Install specific package
pip install package-name

# Update requirements
pip freeze > requirements.txt
```

### Using UV (Faster Alternative)
```bash
# Install UV
pip install uv

# Create new project
uv init

# Install dependencies
uv sync

# Add new dependency
uv add package-name

# Add development dependency
uv add --dev package-name

# Run commands in virtual environment
uv run python script.py
uv run uvicorn main:app --reload

# Update dependencies
uv lock --upgrade

# Install from lock file
uv sync --frozen
```

## What it does

1. Upload resumes (PDF, DOCX, TXT) + paste a job description
2. Gemini evaluates each candidate and returns:
   - **Score /10** — honest, holistic fit score
   - **Will shine in** — 3-4 things they'll genuinely excel at
   - **Needs to grow in** — 3-4 honest gaps
   - **Summary** — 2 sentences: strength + main risk

No pass/fail. No complex weighted formulas. Just clear, actionable intel.

## 🔧 Configuration

### Environment Variables
```bash
# Required
GEMINI_API_KEY=your_gemini_api_key

# Optional (with defaults)
ATS_GEMINI_MODEL=gemini-2.5-flash
ATS_MIN_SCORE=3.0
ATS_TOP_K=10
ATS_MAX_WORKERS=4
ATS_CACHE_TTL_HOURS=24
```

### Supported Models
- `gemini-3.1-flash-lite-preview`
- `gemini-3-flash-preview`
- `gemini-2.5-flash-lite`
- `gemini-2.5-flash` (recommended)

## Recent Updates

- **Migrated to Google GenAI SDK** — Updated from legacy `google-generativeai` to the new `google-genai` library for improved developer experience and better client architecture
- **Docker Support** — Added lightweight Alpine and distroless Docker images
- **UV Support** — Added UV package manager commands for faster dependency management
- **Model Updates** — Streamlined to 4 latest Gemini models only
- Blocking Gemini calls wrapped in `asyncio.to_thread()` — no more event loop stall
- Cache singleton creation is now thread-safe (double-checked locking)
- API key update now clears `lru_cache` so new key takes effect immediately
- `datetime.utcnow()` replaced with `datetime.now(timezone.utc)` everywhere
- Double evaluation in multi-resume path removed
- Cache management endpoints use proper `list_keys()` method
- Phone regex tightened — no more redacting version numbers or "5-8 years experience"