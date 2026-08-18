[CmdletBinding()]
param(
    [switch] $Login,
    [switch] $Gui,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $AgentArgs
)

function Resolve-CodexExecutable {
    if ($env:CODEX_EXE -and (Test-Path -LiteralPath $env:CODEX_EXE -PathType Leaf)) {
        return (Resolve-Path -LiteralPath $env:CODEX_EXE).Path
    }

    $command = Get-Command codex -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $extensionRoots = @(
        (Join-Path $env:USERPROFILE '.vscode\extensions'),
        (Join-Path $env:USERPROFILE '.vscode-insiders\extensions')
    )
    foreach ($root in $extensionRoots) {
        if (-not (Test-Path -LiteralPath $root -PathType Container)) {
            continue
        }
        $extensions = Get-ChildItem -LiteralPath $root -Directory -Filter 'openai.chatgpt-*' |
            Sort-Object LastWriteTime -Descending
        foreach ($extension in $extensions) {
            $candidate = Get-ChildItem -LiteralPath (Join-Path $extension.FullName 'bin') `
                -Recurse -File -Filter 'codex.exe' -ErrorAction SilentlyContinue |
                Select-Object -First 1
            if ($candidate) {
                return $candidate.FullName
            }
        }
    }
    return $null
}

function Resolve-PythonExecutable {
    if ($env:PYTHON_EXE -and (Test-Path -LiteralPath $env:PYTHON_EXE -PathType Leaf)) {
        return (Resolve-Path -LiteralPath $env:PYTHON_EXE).Path
    }

    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command -and $command.Source -notlike '*\Microsoft\WindowsApps\*') {
        return $command.Source
    }

    $searchRoots = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python'),
        $env:ProgramFiles
    )
    foreach ($root in $searchRoots) {
        if (-not $root -or -not (Test-Path -LiteralPath $root -PathType Container)) {
            continue
        }
        $candidate = Get-ChildItem -LiteralPath $root -Directory -Filter 'Python3*' -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            ForEach-Object { Join-Path $_.FullName 'python.exe' } |
            Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
            Select-Object -First 1
        if ($candidate) {
            return $candidate
        }
    }
    return $null
}

# Authentication can be completed before Python is installed. This calls the
# same Codex executable bundled with the official VS Code extension.
if ($Login -or ($AgentArgs.Count -eq 1 -and $AgentArgs[0] -eq '--login')) {
    $codexExecutable = Resolve-CodexExecutable
    if (-not $codexExecutable) {
        Write-Error ('Codex was not found on PATH or in the VS Code extension folders. ' +
            'Install the OpenAI ChatGPT/Codex extension, or set CODEX_EXE to codex.exe.')
        exit 2
    }
    Write-Host "Starting ChatGPT sign-in with: $codexExecutable"
    & $codexExecutable login
    exit $LASTEXITCODE
}

if ($Gui) {
    $AgentArgs = @('--gui') + $AgentArgs
}

$pythonExecutable = Resolve-PythonExecutable
if (-not $pythonExecutable) {
    Write-Error ('Python 3.10+ was not found on PATH or in the standard installation folders. ' +
        'Install it from python.org, or set PYTHON_EXE to the full path of python.exe.')
    exit 2
}

& $pythonExecutable -m freecad_agent @AgentArgs
exit $LASTEXITCODE
