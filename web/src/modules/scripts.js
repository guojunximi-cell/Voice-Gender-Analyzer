// 跟读脚本预设
// ZH：选自村上春树、加西亚·马尔克斯、残雪、凡尔纳的经典段落，
//     长度 ~130-150 字，覆盖四声 + 前后鼻音 + 主要韵母空间，朗读约 50-80 s。
// EN：通用朗读材料，优先选择语音训练社区熟悉的文本（Rainbow Passage 等）——
//     覆盖全部英语元音与常见辅音组合，长度约 30-60 s，适合做 Engine C 对齐。
// FR：公版文学 + IPA 经典朗读样本（La bise et le soleil），覆盖 12 oral
//     元音 + 4 鼻元音（ɛ̃ ɑ̃ ɔ̃ œ̃）+ 前圆唇 (y ø œ)，朗读约 30-60 s。

// "自定义" 槽位用这个 id；不在 PRESET_* 列表里 —— 文本由用户输入，
// main.js 在 dropdown 末尾单独追加这个选项。
export const CUSTOM_SCRIPT_ID = "custom";

export const PRESET_SCRIPTS_ZH = [
	{
		id: "mountain-hut",
		title: "残雪《山上的小屋》",
		text: "在我家屋后的荒山上，有一座木板搭起来的小屋。我反复地清理着抽屉里的东西，使它们排列得整整齐齐。然而每当我抬起头来，母亲总是恶狠狠地盯着我的后脑勺看。我每整理好一回抽屉，过一会儿就又乱了套。我听见有人在屋里翻动，发出沉重的喘息声。屋后的小山上，传来一阵又一阵狼一般的嗥叫声。",
	},
	{
		id: "kafka-storm",
		title: "村上春树《海边的卡夫卡》",
		text: "命运就像一种沙尘暴，当你穿越沙尘暴的时候，你只能埋着头一步一步地走过去。暴风雨结束以后，你不会记得自己是怎样活下来的，你甚至不能确定暴风雨真的已经结束了。但是有一件事情是确定的，当你穿过了暴风雨，你早已不再是原来那个人，这就是这场暴风雨的全部意义所在。",
	},
	{
		id: "macondo-opening",
		title: "马尔克斯《百年孤独》",
		text: "多年以后，面对行刑队，奥雷里亚诺上校将会回想起父亲带他去见识冰块的那个遥远的下午。那时的马孔多还是一个二十户人家的小村庄，一座座土房沿着清澈的河岸整齐地排开。河水流过遍布卵石的河床，卵石洁白光滑宛如史前巨蛋。这块天地是如此之新，许多东西尚未命名，提起的时候还须用手指指点点。",
	},
	{
		id: "twenty-thousand-leagues",
		title: "凡尔纳《海底两万里》",
		text: "我热爱大海，大海就是一切。它覆盖着地球表面十分之七的面积，它的呼吸纯洁而又清新。它是一片浩瀚无边的荒漠，但人在那里却永远不会感到孤独，因为他能感受到生命在身边轻轻颤动。大海不属于压迫者，在大海的表面，他们还能行使他们罪恶的权力，但是到了海面以下三十英尺的地方，他们的权力就停止了。",
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

export const PRESET_SCRIPTS_FR = [
	{
		id: "bise-et-soleil",
		title: "La bise et le soleil (IPA Handbook)",
		text: "La bise et le soleil se disputaient, chacun assurant qu'il était le plus fort, quand ils ont vu un voyageur qui s'avançait, enveloppé dans son manteau. Ils sont tombés d'accord que celui qui arriverait le premier à faire ôter son manteau au voyageur serait regardé comme le plus fort. Alors, la bise s'est mise à souffler de toute sa force, mais plus elle soufflait, plus le voyageur serrait son manteau autour de lui ; et à la fin, la bise a renoncé à le lui faire ôter.",
	},
	{
		id: "hugo-cosette",
		title: "Hugo · Les Misérables (Cosette)",
		text: "Cosette marchait sans se rendre compte de rien. Elle était toute petite et toute seule dans cette immense nuit noire. Elle traversait des rues vides, où il n'y avait personne, où les boutiques étaient fermées, où l'on n'entendait pas un bruit. La forêt était devant elle comme une grande chose noire. Elle entra dans le bois, le seau à la main, et elle se mit à courir, parce qu'elle avait peur.",
	},
	{
		id: "proust-madeleine",
		title: "Proust · La madeleine",
		text: "Et tout d'un coup le souvenir m'est apparu. Ce goût, c'était celui du petit morceau de madeleine que le dimanche matin à Combray, ma tante Léonie m'offrait après l'avoir trempé dans son infusion de thé ou de tilleul. La vue de la petite madeleine ne m'avait rien rappelé avant que je n'y eusse goûté ; peut-être parce que, en ayant souvent aperçu depuis, sans en manger, sur les tablettes des pâtissiers, leur image avait quitté ces jours de Combray.",
	},
	{
		id: "flaubert-yonville",
		title: "Flaubert · Madame Bovary (Yonville)",
		text: "On est, il faut le dire, sur les confins de la Normandie, de la Picardie et de l'Île-de-France, contrée bâtarde où le langage est sans accentuation, comme le paysage sans caractère. C'est là que l'on fait les pires fromages de Neufchâtel de tout l'arrondissement, et, d'autre part, la culture y est coûteuse, parce qu'il faut beaucoup de fumier pour engraisser ces terres friables, pleines de sable et de cailloux.",
	},
];

// Back-compat: old callers import PRESET_SCRIPTS directly. Keep it pointing at
// the zh-CN list so anything not yet language-aware still behaves.
export const PRESET_SCRIPTS = PRESET_SCRIPTS_ZH;

export function scriptsForLang(lang) {
	if (lang === "en-US") return PRESET_SCRIPTS_EN;
	if (lang === "fr-FR") return PRESET_SCRIPTS_FR;
	return PRESET_SCRIPTS_ZH;
}

export function getDefaultScript(lang) {
	return scriptsForLang(lang)[0];
}

export function findScriptById(id, lang) {
	return scriptsForLang(lang).find((s) => s.id === id) ?? null;
}
