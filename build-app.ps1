[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot

function Resolve-AppPython {
    if ($env:PYTHON_EXE -and (Test-Path -LiteralPath $env:PYTHON_EXE -PathType Leaf)) {
        return (Resolve-Path -LiteralPath $env:PYTHON_EXE).Path
    }

    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command -and $command.Source -notlike '*\Microsoft\WindowsApps\*') {
        return $command.Source
    }

    $pythonRoot = Join-Path $env:LOCALAPPDATA 'Programs\Python'
    if (Test-Path -LiteralPath $pythonRoot -PathType Container) {
        $candidate = Get-ChildItem -LiteralPath $pythonRoot -Directory -Filter 'Python3*' |
            Sort-Object LastWriteTime -Descending |
            ForEach-Object { Join-Path $_.FullName 'python.exe' } |
            Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
            Select-Object -First 1
        if ($candidate) {
            return $candidate
        }
    }
    throw 'Python 3.10+ was not found. Set PYTHON_EXE to the full path of python.exe.'
}

$pythonExecutable = Resolve-AppPython
Push-Location $projectRoot
try {
    Write-Host "Installing the application build tools..."
    & $pythonExecutable -m pip install -e '.[build]'
    if ($LASTEXITCODE -ne 0) {
        throw "Could not install the application build tools (exit $LASTEXITCODE)."
    }

    Write-Host "Building the standalone Windows application..."
    $iconPngPath = Join-Path $projectRoot 'assets\freecad-agent.png'
    $iconIcoPath = Join-Path $projectRoot 'assets\freecad-agent.ico'
    & $pythonExecutable (Join-Path $projectRoot 'tools\make_icon.py')
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create the Windows icon (exit $LASTEXITCODE)."
    }
    & $pythonExecutable -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --windowed `
        --name 'FreeCAD Agent' `
        --icon $iconIcoPath `
        --add-data "$iconPngPath;assets" `
        --distpath (Join-Path $projectRoot 'dist') `
        --workpath (Join-Path $projectRoot 'build') `
        --specpath $projectRoot `
        (Join-Path $projectRoot 'freecad_agent_app.pyw')
    if ($LASTEXITCODE -ne 0) {
        throw "Application build failed (exit $LASTEXITCODE)."
    }

    $application = Join-Path $projectRoot 'dist\FreeCAD Agent.exe'
    Write-Host "Built: $application"
} finally {
    Pop-Location
}
