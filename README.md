# N CV Screener App

Runnable Streamlit app for reviewing batches of CVs against pasted role criteria. This version keeps the useful parts of the original desktop tool, but improves the review workflow and makes the final scoring easier to audit.

## Updates

- Criteria are parsed into an editable table before screening.
- The default model is `gpt-5.6-terra`, with model presets for `gpt-5.6-sol`, `gpt-5.6-luna`, `gpt-5.6`, `gpt-4o-mini`, and custom model IDs.
- Model selection includes visible input, cached-input, and output rates before the run.
- The Run tab shows a pre-run estimated API cost, model-call count, and token estimate before `Run Screening` is pressed.
- The model only provides evidence-backed criterion scores; final pass counts, averages, gaps, and recommendation are calculated in code.
- Optional model comparison runs let you compare the primary model against a second model and review score/recommendation changes.
- Calibration results flag criteria with large score spread, mixed pass/fail outcomes, or high variation across candidates.
- A review queue highlights mandatory gaps, borderline mandatory scores, low-confidence passes, extraction warnings, calibration concerns, model disagreements, and compliance notes.
- PDF evidence can include page references when extractable text is available.
- DOCX extraction includes paragraphs and tables.
- Optional OCR fallback is available if OCR dependencies and Tesseract are installed.
- Model-result caching reduces repeat API calls for the same CV, criteria, model, reasoning effort, and prompt version.
- Outputs include summary, matrix, evidence, review queue, calibration, model evaluation, compliance, cost dashboard, criteria, skipped files, extraction warnings, raw JSON, and extracted text.

## Setup

```powershell
cd niras-cv-screener-improved-app
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

You can set the API key once per terminal:

```powershell
$env:OPENAI_API_KEY="<your-openai-api-key>"
```

You can also paste the key directly into the OpenAI Setup panel in the app.

## Optional OCR Setup

OCR requires Python OCR packages plus a local Tesseract OCR installation. Install the Python packages with:

```powershell
pip install -r requirements-ocr.txt
```

Then install Tesseract OCR separately on Windows and make sure `tesseract.exe` is on PATH. If OCR is not installed, the app still runs and warns when OCR was requested but unavailable.

## Run

```powershell
streamlit run app.py
```

The app opens in the browser. Paste your OpenAI API key into the OpenAI Setup panel, paste criteria, check the parsed table, select a CV folder or upload files, choose model/comparison settings, review the model and cost preview, then run the screening.

## Reviewing Results

Each run creates a timestamped folder under the selected output directory. The main review file is:

- `screening_results.xlsx`

Important workbook sheets:

- `Summary`: candidate-level score and recommendation overview.
- `Review Queue`: items a human reviewer should check.
- `Calibration`: criteria that may need scoring calibration across candidates.
- `Model Evaluation`: candidate-level primary/comparison model differences.
- `Model Eval Details`: criterion-level model differences.
- `Compliance`: sensitive/protected information notices to ignore during review.
- `Cost Dashboard`: pre-run estimate, selected model rate card, actual token records, and estimated cost summary.

Additional files:

- `criteria_used.json`
- `results.json`
- `review_queue.json`
- `calibration_report.json`
- `model_evaluation.json`
- `cost_preview.json`
- `cost_records.json`
- `run_manifest.json`
- `raw_results/*.json`
- `comparison_results/*.json`
- `extracted_text/*.txt`

## Cost Notes

- Pre-run costs are estimates based on selected file sizes, criteria size, selected models, and output-size assumptions.
- The estimate is shown before app-level result-cache savings. Repeat runs of the same CV, criteria, model, reasoning effort, and prompt version may cost less if cached locally.
- Actual post-run costs use API token usage when returned by OpenAI, including cached input tokens where reported.
- Custom model IDs can still be used, but the app can only show dollar estimates for models in the local pricing table.

## Notes

- Scanned/image-only PDFs still require OCR before this app can score them well.
- The scoring logic is intentionally conservative: if a mandatory criterion fails, the candidate is recommended as `Reject` regardless of preferred scores.
- Human review is still expected, especially for borderline candidates, model disagreements, and compliance flags.

