"""Confirmed voice samples and cross-recording suggestions."""
import json
import math
from threading import Lock

from app import vault

_lock = Lock()


def _read():
    try:
        return json.loads((vault.BASE / "_Voices.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def _change(remove, add):
    with _lock:
        people = _read()
        before = json.dumps(people, ensure_ascii=False)
        for name, rec_id, spk in remove:
            for engine, samples in list(people.get(name, {}).items()):
                kept = [s for s in samples if s["rec_id"] != rec_id or
                        (spk is not None and s.get("spk") != spk)]
                if kept:
                    people[name][engine] = kept
                else:
                    del people[name][engine]
            if name in people and not people[name]:
                del people[name]
        for name, vector, engine, rec_id, spk in add:
            if not vector or not all(math.isfinite(v) for v in vector) or not math.hypot(*vector):
                continue
            samples = people.setdefault(name, {}).setdefault(engine, [])
            samples[:] = [s for s in samples if (s["rec_id"], s.get("spk")) != (rec_id, spk)][-19:]
            samples.append({"rec_id": rec_id, "spk": spk, "vector": vector})
        after = json.dumps(people, ensure_ascii=False, allow_nan=False)
        if after != before:
            vault._atomic_text(vault.BASE / "_Voices.json", after)


def enrol(name, vector, engine, rec_id):
    _change([], [(name, vector, engine, rec_id, None)])


def forget(name, rec_id):
    _change([(name, rec_id, None)], [])


def update_names(rec, changed):
    """Replace evidence only for affected names, in one store write."""
    if not changed:
        return
    diar = rec["diarization"]
    _change([(old, rec["id"], spk) for spk, old in changed.items() if old],
            [(speaker["name"], diar["embeddings"][spk], diar["engine"], rec["id"], spk)
             for spk in changed if (speaker := rec["speakers"][spk])["name"]
             and spk in diar["embeddings"] and not speaker.get("merged_into")])


def _samples(engine):
    return {name: engines[engine] for name, engines in _read().items() if engine in engines}


def _templates(people, exclude):
    means = {}
    for name, samples in people.items():
        vectors = [s["vector"] for s in samples if s["rec_id"] != exclude]
        if vectors:
            means[name] = [math.fsum(values) / len(vectors) for values in zip(*vectors, strict=True)]
    return means


def _best(vector, templates):
    norm = math.hypot(*vector)
    scores = [(max(-1., min(1., math.fsum((a / norm) * (b / other)
                                        for a, b in zip(vector, mean)))), name)
              for name, mean in templates.items()
              if norm and len(vector) == len(mean) and (other := math.hypot(*mean))]
    return max(scores, default=(-math.inf, None))


def _needed(people):
    return max(0, 3 - sum(len({s["rec_id"] for s in samples}) >= 2 for samples in people.values()))


def needed(engine):
    return _needed(_samples(engine))


def _threshold(people):
    if _needed(people):
        return None
    templates, wrong, total = {}, [], 0
    for name, samples in people.items():
        for sample in samples:
            rec_id = sample["rec_id"]
            if rec_id not in templates:
                templates[rec_id] = _templates(people, rec_id)
            score, match = _best(sample["vector"], templates[rec_id])
            if match is not None and match != name:
                wrong.append(score)
            total += 1
    allowed = total // 20
    return sorted(wrong, reverse=True)[allowed] if len(wrong) > allowed else -1.


def threshold(engine):
    return _threshold(_samples(engine))


def match(rec, templates, cutoff):
    """Keep the strongest claim for each proposed person."""
    embeddings = rec["diarization"]["embeddings"]
    used = {s["name"] for s in rec["speakers"].values() if s["name"] and not s.get("merged_into")}
    winners = {}
    for spk, vector in embeddings.items():
        speaker = rec["speakers"][spk]
        if speaker["name"] or speaker.get("merged_into") or speaker.get("voice_refused"):
            continue
        score, name = _best(vector, templates)
        if score > cutoff and name not in used and (name not in winners or score > winners[name][1]):
            winners[name] = (spk, score)
    return {spk: {"name": name, "score": score} for name, (spk, score) in winners.items()}


def suggest(rec):
    people = _samples(rec["diarization"].get("engine"))
    cutoff = _threshold(people)
    return {} if cutoff is None else match(rec, _templates(people, rec["id"]), cutoff)
