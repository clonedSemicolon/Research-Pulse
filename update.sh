#!/bin/bash

echo ""
echo "========================================"
echo "  ResearchPulse Updater"
echo "========================================"
echo ""

# Detect pip command
if command -v pip3 &> /dev/null; then
    PIP="pip3"
elif command -v pip &> /dev/null; then
    PIP="pip"
else
    echo "[X] pip not found. Please install pip first."
    exit 1
fi

# Show current version
echo "[*] Current version:"
research-pulse --version 2>/dev/null || echo "  (not installed)"
echo ""

# Update
echo "[*] Updating ResearchPulse..."
echo ""

$PIP install research-pulse --upgrade --quiet 2>/dev/null || $PIP install research-pulse --upgrade --user --quiet

echo ""
echo "[*] New version:"
research-pulse --version
echo ""

echo "========================================"
echo "  Update Complete!"
echo "========================================"
echo ""
