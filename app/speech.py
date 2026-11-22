"""Audio -> words (faster-whisper) and audio -> speaker turns (sherpa-onnx), merged into utterances."""
import gc
import json
import os
import subprocess
import sysconfig
import tempfile
import threading
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from app.config import ROOT, cfg

# faster-whisper needs NVIDIA's runtime DLLs; pip puts them under site-packages/nvidia/*/bin.
for _bin in Path(sysconfig.get_paths()["purelib"]).glob("nvidia/*/bin"):
    os.environ["PATH"] = f"{_bin}{os.pathsep}{os.environ['PATH']}"
    os.add_dll_directory(str(_bin))

from faster_whisper import WhisperModel, decode_audio  # noqa: E402
from faster_whisper.feature_extractor import FeatureExtractor  # noqa: E402

_model: tuple[str, WhisperModel] | None = None


def load_audio(path: Path):
    return decode_audio(str(path), sampling_rate=16000)  # PyAV; no ffmpeg binary needed


class _BlockFeatures(FeatureExtractor):
    """Whisper's log-Mel features, with bounded FFT workspace on long recordings."""
    def __call__(self, waveform, padding=160, chunk_length=None):
        if len(waveform) <= self.n_samples:
            return super().__call__(waveform, padding, chunk_length)
        if chunk_length is not None:
            self.n_samples = chunk_length * self.sampling_rate
            self.nb_max_frames = self.n_samples // self.hop_length
        samples = np.asarray(waveform, dtype=np.float32)
        half = self.n_fft // 2
        padded_length = len(samples) + padding
        # The upstream extractor drops the last FFT frame and clips against the full recording's peak.
        frames = (padded_length + 2 * half - self.n_fft) // self.hop_length
        mel = np.empty((len(self.mel_filters), frames), dtype=np.float32)
        window = np.hanning(self.n_fft + 1)[:-1].astype(np.float32)
        for start in range(0, frames, 3000):  # 30 seconds at Whisper's 10 ms hop
            end = min(start + 3000, frames)
            left = start * self.hop_length - half
            right = (end - 1) * self.hop_length + self.n_fft - half
            block = samples[max(0, left):right]
            if right > len(samples):
                zeros = min(right, padded_length) - max(left, len(samples))
                if zeros > 0:
                    block = np.pad(block, (0, zeros))
            if left < 0 or right > padded_length:
                block = np.pad(block, (max(0, -left), max(0, right - padded_length)), mode="reflect")
            fft = self.stft(block, self.n_fft, self.hop_length, window=window, center=False, return_complex=True)
            mel[:, start:end] = self.mel_filters @ (np.abs(fft.astype(np.complex64, copy=False)) ** 2)
        np.maximum(mel, 1e-10, out=mel)
        np.log10(mel, out=mel)
        np.maximum(mel, mel.max() - 8, out=mel)
        mel += 4
        mel /= 4
        return mel


def _whisper(name: str) -> WhisperModel:
    global _model
    if _model is None or _model[0] != name:
        _model = None
        gc.collect()  # free the previous model's VRAM before loading another (8 GB card)
        model = WhisperModel(name, device="cuda", compute_type=cfg["whisper_compute_type"])
        model.feature_extractor = _BlockFeatures(**model.feat_kwargs)
        _model = (name, model)
    return _model[1]


def transcribe(audio, model: str, hotwords: str | None = None, on_progress=None) -> tuple[list[dict], str]:
    """Returns ([{s, e, w}], language).

    Language is detected once per file. Tested on an Italian->English->Italian splice: English
    passages still come out in English, and per-segment detection (multilingual=True) did not
    improve them while perturbing Italian output, so it stays off.
    """
    segments, info = _whisper(model).transcribe(
        audio, language=None, beam_size=5, word_timestamps=True,
        hotwords=hotwords or None,
        condition_on_previous_text=False, no_speech_threshold=0.6, log_prob_threshold=-1.0,
        compression_ratio_threshold=2.4, repetition_penalty=1.1,
        vad_filter=True,
        vad_parameters=dict(threshold=0.35, min_silence_duration_ms=500, speech_pad_ms=300,
                            min_speech_duration_ms=250),
    )
    total = max(len(audio) / 16000.0, 1.0)
    words = []
    for seg in segments:
        words.extend({"s": round(w.start, 2), "e": round(w.end, 2), "w": w.word} for w in (seg.words or []))
        if on_progress:
            on_progress(min(1.0, seg.end / total))
    return words, info.language


def samples(audio, n: int = 4, seconds: int = 45):
    """A few slices spread through the recording (openings are often small talk), joined."""
    w = seconds * 16000
    if len(audio) <= n * w:
        return audio
    return np.concatenate([audio[int(len(audio) * (i + 0.5) / n) - w // 2:][:w] for i in range(n)])


def transcribe_parakeet(audio, on_progress=None) -> list[dict]:
    """Second opinion for the ensemble: NVIDIA Parakeet TDT v3 (ONNX). Returns [{s, e, w}]."""
    global _model
    _model = None
    gc.collect()  # Whisper and Parakeet do not fit in 8 GB together
    import onnx_asr
    import onnxruntime as ort
    ort.preload_dlls()
    asr = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3", str(ROOT / cfg["parakeet_dir"]),
                              providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
    asr = asr.with_vad(onnx_asr.load_vad("silero")).with_timestamps()
    words: list[dict] = []
    total = max(len(audio) / 16000.0, 1.0)
    for seg in asr.recognize(audio, sample_rate=16000):
        if on_progress:
            on_progress(min(1.0, seg.start / total))
        first = True
        for tok, ts in zip(seg.tokens or [], seg.timestamps or []):
            t = round(seg.start + ts, 2)
            if first or tok.startswith(" "):
                words.append({"s": t, "e": t, "w": tok if tok.startswith(" ") else " " + tok})
            else:
                words[-1]["w"] += tok
                words[-1]["e"] = t
            first = False
    del asr
    gc.collect()
    return words


def diarize(audio, num_speakers: int = 0, log=lambda m: None) -> dict:
    """Turns, overlap intervals and embeddings by speaker index. Zero count lets the model decide.

    pyannote (GPU, own environment) when it is installed; otherwise, or if it fails, the built-in
    sherpa-onnx path. Both run outside this process: sherpa-onnx keeps Python's GIL for minutes,
    which froze the dashboard.
    """
    worker_py = ROOT / ".venv-pyannote/Scripts/python.exe"
    if cfg["diar_engine"] == "pyannote" and worker_py.exists():
        global _model
        _model = None
        gc.collect()  # free Whisper's VRAM before loading pyannote (8 GB card)
        # About 2 s per minute of audio normally; half the recording's length means something is wrong.
        limit = max(300, int(len(audio) / 16000 / 2))
        with tempfile.TemporaryDirectory() as tmp:
            np.save(f"{tmp}/audio.npy", audio)
            on_progress = getattr(log, "progress", None)
            # stderr goes to a file: a full pipe nobody reads would stall the worker
            with open(f"{tmp}/err.txt", "w+", encoding="utf-8", errors="replace") as err:
                proc = subprocess.Popen([str(worker_py), str(ROOT / "app/pyannote_worker.py"), f"{tmp}/audio.npy",
                                         f"{tmp}/turns.json"] + ([str(num_speakers)] if num_speakers else []),
                                        stdout=subprocess.PIPE, stderr=err, text=True, errors="replace",
                                        creationflags=_LOW_PRIORITY | getattr(subprocess, "CREATE_NO_WINDOW", 0))
                timer = threading.Timer(limit, proc.kill)
                timer.start()
                try:
                    for line in proc.stdout:   # "progress 0.42" lines from the worker's pyannote hook
                        if on_progress and line.startswith("progress "):
                            on_progress(float(line.split()[1]))
                    proc.wait()
                finally:
                    timed_out = not timer.is_alive() and proc.returncode != 0
                    timer.cancel()
                    if proc.poll() is None:   # this side failed: never leave the GPU worker running
                        proc.kill()
                        proc.wait()
                err.seek(0)
                error = f"no result after {limit // 60} minutes" if timed_out else err.read().strip()[-200:]
            if proc.returncode == 0:
                data = json.loads(Path(f"{tmp}/turns.json").read_text(encoding="utf-8"))
                # keep_all: pyannote's count needed no sliver clean-up on the test recordings, and
                # dropping short speakers would hand a brief participant's words to someone else
                turns = tidy_turns(data["turns"], keep_all=True)
                rank = {old[2]: new[2] for old, new in zip(data["turns"], turns)}
                # Keep voices present only in overlapping speech, too.
                for i in range(len(data["labels"])):
                    if i not in rank:
                        rank[i] = len(rank)
                return {"engine": "pyannote", "turns": turns,
                        "overlap": overlapping(data["overlap_turns"]),
                        "embeddings": {rank[i]: vector for i, vector in enumerate(data["embeddings"])}}
        log(f"pyannote failed, using the built-in speaker model (slower): {error}")
    with ProcessPoolExecutor(1, initializer=_lower_priority) as pool:
        return pool.submit(_diarize, audio, num_speakers).result()


_LOW_PRIORITY = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)


def _lower_priority() -> None:
    """Speaker work yields the CPU to the owner's apps."""
    if _LOW_PRIORITY:
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.c_void_p(-1), _LOW_PRIORITY)  # -1: this process


def _diarize(audio, num_speakers: int) -> dict:
    raw = raw_turns(audio)
    prints = voice_prints(audio, raw)
    merged = merge_voices(raw, prints, cfg["diar_same_voice"], num_speakers)
    turns = tidy_turns(merged, keep_all=bool(num_speakers))
    # merge_voices already absorbs slivers, so tidy preserves the remaining turn order.
    mapping = {old[2]: new[2] for old, new in zip(raw, turns, strict=True)}
    embeddings = {}
    for spk in set(mapping.values()):
        # shortcut: pool cluster vectors by talk time; re-extract merged audio if matching needs it.
        vector = sum(prints[old][0] * prints[old][1] for old in mapping if mapping[old] == spk)
        embeddings[spk] = (vector / np.linalg.norm(vector)).tolist()
    return {"engine": "sherpa", "turns": turns, "overlap": [], "embeddings": embeddings}


def overlapping(turns) -> list[list[float]]:
    """Union of intervals with at least two distinct active voices."""
    events = sorted((t, spk, delta) for s, e, spk in turns if e > s
                    for t, delta in ((s, 1), (e, -1)))
    active, spans, previous = {}, [], 0.0
    for t, spk, delta in events:
        if len(active) >= 2 and t > previous:
            s, e = round(previous, 2), round(t, 2)
            if e > s:
                if spans and s <= spans[-1][1]:
                    spans[-1][1] = e
                else:
                    spans.append([s, e])
        active[spk] = active.get(spk, 0) + delta
        if not active[spk]:
            del active[spk]
        previous = t
    return spans


def raw_turns(audio) -> list[tuple[float, float, int]]:
    """sherpa-onnx's own clustering. It over-splits: one voice ends up in several clusters."""
    import sherpa_onnx
    sd = sherpa_onnx.OfflineSpeakerDiarization(sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=str(ROOT / cfg["diar_segmentation"])),
            num_threads=cfg["diar_threads"]),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(ROOT / cfg["diar_embedding"]), num_threads=cfg["diar_threads"]),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=cfg["diar_threshold"]),
        min_duration_on=0.3, min_duration_off=0.5))
    return [(r.start, r.end, r.speaker) for r in sd.process(audio).sort_by_start_time()]


def voice_prints(audio, turns: list[tuple[float, float, int]], max_s: int = 90) -> dict[int, tuple[float, np.ndarray]]:
    """{cluster: (talk seconds, unit voice embedding of its pooled audio, longest turns first)}.
    An embedding of a minute of pooled speech is far steadier than the per-segment ones sherpa clusters."""
    import sherpa_onnx
    ex = sherpa_onnx.SpeakerEmbeddingExtractor(sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model=str(ROOT / cfg["diar_embedding"]), num_threads=cfg["diar_threads"]))
    out = {}
    for spk in {t[2] for t in turns}:
        mine = sorted((t for t in turns if t[2] == spk), key=lambda t: t[0] - t[1])
        pooled = np.concatenate([audio[int(s * 16000):int(e * 16000)] for s, e, _ in mine])[:max_s * 16000]
        st = ex.create_stream()
        st.accept_waveform(16000, pooled)
        st.input_finished()
        v = np.array(ex.compute(st))
        out[spk] = (sum(e - s for s, e, _ in mine), v / np.linalg.norm(v))
    return out


def merge_voices(turns, prints: dict[int, tuple[float, np.ndarray]], same: float, k: int = 0):
    """Join clusters that are the same voice: repeatedly merge the two most similar groups until
    none are alike (cosine < `same`) or, with a fixed count, until k remain. A leftover group that
    is only a sliver (under 15 s and 2% of the speech) joins the voice it resembles most."""
    groups = [([spk], t, v) for spk, (t, v) in prints.items()]  # (clusters, talk seconds, embedding)
    floor = max(15.0, 0.02 * sum(g[1] for g in groups))
    while len(groups) > max(k, 1):
        pairs = [(float(groups[i][2] @ groups[j][2]), i, j) for i in range(len(groups)) for j in range(i)]
        slivers = [p for p in pairs if min(groups[p[1]][1], groups[p[2]][1]) < floor]
        sim, a, b = max(slivers or pairs)
        if not slivers and not k and sim < same:
            break
        ga, gb = groups[a], groups[b]
        v = ga[2] * ga[1] + gb[2] * gb[1]  # talk-time weighted, so a sliver barely moves a voice
        groups = [g for i, g in enumerate(groups) if i not in (a, b)] + [(ga[0] + gb[0], ga[1] + gb[1], v / np.linalg.norm(v))]
    voice = {spk: i for i, g in enumerate(groups) for spk in g[0]}
    return [(s, e, voice[spk]) for s, e, spk in turns]


def tidy_turns(turns: list[tuple[float, float, int]], keep_all: bool = False) -> list[tuple[float, float, int]]:
    """Drop 'speakers' that are only slivers (under 15 s and 2% of the speech) unless the count
    was fixed by the user, and renumber so that speaker 0 talks most."""
    total: dict[int, float] = {}
    for s, e, spk in turns:
        total[spk] = total.get(spk, 0.0) + e - s
    floor = 0 if keep_all else max(15.0, 0.02 * sum(total.values()))
    order = [spk for spk, t in sorted(total.items(), key=lambda kv: -kv[1]) if t >= floor] or list(total)
    rank = {spk: i for i, spk in enumerate(order)}
    return [(s, e, rank[spk]) for s, e, spk in turns if spk in rank]


def utterances(words: list[dict], turns: list, max_gap: float = 2.0,
               overlap=(), fixes=()) -> list[dict]:
    """Assign speakers phrase by phrase, then group into paragraphs [{s, e, spk, text}].

    A phrase (words up to punctuation or a pause) goes to the speaker whose turns overlap it
    most, so a slightly late or early turn boundary no longer cuts a sentence in half.
    """
    def fixed(word):
        midpoint = (word["s"] + word["e"]) / 2
        return next((f["spk"] for f in reversed(fixes) if f["s"] <= midpoint < f["e"]), None)

    phrases: list[list[dict]] = []
    for w in words:
        prev = phrases[-1][-1] if phrases else None
        if (prev is None or w["s"] - prev["e"] > 0.6
                or prev["w"].rstrip().endswith((".", "?", "!", ",", ";", ":")) or fixed(w) != fixed(prev)):
            phrases.append([])
        phrases[-1].append(w)

    out: list[dict] = []
    i = 0
    for ph in phrases:
        s0, e0 = ph[0]["s"], ph[-1]["e"]
        while i < len(turns) - 1 and turns[i][1] < s0:
            i += 1
        score = {}
        for s, e, spk in turns[max(0, i - 2):]:
            if s > e0 + 5:
                break
            # total overlap with the phrase's words; if none, minus the distance to the turn
            ov = sum(max(0.0, min(e, w["e"]) - max(s, w["s"])) for w in ph) or (min(e, e0) - max(s, s0))
            score[spk] = max(score.get(spk, -1e9), ov) if ov <= 0 else max(score.get(spk, 0), 0) + ov
        best = fixed(ph[0]) or (max(score, key=score.get) if score else "S1")
        flagged = bool(sum(max(0, min(e0, e) - max(s0, s)) for s, e in overlap) >= 0.5)
        text = "".join(w["w"] for w in ph)
        # same speaker continues, unless there is a pause or the paragraph got long (break at a
        # sentence end after 25 s, anywhere after 60 s) so timestamps and highlights stay close
        long = out and (s0 - out[-1]["s"] > 60 or
                        (s0 - out[-1]["s"] > 25 and out[-1]["text"].rstrip().endswith((".", "?", "!"))))
        if (out and out[-1]["spk"] == best and out[-1]["overlap"] == flagged
                and s0 - out[-1]["e"] <= max_gap and not long):
            out[-1]["text"] += text
            out[-1]["e"] = e0
        else:
            out.append({"s": s0, "e": e0, "spk": best, "text": text.lstrip(), "overlap": flagged})
    return out
