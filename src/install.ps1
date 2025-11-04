#!/usr/bin/env pwsh
# install.ps1 - PowerShell version of install.sh

$ErrorActionPreference = "Stop"

trap {
    Write-Error "Error on line $($_.InvocationInfo.ScriptLineNumber): $($_.Exception.Message)"
    exit 1
}

# List of files to install
$Files = @(
    "styles.css",
    "RingBuffer.mpy",
    "boot.py",
    "my_secrets.py"
)

$MainFile = "asynchio4.py"

# ---------------------------------------------------------------------------
# Compile the RingBuffer module - creates RingBuffer.mpy
# ---------------------------------------------------------------------------
if (Test-Path "RingBuffer.py") {
    Write-Host "Compiling RingBuffer.py -> RingBuffer.mpy"
    & mpy-cross "RingBuffer.py"
    if ($LASTEXITCODE -ne 0) {
        throw "mpy-cross failed for RingBuffer.py (exit code $LASTEXITCODE)"
    }
} else {
    throw "RingBuffer.py not found in the current directory."
}

# ---------------------------------------------------------------------------
# Create my_secrets.py if it does not exist
# ---------------------------------------------------------------------------
if (-not (Test-Path "my_secrets.py")) {
    Write-Host "Creating my_secrets.py file. Please edit it with your WiFi credentials."
    @"
# my_secrets.py for RedRover
PASS=None
SSID="RedRover"
MQTT_SERVER="pepper.physics.cornell.edu"
"@ | Set-Content -Encoding UTF8 "my_secrets.py"
}

# ---------------------------------------------------------------------------
# Check for missing files in MAIN_FILE and FILES
# ---------------------------------------------------------------------------
$MissingFiles = $false

foreach ($f in $Files) {
    if (-not (Test-Path $f)) {
        Write-Error "File $f not found!"
        $MissingFiles = $true
    }
}

if (-not (Test-Path $MainFile)) {
    Write-Error "Main file $MainFile not found!"
    $MissingFiles = $true
}

if ($MissingFiles) {
    throw "One or more files are missing. Aborting."
}

# ---------------------------------------------------------------------------
# Upload base files to the Pico via mpremote
# ---------------------------------------------------------------------------
Write-Host "Clearing filesystem on device..."
& mpremote fs rm -r :.
if ($LASTEXITCODE -ne 0) {
    throw "mpremote fs rm -r :. failed with exit code $LASTEXITCODE"
}

Write-Host "Installing mip packages (sdcard, ntptime)..."
& mpremote mip install sdcard
if ($LASTEXITCODE -ne 0) {
    throw "mpremote mip install sdcard failed with exit code $LASTEXITCODE"
}

& mpremote mip install ntptime
if ($LASTEXITCODE -ne 0) {
    throw "mpremote mip install ntptime failed with exit code $LASTEXITCODE"
}

Write-Host "Copying application files to device..."
# mpremote fs cp FILES :
$cpArgs = @("fs", "cp") + $Files + ":"
& mpremote @cpArgs
if ($LASTEXITCODE -ne 0) {
    throw "mpremote fs cp (FILES) : failed with exit code $LASTEXITCODE"
}

# mpremote fs cp MAIN_FILE :main.py
& mpremote fs cp $MainFile ":main.py"
if ($LASTEXITCODE -ne 0) {
    throw "mpremote fs cp $MainFile :main.py failed with exit code $LASTEXITCODE"
}

# ---------------------------------------------------------------------------
# Download the microdot library if it does not exist
# ---------------------------------------------------------------------------
$MicrodotVer  = "2.3.3"
$MicrodotDir  = "microdot-$MicrodotVer"
$ArchiveName  = "v$MicrodotVer.tar.gz"
$MicrodotUrl  = "https://github.com/miguelgrinberg/microdot/archive/refs/tags/v$MicrodotVer.tar.gz"

$MicrodotFiles = @(
    "microdot.py",
    "__init__.py"
)

if (-not (Test-Path $MicrodotDir)) {
    Write-Host "Downloading microdot v$MicrodotVer..."
    Invoke-WebRequest -Uri $MicrodotUrl -OutFile $ArchiveName

    if (-not (Test-Path $ArchiveName)) {
        throw "Failed to download microdot library archive: $ArchiveName not found"
    }

    Write-Host "Extracting $ArchiveName..."
    & tar -xzf $ArchiveName
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to extract microdot library (tar exit code $LASTEXITCODE)"
    }
}

# ---------------------------------------------------------------------------
# Compile and copy the microdot files
# ---------------------------------------------------------------------------
Push-Location "$MicrodotDir/src/microdot"
try {
    foreach ($f in $MicrodotFiles) {
        if (-not (Test-Path $f)) {
            throw "Microdot source file $f not found in $PWD"
        }

        Write-Host "Compiling $f..."
        & mpy-cross $f
        if ($LASTEXITCODE -ne 0) {
            throw "mpy-cross failed for $f (exit code $LASTEXITCODE)"
        }

        $ff = [System.IO.Path]::GetFileNameWithoutExtension($f) + ".mpy"
        if (-not (Test-Path $ff)) {
            throw "Expected compiled file $ff not found"
        }

        Write-Host "Copying $ff to device..."
        & mpremote fs cp $ff ":"
        if ($LASTEXITCODE -ne 0) {
            throw "mpremote fs cp $ff : failed with exit code $LASTEXITCODE"
        }
    }
}
finally {
    Pop-Location
}

# ---------------------------------------------------------------------------
# Show filesystem tree on the device
# ---------------------------------------------------------------------------
Write-Host "Final filesystem tree on device:"
& mpremote fs tree -h