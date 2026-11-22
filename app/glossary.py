"""Folder and global Markdown glossaries, with recording evidence beside each file."""
import datetime as dt
import json
import re
from collections import Counter
from difflib import SequenceMatcher, get_close_matches
from threading import RLock

from app import vault
from app.config import cfg

AUTO = "%% Automatic terms below. Delete a line to drop a term; move it above to keep it for good. %%"
REJECT = "%% Rejected: never added again %%"
LOCK = RLock()
INSTRUCTION = ("After the note, add a fenced block marked `glossary`"
               " that lists up to 15 names, technical terms and acronyms spoken in this meeting, "
               "spelled correctly, one per line. End your response in this format:\n"
               "```glossary\n<term>\n```")
WORD = re.compile(r"[^\W_]+(?:[-'’][^\W_]+)*")
BLOCK = re.compile(r"^```glossary[ \t]*\r?\n(.*?)^```[ \t]*(?:\r?\n|$)", re.M | re.S)


def strip_block(text):
    terms = [line.strip(" \t*-") for block in BLOCK.findall(text) for line in block.splitlines()]
    return BLOCK.sub("", text).rstrip(), [term for term in terms if term][:15]


def replacements(original, edited):
    before, after = WORD.findall(original), WORD.findall(edited)
    known = {w.casefold() for w in before}
    return [w for tag, _, _, a, b in SequenceMatcher(None, before, after, autojunk=False).get_opcodes()
            if tag == "replace" for w in after[a:b]
            if w[:1].isupper() or any(c.isdigit() for c in w) or w.casefold() not in known]


def _read(path):
    raw = path.read_bytes().decode("utf-8") if path.exists() else ""
    marker = re.search("^" + re.escape(AUTO) + r"\r?$", raw, re.M)
    prefix = raw[:marker.start()] if marker else raw
    _, body = vault._frontmatter(prefix.lstrip("\ufeff").replace("\r\n", "\n"))
    owners = [t for line in body.splitlines() if (t := line.strip(" -*\t"))
              and not line.lstrip().startswith(("#", "%%", ">"))]
    owners = [re.sub(r" · \d+ recordings? · last \d{4}-\d{2}-\d{2}$", "", term) for term in owners]
    auto, _, tail = (raw[marker.end():] if marker else "").partition(REJECT)
    visible = {s.split(" · ", 1)[0].casefold() for s in re.findall(r"^- (.+?)\r?$", auto, re.M)}
    side = path.with_suffix(".json")
    state = {}
    if side.exists():
        state = json.loads(side.read_bytes())
        if not isinstance(state, dict) or not {"shown", "rejected", "entries"} <= state.keys():
            raise ValueError(f"Unrecognized glossary evidence file: {side}")
    rejected = {s.casefold(): s for s in re.findall(r"^- (.+?)\r?$", tail, re.M)}
    rejected.update(state.get("rejected", {}))
    retained = visible | {s.casefold() for s in owners}
    for term in state.get("shown", []):
        if term.casefold() not in retained:
            rejected[term.casefold()] = term
    return raw, prefix, owners, rejected, state.get("entries", {})


def _eligible(entry):   # "use": you pressed Use now on it
    return len(entry["ids"]) >= 2 or entry["source"] in ("name", "correction", "use")


def _rank(entry):
    return (entry["source"] != "name", -len(entry["ids"]), -dt.date.fromisoformat(entry["last"]).toordinal(),
            entry["term"].casefold())


def _extra(path):
    """Dashboard bookkeeping in the evidence file: the recordings each of your words was added on,
    and your words now blocked (so Restore makes them yours again)."""
    side = path.with_suffix(".json")
    state = json.loads(side.read_bytes()) if side.exists() else {}
    return {"added": state.get("added", {}), "owned_blocked": state.get("owned_blocked", [])}


def _write(path, original, prefix, owners, rejected, entries, extra=None):
    excluded = set(rejected) | {s.casefold() for s in owners}
    shown = sorted((e for k, e in entries.items() if k not in excluded and _eligible(e)), key=_rank)
    extra = _extra(path) if extra is None else extra   # every writer keeps it, not only the dashboard
    if not entries and not rejected and not any(extra.values()) and not path.with_suffix(".json").exists():
        return
    lines = [AUTO, *(f"- {e['term']} · {len(e['ids'])} recordings · last {e['last']}" for e in shown),
             REJECT, *(f"- {s}" for s in rejected.values())]
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    state = {"shown": [e["term"] for e in shown], "entries": entries, "rejected": rejected, **extra}
    if (path.read_bytes().decode("utf-8") if path.exists() else "") != original:
        raise RuntimeError(f"{path.name} changed during the update; retry to include the edit")
    for dest, value in [(path, prefix + "\n".join(lines) + "\n"),
                        (path.with_suffix(".json"), json.dumps(state, ensure_ascii=False))]:
        data = value.encode("utf-8")
        if not dest.exists() or dest.read_bytes() != data:
            tmp = dest.with_suffix(dest.suffix + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(dest)


def _merge(entries, term, ids, source, last):
    e = entries.setdefault(term.casefold(), dict(term=term, ids=[], source=source, last=last))
    e["ids"] = sorted(set(e["ids"]).union(ids))
    e["last"] = max(last, e["last"])
    if source == "name" or (source == "correction" and e["source"] != "name"):
        e.update(term=term, source=source)


def promote_global():
    with LOCK:
        path = vault.BASE / "_Glossary.md"
        original, prefix, owners, rejected, _ = _read(path)
        combined, folders = {}, Counter()
        for side in vault.BASE.glob("*/Glossary.json"):
            _, _, _, blocked, entries = _read(side.with_suffix(".md"))
            for k, e in entries.items():
                if k not in blocked and _eligible(e):
                    folders[k] += 1
                    _merge(combined, e["term"], e["ids"], e["source"], e["last"])
        _write(path, original, prefix, owners, rejected, {k: e for k, e in combined.items() if folders[k] >= 2})


def valid(term):
    return (0 < len(term) <= 120 and term.isprintable() and " · " not in term
            and "%%" not in term and not term.startswith(("#", ">")))


def _owner_text(prefix, owners):
    """The owner part with its term lines replaced by `owners` (headings, comments, front matter stay)."""
    nl = "\r\n" if "\r\n" in prefix else "\n"
    keep, front = [], False
    for i, line in enumerate(prefix.splitlines(keepends=True)):
        s = line.lstrip("﻿").strip()
        if i == 0 and s == "---":
            front = True
        elif front and s == "---":
            front = False
        elif not front and s and not s.startswith(("#", "%%", ">")):
            continue   # an old term line: replaced by the new list below
        keep.append(line)
    text = "".join(keep)
    if text and not text.endswith("\n"):
        text += nl
    return text + "".join(t + nl for t in owners)


def _set_owners(prefix, before, after):
    """Rewrite the owner lines only when they changed, so an untouched file keeps its own formatting."""
    return prefix if before == after else _owner_text(prefix, after)


def _elsewhere(folder):
    """Words in use in `folder` that live in another file: the general glossary, and for the Inbox
    every folder. casefold -> entry, with `home` naming where it lives."""
    paths = [vault.BASE / "_Glossary.md"]
    if folder == cfg["inbox"]:
        paths += [p for p in sorted(vault.BASE.glob("*/Glossary.md")) if p.parent.name != folder]
    out = {}
    for p in paths:
        home = p.parent.name if p.name == "Glossary.md" else "every folder"
        _, _, own, rejected, entries = _read(p)
        for t in own:
            out.setdefault(t.casefold(), dict(term=t, ids=[], source="owner", last="", home=home))
        for k, e in entries.items():
            if k not in rejected and _eligible(e):
                out.setdefault(k, dict(e, home=home))
    return out


def said(terms, text):
    """How often each term is said in `text`, allowing a small misspelling: without hints Whisper
    spells names freely."""
    words = [w.casefold() for w in WORD.findall(text)]
    grams, found = {}, Counter()
    for term in terms:
        key = " ".join(WORD.findall(term.casefold()))
        if not key:
            continue
        n = key.count(" ") + 1
        if n not in grams:
            grams[n] = Counter(" ".join(words[i:i + n]) for i in range(len(words) - n + 1))
        hits = get_close_matches(key, grams[n], 5, 0.85) if len(key) > 4 else [key] * (key in grams[n])
        if hits:
            found[term] = sum(grams[n][h] for h in hits)
    return found


def heard(terms, text):
    """The terms said in `text` (see `said`)."""
    return set(said(terms, text))


def view(folder, rec):
    """The glossary as one recording's Glossary tab shows it. Every word appears once, in one group:
    new / heard / added (this recording), active / waiting / blocked (rest of the folder).
    `targets` maps each group a word may be dragged to onto the action that puts it there: a waiting word
    can be used (it lands in Heard or Active) or blocked, a word in use can be blocked, a blocked word goes
    back where it came from. Nothing is dragged into "Added by you": you add a word by typing it."""
    rec_id = rec["id"]
    with LOCK:
        path = vault.BASE / folder / "Glossary.md"
        _, _, owners, rejected, entries = _read(path)
        extra, info = _extra(path), _elsewhere(folder)
    sent = _ranked(folder)[0]
    mine = {t.casefold() for t in owners}
    added, owned_blocked = extra["added"], set(extra["owned_blocked"])
    text = " ".join(u["text"] for u in rec.get("utterances", []))
    count = said([*sent, *(e["term"] for e in entries.values())], text)
    dates = {r["id"]: r["date"] for r in vault.scan()}

    def first_here(e):   # a name or fix counts as added on the recording it first came from
        ids = sorted(e["ids"], key=lambda i: (dates.get(i, "9999"), i))
        return bool(ids) and ids[0] == rec_id

    def in_use(k, term):
        e = entries.get(k) or info.get(k)
        if rec_id in added.get(k, []) or (e and e["source"] in ("name", "correction") and first_here(e)):
            return "added"
        return "heard" if count.get(term) else "active"

    def row(term, group, e, targets, **more):
        k = term.casefold()
        kind = ("speaker" if e and e["source"] == "name" else
                "yours" if k in mine or k in owned_blocked or (e and e["source"] in ("correction", "owner")) else "found")
        return dict(term=term, group=group, kind=kind, said=count.get(term, 0), recordings=len(e["ids"]) if e else 0,
                    last=e["last"] if e else "", home=e.get("home") if e else None, targets=targets, **more)

    rows = []
    for term in sent:
        k = term.casefold()
        rows.append(row(term, in_use(k, term), entries.get(k) or info.get(k), {"blocked": "block"}))
    in_sent = {t.casefold() for t in sent}
    for k, e in sorted(entries.items(), key=lambda item: _rank(item[1])):
        if k in rejected or k in mine or k in in_sent or _eligible(e):
            continue
        go = "heard" if count.get(e["term"]) else "active"
        rows.append(row(e["term"], "new" if rec_id in e["ids"] else "waiting", e,
                        {go: "use", "blocked": "block"}))   # "Added by you" takes only typed words
    for k, term in sorted(rejected.items(), key=lambda item: item[1].casefold()):
        e = entries.get(k) or info.get(k)
        if k in owned_blocked or not e:
            back = "added" if rec_id in added.get(k, []) else "heard" if count.get(term) else "active"
        elif _eligible(e):
            back = in_use(k, term)
        else:
            back = "new" if rec_id in e["ids"] else "waiting"
        foreign = k in info and k not in entries and k not in owned_blocked
        rows.append(row(term, "blocked", e, {back: "restore"}, forever=not foreign))
    return {"folder": folder, "inbox": folder == cfg["inbox"], "sent": len(sent), "words": rows}


ACTIONS = ("add", "use", "block", "restore", "delete")
STALE = "This word changed since the page loaded it (in Obsidian or by a job). The glossary has been reloaded."


def act(folder, action, term, rec_id):
    """One change from the Glossary tab. Each action names the change it expects, so a page older than
    the file cannot, say, delete for good a word it still shows as active (RuntimeError)."""
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}")
    term = term.strip(" -*\t") if isinstance(term, str) else ""
    if not valid(term):
        raise ValueError("A word can't be empty or longer than 120 characters, contain · or %%, or start with # or >.")
    k = term.casefold()
    with LOCK:
        path = vault.BASE / folder / "Glossary.md"
        original, prefix, before, rejected, entries = _read(path)
        extra = _extra(path)
        owners, added, owned_blocked = list(before), extra["added"], set(extra["owned_blocked"])
        mine = {t.casefold() for t in owners}
        if action == "add":
            if k in rejected:   # typing a blocked word again means you want it
                del rejected[k]
                owned_blocked.discard(k)
            if k not in mine:
                owners.append(term)
            added[k] = sorted({*added.get(k, []), rec_id})
        elif action == "use":
            e = entries.get(k)
            if not e or k in rejected or k in mine or _eligible(e):
                raise RuntimeError(STALE)
            e["source"] = "use"
        elif action == "block":
            if k in rejected:
                raise RuntimeError(STALE)
            if k in mine:
                owners = [t for t in owners if t.casefold() != k]
                owned_blocked.add(k)
            rejected[k] = term
        else:
            if k not in rejected:
                raise RuntimeError(STALE)
            foreign = k not in entries and k not in owned_blocked and k in _elsewhere(folder)
            if action == "restore":
                term = rejected.pop(k)
                if k in owned_blocked or (k not in entries and not foreign):
                    owners.append(term)
                owned_blocked.discard(k)
            else:   # delete: gone for good, evidence too; a later recording may find it again
                if foreign:
                    raise ValueError("This word lives in another folder's glossary: restore it here, or remove it there.")
                del rejected[k]
                entries.pop(k, None)
                added.pop(k, None)
                owned_blocked.discard(k)
        _write(path, original, _set_owners(prefix, before, owners), owners, rejected, entries,
               {"added": added, "owned_blocked": sorted(owned_blocked)})
        promote_global()


def add_candidates(folder, terms, rec_id, source, date=None):
    with LOCK:
        path = vault.BASE / folder / "Glossary.md"
        original, prefix, owners, rejected, entries = _read(path)
        for term in terms:
            term = term.strip()
            if valid(term) and term.casefold() not in rejected and not re.fullmatch(r"Speaker \d+", term):  # a default label, not a name
                _merge(entries, term, [rec_id], source, date or dt.date.today().isoformat())
        _write(path, original, prefix, owners, rejected, entries)
        promote_global()


def relocate():
    """File each recording's learned terms, and the words you added on it, under the folder it is in
    now. Terms are learned where the recording was transcribed (usually the Inbox); without this,
    moving it left them behind. Your added words leave the old folder, except the Inbox."""
    with LOCK:
        where = {r["id"]: (r["group"], r["date"]) for r in vault.scan()}
        moving, sources = {}, []
        for side in vault.BASE.glob("*/Glossary.json"):
            folder, path = side.parent.name, side.with_suffix(".md")
            original, prefix, owners, rejected, entries = _read(path)
            extra, before = _extra(path), list(owners)
            changed = False
            for k, e in list(entries.items()):
                gone = [i for i in e["ids"] if i in where and where[i][0] != folder]
                for i in gone:
                    moving.setdefault(where[i][0], ([], []))[0].append((e["term"], i, e["source"], where[i][1]))
                if gone:
                    changed = True
                    e["ids"] = [i for i in e["ids"] if i not in gone]
                    if not e["ids"]:
                        del entries[k]
            for k, ids in list(extra["added"].items()):
                term = next((t for t in owners if t.casefold() == k), None)
                gone = [i for i in ids if i in where and where[i][0] != folder]
                if not gone or term is None:   # a blocked word stays where you blocked it
                    continue
                changed = True
                for i in gone:
                    moving.setdefault(where[i][0], ([], []))[1].append((term, i))
                extra["added"][k] = [i for i in ids if i not in gone]
                if not extra["added"][k]:
                    del extra["added"][k]
                    if folder != cfg["inbox"]:
                        owners = [t for t in owners if t.casefold() != k]
            if changed:
                sources.append((path, original, _set_owners(prefix, before, owners), owners, rejected, entries, extra))
        for folder, (learned, mine) in moving.items():   # destinations first: a failure here loses nothing
            path = vault.BASE / folder / "Glossary.md"
            original, prefix, owners, rejected, entries = _read(path)
            extra, before = _extra(path), list(owners)
            for term, i, source, last in learned:
                if term.casefold() not in rejected:
                    _merge(entries, term, [i], source, last)
            for term, i in mine:
                k = term.casefold()
                rejected.pop(k, None)
                if k not in {t.casefold() for t in owners}:
                    owners.append(term)
                extra["added"][k] = sorted({*extra["added"].get(k, []), i})
            _write(path, original, _set_owners(prefix, before, owners), owners, rejected, entries, extra)
        for args in sources:
            _write(*args)
        if moving:
            promote_global()


def notice_rejections(folder):
    add_candidates(folder, [], "", "")


INBOX_POOL = 150   # words sent to the AI calls; Whisper takes fewer (see hotwords)


def _one(owner_terms, sources, blocked, rec_id, auto):
    """One glossary in use order: owner words, then learned words by rank."""
    combined = {}
    for source, rejected in sources:
        for k, e in source.items():
            if k not in blocked and k not in rejected and _eligible(e):
                _merge(combined, e["term"], e["ids"], e["source"], e["last"])
    owners = {}
    for term in owner_terms:
        owners.setdefault(term.casefold(), term)
    return list(owners.values()), [
        e["term"] for k, e in sorted(combined.items(), key=lambda item: _rank(item[1]))
        if k not in owners and (auto or e["source"] == "name") and any(i != rec_id for i in e["ids"])]


def _ranked(folder, rec_id=None, auto=True, text=None):
    """(terms in use order, how many are owner words, folders matched in `text`).

    The Inbox has no topic of its own, so it borrows every folder's glossary: its own and the
    general one first, then the folders taking turns, one word each, so a big folder cannot crowd
    out the rest. With `text` (a sample of the recording) the folders whose words are heard in it
    go first, most matches first."""
    pool = folder == cfg["inbox"]
    with LOCK:
        _, _, local, blocked, entries = _read(vault.BASE / folder / "Glossary.md")
        _, _, shared, global_blocked, promoted = _read(vault.BASE / "_Glossary.md")
        others = [(p.parent.name, *_read(p)[2:]) for p in sorted(vault.BASE.glob("*/Glossary.md"))
                  if pool and p.parent.name != folder]   # (name, owners, rejected, entries)
    owners, learned = _one(local + shared, [(promoted, global_blocked), (entries, {})], blocked, rec_id, auto)
    ranked, owned = owners + learned, {t.casefold() for t in owners}
    lead = []
    if others:
        lists = {}
        for name, mine, rejected, found in others:
            o, l = _one([t for t in mine if t.casefold() not in blocked], [(found, rejected)], blocked, rec_id, auto)
            owned |= {t.casefold() for t in o}
            lists[name] = o + l
        if text:
            said = heard({t for terms in lists.values() for t in terms}, text)
            score = {name: sum(t in said for t in terms) for name, terms in lists.items()}
            lead = sorted((n for n in lists if score[n]), key=lambda n: -score[n])
            lists = {n: sorted(t, key=lambda term: term not in said) for n, t in lists.items()}
        turns = [lists[n] for n in lists if n not in lead]
        ranked += [t for n in lead for t in lists[n]]
        ranked += [t for i in range(max(map(len, turns), default=0)) for terms in turns if i < len(terms)
                   for t in [terms[i]]]
        first = {}
        for t in ranked:
            first.setdefault(t.casefold(), t)
        ranked = list(first.values())[:INBOX_POOL]
    return ranked, sum(t.casefold() in owned for t in ranked), lead


def counts(folder):
    ranked, owners, _ = _ranked(folder)
    return len(ranked), len(ranked) - owners


def active(folder, rec_id=None, text=None):
    return _ranked(folder, rec_id, text=text)[0]


def leading(folder, text):
    """Folders whose words were heard in `text`, most matches first."""
    return _ranked(folder, text=text)[2]


def hotwords(folder, rec_id, tokenizer, text=None):
    terms = _ranked(folder, rec_id, cfg["auto_glossary_whisper"], text)[0]
    for n in range(1, len(terms) + 1):
        prompt = " " + ", ".join(terms[:n])
        if len(tokenizer.encode(prompt, add_special_tokens=False).ids) > 213:
            return ", ".join(terms[:n - 1]), terms[n - 1:]
    return ", ".join(terms), []
