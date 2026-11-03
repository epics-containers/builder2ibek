"""Estimate a sweep: generate every module in memory and under <status>/survey only,
with nothing validated and nothing written to a repo. Prints the outcome of each."""

from __future__ import annotations

import json
import signal
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gen import process  # noqa: E402
from release import pick  # noqa: E402
from settings import CFG  # noqa: E402
from sweep import inventory, pinned  # noqa: E402


def timeout(*_):
    raise TimeoutError


def survey(folders: list[str]):
    signal.signal(signal.SIGALRM, timeout)
    res = {}
    for it in inventory():
        name = it["dir"]
        if (folders and name not in folders) or (it["repo"], name) in CFG.hand_written or (it["repo"], name) in CFG.fork_twins():
            continue
        rel, how = pick(name, it["module"], it["install"])
        r = dict(repo=it["repo"], already_has_pvi=it["has_pvi"] and not pinned(name), release=str(rel), how=how)
        if rel is None:
            res[name] = {**r, "class": "no release"}
            print(name, "no release", flush=True)
            continue
        try:
            signal.alarm(120)
            rep = process(name, False, dict(repo=it["repo"], release=str(rel), dir=name, yaml=it["yaml"]), CFG.status / "survey")
            signal.alarm(0)
            devs = {k: v for k, v in rep["devices"].items() if "error" not in v}
            r["devices"] = {
                k: dict(records=v["n_records"], placed=v["n_placed"], unmatched=len(v["on_screen_not_in_db"]), judgements=len(v["judgements"]), how=v["how"], external=len(v["external"]), unmapped=sum(len(e["unmapped_macros"]) for e in v["entities"]))
                for k, v in devs.items()
            }
            r["errors"] = [v["error"] for v in rep["devices"].values() if "error" in v]
            r["no_screen"] = len(rep["no_screen"])
            r["class"] = "ok" if devs else ("root screen missing" if r["errors"] else "no entity has a screen")
        except Exception as e:  # noqa: BLE001
            signal.alarm(0)
            r["class"] = "exception"
            r["exception"] = f"{type(e).__name__}: {e}"
            r["where"] = traceback.format_exc().splitlines()[-3][:160]
        res[name] = r
        print(name, r["class"], flush=True)
    (CFG.status / "survey.json").write_text(json.dumps(res, indent=1))
