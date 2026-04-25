// 跟读脚本预设
// ZH：选自村上春树、加西亚·马尔克斯、残雪、凡尔纳的经典段落，
//     长度 ~70-90 字，覆盖四声 + 前后鼻音 + 主要韵母空间，朗读约 30-50 s。
// EN：通用朗读材料，优先选择语音训练社区熟悉的文本（Rainbow Passage 等）——
//     覆盖全部英语元音与常见辅音组合，长度约 30-60 s，适合做 Engine C 对齐。

export const PRESET_SCRIPTS_ZH = [
	{
		id: "kafka-storm",
		title: "村上春树《海边的卡夫卡》",
		text: "暴风雨结束以后，你不会记得自己是怎样活下来的，你甚至不能确定暴风雨真的已经结束了。但有一件事情是确定的，当你穿过了暴风雨，你早已不再是原来那个人。",
	},
	{
		id: "macondo-opening",
		title: "马尔克斯《百年孤独》",
		text: "多年以后，面对行刑队，奥雷里亚诺上校将会回想起父亲带他去见识冰块的那个遥远的下午。那时的马孔多还是一个二十户人家的小村庄，一座座土房沿着清澈的河岸整齐地排开。",
	},
	{
		id: "mountain-hut",
		title: "残雪《山上的小屋》",
		text: "在我家屋后的荒山上，有一座木板搭起来的小屋。我反复地清理着抽屉里的东西，使它们排列得整整齐齐。然而每当我抬起头，母亲总是恶狠狠地盯着我的后脑勺看。",
	},
	{
		id: "twenty-thousand-leagues",
		title: "凡尔纳《海底两万里》",
		text: "我热爱大海，大海就是一切。它覆盖着地球表面十分之七的面积，它的呼吸纯洁而又清新。它是一片浩瀚无边的荒漠，但人在那里却永远不会感到孤独，因为他能感受到生命在身边颤动。",
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
