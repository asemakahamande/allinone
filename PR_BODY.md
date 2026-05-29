Title: Fix PDF generation startup crash — install FreeType and lazy-load xhtml2pdf

Summary:
- Install system FreeType and other native libraries in `Dockerfile` so `reportlab`/`xhtml2pdf` can load `libfreetype.so.6`.
- Make `xhtml2pdf` import lazy in `school/score/views.py` and add error handling so the app doesn't crash at startup when system libs are missing.
- Add GitHub Actions workflow to build the Docker image and verify `reportlab`/`xhtml2pdf` import and presence of `libfreetype`.

Testing:
- CI workflow `.github/workflows/docker-pdf-check.yml` will build the image and run import checks.
- Locally: run `scripts/push_fix_pdf_libs.ps1` then build the Docker image and run the import tests (commands in README or earlier outputs).

Notes:
- If deploying to Heroku, add an `Aptfile` or use the apt buildpack to install `libfreetype6`.
- The lazy import is defensive: after installing system libs you can revert if preferred.
