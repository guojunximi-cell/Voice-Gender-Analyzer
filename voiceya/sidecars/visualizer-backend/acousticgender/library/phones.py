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

		if active_list is not None:
			active_list.append(line)

	data = {}

	pronunciation_dict = {}
	if lang == 'zh':
		dict_file, dict_encoding = 'mandarin_dict.txt', 'utf-8-sig'
	else:
		dict_file, dict_encoding = 'cmudict.txt', 'iso-8859-1'
	with open(dict_file, 'r', encoding=dict_encoding) as f:
		for line in f.readlines():
			if lang == 'zh':
				# mandarin_dict.txt format: word\tprob\tprob\tprob\tprob\tphone1 phone2 ...
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
		word_key = cols[1] if lang == 'zh' else cols[1].upper()
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
