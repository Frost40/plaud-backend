"""Fake CLI provider for offline tests (stdin -> stdout / {out} / stream-json)."""
import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--out")
    parser.add_argument("--stream-json", action="store_true")
    parser.add_argument("--exit", type=int, default=0)
    parser.add_argument("--stdout", default="")
    parser.add_argument("--stderr", default="")
    parser.add_argument("--echo-cwd", action="store_true")
    args, _ = parser.parse_known_args()

    raw = sys.stdin.read()
    if args.stream_json and raw.strip():
        event = json.loads(raw.splitlines()[0])
        prompt = event["message"]["content"]
    else:
        prompt = raw

    if args.stderr:
        sys.stderr.write(args.stderr)

    reply = args.stdout or (f"CWD={Path.cwd()}|PROMPT={prompt.strip()}" if args.echo_cwd else f"OK: {prompt.strip()}")
    if args.exit != 0:
        if args.stream_json and not args.stdout:
            sys.stdout.write(json.dumps({"event": "result", "result": {"status": "ERROR", "error": args.stderr or "failed"}}) + "\n")
        elif args.stdout:
            sys.stdout.write(args.stdout)
        return args.exit

    if args.stream_json:
        sys.stdout.write(json.dumps({"event": "result", "result": {"status": "SUCCESS", "response": reply}}) + "\n")
    elif args.out:
        Path(args.out).write_text(reply, encoding="utf-8")
    else:
        sys.stdout.write(reply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
