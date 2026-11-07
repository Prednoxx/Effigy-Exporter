param(
    [string]$Python = "python",
    [string]$VendorPath = "",
    [string]$Installer = "",
    [string]$Blender = "",
    [switch]$UseEnvironment,
    [switch]$SkipRuntime
)
$ErrorActionPreference = "Stop"

$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$build = Join-Path $root "build"
$runtime = Join-Path $build "runtime"
$releases = Join-Path $root "Releases"
$stage = Join-Path $build "dist/EffigyExporter"
$resources = Join-Path $root "souls_studio/resources"
$Python = (Get-Command $Python -ErrorAction Stop).Source
if ($VendorPath) { $VendorPath = (Resolve-Path -LiteralPath $VendorPath).Path }
if ($Blender) { $Blender = (Resolve-Path -LiteralPath $Blender).Path }

function Invoke-Checked([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program exited with $LASTEXITCODE." }
}

Push-Location -LiteralPath $root
try {
    Invoke-Checked $Python @("-c", "import sys; assert sys.version_info[:2] == (3, 13) and sys.maxsize > 2**32")
    if (-not $UseEnvironment) {
        $venv = Join-Path $build "venv"
        Invoke-Checked $Python @("-m", "venv", $venv)
        $Python = Join-Path $venv "Scripts/python.exe"
        Invoke-Checked $Python @("-m", "pip", "install", "--disable-pip-version-check", "-r", "requirements-build.txt")
    }
    if (-not $SkipRuntime) {
        & (Join-Path $PSScriptRoot "prepare_runtime.ps1") -VendorPath $VendorPath
    }
    $env:EFFIGY_RUNTIME = $runtime
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $build "pyinstaller-cache"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    Invoke-Checked $Python @("-m", "unittest", "discover", "-s", "tests")
    $version = & $Python -c 'from souls_studio import __version__; print(__version__)'
    if ($LASTEXITCODE -ne 0 -or $version -notmatch '^\d+\.\d+\.\d+$') { throw "Invalid app version." }
    $parts = ($version -split "\.") -join ", "
    $versionInfo = Join-Path $build "version_info.txt"
    [IO.File]::WriteAllText($versionInfo, @"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($parts, 0), prodvers=($parts, 0), mask=0x3f,
                    flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Prednoxx'),
      StringStruct('FileDescription', 'Effigy Exporter'),
      StringStruct('FileVersion', '$version'),
      StringStruct('InternalName', 'EffigyExporter'),
      StringStruct('OriginalFilename', 'EffigyExporter.exe'),
      StringStruct('ProductName', 'Effigy Exporter'),
      StringStruct('ProductVersion', '$version')
  ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)
"@)

    Invoke-Checked $Python @("-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--noupx",
        "--name", "EffigyExporter", "--specpath", $build, "--distpath", (Join-Path $build "dist"),
        "--workpath", (Join-Path $build "work"), "--paths", (Join-Path $runtime "bridge/standalone"),
        "--collect-submodules", "OpenGL", "--hidden-import", "pyopengltk.win32",
        "--collect-data", "soulstruct", "--hidden-import", "PIL._tkinter_finder",
        "--add-data", "$resources;souls_studio/resources",
        "--add-data", "$(Join-Path $root 'souls_studio/*_names.json');souls_studio",
        "--add-data", "$(Join-Path $runtime 'bridge/standalone/schemas');schemas",
        "--add-data", "$(Join-Path $runtime 'uxm');runtime/uxm",
        "--add-data", "$(Join-Path $runtime 'decoder');runtime/decoder",
        "--icon", (Join-Path $resources "effigy.ico"), "--version-file", $versionInfo, "launcher.py")
    $addon = & $Python tools/package_release.py
    if ($LASTEXITCODE -ne 0) { throw "Release packaging failed." }
    if ($Blender) {
        Invoke-Checked $Blender @("--factory-startup", "--command", "extension", "validate", $addon)
    }

    if (-not $Installer) {
        $command = Get-Command iscc.exe -ErrorAction SilentlyContinue
        $Installer = if ($command) { $command.Source } else {
            @(
                (Join-Path $env:LOCALAPPDATA "Programs/Inno Setup 6/ISCC.exe"),
                (Join-Path ([Environment]::GetEnvironmentVariable("ProgramFiles(x86)")) "Inno Setup 6/ISCC.exe"),
                (Join-Path $env:ProgramFiles "Inno Setup 6/ISCC.exe")
            ) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
        }
    }
    if ($Installer) {
        Invoke-Checked $Installer @("/Qp", "/DAppVersion=$version", "/DStageDir=$stage", "/O$releases",
            (Join-Path $root "installer/EffigyExporter.iss"))
    }
    Invoke-Checked $Python @("tools/package_release.py", "--checksums")
    Write-Host "Release files: $releases"
} finally {
    Pop-Location
}
