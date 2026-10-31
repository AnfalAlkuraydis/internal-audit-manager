# Internal Audit Manager

audit agent with a connected React workspace. Azure Grok chooses permitted actions through eight typed tools; LangGraph checkpoints workflow progress. SQLite stores evidence, results, reviews and simulated communication. Human approval remains required for plans, findings, escalations and closure. Gmail and later phases are not implemented.

This repository contains the connected UI only. It excludes the standalone mock prototype, superseded UI builds, local audit sessions, databases, checkpoints, credentials and browser profiles. Evaluation records are retained as testing evidence, not active audit state.

## Setup

Requires Python 3.12 and Node.js with npm.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
Copy-Item .env.example .env
# Configure Azure endpoint/deployment/key and distinct private auditor/reviewer tokens locally.
.\.venv\Scripts\python.exe -m scripts.prepare_data
cd frontend
npm ci
npm run build
cd ..
.\.venv\Scripts\python.exe -m uvicorn backend.app:create_app --factory --env-file .env --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 and sign in with the locally configured auditor or reviewer token. Never commit `.env`. Starting the server does not migrate or seed storage; run prepare_data first.

## Connected workflow

Create an audit assignment, review and approve the generated plan, then observe real agent activity and saved control outcomes. The seven sections show actual records. Synthetic email replies are explicit previews submitted through evidence validation; they can resume affected work and support independent retesting. They are not real Gmail messages. Ordinary follow-ups default to three days with deadline-aware adjustment. Existing paused sessions remain dormant.

## Tests and evidence

```powershell
.\.venv\Scripts\python.exe -m scripts.run_tests
cd frontend
npm test
npm run build
cd ..
# Optional paid real-provider evaluations; not part of ordinary offline tests:
.\.venv\Scripts\python.exe -m scripts.run_tests --live
.\.venv\Scripts\python.exe -m scripts.evaluate_heldout
```

- [Held-out report](evaluation/heldout_report.md): 36/36 control results and 3/3 real-agent cases on the recorded synthetic held-out partition. Provisional labels and small sample limit generalization.
- [Named component proof](evaluation/component_test_proof.md): 21 passing component tests from the recorded evaluation.
- [Regression history](evaluation/regression_history.txt) and component/integration/system logs preserve actual historical outcomes, including failures and NOT RUN entries.
- [Connected UI validation](docs/connected_ui_report.md), [real connected receipts](evaluation/connected_ui_trace.json), and [browser results](frontend/review/connected-browser.json) document the connected workflow.
- [Evaluation methodology](docs/evaluation_methodology.md) and [architecture](docs/architecture_decisions.md) explain safeguards and limitations. Phase reports describe historical implementation milestones; the connected UI is the current interface.

These are historical measured results, not a claim that every current source revision was rerun live. Evaluation harness approvals apply only in isolated test databases. Azure rate limits can pause live progress; missing or unexecuted live checks must remain NOT RUN. No credential, runtime database or active audit state is required to inspect the evidence.

See [publication manifest](docs/publication_manifest.json) for the exact source/evidence inventory and hashes prepared for GitHub. Local absolute paths in historical receipts identify the original test environment; referenced runtime databases are deliberately excluded.
