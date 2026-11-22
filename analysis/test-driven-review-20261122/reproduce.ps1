param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('model-tests', 'known-bugs')]
    [string]$Mode
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$frozen = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'frozen-inputs.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$source = Join-Path $PSScriptRoot 'source-app'
if (!(Test-Path -LiteralPath $source)) {
    $source = Join-Path $root 'analysis/react-lead-form-review-20261102/rlfm-0df740e1d9e8/app'
}
if (!(Test-Path -LiteralPath $source)) { throw 'Restore Z with the #8 restore_artifacts.ps1 script first.' }
$source = (Resolve-Path -LiteralPath $source).Path
$expected = @{}
foreach ($property in $frozen.source_files.PSObject.Properties) {
    $expected[$property.Name] = [string]$property.Value
}
$actual = Get-ChildItem -LiteralPath $source -Recurse -File
if ($actual.Count -ne $expected.Count) { throw 'Restored source file count differs from frozen input.' }
foreach ($file in $actual) {
    $relative = $file.FullName.Substring($source.Length + 1).Replace('\', '/')
    if (!$expected.ContainsKey($relative)) { throw "Unexpected restored file: $relative" }
    $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne $expected[$relative]) { throw "Restored source hash mismatch: $relative" }
}

$dockerBin = if ($env:RLFM_DOCKER) { $env:RLFM_DOCKER } else { (Get-Command docker -ErrorAction Stop).Source }
$args = @(
    'run', '--rm', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
    '--security-opt', 'no-new-privileges', '--tmpfs', '/tmp:rw,nosuid,size=512m',
    '--mount', "type=bind,source=$source,target=/source,readonly"
)
if ($Mode -eq 'model-tests') {
    $tests = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'test-work-trial2/tests')).Path
    $args += @('--mount', "type=bind,source=$tests,target=/tests,readonly")
    $script = 'cp -a /source /tmp/test-app && ln -s /app/node_modules /tmp/test-app/node_modules && /app/node_modules/.bin/tsx --test /tests/intake_pipeline.test.ts /tests/intake_form.test.ts'
} else {
    $evaluator = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'adjudicate_known.ts')).Path
    $args += @('--mount', "type=bind,source=$evaluator,target=/evaluator.ts,readonly")
    $script = 'cp -a /source /tmp/test-app && ln -s /app/node_modules /tmp/test-app/node_modules && /app/node_modules/.bin/tsx /evaluator.ts'
}
$args += @($frozen.test_image, 'sh', '-c', $script)
& $dockerBin @args
exit $LASTEXITCODE
