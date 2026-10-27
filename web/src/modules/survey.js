/**
 * survey.js — 站内问卷（功能体验 + 期待 + NPS）。
 *
 * 题目由 QUESTIONS 配置生成，元素带 data-i18n* 属性，切语言时 setLang() 里的
 * applyStaticDom() 直接刷新文案，DOM 不重建、已填答案不丢。
 *
 * 分两部分：「关于你」所有人都答；「使用体验」只在 Q2 ≠ "first" 时展开，
 * 首次使用者没有可评价的体验，只答前四题。
 *
 * 提交复用反馈浮层的 Formspree 接口（读 #vgaFeedbackForm 的 action），
 * 只发问卷答案——不附带分析结果、音频、语言、邮箱等任何其他数据。
 * 选项值用与界面语言无关的代码（如 "search"），四语答卷可直接合并统计。
 *
 * localStorage：
 *   vga.surveyPrompted.v1 — 首次进站提示卡已处理过（打开或关闭）
 *   vga.surveyDone.v1     — "intro"（只答第一部分）| "full"（完整问卷）
 */

import { t } from "./i18n.js";

const PROMPTED_KEY = "vga.surveyPrompted.v1";
const DONE_KEY = "vga.surveyDone.v1";
const PROMPT_DELAY_MS = 1500;
const OTHER_MAXLEN = 100;
const TEXT_MAXLEN = 500;
// Formspree 收件箱里用来和自由文本反馈区分
const SUBJECT = "Survey · 问卷";

// opt(code, key?)：key 省略时用 survey.<qid>.opt.<code>；
// 与界面已有文案同义的选项直接复用现有 key，界面改名时问卷跟着变。
const opt = (code, key) => ({ code, key });

const QUESTIONS = [
	{
		id: "q1_source",
		section: "about",
		type: "single",
		other: true,
		options: [opt("search"), opt("ai"), opt("reddit"), opt("social"), opt("community")],
	},
	{
		id: "q2_visits",
		section: "about",
		type: "single",
		required: true,
		options: [opt("first"), opt("2_5"), opt("6_10"), opt("10_plus")],
	},
	{
		id: "q3_lang",
		section: "about",
		type: "multi",
		other: true,
		options: [
			opt("zh", "header.langName.zh"),
			opt("en", "header.langName.en"),
			opt("fr", "header.langName.fr"),
			opt("ko", "header.langName.ko"),
		],
	},
	{
		id: "q4_channels",
		section: "about",
		type: "multi",
		other: true,
		exclusive: ["none"],
		options: [opt("teacher"), opt("video"), opt("apps"), opt("peer"), opt("self"), opt("none")],
	},
	{
		id: "q5_best",
		section: "usage",
		type: "multi",
		other: true,
		options: [
			opt("upload"),
			opt("record_script"),
			opt("record_free"),
			opt("timeline"),
			opt("pitch", "dashboard.block.pitch"),
			opt("formants", "dashboard.block.formants"),
			opt("resonance", "dashboard.block.resonance"),
			opt("nn", "dashboard.block.nn"),
			opt("history"),
			opt("export"),
		],
	},
	{ id: "q6_clarity", section: "usage", type: "scale", min: 1, max: 5 },
	{ id: "q7_helpful", section: "usage", type: "scale", min: 1, max: 5 },
	{
		id: "q8_improve",
		section: "usage",
		type: "multi",
		other: true,
		limit: 3,
		options: [opt("speed"), opt("explain"), opt("tips"), opt("accuracy"), opt("mobile"), opt("input"), opt("scripts")],
	},
	{ id: "q9_nps", section: "usage", type: "scale", min: 0, max: 10, required: true },
	{ id: "q10_message", section: "usage", type: "text" },
];

const SECTIONS = ["about", "usage"];

// ─── localStorage（私密模式 / 被禁用时一律吞掉）─────────────────

function _lsGet(key) {
	try {
		return localStorage.getItem(key);
	} catch {
		return undefined; // undefined = 不可用，区别于 null = 没写过
	}
}

function _lsSet(key, value) {
	try {
		localStorage.setItem(key, value);
	} catch {
		/* ignore — 最坏情况是下次还能看到提示 */
	}
}

// ─── DOM 构建 ────────────────────────────────────────────────

function _el(tag, attrs = {}, children = []) {
	const node = document.createElement(tag);
	for (const [k, v] of Object.entries(attrs)) {
		if (v === false || v == null) continue;
		if (k === "className") node.className = v;
		else node.setAttribute(k, v === true ? "" : v);
	}
	for (const c of children) node.append(c);
	return node;
}

function _legend(q) {
	const legend = _el("legend", { className: "survey-q-label" }, [_el("span", { "data-i18n": `survey.${q.id}.label` })]);
	if (q.required) legend.append(_el("span", { "className": "survey-req", "aria-hidden": "true" }, ["*"]));
	return legend;
}

function _buildChoice(q) {
	const inputType = q.type === "single" ? "radio" : "checkbox";
	const options = q.other ? [...q.options, opt("other", "survey.opt.other")] : q.options;
	const list = _el("div", { className: "survey-options" });
	for (const o of options) {
		list.append(
			_el("label", { className: "survey-option" }, [
				_el("input", { type: inputType, name: q.id, value: o.code }),
				_el("span", { "data-i18n": o.key ?? `survey.${q.id}.opt.${o.code}` }),
			]),
		);
	}
	const field = _el("fieldset", { "className": "survey-q", "data-qid": q.id }, [_legend(q), list]);
	if (q.other) {
		field.append(
			_el("input", {
				"type": "text",
				"name": `${q.id}_other`,
				"className": "vga-feedback-input survey-other-input",
				"maxlength": OTHER_MAXLEN,
				"data-i18n-placeholder": "survey.otherPlaceholder",
				"data-i18n-aria-label": "survey.otherPlaceholder",
				"hidden": true,
			}),
		);
	}
	return field;
}

function _buildScale(q) {
	const row = _el("div", { className: "survey-scale", style: `--survey-scale-n: ${q.max - q.min + 1}` });
	for (let v = q.min; v <= q.max; v++) {
		row.append(
			_el("label", { className: "survey-scale-item" }, [
				_el("input", { type: "radio", name: q.id, value: String(v) }),
				_el("span", {}, [String(v)]),
			]),
		);
	}
	const anchors = _el("div", { className: "survey-scale-anchors" }, [
		_el("span", { "data-i18n": `survey.${q.id}.low` }),
		_el("span", { "data-i18n": `survey.${q.id}.high` }),
	]);
	return _el("fieldset", { "className": "survey-q", "data-qid": q.id }, [_legend(q), row, anchors]);
}

function _buildText(q) {
	const inputId = `survey-${q.id}`;
	return _el("div", { "className": "survey-q", "data-qid": q.id }, [
		_el("label", { "className": "survey-q-label", "for": inputId, "data-i18n": `survey.${q.id}.label` }),
		_el("textarea", {
			"id": inputId,
			"name": q.id,
			"className": "vga-feedback-input survey-textarea",
			"maxlength": TEXT_MAXLEN,
			"data-i18n-placeholder": `survey.${q.id}.placeholder`,
		}),
	]);
}

function _buildQuestions(container) {
	for (const section of SECTIONS) {
		const wrap = _el("section", { "className": "survey-section", "data-section": section }, [
			_el("h4", { "className": "survey-section-title", "data-i18n": `survey.section.${section}` }),
		]);
		if (section === "usage") wrap.hidden = true;
		for (const q of QUESTIONS.filter((x) => x.section === section)) {
			if (q.type === "scale") wrap.append(_buildScale(q));
			else if (q.type === "text") wrap.append(_buildText(q));
			else wrap.append(_buildChoice(q));
		}
		container.append(wrap);
	}
}

// ─── 状态 / 规则 ─────────────────────────────────────────────

const $ = (id) => document.getElementById(id);

function _form() {
	return $("survey-form");
}

function _checked(qid) {
	return [..._form().querySelectorAll(`input[name="${qid}"]:checked`)].map((i) => i.value);
}

function _isFirstTime() {
	return _checked("q2_visits")[0] === "first";
}

function _usageVisible() {
	const v = _checked("q2_visits")[0];
	return v != null && v !== "first";
}

// 单题内的联动：互斥项、选择上限、「其他」填空框显隐
function _syncQuestion(q, changed) {
	const form = _form();
	const inputs = [...form.querySelectorAll(`input[name="${q.id}"]`)];
	if (q.exclusive && changed?.checked) {
		const changedIsExclusive = q.exclusive.includes(changed.value);
		for (const i of inputs) {
			if (i === changed) continue;
			if (changedIsExclusive || q.exclusive.includes(i.value)) i.checked = false;
		}
	}
	if (q.limit) {
		const full = inputs.filter((i) => i.checked).length >= q.limit;
		for (const i of inputs) {
			i.disabled = full && !i.checked;
			i.closest(".survey-option")?.classList.toggle("is-disabled", i.disabled);
		}
	}
	if (q.other) {
		const otherInput = form.querySelector(`input[name="${q.id}_other"]`);
		const otherOn = inputs.some((i) => i.value === "other" && i.checked);
		if (otherInput && otherInput.hidden === otherOn) {
			otherInput.hidden = !otherOn;
			if (otherOn) otherInput.focus();
		}
	}
}

function _syncForm() {
	const usage = _form().querySelector('[data-section="usage"]');
	if (usage) usage.hidden = !_usageVisible();
	const q2Done = _checked("q2_visits").length > 0;
	const npsDone = _checked("q9_nps").length > 0;
	const submit = $("survey-submit");
	if (submit) submit.disabled = !q2Done || (_usageVisible() && !npsDone);
}

// 只收集当前可见部分的答案；空答案不提交
function _collect() {
	const form = _form();
	const fd = new FormData();
	fd.append("_subject", SUBJECT);
	fd.append("_gotcha", form.querySelector('input[name="_gotcha"]')?.value ?? "");
	const sections = _usageVisible() ? SECTIONS : ["about"];
	for (const q of QUESTIONS.filter((x) => sections.includes(x.section))) {
		if (q.type === "text") {
			const text = form.querySelector(`[name="${q.id}"]`)?.value.trim();
			if (text) fd.append(q.id, text);
			continue;
		}
		const values = _checked(q.id);
		if (values.length) fd.append(q.id, values.join(", "));
		if (q.other && values.includes("other")) {
			const text = form.querySelector(`input[name="${q.id}_other"]`)?.value.trim();
			if (text) fd.append(`${q.id}_other`, text);
		}
	}
	return fd;
}

function _resetForm() {
	const form = _form();
	form.reset();
	for (const q of QUESTIONS) if (q.type === "multi" || q.type === "single") _syncQuestion(q);
	_syncForm();
	form.hidden = false;
	$("survey-thanks").hidden = true;
}

function _syncEntry() {
	const entry = $("survey-entry");
	if (entry) entry.hidden = _lsGet(DONE_KEY) === "full";
}

// ─── 打开 / 关闭 ─────────────────────────────────────────────

export function openSurvey() {
	const dialog = $("survey-dialog");
	if (!dialog) return;
	_hidePrompt();
	// 上次提交成功后停在感谢页——重开时换一份空白问卷
	if (!$("survey-thanks").hidden) _resetForm();
	if (typeof dialog.showModal === "function") dialog.showModal();
	else dialog.setAttribute("open", "");
}

function _close() {
	const dialog = $("survey-dialog");
	if (typeof dialog?.close === "function") dialog.close();
}

async function _submit(e) {
	e.preventDefault();
	const submit = $("survey-submit");
	if (!submit || submit.disabled) return;
	const action = $("vgaFeedbackForm")?.getAttribute("action");
	if (!action) return;
	const firstTime = _isFirstTime();
	submit.disabled = true;
	submit.textContent = t("action.sending");
	try {
		const res = await fetch(action, {
			method: "POST",
			body: _collect(),
			headers: { Accept: "application/json" },
		});
		if (!res.ok) throw new Error(`HTTP ${res.status}`);
		// "full" 不被 "intro" 覆盖：答过完整问卷的人再交一次首次部分也算完成
		if (!firstTime || _lsGet(DONE_KEY) !== "full") _lsSet(DONE_KEY, firstTime ? "intro" : "full");
		_syncEntry();
		_form().hidden = true;
		$("survey-thanks-intro").hidden = !firstTime;
		$("survey-thanks").hidden = false;
		submit.textContent = t("action.send");
	} catch {
		submit.textContent = t("action.sendFail");
		setTimeout(() => {
			submit.textContent = t("action.send");
			_syncForm();
		}, 3000);
	}
}

// ─── 首次进站提示卡 ──────────────────────────────────────────

function _hidePrompt() {
	const prompt = $("survey-prompt");
	if (prompt) prompt.hidden = true;
}

function _dismissPrompt() {
	_lsSet(PROMPTED_KEY, "1");
	_hidePrompt();
}

function _maybeShowPrompt() {
	const prompted = _lsGet(PROMPTED_KEY);
	// undefined = localStorage 不可用：不弹，免得每次进站都看到
	if (prompted === undefined || prompted === "1" || _lsGet(DONE_KEY)) return;
	setTimeout(() => {
		const prompt = $("survey-prompt");
		if (prompt && !$("survey-dialog")?.open) prompt.hidden = false;
	}, PROMPT_DELAY_MS);
}

// ─── 挂载 ────────────────────────────────────────────────────

function _bindOnce() {
	const dialog = $("survey-dialog");
	const form = _form();
	if (!dialog || !form || dialog.dataset.bound) return false;
	dialog.dataset.bound = "1";

	_buildQuestions($("survey-questions"));

	form.addEventListener("change", (e) => {
		const qid = e.target?.name;
		const q = QUESTIONS.find((x) => x.id === qid);
		if (q && (q.type === "multi" || q.type === "single")) _syncQuestion(q, e.target);
		_syncForm();
	});
	form.addEventListener("submit", _submit);

	$("survey-close")?.addEventListener("click", _close);
	$("survey-cancel")?.addEventListener("click", _close);
	$("survey-thanks-close")?.addEventListener("click", _close);

	$("survey-entry")?.addEventListener("click", () => {
		window.toggleVgaFeedback?.();
		openSurvey();
	});

	$("survey-prompt-open")?.addEventListener("click", () => {
		_dismissPrompt();
		openSurvey();
	});
	$("survey-prompt-dismiss")?.addEventListener("click", _dismissPrompt);
	$("survey-prompt-close")?.addEventListener("click", _dismissPrompt);
	// 打开反馈浮层时提示卡让位（不记为已处理，下次进站还会出现）
	$("vgaFeedbackBtn")?.addEventListener("click", _hidePrompt);
	return true;
}

/** Boot 时调用一次：生成题目、绑定事件、按需弹首次进站提示。 */
export function mountSurvey() {
	if (!_bindOnce()) return;
	_syncForm();
	_syncEntry();
	_maybeShowPrompt();
}
