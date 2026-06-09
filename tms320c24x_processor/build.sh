#!/bin/bash

# Build script for TMS320C24x Ghidra processor module
# Compiles SLEIGH specification to binary format

set -e

# Check if GHIDRA_INSTALL_DIR is set
if [ -z "$GHIDRA_INSTALL_DIR" ]; then
    echo "Error: GHIDRA_INSTALL_DIR environment variable not set"
    echo "Please set it to your Ghidra installation directory"
    echo "Example: export GHIDRA_INSTALL_DIR=/path/to/ghidra"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LANG_DIR="$SCRIPT_DIR/data/languages"
SLEIGH_COMPILER="$GHIDRA_INSTALL_DIR/support/sleigh"

# Check if sleigh compiler exists
if [ ! -f "$SLEIGH_COMPILER" ]; then
    echo "Error: Sleigh compiler not found at $SLEIGH_COMPILER"
    echo "Please verify your GHIDRA_INSTALL_DIR is correct"
    exit 1
fi

echo "Building TMS320C24x processor module..."
echo "Ghidra installation: $GHIDRA_INSTALL_DIR"
echo "Language directory: $LANG_DIR"

# Create output directory if it doesn't exist
mkdir -p "$LANG_DIR"

# Compile SLEIGH specification
echo "Compiling SLEIGH specification..."
cd "$LANG_DIR"

if "$SLEIGH_COMPILER" TMS320C24x.slaspec TMS320C24x.sla; then
    echo "Successfully compiled TMS320C24x.slaspec -> TMS320C24x.sla"
else
    echo "Error: Failed to compile SLEIGH specification"
    exit 1
fi

echo "Build complete!"
echo ""
echo "To install the processor module:"
echo "1. Copy the entire tms320c24x_processor directory to:"
echo "   $GHIDRA_INSTALL_DIR/Ghidra/Processors/TMS320C24x/"
echo "   OR"
echo "   ~/.ghidra/.ghidra_*/Extensions/TMS320C24x/"
echo ""
echo "2. Restart Ghidra"
echo ""
echo "The TMS320C24x processor will then be available for selection"
echo "when importing binary files."