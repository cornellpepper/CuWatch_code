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

# uninstall / nuke the flash fs
mpremote fs rm -r :
mpremote fs tree -h

mpremote mip install sdcard
mpremote mip install umqtt.simple
mpremote mip install ntptime

mpremote fs cp $FILES :
mpremote fs cp $MAIN_FILE :main.py

mpremote fs tree -h

