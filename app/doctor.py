"""Read-only setup checks: python -m app.doctor [--config FILE]."""
import argparse
import datetime as dt
import os
import shutil


def check() -> dict:
    from app import plaud
    from app.config import ROOT, VAULT, cfg
    checks = {}
    try:
        plaud.me()
        checks["plaud"] = "ok"
    except Exception as e:
        checks["plaud"] = " ".join(str(e).split())
    try:
        import ctranslate2
        checks["GPU"] = "ok" if ctranslate2.get_cuda_device_count() > 0 else "install/update the NVIDIA driver; no CUDA GPU found"
    except Exception as e:
        checks["GPU"] = f"repair the CUDA installation: {e}"
    checks["ffmpeg"] = "not needed"
    parakeet = ROOT / cfg["parakeet_dir"]
    missing = [name for name in ("config.json", "encoder-model.onnx", "decoder_joint-model.onnx", "vocab.txt")
               if not (parakeet / name).is_file()]
    checks["parakeet_dir"] = "ok" if not missing else f"fetch models into {parakeet}; missing {', '.join(missing)}"
    for key in ("diar_segmentation", "diar_embedding"):
        path = ROOT / cfg[key]
        checks[key] = "ok" if path.is_file() else f"fetch model: {path}"
    checks["pyannote"] = "ok" if (ROOT / ".venv-pyannote/Scripts/python.exe").is_file() else "create .venv-pyannote (documentation/SETUP.md)"
    checks["vault"] = "ok" if VAULT.is_dir() else f"create the vault folder or fix config.json: {VAULT}"
    providers = [name for name, p in cfg["providers"].items() if p["type"] == "cli" and shutil.which(p["cmd"][0])]
    checks["providers"] = "ok: " + ", ".join(providers) if providers else "install a provider CLI (documentation/SETUP.md)"
    failed = [name for name, result in checks.items() if not result.startswith("ok") and result != "not needed"]
    return {"checks": checks, "summary": "Setup ok" if not failed else "Setup needs attention: " + ", ".join(failed),
            "at": dt.datetime.now().isoformat(timespec="seconds")}


def check_providers(log=lambda m: None, provider: str | None = None) -> dict[str, dict]:
    from app import llm
    from app.config import cfg
    names = [provider] if provider is not None else list(cfg["providers"])
    results = {}
    for name in names:
        if name not in cfg["providers"]:
            continue
        if llm.is_installed(name):
            log(f"checking {name}")
        results[name] = llm.check(name)
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    parser.add_argument("--fetch-models", action="store_true", help="print download commands; do not run them")
    parser.add_argument("--providers", action="store_true", help="check every configured AI provider")
    args = parser.parse_args()
    if args.config:
        os.environ["PLAUD_CONFIG"] = args.config
    if args.providers:
        for name, res in check_providers().items():
            if res["ok"]:
                print(f"{name}: ok ({res['message']}) [{res['at']}]")
            elif res["message"] == "not installed":
                print(f"{name}: not installed")
            else:
                print(f"{name}: failed ({res['message']})")
        return
    if args.fetch_models:
        print(r'''.venv\Scripts\python -c "import onnx_asr; onnx_asr.load_model('nemo-parakeet-tdt-0.6b-v3', 'models/parakeet-v3', providers=['CPUExecutionProvider'])"
New-Item -ItemType Directory -Force models | Out-Null
Invoke-WebRequest 'https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2' -OutFile models/segmentation.tar.bz2
tar -xf models/segmentation.tar.bz2 -C models
Invoke-WebRequest 'https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_eres2netv2_sv_zh-cn_16k-common.onnx' -OutFile models/3dspeaker_speech_eres2netv2_sv_zh-cn_16k-common.onnx''')
        return
    for name, result in check()["checks"].items():
        print(f"{name}: {result}")


if __name__ == "__main__":
    main()
