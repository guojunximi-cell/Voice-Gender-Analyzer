#!/usr/bin/praat --run

# voiceya patch (2026-05-01): adaptive formant ceiling.  Instead of a single
# 5000 Hz pass, sweep 5 ceilings inside one Praat process and emit all 15
# formant columns (3 formants × 5 ceilings) per phone into a separate
# "Multi-Ceiling-Formants:" section.  The Python wrapper picks the optimal
# ceiling per recording and synthesises the standard "Phonemes:" section
# downstream so phones.parse() stays unchanged.
#
# Output format compatible-superset of the original script: still emits
# "Words:" and "Phonemes:" sections (Phonemes uses 5000 Hz baseline so any
# unmodified consumer keeps current behaviour); adds the new section after.

form File
	sentence soundfile
	sentence textgrid
endform

Read from file... 'soundfile$'
sound$ = selected$("Sound")

Read from file... 'textgrid$'
textGrid$ = selected$("TextGrid")


# ---- Words section (unchanged) ----
appendInfoLine: "Words:"

select TextGrid 'textGrid$'
numberOfWords = Get number of intervals: 1

for i from 1 to numberOfWords
	select TextGrid 'textGrid$'
	word$ = Get label of interval: 1, i
	startTime = Get start point: 1, i
	endTime   = Get end point:   1, i

	appendInfoLine: startTime, "	", word$
endfor


# ---- Phone setup ----
select TextGrid 'textGrid$'
numberOfPhonemes = Get number of intervals: 2

select Sound 'sound$'
To Pitch: 0, 75, 600
pitchID = selected("Pitch")

# ---- 5 Formant objects, one per candidate ceiling ----
select Sound 'sound$'
To Formant (burg)... 0 5 4500 0.025 50
formantID_1 = selected("Formant")

select Sound 'sound$'
To Formant (burg)... 0 5 5000 0.025 50
formantID_2 = selected("Formant")

select Sound 'sound$'
To Formant (burg)... 0 5 5500 0.025 50
formantID_3 = selected("Formant")

select Sound 'sound$'
To Formant (burg)... 0 5 6000 0.025 50
formantID_4 = selected("Formant")

select Sound 'sound$'
To Formant (burg)... 0 5 6500 0.025 50
formantID_5 = selected("Formant")


# ---- Standard Phonemes section (5000 Hz baseline; preserves backward compat) ----
appendInfoLine: "Phonemes:"
for i from 1 to numberOfPhonemes
	select TextGrid 'textGrid$'
	phoneme$ = Get label of interval: 2, i

	startTime = Get start point: 2, i
	endTime   = Get end point:   2, i
	midpoint = startTime + (endTime - startTime) / 2

	select 'pitchID'
	f0 = Get value at time... midpoint Hertz Linear

	selectObject: formantID_2
	f1 = Get value at time... 1 midpoint Hertz Linear
	f2 = Get value at time... 2 midpoint Hertz Linear
	f3 = Get value at time... 3 midpoint Hertz Linear

	appendInfoLine: startTime, "	", phoneme$, "	", f0, "	", f1, "	", f2, "	", f3
endfor


# ---- Multi-Ceiling section (new) ----
appendInfoLine: "Multi-Ceiling-Formants:"
appendInfoLine: "# ceilings: 4500 5000 5500 6000 6500"
for i from 1 to numberOfPhonemes
	select TextGrid 'textGrid$'
	phoneme$ = Get label of interval: 2, i

	startTime = Get start point: 2, i
	endTime   = Get end point:   2, i
	midpoint = startTime + (endTime - startTime) / 2

	select 'pitchID'
	f0 = Get value at time... midpoint Hertz Linear

	selectObject: formantID_1
	a1 = Get value at time... 1 midpoint Hertz Linear
	a2 = Get value at time... 2 midpoint Hertz Linear
	a3 = Get value at time... 3 midpoint Hertz Linear

	selectObject: formantID_2
	b1 = Get value at time... 1 midpoint Hertz Linear
	b2 = Get value at time... 2 midpoint Hertz Linear
	b3 = Get value at time... 3 midpoint Hertz Linear

	selectObject: formantID_3
	c1 = Get value at time... 1 midpoint Hertz Linear
	c2 = Get value at time... 2 midpoint Hertz Linear
	c3 = Get value at time... 3 midpoint Hertz Linear

	selectObject: formantID_4
	d1 = Get value at time... 1 midpoint Hertz Linear
	d2 = Get value at time... 2 midpoint Hertz Linear
	d3 = Get value at time... 3 midpoint Hertz Linear

	selectObject: formantID_5
	e1 = Get value at time... 1 midpoint Hertz Linear
	e2 = Get value at time... 2 midpoint Hertz Linear
	e3 = Get value at time... 3 midpoint Hertz Linear

	appendInfoLine: startTime, "	", phoneme$, "	", f0, "	", a1, "	", a2, "	", a3, "	", b1, "	", b2, "	", b3, "	", c1, "	", c2, "	", c3, "	", d1, "	", d2, "	", d3, "	", e1, "	", e2, "	", e3
endfor
