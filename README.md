# N CV Screener

A Streamlit application for screening batches of CVs against role-specific criteria. The tool extracts text from CV files, asks an OpenAI model to score each criterion using evidence from the CV, then produces structured Excel and JSON outputs for human review, calibration, cost tracking, and auditability.

The app is designed for first-pass screening support. It does not replace a recruiter, hiring manager, or formal HR decision process. Its main value is making repeated CV review faster, more consistent, and easier to audit.

## What The Tool Does

The tool helps a reviewer:

- Paste role requirements or evaluation criteria into the app.
- Convert those criteria into an editable scoring table.
- Load multiple CVs from a folder or by upload.
- Extract text from PDF, DOCX, TXT, or Markdown files.
- Score each CV against every criterion using an OpenAI model.
- Calculate mandatory-pass status, weighted averages, and recommendations in deterministic Python code.
- Highlight candidates or criteria that need human review.
- Produce an Excel workbook and JSON files that can be reviewed, shared, or archived.
- Estimate OpenAI cost before the run and summarize actual token/cost usage after the run.

## How It Works

The workflow has five main stages.

1. Criteria preparation

   The user pastes role criteria into the `Criteria` tab. The app parses the text into rows with criterion IDs, sections, mandatory flags, pass scores, and weights. The reviewer can edit the parsed table before running the screen.

2. CV intake and extraction

   The user selects a folder of CVs or uploads files. The app supports `.pdf`, `.docx`, `.txt`, and `.md`. PDF extraction uses embedded text where available. DOCX extraction reads paragraphs and table text. Optional OCR can be enabled for scanned PDFs if the OCR dependencies and Tesseract are installed.

3. Model assessment

   The OpenAI model receives the criteria and extracted CV text. It is instructed to return evidence-backed criterion scores only. The model does not make the final recommendation. This keeps the subjective extraction and judgement step separate from the deterministic scoring step.

4. Deterministic scoring

   Python code calculates pass/fail status, mandatory gaps, weighted score, preferred score, and recommendation. If a mandatory criterion fails, the candidate is rejected regardless of preferred scores. This keeps the business rule clear and reproducible.

5. Review, calibration, and export

   The app builds a review queue, calibration report, optional model comparison report, compliance flags, cost dashboard, Excel workbook, and JSON outputs.

## Key Features

- Editable criteria table before screening.
- Mandatory and preferred criteria support.
- Criterion-level score, rationale, confidence, source reference, and evidence.
- Deterministic recommendation logic in code.
- Optional comparison-model run for calibration or higher-risk batches.
- Pre-run model and cost preview before pressing `Run Screening`.
- Post-run cost dashboard using API token usage where available.
- Local result caching to reduce repeat model calls for unchanged inputs.
- Extraction warnings for files with little or no usable text.
- Review queue for borderline or uncertain results.
- Calibration report showing scoring spread and variation by criterion.
- Compliance flagging for possible protected or sensitive personal information.
- Excel output designed for human review, not just machine processing.

## Model Selection And Cost Preview

The sidebar lets the user choose a primary model from presets or enter a custom model ID. The current presets are:

- `gpt-5.6-terra` - balanced quality and cost, used as the default.
- `gpt-5.6-sol` - higher-cost option for complex or high-stakes review.
- `gpt-5.6-luna` - lower-cost option for high-volume screening.
- `gpt-5.6` - alias-style option included for compatibility.
- `gpt-4o-mini` - lower-cost legacy preset.

Before the user starts a run, the `Run` tab shows:

- selected model rate card
- estimated model calls
- estimated input tokens
- estimated output tokens
- estimated API cost
- cost impact of enabling a comparison model

The estimate is intentionally shown before the run so the user can change model choice, disable comparison, reduce the batch size, or adjust criteria before spending API credits.

Cost estimates are based on file size, criteria size, selected models, and expected response size. Actual costs can differ because PDF extraction length, OCR quality, model behavior, API tokenization, and API prompt caching can vary. After the run, the cost dashboard uses actual API token usage when available.

## Scoring Logic

The model scores each criterion from 0 to 5:

- `0`: no evidence
- `1`: very weak evidence
- `2`: partial or unclear evidence
- `3`: adequate evidence
- `4`: strong evidence
- `5`: excellent evidence

Each criterion can have:

- `mandatory`: whether the criterion must pass
- `pass_score`: minimum score needed for that criterion
- `weight`: how much that criterion contributes to weighted scoring
- `section`: for grouping requirements
- `criterion_id`: stable ID used in outputs and comparisons

The app then calculates:

- mandatory pass count
- mandatory average
- preferred average
- weighted score
- critical gaps
- recommendation

The default recommendation logic is conservative:

- If any mandatory criterion fails, recommendation is `Reject`.
- If mandatory criteria pass and weighted score meets the interview threshold, recommendation is `Interview`.
- If mandatory criteria pass and weighted score meets the reserve threshold, recommendation is `Reserve`.
- Otherwise recommendation is `Reject`.

Thresholds can be changed in the sidebar before running.

## Human Review Checks

The app creates a review queue so the reviewer can focus on uncertain or important cases. Review queue items can include:

- Failed mandatory criteria.
- Borderline mandatory scores close to the pass score.
- Low-confidence passes.
- Missing or weak evidence.
- Missing source references.
- Extraction warnings.
- Calibration warnings for criteria with unusual spread or variation.
- Model comparison disagreements.
- Possible compliance issues.

The review queue is not a final decision list. It is a prioritised set of items that should be checked by a person.

## Calibration Checks

The calibration report looks across all screened candidates and flags criteria that may need closer review. It can help identify:

- criteria where candidates receive very different scores
- criteria with mixed pass/fail outcomes
- criteria with high score variation
- criteria that may be ambiguous or too broad
- criteria where the model may need stronger guidance

This is useful after an initial batch because it helps reviewers decide whether the criteria need rewriting, whether score thresholds are fair, or whether a second model pass is worth running.

## Optional Model Evaluation

The app can run a comparison model against the same CVs and criteria. This is useful for calibration, quality checks, and reviewing borderline decisions.

When enabled, the app compares:

- primary recommendation
- comparison recommendation
- weighted score difference
- criterion-level score differences
- pass/fail flips
- evidence differences

Because comparison mode makes an additional model call for each CV, it increases cost unless cached results are reused. It is best used for calibration batches, shortlists, disputed cases, or spot checks rather than every routine run.

## Compliance And Sensitive Information

The app includes a basic compliance scan for possible protected or sensitive personal information, such as age, marital status, nationality, religion, gender, disability, and health references.

These flags are included so reviewers can avoid relying on irrelevant or protected information. The flags are not legal advice and do not determine candidate suitability. They are prompts for human caution.

## Data Handling

- The OpenAI API key can be pasted into the UI or supplied through `OPENAI_API_KEY`.
- The API key is held in the app session and is not written to output files.
- CV text is sent to OpenAI for model scoring when a run is started.
- Output files are written locally to the selected output folder.
- Generated outputs and caches are ignored by `.gitignore`.
- This GitHub-ready package does not include real CVs, extracted CV text, raw screening outputs, Excel outputs, or local caches.

Users should still confirm that their organisation allows CV data to be processed through the selected OpenAI account and model.

## Setup

Create a virtual environment and install the required packages:

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

OCR is only needed for scanned or image-only PDFs. Install the optional Python packages with:

```powershell
pip install -r requirements-ocr.txt
```

Then install Tesseract OCR separately on Windows and make sure `tesseract.exe` is on PATH.

If OCR is not installed, the app still runs. It will warn when OCR was requested but unavailable.

## Run The App

```powershell
streamlit run app.py
```

Then open the local Streamlit URL in a browser if it does not open automatically.

Typical use:

1. Paste or edit criteria in the `Criteria` tab.
2. Confirm the parsed criteria table.
3. Select a CV folder or upload files in the `CVs` tab.
4. Choose model, thresholds, caching, OCR, and optional comparison settings.
5. Review the model and cost preview in the `Run` tab.
6. Press `Run Screening`.
7. Review results in the app or download the Excel workbook.

## Outputs

Each run creates a timestamped folder under the selected output directory.

Main workbook:

- `screening_results.xlsx`

Workbook sheets:

- `Summary`: candidate-level recommendation, scores, gaps, review counts, and comparison summary.
- `Screening Matrix`: criteria by candidate score matrix.
- `Evidence`: criterion-level score, evidence, confidence, notes, and source reference.
- `Review Queue`: human review actions and notes columns.
- `Calibration`: score spread, pass rate, variation, and calibration flags by criterion.
- `Model Evaluation`: candidate-level primary/comparison model differences.
- `Model Eval Details`: criterion-level model score and evidence differences.
- `Compliance`: possible sensitive-information flags.
- `Criteria`: criteria snapshot used for the run.
- `Skipped files`: files that could not be processed.
- `Extraction Warnings`: file extraction issues.
- `Cost Dashboard`: pre-run estimate, selected model rate card, actual token records, and estimated cost summary.
- `Run Settings`: run configuration and summary metadata.

JSON outputs:

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

## Testing

Run the unit tests with:

```powershell
python -m unittest discover -s tests
```

The tests cover:

- criteria parsing
- duplicate criterion validation
- scoring and recommendation logic
- model comparison flags
- calibration flags
- review queue generation
- cost estimation
- workbook generation

A GitHub Actions workflow is included at `.github/workflows/tests.yml` so tests run automatically after publishing to GitHub.

## Nuances And Limitations

- The model can only score what is present in the extracted CV text.
- Poorly scanned PDFs may need OCR before reliable scoring is possible.
- OCR quality depends on scan quality and local Tesseract installation.
- Model outputs should be reviewed, especially for borderline candidates.
- The app deliberately separates model scoring from final recommendation logic.
- Cost estimates are estimates, not invoices.
- Custom model IDs may work, but cost estimates are only available for models in the local pricing table.
- The pricing table should be reviewed periodically because model pricing can change.
- Compliance flags are simple text-pattern alerts and may produce false positives or miss subtle issues.
- The tool should not be used as the sole basis for hiring decisions.

## Repository Hygiene

The `.gitignore` excludes:

- virtual environments
- Python bytecode
- local secrets
- generated outputs
- local caches
- generated Excel files
- editor and OS noise

Before publishing a repository, check that no CV files, extracted text, output workbooks, raw model results, or API keys have been added.
