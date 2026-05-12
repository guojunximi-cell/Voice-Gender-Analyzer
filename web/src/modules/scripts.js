// 跟读脚本预设
// ZH：选自村上春树、加西亚·马尔克斯、残雪、凡尔纳的经典段落，
//     长度 ~130-150 字，覆盖四声 + 前后鼻音 + 主要韵母空间，朗读约 50-80 s。
// EN：通用朗读材料，优先选择语音训练社区熟悉的文本（Rainbow Passage 等）——
//     覆盖全部英语元音与常见辅音组合，长度约 30-60 s，适合做 Engine C 对齐。
// FR：公版文学 + IPA 经典朗读样本（La bise et le soleil），覆盖 12 oral
//     元音 + 4 鼻元音（ɛ̃ ɑ̃ ɔ̃ œ̃）+ 前圆唇 (y ø œ)，朗读约 30-60 s。
// KO：北风과 태양 (IPA Handbook 韩语样本) + 公版文学（윤동주 / 김유정 /
//     주요섭），覆盖 7 单元音 × 短/长 + glide+vowel 二合，朗读约 30-60 s。

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

export const PRESET_SCRIPTS_KO = [
	{
		id: "bukpung-taeyang",
		title: "북풍과 태양 (IPA Handbook)",
		text: "북풍과 태양이 누가 더 힘이 센지 다투고 있을 때, 한 나그네가 따뜻한 외투를 입고 걸어왔습니다. 그래서 둘은 누구든 먼저 나그네의 외투를 벗기는 쪽이 더 세다고 하기로 했습니다. 그러자 북풍은 있는 힘껏 불었지만, 북풍이 거세게 불수록 나그네는 외투를 더 단단히 여몄습니다. 마침내 북풍은 포기했습니다. 이번에는 태양이 따뜻하게 비추기 시작했고, 나그네는 곧 외투를 벗어 버렸습니다. 그래서 북풍은 둘 중에 태양이 더 세다는 것을 인정할 수밖에 없었습니다.",
	},
	{
		id: "yun-byeol",
		title: "윤동주 · 별 헤는 밤",
		text: "계절이 지나가는 하늘에는 가을로 가득 차 있습니다. 나는 아무 걱정도 없이 가을 속의 별들을 다 헤일 듯합니다. 가슴 속에 하나 둘 새겨지는 별을 이제 다 못 헤는 것은 쉬이 아침이 오는 까닭이요, 내일 밤이 남은 까닭이요, 아직 나의 청춘이 다하지 않은 까닭입니다. 별 하나에 추억과 별 하나에 사랑과 별 하나에 쓸쓸함과 별 하나에 동경과 별 하나에 시와 별 하나에 어머니, 어머니.",
	},
	{
		id: "kim-spring",
		title: "김유정 · 동백꽃",
		text: "오늘도 또 우리 수탉이 막 쪼키었다. 내가 점심을 먹고 나무를 하러 갈 양으로 나올 때이었다. 산으로 올라서려니까 등 뒤에서 푸드덕푸드덕 하고 닭의 횃소리가 야단이다. 깜짝 놀라 고개를 돌려 보니 아니나다르랴, 두 놈이 또 얼이 빠져서 그 비탈 위에서 등을 잔뜩 일으키고 깃을 곤두세웠다. 동백꽃이 활짝 핀 노란 산기슭이었다.",
	},
	{
		id: "joo-friend",
		title: "주요섭 · 사랑손님과 어머니",
		text: "나는 금년 여섯 살 난 처녀애입니다. 내 이름은 박옥희이고요. 우리 집 식구라고는 세상에서 제일 예쁜 우리 어머니와 단 두 식구뿐이랍니다. 아차 큰일 났군, 외삼촌을 빼놓을 뻔했으니. 가만 있자, 그러니까 우리 집 식구는 어머니, 외삼촌, 그러고 나, 이렇게 세 식구입니다. 우리 어머니는 어떻게 곱고 어여쁜지 모르는 사람이 없답니다.",
	},
];

// Back-compat: old callers import PRESET_SCRIPTS directly. Keep it pointing at
// the zh-CN list so anything not yet language-aware still behaves.
export const PRESET_SCRIPTS = PRESET_SCRIPTS_ZH;

export function scriptsForLang(lang) {
	if (lang === "en-US") return PRESET_SCRIPTS_EN;
	if (lang === "fr-FR") return PRESET_SCRIPTS_FR;
	if (lang === "ko-KR") return PRESET_SCRIPTS_KO;
	return PRESET_SCRIPTS_ZH;
}

export function getDefaultScript(lang) {
	return scriptsForLang(lang)[0];
}

export function findScriptById(id, lang) {
	return scriptsForLang(lang).find((s) => s.id === id) ?? null;
}
