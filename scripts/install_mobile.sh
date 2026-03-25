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
echo "[1/6] Installing packages..."
pkg update -y
pkg install -y python git

# --- 2. Clone chess-coach ---
if [ -d "$REPO_DIR" ]; then
    echo "[2/6] Updating chess-coach..."
    cd "$REPO_DIR"
    git pull
else
    echo "[2/6] Cloning chess-coach..."
    git clone https://github.com/qam4/chess-coach.git "$REPO_DIR"
    cd "$REPO_DIR"
fi

# --- 3. Install Python dependencies ---
echo "[3/6] Installing Python dependencies..."
pip install -e "$REPO_DIR"

# --- 4. Set up engine ---
echo "[4/6] Setting up engine..."
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

# --- 5. Create config ---
echo "[5/6] Creating config..."
sed "s|{APP_DATA}|$DATA_DIR|g" "$REPO_DIR/config.mobile.yaml" > "$DATA_DIR/config.yaml"
echo "  Config written to $DATA_DIR/config.yaml"

# --- 6. Create launcher script ---
echo "[6/6] Creating launcher..."
cat > "$HOME/chess-coach-start.sh" << 'LAUNCHER'
#!/bin/bash
DATA_DIR="$HOME/chess-coach-data"
PORT=8361
echo "Starting Chess Coach on http://localhost:$PORT"
echo "Open Chrome and go to: http://localhost:$PORT?mobile=1"
echo "Press Ctrl+C to stop."
python -c "
from chess_coach.mobile_entry import start_server
start_server('$DATA_DIR/config.yaml', $PORT, '$DATA_DIR')
"
LAUNCHER
# Re-expand variables in the launcher
sed -i "s|\$DATA_DIR|$DATA_DIR|g" "$HOME/chess-coach-start.sh"
sed -i "s|\$PORT|$PORT|g" "$HOME/chess-coach-start.sh"
chmod +x "$HOME/chess-coach-start.sh"

echo ""
echo "=== Setup complete! ==="
echo ""
echo "To start Chess Coach:"
echo "  bash ~/chess-coach-start.sh"
echo ""
echo "Then open Chrome on your phone:"
echo "  http://localhost:$PORT?mobile=1"
echo ""
