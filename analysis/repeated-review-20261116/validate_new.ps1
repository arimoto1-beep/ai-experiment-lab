$ErrorActionPreference = 'Stop'
$dockerBin = if ($env:RLFM_DOCKER) { $env:RLFM_DOCKER } else { (Get-Command docker -ErrorAction Stop).Source }
$image = 'sha256:9324cc278c6c71938d6bb2e8d2354c346677fdeee80b3bcbd8410a8529808059'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$sources = @{
    X = @('rlfm-55c4dc725287', 'react-lead-form__7S2gRVa')
    Y = @('rlfm-8fc5a785bdcd', 'react-lead-form__mE4ZMAE')
    Z = @('rlfm-0df740e1d9e8', 'react-lead-form__YRqsvPJ')
}
$script = (Resolve-Path (Join-Path $PSScriptRoot 'validate_new.ts')).Path
$rows = @()
foreach ($label in @('X', 'Y', 'Z')) {
    $runId, $trialId = $sources[$label]
    $app = (Resolve-Path (Join-Path $root "results/react_lead_form_harbor/$runId/jobs/$runId/$trialId/artifacts/app")).Path
    $name = "rlfm-11-check-$($label.ToLower())"
    $created = $false
    try {
        & $dockerBin create --name $name --network none $image sleep infinity | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'docker create failed' }
        $created = $true
        & $dockerBin cp "$app/." "${name}:/app"
        if ($LASTEXITCODE -ne 0) { throw 'docker cp app failed' }
        & $dockerBin cp $script "${name}:/tmp/validate_new.ts"
        if ($LASTEXITCODE -ne 0) { throw 'docker cp script failed' }
        & $dockerBin start $name | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'docker start failed' }
        $output = & $dockerBin exec $name /app/node_modules/.bin/tsx /tmp/validate_new.ts $label 2>&1
        $code = $LASTEXITCODE
        $rows += @{ label = $label; exit_code = $code; output = @($output) }
    }
    finally {
        if ($created) { & $dockerBin rm -f $name | Out-Null }
    }
}
$json = $rows | ConvertTo-Json -Depth 8
[System.IO.File]::WriteAllText((Join-Path $PSScriptRoot 'validation.json'), $json + "`n", (New-Object System.Text.UTF8Encoding($false)))
$rows | ConvertTo-Json -Depth 8
