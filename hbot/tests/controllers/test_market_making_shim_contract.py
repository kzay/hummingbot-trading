from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MM_DIR = ROOT / "controllers" / "market_making"


def test_market_making_folder_contains_shim_only_modules() -> None:
    py_files = sorted(p for p in MM_DIR.glob("*.py") if p.name != "__init__.py")
    assert py_files, "controllers/market_making must contain shim modules for market_making loader resolution"

    for path in py_files:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        for node in ast.walk(tree):
            assert not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)), (
                f"{path.name} must not define strategy logic; keep only wrapper imports"
            )

        import_modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                import_modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                import_modules.append(node.module)

        assert import_modules, f"{path.name} must import a target controller module"
        invalid = sorted(m for m in import_modules if not m.startswith("controllers."))
        assert not invalid, f"{path.name} should only import from controllers.*; got {invalid}"
