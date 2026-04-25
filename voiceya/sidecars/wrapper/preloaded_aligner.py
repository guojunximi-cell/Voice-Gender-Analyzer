"""Preloaded MFA alignment via kalpy — bypasses the 27 s MFA CLI startup.

The ``mfa align`` CLI re-loads the acoustic model, re-compiles the lexicon
FST, and re-initialises its SQLAlchemy/Postgres-like state on every call.
For the sidecar's use case (many short requests on a known language pair)
that startup cost is ~90% of the wall time.

This module takes the same low-level kalpy path that MFA's own ``align_one``
CLI uses, but constructs the heavy objects ONCE at module import so every
subsequent alignment call is tens of milliseconds instead of ~40 s:

    - ``AcousticModel``             loaded from acoustic_model.zip
    - ``LexiconCompiler`` + L.fst   compiled (or loaded from MFA's on-disk
                                    cache under ``TEMPORARY_DIRECTORY/
                                    extracted_models/dictionary/<stem>/``)
    - ``SimpleTokenizer``           shares lexicon's word table
    - ``KalpyAligner``              wraps the acoustic model + lexicon

All four are kept alive for the lifetime of the uvicorn worker.

Correctness was verified empirically (POC on a 15.7 s English clip): the
kalpy TextGrid is byte-for-byte identical to the single-block MFA CLI
output for the same audio, modulo number formatting ("8" vs "8.0") and
silence labels (kalpy uses "<eps>", MFA uses ""; we normalise during
post-processing).  On short trimmed clips kalpy is actually *more* accurate
than MFA CLI because it skips MFA's per-utterance speaker-adaptation pass
which tends to overfit on short data.

Usage:

    aligner = PreloadedAligner.load("en", acoustic_path, dictionary_path)
    with tempfile.NamedTemporaryFile(...) as txt, ... as grid:
        aligner.align_one(wav_path, "hello world", grid)
        # grid now holds a long-format TextGrid ready for the Praat script.

Fallback: ``PreloadedAligner.load`` returns ``None`` if kalpy/MFA imports
fail or the models aren't resolvable — caller keeps the subprocess MFA
path for that language.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

logger = logging.getLogger("engine_c.preloaded_aligner")


# Beam settings mirror the sidecar's fast-mode knobs (see wrapper/main.py).
# Narrower than upstream MFA's 100/400 because our inputs are clean studio
# voice — MFA auto-falls-back to retry_beam if the first pass drops frames.
_DEFAULT_BEAM = 50
_DEFAULT_RETRY_BEAM = 200


class PreloadedAligner:
    """Holds preloaded kalpy + MFA objects for one (lang, model) pair."""

    def __init__(
        self,
        lang: str,
        acoustic_model,
        lexicon_compiler,
        tokenizer,
        kalpy_aligner,
    ) -> None:
        self.lang = lang
        self._acoustic_model = acoustic_model
        self._lexicon_compiler = lexicon_compiler
        self._tokenizer = tokenizer
        self._kalpy_aligner = kalpy_aligner
        # KalpyAligner state isn't documented as thread-safe; keep a process
        # -wide mutex so concurrent align_one calls serialise at this layer.
        # The sidecar is single-worker today so this only guards against
        # future asyncio.to_thread() fan-out within one request.
        self._lock = threading.Lock()
        # Lazy cmvn computer — kalpy's CmvnComputer() is cheap to re-create
        # per request, but keeping one saves a few µs and matches the
        # align_one CLI's pattern.
        from kalpy.feat.cmvn import CmvnComputer
        self._cmvn_computer = CmvnComputer()

    @classmethod
    def load(
        cls,
        lang: str,
        acoustic_model_path: Path,
        dictionary_path: Path,
        *,
        beam: int = _DEFAULT_BEAM,
        retry_beam: int = _DEFAULT_RETRY_BEAM,
    ) -> "PreloadedAligner | None":
        """Construct + return a preloaded aligner, or None on any failure.

        Safe to call at module import: catches every exception and logs;
        returning None signals the caller to fall back to subprocess MFA
        for this language.
        """
        try:
            # Deferred imports — kalpy + MFA pull in heavy deps (Kaldi
            # bindings, spaCy, SQLAlchemy) that we don't want at sidecar
            # startup unless alignment is actually going to be used.
            import time  # noqa: PLC0415

            import pywrapfst  # noqa: PLC0415
            from kalpy.aligner import KalpyAligner  # noqa: PLC0415
            from kalpy.fstext.lexicon import LexiconCompiler  # noqa: PLC0415
            from montreal_forced_aligner import config  # noqa: PLC0415
            from montreal_forced_aligner.data import (  # noqa: PLC0415
                BRACKETED_WORD,
                CUTOFF_WORD,
                LAUGHTER_WORD,
                OOV_WORD,
            )
            from montreal_forced_aligner.dictionary.mixins import (  # noqa: PLC0415
                DEFAULT_BRACKETS,
                DEFAULT_CLITIC_MARKERS,
                DEFAULT_COMPOUND_MARKERS,
                DEFAULT_PUNCTUATION,
                DEFAULT_WORD_BREAK_MARKERS,
            )
            from montreal_forced_aligner.models import AcousticModel  # noqa: PLC0415
            from montreal_forced_aligner.tokenization.simple import (  # noqa: PLC0415
                SimpleTokenizer,
            )

            t0 = time.perf_counter()
            acoustic_model = AcousticModel(acoustic_model_path)
            t_a = time.perf_counter()

            p = acoustic_model.parameters
            lexicon_compiler = LexiconCompiler(
                disambiguation=False,
                silence_probability=p["silence_probability"],
                initial_silence_probability=p["initial_silence_probability"],
                final_silence_correction=p["final_silence_correction"],
                final_non_silence_correction=p["final_non_silence_correction"],
                silence_phone=p["optional_silence_phone"],
                oov_phone=p["oov_phone"],
                position_dependent_phones=p["position_dependent_phones"],
                phones=p["non_silence_phones"],
                ignore_case=True,
            )

            # MFA's pretrained dictionaries can contain phones that the
            # shipped acoustic model doesn't know — mandarin_mfa's dict
            # uses tone variants like ``i˥˥`` / ``a˨`` / ``aj˦`` that
            # never appear in the model's phones.txt (which stops at
            # ``i˥``, ``a˥``, ``aj˥``, etc.).  MFA's full ``align`` CLI
            # handles this via PretrainedAligner's excluded_phones logic
            # — it drops pronunciations whose phones aren't in the model.
            # ``align_one`` doesn't filter, which is why it dies with
            # ``ContextFst: invalid ilabel supplied: 161`` on any real
            # Chinese transcript.  We replicate the filter here.
            model_phones_path = acoustic_model.phone_symbol_path
            model_phone_table = pywrapfst.SymbolTable.read_text(str(model_phones_path))
            valid_phones: set[str] = set()
            for i in range(model_phone_table.num_symbols()):
                sym = model_phone_table.find(i)
                name = sym.decode() if isinstance(sym, bytes) else sym
                if name:
                    valid_phones.add(name)
            # pronunciation dictionary helpers (optional silence phone, oov
            # phone, disambig syms, etc.) — keep <eps> ids reachable too.
            valid_phones.add(p["optional_silence_phone"])
            valid_phones.add(p["oov_phone"])

            # Cache dir keyed by dict stem + model-phones fingerprint so a
            # refresh of either side invalidates the compiled L.fst.
            cache_key = f"{Path(dictionary_path).stem}-{model_phones_path.stat().st_size}"
            cache_dir = config.TEMPORARY_DIRECTORY.joinpath(
                "extracted_models", "dictionary", cache_key,
            )
            cache_dir.mkdir(parents=True, exist_ok=True)
            l_fst = cache_dir / "L.fst"
            l_align = cache_dir / "L_align.fst"
            words_txt = cache_dir / "words.txt"
            phones_txt = cache_dir / "phones.txt"
            filtered_dict = cache_dir / "filtered.dict"

            # Pre-filter the dict (write once, reuse across container
            # restarts).  Format preserved line-for-line so MFA's own
            # parse_dictionary_file keeps working.
            if not filtered_dict.exists():
                import tempfile  # noqa: PLC0415
                kept = 0
                skipped = 0
                with (
                    open(dictionary_path, encoding="utf-8") as src,
                    tempfile.NamedTemporaryFile(
                        "w", encoding="utf-8", delete=False,
                        dir=cache_dir, suffix=".dict.tmp",
                    ) as tmp,
                ):
                    for line in src:
                        cols = line.rstrip("\n").split("\t")
                        if len(cols) < 2:
                            tmp.write(line)
                            kept += 1
                            continue
                        # mandarin_mfa dict: word<tab>p1<tab>p2<tab>p3<tab>p4<tab>phones
                        # english_us_arpa dict: word<tab>phones (2 cols)
                        pron = cols[-1].split()
                        if set(pron) - valid_phones:
                            skipped += 1
                            continue
                        tmp.write(line)
                        kept += 1
                    tmp_path = Path(tmp.name)
                tmp_path.rename(filtered_dict)
                logger.info(
                    "preloaded aligner [%s] filtered dict: kept %d, skipped %d "
                    "(phones not in acoustic model)",
                    lang, kept, skipped,
                )

            # Critical: pre-populate phone_table from the model so
            # load_pronunciations' add_symbol calls for known phones
            # return existing IDs (idempotent) rather than appending.
            lexicon_compiler.phone_table = pywrapfst.SymbolTable.read_text(
                str(model_phones_path),
            )

            cache_hit = l_fst.exists() and not config.CLEAN
            if cache_hit:
                lexicon_compiler.load_l_from_file(l_fst)
                lexicon_compiler.load_l_align_from_file(l_align)
                lexicon_compiler.word_table = pywrapfst.SymbolTable.read_text(str(words_txt))
                # phone_table already set above from the model.
            else:
                lexicon_compiler.load_pronunciations(filtered_dict)
                lexicon_compiler.create_fsts()
                lexicon_compiler.fst.write(str(l_fst))
                lexicon_compiler.align_fst.write(str(l_align))
                lexicon_compiler.word_table.write_text(str(words_txt))
                lexicon_compiler.phone_table.write_text(str(phones_txt))
                lexicon_compiler.clear()
            t_l = time.perf_counter()

            tokenizer = SimpleTokenizer(
                word_table=lexicon_compiler.word_table,
                word_break_markers=DEFAULT_WORD_BREAK_MARKERS,
                punctuation=DEFAULT_PUNCTUATION,
                clitic_markers=DEFAULT_CLITIC_MARKERS,
                compound_markers=DEFAULT_COMPOUND_MARKERS,
                brackets=DEFAULT_BRACKETS,
                laughter_word=LAUGHTER_WORD,
                oov_word=OOV_WORD,
                bracketed_word=BRACKETED_WORD,
                cutoff_word=CUTOFF_WORD,
                ignore_case=True,
            )

            kalpy_aligner = KalpyAligner(
                acoustic_model, lexicon_compiler,
                beam=beam, retry_beam=retry_beam,
                acoustic_scale=0.1, transition_scale=1.0,
                self_loop_scale=0.1, boost_silence=1.0,
            )
            t_k = time.perf_counter()

            logger.info(
                "preloaded aligner [%s] ready: acoustic=%.2fs  "
                "lexicon=%.2fs (cached=%s)  kalpy=%.2fs  TOTAL=%.2fs",
                lang, t_a - t0, t_l - t_a, cache_hit, t_k - t_l, t_k - t0,
            )
            return cls(lang, acoustic_model, lexicon_compiler, tokenizer, kalpy_aligner)
        except Exception as exc:
            logger.warning(
                "preloaded aligner [%s] init failed — falling back to subprocess MFA: %s",
                lang, exc,
            )
            logger.debug("preloaded aligner init trace", exc_info=True)
            return None

    def align_one(
        self,
        wav_path: Path,
        transcript: str,
        textgrid_out: Path,
    ) -> None:
        """Align one clip; write a long-format TextGrid to ``textgrid_out``.

        Raises on alignment failure (beam too narrow, OOV, kalpy bug) so
        the caller can fall back to subprocess MFA for that one chunk.
        """
        # Deferred imports — same reason as load().
        import re  # noqa: PLC0415
        import tempfile  # noqa: PLC0415

        from kalpy.fstext.lexicon import HierarchicalCtm  # noqa: PLC0415
        from kalpy.utterance import (  # noqa: PLC0415
            Segment,
        )
        from kalpy.utterance import (
            Utterance as KalpyUtterance,
        )
        from montreal_forced_aligner.corpus.classes import FileData  # noqa: PLC0415
        from montreal_forced_aligner.data import Language  # noqa: PLC0415
        from montreal_forced_aligner.online.alignment import (  # noqa: PLC0415
            tokenize_utterance_text,
        )

        # zh: match the vendored preprocessing.process convention of
        # turning each hanzi into its own whitespace-separated token so
        # the ``mandarin_mfa`` dictionary's per-character entries resolve.
        # Without this the whole transcript looks like one giant OOV word.
        # en: pass through — SimpleTokenizer handles whitespace splitting.
        if self.lang == "zh":
            transcript = " ".join(re.findall(r"[一-鿿]", transcript))

        # MFA's FileData wants a text file on disk.  Use a tempfile in a
        # sibling dir so we don't clobber a ``<stem>.txt`` the caller may
        # already have written next to the wav (slice_chunks does).
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", encoding="utf-8",
            dir=wav_path.parent, delete=False,
        ) as tmp:
            tmp.write(transcript.strip() + "\n")
            txt_path = Path(tmp.name)

        try:
            file = FileData.parse_file(wav_path.stem, wav_path, txt_path, "", 0)
            utterances = []
            for utt_meta in file.utterances:
                seg = Segment(
                    str(wav_path), utt_meta.begin, utt_meta.end, utt_meta.channel,
                )
                # Force Language.unknown so tokenize_utterance_text takes the
                # 3-tuple SimpleTokenizer branch (``normalized, _, oovs``).
                # The "known language" branch expects a
                # ``generate_language_tokenizer`` instance that returns
                # 2-tuples — we intentionally use SimpleTokenizer everywhere
                # because zh is pre-segmented per hanzi above (matching the
                # vendored preprocessing.process convention) and en needs
                # nothing more than whitespace tokenisation.
                normalized = tokenize_utterance_text(
                    utt_meta.text, self._lexicon_compiler, self._tokenizer, None,
                    language=Language.unknown,
                )
                utt = KalpyUtterance(seg, normalized)
                utt.generate_mfccs(self._acoustic_model.mfcc_computer)
                utterances.append(utt)

            if not utterances:
                raise RuntimeError(
                    f"kalpy: no utterances parsed from {wav_path} (empty transcript?)"
                )

            cmvn = self._cmvn_computer.compute_cmvn_from_features(
                [u.mfccs for u in utterances],
            )
            file_ctm = HierarchicalCtm([])
            with self._lock:
                for utt in utterances:
                    utt.apply_cmvn(cmvn)
                    ctm = self._kalpy_aligner.align_utterance(utt)
                    file_ctm.word_intervals.extend(ctm.word_intervals)

            file_ctm.export_textgrid(
                textgrid_out,
                file_duration=file.wav_info.duration,
                output_format="long_textgrid",
            )
        finally:
            try:
                txt_path.unlink()
            except FileNotFoundError:
                pass

    def warmup(self) -> bool:
        """Align a realistic-ish transcript on silent audio to pay the
        kalpy/Kaldi first-call JIT tax so the user's first real request
        doesn't.

        Returns True on success, False on failure — informational only.
        Caller registers the aligner regardless; runtime kalpy errors fall
        back to subprocess MFA via ``_run_chunked_path``'s outer
        try/except, so a failed warmup no longer needs to gate
        registration.  Historical context: this used to gate registration
        because mandarin_mfa's phone-ID space collided with kalpy's
        ``CompileGraphFromText`` (``ContextFst: invalid ilabel``).  That
        bug is now routed around at the dict layer (``mandarin_china_mfa``
        + phone-inventory filter), so a silent-audio warmup failure is no
        longer a reliable "language broken" signal — zh's silent warmup
        in particular exhausts beam=50 without acoustic anchors despite
        real audio aligning fine.
        """
        import tempfile  # noqa: PLC0415
        import wave  # noqa: PLC0415
        from pathlib import Path  # noqa: PLC0415

        # 10+ tokens to push through a broad slice of the phone inventory.
        # zh: kept short — historically used for the mandarin_mfa phone-ID
        # collision check, but that's now resolved by routing zh dict to
        # ``mandarin_china_mfa`` (matches the v3 acoustic model's phone
        # set).  A long zh transcript on silent audio now exhausts beam=50
        # because the richer FST has too many candidate paths to explore
        # without acoustic anchors; a 2-hanzi warmup still pays the JIT
        # cost without that risk.
        warmup_transcript = {
            "en": "the quick brown fox jumps over a lazy dog again",
            "zh": "你好",
        }.get(self.lang, "the")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                wav_path = Path(tmp) / "warmup.wav"
                with wave.open(str(wav_path), "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)  # 16-bit
                    w.setframerate(16000)
                    # 3 s of silence — long enough that alignment has room
                    # to place every transcript token without retry_beam
                    # exhausting on the first call.
                    w.writeframes(b"\x00\x00" * 16000 * 3)
                grid_path = Path(tmp) / "warmup.TextGrid"
                self.align_one(wav_path, warmup_transcript, grid_path)
            logger.info("preloaded aligner [%s] warmup ok", self.lang)
            return True
        except Exception as exc:  # pragma: no cover — best-effort
            logger.warning(
                "preloaded aligner [%s] warmup FAILED: %s — kalpy still "
                "registered; first real request will pay the JIT tax instead",
                self.lang, exc,
            )
            return False
