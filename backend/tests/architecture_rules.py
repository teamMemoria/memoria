"""Static dependency guard used by tests; resolves imports without importing code."""

import ast
from importlib.util import resolve_name

IO_MODULES = (
    "pathlib",
    "os",
    "io",
    "time",
    "subprocess",
    "socket",
    "httpx",
    "requests",
    "urllib.request",
    "shutil",
    "tempfile",
    "sqlite3",
    "asyncio",
)
OUTER_MODULES = (
    "sqlalchemy",
    "fastapi",
    "pydantic",
    "backend.models",
    "backend.schemas",
    "backend.providers",
    "backend.services",
    "backend.frameworks",
    "backend.interface_adapters",
    "backend.db",
    "backend.core",
    "backend.data",
)


def violations(source, module, *, layer="core"):
    """Reject forbidden imports and file/clock calls, including common aliases."""
    tree = ast.parse(source)
    package = module.rpartition(".")[0]
    forbidden = IO_MODULES + (
        OUTER_MODULES + ("ml",) if layer != "ml" else ("backend",)
    )
    if ".entities." in module:
        forbidden += ("backend.use_cases",)
    aliases = {}
    errors = []

    def blocked(name):
        return any(
            name == prefix or name.startswith(prefix + ".") for prefix in forbidden
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for value in node.names:
                aliases[value.asname or value.name.split(".")[0]] = (
                    value.name if value.asname else value.name.split(".")[0]
                )
                if blocked(value.name):
                    errors.append("import " + value.name)
        elif isinstance(node, ast.ImportFrom):
            name = (
                resolve_name("." * node.level + (node.module or ""), package)
                if node.level
                else node.module or ""
            )
            for value in node.names:
                path = name + "." + value.name
                aliases[value.asname or value.name] = path
                if blocked(name) or blocked(path):
                    errors.append("import " + path)

    def path(node):
        if isinstance(node, ast.Name):
            return aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            return path(node.value) + "." + node.attr
        return ""

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = path(node.func)
        if name in {
            "open",
            "builtins.open",
            "eval",
            "exec",
            "builtins.eval",
            "builtins.exec",
        }:
            errors.append("call " + name)
        if name.startswith("datetime.") and name.rsplit(".", 1)[-1] in {
            "now",
            "utcnow",
            "today",
            "fromtimestamp",
            "utcfromtimestamp",
        }:
            errors.append("clock " + name)
        if name in {"__import__", "builtins.__import__", "importlib.import_module"}:
            # Dynamic imports belong at execution edges; no string/path escape hatch.
            errors.append("dynamic import")
        root = node.func
        while isinstance(root, ast.Attribute):
            root = root.value
        if isinstance(root, ast.Name) and root.id in aliases and blocked(name):
            errors.append("call " + name)
    return errors
