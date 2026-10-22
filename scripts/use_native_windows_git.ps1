# Git for Windows bin/git.exe and cmd/git.exe launch mingw64/bin/git.exe.
# CI creates thousands of tiny repositories; use the same installation directly
# without changing Git configuration, hooks, verification, or test coverage.
$ErrorActionPreference = 'Stop'
$resolved = (Get-Command git -CommandType Application | Select-Object -First 1).Source
$directory = Split-Path $resolved -Parent
if ((Split-Path $directory -Leaf) -notin @('bin', 'cmd')) {
    Write-Host "Keeping Git from $resolved (unrecognized installation layout)"
    return
}
$native = Join-Path (Split-Path $directory -Parent) 'mingw64/bin/git.exe'
if (!(Test-Path -LiteralPath $native -PathType Leaf)) {
    Write-Host "Keeping Git from $resolved (no native executable beside launcher)"
    return
}
$before = & $resolved --version
if ($LASTEXITCODE -ne 0) { throw 'Cannot verify current Git version' }
$after = & $native --version
if ($LASTEXITCODE -ne 0 -or $before -ne $after) {
    throw 'Native Git does not match the existing Git installation'
}
$nativeDirectory = Split-Path $native -Parent
$env:PATH = "$nativeDirectory$([IO.Path]::PathSeparator)$env:PATH"
if ($env:GITHUB_PATH) {
    $nativeDirectory | Out-File -FilePath $env:GITHUB_PATH -Encoding utf8 -Append
}
Write-Host "Using $native ($after)"
