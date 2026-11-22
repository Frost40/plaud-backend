import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def app_sources():
    return [p for p in (ROOT / "app").rglob("*") if p.is_file() and "__pycache__" not in p.parts]


def test_no_forbidden_dependencies():
    for path in [ROOT / "requirements.txt", *app_sources()]:
        assert not re.search(rb"docker|riffado|supabase", path.read_bytes(), re.I), str(path)


def test_plaud_only_through_cli():
    for path in app_sources():
        assert b"plaud.ai" not in path.read_bytes().lower(), str(path)
        if path.suffix != ".py" or path.name == "plaud.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assignments = {target.id: node.value for node in ast.walk(tree) if isinstance(node, ast.Assign)
                       for target in node.targets if isinstance(target, ast.Name)}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if name not in {"run", "Popen", "call", "check_call", "check_output", "system", "popen", "which"}:
                continue
            command = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg in {"args", "command"}), None)
            seen = set()
            while isinstance(command, ast.Name) and command.id not in seen:
                seen.add(command.id)
                command = assignments.get(command.id)
            if isinstance(command, (ast.List, ast.Tuple)):
                command = command.elts[0] if command.elts else None
            if isinstance(command, ast.Constant) and isinstance(command.value, str):
                assert not re.match(r"^(?:.*[/\\])?plaud(?:\.(?:exe|cmd))?(?:\s|$)",
                                    command.value, re.I), (str(path), node.lineno)
