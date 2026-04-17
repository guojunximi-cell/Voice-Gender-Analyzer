#!/usr/bin/env python3

print('corpusanalysis.py: __package__ ->', __package__)

import os, sys, subprocess, json, argparse
from collections import defaultdict
from statistics import mean, median, stdev
from concurrent.futures import ProcessPoolExecutor, as_completed

from library import preprocessing, phones, resonance
from library.resonance import _strip_tone

parser = argparse.ArgumentParser()
parser.add_argument('--lang', default='en', choices=['en', 'zh'])
parser.add_argument('--corpus-dir', default='./corpus')
parser.add_argument('--processed-dir', default=None,
	help='默认 ./corpus-processed（en）或 ./corpus-processed-zh（zh）')
parser.add_argument('--stats-out', default=None,
	help='默认 stats.json（en）或 stats_zh.json（zh）')
parser.add_argument('--weights-out', default=None,
	help='默认 weights.json（en）或 weights_zh.json（zh）')
parser.add_argument('--skip-weights', action='store_true',
	help='只生成 stats，不跑权重暴力搜索')
parser.add_argument('--jobs', type=int, default=1,
	help='并行 worker 数（preprocessing 阶段）；1=串行')
parser.add_argument('--weights-granularity', type=int, default=500,
	help='weights 第一轮粗搜 granularity（C(g+2,2) 个候选）')
parser.add_argument('--weights-refine', action='store_true',
	help='在粗搜 winner 周围 ±0.05 内做一轮精搜（granularity=1000 等效）')
parser.add_argument('--weights-refine-steps', type=int, default=201,
	help='精搜每个维度的分辨率（201^3 ≈ 8M 候选，走分块）')
parser.add_argument('--weights-chunk', type=int, default=200000,
	help='精搜分块大小（避免一次性分配巨大矩阵）')
parser.add_argument('--weights-refine-half-width', type=float, default=0.05,
	help='精搜半宽（默认 ±0.05）')
parser.add_argument('--weights-kfold', type=int, default=10,
	help='k-fold CV；<2 时退化为全量拟合')
parser.add_argument('--weights-seed', type=int, default=42,
	help='k-fold 打乱随机种子')
args = parser.parse_args()

lang = args.lang
corpus_dir = args.corpus_dir
processed_corpus_dir = args.processed_dir or (
	'./corpus-processed' if lang == 'en' else './corpus-processed-zh')
stats_out = args.stats_out or ('stats.json' if lang == 'en' else 'stats_zh.json')
weights_out = args.weights_out or ('weights.json' if lang == 'en' else 'weights_zh.json')

def phoneme_key(phone):
	return _strip_tone(phone['phoneme']) if lang == 'zh' else phone['phoneme']

def _process_one(directory, corpus_dir, processed_corpus_dir, lang):
	# 每 worker 独立 MFA_ROOT_DIR，避免并发写 command_history.yaml / temp 冲突。
	# 但要软链 pretrained_models / models / extracted_models / global_config.yaml
	# 到默认 ~/Documents/MFA，否则找不到已下载的 mandarin_mfa。
	mfa_root = os.path.abspath(processed_corpus_dir + '/.mfa-root-' + str(os.getpid()))
	if not os.path.exists(mfa_root):
		os.makedirs(mfa_root)
		default_root = os.path.expanduser('~/Documents/MFA')
		for sub in ('pretrained_models', 'models', 'extracted_models', 'global_config.yaml'):
			src = os.path.join(default_root, sub)
			dst = os.path.join(mfa_root, sub)
			if os.path.exists(src) and not os.path.exists(dst):
				os.symlink(src, dst)
	os.environ['MFA_ROOT_DIR'] = mfa_root
	transcript = ''
	recording = None
	src = corpus_dir + '/' + directory
	for filename in os.listdir(src):
		if filename.endswith('.txt'):
			with open(src + '/' + filename, encoding='utf-8') as f:
				transcript = f.read()
		elif any(filename.endswith(ext) for ext in ['.wav', '.mp3', '.ogg', '.opus']):
			with open(src + '/' + filename, 'rb') as f:
				recording = f.read()
	# preprocessing.process 会 os.mkdir(tmp_dir) + 最后 shutil.rmtree(tmp_dir)，
	# 所以用一次性 tmp 路径，把返回的 TSV 文本落到持久 processed_dir。
	tmp_dir = processed_corpus_dir + '/' + directory + '.tmp'
	persist_dir = processed_corpus_dir + '/' + directory
	if os.path.exists(tmp_dir):
		import shutil as _sh; _sh.rmtree(tmp_dir)
	if os.path.exists(persist_dir):
		return (directory, True, 'already-done')
	try:
		praat_tsv = preprocessing.process(recording, transcript, tmp_dir, lang=lang)
		if not praat_tsv:
			return (directory, False, 'empty praat output')
		os.makedirs(persist_dir + '/output', exist_ok=True)
		with open(persist_dir + '/output/recording.tsv', 'w', encoding='utf-8') as f:
			f.write(praat_tsv)
		return (directory, True, None)
	except Exception as e:
		return (directory, False, str(e))

if not os.path.exists(processed_corpus_dir):
	os.makedirs(processed_corpus_dir)
	subprocess.run(['chmod', '777', '-R', processed_corpus_dir])

# 总是遍历，per-dir 幂等跳过（_process_one 内部检查 persist_dir 是否已存在）
if True:
	dirs = sorted([d for d in os.listdir(corpus_dir)
	               if os.path.isdir(os.path.join(corpus_dir, d)) and not d.startswith('_')])
	if args.jobs <= 1:
		for d in dirs:
			r = _process_one(d, corpus_dir, processed_corpus_dir, lang)
			print(r)
	else:
		with ProcessPoolExecutor(max_workers=args.jobs) as ex:
			futs = {ex.submit(_process_one, d, corpus_dir, processed_corpus_dir, lang): d for d in dirs}
			done = 0
			for fut in as_completed(futs):
				r = fut.result()
				done += 1
				print(f'[{done}/{len(dirs)}]', r[0], 'ok' if r[1] else 'FAIL', r[2] or '')

m_count = 0
f_count = 0
m_data = []
f_data = []
for directory in os.listdir(processed_corpus_dir):
	tsv_file =  (processed_corpus_dir + '/' + directory +
	             '/output/recording.tsv')
	if os.path.exists(tsv_file):
		with open(tsv_file) as f:
			tsv_text = f.read()

		if directory[0] == 'm':
			m_data.append(phones.parse(tsv_text, lang=lang))
			m_count += 1
		if directory[0] == 'f':
			f_data.append(phones.parse(tsv_text, lang=lang))
			f_count += 1

if len(f_data) > len(m_data):
	f_data = f_data[0:len(m_data)]
if len(m_data) > len(f_data):
	m_data = m_data[0:len(f_data)]

print('lang', lang)
print('m_count', m_count)
print('f_count', f_count)
print('len(f_data)', len(f_data))
print('len(m_data)', len(m_data))


population_phones = defaultdict(list)
for data in m_data + f_data:
	for phone in data['phones']:
		if (phone['F'] and phone['F'][0] and phone['F'][1] and
		    phone['F'][2] and phone['F'][3]
		):
			population_phones[phoneme_key(phone)].append(phone)

phone_stats = {}

for phoneme in population_phones:
	print(phoneme)
	Fs = [[phone['F'][i] for phone in population_phones[phoneme] ]
	       for i in range(4)]
	# stdev 需要至少 2 个样本
	if len(Fs[0]) < 2:
		print('\tskip (only', len(Fs[0]), 'sample)')
		continue
	for i in range(4):
		print('\tf' + str(i), mean(Fs[i]), stdev(Fs[i]))

	phone_stats[phoneme] = [
		{	'mean' : mean(Fs[i]),
			'stdev': stdev(Fs[i]),
			'median': median(Fs[i]),
			'max': max(Fs[i]),
			'min': min(Fs[i]),
		} for i in range(4)
	]

with open(stats_out, 'w') as f:
	f.write(json.dumps(phone_stats, ensure_ascii=False))
print('wrote', stats_out)

if args.skip_weights:
	sys.exit(0)

# ---------------------------------------------------------------------------
# 向量化 k-fold weights 暴力搜索
#
# 思路：resonance 对 weights 的依赖是线性的，z-score 只依赖 stats——所以
# 预先算一次 (outlier removal + F_stdevs)，然后对所有 candidate weights 一次
# matmul 扫描，配 k-fold CV 选最稳的一组。
# ---------------------------------------------------------------------------
import numpy as np
import random as _random

# 1) 预计算每条 utt 的 (n_phones_valid, 3) z-score 矩阵。
#    用任意权重调一次 compute_resonance，只为触发 outlier removal + F_stdevs 填充。
_dummy_w = [1/3, 1/3, 1/3]
for data in m_data + f_data:
	resonance.compute_resonance(data, _dummy_w, lang=lang)

def _extract_Z(data):
	rows = []
	for phone in data['phones']:
		if phone.get('outlier'): continue
		fs = phone.get('F_stdevs')
		if not fs: continue
		z1, z2, z3 = fs[1], fs[2], fs[3]
		if z1 is None or z2 is None or z3 is None: continue
		rows.append((z1, z2, z3))
	if not rows: return None
	return np.asarray(rows, dtype=np.float64)

Z_list = []
labels = []  # 0=m, 1=f
for data in m_data:
	Z = _extract_Z(data)
	if Z is not None: Z_list.append(Z); labels.append(0)
for data in f_data:
	Z = _extract_Z(data)
	if Z is not None: Z_list.append(Z); labels.append(1)

labels = np.asarray(labels, dtype=np.int8)
n_utts = len(Z_list)
print(f'n_utts with valid Z: {n_utts} (m={int((labels==0).sum())}, f={int((labels==1).sum())})')

def _score_candidates(W):
	"""W: (C, 3) → R: (n_utts, C) utt-level meanResonance."""
	C = W.shape[0]
	R = np.empty((n_utts, C), dtype=np.float64)
	for u, Z in enumerate(Z_list):
		phone_res = np.clip(Z @ W.T + 0.5, 0.0, 1.0)
		R[u] = phone_res.mean(axis=0)
	return R

def _kfold_acc(R, labels, k, seed):
	"""返回每个 candidate 在 k-fold 上的 (mean_acc, std_acc)。"""
	n = R.shape[0]; C = R.shape[1]
	idx = np.arange(n)
	rng = _random.Random(seed); rng_idx = list(idx); rng.shuffle(rng_idx)
	idx = np.asarray(rng_idx, dtype=int)
	folds = np.array_split(idx, k)
	accs = np.zeros((k, C), dtype=np.float64)
	for fi, test_idx in enumerate(folds):
		train_mask = np.ones(n, dtype=bool); train_mask[test_idx] = False
		R_train, y_train = R[train_mask], labels[train_mask]
		R_test,  y_test  = R[test_idx],  labels[test_idx]
		# 每 candidate 用 train median 作为阈值
		thr = np.median(R_train, axis=0)  # (C,)
		# m 正确：R_test <= thr；f 正确：R_test >= thr（与原逻辑一致，边界双算）
		pred_m = R_test <= thr
		pred_f = R_test >= thr
		is_m = (y_test == 0)[:, None]
		is_f = (y_test == 1)[:, None]
		correct = (pred_m & is_m) | (pred_f & is_f)
		accs[fi] = correct.mean(axis=0)
	return accs.mean(axis=0), accs.std(axis=0)

def _gen_simplex(g):
	"""{(i/g, j/g, k/g) : i+j+k=g, i,j,k>=0}"""
	W = []
	for i in range(g + 1):
		for j in range(g + 1 - i):
			k = g - i - j
			W.append((i / g, j / g, k / g))
	return np.asarray(W, dtype=np.float64)

def _gen_box(center, half_width, steps):
	"""在 center ±half_width 的盒子里采样，再投影回单纯形（归一化和=1）。
	steps 为每维分辨率。丢弃负权重样本。"""
	c = np.clip(np.asarray(center, dtype=np.float64), 0, 1)
	axis = np.linspace(-half_width, half_width, steps)
	W = []
	for a in axis:
		for b in axis:
			for d in axis:
				w = c + np.array([a, b, d])
				if (w < -1e-9).any(): continue
				s = w.sum()
				if s <= 1e-9: continue
				W.append(w / s)
	if not W: return np.asarray([c / c.sum()], dtype=np.float64)
	return np.asarray(W, dtype=np.float64)

# 2) 粗搜（单纯形均匀）
g = args.weights_granularity
print(f'\n[coarse] granularity={g}, candidates={(g+1)*(g+2)//2}')
W_coarse = _gen_simplex(g)
R_coarse = _score_candidates(W_coarse)
if args.weights_kfold >= 2:
	mean_acc, std_acc = _kfold_acc(R_coarse, labels, args.weights_kfold, args.weights_seed)
	# 选 mean 最大；并列时 std 最小
	score = mean_acc - 1e-6 * std_acc
	best = int(np.argmax(score))
	print(f'[coarse] best mean_acc={mean_acc[best]:.4f} std={std_acc[best]:.4f} '
	      f'weights={W_coarse[best].tolist()}')
else:
	# 全量拟合（与旧逻辑一致）
	thr = np.median(R_coarse, axis=0)
	acc = (((R_coarse <= thr) & (labels == 0)[:, None]) |
	       ((R_coarse >= thr) & (labels == 1)[:, None])).mean(axis=0)
	best = int(np.argmax(acc))
	mean_acc = acc; std_acc = np.zeros_like(acc)
	print(f'[coarse] best acc={acc[best]:.4f} weights={W_coarse[best].tolist()}')

winner_W = W_coarse[best]
winner_mean = float(mean_acc[best]); winner_std = float(std_acc[best])

# 3) 精搜（可选，分块扫以免内存爆炸）
if args.weights_refine:
	hw = args.weights_refine_half_width
	steps = args.weights_refine_steps
	W_fine = _gen_box(winner_W, hw, steps)
	N = len(W_fine); chunk = max(1, args.weights_chunk)
	print(f'\n[refine] around {winner_W.tolist()} ±{hw}, steps={steps}, '
	      f'candidates={N}, chunk={chunk}')
	best_i = -1; best_mean = -1.0; best_std = 0.0
	for start in range(0, N, chunk):
		end = min(start + chunk, N)
		W_chunk = W_fine[start:end]
		R_chunk = _score_candidates(W_chunk)
		if args.weights_kfold >= 2:
			m_acc, s_acc = _kfold_acc(R_chunk, labels, args.weights_kfold, args.weights_seed)
		else:
			thr = np.median(R_chunk, axis=0)
			m_acc = (((R_chunk <= thr) & (labels == 0)[:, None]) |
			         ((R_chunk >= thr) & (labels == 1)[:, None])).mean(axis=0)
			s_acc = np.zeros_like(m_acc)
		score = m_acc - 1e-6 * s_acc
		bi = int(np.argmax(score))
		if (m_acc[bi] > best_mean or
		    (m_acc[bi] == best_mean and s_acc[bi] < best_std)):
			best_mean = float(m_acc[bi]); best_std = float(s_acc[bi]); best_i = start + bi
		print(f'  chunk {start:>9}-{end:<9} local_best mean={m_acc[bi]:.4f} std={s_acc[bi]:.4f} '
		      f'| global_best mean={best_mean:.4f} std={best_std:.4f}')
	print(f'[refine] best mean_acc={best_mean:.4f} std={best_std:.4f} '
	      f'weights={W_fine[best_i].tolist()}')
	if best_mean > winner_mean or (best_mean == winner_mean and best_std < winner_std):
		winner_W = W_fine[best_i]; winner_mean = best_mean; winner_std = best_std

winner = [float(x) for x in winner_W]
print(f'\n[final] weights={winner}  mean_acc={winner_mean:.4f}  std={winner_std:.4f}')

with open(weights_out, 'w') as f:
	f.write(json.dumps(winner))
print('wrote', weights_out)
