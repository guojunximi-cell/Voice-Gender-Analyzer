# Marker file — makes hatchling treat voiceya/inaSpeechSegmenter/ as a
# subpackage so the vendored inaSpeechSegmenter tree is included in the
# built wheel (and therefore in `uv sync --no-editable` installs).
# Do not import anything here; the actual package lives one level down at
# voiceya/inaSpeechSegmenter/inaSpeechSegmenter/__init__.py.
