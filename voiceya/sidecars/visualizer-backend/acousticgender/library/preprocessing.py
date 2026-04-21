import subprocess, os, glob, shutil, sys
import magic

from . import settings as settings_module

settings = settings_module.settings

def process(uploaded_file, transcript, tmp_dir, lang='en'):
	################## Noise Removal ##################

	os.mkdir(tmp_dir)
	filetype = magic.from_buffer(uploaded_file)

	input_file    = tmp_dir + '/orig'
	format_file   = tmp_dir + '/format.wav'
	silence_file  = tmp_dir + '/silence.wav'
	clean_file    = tmp_dir + '/clean.wav'
	noise_profile = tmp_dir + '/noise.prof'

	with open(input_file, "wb") as f: 
		f.write(uploaded_file)

	assert(os.path.exists(input_file))

	try:
		subprocess.check_output([settings['ffmpeg'], '-i', input_file, format_file])

		ffmpeg_silence = subprocess.check_output([
				settings['ffmpeg'], '-i', input_file,
				'-af', 'silencedetect=n=-30dB:d=0.5',
				'-f', 'null', '-'
		], stderr=subprocess.STDOUT).decode('utf-8').split('\n')

		silence_ranges = list(zip(
				[line.split(" ")[4] for line in ffmpeg_silence
						if 'silence_start' in line],
				[line.split(" ")[4] for line in ffmpeg_silence
						if 'silence_end' in line]
		))

		subprocess.check_output([settings['ffmpeg'], '-i', input_file,
				'-af', "aselect='" + '+'.join(
						['between(t,' + r[0] + ',' + r[1]+')' for r in silence_ranges]
				) + "', asetpts=N/SR/TB",
				silence_file
		])

		assert(os.path.exists(silence_file))

		subprocess.check_output([
				settings['sox'], silence_file, '-n', 'noiseprof', noise_profile
		])
		subprocess.check_output([
				settings['sox'], format_file, clean_file,
				'noisered', noise_profile, '0.2'
		])

		assert(os.path.exists(clean_file))
	except Exception:
		clean_file = input_file

	################## Forced Alignment ##################
	corpus_dir = tmp_dir + '/corpus'
	output_dir = tmp_dir + '/output'
	os.mkdir(corpus_dir)
	os.mkdir(output_dir)

	subprocess.check_output([
		settings['ffmpeg'],
		'-i'     , clean_file,
		'-acodec', 'pcm_s16le',
		'-ac'    , '1',
		'-ar'    , '16000',
		corpus_dir + '/recording.wav'
	])

	if lang == 'zh':
		import re as _re
		han_chars = _re.findall(r'[\u4e00-\u9fff]', transcript)
		transcript_out = ' '.join(han_chars)
	else:
		transcript_out = transcript

	with open(corpus_dir + '/recording.txt', 'w', encoding='utf-8') as f:
		f.write(transcript_out)

	mfa_model = 'mandarin_mfa' if lang == 'zh' else 'english_mfa'

	scripts_dir = os.path.dirname(settings['mfa'])
	env_dir     = os.path.dirname(scripts_dir)
	mfa_env     = os.environ.copy()

	if sys.platform == 'win32':
		# Windows conda layout: env/Scripts/mfa.exe + env/python.exe
		mfa_python = os.path.join(env_dir, 'python.exe')
		mfa_script = os.path.join(scripts_dir, 'mfa-script.py')
		mfa_cmd    = [mfa_python, mfa_script]
		path_additions = os.pathsep.join([
			os.path.join(env_dir, 'Library', 'bin'),
			os.path.join(env_dir, 'Library', 'mingw-w64', 'bin'),
			os.path.join(env_dir, 'Library', 'usr', 'bin'),
			os.path.join(env_dir, 'Scripts'),
			env_dir,
		])
		mfa_env['PATH'] = path_additions + os.pathsep + mfa_env.get('PATH', '')
	else:
		# Linux/macOS conda layout: env/bin/mfa (shell shim) + env/bin/python
		mfa_cmd = [settings['mfa']]
		mfa_env['PATH'] = scripts_dir + os.pathsep + mfa_env.get('PATH', '')

	mfa_env['CONDA_PREFIX'] = env_dir

	cwd = os.getcwd()
	os.chdir(tmp_dir)

	print(f"[MFA] cmd: {mfa_cmd}", file=sys.stderr)
	print(f"[MFA] env_dir: {env_dir} (exists: {os.path.isdir(env_dir)})", file=sys.stderr)
	try:
		mfa_out = subprocess.check_output(
			mfa_cmd + ['align',
			 './corpus/', mfa_model, mfa_model, './output/', '--clean',
			 '--beam', '100', '--retry_beam', '400'],
			stderr=subprocess.STDOUT,
			env=mfa_env
		)
		print("[MFA] stdout+stderr:", mfa_out.decode('utf-8', errors='replace'), file=sys.stderr)
	except subprocess.CalledProcessError as e:
		print("CalledProcessError", file=sys.stderr)
		print(e, file=sys.stderr)
		print(str(e.output, 'utf-8', errors='replace'), file=sys.stderr)
		raise RuntimeError("MFA align failed: " + str(e.output, 'utf-8', errors='replace')[-800:])
	except Exception as e:
		print("Error running MFA:", e, file=sys.stderr)
		raise

	print(f"[MFA] TextGrids found: {glob.glob(output_dir + '/*.TextGrid')}", file=sys.stderr)

	os.chdir(cwd)


	################## Phonetic Processing ##################
	praat_output = None
	for recording, grid in zip(
		sorted(glob.glob(corpus_dir + '/*.wav')),
		sorted(glob.glob(output_dir + '/*.TextGrid'))
	):
		print(f"[Praat] running: {settings['praat']} --run textgrid-formants.praat {recording} {grid}", file=sys.stderr)
		try:
			praat_output = subprocess.check_output([
				settings['praat'], '--run',
				os.path.join(cwd, 'textgrid-formants.praat'),
				recording, grid
			], stderr=subprocess.STDOUT).decode('utf-8')
			print(f"[Praat] output ({len(praat_output)} chars): {praat_output[:500]}", file=sys.stderr)
		except subprocess.CalledProcessError as e:
			print(f"[Praat] CalledProcessError (exit {e.returncode}):", file=sys.stderr)
			print(e.output.decode('utf-8', errors='replace'), file=sys.stderr)
			raise

		with open(grid.replace('.TextGrid', '.tsv'), 'w') as f:
			f.write(praat_output)

	shutil.rmtree(tmp_dir)
	return praat_output
