#! /bin/sh
# for running on a MAC though
set -e

trap 'echo "Error occurred at line $LINENO: $BASH_COMMAND"; exit 1' ERR

# source $(conda info --base)/etc/profile.d/conda.sh
# conda activate rpico


# list of files to install
FILES="styles.css \
    RingBuffer.mpy \
    boot.py \
    my_secrets.py "

MAIN_FILE="asynchio4.py"

# compile the RingBuffer module - creates mpy file
mpy-cross RingBuffer.py

# create my_secrets.py if it does not exist. Since RedRover does not 
# require WiFi credentials, we can provide default values.
if [ ! -f my_secrets.py ]; then
    echo "Creating my_secrets.py file. Please edit it with your WiFi credentials."
    cat > my_secrets.py <<EOL
# my_secrets.py for RedRover
PASS=None
SSID="RedRover"
MQTT_SERVER="pepper.physics.cornell.edu"
EOL
fi

# check for missing files in MAIN_FILE and FILES
MISSING_FILES=0
for f in $FILES; do
  if [ ! -f $f ]; then
    echo "File $f not found!"
    MISSING_FILES=1
  fi
done
if [ ! -f $MAIN_FILE ]; then
    echo "Main file $MAIN_FILE not found!"
    MISSING_FILES=1
fi
if [ $MISSING_FILES -ne 0 ]; then
    echo "One or more files are missing. Aborting."
    exit 1
fi

mpremote fs rm -r :.
mpremote mip install sdcard
mpremote mip install ntptime
mpremote fs cp $FILES :
mpremote fs cp $MAIN_FILE :main.py

# download the microdot library if it does not exist
MICRODOT_VER=2.3.3
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

# compile and copy the microdot files
for f in $MICRODOT_FILES; do
    mpy-cross $f
    ff=$(basename $f .py).mpy 
    mpremote fs cp $ff :
done

mpremote fs tree -h 
