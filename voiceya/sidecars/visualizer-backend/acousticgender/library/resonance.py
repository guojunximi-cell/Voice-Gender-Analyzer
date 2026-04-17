import statistics
import json
import re

clamp = lambda minimum, maximum, value : max(minimum, min(value, maximum))

# IPA tone diacritics used by MFA mandarin_mfa
_TONE_RE = re.compile(r'[˥˦˧˨˩]+')

def _strip_tone(p):
	"""Remove tone diacritics from an IPA phoneme label."""
	return _TONE_RE.sub('', p) if p else p

# Vowel nuclei as output by MFA mandarin_mfa (after stripping tone marks)
# Includes syllabic consonants used as nuclei (零韵母): ʐ̩ (zhi/chi/shi/ri), z̩ (zi/ci/si)
ZH_VOWELS = {'a', 'aj', 'aw', 'e', 'ej', 'i', 'io', 'o', 'ow', 'u', 'y', 'ə', 'ɥ', 'ʐ̩', 'z̩'}

def compute_resonance(data, weights=[2/5, 2/5, 1/5], lang='en'):
	assert(abs(sum(weights) - 1) < .01)

	data['mean']  = {'F': []}
	data['stdev'] = {'F': []}

	# Remove outliers (TODO: Make configurable)
	for i in range(4):
		mean = statistics.mean([
			phoneme['F'][i] for phoneme in data['phones']
			if phoneme['F'][i] is not None
		])
		stdev = statistics.stdev([
			phoneme['F'][i] for phoneme in data['phones']
			if phoneme['F'][i] is not None
		])
		data['mean']['F'].append(mean)
		data['stdev']['F'].append(stdev)
		for p in range(len(data['phones'])):
			if data['phones'][p]['F'][i] is None:
				continue
			if abs(data['phones'][p]['F'][i] - mean) / stdev > 2:
				data['phones'][p]['outlier'] = True
				data['phones'][p]['F'][i] = None
		
	stats_file = 'stats_zh.json' if lang == 'zh' else 'stats.json'
	with open(stats_file) as f:
		stats = json.loads(f.read())

	for phone in data['phones']:
		phoneme_key  = _strip_tone(phone.get('phoneme'))  if lang == 'zh' else phone.get('phoneme')
		expected_key = _strip_tone(phone.get('expected')) if lang == 'zh' else phone.get('expected')
		if (not (phoneme_key and expected_key and
			stats.get(phoneme_key) and stats.get(expected_key))
		): continue

		phone['F_stdevs'] = [
			None if len(phone['F']) <= i or phone['F'][i] == None else
			(phone['F'][i] - stats[expected_key][i]['mean'])
			/ stats[expected_key][i]['stdev']
			for i in list(range(4))
		]



	for i in range(len(data['phones'])):
		currentPhone = data['phones'][i]

		if lang == 'zh':
			isVowel = currentPhone['phoneme'] and (
				_strip_tone(currentPhone['phoneme']) in ZH_VOWELS
			)
		else:
			isVowel = currentPhone['phoneme'] and len([
				value for value in list(currentPhone['phoneme'])
				if value in ["A", "E", "I", "O", "U", "Y"]
			]) >= 1

		stdevs = currentPhone.get('F_stdevs')
		if stdevs and (
			(weights[0] == 0 or stdevs[1] is not None) and
			(weights[1] == 0 or stdevs[2] is not None) and
			(weights[2] == 0 or stdevs[3] is not None)
		):
			data['phones'][i]['resonance'] = clamp(0, 1,
				weights[0] * (stdevs[1] or 0)
				+ weights[1] * (stdevs[2] or 0)
				+ weights[2] * (stdevs[3] or 0)
				+ .5
			)

	pitch_sample = [
		phone['F'][0] for phone in data['phones'] 
		if phone.get('F') and phone['F'][0] and not phone.get('outlier')
	]
	resonance_sample = [
		phone['resonance'] for phone in data['phones'] 
		if phone.get('resonance') and not phone.get('outlier')
	]
	data['meanPitch'] = statistics.mean(pitch_sample)
	data['meanResonance'] = statistics.mean(resonance_sample)
	data['medianPitch'] = statistics.median(pitch_sample)
	data['medianResonance'] = statistics.median(resonance_sample)
	data['stdevPitch'] = statistics.stdev(pitch_sample)
	data['stdevResonance'] = statistics.stdev(resonance_sample)
