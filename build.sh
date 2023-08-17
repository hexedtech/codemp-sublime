#!/bin/sh

ROOT_DIR="$(pwd)"
BUILD_DIR="$ROOT_DIR/target/debug/deps"
FILENAME="libcodemp_client"

TARGET_DIR="$ROOT_DIR/bindings"
TARGET_NAME="codemp_client"
TARGET_EXT="$(python -c 'import sysconfig; print(sysconfig.get_config_var("EXT_SUFFIX"))')"

FULL_TARGET="${TARGET_NAME}${TARGET_EXT}"

PYO3_PYTHON="$(pyenv which python)"
PYTHON_SYS_EXECUTABLE="$PYO3_PYTHON"
CARGO_FEATURES="pyo3/extension-module"

env PYO3_PYTHON="${PYO3_PYTHON}" PYTHON_SYS_EXECUTABLE="$PYO3_PYTHON" cargo build --features "$CARGO_FEATURES"

[[ -f "$TARGET_DIR/$FUll_TARGET" ]] && echo "$FILE exists."
ditto "$BUILD_DIR/${FILENAME}.dylib" "$TARGET_DIR/$FULL_TARGET"
