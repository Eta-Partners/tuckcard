"""Promotion: renumbering, reference rewrite, quarantine and the index."""

import io

import support
import promote
import verify_citations


# A rule file as a person leaves one: a header comment, an inline comment, a
# quoted description and explicit `null`s. Promotion re-renders every rule file
# it reads, so these are the things a rewrite must not quietly drop.
HAND_EDITED = """\
# Header note: this file is edited by hand.
scope: {scope}   # the band this file serves
status: active
description: 'Quoted description, kept as written.'
rules:
  - id: {rule_id}
    type: avoid
    strength: should
    applies_to:
      - title
      - lines
      - notes
    when: null
    overrides: []
    text: Keep the lines specific and doable.
    why: Specific, doable lines are easier to act on.
    cites:
      - F-0001
    check: judge
    lint: null
    examples: null
"""


def tree(tmp_path):
    knowledge = support.base_knowledge(tmp_path / "knowledge")
    gaps = knowledge / "gaps"
    gaps.mkdir()
    (gaps / "academics.md").write_text(
        "# Gaps: academics\n\n"
        "## G-academics-01\n\n"
        "- **Question:** Does L-0001 hold during exam weeks?\n"
        "- **Searches tried:** one database search\n"
        "- **What turned up:** R-academics-L001 still needs a check.\n"
        "- **Date:** 2026-11-10\n"
        "- **Next idea:** re-read L-0001.\n",
        encoding="utf-8",
    )
    source = tmp_path / "source"
    support.write_finding(
        source / "findings",
        support.finding(
            "L-0001",
            source={
                "doi": "10.1234/example.valid",
                "title": "A small start helps",
                "year": 2020,
                "first_author": "Rivera",
            },
        ),
    )
    support.write_finding(
        source / "findings",
        support.finding(
            "L-0002",
            source={"doi": "10.1016/S0140-6736(97)11096-0"},
        ),
    )
    support.write_rule_file(
        source / "rules/academics.yaml",
        "context/academics",
        [
            support.rule(
                "R-academics-L001",
                "avoid",
                cites=("L-0001",),
                overrides=["R-core-001"],
                text="Keep the line usable in L-0001's setting.",
            )
        ],
    )
    return knowledge, source


def test_promotion_renumbers_rewrites_and_moves(tmp_path, capsys):
    knowledge, source = tree(tmp_path)
    code = promote.main(
        [
            "--source",
            str(source),
            "--knowledge",
            str(knowledge),
            "--responses",
            str(support.RESPONSES),
            "--today",
            "2026-11-11",
        ]
    )
    assert code == 0, capsys.readouterr().out

    passed = knowledge / "findings/F-0004.md"
    data, _ = support.files.read_frontmatter(passed)
    assert data["id"] == "F-0004"
    assert data["status"] == "active"
    assert data["verification"]["checked_on"] == "2026-11-11"
    assert data["verification"]["metadata_match"] == [
        "title",
        "year",
        "first_author",
    ]

    failed = knowledge / "quarantine/F-0005.md"
    data, _ = support.files.read_frontmatter(failed)
    assert data["id"] == "F-0005"
    assert data["status"] == "quarantined"
    assert "retracted" in data["quarantine_reason"]

    # Nothing was deleted: the overlay copies are still where they were.
    assert (source / "findings/L-0001.md").is_file()
    assert (source / "findings/L-0002.md").is_file()

    rule_file = support.files.load_yaml(knowledge / "rules/context/academics.yaml")
    promoted_rule = rule_file["rules"][0]
    assert promoted_rule["id"] == "R-academics-001"
    assert promoted_rule["cites"] == ["F-0004"]
    assert promoted_rule["overrides"] == ["R-core-001"]
    assert "F-0004's setting" in promoted_rule["text"]

    gap = (knowledge / "gaps/academics.md").read_text(encoding="utf-8")
    assert "L-0001" not in gap
    assert "R-academics-L001" not in gap
    assert "F-0004" in gap
    assert "R-academics-001" in gap

    index = support.files.load_yaml(knowledge / "findings/index.yaml")
    assert [entry["id"] for entry in index["findings"]] == [
        "F-0001",
        "F-0002",
        "F-0003",
        "F-0004",
    ]
    out = capsys.readouterr().out
    assert "overlay files were left in place" in out


def promote_main(source, knowledge):
    return promote.main(
        [
            "--source",
            str(source),
            "--knowledge",
            str(knowledge),
            "--responses",
            str(support.RESPONSES),
            "--today",
            "2026-11-11",
        ]
    )


def sparse_knowledge(tmp_path):
    """A pool holding F-0001 and F-0003, so the next free id is a hole."""
    knowledge = support.base_knowledge(tmp_path / "knowledge")
    (knowledge / "findings/F-0002.md").unlink()
    support.write_finding(
        knowledge / "findings",
        support.finding(
            "F-0003", grade="B", source={"doi": "10.1234/example.shipped3"}
        ),
    )
    support.write_rule_file(
        knowledge / "rules/core.yaml",
        "core",
        [support.rule("R-core-001", "avoid", cites=("F-0001",))],
    )
    return knowledge


def two_findings(tmp_path):
    source = tmp_path / "source"
    support.write_finding(
        source / "findings",
        support.finding("L-0001", source={"doi": "10.1234/example.valid"}),
    )
    support.write_finding(
        source / "findings",
        support.finding("L-0002", source={"doi": "10.1234/example.fake"}),
    )
    return source


def test_promotion_never_lands_on_an_existing_id(tmp_path, capsys):
    knowledge = sparse_knowledge(tmp_path)
    source = two_findings(tmp_path)
    assert promote_main(source, knowledge) == 0, capsys.readouterr().out

    kept, _ = support.files.read_frontmatter(knowledge / "findings/F-0003.md")
    assert kept["source"]["doi"] == "10.1234/example.shipped3"

    shipped, _ = support.files.read_frontmatter(knowledge / "findings/F-0002.md")
    assert shipped["id"] == "F-0002"
    assert shipped["source"]["doi"] == "10.1234/example.valid"
    quarantined, _ = support.files.read_frontmatter(knowledge / "quarantine/F-0004.md")
    assert quarantined["id"] == "F-0004"
    assert quarantined["status"] == "quarantined"


def test_promotion_refuses_a_doi_already_in_the_pool(tmp_path, capsys):
    knowledge = support.base_knowledge(tmp_path / "knowledge")
    source = tmp_path / "source"
    support.write_finding(
        source / "findings",
        support.finding("L-0001", source={"doi": "10.1234/example.shipped"}),
    )
    assert promote_main(source, knowledge) == 1
    out = capsys.readouterr().out
    assert "10.1234/example.shipped" in out
    assert "already held by F-0001" in out
    assert not (knowledge / "findings/F-0004.md").exists()
    assert (source / "findings/L-0001.md").is_file()


def test_promotion_refuses_a_doi_already_in_quarantine(tmp_path, capsys):
    knowledge = support.base_knowledge(tmp_path / "knowledge")
    support.write_finding(
        knowledge / "quarantine",
        support.finding(
            "F-0007",
            status="quarantined",
            quarantine_reason="source is retracted",
            source={"doi": "10.1234/example.valid"},
        ),
    )
    source = tmp_path / "source"
    support.write_finding(
        source / "findings",
        support.finding("L-0001", source={"doi": "10.1234/example.valid"}),
    )
    assert promote_main(source, knowledge) == 1
    out = capsys.readouterr().out
    assert "already held by F-0007" in out


def test_a_promotion_that_could_not_check_writes_nothing(tmp_path, capsys, monkeypatch):
    """A check that did not complete is not a reason to quarantine a finding.

    The source is neither shipped nor quarantined: the whole promotion stops
    and says which URL it could not answer for.
    """
    monkeypatch.setattr(verify_citations, "_wait", lambda seconds: None)
    knowledge = support.base_knowledge(tmp_path / "knowledge")
    source = tmp_path / "source"
    support.write_finding(
        source / "findings",
        support.finding("L-0001", source={"doi": "10.1234/example.unrecorded"}),
    )
    before = {
        path: path.read_bytes()
        for path in sorted(knowledge.rglob("*"))
        if path.is_file()
    }
    responses = tmp_path / "incomplete.json"
    responses.write_text("{}", encoding="utf-8")

    code = promote.main(
        [
            "--source",
            str(source),
            "--knowledge",
            str(knowledge),
            "--responses",
            str(responses),
            "--today",
            "2026-11-11",
        ]
    )

    assert code == 1
    after = {
        path: path.read_bytes()
        for path in sorted(knowledge.rglob("*"))
        if path.is_file()
    }
    assert after == before
    out = capsys.readouterr().out
    assert "could not check, nothing was promoted" in out
    assert "https://api.crossref.org/works/10.1234%2Fexample.unrecorded" in out


def test_promotion_moves_a_fetch_verified_finding_to_active(tmp_path, capsys):
    knowledge = support.base_knowledge(tmp_path / "knowledge")
    source = tmp_path / "source"
    support.write_finding(
        source / "findings",
        support.finding(
            "L-0001",
            source={"doi": "10.1234/example.valid"},
            verification={"exists": "fetch"},
            status="provisional",
        ),
    )
    assert promote_main(source, knowledge) == 0, capsys.readouterr().out

    data, _ = support.files.read_frontmatter(knowledge / "findings/F-0004.md")
    assert data["status"] == "active"
    assert data["verification"]["exists"] == "script"


def test_promotion_leaves_an_untouched_rule_file_byte_identical(tmp_path, capsys):
    """A rule file the promotion does not add to comes out as it went in."""
    knowledge, source = tree(tmp_path)
    history = knowledge / "rules/context/history.yaml"
    text = HAND_EDITED.format(scope="context/history", rule_id="R-history-001")
    history.parent.mkdir(parents=True, exist_ok=True)
    history.write_text(text, encoding="utf-8")

    assert promote_main(source, knowledge) == 0, capsys.readouterr().out

    assert history.read_text(encoding="utf-8") == text


def test_promotion_keeps_comments_quotes_and_nulls_it_did_not_touch(
    tmp_path, capsys
):
    """A rule appended to a hand-edited file leaves that file's own prose alone."""
    knowledge, source = tree(tmp_path)
    academics = knowledge / "rules/context/academics.yaml"
    academics.parent.mkdir(parents=True, exist_ok=True)
    academics.write_text(
        HAND_EDITED.format(scope="context/academics", rule_id="R-academics-001"),
        encoding="utf-8",
    )

    assert promote_main(source, knowledge) == 0, capsys.readouterr().out

    after = academics.read_text(encoding="utf-8")
    assert after.startswith("# Header note: this file is edited by hand.\n")
    assert "scope: context/academics   # the band this file serves" in after
    assert "description: 'Quoted description, kept as written.'" in after
    assert "    when: null\n" in after
    assert "    lint: null\n" in after
    # The promoted rule did land, so the write happened and kept the rest.
    assert "R-academics-002" in after



def test_a_rule_write_does_not_change_how_other_files_spell_null():
    """The null representer belongs to one writer, not to the whole process.

    ruamel's `add_representer` is a class method, so a rule writer that installs
    it there changes every later write in the same run: a finding written after
    a promote would gain `key: null` where it had `key:`, which is the reformat
    churn this work exists to remove. Write order is not something a caller
    should have to know, so the property is order independence.
    """
    support.files.rule_yaml()
    plain = io.StringIO()
    support.files.yaml_out().dump({"a": None}, plain)
    assert plain.getvalue().strip() == "a:"
    rules = io.StringIO()
    support.files.rule_yaml().dump({"a": None}, rules)
    assert rules.getvalue().strip() == "a: null"
