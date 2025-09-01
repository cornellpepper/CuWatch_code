#! /bin/sh
# for running on a MAC though
set -e

trap 'echo "Error occurred at line $LINENO: $BASH_COMMAND"; exit 1' ERR

source $(conda info --base)/etc/profile.d/conda.sh
conda activate rpico


# list of files to install
FILES="RingBuffer.mpy \
    my_secrets.py \
    boot.py"

MAIN_FILE="asynchio5.py"

mpremote mip install sdcard
mpremote mip install umqtt.simple

mpremote fs cp $FILES :
mpremote fs cp $MAIN_FILE :main.py

# download the microdot library if it does not exist
MICRODOT_VER=2.0.6
MICRODOT_TGZ="https://github.com/miguelgrinberg/microdot/archive/refs/tags/v"${MICRODOT_VER}".tar.gz"

MICRODOT_FILES="microdot.py \
                __init__.py"
MICRODOT_DIR="microdot-"${MICRODOT_VER}
if [ ! -d $MICRODOT_DIR ]; then
    curl -L -O $MICRODOT_TGZ
    if [ $? -ne 0 ]; then
        echo "Failed to download microdot library"
        exit 1
    fi
    tar -xzf v${MICRODOT_VER}.tar.gz
    if [ $? -ne 0 ]; then
        echo "Failed to extract microdot library"
        exit 1
    fi
fi

cd $MICRODOT_DIR/src/microdot

for f in $MICRODOT_FILES; do
    mpy-cross $f
    ff=$(basename $f .py).mpy 
    mpremote fs cp $ff :
done
