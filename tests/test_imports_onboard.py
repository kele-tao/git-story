"""The real import parser and the onboarding ranking built on it."""

from __future__ import annotations

from gitstory.history import Commit, FileChange, History
from gitstory.imports import (
    build_import_graph,
    is_js,
    is_noise,
    js_imports,
    python_imports,
    resolve_js,
    resolve_python,
)
from gitstory.onboard import onboard


def test_python_imports_are_parsed_with_ast():
    source = "import os\nimport json\nfrom . import sibling\nfrom pkg.mod import thing\n"
    assert python_imports(source) == ["os", "json", "pkg.mod"]


def test_broken_python_yields_no_imports():
    assert python_imports("def broken(:\n") == []


def test_js_imports_only_follow_relative_specifiers():
    source = "import x from './a'\nimport y from 'lib'\nconst z = require('./b');\n"
    assert js_imports(source) == ["./a", "./b"]


def test_resolution_prefers_exact_module_path():
    index = {"pkg/core.py": "pkg/core.py"}
    assert resolve_python("pkg.core", index) == "pkg/core.py"


def test_resolution_understands_src_layout():
    index = {"src/pkg/core.py": "src/pkg/core.py"}
    assert resolve_python("pkg.core", index) == "src/pkg/core.py"


def test_resolution_handles_package_init():
    index = {"pkg/__init__.py": "pkg/__init__.py"}
    assert resolve_python("pkg", index) == "pkg/__init__.py"


def test_relative_and_absolute_edges_are_recorded():
    files = {
        "src/app.py": "from .util import helper\n",
        "src/util.py": "x = 1\n",
        "src/other.py": "import src.app\n",
    }
    graph = build_import_graph(files)
    assert graph.edges["src/app.py"] == {"src/util.py"}
    assert graph.edges["src/other.py"] == {"src/app.py"}


def test_in_degree_counts_importers():
    files = {
        "a.py": "import b\n",
        "c.py": "import b\n",
        "b.py": "x = 1\n",
    }
    graph = build_import_graph(files)
    assert graph.in_degree["b.py"] == 2
    assert graph.edge_count == 2
    assert graph.importers_of("b.py") == ["a.py", "c.py"]


def test_self_import_is_ignored():
    files = {"a.py": "import a\n"}
    assert build_import_graph(files).edges.get("a.py", set()) == set()


def test_js_resolution_appends_extensions():
    index = {"src/b.ts": "src/b.ts"}
    assert resolve_js("./b", "src/a.ts", index) == "src/b.ts"


def test_js_resolution_finds_index_files():
    index = {"src/widgets/index.tsx": "src/widgets/index.tsx"}
    assert resolve_js("./widgets", "src/a.tsx", index) == "src/widgets/index.tsx"


def test_unresolved_imports_are_counted_not_invented():
    graph = build_import_graph({"a.py": "import nothere\n"})
    assert graph.unresolved == 1
    assert graph.edge_count == 0


def test_suffix_helpers():
    assert is_js("a.jsx")
    assert not is_js("a.py")
    assert is_noise("tests/conftest.py")
    assert is_noise("node_modules/x/y.js")
    assert not is_noise("src/app.py")


class FakeRepo:
    name = "fake"

    def __init__(self, files):
        self.files = files
        self.root = None

    def run_text(self, *args, check=True):
        return "\n".join(self.files)

    def show_file(self, spec, limit=400_000):
        return self.files.get(spec.split(":", 1)[1])


def history_with(files: dict[str, str]) -> History:
    names = sorted(files)
    commits = []
    for i in range(6):
        touched = [names[i % len(names)]] if names else []
        commits.append(
            Commit(
                sha=f"{i:040d}",
                parents=("a",),
                author="Ada",
                email="a@x",
                timestamp=1_700_000_000 + i * 1000,
                subject="feat: change",
                body="",
                files=[FileChange(name, None, 10, 0) for name in touched],
            )
        )
    return History(FakeRepo(files), commits, [])


def test_onboard_ranks_shared_dependency_first():
    files = {
        "src/core.py": "x = 1\n",
        "src/a.py": "import src.core\n",
        "src/b.py": "import src.core\n",
        "src/cli.py": "import src.a\n",
    }
    entries = onboard(history_with(files), sources=files)
    assert entries[0].path == "src/core.py"
    assert entries[0].importers == 2
    assert entries[0].rank == 1


def test_onboard_excludes_tests_by_default():
    files = {
        "src/core.py": "x = 1\n",
        "src/a.py": "import src.core\n",
        "tests/test_core.py": "import src.core\n",
    }
    paths = [e.path for e in onboard(history_with(files), sources=files)]
    assert "tests/test_core.py" not in paths
    assert "src/core.py" in paths
    with_tests = [e.path for e in onboard(history_with(files), sources=files, include_tests=True)]
    assert "tests/test_core.py" in with_tests


def test_onboard_entries_carry_reasons():
    files = {"src/core.py": "x = 1\n", "src/a.py": "import src.core\n"}
    entry = onboard(history_with(files), sources=files)[0]
    assert entry.reasons
    assert any("imported by" in reason for reason in entry.reasons)
    assert entry.read_minutes >= 2


def test_onboard_on_empty_sources_returns_empty():
    assert onboard(history_with({}), sources={}) == []
