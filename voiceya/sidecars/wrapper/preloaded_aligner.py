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

            # Re-use MFA's on-disk L.fst cache — same directory convention
            # the align_one CLI uses, so any prior `mfa align_one` run gave
            # us a warm cache.  Cold start (fresh image) compiles + writes.
            cache_dir = config.TEMPORARY_DIRECTORY.joinpath(
                "extracted_models", "dictionary", Path(dictionary_path).stem,
            )
            cache_dir.mkdir(parents=True, exist_ok=True)
            l_fst = cache_dir / "L.fst"
            l_align = cache_dir / "L_align.fst"
            words_txt = cache_dir / "words.txt"
            phones_txt = cache_dir / "phones.txt"

            cache_hit = l_fst.exists() and not config.CLEAN
            if cache_hit:
                lexicon_compiler.load_l_from_file(l_fst)
                lexicon_compiler.load_l_align_from_file(l_align)
                lexicon_compiler.word_table = pywrapfst.SymbolTable.read_text(words_txt)
                lexicon_compiler.phone_table = pywrapfst.SymbolTable.read_text(phones_txt)
            else:
                lexicon_compiler.load_pronunciations(dictionary_path)
                lexicon_compiler.create_fsts()
                lexicon_compiler.fst.write(str(l_fst))
                lexicon_compiler.align_fst.write(str(l_align))
                lexicon_compiler.word_table.write_text(words_txt)
                lexicon_compiler.phone_table.write_text(phones_txt)
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
        import tempfile  # noqa: PLC0415

        from kalpy.fstext.lexicon import HierarchicalCtm  # noqa: PLC0415
        from kalpy.utterance import (  # noqa: PLC0415
            Segment,
        )
        from kalpy.utterance import (
            Utterance as KalpyUtterance,
        )
        from montreal_forced_aligner.corpus.classes import FileData  # noqa: PLC0415
        from montreal_forced_aligner.online.alignment import (  # noqa: PLC0415
            tokenize_utterance_text,
        )

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
                normalized = tokenize_utterance_text(
                    utt_meta.text, self._lexicon_compiler, self._tokenizer, None,
                    language=self._acoustic_model.language,
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

    def warmup(self) -> None:
        """Run one tiny alignment to pay the first-call JIT/init cost upfront.

        On a fresh container the first ``align_utterance`` call takes
        several seconds even though subsequent calls are < 100 ms — Kaldi
        binds pay a one-time initialisation cost on the first invocation.
        Running this synchronously at module load moves that tax off the
        user's first request.

        Best-effort: any error is swallowed.  A silent warmup wav matches
        the aligner's SR expectations; a single "the" utterance gives the
        aligner something real to bind against (pure silence skips the
        expensive retry_beam path that production audio can hit).
        """
        import tempfile  # noqa: PLC0415
        import wave  # noqa: PLC0415
        from pathlib import Path  # noqa: PLC0415

        try:
            with tempfile.TemporaryDirectory() as tmp:
                wav_path = Path(tmp) / "warmup.wav"
                with wave.open(str(wav_path), "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)  # 16-bit
                    w.setframerate(16000)
                    # 1 s of near-silence — a single zero sample repeated
                    # is fine; we're exercising code paths, not measuring
                    # alignment quality.
                    w.writeframes(b"\x00\x00" * 16000)
                grid_path = Path(tmp) / "warmup.TextGrid"
                # Use a single OOV-safe word; dictionary always has "the".
                self.align_one(wav_path, "the", grid_path)
            logger.info("preloaded aligner [%s] warmup ok", self.lang)
        except Exception as exc:  # pragma: no cover — best-effort
            logger.info(
                "preloaded aligner [%s] warmup skipped (%s) — "
                "first real request will pay the init cost instead",
                self.lang, exc,
            )
