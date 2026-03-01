#!/usr/bin/env bash
# kimidoesitlikethis – quick setup script
set -euo pipefail

echo "=== kimidoesitlikethis setup ==="

# 1. Python version check
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "Python: $python_version"

# 2. Create virtual environment
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment…"
    python3 -m venv .venv
fi

source .venv/bin/activate
echo "Virtual environment: $(which python)"

# 3. Install dependencies
echo "Installing Python dependencies…"
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
echo "Python packages installed."

# 4. Install Playwright browsers (for browser tool)
echo "Installing Playwright browsers (Chromium)…"
playwright install chromium --with-deps 2>/dev/null || {
    echo "Warning: Playwright browser install failed. Browser screenshot/form features will be limited."
    echo "You can retry manually: playwright install chromium"
}

# 5. Create .env from example if not present
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "Created .env from .env.example"
    echo "IMPORTANT: Edit .env and fill in your credentials before running."
else
    echo ".env already exists – skipping copy."
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env with your credentials"
echo "  2. (Google) Run: python get_google_token.py --client-id <id> --client-secret <secret>"
echo "  3. Start the bot: python main.py"
echo ""
