param([string]$VendorPath = "")
$ErrorActionPreference = "Stop"

$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$build = Join-Path $root "build"
$vendor = if ($VendorPath) { (Resolve-Path -LiteralPath $VendorPath).Path } else { Join-Path $build "vendor" }
$runtime = Join-Path $build "runtime"
New-Item -ItemType Directory -Force -Path $vendor, $runtime | Out-Null

function Invoke-Checked([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program exited with $LASTEXITCODE." }
}

function Get-Source([string]$Name, [string]$Repository, [string]$Commit) {
    $target = Join-Path $vendor $Name
    if (-not (Test-Path -LiteralPath $target)) {
        $temporary = Join-Path $vendor "$Name-$([guid]::NewGuid().ToString('N'))"
        Invoke-Checked git @("init", "--quiet", $temporary)
        Invoke-Checked git @("-C", $temporary, "config", "core.longpaths", "true")
        Invoke-Checked git @("-C", $temporary, "fetch", "--quiet", "--depth", "1", $Repository, $Commit)
        Invoke-Checked git @("-C", $temporary, "checkout", "--quiet", "--detach", "FETCH_HEAD")
        Move-Item -LiteralPath $temporary -Destination $target
    }
    $head = & git -C $target rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or $head -ne $Commit) {
        throw "$Name requires revision $Commit."
    }
    return $target
}

$uxm = Get-Source uxm "https://github.com/Nordgaren/UXM-Selective-Unpack.git" "9501be87e272b6dae55e60a13c3f4753ca6fb3bb"
$bridge = Get-Source bridge "https://github.com/Beertraps/SekiroAnimationBridge.git" "5b607341d15a34755acec9b6359033b6651fc83f"
$pipeline = Get-Source pipeline "https://github.com/Meowmaritus/SoulsAssetPipeline.git" "d11caf989c917c7a43e2c7559915b1c5af218153"

$lookup = Join-Path $runtime "uxm/UXM"
New-Item -ItemType Directory -Force -Path (Join-Path $lookup "res") | Out-Null
$keyText = [IO.File]::ReadAllText((Join-Path $uxm "UXM/ArchiveKeys.cs"))
$lookupKeys = [ordered]@{}
foreach ($game in "DarkSouls3", "EldenRingNightreign") {
    $start = $keyText.IndexOf($game + "Keys")
    if ($start -lt 0) { throw "Archive lookup missing for $game." }
    $end = $keyText.IndexOf("};", $start)
    if ($end -lt 0) { throw "Archive lookup is incomplete for $game." }
    $section = $keyText.Substring($start, $end - $start)
    $keys = [ordered]@{}
    foreach ($match in [regex]::Matches($section,
        '\["(\w+)"\]\s*=\s*@"(-----BEGIN RSA PUBLIC KEY-----[\s\S]*?-----END RSA PUBLIC KEY-----)"')) {
        $keys[$match.Groups[1].Value] = $match.Groups[2].Value
    }
    if ($keys.Count -eq 0) { throw "No archive keys for $game." }
    $lookupKeys[$game] = $keys
}
[IO.File]::WriteAllText((Join-Path $lookup "keys.json"), ($lookupKeys | ConvertTo-Json -Depth 4))
foreach ($name in "DarkSouls3Dictionary.txt", "EldenRingNightreignDictionary.txt") {
    Copy-Item -LiteralPath (Join-Path $uxm "UXM/res/$name") -Destination (Join-Path $lookup "res") -Force
}

$bridgeModules = Join-Path $runtime "bridge/standalone"
New-Item -ItemType Directory -Force -Path $bridgeModules | Out-Null
Get-ChildItem -LiteralPath (Join-Path $bridge "standalone") -File -Filter "*.py" |
    Copy-Item -Destination $bridgeModules -Force
foreach ($folder in "games", "schemas") {
    Copy-Item -LiteralPath (Join-Path $bridge "standalone/$folder") -Destination $bridgeModules -Recurse -Force
}

$source = Join-Path $build "decoder-source"
New-Item -ItemType Directory -Force -Path $source | Out-Null
$upstream = Join-Path $bridge "tools/SekiroMotionDecoder"
$project = Join-Path $source "SekiroMotionDecoder.csproj"
$projectText = [IO.File]::ReadAllText((Join-Path $upstream "SekiroMotionDecoder.csproj"))
[IO.File]::WriteAllText($project, $projectText.Replace("net9.0-windows", "net10.0-windows"))
Copy-Item -LiteralPath (Join-Path $root "decoder/ModelReader.cs") -Destination $source -Force

$program = [IO.File]::ReadAllText((Join-Path $upstream "Program.cs"))
$dispatch = 'if (args.Length == 1 && args[0] == "--version")'
$frames = '    var frames = Enumerable.Range(0, animationData.FrameCount).Select(frameIndex =>'
if (-not $program.Contains($dispatch) -or -not $program.Contains($frames)) {
    throw "Unexpected decoder source."
}
$program = $program.Replace($dispatch, @"
if (args.Length == 3 && args[0] == "--flver")
    return ModelReader.Run(args[1], args[2]);

$dispatch
"@)
$program = $program.Replace($frames, @"
    // DS3 splines may include padding tracks whose binding is -1.
    if (trackToBone.Length != trackCount || trackToBone.Any(i => i < -1 || i >= skeleton.Bones.Size))
        throw new NotSupportedException("Animation binding does not match the skeleton.");
    int[] boundTracks = Enumerable.Range(0, trackCount).Where(i => trackToBone[i] >= 0).ToArray();
    if (boundTracks.Length == 0)
        throw new NotSupportedException("Animation has no bound transform tracks.");
$frames
"@)
$program = $program.Replace('Enumerable.Range(0, trackCount).Select(trackIndex =>', 'boundTracks.Select(trackIndex =>')
$program = $program.Replace('        trackCount,', '        trackCount = boundTracks.Length,')
$program = $program.Replace('        trackBoneIndices = trackToBone,', '        trackBoneIndices = boundTracks.Select(i => trackToBone[i]).ToArray(),')
$program = $program.Replace('        trackNames,', '        trackNames = boundTracks.Select(i => trackNames[i]).ToArray(),')
[IO.File]::WriteAllText((Join-Path $source "Program.cs"), $program)

$published = Join-Path $build "decoder-publish"
Invoke-Checked dotnet @("publish", $project, "-c", "Release", "-r", "win-x64", "--self-contained", "true",
    "-p:SoulsAssetPipelineProject=$(Join-Path $pipeline 'SoulsAssetPipeline/SoulsAssetPipeline.csproj')",
    "-p:DebugType=None", "-p:DebugSymbols=false", "-o", $published)
$decoder = Join-Path $runtime "decoder"
New-Item -ItemType Directory -Force -Path $decoder | Out-Null
Get-ChildItem -LiteralPath $published | Where-Object { $_.Name -notin @("SapResources", "x86") } |
    Copy-Item -Destination $decoder -Recurse -Force
Invoke-Checked (Join-Path $decoder "SekiroMotionDecoder.exe") @("--version")

$notices = Join-Path $runtime "licenses"
New-Item -ItemType Directory -Force -Path $notices | Out-Null
Copy-Item -LiteralPath (Join-Path $bridge "LICENSE") -Destination (Join-Path $notices "SekiroAnimationBridge.txt") -Force
Copy-Item -LiteralPath (Join-Path $pipeline "LICENSE") -Destination (Join-Path $notices "SoulsAssetPipeline.txt") -Force
$runtimePack = Join-Path $env:USERPROFILE ".nuget/packages/microsoft.netcore.app.runtime.win-x64"
if (Test-Path -LiteralPath $runtimePack) {
    $runtimeVersion = Get-ChildItem -LiteralPath $runtimePack -Directory |
        Sort-Object { [version]($_.Name -split "-")[0] } -Descending | Select-Object -First 1
    foreach ($file in "LICENSE.TXT", "THIRD-PARTY-NOTICES.TXT") {
        $path = Join-Path $runtimeVersion.FullName $file
        if (Test-Path -LiteralPath $path) {
            Copy-Item -LiteralPath $path -Destination (Join-Path $notices ".NET-$file") -Force
        }
    }
}
