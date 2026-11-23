$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    $pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pythonLauncher) {
        & py -m venv .venv
    } else {
        & python -m venv .venv
    }
    if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
        throw "Could not create .venv. Install Python and make sure it is available on PATH."
    }
}

$python = ".venv\Scripts\python.exe"
& $python -m pip install -r requirements.txt
& $python -c "from study_guide.app import app; app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)" 
