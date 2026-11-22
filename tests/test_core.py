"""Checks for the pure logic: no GPU, no network, no Plaud account needed."""
import json
from pathlib import Path

import pytest

from app import ensemble, plaud, vault


def test_parse_plaud_listing():
    text = ("- Fetching files...\n\n  ID   NAME   DATE   DURATION\n"
            "  of_c2dfaf9694e3ff65746fae8c1dadfe17  11-11 Weekly Architecture Sync  2026-11-11  34m47s\n"
            "  of_d7b29f08a6d271bcd3fa86f7df30be3b  2026-10-27 16:02:50  2026-10-27  29m38s\n")
    rows = plaud.parse_list(text)
    assert [r["title"] for r in rows] == ["11-11 Weekly Architecture Sync", "2026-10-27 16:02:50"]
    assert rows[0]["date"] == "2026-11-11" and rows[1]["duration"] == "29m38s"


def test_recording_ids_are_validated():
    with pytest.raises(ValueError):
        plaud._check("of_123; rm -rf /")


def test_parse_plaud_listing_pages(monkeypatch):
    pages = ["\n".join(f"  of_{n:032x}  Recording {n}  2026-11-17  1m" for n in range(start, stop))
             for start, stop in ((0, 100), (100, 103))]
    calls = []
    def run(*args):
        calls.append(args)
        return pages[int(args[args.index("-p") + 1]) - 1]
    monkeypatch.setattr(plaud, "_run", run)
    rows = plaud.list_recordings("2026-11-17")
    assert len(rows) == 103 and len({r["id"] for r in rows}) == 103
    assert calls == [("files", "-s", "100", "-p", str(n), "--date-from", "2026-11-17") for n in (1, 2)]


def test_plaud_errors_and_partial_download_keep_existing_audio(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setattr(plaud.shutil, "which", lambda _: "fake-plaud")
    for code, output, message in ((0, "AUTH_FAILED", "sign-in expired"), (1, "network failed", "network failed")):
        monkeypatch.setattr(plaud.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, code, output, ""))
        with pytest.raises(RuntimeError, match=message):
            plaud.me()
    monkeypatch.setattr(plaud, "_run", lambda *args: "https://example.invalid/audio")
    class BrokenStream:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def raise_for_status(self):
            pass
        def iter_bytes(self, size):
            yield b"partial"
            raise RuntimeError("download interrupted")
    monkeypatch.setattr(plaud.httpx, "stream", lambda *a, **kw: BrokenStream())
    dest = tmp_path / "audio.ogg"
    dest.write_bytes(b"existing audio")
    with pytest.raises(RuntimeError, match="interrupted"):
        plaud.download_audio("of_" + "a" * 32, dest)
    assert dest.read_bytes() == b"existing audio"


def test_download_status_error_keeps_signed_url_private(tmp_path, monkeypatch):
    url = "https://example.invalid/audio?token=private"
    monkeypatch.setattr(plaud, "_run", lambda *args: url)
    transport = plaud.httpx.MockTransport(lambda request: plaud.httpx.Response(403))
    with plaud.httpx.Client(transport=transport) as client:
        monkeypatch.setattr(plaud.httpx, "stream", client.stream)
        with pytest.raises(RuntimeError) as error:
            plaud.download_audio("of_" + "a" * 32, tmp_path / "audio.ogg")
    assert str(error.value) == "Audio download failed (HTTP 403)"
    assert error.value.__suppress_context__


def test_words_get_the_overlapping_speaker():
    from app.speech import utterances  # imports faster-whisper; fine without a GPU
    words = [{"s": 0.2, "e": 0.5, "w": " ciao"}, {"s": 0.6, "e": 0.9, "w": " come"},
             {"s": 5.1, "e": 5.4, "w": " bene"}, {"s": 5.4, "e": 5.41, "w": " grazie"}]
    utts = utterances(words, [(0.0, 1.0, 0), (5.0, 6.0, 1)])
    assert [(u["spk"], u["text"]) for u in utts] == [(0, "ciao come"), (1, "bene grazie")]


def test_ensemble_guard_rejects_invented_words(monkeypatch):
    a = [{"s": 1.0, "e": 1.2, "w": " il"}, {"s": 1.3, "e": 1.6, "w": " ticere"}, {"s": 1.7, "e": 2.0, "w": " spiega"}]
    b = [{"s": 1.0, "e": 1.2, "w": " il"}, {"s": 1.3, "e": 1.6, "w": " teacher"}, {"s": 1.7, "e": 2.0, "w": " spiega"}]
    monkeypatch.setattr(ensemble.llm, "run", lambda p, prompt: "1|il teacher spiega")
    words, rejected, candidates = ensemble.fuse([a, b], [], "x")
    assert "".join(w["w"] for w in words) == " il teacher spiega" and rejected == {} and candidates == ["teacher"]
    assert words[1]["s"] == 1.0 + 0.2 or words[1]["s"] >= 1.2  # retimed after the previous word
    monkeypatch.setattr(ensemble.llm, "run", lambda p, prompt: "1|il professore spiega tutto")
    words, rejected, candidates = ensemble.fuse([a, b], [], "x")
    assert words == a and rejected == {"invented words": 1}  # invented word -> raw transcript kept


def test_folder_names():
    assert vault.group_ok("Research Notes") and not vault.group_ok("../x") and not vault.group_ok("_Blueprints")
    assert vault.safe("11-11 Sync: Research / [x]") == "11-11 Sync Research x"


def test_render_and_move(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "BASE", tmp_path)
    vault.seed()
    rec = vault.new_recording({"id": "of_" + "a" * 32, "title": "Riunione", "date": "2026-11-16", "duration": "1m"})
    rec["utterances"] = [{"s": 0, "e": 20, "spk": "S1", "text": "prima parte"}, {"s": 21, "e": 40, "spk": "S2", "text": "seconda"}]
    rec["marks"] = [{"t": 25.0, "kind": "memo", "text": "pistone medio"}]
    rec["speakers"] = {"S2": {"name": "Bob"}}
    vault.render(rec)
    t = (rec["_dir"] / f"{rec['stem']} - Transcript.md").read_text(encoding="utf-8")
    assert t.index("prima parte") < t.index("pistone medio") < t.index("**Bob**")  # memo sits before its utterance
    hub = rec["_dir"] / f"{rec['stem']}.md"
    hub.write_text(hub.read_text(encoding="utf-8") + "my own comment\n", encoding="utf-8")
    vault.render(vault.find(rec["id"]))
    assert "my own comment" in hub.read_text(encoding="utf-8")  # user text below the marker survives
    vault.move(rec["id"], "Research")
    moved = vault.find(rec["id"])
    assert moved["group"] == "Research" and (moved["_dir"] / "recording.json").exists()
    assert json.loads((moved["_dir"] / "recording.json").read_text(encoding="utf-8"))["speakers"] == {"S2": {"name": "Bob"}}
    assert "Bob" not in vault.glossary("Research") and vault.glossary("Research") == []


def test_late_turn_boundary_does_not_split_a_sentence():
    from app.speech import utterances
    # speaker 1's turn starts 0.5 s late, in the middle of their sentence
    words = [{"s": 0.0, "e": 0.4, "w": " Va"}, {"s": 0.4, "e": 0.9, "w": " bene."},
             {"s": 1.0, "e": 1.4, "w": " La"}, {"s": 1.4, "e": 1.9, "w": " cornice"}, {"s": 1.9, "e": 2.6, "w": " serve."}]
    utts = utterances(words, [(0.0, 1.5, 0), (1.5, 3.0, 1)])
    assert [(u["spk"], u["text"]) for u in utts] == [(0, "Va bene."), (1, "La cornice serve.")]


def test_sliver_speakers_are_dropped_and_renumbered():
    from app.speech import tidy_turns
    turns = [(0, 100, 7), (100, 400, 2), (400, 403, 5), (403, 500, 7)]  # speaker 5 talks 3 s
    assert tidy_turns(turns) == [(0, 100, 1), (100, 400, 0), (403, 500, 1)]
    assert len({spk for *_, spk in tidy_turns(turns, keep_all=True)}) == 3  # user fixed the count: keep


def test_split_voice_is_merged_and_sliver_joins_nearest():
    import numpy as np
    from app.speech import merge_voices, tidy_turns

    def v(*x):
        a = np.array(x, dtype=float)
        return a / np.linalg.norm(a)
    # clusters 0 and 1 are one voice, 2 is another, 3 is a 5 s sliver that sounds most like 2
    prints = {0: (300.0, v(1, 0, 0)), 1: (200.0, v(0.95, 0.1, 0)), 2: (100.0, v(0, 1, 0)), 3: (5.0, v(0.3, 0.6, 0.5))}
    turns = [(0, 300, 0), (300, 500, 1), (500, 600, 2), (600, 605, 3)]
    merged = tidy_turns(merge_voices(turns, prints, same=0.82))
    assert [spk for _, _, spk in merged] == [0, 0, 1, 1]
    # a fixed count overrides the similarity rule
    assert len({spk for _, _, spk in merge_voices(turns, prints, same=0.82, k=1)}) == 1


def test_note_for_a_long_title_gets_its_own_file(tmp_path):
    stem = "x" * 80  # as long as safe() allows: the note name used to collapse onto the hub note
    (tmp_path / f"{stem}.md").write_text("hub")
    rec = {"stem": stem, "_dir": tmp_path}
    assert vault.add_note(rec, "Meeting minutes (claude)", "a") == f"{stem} - Meeting minutes (claude)"
    assert vault.add_note(rec, "Meeting minutes (claude)", "b") == f"{stem} - Meeting minutes (claude) 2"
    assert (tmp_path / f"{stem}.md").read_text() == "hub"


def test_move_keeps_every_note_and_wikilink(tmp_path, monkeypatch):
    import re
    monkeypatch.setattr(vault, "BASE", tmp_path)
    rec = vault.new_recording({"id": "of_" + "b" * 32, "title": "Move me", "date": "2026-11-17", "duration": "1m"})
    (rec["_dir"] / f"{rec['stem']}.ogg").write_bytes(b"fake audio")
    for provider in ("claude", "codex"):
        name = vault.add_note(rec, f"Minutes ({provider})", f"From [[{rec['stem']}]]\n{provider}")
        rec["notes"].append({"file": name + ".md"})
    vault.render(rec)
    before = {p.name: p.read_bytes() for p in rec["_dir"].iterdir()}
    old_folder = rec["_dir"]
    vault.move(rec["id"], "Destination")
    moved = vault.find(rec["id"])
    assert not old_folder.exists()
    assert {p.name: p.read_bytes() for p in moved["_dir"].iterdir()} == before
    hub = (moved["_dir"] / f"{rec['stem']}.md").read_text(encoding="utf-8")
    for link in re.findall(r"\[\[([^\]]+)\]\]", hub):
        assert (moved["_dir"] / (link if link.endswith(".ogg") else link + ".md")).is_file()


def test_agy_stream_json_provider(monkeypatch):
    import subprocess
    from app import config, llm

    seen = {}

    def fake_run(cmd, input, stdout, stderr, **kw):
        assert all(kw["env"][key] == kw["cwd"] for key in ("TEMP", "TMP", "TMPDIR"))
        seen["cmd"] = cmd
        seen["input"] = input
        stdout.write(
            b'{"event":"init"}\n'
            b'{"event":"result","result":{"status":"SUCCESS","response":"OK\\n"}}\n'
        )
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(llm.shutil, "which", lambda name: name)
    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    assert llm.run("antigravity", "Reply OK") == "OK"
    assert json.loads(seen["input"]) == {"event": "user", "message": {"content": "Reply OK"}}
    assert seen["cmd"][0] == "agy" and "antigravity" in config.cfg["providers"]

    def fake_err(cmd, input, stdout, stderr, **kw):
        stdout.write(b'{"event":"result","result":{"status":"ERROR","error":"rate limited"}}\n')
        return subprocess.CompletedProcess(cmd, 1)

    monkeypatch.setattr(llm.subprocess, "run", fake_err)
    with pytest.raises(RuntimeError, match="rate limited"):
        llm.run("antigravity", "Reply OK")


def test_marks_survive_retranscribe_and_redo(tmp_path, monkeypatch):
    from app import pipeline, speech
    monkeypatch.setattr(vault, "BASE", tmp_path)
    rec = vault.new_recording({"id": "of_" + "e" * 32, "title": "Marks", "date": "2026-11-17", "duration": "1m"})
    marks = [{"t": 0.5, "kind": "memo", "text": "Remember"}, {"t": 1, "kind": "highlight", "text": ""}]
    rec.update(marks=marks, speakers={"S1": {"name": "Alice"}})
    rec["diarization"]["turns"] = [[0, 2, "S1"]]
    vault.save(rec)
    monkeypatch.setattr(speech, "load_audio", lambda _: [])
    monkeypatch.setattr(speech, "transcribe", lambda *a: ([{"s": 0, "e": 2, "w": " Hello."}], "en"))
    monkeypatch.setattr(speech, "diarize", lambda *a: {
        "engine": "fake", "turns": [[0, 2, 0]], "overlap": [], "embeddings": {}})
    pipeline.retranscribe(rec["id"], "large-v3-turbo", 0, lambda _: None)
    pipeline.respeak(rec["id"], 0, lambda _: None)
    current = vault.find(rec["id"])
    assert current["marks"] == marks and current["speakers"]["S1"]["name"] == "Alice"
    text = (rec["_dir"] / f"{rec['stem']} - Transcript.md").read_text(encoding="utf-8")
    assert "Remember" in text and "Highlight" in text


def test_same_blueprint_two_providers_two_notes_both_in_hub(tmp_path, monkeypatch):
    from app import pipeline
    monkeypatch.setattr(vault, "BASE", tmp_path)
    vault.seed()
    rec = vault.new_recording({"id": "of_" + "a" * 32, "title": "Notes", "date": "2026-11-17", "duration": "1m"})
    monkeypatch.setattr(pipeline.llm, "run", lambda provider, prompt: "## Core theme ## Tasks ## Ideas\n" + provider)
    for provider in ("claude", "codex"):
        pipeline.generate(rec["id"], "Voice memo", provider, lambda _: None)
    current = vault.find(rec["id"])
    hub = (current["_dir"] / (current["stem"] + ".md")).read_text(encoding="utf-8")
    assert {n["provider"] for n in current["notes"]} == {"claude", "codex"}
    for note in current["notes"]:
        assert f"[[{note['file'][:-3]}]]" in hub
        assert note["provider"] in (current["_dir"] / note["file"]).read_text(encoding="utf-8")


def test_marks_are_in_the_note_prompt(tmp_path, monkeypatch):
    from app import pipeline
    monkeypatch.setattr(vault, "BASE", tmp_path)
    rec = vault.new_recording({"id": "of_" + "a" * 32, "title": "Marks", "date": "2026-11-17", "duration": "1m"})
    rec["marks"] = [{"t": 12, "kind": "memo", "text": "My memo"}, {"t": 20, "kind": "highlight", "text": ""}]
    prompt = pipeline.build_prompt(rec, {"body": "Summarise"})
    assert "[00:12] memo: My memo" in prompt and "[00:20] highlight: (no text)" in prompt


def test_blueprint_edit_is_used_without_restart(tmp_path, monkeypatch):
    from app import pipeline
    monkeypatch.setattr(vault, "BASE", tmp_path)
    vault.seed()
    rec = vault.new_recording({"id": "of_" + "a" * 32, "title": "Prompt", "date": "2026-11-17", "duration": "1m"})
    monkeypatch.setattr(pipeline.llm, "run", lambda provider, prompt: prompt)
    bp = tmp_path / "_Blueprints" / "Voice memo.md"
    for text in ("First version", "Edited version"):
        bp.write_text(text, encoding="utf-8")
        name = pipeline.generate(rec["id"], "Voice memo", "claude", lambda _: None)
        assert text in (rec["_dir"] / (name + ".md")).read_text(encoding="utf-8")


def test_glossary_folder_plus_global_dedup(tmp_path, monkeypatch):
    from app import pipeline
    monkeypatch.setattr(vault, "BASE", tmp_path)
    vault.seed()
    rec = vault.new_recording({"id": "of_" + "a" * 32, "title": "Terms", "date": "2026-11-17", "duration": "1m"})
    (tmp_path / "_Glossary.md").write_text("# Terms\n- Obsidian\n- Alice\n", encoding="utf-8")
    (tmp_path / rec["group"] / "Glossary.md").write_text("Alice\nCGH\n", encoding="utf-8")
    assert vault.glossary(rec["group"]) == ["Alice", "CGH", "Obsidian"]
    assert "Spellings to use: Alice, CGH, Obsidian" in pipeline.build_prompt(rec, {"body": "Summarise"})


def test_plaud_details_transcript_and_summaries_parsing(tmp_path, monkeypatch):
    rec_id = "of_" + "1" * 32
    monkeypatch.setattr(plaud, "_run", lambda *args: (
        "  name: Demo Meeting\n  start_at: 2026-11-10T16:27:53\n"
        "  audio: available\n  transcript: available\n  summary: available\n"
    ))
    info = plaud.details(rec_id)
    assert info == {"title": "Demo Meeting", "start_at": "2026-11-10T16:27:53",
                    "has_transcript": True, "has_summary": True}

    parsed = plaud.parse_transcript(
        "Transcript: Demo\n"
        "[00:01 - 00:19] Alice Mercer: Prima frase.\n"
        "Continua qui.\n"
        "[72:19 - 72:29] Speaker 2: Seconda frase.\n"
    )
    assert len(parsed) == 2
    assert parsed[0] == {"s": 1.0, "e": 19.0, "speaker": "Alice Mercer", "text": "Prima frase. Continua qui."}
    assert parsed[1] == {"s": 4339.0, "e": 4349.0, "speaker": "Speaker 2", "text": "Seconda frase."}

    # transcript() falls back from --polished to raw when polished is unavailable.
    calls = []
    def fake_run(*args):
        calls.append(args)
        if "--polished" in args:
            raise RuntimeError('No "transaction_polish" transcript')
        out_path = Path(args[args.index("-o") + 1])
        out_path.write_text("[00:00 - 00:05] Speaker 1: Ciao\n", encoding="utf-8")
        return "Transcript saved"
    monkeypatch.setattr(plaud, "_run", fake_run)
    segs, polished = plaud.transcript(rec_id, tmp_path / "tr.tmp.txt")
    assert not polished and len(segs) == 1 and segs[0]["text"] == "Ciao"
    assert len(calls) == 2 and not (tmp_path / "tr.tmp.txt").exists()

    # summaries() skips empty entries, converts <mark> to ==...==, and strips plaud:// image stubs.
    def fake_sum(*args):
        out_path = Path(args[args.index("-o") + 1])
        out_path.write_text(json.dumps([
            {"data_type": "auto_sum_note", "data_tab_name": "Summary",
             "data_content": "## Intro\n<mark data-color=\"rgb(1,2,3)\">Key point</mark>\n\n## Related Photos\n\n[](plaud://image?id=1)"},
            {"data_type": "high_light", "data_tab_name": "Highlights", "data_content": "   "},
        ]), encoding="utf-8")
        return "Notes saved"
    monkeypatch.setattr(plaud, "_run", fake_sum)
    notes = plaud.summaries(rec_id, tmp_path / "sum.tmp.json")
    assert len(notes) == 1
    assert notes[0]["title"] == "Summary"
    assert notes[0]["content"] == "## Intro\n==Key point=="
    assert not (tmp_path / "sum.tmp.json").exists()


def test_ingest_plaud_imports_transcript_and_notes_without_gpu_or_llm(tmp_path, monkeypatch):
    from app import llm, pipeline
    monkeypatch.setattr(vault, "BASE", tmp_path)
    vault.seed()
    rec_id = "of_" + "9" * 32

    monkeypatch.setattr(llm, "run", lambda *a, **kw: pytest.fail("Plaud import must not call an AI provider"))
    monkeypatch.setattr(plaud, "list_recordings", lambda date_from=None: [
        {"id": rec_id, "title": "11-10 Short", "date": "2026-11-10", "duration": "1m"}
    ])
    monkeypatch.setattr(plaud, "details", lambda i: {
        "title": "11-10 Full Title", "start_at": "2026-11-10T16:27:53",
        "has_transcript": True, "has_summary": True,
    })
    monkeypatch.setattr(plaud, "download_audio", lambda i, dest: dest.write_bytes(b"OggS-fake") and dest)
    monkeypatch.setattr(plaud, "marks", lambda i, tmp: [{"t": 5.0, "kind": "highlight", "text": "Important"}])
    monkeypatch.setattr(plaud, "transcript", lambda i, tmp: ([
        {"s": 1.0, "e": 10.0, "speaker": "Alice", "text": "Ciao mondo."},
        {"s": 11.0, "e": 75.0, "speaker": "Speaker 2", "text": "Risposta qui."},
    ], True))
    monkeypatch.setattr(plaud, "summaries", lambda i, tmp: [
        {"title": "Summary", "type": "auto_sum_note", "content": "## Riassunto\nAlice e Speaker 2 discutono."}
    ])

    pipeline.ingest_plaud(rec_id, log=lambda _: None)
    rec = vault.find(rec_id)
    assert rec["stage"] == "done" and rec["source"] == "plaud"
    assert rec["model"] == "plaud" and rec["speaker_engine"] == "plaud"
    assert rec["title"] == "11-10 Full Title" and rec["duration_s"] == 75.0
    assert rec["speakers"] == {"S1": {"name": "Alice"}, "S2": {"name": ""}}
    assert len(rec["utterances"]) == 2 and len(rec["words"]) == 4
    assert len(rec["notes"]) == 1 and rec["notes"][0]["provider"] == "plaud"
    hub = (rec["_dir"] / f"{rec['stem']}.md").read_text(encoding="utf-8")
    assert f"[[{rec['notes'][0]['file'][:-3]}]]" in hub

    # Speaker edits (rename + merge + fix) work on Plaud-imported recordings too.
    pipeline.rename_speakers(rec_id, {"S1": "Alice", "S2": "Bob"})
    note_body = (rec["_dir"] / rec["notes"][0]["file"]).read_text(encoding="utf-8")
    assert "Bob" in note_body
    pipeline.add_fix(rec_id, 11.0, 75.0, "S1")
    assert all(u["spk"] == "S1" for u in vault.find(rec_id)["utterances"])

    # Unparsed recording in Plaud fails cleanly without creating a vault folder.
    unparsed_id = "of_" + "8" * 32
    monkeypatch.setattr(plaud, "details", lambda i: {"title": "Raw", "start_at": "", "has_transcript": False, "has_summary": False})
    with pytest.raises(RuntimeError, match="not been transcribed"):
        pipeline.ingest_plaud(unparsed_id, log=lambda _: None)
    assert all(r["id"] != unparsed_id for r in vault.scan())


def test_shipped_blueprints_are_consistent(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "BASE", tmp_path)
    vault.seed()
    bps = vault.blueprints()
    assert len(bps) == len(list((Path(vault.__file__).parent / "blueprints").glob("[!_]*.md")))
    assert [b["auto"] for b in bps].count(True) == 1 and bps[0]["auto"]  # the dashboard preselects it
    for bp in bps:
        assert bp["requires"] and bp["name"] == vault.safe(bp["name"])
        missing = [r for r in bp["requires"] if r not in bp["body"]]
        assert not missing, f"{bp['name']}: the prompt never shows {missing}"
