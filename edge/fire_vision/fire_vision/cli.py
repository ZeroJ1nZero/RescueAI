import argparse
import json
import sys
from pathlib import Path

from .config import load_config
from .environment import inspect_environment
from .export import Session, write_json, verify_export, protect_source


def main(argv=None):
    effective = list(argv) if argv is not None else sys.argv[1:]
    if effective and effective[0] == "spatial":
        from .spatial.cli import main as spatial_main
        return spatial_main(effective[1:])
    parser=argparse.ArgumentParser(description="Measured RGB-D/IMU experiment tooling; E0 first")
    sub=parser.add_subparsers(dest="command",required=True)
    env=sub.add_parser("environment"); env.add_argument("--out",required=True)
    inv=sub.add_parser("inspect-bag"); inv.add_argument("bag"); inv.add_argument("--out",required=True)
    extract=sub.add_parser("extract-bag"); extract.add_argument("bag"); extract.add_argument("--config",required=True); extract.add_argument("--out",required=True)
    for name in ("check-input","replay","run","project-objects"):
        cmd=sub.add_parser(name)
        cmd.add_argument("--config",required=True); cmd.add_argument("--out",required=True)
        if name=="run":
            cmd.add_argument("stage",choices=[f"E{i}" for i in range(1,6)])
            cmd.add_argument("--repeat",type=int,default=3,choices=[3])
        if name=="replay":
            cmd.add_argument("--validated-session",required=True)
    exp=sub.add_parser("export"); exp.add_argument("session")
    args=parser.parse_args(argv)
    session=None
    try:
        if args.command=="environment":
            target=Path(args.out)
            if target.exists():
                raise FileExistsError(target)
            target.parent.mkdir(parents=True,exist_ok=True)
            write_json(target,inspect_environment())
            print(f"Environment recorded: {target}")
            return 0
        if args.command=="inspect-bag":
            from .dataset_adapter import inventory_bag
            protect_source(args.out,args.bag)
            if Path(args.out).exists():
                raise FileExistsError(args.out)
            write_json(args.out,inventory_bag(args.bag))
            return 0
        if args.command=="export":
            result=verify_export(args.session)
            print(json.dumps(result,ensure_ascii=False,indent=2))
            return 2 if result["hash_mismatches"] else 0
        c=load_config(args.config)
        if args.command=="extract-bag":
            from .dataset_adapter import extract_bag
            extract_bag(args.bag,args.out,c)
            print(f"Extracted: {args.out}; physical calibration review is still required")
            return 0
        session=Session(args.out,c,inspect_environment())
        session.data["command"] = argv if argv is not None else sys.argv[1:]
        if args.command=="check-input":
            if not c["dataset"]["path"] or not Path(c["dataset"]["path"]).exists():
                session.stage("E0","not_run","dataset_missing")
                session.failure("E0","dataset_missing","Provide a measured OpenLORIS recording and run inspect-bag/extract-bag")
                session.finish()
                print("E0 not run: dataset_missing",file=sys.stderr)
                return 2
            from .validation import validate_input
            session.stage("E0","running"); session.finish()
            report=validate_input(c["dataset"]["path"],c,session.path)
            session.stage("E0",report["status"],None if report["status"]=="passed" else "input_validation_failed")
            for i in report["issues"]:
                if i["severity"]=="error":
                    session.failure("E0",i["code"],i["detail"])
            session.finish()
            print(f"E0 {report['status']}: {session.path}")
            return 0 if report["status"]=="passed" else 2
        if args.command=="replay":
            from .replay import replay_ros
            replay_ros(c["dataset"]["path"],c,args.validated_session,session)
            session.finish()
            return 0
        stage=args.stage if args.command=="run" else "E3"
        from .localization import blockers
        reasons=blockers(stage,c)
        if stage not in {"E1","E2"}:
            reasons.append("E1 not passed; later-stage integration is intentionally deferred")
        session.data["requested_repetitions"]=getattr(args,"repeat",None)
        session.stage(stage,"not_run","; ".join(reasons))
        session.failure(stage,"stage_gate", "; ".join(reasons))
        session.finish()
        print(f"{stage} not run: "+"; ".join(reasons),file=sys.stderr)
        return 2
    except Exception as e:
        if session is not None:
            stage="E0" if args.command=="check-input" else getattr(args,"stage","E0")
            session.stage(stage,"failed",type(e).__name__)
            session.failure(stage,type(e).__name__,str(e))
            if session.data.get("replay",{}).get("status")=="running":
                session.data["replay"]["status"]="failed"
            session.finish()
        print(f"{type(e).__name__}: {e}",file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
