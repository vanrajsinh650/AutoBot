#!/bin/bash
# ════════════════════════════════════════════════════════════════
#  AutoBot v2 — One-time Setup Script
#  Run this ONCE from the AutoBot folder:  bash setup.sh
# ════════════════════════════════════════════════════════════════
set -e

echo ""
echo "╔══════════════════════════════════════╗"
echo "║   🤖 AutoBot v2 — Setup              ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ── Check prerequisites ──────────────────────────────────────────
command -v python3  >/dev/null || { echo "❌ python3 not found. Install Python 3.11+"; exit 1; }
command -v docker   >/dev/null || { echo "❌ Docker not found. Install Docker Desktop."; exit 1; }

PYTHON_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "✓ Python $PYTHON_VER"

# ── Virtual environment ──────────────────────────────────────────
echo ""
echo "📦 Creating virtual environment..."
python3 -m venv .venv
source .venv/bin/activate

# ── Install Python dependencies ──────────────────────────────────
echo "📥 Installing dependencies (this takes ~2 mins)..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "✓ Python packages installed"

# ── Playwright browsers ──────────────────────────────────────────
echo ""
echo "🌐 Installing Playwright Chromium browser..."
playwright install chromium
echo "✓ Playwright ready"

# ── Qdrant via Docker ────────────────────────────────────────────
echo ""
echo "🗄  Starting Qdrant vector database (Docker)..."
docker compose up -d
echo "✓ Qdrant running at http://localhost:6333"

# ── .env setup ──────────────────────────────────────────────────
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "📝 Created .env file — edit it now!"
fi

# ── Data folders ─────────────────────────────────────────────────
mkdir -p data/resume data/portfolio logs

# ── Done ─────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════"
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Edit .env — add your API keys + LinkedIn credentials"
echo "  2. Put your resume at: data/resume/resume.pdf"
echo "  3. Set linkedin_url in config.yaml (optional but recommended)"
echo ""
echo "Then run:"
echo "  source .venv/bin/activate"
echo "  python main.py --ingest-only   ← load your profile first"
echo "  python main.py                 ← full agent run"
echo "════════════════════════════════════════"
echo ""
