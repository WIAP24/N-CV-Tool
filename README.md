# NIRAS CV Screener

A Streamlit application for screening batches of CVs against role-specific criteria. The tool extracts text from CV files, asks an OpenAI model to score each criterion using evidence from the CV, then produces structured Excel and JSON outputs for human review, calibration, cost tracking, and auditability.

The app is designed for first-pass screening support. It does not replace a recruiter, hiring manager, or formal HR decision process. Its main value is making repeated CV review faster, more consistent, and easier to audit.

## Streamlit Community Cloud

Upload this package's contents to GitHub, preserving `src/`, `assets/`, and the other subfolders. In Community Cloud, select your repository and branch, set the entrypoint to `app.py` (or its repository-relative path), and select Python 3.13 in Advanced settings. `requirements.txt` installs Python dependencies; `packages.txt` installs Poppler and Tesseract for OCR on Linux. Reboot the app after changing dependencies.

The default is browser uploads and downloads. No desktop paths need to be configured:

1. Paste your API key in the app's password field. It remains in that user's session.
2. Enter Role Title, Essential Requirements and Preferred Requirements, with one criterion per line. Press Parse Criteria and check the table, then upload CVs from the `CVs` tab.
3. For desktop or synced OneDrive CVs, use the browser's file picker to select them. Make OneDrive files available offline first ("Always keep on this device").
4. Review the cost preview and run screening.
5. In Results, download Excel or the complete results ZIP. Choose your local or OneDrive destination using the browser's save dialog; if it downloads automatically, enable the browser's "Ask where to save each file" setting.

A cloud server cannot access `C:\Users\...`, a mapped drive, or your local OneDrive folder by receiving its path. Direct access to online OneDrive/SharePoint would require a separate authenticated Microsoft Graph integration; this version uses browser uploads.

Cloud runs process uploaded bytes directly in memory. The app does not write uploaded CVs, extracted text, JSON, Excel, ZIP files, or model caches to the server filesystem. Even Excel worksheet XML is generated in memory. The ZIP contains that run's Excel, JSON, extracted text, and skipped-file reports; it never contains the API key. Download it to save these files on your computer or synced OneDrive folder. Filenames are normalized and duplicates disambiguated. The browser upload limit is 200 MB per file by default; smaller batches reduce cloud memory use.

Use **Clear CVs, results and session** after downloading to reset session data, uploads, criteria and the entered API key. It does not remove files already downloaded to your device. Upload widgets reset after each run (including failures); results remain in session memory for review and download until cleared, replaced, or the session expires. Streamlit manages disconnected-session and download-buffer cleanup; closing the browser is not a guarantee of immediate memory erasure. Reports are not automatically saved to your computer: you must use the download buttons.

Cloud result caching and OCR are disabled. The existing OCR engine creates temporary files, so scanned PDFs must be made searchable using OCR on your computer before upload. OCR and disk caching remain available in explicitly enabled desktop mode. With no app cache in cloud mode, rerunning a batch makes new paid API calls.

After deployment, reboot the app. On Linux, startup removes the previous app's known `niras_session_*` and `niras_cv_uploads_*` temporary directories and generated `outputs/outputs_*` and `outputs/.cv_screener_cache` directories. If removal fails, screening is blocked. This is not a deletion guarantee for infrastructure backups, unknown older locations, or copies already sent to OpenAI.

### Online processing boundary

CV data still passes through Streamlit server memory and OpenAI. Every Responses API request sets `store=False`, including compatibility retries. This disables stored API responses; it does not enable account-level Zero Data Retention or override provider abuse-monitoring, prompt-caching, or infrastructure policies. Review [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data) for your account. This implementation prevents application-level CV file persistence, not every form of retention by hosting/API providers. Cloud errors omit raw provider exception bodies to avoid reflecting submitted CV text.

For trusted desktop use only, enable local paths before starting the app in PowerShell:

```powershell
$env:NIRAS_ALLOW_LOCAL_PATHS = "true"
python -m streamlit run app.py
```

This restores the folder-path input and output-folder field. Leave this setting unset on Community Cloud. Do not commit CVs, outputs, caches, or API keys to GitHub.

## Visual Style

The Streamlit interface uses NIRAS-inspired brand cues from the public NIRAS website: the red NIRAS logo, a restrained white and light-grey workspace, NIRAS red for primary actions, teal/blue accents for review states, and typography that follows the public site's Soho Gothic Pro and Guardian Egyptian font stack where available, with local system fallbacks when those fonts cannot be loaded.

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

   The `Criteria` tab starts empty with separate Role Title, Essential Requirements and Preferred Requirements fields. Enter one criterion per line and press Parse Criteria. Role Title and at least one essential criterion are required; preferred requirements are optional. Essential entries are mandatory, preferred entries are optional, and every non-empty line becomes one criterion even if it resembles a heading. Bullets and numbering are removed; optional weight and pass annotations are supported. The reviewer can edit the resulting table before screening. Changing the source fields clears the old table and requires parsing again to avoid stale criteria.

2. CV intake and extraction

   The user uploads files, or selects a folder in desktop mode. The app supports `.pdf`, `.docx`, `.txt`, and `.md`. PDF extraction uses embedded text where available. DOCX extraction reads paragraphs and table text. Optional OCR is available only in desktop mode; cloud users must OCR scans locally before upload.

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
- Optional result caching in desktop mode only; cloud runs never use disk or model-result caches.
- Extraction warnings for files with little or no usable text.
- Review queue for borderline or uncertain results.
- Calibration report showing scoring spread and variation by criterion.
- Compliance flagging for possible protected or sensitive personal information.
- Excel output designed for human review, not just machine processing.

## Model Selection And Cost Preview

The sidebar lets the user choose a primary model from presets or enter a custom model ID. The comparison pass is enabled by default and initially uses the same model as the primary run, so the first cost estimate reflects two assessment passes per candidate. The primary pass and comparison pass each have their own reasoning effort selector.

The app only shows reasoning effort options that are listed for the selected model in the local model catalog. When the selected model changes, the reasoning selector resets to that model's default reasoning level. `gpt-5.6-terra` and `gpt-5.6-luna` default to `medium`, while `gpt-5.6-sol` defaults to `high`.

The current priced presets are:

- `gpt-5-mini` - default for cost-efficient structured screening, with medium reasoning. Its standard rates are $0.25 input, $0.025 cached input and $2.00 output per million tokens, including reasoning output. The comparison pass defaults to the same model and its extra cost is included.
- `gpt-4o-mini` - optional lower-cost alternative, available for primary or comparison runs. Standard rates are $0.15 input, $0.075 cached input and $0.60 output per million tokens. It does not support adjustable reasoning effort.
- `gpt-5.6-terra` - balanced quality and cost, defaulting to `medium` reasoning.
- `gpt-5.6-sol` - higher-cost option for complex or high-stakes review, defaulting to `high` reasoning.
- `gpt-5.6-luna` - lower-cost GPT-5.6 option for high-volume screening, defaulting to `medium` reasoning.

Before the user starts a run, the `Run` tab shows:

- selected model rate cards
- supported/default reasoning effort for each selected model
- selected primary and comparison reasoning effort
- estimated model calls
- estimated input tokens
- estimated visible output tokens
- estimated reasoning output tokens
- estimated total output tokens
- estimated API cost
- cost impact of the default comparison pass

The estimate is intentionally shown before the run so the user can change model choice, reasoning effort, comparison settings, batch size, or criteria before spending API credits.

Cost estimates are based on file size, criteria size, selected models, selected reasoning effort, and expected response size. Reasoning effort matters because higher effort can produce extra reasoning output tokens, so the pre-run estimate applies a planning factor for `low`, `medium`, `high`, `xhigh`, and `max` effort levels. Actual costs can differ because PDF extraction length, OCR quality, model behavior, API tokenization, hidden reasoning, and API prompt caching can vary. After the run, the cost dashboard uses actual API token usage when available and records reported reasoning output tokens separately.

GPT-5 mini and GPT-4o mini pricing was checked against their official model pages on 2026-09-21: [GPT-5 mini](https://developers.openai.com/api/docs/models/gpt-5-mini), [GPT-4o mini](https://developers.openai.com/api/docs/models/gpt-4o-mini). The other preset rates retain their 2026-07-24 check date. GPT-5 mini supports minimal, low, medium and high reasoning; all levels are included in pre-run cost estimates. GPT-5.5 is not offered as a preset.

The [API deprecation schedule](https://developers.openai.com/api/docs/deprecations), checked 2026-09-21, lists retirement of the dated `gpt-5-mini-2025-08-07` snapshot on 11 December 2026. This app selects the `gpt-5-mini` alias; review its availability before that date rather than assuming indefinite support. No shutdown of the standard `gpt-4o-mini` text model or `gpt-5.5` API model was listed in that schedule. ChatGPT/Codex product retirement notices do not necessarily apply to API access. Pricing and availability can change.

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

The app runs a comparison pass by default against the same CVs and criteria. By default, the comparison model is the same as the primary model selected for the initial run. This gives reviewers a second assessment pass for calibration, quality checks, and reviewing borderline decisions.

When enabled, the app compares:

- primary recommendation
- comparison recommendation
- weighted score difference
- criterion-level score differences
- pass/fail flips
- evidence differences

Because comparison mode makes an additional model call for each CV, it increases cost unless cached results are reused. The pre-run cost preview and exported cost dashboard include this comparison cost, even when the comparison model matches the primary model. You can disable comparison mode in the sidebar when a lower-cost single-pass run is preferred.

## Compliance And Sensitive Information

The app includes a basic compliance scan for possible protected or sensitive personal information, such as age, marital status, nationality, religion, gender, disability, and health references.

These flags are included so reviewers can avoid relying on irrelevant or protected information. The flags are not legal advice and do not determine candidate suitability. They are prompts for human caution.

## Data Handling

- The OpenAI API key can be pasted into the UI or supplied through `OPENAI_API_KEY`.
- The API key is held in the app session and is not written to output files.
- CV text is sent to OpenAI for model scoring when a run is started.
- In default browser mode, download output files from Results. In optional desktop mode, files are also written to the selected output folder.
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

OCR is only needed for scanned or image-only PDFs and is disabled in cloud mode. For desktop use, install the optional Python packages with:

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

1. Enter the role title and separate essential and preferred requirements in the `Criteria` tab, then press Parse Criteria.
2. Confirm the parsed criteria table.
3. Upload files in the `CVs` tab (or select a folder when desktop mode is enabled).
4. Choose model, thresholds, caching, OCR, and comparison settings.
5. Review the model and cost preview in the `Run` tab.
6. Press `Run Screening`.
7. Review results in the app or download the Excel workbook.

## Outputs

Cloud runs generate all reports in memory for download, without creating a report folder on the server. Desktop mode creates a timestamped report folder under the selected local output directory.

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
- model catalog defaults and removed preset checks
- trimmed model catalog checks
- cached-input and no-cached-discount pricing behaviour
- reasoning-effort impact on pre-run cost estimates
- model comparison flags
- calibration flags
- review queue generation
- workbook generation, including cost dashboard fields

Run `python -m unittest discover -s tests` to verify the app, including cloud uploads, downloads, and session cleanup.

## Nuances And Limitations

- The model can only score what is present in the extracted CV text.
- Poorly scanned PDFs may need OCR before reliable scoring is possible.
- OCR quality depends on scan quality and local Tesseract installation.
- Model outputs should be reviewed, especially for borderline candidates.
- The app deliberately separates model scoring from final recommendation logic.
- Cost estimates are estimates, not invoices, and include selected reasoning effort, estimated reasoning output tokens, and the comparison pass when comparison is enabled.
- Custom model IDs may work, but dollar cost estimates are only available for models in the local pricing table. Generic GPT-5 custom IDs can still expose reasoning effort choices.
- The pricing table should be reviewed periodically because model pricing and supported reasoning options can change.
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
