"""Settings: defaults overridden by PLAUD_CONFIG or the project's config.json."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "vault": str(Path.home() / "Documents" / "Obsidian Vault"),
    "base_folder": "Plaud",          # everything lives under <vault>/<base_folder>
    "inbox": "Inbox",                # folder new recordings land in
    "host": "127.0.0.1",
    "port": 8377,
    "data_dir": "data",
    "poll_minutes": 5,
    "auto_process": True,            # process recordings that appear after first start
    "whisper_model": "large-v3-turbo",
    "whisper_models": ["large-v3-turbo", "ensemble", "large-v3"],  # ensemble = whisper_model + Parakeet + LLM arbiter
    "auto_glossary_whisper": True,
    "ensemble_languages": ["it"],  # English removed in M7: ensemble did not improve Jobs & Gates WER (7.67% vs 7.55%)
    "parakeet_dir": "models/parakeet-v3",
    "whisper_compute_type": "float16",
    # Speaker separation. "pyannote" (GPU, needs .venv-pyannote and a Hugging Face login, see
    # README) got the right count on three test recordings without tuning and is ~10x faster;
    # "sherpa" is the built-in CPU path, also used if pyannote is missing or fails.
    "diar_engine": "pyannote",
    "diar_segmentation": "models/sherpa-onnx-pyannote-segmentation-3-0/model.onnx",
    "diar_embedding": "models/3dspeaker_speech_eres2netv2_sv_zh-cn_16k-common.onnx",  # best of 5 tested on your recordings
    "diar_threshold": 0.5,
    # Clusters whose pooled voices are at least this similar are one person. On three of your
    # recordings 0.84-0.86 gave the right count; 0.83 fused two people, 0.87 split one. Narrow,
    # so the dashboard asks you to check an automatic count.
    "diar_same_voice": 0.85,
    "diar_threads": 6,
    "default_provider": "claude",
    "arbiter_provider": None,        # defaults to default_provider when unset
    # LLM providers. "cli": prompt goes to stdin, answer comes from stdout (or the {out} file).
    # "openai": any OpenAI-compatible HTTP API; the key is read from the named environment variable.
    "providers": {
        "claude": {
            "type": "cli",
            "check": "Reply with exactly: OK",
            "model": "opus",
            "models": ["opus", "sonnet", "haiku"],
            "effort_args": ["--effort", "{effort}"],
            "cmd": [
                "claude", "-p", "--model", "{model}", "--tools", "", "--strict-mcp-config",
                "--setting-sources", "", "--disable-slash-commands", "--no-session-persistence",
                "--system-prompt", "You turn meeting transcripts into notes. Output only the requested text.",
            ],
        },
        "codex": {
            "type": "cli",
            "check": "Reply with exactly: OK",
            "model": "gpt-6.2-astra",
            "models_cache_file": "~/.codex/models_cache.json",
            "effort_args": ["-c", 'model_reasoning_effort="{effort}"'],
            "models": [
                "gpt-6.2-astra", "gpt-6.2-sol", "gpt-6.1-terra", "gpt-6.1-sol",
                "gpt-6-astra", "gpt-6-sol", "gpt-6-luna",
                "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna",
            ],
            "cmd": [
                "codex", "exec", "--model", "{model}", "--sandbox", "read-only",
                "--skip-git-repo-check", "--ephemeral", "--color", "never", "-o", "{out}", "-",
            ],
        },
        "antigravity": {
            "type": "cli",
            "check": "Reply with exactly: OK",
            "format": "agy-stream-json",
            "model": "gemini-4-hydrogen-medium",
            "models_cmd": ["agy", "models"],
            "models": [
                "gemini-4-hydrogen-medium", "gemini-4-hydrogen-high",
                "gemini-4-hydrogen-xhigh", "gemini-4-hydrogen-low",
                "gemini-4-neon-medium", "gemini-4-neon-high",
                "gemini-4-neon-xhigh", "gemini-4-neon-low",
                "gemini-4-argon-medium", "gemini-4-argon-high", "gemini-4-argon-low",
                "gemini-3.8-flash-medium", "gemini-3.8-flash-high", "gemini-3.8-flash-low",
                "claude-opus-5-5-medium", "claude-opus-5-5-high",
                "claude-sonnet-5-5-medium", "claude-sonnet-5-5-high",
                "gpt-oss-120b-medium",
            ],
            "cmd": [
                "agy", "--input-format", "stream-json", "--output-format", "stream-json",
                "--model", "{model}", "--sandbox", "--disable-slash-commands",
                "--settings", json.dumps({
                    "permissions": {
                        "deny": [
                            "command(*)", "write_file(*)", "replace_file_content(*)",
                            "multi_replace_file_content(*)", "sed_file(*)",
                            "notebook_edit(*)", "notebook_execution(*)", "mcp(*)",
                            "execute_url(*)", "open_browser_url(*)",
                            "browser_subagent(*)", "invoke_subagent(*)",
                            "run_workflow(*)", "schedule(*)",
                        ]
                    }
                }),
            ],
        },
        "api": {
            "type": "openai",
            "check": "Reply with exactly: OK",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-5",
            "api_key_env": "OPENAI_API_KEY",
            "dashboard_key": True,
        },
        "freellmapi": {
            "type": "openai",
            "check": "Reply with exactly: OK",
            "base_url": "http://127.0.0.1:31415/v1",  # FreeLLMAPI desktop app; :3001 is another project's instance
            "model": "auto",
            "api_key_env": "FREELLMAPI_API_KEY",
        },
    },
    "hallucination_blocklist": [
        "Thanks for watching", "Thank you for watching", "Subtitles by", "Please subscribe",
        "Like and subscribe", "Amara.org", "Grazie per la visione", "Sottotitoli di",
        "Sottotitoli a cura di", "Iscriviti al canale", "Sottotitoli creati dalla comunità",
    ],
}

_override = os.environ.get("PLAUD_CONFIG")
_user = Path(_override) if _override else ROOT / "config.json"
cfg = DEFAULTS | (json.loads(_user.read_text(encoding="utf-8")) if _override or _user.exists() else {})
if not cfg.get("arbiter_provider"):
    cfg["arbiter_provider"] = cfg["default_provider"]

VAULT = Path(cfg["vault"])
BASE = VAULT / cfg["base_folder"]
DATA = ROOT / cfg["data_dir"]        # local state only; not in the vault


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key, val = key.strip(), val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        if key and val and not os.environ.get(key):
            os.environ[key] = val


if DATA != ROOT / "data":
    load_dotenv(DATA / ".env")
load_dotenv(ROOT / ".env")
