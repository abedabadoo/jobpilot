from __future__ import annotations
import argparse
import json
from pathlib import Path
from .models import ModelSettings, Profile, RunRequest


def main():
    parser = argparse.ArgumentParser(description="ResumeForge local resume engine")
    sub = parser.add_subparsers(dest="command", required=True)
    web = sub.add_parser("serve",help="Open the local desktop-style app")
    web.add_argument("--port",type=int,default=8765)
    web.add_argument("--data-dir",type=Path)
    web.add_argument("--open",action="store_true")
    cli = sub.add_parser("run",help="Tailor and verify a resume from JSON")
    cli.add_argument("--profile",type=Path)
    cli.add_argument("--job",type=Path)
    cli.add_argument("--keywords",default="")
    cli.add_argument("--provider",choices=["none","ollama","openai-compatible"],default="none")
    cli.add_argument("--mode", choices=["inspiration","grounded","verified"], default="inspiration")
    cli.add_argument("--model",default="")
    cli.add_argument("--endpoint",default="http://127.0.0.1:11434")
    cli.add_argument("--out",required=True,type=Path)
    cli.add_argument("--request",type=Path,help="Full RunRequest JSON including a reviewed plan; overrides other inputs")
    inspect = sub.add_parser("inspect",help="Extract source text and template geometry")
    inspect.add_argument("file",type=Path)
    args = parser.parse_args()
    if args.command == "serve":
        from .server import serve
        serve(args.port,args.data_dir,args.open)
    elif args.command == "inspect":
        from .importing import inspect_document
        print(json.dumps(inspect_document(args.file.name,args.file.read_bytes()),indent=2))
    else:
        from .engine import run
        if not args.request and not args.profile:
            parser.error("run requires --profile or --request")
        request = RunRequest.model_validate_json(args.request.read_text()) if args.request else RunRequest(
            profile=Profile.model_validate_json(args.profile.read_text()), job_description=args.job.read_text() if args.job else "",
            keywords=[k.strip() for k in args.keywords.split(",") if k.strip()],
            settings=ModelSettings(draft_mode="inspiration" if args.mode=="inspiration" else "grounded", wording_policy="verified" if args.mode=="verified" else "rewrite",provider=args.provider,model=args.model,base_url=args.endpoint))
        result = run(request,args.out,lambda m:print(m,flush=True))
        print(json.dumps({"status":result["status"],"bottom_gap_pt":result["report"]["bottom_gap_pt"],"output":str(args.out.resolve())},indent=2))
        if result["status"] != "ready":
            raise SystemExit(2)


if __name__ == "__main__":
    main()
