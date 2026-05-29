# Push script for fix/pdf-libs branch
# Run this from the repository root: PowerShell

param(
    [string]$Branch = "fix/pdf-libs",
    [string]$Remote = "origin"
)

Write-Host "Switching to branch $Branch (creates if needed)..."
git checkout -B $Branch

Write-Host "Staging files..."
git add Dockerfile .github/workflows/docker-pdf-check.yml school/score/views.py

Write-Host "Committing..."
git commit -m "Install freetype in Dockerfile; lazy-import xhtml2pdf; add CI check" -q

Write-Host "Pushing to $Remote/$Branch..."
git push -u $Remote $Branch

if ($LASTEXITCODE -ne 0) {
    Write-Error "Git push failed. Please ensure you have network access and proper credentials set up."
    exit $LASTEXITCODE
}

Write-Host "Push complete. Open a PR on GitHub to trigger CI if needed." 
Write-Host "Repository: https://github.com/asemakahamande/allinone/compare/$Branch"