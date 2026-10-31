"""Build and test the actual React workspace and append measured results."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from uuid import uuid4
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1]

def main():
    """Use installed Node (or the verified local portable copy), never install it silently."""
    node=shutil.which("node")
    if not node:
        candidates=sorted((ROOT/".tools").glob("node-*-win-x64/node.exe"))
        node=str(candidates[-1]) if candidates else None
    if not node:
        raise SystemExit("Node is required; frontend checks NOT RUN.")
    npm=Path(node).parent/"node_modules/npm/bin/npm-cli.js"
    if not npm.exists():
        raise SystemExit("npm CLI was not found beside Node; frontend checks NOT RUN.")
    env={**os.environ,"PATH":str(Path(node).parent)+os.pathsep+os.environ.get("PATH","")}
    run_id=str(uuid4());results=[]
    for name,args in [("production_build",["run","build"]),("dom_tests",["test"]),("dependency_audit",["audit","--json"])]:
        started=time.perf_counter()
        process=subprocess.run([node,str(npm),*args],cwd=ROOT/"frontend",env=env,
            capture_output=True,text=True,encoding="utf-8",errors="replace")
        result=dict(run_id=run_id,event="phase4_frontend_check",check=name,
            status="PASS" if process.returncode==0 else "FAIL",exit_code=process.returncode,
            execution_date_utc=datetime.now(timezone.utc).isoformat(),test_version="phase4-v1",
            duration_seconds=time.perf_counter()-started,
            actual_stdout=process.stdout[-9000:],actual_stderr=process.stderr[-4000:])
        with (ROOT/"evaluation/frontend_tests.txt").open("a",encoding="utf-8") as f:
            f.write(json.dumps(result)+"\n")
        results.append({k:v for k,v in result.items() if k not in {"actual_stdout","actual_stderr"}})
        print(json.dumps(results[-1]),flush=True)
    with (ROOT/"evaluation/metrics_summary.txt").open("a",encoding="utf-8") as f:
        f.write(json.dumps(dict(run_id=run_id,event="phase4_frontend_checks",results=results))+"\n")
    raise SystemExit(0 if all(r["status"]=="PASS" for r in results) else 1)

if __name__=="__main__":
    main()
