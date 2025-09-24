#!/usr/bin/env pwsh
[CmdletBinding()]
param(
    [string]$Port
)

$ErrorActionPreference = "Stop"

if (-not $Env:CONDA_DEFAULT_ENV) {
    throw "Activate your Conda environment (e.g. `conda activate rpico`) before running this script."
}

if ($Port) {
    $env:AMPY_PORT = $Port    # mpremote picks this up as default port
}

function Assert-Command($name) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "Required command '$name' not found. Install it inside the rpico environment."
    }
}

Assert-Command conda
Assert-Command mpremote
Assert-Command mpy-cross
Assert-Command tar
Assert-Command curl

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $repoRoot

$files = @(
    "styles.css",
    "RingBuffer.mpy",
    "boot.py",
    "my_secrets.py"
)

$mainFile = "asynchio4.py"
$microdotVersion = "2.3.3"
$microdotDir = "microdot-$microdotVersion"
$microdotArchive = "v$microdotVersion.tar.gz"
$microdotUrl = "https://github.com/miguelgrinberg/microdot/archive/refs/tags/v$microdotVersion.tar.gz"
$microdotFiles = @("microdot.py", "__init__.py")

Write-Host "Clearing board filesystem..."
& mpremote fs rm -r :.

Write-Host "Installing mip packages..."
& mpremote mip install sdcard
& mpremote mip install ntptime

Write-Host "Copying project files..."
$copyArgs = $files + ":"
& mpremote fs cp @copyArgs
& mpremote fs cp $mainFile ":main.py"

if (-not (Test-Path $microdotDir)) {
    Write-Host "Downloading Microdot $microdotVersion..."
    & curl -L -o $microdotArchive $microdotUrl

    Write-Host "Extracting Microdot..."
    & tar -xzf $microdotArchive
}

Push-Location (Join-Path $microdotDir "src\microdot")
try {
    foreach ($file in $microdotFiles) {
        Write-Host "Compiling $file..."
        & mpy-cross $file
        $mpy = [System.IO.Path]::ChangeExtension($file, ".mpy")
        Write-Host "Uploading $mpy..."
        & mpremote fs cp $mpy :
    }
}
finally {
    Pop-Location
}

Write-Host "Remote filesystem:"
& mpremote fs tree -h
