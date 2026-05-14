import re

def parse(praat_output, lang='en'):
	if praat_output is None:
		return {'words': [], 'phones': []}

	word_lines = []
	phoneme_lines = []
	active_list = None

	for line in praat_output.split('\n'):
		if line == "Words:":
			active_list = word_lines
			continue
		if line == "Phonemes:":
			active_list = phoneme_lines
			continue
		# voiceya patch (2026-05-01): the patched textgrid-formants.praat appends
		# a "Multi-Ceiling-Formants:" section after "Phonemes:" so the wrapper's
		# ceiling_selector can pick the optimal ceiling per recording.  Without
		# this guard, phones.parse would happily keep appending those rows to
		# phoneme_lines, blowing past the word boundaries with IndexError.
		# Any unrecognised section header (line ending in ":" with no tabs)
		# closes the current section.
		if line and line.endswith(":") and "\t" not in line and active_list is not None:
			active_list = None
			continue

		if active_list is not None:
			active_list.append(line)

	data = {}

	pronunciation_dict = {}
	# voiceya patch: fr added 2026-04-28, ko added 2026-05-12.  zh/fr/ko all
	# use MFA pretrained v3's multi-column probability dict format
	# (word\tprob\tprob\tprob\tprob\tphone1 phone2 ...); en uses cmudict's
	# 2-column ARPABET format.  See voiceya/sidecars/README.md "Vendor patches".
	if lang == 'zh':
		dict_file, dict_encoding = 'mandarin_dict.txt', 'utf-8-sig'
	elif lang == 'fr':
		dict_file, dict_encoding = 'french_mfa_dict.txt', 'utf-8'
	elif lang == 'ko':
		dict_file, dict_encoding = 'korean_mfa_dict.txt', 'utf-8'
	else:
		dict_file, dict_encoding = 'cmudict.txt', 'iso-8859-1'
	with open(dict_file, 'r', encoding=dict_encoding) as f:
		for line in f.readlines():
			if lang in ('zh', 'fr', 'ko'):
				# MFA pretrained v3 dict format: word\tprob\tprob\tprob\tprob\tphone1 phone2 ...
				cols = line.rstrip('\n').split('\t')
				if len(cols) >= 6:
					pronunciation_dict[cols[0]] = cols[5].split()
			else:
				cols = line.split()
				if len(cols) >= 2:
					pronunciation_dict[cols[0]] = cols[1:]

	data['words'] = []
	for line in word_lines:
		cols = line.split('\t')
		# voiceya patch: zh/fr/ko keep lowercase (MFA v3 dicts are lowercase);
		# only en cmudict needs upper-casing for lookup.
		word_key = cols[1] if lang in ('zh', 'fr', 'ko') else cols[1].upper()
		data['words'].append({
			'time' : float(cols[0]),
			'word' : cols[1],
			'expected' : (pronunciation_dict.get(word_key) or [None]) + [None] * 10
		})

	data['phones'] = []
	word_index = -1
	phoneme_in_word_index = 0
	for line in phoneme_lines:
		cols = line.split('\t')

		if len(cols) < 3: continue

		time = float(cols[0]) if re.match(r'^-?\d+(?:\.\d+)?$', cols[0]) else None
		while (
			type(time) == float and
			word_index < len(data['words']) - 1 and
			time >= data['words'][word_index + 1]['time']
		):
			word_index += 1
			phoneme_in_word_index = 0

		if word_index < 0 or word_index >= len(data['words']):
			continue

		data['phones'].append({
			'time': time,
			'phoneme': cols[1],
			'word_index': word_index,
			'word': data['words'][word_index],
			'word_time': data['words'][word_index]['time'],
			'expected': data['words'][word_index]['expected'][phoneme_in_word_index],
			'F': [None if '--' in f else float(f) for f in cols[2:]]
		})
		phoneme_in_word_index += 1

	return data
