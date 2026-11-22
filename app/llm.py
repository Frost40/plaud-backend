"""One function, any provider: a subscription CLI (prompt on stdin) or an OpenAI-compatible API."""
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

import httpx

from app.config import DATA, ROOT, cfg

DEFAULT_CHECK = "Reply with exactly: OK"
HTTP_TRANSPORT = None
ENV_FILE: Path | None = None
_PROVIDERS_LOCK = threading.Lock()
_ENV_STATE: tuple[Path, int] | None = None

_AUTH_RE = re.compile(
    r"not logged in|not logged into|not signed in|please run /login|claude auth login|codex login|"
    r"open codex to sign in|log in from the terminal|sign in with chatgpt|oauth reauthentication|"
    r"sign in again|sign in required|cannot sign in|please log in|log in again|"
    r"authentication required|authentication[_ ]failed|authentication[_ ]error|"
    r"auth(?:entication)?[_ ](?:expired|invalid)|invalid[_ ]api[_ ]key|incorrect api key|"
    r"oauth token (?:expired|revoked)|token[_ ]expired|token could not be refreshed|"
    r"refresh token expired|\bunauthenticated\b|\bunauthorized\b|"
    r"(?:http|status|error|code|unauth)[^\n]{0,20}\b401\b|^\s*401\b",
    re.I | re.M,
)
_LIMIT_RE = re.compile(
    r"usage[_ ]limit|hit your limit|rate[_ -]?limit|quota[_ ]?(?:exceeded|exhausted|reached)|"
    r"resource[_ ]exhausted|model_capacity_exhausted|insufficient[_ ]quota|too many requests|"
    r"credit balance(?: is)? too low|(?:http|status|error|code|too many)[^\n]{0,20}\b429\b|^\s*429\b",
    re.I | re.M,
)


class ProviderError(RuntimeError):
    def __init__(self, provider: str, kind: str, message: str, exit_code: int | None = None):
        super().__init__(message)
        self.provider = provider
        self.kind = kind
        self.exit_code = exit_code


def classify(provider: str, exit_code: int | None, text: str) -> str:
    p = cfg["providers"].get(provider, {})
    if p.get("type") == "openai":
        if exit_code == 429:
            return "limit"
        if exit_code == 401:
            return "auth"
    if _AUTH_RE.search(text or ""):
        return "auth"
    if _LIMIT_RE.search(text or ""):
        return "limit"
    return "other"


def _format_error(provider: str, kind: str, code: int | None, detail: str) -> str:
    snippet = " ".join(detail.split())[-400:]
    if kind == "auth":
        return f"sign in to {provider} again ({snippet})" if snippet else f"sign in to {provider} again"
    if kind == "limit":
        return f"{provider} limit ({snippet})" if snippet else f"{provider} limit reached"
    return f"{provider} failed (exit {code}): {snippet}"


def _parse_agy_stream(stdout: str) -> tuple[str, str]:
    """Return (response_text, error_text) from agy --output-format stream-json NDJSON output."""
    result = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("event") == "result":
            result = obj.get("result") or {}
    if result is None:
        return "", ""
    if result.get("status") != "SUCCESS":
        return "", str(result.get("error") or result.get("status") or "unknown error")
    return str(result.get("response") or ""), ""


def _env_path() -> Path:
    if ENV_FILE is not None:
        return ENV_FILE
    return ROOT / ".env" if DATA == ROOT / "data" else DATA / ".env"


def _sync_dotenv() -> None:
    """Reload provider API keys from .env whenever the file changes on disk."""
    global _ENV_STATE
    path = _env_path()
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return
    if _ENV_STATE == (path, mtime):
        return
    key_envs = {p["api_key_env"] for p in cfg["providers"].values() if p.get("type") == "openai" and p.get("api_key_env")}
    if not key_envs:
        _ENV_STATE = (path, mtime)
        return
    found: dict[str, str] = {}
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                v = v[1:-1]
            if k in key_envs and v:
                found[k] = v
    except OSError:
        return
    for k, v in found.items():
        os.environ[k] = v
    _ENV_STATE = (path, mtime)


def is_installed(provider: str) -> bool:
    p = cfg["providers"].get(provider)
    if not p:
        return False
    if p["type"] == "cli":
        return bool(shutil.which(p["cmd"][0]))
    if p["type"] == "openai":
        _sync_dotenv()
        key_env = p.get("api_key_env")
        return not key_env or bool(os.environ.get(key_env))
    return False


def available() -> list[str]:
    return [name for name in cfg["providers"] if is_installed(name)]


def statuses() -> dict[str, dict]:
    path = DATA / "providers.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _record_status(provider: str, entry: dict) -> dict:
    with _PROVIDERS_LOCK:
        path = DATA / "providers.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = statuses()
        data[provider] = entry
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    return entry


def check(provider: str) -> dict:
    p = cfg["providers"][provider]
    now = dt.datetime.now().isoformat(timespec="seconds")
    if not is_installed(provider):
        msg = "not installed" if p["type"] == "cli" else f"missing {p['api_key_env']}"
        return _record_status(provider, {"ok": False, "at": now, "message": msg})
    prompt = p.get("check") or DEFAULT_CHECK
    try:
        reply = run(provider, prompt)
        if p.get("models_cmd"):
            _discover_models(provider)
        return _record_status(provider, {"ok": True, "at": now, "message": " ".join(reply.split())[:160]})
    except Exception as e:
        return _record_status(provider, {"ok": False, "at": now, "message": " ".join(str(e).split())[:300]})


def _discovered_models() -> dict[str, list[str]]:
    path = DATA / "discovered_models.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {k: [m for m in v if isinstance(m, str)] for k, v in data.items() if isinstance(v, list)} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _discover_models(provider: str) -> list[str]:
    p = cfg["providers"].get(provider) or {}
    cmd_cfg = p.get("models_cmd")
    if not cmd_cfg:
        return []
    exe = shutil.which(cmd_cfg[0])
    if not exe:
        return []
    try:
        res = subprocess.run([exe, *cmd_cfg[1:]], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=30,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if res.returncode != 0:
            return []
        models = []
        for raw in res.stdout.splitlines():
            if "\t" not in raw:
                continue
            slug = raw.split("\t", 1)[0].strip()
            if slug and " " not in slug and "orchestrator" not in slug.lower():
                models.append(slug)
        if not models:
            return []
        with _PROVIDERS_LOCK:
            path = DATA / "discovered_models.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            data = _discovered_models()
            data[provider] = models
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
        return models
    except Exception:
        return []


def available_models(provider: str) -> list[str]:
    p = cfg["providers"].get(provider) or {}
    static = list(p.get("models") or [])
    if cache_path := p.get("models_cache_file"):
        try:
            raw = json.loads(Path(cache_path).expanduser().read_text(encoding="utf-8"))
            cached = [m["slug"] for m in raw.get("models", [])
                      if isinstance(m, dict) and m.get("visibility") == "list" and isinstance(m.get("slug"), str)]
            if cached:
                return cached
        except (OSError, ValueError, TypeError):
            pass
    if p.get("models_cmd"):
        disc = _discovered_models().get(provider)
        if disc:
            return disc
    return static


def model_overrides() -> dict[str, str]:
    path = DATA / "provider_models.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def selected_model(provider: str) -> str | None:
    p = cfg["providers"].get(provider) or {}
    models = available_models(provider)
    saved = model_overrides().get(provider)
    if models and saved in models:
        return saved
    default = p.get("model")
    if models and default not in models:
        return models[0]
    return default


def set_model(provider: str, model: str) -> str:
    p = cfg["providers"].get(provider)
    if not p:
        raise ValueError("unknown provider")
    models = available_models(provider)
    if not models:
        raise ValueError("this provider does not support model selection")
    if not isinstance(model, str) or model not in models:
        raise ValueError("unknown model for provider")
    with _PROVIDERS_LOCK:
        path = DATA / "provider_models.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = model_overrides()
        data[provider] = model
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    return model


def set_api_key(provider: str, api_key: str) -> bool:
    global _ENV_STATE
    p = cfg["providers"].get(provider)
    if not p:
        raise ValueError("unknown provider")
    key_env = p.get("api_key_env") if p.get("type") == "openai" and p.get("dashboard_key") else None
    if not key_env:
        raise ValueError("API key for this provider cannot be edited from the dashboard")
    if not isinstance(api_key, str) or any(c in api_key for c in "\r\n"):
        raise ValueError("invalid API key")
    val = api_key.strip()
    if val:
        os.environ[key_env] = val
    else:
        os.environ.pop(key_env, None)
    with _PROVIDERS_LOCK:
        path = _env_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
        out, replaced = [], False
        for line in lines:
            stripped = line.lstrip()
            if not stripped.startswith("#") and "=" in stripped and stripped.split("=", 1)[0].strip() == key_env:
                if val and not replaced:
                    out.append(f"{key_env}={val}")
                    replaced = True
                continue
            out.append(line)
        if val and not replaced:
            out.append(f"{key_env}={val}")
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text("\n".join(out) + ("\n" if out else ""), encoding="utf-8")
        os.replace(tmp, path)
        _ENV_STATE = (path, path.stat().st_mtime_ns)
    if not val:
        now = dt.datetime.now().isoformat(timespec="seconds")
        _record_status(provider, {"ok": False, "at": now, "message": f"missing {key_env}"})
    return bool(val)


EFFORT_LEVELS = {"low", "medium", "high", "xhigh", "max"}


def _cli_cmd(exe: str, raw_args: list[str], out_file: Path, model: str | None,
             model_flag: str | None = None, effort: str | None = None,
             effort_args: list[str] | None = None) -> list[str]:
    cmd = [exe]
    has_placeholder = "{model}" in raw_args
    for arg in raw_args:
        if arg == "{model}":
            if model:
                cmd.append(model)
            elif len(cmd) > 1:
                cmd.pop()
        else:
            cmd.append(arg.replace("{out}", str(out_file)))
    if model and not has_placeholder and model_flag:
        if len(cmd) > 1 and cmd[-1] == "-":
            cmd[-1:-1] = [model_flag, model]
        else:
            cmd.extend([model_flag, model])
    if effort and effort_args:
        extra = [a.replace("{effort}", effort) for a in effort_args]
        if len(cmd) > 1 and cmd[-1] == "-":
            cmd[-1:-1] = extra
        else:
            cmd.extend(extra)
    return cmd


def run(provider: str, prompt: str, model: str | None = None, effort: str | None = None) -> str:
    p = cfg["providers"][provider]
    if model is not None:
        allowed = available_models(provider)
        if not allowed or model not in allowed:
            raise ValueError("unknown model for provider")
    if effort is not None and effort not in EFFORT_LEVELS:
        raise ValueError("unknown reasoning effort")
    chosen_model = model or selected_model(provider)
    if p["type"] == "openai":
        _sync_dotenv()
        key_env = p.get("api_key_env")
        headers = {"Authorization": f"Bearer {os.environ[key_env]}"} if key_env else None
        try:
            with httpx.Client(timeout=600, transport=HTTP_TRANSPORT) as client:
                r = client.post(
                    f"{p['base_url'].rstrip('/')}/chat/completions",
                    headers=headers,
                    json={"model": chosen_model or p["model"], "messages": [{"role": "user", "content": prompt}]},
                )
                r.raise_for_status()
            text = (r.json()["choices"][0]["message"]["content"] or "").strip()
            if not text:
                raise ProviderError(provider, "other", f"{provider} returned an empty response")
            return text
        except httpx.HTTPStatusError as e:
            detail = e.response.text or str(e)
            kind = classify(provider, e.response.status_code, detail)
            raise ProviderError(provider, kind, _format_error(provider, kind, e.response.status_code, detail),
                                exit_code=e.response.status_code) from e

    # CLI agents run in an empty folder with tools off / read-only (see the flags in config):
    # a transcript is other people's words and must not be able to steer an agent into acting.
    exe = shutil.which(p["cmd"][0])
    if not exe:
        raise ProviderError(provider, "other", f"{provider} CLI not found: {p['cmd'][0]}")
    stream_mode = p.get("format") == "agy-stream-json"
    stdin_text = json.dumps({"event": "user", "message": {"content": prompt}}) + "\n" if stream_mode else prompt
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        out_file, so, se = Path(tmp) / "out.txt", Path(tmp) / "stdout.txt", Path(tmp) / "stderr.txt"
        cmd = _cli_cmd(exe, p["cmd"][1:], out_file, chosen_model, p.get("model_flag"), effort, p.get("effort_args"))
        # Output goes to files, not pipes (precaution): if a CLI leaves a helper running, the
        # helper keeps the pipe open and reading it would outlast the timeout.
        with so.open("wb") as fo, se.open("wb") as fe:
            res = subprocess.run(cmd, input=stdin_text, stdout=fo, stderr=fe, text=True, encoding="utf-8",
                                 errors="replace", cwd=tmp, timeout=900,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                 env={**os.environ, "TEMP": tmp, "TMP": tmp, "TMPDIR": tmp})
        stdout, stderr = (f.read_text(encoding="utf-8", errors="replace") for f in (so, se))
        stream_err = ""
        if stream_mode:
            text, stream_err = _parse_agy_stream(stdout)
        else:
            text = out_file.read_text(encoding="utf-8") if out_file.exists() else stdout
        if res.returncode != 0 or stream_err or not text.strip():
            parts = [p.strip() for p in (stream_err, stderr, "" if stream_mode and stream_err else stdout) if p and p.strip()]
            combined = "\n".join(p[-2000:] for p in parts)
            detail = "\n".join(dict.fromkeys(parts))
            kind = classify(provider, res.returncode, combined)
            raise ProviderError(provider, kind, _format_error(provider, kind, res.returncode, detail),
                                exit_code=res.returncode)
        return text.strip()
