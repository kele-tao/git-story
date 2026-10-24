"""A real import parser, used to find the files that everything depends on.

Python is parsed with the stdlib *ast* module: no regex guessing. JavaScript
and TypeScript get a conservative ES-module / CommonJS regex because shipping
a JS parser is not worth a dependency. Anything else is ignored -- git-story
never invents edges it cannot see in the source.
"""

from __future__ import annotations

import ast
import posixpath
import re
from dataclasses import dataclass, field

PY_SUFFIX = ".py"
JS_SUFFIXES = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")

JS_ESM_RE = re.compile(r"""(?:^|\n)\s*import\s+(?:[^'"]*?\s+from\s+)?['"]([^'"]+)['"]""")
JS_REQUIRE_RE = re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)""")

# Files that add no architectural signal.
NOISE_NAMES = (
    "__init__.py",
    "setup.py",
    "conftest.py",
    "version.py",
    "_version.py",
    "conf.py",
)
NOISE_PARTS = ("node_modules/", "vendor/", "dist/", "build/", ".venv/", "venv/")


@dataclass
class ImportGraph:
    """Directed edges "this file imports that file", keyed by repo path."""

    edges: dict[str, set[str]] = field(default_factory=dict)
    unresolved: int = 0

    def add(self, src: str, dst: str) -> None:
        if src == dst:
            return
        self.edges.setdefault(src, set()).add(dst)

    @property
    def in_degree(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for targets in self.edges.values():
            for dst in targets:
                counts[dst] = counts.get(dst, 0) + 1
        return counts

    @property
    def edge_count(self) -> int:
        return sum(len(v) for v in self.edges.values())

    def importers_of(self, path: str) -> list[str]:
        return sorted(src for src, targets in self.edges.items() if path in targets)


def is_python(path: str) -> bool:
    return path.endswith(PY_SUFFIX)


def is_js(path: str) -> bool:
    return path.endswith(JS_SUFFIXES)


def is_noise(path: str) -> bool:
    base = posixpath.basename(path)
    if base in NOISE_NAMES:
        return True
    lowered = "/" + path.lower() + "/"
    return any(part in lowered for part in NOISE_PARTS)


def python_imports(source: str) -> list[str]:
    """Return the module names a Python source file imports (absolute form)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue  # relative imports need the file's package; resolved by caller
            if node.module:
                names.append(node.module)
    return names


def js_imports(source: str) -> list[str]:
    found = JS_ESM_RE.findall(source) + JS_REQUIRE_RE.findall(source)
    return [spec for spec in found if spec.startswith(".")]


def module_candidates(module: str) -> list[str]:
    """Possible repo paths for an absolute Python module name."""
    parts = module.split(".")
    joined = "/".join(parts)
    return [joined + ".py", joined + "/__init__.py"]


def resolve_python(module: str, index: dict[str, str]) -> str | None:
    for candidate in module_candidates(module):
        if candidate in index:
            return index[candidate]
    # src-layout repositories: strip a leading package directory.
    for candidate in module_candidates(module):
        for root in index:
            if root.endswith("/" + candidate):
                return index[root]
    return None


def resolve_js(spec: str, src: str, index: dict[str, str]) -> str | None:
    base = posixpath.normpath(posixpath.join(posixpath.dirname(src), spec))
    for ext in ("", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
        candidate = base + ext
        if candidate in index:
            return index[candidate]
        for suffix in ("/index.ts", "/index.tsx", "/index.js", "/index.jsx"):
            if candidate + suffix in index:
                return index[candidate + suffix]
    return None


def build_import_graph(files: dict[str, str], limit: int = 200_000) -> ImportGraph:
    """Build the import graph from a mapping of repo path -> source text."""
    graph = ImportGraph()
    index = {path: path for path in files}
    for path, source in files.items():
        if len(source) > limit:
            continue
        if is_python(path):
            for module in python_imports(source):
                target = resolve_python(module, index)
                if target is None:
                    graph.unresolved += 1
                else:
                    graph.add(path, target)
            # Relative imports: from . import x / from .mod import y
            try:
                tree = ast.parse(source)
            except (SyntaxError, ValueError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level:
                    base_dir = posixpath.dirname(path)
                    for _ in range(node.level - 1):
                        base_dir = posixpath.dirname(base_dir)
                    if node.module:
                        module_path = node.module.replace(".", "/")
                        stem = base_dir + "/" + module_path if base_dir else module_path
                        for candidate in (stem + ".py", stem + "/__init__.py"):
                            if candidate in index:
                                graph.add(path, index[candidate])
                                break
                    for alias in node.names:
                        stem = (base_dir + "/" if base_dir else "") + alias.name + ".py"
                        if stem in index:
                            graph.add(path, index[stem])
        elif is_js(path):
            for spec in js_imports(source):
                target = resolve_js(spec, path, index)
                if target is None:
                    graph.unresolved += 1
                else:
                    graph.add(path, target)
    return graph
