param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('dev', 'test', 'lint', 'fmt', 'check', 'replay', 'eval', 'reprice', 'markers', 'modal-deploy')]
    [string]$Task,

    [Parameter(Position = 1)]
    [string]$Sweep
)

$ErrorActionPreference = 'Stop'

function Invoke-TaskCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Executable exited with code $LASTEXITCODE."
    }
}

function Invoke-Lint {
    Invoke-TaskCommand -Executable 'uv' -Arguments @('run', 'ruff', 'check', '.')
    Invoke-TaskCommand -Executable 'uv' -Arguments @('run', 'ruff', 'format', '--check', '.')
}

function Require-Sweep {
    if ([string]::IsNullOrWhiteSpace($Sweep)) {
        throw "The '$Task' task requires a sweep path as its second argument."
    }
}

switch ($Task) {
    'dev' {
        Invoke-TaskCommand -Executable 'uv' -Arguments @(
            'run', 'uvicorn', 'app.server.main:app', '--reload', '--host', '0.0.0.0', '--port', '8000'
        )
    }
    'test' {
        Invoke-TaskCommand -Executable 'uv' -Arguments @('run', 'pytest', '-q')
    }
    'lint' {
        Invoke-Lint
    }
    'fmt' {
        Invoke-TaskCommand -Executable 'uv' -Arguments @('run', 'ruff', 'format', '.')
        Invoke-TaskCommand -Executable 'uv' -Arguments @('run', 'ruff', 'check', '--fix', '.')
    }
    'check' {
        Invoke-Lint
        Invoke-TaskCommand -Executable 'uv' -Arguments @('run', 'pytest', '-q')
    }
    'replay' {
        Require-Sweep
        Invoke-TaskCommand -Executable 'uv' -Arguments @('run', 'python', '-m', 'app.cli', 'replay', $Sweep)
    }
    'eval' {
        Require-Sweep
        Invoke-TaskCommand -Executable 'uv' -Arguments @(
            'run', 'python', '-m', 'app.cli', 'evaluate', '--sweep', $Sweep,
            '--gt', 'eval/ground_truth', '--out', 'docs/results.md'
        )
    }
    'reprice' {
        Require-Sweep
        Invoke-TaskCommand -Executable 'uv' -Arguments @(
            'run', 'python', '-m', 'app.cli', 'reprice', '--sweep', $Sweep,
            '--country', 'GB', '--limit', '10'
        )
    }
    'markers' {
        Invoke-TaskCommand -Executable 'uv' -Arguments @(
            'run', 'python', '-m', 'app.cli', 'make-markers', '--ids', '0', '1', '2',
            '--size-mm', '100', '--out', 'markers.pdf'
        )
    }
    'modal-deploy' {
        Invoke-TaskCommand -Executable 'uv' -Arguments @('run', '--extra', 'gpu', 'modal', 'deploy', 'gpu/modal_recon.py')
    }
}
