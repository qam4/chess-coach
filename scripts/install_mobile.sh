#!/bin/bash
# Chess Coach — Termux mobile setup script
#
# Run this in Termux on your Android phone:
#   curl -sL https://raw.githubusercontent.com/qam4/chess-coach/main/scripts/install_mobile.sh | bash
#
# Or clone the repo first and run locally:
#   bash scripts/install_mobile.sh
#
# Prerequisites: Termux installed from F-Droid

set -e

DATA_DIR="$HOME/chess-coach-data"
REPO_DIR="$HOME/chess-coach"
PORT=8361

echo "=== Chess Coach Mobile Setup ==="
echo ""

# --- 1. Install system packages ---
echo "[1/7] Installing packages..."
pkg update -y
pkg install -y python git termux-api

# --- 2. Grant storage access if needed ---
if [ ! -d "$HOME/storage" ]; then
    echo "[2/7] Setting up storage access..."
    termux-setup-storage
    echo "  Please grant storage permission if prompted."
    echo "  Press Enter to continue after granting..."
    read -r
else
    echo "[2/7] Storage access already set up."
fi

# --- 3. Clone chess-coach ---
if [ -d "$REPO_DIR" ]; then
    echo "[3/7] Updating chess-coach..."
    git -C "$REPO_DIR" pull
else
    echo "[3/7] Cloning chess-coach..."
    git clone https://github.com/qam4/chess-coach.git "$REPO_DIR"
fi

# --- 4. Install Python dependencies ---
echo "[4/7] Installing Python dependencies..."
# Use mobile requirements to avoid pydantic v2 (needs Rust compiler).
# FastAPI 0.99.1 + pydantic v1 works without native compilation.
pip install -r "$REPO_DIR/requirements-mobile.txt"
pip install -e "$REPO_DIR" --no-deps

# --- 5. Set up engine ---
echo "[5/7] Setting up engine..."
mkdir -p "$DATA_DIR"

# Check if engine already extracted
if [ -x "$DATA_DIR/engine/blunder" ]; then
    echo "  Engine already installed."
else
    # Look for the zip in common locations
    ZIP=""
    for candidate in \
        "$DATA_DIR/blunder-android-arm64.zip" \
        "$HOME/storage/downloads/blunder-android-arm64.zip" \
        "$HOME/storage/shared/Download/blunder-android-arm64.zip" \
        "/sdcard/Download/blunder-android-arm64.zip" \
        "/sdcard/blunder-android-arm64.zip"; do
        if [ -f "$candidate" ]; then
            ZIP="$candidate"
            break
        fi
    done

    if [ -z "$ZIP" ]; then
        echo ""
        echo "  Engine zip not found. Please download it first:"
        echo ""
        echo "  Option A: Download from GitHub CI artifacts (needs browser):"
        echo "    https://github.com/qam4/blunder/actions"
        echo "    → latest successful build → Artifacts → blunder-android-arm64"
        echo "    Save to Downloads folder, then re-run this script."
        echo ""
        echo "  Option B: Push from your computer via adb:"
        echo "    adb push blunder-android-arm64.zip /sdcard/"
        echo "    Then re-run this script."
        echo ""
        echo "  Option C: Copy the zip manually to:"
        echo "    $DATA_DIR/blunder-android-arm64.zip"
        echo ""
        exit 1
    fi

    echo "  Extracting $ZIP..."
    unzip -o "$ZIP" -d "$DATA_DIR"
    chmod +x "$DATA_DIR/engine/blunder"
    echo "  Engine installed."
fi

# --- 6. Create config ---
echo "[6/7] Creating config..."
sed "s|{APP_DATA}|$DATA_DIR|g" "$REPO_DIR/config.mobile.yaml" > "$DATA_DIR/config.yaml"
echo "  Config written to $DATA_DIR/config.yaml"

# --- 7. Create launcher + Termux:Widget shortcut ---
echo "[7/7] Creating launcher..."

# Main launcher script
cat > "$HOME/chess-coach-start.sh" << LAUNCHER
#!/bin/bash
PORT=$PORT
DATA_DIR="$DATA_DIR"
URL="http://localhost:\$PORT?mobile=1"

echo "♟ Chess Coach starting..."
echo ""

# Start server in background
python -c "
from chess_coach.mobile_entry import start_server
start_server('\$DATA_DIR/config.yaml', \$PORT, '\$DATA_DIR')
" &
SERVER_PID=\$!

# Wait for server to be ready
echo "Waiting for server..."
for i in \$(seq 1 30); do
    if curl -s "http://localhost:\$PORT/" > /dev/null 2>&1; then
        echo "Server ready!"
        echo ""
        # Open Chrome automatically
        termux-open-url "\$URL" 2>/dev/null || am start -a android.intent.action.VIEW -d "\$URL" 2>/dev/null || echo "Open in browser: \$URL"
        echo "Chess Coach is running. Press Ctrl+C to stop."
        wait \$SERVER_PID
        exit 0
    fi
    sleep 1
done

echo "Server failed to start. Check logs."
kill \$SERVER_PID 2>/dev/null
exit 1
LAUNCHER
chmod +x "$HOME/chess-coach-start.sh"

# Termux:Widget shortcut (tap from home screen)
WIDGET_DIR="$HOME/.shortcuts"
mkdir -p "$WIDGET_DIR"
cat > "$WIDGET_DIR/Chess Coach" << WIDGET
#!/bin/bash
bash $HOME/chess-coach-start.sh
WIDGET
chmod +x "$WIDGET_DIR/Chess Coach"

echo ""
echo "=== Setup complete! ==="
echo ""
echo "To start Chess Coach:"
echo ""
echo "  Option 1: Run in Termux:"
echo "    bash ~/chess-coach-start.sh"
echo ""
echo "  Option 2: Home screen shortcut (install Termux:Widget from F-Droid):"
echo "    Add a Termux:Widget widget → pick 'Chess Coach'"
echo "    Tap it to launch — Chrome opens automatically."
echo ""
