"""CLI behaviour: exit codes, every documented flag, error messages."""

from __future__ import annotations

import json

import pytest

from conftest import git
from gitstory.cli import main


def run(capsys, *argv):
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0


def test_no_command_is_a_usage_error(capsys):
    code, out, _err = run(capsys)
    assert code == 2
    assert "usage:" in out


def test_summary_prints_headline(small_history, capsys):
    code, out, err = run(capsys, "summary", str(small_history.repo.root), "--color", "never")
    assert code == 0
    assert err == ""
    assert "commits" in out
    assert "Findings" in out


def test_chronicle_groups_by_month(small_history, capsys):
    code, out, _ = run(capsys, "chronicle", str(small_history.repo.root), "--color", "never")
    assert code == 0
    assert "commits" in out
    assert "Feature" in out


def test_chronicle_respects_per_month(small_history, capsys):
    _code, out, _ = run(capsys, "chronicle", str(small_history.repo.root),
                        "--color", "never", "--per-month", "1")
    assert "more" in out or out.count("feat") <= 2


def test_chronicle_with_merges(repo, capsys):
    repo.write("a.py", "x = 1\n")
    repo.commit("feat: base")
    git(repo.root, "checkout", "-b", "topic")
    repo.write("a.py", "x = 2\n")
    repo.commit("feat: topic")
    git(repo.root, "checkout", "main")
    repo.write("b.py", "y = 1\n")
    repo.commit("feat: main")
    git(repo.root, "merge", "--no-ff", "topic", "-m", "Merge branch 'topic'")
    _code, out, _ = run(capsys, "chronicle", str(repo.root), "--color", "never", "--with-merges")
    assert "Merge branch" in out


def test_bus_factor_reports_directories(small_history, capsys):
    code, out, _ = run(capsys, "bus-factor", str(small_history.repo.root), "--color", "never")
    assert code == 0
    assert "Bus factor" in out
    assert "src" in out


def test_bus_factor_threshold_flag(small_history, capsys):
    code, out, _ = run(capsys, "bus-factor", str(small_history.repo.root),
                       "--color", "never", "--threshold", "0.9")
    assert code == 0
    assert "bus" in out


def test_hotspots_lists_files(small_history, capsys):
    code, out, _ = run(capsys, "hotspots", str(small_history.repo.root), "--color", "never")
    assert code == 0
    assert "Hotspots" in out


def test_coupling_runs(small_history, capsys):
    code, out, _ = run(capsys, "coupling", str(small_history.repo.root),
                       "--color", "never", "--min-together", "2")
    assert code == 0
    assert "coupling" in out.lower()


def test_onboard_ranks_files(small_history, capsys):
    code, out, _ = run(capsys, "onboard", str(small_history.repo.root), "--color", "never")
    assert code == 0
    assert "Read these first" in out


def test_refactor_table(small_history, capsys):
    code, out, _ = run(capsys, "refactor", str(small_history.repo.root), "--color", "never")
    assert code == 0
    assert "Refactor vs feature" in out


def test_json_output_is_valid(small_history, capsys):
    code, out, _ = run(capsys, "bus-factor", str(small_history.repo.root), "--json")
    assert code == 0
    payload = json.loads(out)
    assert payload["repo"] == "sample"
    assert payload["commits"] == 4
    assert isinstance(payload["directories"], list)


def test_json_and_text_agree_on_commit_count(small_history, capsys):
    _c, out, _ = run(capsys, "summary", str(small_history.repo.root), "--json")
    payload = json.loads(out)
    assert payload["commits"] == len(small_history)
    assert payload["themes"]["feature"] >= 1


def test_story_writes_html(small_history, tmp_path, capsys):
    target = tmp_path / "story.html"
    code, _out, err = run(
        capsys, "story", str(small_history.repo.root), "--format", "html",
        "--out", str(target), "--title", "My story",
    )
    assert code == 0
    html = target.read_text(encoding="utf-8")
    assert "<!doctype html>" in html
    assert "My story" in html
    assert "<svg" in html
    assert "wrote" in err


def test_story_html_stdout_when_no_out(small_history, capsys):
    code, out, _ = run(capsys, "story", str(small_history.repo.root), "--format", "html")
    assert code == 0
    assert out.startswith("<!doctype html>")


def test_story_text_and_json_formats(small_history, capsys):
    code, out, _ = run(capsys, "story", str(small_history.repo.root))
    assert code == 0 and "Findings" in out
    code, out, _ = run(capsys, "story", str(small_history.repo.root), "--format", "json")
    assert code == 0 and json.loads(out)["repo"] == "sample"


def test_since_filters_commits(small_history, capsys):
    _code, out, _ = run(capsys, "summary", str(small_history.repo.root), "--json",
                        "--since", "2023-01-01")
    assert json.loads(out)["commits"] == 4
    code, _out, err = run(capsys, "summary", str(small_history.repo.root), "--json",
                           "--since", "2999-01-01")
    assert code == 2
    assert "no commits" in err


def test_no_merges_flag(small_history, capsys):
    code, out, _ = run(capsys, "summary", str(small_history.repo.root), "--json", "--no-merges")
    assert code == 0
    assert json.loads(out)["commits"] == 4


def test_max_commits_flag(repo, capsys):
    for i in range(5):
        repo.write("a.py", f"x = {i}\n")
        repo.commit(f"feat: change {i}")
    _code, out, _ = run(capsys, "summary", str(repo.root), "--json", "--max-commits", "2")
    assert json.loads(out)["commits"] == 2


def test_quality_gate_passes_when_no_signal(small_history, capsys):
    code, _out, _err = run(capsys, "summary", str(small_history.repo.root),
                           "--fail-on", "unreviewed")
    assert code == 0


def test_quality_gate_fails_on_unreviewed_merge(repo, capsys):
    repo.write("a.py", "x = 1\n")
    repo.commit("feat: base")
    git(repo.root, "checkout", "-b", "topic")
    repo.write("a.py", "x = 2\n")
    repo.commit("feat: topic")
    git(repo.root, "checkout", "main")
    repo.write("b.py", "y = 1\n")
    repo.commit("feat: main")
    git(repo.root, "merge", "--no-ff", "topic", "-m", "Merge branch 'topic'")
    code, _out, err = run(capsys, "summary", str(repo.root), "--fail-on", "unreviewed")
    assert code == 1
    assert "quality gate failed" in err


def test_quality_gate_fails_on_bus_factor(repo, capsys):
    for i in range(6):
        repo.write(f"lib/f{i}.py", "x = 1\n")
        repo.commit(f"feat: file {i}", author="Solo")
    code, _out, err = run(capsys, "bus-factor", str(repo.root), "--fail-on", "bus-factor")
    assert code == 1
    assert "bus factor 1" in err


def test_quality_gate_fails_on_hotspot(repo, capsys):
    body = "\n".join("if x: y" for _ in range(120))
    for i in range(6):
        repo.write("hot.py", body + f"\n# {i}\n")
        repo.commit(f"feat: grow the hot file {i}", author="Solo")
    code, _out, err = run(capsys, "hotspots", str(repo.root), "--fail-on", "hotspot")
    assert code == 1
    assert "danger hotspots" in err


def test_path_via_dash_c(small_history, capsys):
    code, out, _ = run(capsys, "-C", str(small_history.repo.root), "summary", "--json")
    assert code == 0
    assert json.loads(out)["repo"] == "sample"


def test_global_options_after_subcommand(small_history, capsys):
    code, out, _ = run(capsys, "summary", str(small_history.repo.root), "--json",
                       "--color", "never")
    assert code == 0
    assert json.loads(out)["commits"] == 4


def test_missing_repository_is_a_friendly_error(tmp_path, capsys):
    empty = tmp_path / "plain"
    empty.mkdir()
    code, _out, err = run(capsys, "summary", str(empty))
    assert code == 2
    assert "not a git repository" in err
    assert "Traceback" not in err


def test_unknown_flag_is_a_usage_error(small_history):
    with pytest.raises(SystemExit) as exc:
        main(["summary", str(small_history.repo.root), "--nope"])
    assert exc.value.code == 2


def test_bad_since_is_a_friendly_error(small_history, capsys):
    code, _out, err = run(capsys, "summary", str(small_history.repo.root), "--since", "yesterday")
    assert code == 2
    assert "cannot parse --since" in err
    assert "Traceback" not in err


def test_color_always_emits_ansi(small_history, capsys):
    _code, out, _ = run(capsys, "bus-factor", str(small_history.repo.root), "--color", "always")
    assert "\x1b[" in out
