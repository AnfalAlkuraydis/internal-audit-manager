"""Isolated connected-UI validation server; never touches the user's audit database."""
from pathlib import Path
from uuid import uuid4
import json
import uvicorn
from dotenv import load_dotenv
from backend.app import create_app
from backend.auth import AuthConfig
from backend.config import Settings
from backend.database.connection import create_database
from backend.database.migrate import migrate
from backend.database.repository import read_catalog,read_bundle,load_seed
from backend.agent.orchestrator import AgentRuntime

ROOT=Path(__file__).resolve().parents[1]

def main():
    """Serve a real one-control development audit to validate all connected UI checkpoints."""
    load_dotenv(ROOT/".env")
    folder=ROOT/"var/connected-ui-validation"/str(uuid4())
    folder.mkdir(parents=True)
    catalog=read_catalog(ROOT/"data/catalog.json")
    catalog=catalog.model_copy(update=dict(
        controls=[c for c in catalog.controls if c.id=="PR-02.v1"],
        procedures=[p for p in catalog.procedures if p.control_id=="PR-02.v1"]))
    engine=create_database(folder/"audit.sqlite")
    migrate(engine)
    load_seed(engine,catalog,read_bundle(ROOT/"data/development/dataset.json"))
    from backend.services.audit import AuditService
    runtime=AgentRuntime(AuditService(engine),folder/"checkpoints.sqlite")
    app=create_app(Settings.from_env(),engine=engine,runtime=runtime,enable_worker=True,
                   auth_config=AuthConfig("ui-test-auditor","ui-test-reviewer"))
    (ROOT/"evaluation/connected_ui_validation.json").write_text(json.dumps({
        "directory":str(folder.relative_to(ROOT)),"port":8001,"inference":"azure_grok",
        "scope":"Development PR-02; real approval, missing-evidence reply and remediation workflow"}),encoding="utf-8")
    uvicorn.run(app,host="127.0.0.1",port=8001,log_level="warning")

if __name__=="__main__":
    main()
