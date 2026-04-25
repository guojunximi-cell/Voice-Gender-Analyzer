// 跟读脚本预设
// ZH：中文短句 ~18-22 字，覆盖四声 + 前后鼻音 + 主要韵母空间。
// EN：通用朗读材料，优先选择语音训练社区熟悉的文本（Rainbow Passage 等）——
//     覆盖全部英语元音与常见辅音组合，长度约 30-60 s，适合做 Engine C 对齐。

export const PRESET_SCRIPTS_ZH = [
	{
		id: "spring-birds",
		title: "春日晨景",
		text: "春天的早晨小鸟在树上快乐地唱着歌",
	},
	{
		id: "beach-kids",
		title: "海边沙滩",
		text: "海边的沙滩上孩子们光着脚丫追逐海浪",
	},
	{
		id: "grandpa-yard",
		title: "老院子",
		text: "爷爷坐在院子里的老槐树下安静地听收音机",
	},
	{
		id: "distant-bell",
		title: "远处钟声",
		text: "远处传来悠扬的钟声让人的心里感到十分平静",
	},
];

export const PRESET_SCRIPTS_EN = [
	{
		id: "rainbow-passage",
		title: "Rainbow Passage",
		text: "When the sunlight strikes raindrops in the air, they act as a prism and form a rainbow. The rainbow is a division of white light into many beautiful colors. These take the shape of a long round arch, with its path high above and its two ends apparently beyond the horizon.",
	},
	{
		id: "grandfather-passage",
		title: "Grandfather Passage",
		text: "You wished to know all about my grandfather. Well, he is nearly ninety-three years old. He dresses himself in an ancient black frock coat, usually minus several buttons. A long beard clings to his chin, giving those who observe him a pronounced feeling of the utmost respect.",
	},
	{
		id: "comma-gets-a-cure",
		title: "Comma Gets a Cure (opening)",
		text: "Well, here's a story for you. Sarah Perry was a veterinary nurse who had been working daily at an old zoo in a deserted district of the territory, so she was very happy to start a new job at a superb private practice in North Square near the Duke Street Tower.",
	},
	{
		id: "morning-coffee",
		title: "Morning coffee",
		text: "Every morning I make a small pot of coffee and sit by the window for a few quiet minutes. The birds outside are just waking up, and the soft light feels like a gentle reminder that the day is full of possibility.",
	},
];

// Back-compat: old callers import PRESET_SCRIPTS directly. Keep it pointing at
// the zh-CN list so anything not yet language-aware still behaves.
export const PRESET_SCRIPTS = PRESET_SCRIPTS_ZH;

export function scriptsForLang(lang) {
	return lang === "en-US" ? PRESET_SCRIPTS_EN : PRESET_SCRIPTS_ZH;
}

export function getDefaultScript(lang) {
	return scriptsForLang(lang)[0];
}

export function findScriptById(id, lang) {
	return scriptsForLang(lang).find((s) => s.id === id) ?? null;
}
