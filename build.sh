#!/bin/sh

ROOT_DIR="$(pwd)"
BUILD_DIR="$ROOT_DIR/target/debug/"
WHEEL_DIR="$ROOT_DIR/target/wheels"
FILENAME="libcodemp"

TARGET_DIR="$ROOT_DIR/bindings"
SO_NAME="codemp"
WHEEL_NAME="Codemp_Sublime"

PYO3_PYTHON="$(pyenv which python)"
TARGET_EXT="$($PYO3_PYTHON -c 'import sysconfig; print(sysconfig.get_config_var("EXT_SUFFIX"))')"
SO_TARGET="${SO_NAME}${TARGET_EXT}"

echo "Building .SO with python: $PYO3_PYTHON"
env PYO3_PYTHON="${PYO3_PYTHON}" cargo build
echo "Copying into: $TARGET_DIR/$SO_TARGET"

echo "Building python wheel..."
maturin build -i "$PYO3_PYTHON"

wheels=($WHEEL_DIR/$WHEEL_NAME*.whl)
for whl in $wheels; do
	cp $whl $TARGET_DIR
done
ditto "$BUILD_DIR/${FILENAME}.dylib" "$TARGET_DIR/$SO_TARGET"
