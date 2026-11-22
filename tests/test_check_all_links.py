"""Tests for tools/check_all_links.py — the repository-wide link gate.

The gate exists because six implementations now sit side by side and each one's own checker only
walks its own directory. These tests pin the behaviours that make it trustworthy: it must catch a
missing file and a missing anchor, and it must not cry wolf on anchors a page builds at runtime.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import check_all_links


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def page(title="Page", body="") -> str:
    return (
        "<!doctype html><html><head><title>" + title + "</title></head>"
        '<body><main id="main">' + body + "</main></body></html>"
    )


def run(root: Path) -> int:
    return check_all_links.main([], root=root)


def test_clean_tree_passes(tmp_path):
    write(tmp_path, "index.html", page(body='<a href="about.html">About</a>'))
    write(tmp_path, "about.html", page())
    assert run(tmp_path) == 0


def test_missing_target_fails(tmp_path, capsys):
    write(tmp_path, "index.html", page(body='<a href="gone.html">Gone</a>'))
    assert run(tmp_path) == 1
    assert "missing gone.html" in capsys.readouterr().err


def test_missing_anchor_fails(tmp_path, capsys):
    write(tmp_path, "index.html", page(body='<a href="about.html#nope">Jump</a>'))
    write(tmp_path, "about.html", page(body='<h2 id="real">Real</h2>'))
    assert run(tmp_path) == 1
    assert "no element #nope" in capsys.readouterr().err


def test_existing_anchor_passes(tmp_path):
    write(tmp_path, "index.html", page(body='<a href="about.html#real">Jump</a>'))
    write(tmp_path, "about.html", page(body='<h2 id="real">Real</h2>'))
    assert run(tmp_path) == 0


def test_directory_link_resolves_to_index(tmp_path):
    write(tmp_path, "index.html", page(body='<a href="docs/">Docs</a>'))
    write(tmp_path, "docs/index.html", page())
    assert run(tmp_path) == 0


def test_published_site_prefix_is_stripped(tmp_path):
    write(tmp_path, "index.html", page(body='<a href="/Tradebot1/docs/">Docs</a>'))
    write(tmp_path, "docs/index.html", page())
    assert run(tmp_path) == 0


def test_relative_traversal_escaping_the_repository_fails(tmp_path, capsys):
    write(tmp_path, "index.html", page(body='<a href="../../etc/passwd">Escape</a>'))
    assert run(tmp_path) == 1
    assert "escapes the repository" in capsys.readouterr().err


def test_site_absolute_path_is_treated_as_a_missing_file_not_an_escape(tmp_path, capsys):
    """/Tradebot1/... is how the published site addresses its own pages, so a bare /etc/passwd
    means "the site has no etc/passwd page", not "someone is linking off the server"."""
    write(tmp_path, "index.html", page(body='<a href="/etc/passwd">Escape</a>'))
    assert run(tmp_path) == 1
    assert "missing etc/passwd" in capsys.readouterr().err


def test_runtime_anchor_from_a_data_file_is_accepted(tmp_path):
    """A page that renders rows from data/*.json uses the record id as the anchor."""
    write(tmp_path, "index.html", page(body='<a href="flagged.html#F-06">F-06</a>'))
    write(tmp_path, "flagged.html", page(body='<section id="flags"></section>'
                                          '<script src="assets/flagged.js"></script>'))
    write(tmp_path, "assets/flagged.js", "const data = await loadLocal('data/flags.json');")
    write(tmp_path, "data/flags.json", json.dumps({"flags": [{"id": "F-06", "title": "A flag"}]}))
    assert run(tmp_path) == 0


def test_runtime_anchor_still_fails_when_the_id_is_not_in_the_data(tmp_path, capsys):
    write(tmp_path, "index.html", page(body='<a href="flagged.html#F-99">F-99</a>'))
    write(tmp_path, "flagged.html", page(body='<section id="flags"></section>'
                                          '<script src="assets/flagged.js"></script>'))
    write(tmp_path, "assets/flagged.js", "const data = await loadLocal('data/flags.json');")
    write(tmp_path, "data/flags.json", json.dumps({"flags": [{"id": "F-06"}]}))
    assert run(tmp_path) == 1
    assert "no element #F-99" in capsys.readouterr().err


def test_build_output_and_dependencies_are_not_walked(tmp_path):
    write(tmp_path, "public/index.html", page(body='<a href="missing.html">Nope</a>'))
    write(tmp_path, "index.html", page())
    assert run(tmp_path) == 0, "generated output must not be gated as if it were source"


def test_server_rendered_uis_are_not_walked(tmp_path):
    """app/static/ and live/static/ are served by their own servers, not by GitHub Pages."""
    write(tmp_path, "live/static/index.html", page(body='<a href="qa.html">Audit</a>'))
    write(tmp_path, "app/static/index.html", page(body='<a href="/api/state">State</a>'))
    write(tmp_path, "index.html", page())
    assert run(tmp_path) == 0


def test_the_repository_itself_is_clean():
    """The real gate. If this fails, a page in the repository has a broken internal link."""
    assert check_all_links.main([], root=Path(__file__).resolve().parent.parent) == 0


def test_the_repository_gate_covers_every_implementation():
    root = Path(__file__).resolve().parent.parent
    pages = {str(path.relative_to(root)) for path in check_all_links.html_pages()}
    for expected in (
        "index.html",
        "docs/desk/index.html",
        "docs/index.html",
        "site/index.html",
        "docs/engine/index.html",
    ):
        assert expected in pages, f"{expected} is not covered by the repository-wide gate"
