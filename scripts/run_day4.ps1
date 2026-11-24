$ErrorActionPreference = "Stop"
python -m day4.cli init
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m day4.cli benchmark
exit $LASTEXITCODE
