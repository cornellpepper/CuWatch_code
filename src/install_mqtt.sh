#! /bin/sh
# for running on a MAC though
set -e

trap 'echo "Error occurred at line $LINENO: $BASH_COMMAND"; exit 1' ERR

if [ "$#" -ne 1 ]; then
  echo "Need 1 argument: board number"
  exit 1
fi
if ! [ "$1" -eq "$1" ] 2>/dev/null; then
  echo "$1 is not a number"
  exit 2
fi
BOARD_ID=$1
[ -f id.txt ] && rm id.txt
echo $BOARD_ID > id.txt


source $(conda info --base)/etc/profile.d/conda.sh
conda activate rpico


# list of files to install
FILES="RingBuffer.mpy \
    my_secrets.py \
    id.txt \
    boot.py"

MAIN_FILE="asynchio5.py"

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

# compile the RingBuffer module - creates mpy file
mpy-cross RingBuffer.py

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


# uninstall / nuke the flash fs
mpremote fs rm -r :
mpremote fs tree -h

mpremote mip install sdcard
mpremote mip install umqtt.simple
mpremote mip install ntptime

mpremote fs cp $FILES :
mpremote fs cp $MAIN_FILE :main.py

mpremote fs tree -h

