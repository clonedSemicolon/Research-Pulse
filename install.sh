#!/bin/bash

echo ""
echo "========================================"
echo "  ResearchPulse Installer"
echo "========================================"
echo ""

# Detect OS
OS="$(uname -s)"
case "$OS" in
    Linux*)     PLATFORM="Linux";;
    Darwin*)    PLATFORM="Mac";;
    *)          PLATFORM="Unknown";;
esac

echo "[*] Detected platform: $PLATFORM"
echo ""

# Check if Python is installed
if command -v python3 &> /dev/null; then
    PYTHON="python3"
    PIP="pip3"
    echo "[OK] Python3 is installed: $(python3 --version)"
elif command -v python &> /dev/null; then
    PYTHON="python"
    PIP="pip"
    echo "[OK] Python is installed: $(python --version)"
else
    echo "[!] Python is not installed."
    echo ""
    
    # Install Python based on platform
    if [ "$PLATFORM" = "Mac" ]; then
        # Check for Homebrew
        if command -v brew &> /dev/null; then
            echo "[*] Installing Python via Homebrew..."
            brew install python
        else
            echo "[*] Installing Homebrew first..."
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
            echo "[*] Installing Python..."
            brew install python
        fi
    elif [ "$PLATFORM" = "Linux" ]; then
        # Detect package manager
        if command -v apt-get &> /dev/null; then
            echo "[*] Installing Python via apt..."
            sudo apt-get update
            sudo apt-get install -y python3 python3-pip
        elif command -v dnf &> /dev/null; then
            echo "[*] Installing Python via dnf..."
            sudo dnf install -y python3 python3-pip
        elif command -v yum &> /dev/null; then
            echo "[*] Installing Python via yum..."
            sudo yum install -y python3 python3-pip
        elif command -v pacman &> /dev/null; then
            echo "[*] Installing Python via pacman..."
            sudo pacman -S --noconfirm python python-pip
        else
            echo "[X] Could not detect package manager."
            echo "Please install Python 3.10+ manually:"
            echo "  https://www.python.org/downloads/"
            exit 1
        fi
    fi
    
    # Verify installation
    if command -v python3 &> /dev/null; then
        PYTHON="python3"
        PIP="pip3"
        echo "[OK] Python installed: $(python3 --version)"
    elif command -v python &> /dev/null; then
        PYTHON="python"
        PIP="pip"
        echo "[OK] Python installed: $(python --version)"
    else
        echo "[X] Python installation failed."
        echo "Please install Python 3.10+ manually."
        exit 1
    fi
fi

echo ""
echo "[*] Installing ResearchPulse..."
echo ""

# Install research-pulse
$PIP install research-pulse --quiet 2>/dev/null || $PIP install research-pulse --user --quiet

if [ $? -ne 0 ]; then
    echo "[X] Installation failed."
    echo "Try manually: pip install research-pulse"
    exit 1
fi

echo ""
echo "========================================"
echo "  Installation Complete!"
echo "========================================"
echo ""
echo "Usage:"
echo "  research-pulse help              Show all commands"
echo "  research-pulse                   Today's papers"
echo "  research-pulse subscribe         Subscribe to newsletter"
echo "  research-pulse search \"query\"    Search papers"
echo ""
echo "Run: research-pulse help"
echo ""
