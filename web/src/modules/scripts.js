// 跟读脚本预设 — 中文短句，~18-22 字，覆盖四声 + 前后鼻音 + 主要韵母空间。
// 选用偏日常描写的句子，重复朗读不会产生心理负担。
// 新增/调整条目无需改后端——只影响 UI 展示。

export const PRESET_SCRIPTS = [
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

export function getDefaultScript() {
	return PRESET_SCRIPTS[0];
}

export function findScriptById(id) {
	return PRESET_SCRIPTS.find((s) => s.id === id) ?? null;
}
