$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    foreach ($folder in @('build', 'dist', '.venv-build')) {
        $target = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot $folder))
        if (Test-Path -LiteralPath $target) {
            $item = Get-Item -LiteralPath $target -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Build directory cannot be a link: $target"
            }
        }
    }
    if (!(Test-Path -LiteralPath '.venv-build/Scripts/python.exe')) {
        python -m venv .venv-build
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the build environment.' }
    }
    & '.venv-build/Scripts/python.exe' -m pip install -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw 'Could not install build dependencies.' }
    & '.venv-build/Scripts/flet.exe' pack gui.py --name GModServerSetup --product-name "Garry's Mod Server Setup" --file-description "Garry's Mod Server Setup" --uac-admin --yes
    if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }
    if (!(Test-Path -LiteralPath 'dist/GModServerSetup.exe')) { throw 'Build produced no executable.' }
    Write-Host "Executable ready: $PSScriptRoot\dist\GModServerSetup.exe"
}
finally {
    Pop-Location
}
