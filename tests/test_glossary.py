from pathlib import Path

import pytest
from huggingface_hub.constants import HF_HUB_CACHE
from tokenizers import Tokenizer

from app import glossary as g, pipeline, vault


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "BASE", tmp_path)
    vault.seed()
    return "Inbox"


def test_parse_and_strip_glossary_block(folder, monkeypatch):
    r = vault.new_recording(dict(title="Test", id="one", duration="1m", date="2026-11-17"))
    answer = "## Core theme ## Tasks ## Ideas\n```mermaid\nmindmap\n```\n```glossary\n- CGH\n```"
    def run(provider, prompt):
        assert prompt.rstrip().endswith(g.INSTRUCTION)
        return answer
    monkeypatch.setattr(pipeline.llm, "run", run)
    name = pipeline.generate(r["id"], "Voice memo", "claude", lambda _: None)
    body = (r["_dir"] / (name + ".md")).read_text(encoding="utf-8")
    assert "```mermaid" in body and "```glossary" not in body
    g.add_candidates(folder, ["CGH"], "two", "note")
    assert g.active(folder) == ["CGH"]


def test_promotion_needs_two_recordings(folder):
    for _ in range(2):
        g.add_candidates(folder, ["CGH"], "a", "note")
    assert g.active(folder) == []
    g.add_candidates(folder, ["cgh"], "b", "ensemble")
    assert g.active(folder) == ["CGH"]
    (vault.BASE / "Other").mkdir()
    g.add_candidates("Other", ["CGH"], "c", "correction")
    assert g.active("Third") == ["CGH"]


def test_terms_follow_a_moved_recording(folder):
    a = vault.new_recording(dict(title="A", id="a", duration="1m", date="2026-11-17"))
    vault.new_recording(dict(title="B", id="b", duration="1m", date="2026-11-18"))
    g.add_candidates(folder, ["Alice", "CGH"], "a", "name")
    g.add_candidates(folder, ["CGH", "Bob"], "b", "note")
    (vault.BASE / "TESI").mkdir()
    g.add_candidates("TESI", [], "", "")
    g.act("TESI", "block", "Bob", "a")                       # rejected in the destination
    vault.move(a["id"], "TESI")
    assert set(g.active("TESI")) == {"Alice", "CGH"}
    inbox = g._read(vault.BASE / folder / "Glossary.md")[4]
    assert set(inbox) == {"cgh", "bob"} and inbox["cgh"]["ids"] == ["b"]
    g.relocate()                                              # idempotent
    assert set(g.active("TESI")) == {"Alice", "CGH"}


def test_names_and_corrections_active_at_once(folder):
    g.add_candidates(folder, ["Alice"], "a", "name")
    g.add_candidates(folder, ["Prism"], "a", "correction")
    assert g.active(folder) == ["Alice", "Prism"]


def test_rejected_term_never_returns(folder):
    g.add_candidates(folder, ["Alice", "Bob"], "a", "name")
    path = vault.BASE / folder / "Glossary.md"
    content = "\n".join(s for s in path.read_text(encoding="utf-8").splitlines() if " recordings · " not in s)
    moved = next(s for s in path.read_text(encoding="utf-8").splitlines() if s.startswith("- Bob"))
    path.write_text(moved + "\n" + content, encoding="utf-8")
    g.notice_rejections(folder)
    g.add_candidates(folder, ["ALICE"], "b", "correction")
    assert g.active(folder) == ["Bob"]
    assert path.read_text(encoding="utf-8").split(g.REJECT)[1].strip() == "- Alice"


def test_budget_keeps_owner_terms_first_and_reports_dropped(folder, monkeypatch):
    tokenizer = Tokenizer.from_file(str(next(Path(HF_HUB_CACHE).glob(
        "models--*--faster-whisper-large-v3-turbo/snapshots/*/tokenizer.json"))))
    (vault.BASE / folder / "Glossary.md").write_text("Folder term\n", encoding="utf-8")
    (vault.BASE / "_Glossary.md").write_text("Global term\n", encoding="utf-8")
    terms = [f"acronym-{i:03}" for i in range(100)]
    g.add_candidates(folder, terms, "1", "correction")
    g.add_candidates(folder, ["Alice"], "2", "name")
    monkeypatch.setitem(g.cfg, "auto_glossary_whisper", True)
    prompt, dropped = g.hotwords(folder, "3", tokenizer)
    assert prompt.startswith("Folder term, Global term, Alice, acronym-000")
    assert prompt.split(", ") + dropped == g.active(folder)
    assert len(tokenizer.encode(" " + prompt, add_special_tokens=False).ids) <= 213
    assert len(tokenizer.encode(" " + prompt + ", " + dropped[0], add_special_tokens=False).ids) > 213
    monkeypatch.setitem(g.cfg, "auto_glossary_whisper", False)
    assert g.hotwords(folder, "3", tokenizer) == ("Folder term, Global term, Alice", [])


def test_edit_diff_finds_corrected_term(folder):
    r = vault.new_recording(dict(title="Edit", id="one", duration="1m", date="2026-11-17"))
    r.update(utterances=[dict(s=0, e=3, spk="S1", text="use the prism now")])
    vault.render(r)
    path = r["_dir"] / (r["stem"] + " - Transcript.md")
    edit = path.read_text(encoding="utf-8").replace("the prism", "the MRAF")
    path.write_text(edit, encoding="utf-8")
    r["utterances"][0]["text"] = "this version changed completely"
    vault.render(r)
    assert g.active(folder) == ["MRAF"]
    assert next(r["_dir"].glob("*(your edit 1).md")).read_text(encoding="utf-8") == edit


def test_terms_do_not_feed_their_own_recording(folder):
    g.add_candidates(folder, ["Alice"], "a", "name")
    assert g.active(folder, "a") == []
    assert g.active(folder, "b") == ["Alice"]
    g.add_candidates(folder, ["Alice"], "b", "note")
    assert g.active(folder, "a") == ["Alice"]


def test_owner_part_never_rewritten(folder):
    prefix = b"\xef\xbb\xbf---\r\nx: y\r\n---\r\n# terms\r\n- Caf\xc3\xa9  \r\n"
    path = vault.BASE / folder / "Glossary.md"
    path.write_bytes(prefix)
    g.add_candidates(folder, ["MRAF"], "a", "correction")
    g.add_candidates(folder, ["MRAF"], "b", "note")
    assert path.read_bytes().split(g.AUTO.encode())[0] == prefix
    assert g.active(folder) == ["Café", "MRAF"]


def _rec(rec_id, date, group, text=""):
    r = vault.new_recording(dict(title=rec_id, id=rec_id, duration="1m", date=date), group)
    r["utterances"] = [dict(s=0, e=3, spk="S1", text=text)] if text else []
    vault.save(r)
    return vault.find(rec_id)


def _groups(folder, rec_id):
    return {w["term"]: w["group"] for w in g.view(folder, vault.find(rec_id))["words"]}


def test_tab_shows_each_word_once_for_its_recording(folder):
    (vault.BASE / "TESI").mkdir()
    path = vault.BASE / "TESI" / "Glossary.md"
    path.write_bytes(b"---\r\nx: y\r\n---\r\n# terms\r\n- Old\r\n")
    _rec("a", "2026-11-10", "TESI", "we ran the FFT on the Sinkhorn output, the fft again")
    _rec("b", "2026-11-11", "TESI", "nothing here")
    for rec in ("a", "b"):
        g.add_candidates("TESI", ["FFT"], rec, "note")
    g.add_candidates("TESI", ["Sinkhorn"], "a", "note")
    g.add_candidates("TESI", ["Speckle"], "b", "note")
    g.add_candidates("TESI", ["Alice"], "a", "name")
    g.add_candidates("TESI", ["Alice"], "b", "name")
    assert _groups("TESI", "a") == {"Old": "active", "Alice": "added", "FFT": "heard", "Sinkhorn": "new", "Speckle": "waiting"}
    assert _groups("TESI", "b") == {"Old": "active", "Alice": "active", "FFT": "active", "Sinkhorn": "waiting", "Speckle": "new"}
    words = {w["term"]: w for w in g.view("TESI", vault.find("a"))["words"]}
    assert words["FFT"]["said"] == 2 and words["Alice"]["kind"] == "speaker" and words["Old"]["kind"] == "yours"
    assert words["Sinkhorn"]["targets"] == {"heard": "use", "blocked": "block"}   # never dragged into "Added by you"
    assert words["FFT"]["targets"] == words["Alice"]["targets"] == {"blocked": "block"}

    g.act("TESI", "use", "Sinkhorn", "a")                       # Use now: active without a second recording
    assert _groups("TESI", "a")["Sinkhorn"] == "heard" and "Sinkhorn" in g.active("TESI")
    g.act("TESI", "add", "MRAF", "a")
    assert (_groups("TESI", "a")["MRAF"], _groups("TESI", "b")["MRAF"]) == ("added", "active")
    assert path.read_bytes().decode("utf-8").startswith("---\r\nx: y\r\n---\r\n# terms\r\nOld\r\nMRAF\r\n" + g.AUTO)
    for writer in (lambda: g.add_candidates("TESI", ["X"], "c", "note"), g.promote_global,
                   lambda: g.notice_rejections("TESI"), g.relocate):
        writer()
        assert g._extra(path)["added"] == {"mraf": ["a"]}      # no other writer drops what the tab knows

    g.act("TESI", "block", "MRAF", "a")                         # your word: blocked, then restored as yours
    words = {w["term"]: w for w in g.view("TESI", vault.find("a"))["words"]}
    assert words["MRAF"]["group"] == "blocked" and words["MRAF"]["targets"] == {"added": "restore"} and "MRAF" not in g.active("TESI")
    g.act("TESI", "restore", "MRAF", "a")
    assert _groups("TESI", "a")["MRAF"] == "added" and "MRAF" in g.active("TESI")

    g.act("TESI", "block", "Speckle", "a")
    g.add_candidates("TESI", ["Speckle"], "c", "note")
    assert "Speckle" not in g.active("TESI")                     # blocked words never come back by themselves
    g.act("TESI", "delete", "Speckle", "a")                      # second remove: gone for good, evidence too
    assert "Speckle" not in _groups("TESI", "a")
    g.add_candidates("TESI", ["Speckle"], "d", "note")           # a later recording may find it again
    assert _groups("TESI", "a")["Speckle"] == "waiting"

    for action, term in (("delete", "FFT"), ("use", "FFT"), ("restore", "FFT"), ("block", "Speckle"), ("block", "Speckle")):
        if action == "block" and _groups("TESI", "a").get(term) != "blocked":
            g.act("TESI", action, term, "a")
            continue
        with pytest.raises(RuntimeError):                        # a page older than the file changes nothing
            g.act("TESI", action, term, "a")
    for action, term in (("add", "bad · term"), ("add", "  "), ("rename", "FFT")):
        with pytest.raises(ValueError):
            g.act("TESI", action, term, "a")


def test_blocked_word_goes_back_only_where_it_was(folder):
    (vault.BASE / "TESI").mkdir()
    (vault.BASE / "TESI" / "Glossary.md").write_text("Old\n", encoding="utf-8")
    _rec("a", "2026-11-10", "TESI", "the FFT again")
    _rec("b", "2026-11-11", "TESI")
    for rec in ("a", "b"):
        g.add_candidates("TESI", ["FFT"], rec, "note")
    g.add_candidates("TESI", ["Sinkhorn"], "a", "note")
    g.add_candidates("TESI", ["Speckle"], "b", "note")
    g.act("TESI", "add", "MRAF", "a")
    before = _groups("TESI", "a")
    assert set(before.values()) == {"new", "heard", "added", "active", "waiting"}
    for term, group in before.items():
        g.act("TESI", "block", term, "a")
        row = next(w for w in g.view("TESI", vault.find("a"))["words"] if w["term"] == term)
        assert row["targets"] == {group: "restore"}, term      # one way out: back where it came from
        g.act("TESI", "restore", term, "a")
        assert _groups("TESI", "a")[term] == group, term


def test_added_words_follow_a_moved_recording(folder):
    for name in ("TESI", "Optics"):
        (vault.BASE / name).mkdir()
    _rec("a", "2026-11-10", "TESI")
    _rec("i", "2026-11-12", folder)
    g.act("TESI", "add", "MRAF", "a")
    g.act(folder, "add", "Zemax", "i")
    vault.move("a", "Optics")
    assert "MRAF" not in g.active("TESI") and _groups("Optics", "a")["MRAF"] == "added"
    vault.move("i", "TESI")
    assert _groups("TESI", "i")["Zemax"] == "added"
    assert "Zemax" in g._read(vault.BASE / folder / "Glossary.md")[2]   # the Inbox keeps it


def test_inbox_keeps_another_folders_word_until_removed_there(folder):
    (vault.BASE / "TESI").mkdir()
    (vault.BASE / "TESI" / "Glossary.md").write_text("Zernike\n", encoding="utf-8")
    _rec("i", "2026-11-12", folder, "Zernike again")
    assert _groups(folder, "i") == {"Zernike": "heard"}
    g.act(folder, "block", "Zernike", "i")
    blocked = g.view(folder, vault.find("i"))["words"][0]
    assert (blocked["group"], blocked["forever"], blocked["home"]) == ("blocked", False, "TESI")
    with pytest.raises(ValueError):
        g.act(folder, "delete", "Zernike", "i")
    g.act(folder, "restore", "Zernike", "i")
    assert _groups(folder, "i") == {"Zernike": "heard"}
    assert g._read(vault.BASE / folder / "Glossary.md")[2] == []        # still TESI's word, not the Inbox's


def test_import_into_a_folder_and_inbox_borrows_every_folder(folder):
    (vault.BASE / "TESI").mkdir()
    (vault.BASE / "TESI" / "Glossary.md").write_text("Zernike\n", encoding="utf-8")
    r = vault.new_recording(dict(title="Filed", id="f", duration="1m", date="2026-11-17"), "TESI")
    assert r["group"] == "TESI" and vault.find("f")["_dir"].parent.name == "TESI"
    assert g.active("TESI") == ["Zernike"]
    assert g.active(folder) == ["Zernike"]          # an unfiled import still gets the folder words
    g.act(folder, "block", "Zernike", "f")
    assert g.active(folder) == []                    # unless removed in the Inbox itself
    with pytest.raises(ValueError):
        vault.new_recording(dict(title="Bad", id="x", duration="1m", date="2026-11-17"), "../out")


def test_inbox_pool_shares_whisper_budget_and_follows_what_is_heard(folder):
    tokenizer = Tokenizer.from_file(str(next(Path(HF_HUB_CACHE).glob(
        "models--*--faster-whisper-large-v3-turbo/snapshots/*/tokenizer.json"))))
    for name, prefix in (("Alpha", "alphaterm"), ("Optics", "opticsterm")):   # each overflows Whisper alone
        (vault.BASE / name).mkdir()
        (vault.BASE / name / "Glossary.md").write_text("\n".join(
            [f"{prefix}-{i:03}" for i in range(120)] + (["Zernike"] if name == "Optics" else [])) + "\n", encoding="utf-8")
    prompt, dropped = g.hotwords(folder, "x", tokenizer)
    sent = prompt.split(", ")
    assert dropped and sum(t.startswith("alpha") for t in sent) - sum(t.startswith("optics") for t in sent) in (0, 1)
    said = "then we fit the Zernicke polynomials to the phase"   # misspelt, as Whisper writes it without hints
    assert g.leading(folder, said) == ["Optics"]
    prompt, dropped = g.hotwords(folder, "x", tokenizer, said)
    sent = prompt.split(", ")
    assert sent[0] == "Zernike" and all(t.startswith("optics") for t in sent[1:])
    assert sent == g.active(folder, "x", said)[:len(sent)]       # the logged count matches what Whisper got
    assert g.leading(folder, "nothing relevant here") == []
    assert g.heard(["CGH", "FFT"], "the cgh and the fft") == {"CGH", "FFT"}
    assert g.heard(["CGH"], "the cgi") == set()                  # short words must match exactly
    assert g.said(["Zernike", "FFT"], "zernike, Zernicke and fft") == {"Zernike": 2, "FFT": 1}
