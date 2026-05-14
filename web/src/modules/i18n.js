/**
 * i18n.js — UI 语言 + 分析管线语言。
 *
 * 一个简单的键值字典：zh-CN 是原版 UI，en-US / fr-FR 沿用同一套
 * gender-affirming 口吻：masculine/feminine、perceived、避免 pass/passing；
 * 法语 féminin / masculin / androgyne / neutre，避免 « passer »。
 *
 * 对外：
 *   t(key, params?) — 取当前语言下的字符串；`{name}` 占位由 params 注入。
 *   getLang() / setLang(code) — "zh-CN" | "en-US" | "fr-FR"
 *   onLangChange(cb) — 订阅变化（cb 收到新语言）
 *   applyStaticDom(root?) — 按 data-i18n* 属性刷新 root 下的文本；不传则整页。
 *
 * 语言写进 localStorage("vga.lang")；同一个语言同时决定：
 *   1. 界面文案（本文件 DICT）
 *   2. 示例稿件库（scripts.js 按语言取）
 *   3. POST /api/analyze-voice 的 `language` 表单字段（analyzer.js 读）
 */

const LS_KEY = "vga.lang";
export const SUPPORTED = ["zh-CN", "en-US", "fr-FR", "ko-KR"];

const DICT = {
	"zh-CN": {
		"app.title": "声音分析鸭 — 声音性别分析",
		"app.logoAria": "声音分析鸭 GitHub 仓库",
		"app.name": "声音分析鸭",
		"header.help": "使用帮助",
		"header.disclosure": "使用前须知",
		"header.theme": "切换主题",
		"header.lang": "切换语言 / Language / Langue",
		"header.langShort.zh": "中",
		"header.langShort.en": "EN",
		"header.langShort.fr": "FR",
		"header.langShort.ko": "한",
		"header.langName.zh": "中文",
		"header.langName.en": "English",
		"header.langName.fr": "Français",
		"header.langName.ko": "한국어",

		"panel.history": "历史分析",
		"panel.metrics": "综合声学特征",

		"scatter.modeAria": "历史排布",
		"scatter.mode.score": "倾向",
		"scatter.mode.time": "时间",
		"scatter.mode.scoreTip": "按性别倾向排布（默认）",
		"scatter.mode.timeTip": "按创建时间排布（最新在顶）",
		"scatter.tick.justNow": "刚才",
		"scatter.tick.minutesAgoFmt": "{n}m",
		"scatter.tick.hoursAgoFmt": "{n}h",
		"scatter.tick.dayAgo": "1天",
		"scatter.tick.daysAgoFmt": "{n}天",
		"scatter.tick.weekAgo": "1周",
		"scatter.tick.monthAgo": "1月",

		"action.delete": "删除此记录",
		"action.clear": "清空历史",
		"action.changeFile": "更换文件",
		"action.browse": "点击选择文件",
		"action.analyze": "开始分析",
		"action.analyzing": "分析中…",
		"action.analyzed": "已分析",
		"action.play": "播放",
		"action.pause": "暂停",
		"action.seekAria": "播放进度",
		"action.recordStart": "开始录制",
		"action.recordStartBig": "开始录制",
		"action.recordStop": "停止录制",
		"action.stop": "停止",
		"action.next": "换一段",
		"action.send": "发送",
		"action.sending": "发送中…",
		"action.sendOK": "发送成功",
		"action.sendFail": "发送失败",

		"upload.title": "拖拽音频文件到此处",
		"upload.or": "或",
		"upload.hint": "支持 MP3 · WAV · OGG · M4A · FLAC · 最大 {mb} MB / {min} 分钟",
		"upload.privacy": "服务器不留存音频与分析结果；历史记录保存在您本地浏览器，可随时清空",
		"upload.audioUnavailable": "原音频不可用（页面刷新后丢失）",

		"action.cancel": "取消",

		"import.button": "导入分析结果",
		"import.successFmt": "已导入 {name}",
		"import.successMultiFmt": "已导入 {n} 项历史记录",
		"import.errParse": "文件无法解析为 JSON",
		"import.errSchemaFmt": "导出格式版本不匹配（文件 {version}，当前 1）",
		"import.errMalformed": "导出文件缺少必要字段",
		"import.errTooLarge": "文件过大（{mb} MB，上限 {limit} MB）",
		"import.errTooManySessions": "文件包含 {n} 条记录，超过上限 {limit}",
		"export.button": "导出",
		"export.confirm": "导出",
		"export.dialogTitle": "导出分析结果",
		"export.scopeLabel": "范围",
		"export.scopeCurrent": "当前结果",
		"export.scopeAll": "全部历史",
		"export.scopeAllCountFmt": "（{n} 项）",
		"export.contentLabel": "内容",
		"export.includeAudio": "包含原音频",
		"export.includeEngineC": "包含 Engine C 音素数据",
		"export.alsoAudio": "同时单独导出原音频",
		"export.alsoAudioHintMulti": "（{n} 个文件）",
		"export.audioSizeFmt": "约 {size}",
		"export.audioSizeMultiFmt": "约 {n} 段共 {size}",
		"export.audioSizeNone": "（无音频）",
		"export.successFmt": "已导出 {name}（{size}）",
		"export.audioDownloadedFmt": "已另存 {n} 个原音频",
		"export.audioSkippedFmt": "{n} 个历史项缺少原音频，已跳过",
		"export.errNoData": "当前没有可导出的分析结果",
		"export.errEmptyHistory": "历史为空",

		"input.tabsAria": "选择输入方式",
		"input.tabUpload": "上传文件",
		"input.tabRecord": "麦克风录音",

		"record.modeLabel": "分析模式",
		"record.modeAria": "分析模式",
		"record.modeScript": "跟读稿件",
		"record.modeFree": "自由说话",
		"record.scriptTip": "跟读下方稿件——跳过语音识别，分析更快更稳",
		"record.freeTip": "自由朗读，由 AI 自动转写（较慢，占用更多资源）",
		"record.hint": "朗读上方文字；鸭鸭会直接按这段稿子对齐，不再跑语音识别。",
		"record.scriptPickerLabel": "选择稿件",
		"record.scriptPickerAria": "选择跟读稿件",
		"record.scriptCustom": "自定义稿件",
		"record.scriptCustomPlaceholder": "在这里写下你想朗读的稿子……",
		"record.customHint": "这段文字会直接喂给对齐器；请确保和「分析语言」一致，否则对不齐。",
		"record.scriptCustomEmpty": "请先在自定义稿件里填一些文字。",

		"stats.title": "声音占比",
		"stats.subtitle": "仅人声片段（音乐 / 静音不计入）",
		"stats.modeAria": "占比依据",
		"stats.modeA": "神经网络",
		"stats.modePitch": "音高",
		"stats.modeResonance": "共鸣",
		"stats.modeATip": "依 inaSpeechSegmenter 神经网络标签",
		"stats.modePitchTip": "依每个音素的基频（145 Hz 以下偏男 / 145–185 Hz 中性 / 185 Hz 以上偏女）",
		"stats.modeResonanceTip": "依每个音素的共鸣值（按当前语种的 cis 分布 p25/p75 划分男 / 中性 / 女）",
		"stats.lockedTip": "该文件无 Engine C 音素数据（可能 Engine C 未启用或失败）",
		"label.male": "男声",
		"label.neutral": "中性",
		"label.female": "女声",
		"label.other": "其他",
		"label.music": "音乐",
		"label.noise": "噪音",
		"label.silence": "静音",

		"dashboard.addBlock": "加块",
		"dashboard.hideBlock": "隐藏",
		"dashboard.resetLayout": "重置布局",
		"dashboard.toggleCollapse": "折叠 / 展开",
		"dashboard.editHint": "拖拽 ⋮⋮ 换位置 · 拖右下角拉伸",
		"dashboard.empty.segment": "点击音段查看",
		"dashboard.empty.analysis": "上传音频后查看",
		"dashboard.popoverEmpty": "全部已显示",
		"dashboard.block.pitch": "音高范围",
		"dashboard.block.formants": "共振峰",
		"dashboard.block.resonance": "元音共振",
		"dashboard.block.nn": "神经网络估计",
		"dashboard.block.stats": "占比分布",

		"metrics.emptyClick": "点击音段<br/>查看声学特征",
		"metrics.emptyUpload": "上传并分析音频<br/>查看整段声学平均",
		"metrics.noEngineC": "Engine C 未启用<br/>无法展示整段声学平均",
		"metrics.alignWarning": "对齐质量偏低，结果仅供参考。",
		"metrics.alignHintScript": "可能漏读或跳读；重录一次可改善。",
		"metrics.alignHintFree": "可能因噪音或语速导致对齐偏弱。",
		"metrics.alignPhoneRatio": "音素/汉字比 {ratio}",
		"metrics.alignCoverage": "覆盖 {pct}%",
		"metrics.cardPitch": "基频 PITCH",
		"metrics.cardResonance": "共鸣 RESONANCE",
		"metrics.pitchRangeTitle": "音高范围",
		"metrics.zoneMale": "男性 80~145 Hz",
		"metrics.zoneOverlap": "中间 145~185 Hz",
		"metrics.zoneFemale": "女性 185~255 Hz",
		"metrics.legendMale": "♂ 80~145 Hz",
		"metrics.legendNeutral": "♂♀ 145~185 Hz",
		"metrics.legendFemale": "♀ 185~255 Hz",
		"metrics.formantsTitle": "共振峰",
		"metrics.nnTitle": "神经网络估计",
		"metrics.nnDisclaimer":
			"此估计来自一个在大规模语音数据上训练的分类器。它反映的是「典型听者可能如何感知你的声音」，不代表你的身份。",
		"metrics.nnSegmentNote":
			"↑ 整段加权均值。分段详情里偏男/偏女交替是 AI 对中性区边界敏感的正常现象——不代表多说话者。",
		"metrics.headerOverall": "整段",
		"metrics.headerOverallSpeech": "整段 · 语音 {dur}",
		"metrics.disclaimer.prefix": "真挚感谢两个开源项目：神经网络分类器来自 ",
		"metrics.disclaimer.mid": " 音素级共振峰 z-score 链路来自 ",
		"metrics.disclaimer.forkLabel": "fork",

		"timeline.pitch": "音高",
		"timeline.resonance": "共鸣",
		"timeline.prevAria": "上一句",
		"timeline.nextAria": "下一句",
		"timeline.pagerAria": "句子分页",
		"timeline.readoutPitch": "音高",
		"timeline.readoutResonance": "共鸣",
		"timeline.pitchTitle": "{char} {phone} · 音高 {raw}",
		"timeline.pitchTitleInterp": "{char} {phone} · 音高 {raw} (字级推算 {interp} Hz)",
		"timeline.resonanceTitle": "{char} {phone} · 共鸣 {res}",
		"timeline.ariaPitch": "音高热力带，每个单位的音高（不发声辅音继承该单位的元音值）",
		"timeline.ariaPitchDesc": "当前页的音高热力带",
		"timeline.ariaResonance": "共鸣热力带，每格代表一个音素的共鸣值 0–1",
		"timeline.ariaResonanceDesc": "当前页的共鸣热力带；0.5 = 女性参考均值，女声阈值 = 0.587",
		"timeline.announceReady": "分析完成，共 {n} 个字",
		"timeline.returnToCurrent": "回到当前",
		"timeline.barModePhone": "音素",
		"timeline.barModeWord": "整词平均",
		"timeline.barModeAria": "切换条形显示粒度：每音素一格 / 整词时长加权平均",
		"timeline.wordAvgLabel": "整词平均",

		"fallback.noTimelineTitle": "无法生成逐字时间轴",
		"fallback.noTimelineLead": "我们已经识别到音频，但未能完成逐字对齐分析。",
		"fallback.commonReasons": "常见原因",
		"fallback.reasonTooShort": "录音太短（建议 5 秒以上）",
		"fallback.reasonWrongLang": "录音语言与当前管线不匹配（请在顶部切换语言后重试）",
		"fallback.reasonNoise": "背景噪声过大",
		"fallback.reasonNoSpeech": "录音中没有清晰语音",
		"fallback.tips": "建议",
		"fallback.tipQuiet": "在安静环境中重新录制",
		"fallback.tipRead": "朗读一段 10~30 秒的文本",
		"fallback.tipMicDist": "保持与麦克风 15~25 cm 距离",
		"fallback.stillVisible": "您仍然可以查看波形和下方的神经网络估计。",
		"fallback.lowPhone": "仅检测到 {n} 个音素，统计可能不够稳定。建议录制至少 10 秒的连续语音以获得更可靠的分析。",
		"fallback.noSpeechTitle": "未检测到语音内容",
		"fallback.noSpeechLead": "音频中未找到可分析的语音。是否为纯背景音或乐器？",
		"fallback.noSpeechHint": "请录制一段包含说话内容的音频后重试。",

		"legend.azimuthAria": "共鸣色条说明",
		"legend.scienceAria": "色系科学依据",
		"legend.male": "男声方向",
		"legend.neutral": "中性",
		"legend.female": "女声方向",
		"legend.infoAria": "色系说明",
		"legend.sci1":
			"<strong>共鸣色条</strong>的 0.5 是<strong>女性参考均值</strong>（不是男女中线——实测男声 median ≈ 0.35–0.49，女声 median ≈ 0.65–0.81，因语言而异），女声阈值 = <strong>{res}</strong>。",
		"legend.sci2": "该阈值基于 AISHELL-3 语料库（134 男 + 134 女）的 10-fold 交叉验证，精度 <strong>0.900</strong>。",
		"legend.sci3":
			"<strong>音高参考</strong>：{neutral} Hz 为男声上限 / 女声下限交界，{fem} Hz 为声音训练常用的女声感知阈值。",
		"legend.sci4":
			"音高区间基于 cis 英语母语者的参考分布，不代表训练目标。很多 cis 女性 F0 长期低于 175 Hz——共鸣的重要性不亚于音高。",
		"legend.sciNote": "色值仅作方向参考，不是性别判定。",

		// Segment-level lean tag (waveform tooltip + NN block), keyed off
		// inaSpeechSegmenter confidence margins. Was advice.tone.* before
		// the advice block was retired.
		"tone.leans_feminine": "倾向偏女",
		"tone.leans_masculine": "倾向偏男",
		"tone.weakly_feminine": "轻微偏女",
		"tone.weakly_masculine": "轻微偏男",
		"tone.not_clearly_leaning": "倾向不明显",

		"advice.resonance.title": "共鸣表现",
		"advice.resonance.summary.clearly_below_female": "顺性别男性区间",
		"advice.resonance.summary.leans_male": "倾向于顺性别男性",
		"advice.resonance.summary.mid_neutral": "无性别区间",
		"advice.resonance.summary.leans_female": "顺性别女性区间",
		"advice.resonance.summary.at_ceiling": "顺性别女性区间",
		"advice.resonance.caveat.score_clamp": "共振评分上限 1.0，部分元音可能已封顶；看具体元音的 z 值更准。",
		"advice.resonance.caveat.low_alignment": "对齐质量较低，本次结果仅供参考。",
		"advice.resonance.section_title_all": "元音",
		"advice.resonance.consonants.toggle_vowels_only": "仅元音",
		"advice.resonance.consonants.toggle_all_phones": "包含辅音",
		"advice.resonance.consonants.tooltip":
			"辅音（鼻音 /m n ŋ/、半元音 /j w/ 等）的共振峰也反映声道共振状态，但训练目标通常聚焦元音。开启此项可看到全部 phone 的诊断分布。",
		"advice.resonance.consonants.aria_label": "是否在共鸣面板包含辅音",
		"advice.resonance.history.compare_with": "对比 {when} 的同稿录音",
		"advice.resonance.history.improved": "进步了",
		"advice.resonance.history.regressed": "退步了",
		"advice.resonance.history.no_prior": "暂无同稿历史可对比",
		"advice.resonance.history.pitch_compensation":
			"⚠ NN 评分上升，但多数元音的共振细节在退步——可能是用提高音调代替了真正的共振调整。建议：保持下颌放松、软腭抬起，重点练 /a/ /o/。",

		"disclosure.title": "使用前请先了解",
		"disclosure.intro": "这个工具帮你测量声音的几个声学指标，作为练习参考。它不是诊断、不是评分、不是替代专业老师。",
		"disclosure.point.measurement": "显示的是测量值，不是给你的指令——具体怎么练你说了算。",
		"disclosure.point.model_judgment": "数字是模型判断，不一定等同于人耳听感。模型在某些声音上会出错。",
		"disclosure.point.not_teacher": "不替代 voice teacher / SLP——这些数字读不出技巧细节，老师可以。",
		"disclosure.point.dysphoria": "如果当下情绪不太稳，结果可能让你感觉更糟。可以先关掉，状态好一点再回来。",
		"disclosure.resources.heading": "推荐资源",
		"disclosure.resources.transvoice_note": "— Zheanna Erose 的频道，TVT 社区最常推荐的入门教学。",
		"disclosure.resources.sumian_note": "— Sumian 的频道，覆盖 resonance / pitch / weight 等技巧。",
		"disclosure.acknowledge": "我已了解，开始使用",
		"disclosure.close": "关闭",

		"duck.msg1": "正在聆听声纹…",
		"duck.msg2": "鸭鸭努力工作中…",
		"duck.msg3": "鸭鸭竖起了耳朵…",
		"duck.msg4": "鸭鸭在分析音高特征…",
		"duck.msg5": "鸭鸭在计算共振峰…",
		"duck.msg6": "鸭鸭快好了…",
		"duck.done": "分析完成 🎉",
		"duck.running": "正在分析…",

		"toast.cancelled": "分析超时，请尝试较短的音频文件",
		"toast.failedFmt": "分析失败：{msg}",
		"toast.batchFmt": "批量分析完成：{ok} / {total} 个成功",
		"toast.batchItemFmt": "{name} 失败：{msg}",
		"toast.confirmClear": "清空所有历史分析记录？",
		"toast.processing": "处理中…",
		"toast.hideFeedback": "已隐藏反馈按钮（URL 加 ?feedback=1 可恢复）",

		"progress.queued": "排队等候中",
		"progress.queuedNext": "马上轮到您了…",
		"progress.queuedCount": "排队中，前面还有 {n} 人",
		"progress.processing": "鸭鸭正在处理音频…",
		"progress.listening": "鸭鸭正在聆听声纹…（此步骤较慢）",
		"progress.organizing": "鸭鸭听完了！正在整理笔记…",
		"progress.loadAudio": "鸭鸭正在载入音频…",
		"progress.analyseSegment": "鸭鸭在分析第 {i}/{total} 段…",
		"progress.engineCScript": "鸭鸭照着稿子逐字对齐…",
		"progress.engineCFree": "鸭鸭开小灶做进阶分析…",
		"progress.almostDone": "鸭鸭快好了…",

		"recorder.noPermission": "请允许麦克风权限后重试",
		"recorder.noDevice": "未找到麦克风设备",
		"recorder.noAccess": "无法访问麦克风",
		"recorder.recordError": "录制出错：{msg}",
		"recorder.empty": "录音内容为空，请重新录制",
		"recorder.filenamePrefix": "录音",
		"recorder.idleHint": "最长录制 3 分钟；录完会自动跳到分析按钮。",

		"upload.errEmpty": "文件内容为空，请重新选择。",
		"upload.errUnsupported": "不支持的格式：{fmt}。请上传音频文件。",
		"upload.errUnknown": "未知",
		"upload.errTooLarge": "文件过大（{mb} MB），当前模式最大支持 {limit} MB。",
		"upload.errNoFile": "未选择文件",
		"analyzer.noTaskId": "后端未返回 task_id",
		"analyzer.needOnProgress": "analyzeAudio 需要 onProgress 回调才能订阅进度流",
		"analyzer.submitFailed": "请求失败 ({status})",
		"analyzer.streamFailed": "订阅进度失败 ({status})",
		"analyzer.backendError": "后端分析出错",
		"analyzer.noResult": "未收到分析结果",

		"audioGate.clipping": "削波严重（{pct}% 样本饱和），请降低录音音量后重试",
		"audioGate.tooQuiet": "音量过低（RMS {db} dBFS），请靠近麦克风或调高输入增益",
		"audioGate.silence": "音频几乎没有声音，请检查麦克风是否被静音",
		"audioGate.insufficientVoicing": "有效语音占比过低（{pct}%），请录制连续说话的片段",

		"feedback.title": "意见反馈",
		"feedback.email": "您的邮箱（选填）",
		"feedback.placeholder": "输入您的反馈或建议…",
		"feedback.btnAria": "意见反馈（长按隐藏）",
		"feedback.btnTitle": "长按隐藏此按钮",
		"feedback.close": "关闭",

		"help.title": "🦆 声音分析鸭 · 使用说明",
		"help.what.h": "这是什么？",
		"help.what.p":
			"上传或录制中文 / 英文 / 法文音频，分析声音的性别声学特征。中央时间轴展示逐音素的音高与共鸣，右侧给出整段中位数。仅作练声参考，不是判定。",
		"help.what.engineA.h": "Engine A · 音色参考",
		"help.what.engineA.desc": "inaSpeechSegmenter K-3 fork · CNN 分类器，输出整段女性化分数",
		"help.what.engineC.h": "Engine C · 主线 · 音素级",
		"help.what.engineC.desc": "ASR + Montreal Forced Aligner + Praat 共振峰，按音素出 pitch / resonance",
		"help.what.beta": "beta · 迭代中",
		"help.flow.h": "分析流程",
		"help.flow.s1.h": "上传 / 录音",
		"help.flow.s1.note":
			"拖拽音频、选择文件，或调用麦克风（≤ {mb} MB，< {min} 分钟，中文 zh-CN / 英文 en-US / 法文 fr-FR）",
		"help.flow.s2.h": "VAD 分段",
		"help.flow.s2.note": "Engine A · inaSpeechSegmenter K-3 神经网络分出语音 / 音乐 / 静音",
		"help.flow.s3.h": "文本对齐",
		"help.flow.s3.note":
			"Engine C · 自由模式跑 ASR（FunASR / faster-whisper），跟稿模式直接用您的稿子；Montreal Forced Aligner 对齐到音素",
		"help.flow.s4.h": "共振峰 + z-score",
		"help.flow.s4.note": "Praat 提 F1 / F2 / F3 → z-score 归一为共鸣值；整段聚合用「每元音 median 再取中位数」",
		"help.flow.s5.h": "三面板渲染",
		"help.flow.s5.note": "波形 · 中央三明治时间轴 · 右侧整段均值",
		"help.how.h": "如何使用？",
		"help.how.1": "拖拽音频 / 点击上传 / 录音（≤ {mb} MB，< {min} 分钟）",
		"help.how.2": "点击「开始分析」，等待鸭子跑完进度条",
		"help.how.3": "三块面板自动填充，无需额外点击",
		"help.heatmap.h": "术语",
		"help.heatmap.resonanceDT": "共鸣",
		"help.heatmap.resonanceDD":
			"音素内的共鸣，仅在元音上计算，由 F1 / F2 / F3 加权 + z-score 归一。Baseline 来自 cis 录音的分布参考（详见下表）。",
		"help.heatmap.resonance.credit": "算法来自",
		"help.heatmap.pitchDT": "音高",
		"help.heatmap.pitchDD":
			"音素内的 F0（pyin，60–250 Hz）。听感上最容易识别，但不是唯一线索——F0 抬上去而 resonance 没跟上，听起来通常是「捏着嗓子」，把两条热力图对照看比单看 F0 更有用。",
		"help.baseline.h": "参考分布",
		"help.baseline.note": "男女分布严重重叠 — 数字偏哪一侧不构成判定。calibration_v1，每语种 ~90 段 cis 录音。",
		"help.baseline.col.lang": "语种",
		"help.baseline.col.male": "男声 中位数 (p25–p75)",
		"help.baseline.col.female": "女声 中位数 (p25–p75)",
		"help.overall.h": "整段分析",
		"help.overall.note": "时间轴是音素级测量，右侧是整段聚合。聚合方式见下：",
		"help.aggregate.h": "聚合方式",
		"help.aggregate.f0.h": "F0",
		"help.aggregate.f0.body": "pyin 中位数 + p25 / p75",
		"help.aggregate.resonance.h": "共鸣",
		"help.aggregate.resonance.body": "每元音 median 再取中位数（每元音等权，避免高频元音压全局）",
		"help.aggregate.formant.h": "F1 / F2 / F3",
		"help.aggregate.formant.body": "有效帧均值",
		"help.qa.h": "常见问题",
		"help.qa.q1": "先看哪里？",
		"help.qa.a1":
			"看中央时间轴上 resonance 和 pitch 的热力图。右侧 NN 那个百分比已经降级成音色参考——不准，别盯着它练。Resonance / pitch 是音素级直接测量，这才是能指导练习的东西。",
		"help.qa.q2": "两个引擎分歧？",
		"help.qa.a2":
			"信 resonance 和 pitch（Engine C）。它们对不上 NN（Engine A）是正常的——测的不是同一个东西。更有用的问法是「resonance 和 pitch 自己之间对得上吗」。如果 pitch 已经上去但 resonance 还偏低，说明抬了音高但共鸣腔还没改，这就是下一步的方向。",
		"help.qa.q3": '"Other" 是什么？',
		"help.qa.a3": "停顿、呼吸、或者引擎没法判断的片段。",
		"help.qa.q4": "我现实里 pass，但工具说我是 masc，怎么回事？",
		"help.qa.a4": "工具是错的，你没问题。",
		"help.qa.q5": "那这工具到底有什么用？",
		"help.qa.a5":
			"看每个元音的 resonance 和 pitch 在时间轴上的变化。「这个 a 很亮，那个 a 塌回去了」。这种细节耳朵很难抓到，但热力图能看出来。",
		"help.qa.q6": "音频限制？",
		"help.qa.a6": "≤ 5 MB，< 3 分钟。30 秒以上、安静、单人录音效果最好。",
		"help.qa.q7": "语言切换？",
		"help.qa.a7": "右上角依次切换 zh-CN / en-US / fr-FR。",
		"help.qa.q8": "数据会留吗？",
		"help.qa.a8": "服务器不保存任何东西。",
		"help.qa.q9": "手机能用吗？",
		"help.qa.a9": "能，但建议横屏打开看时间轴。",
		"help.links.h": "友情链接",
		"help.links.projGroup": "项目自身",
		"help.links.creditsGroup": "技术致谢",
		"help.links.repo": "GitHub 仓库",
		"help.links.issues": "提交反馈 / Issue",
		"help.links.ina": "inaSpeechSegmenter（K-3 fork）",
		"help.links.gvv": "gender-voice-visualization",
		"help.links.mfa": "Montreal Forced Aligner",
		"help.links.praat": "Praat",
		"help.links.funasr": "FunASR",
		"help.links.whisper": "faster-whisper",
	},

	"en-US": {
		"app.title": "Voiceduck — voice analysis for gender-affirming training",
		"app.logoAria": "Voiceduck GitHub repository",
		"app.name": "Voiceduck",
		"header.help": "Help",
		"header.disclosure": "Before you start",
		"header.theme": "Toggle theme",
		"header.lang": "Switch language / 切换语言 / Langue",
		"header.langShort.zh": "中",
		"header.langShort.en": "EN",
		"header.langShort.fr": "FR",
		"header.langShort.ko": "한",
		"header.langName.zh": "中文",
		"header.langName.en": "English",
		"header.langName.fr": "Français",
		"header.langName.ko": "한국어",

		"panel.history": "Past sessions",
		"panel.metrics": "Acoustic summary",

		"scatter.modeAria": "History layout",
		"scatter.mode.score": "Tendency",
		"scatter.mode.time": "Time",
		"scatter.mode.scoreTip": "Lay out by gender tendency (default)",
		"scatter.mode.timeTip": "Lay out by creation time (newest on top)",
		"scatter.tick.justNow": "Now",
		"scatter.tick.minutesAgoFmt": "{n}m",
		"scatter.tick.hoursAgoFmt": "{n}h",
		"scatter.tick.dayAgo": "1d",
		"scatter.tick.daysAgoFmt": "{n}d",
		"scatter.tick.weekAgo": "1w",
		"scatter.tick.monthAgo": "1mo",

		"action.delete": "Remove this session",
		"action.clear": "Clear history",
		"action.changeFile": "Choose another file",
		"action.browse": "browse for a file",
		"action.analyze": "Analyze",
		"action.analyzing": "Analyzing…",
		"action.analyzed": "Analyzed",
		"action.play": "Play",
		"action.pause": "Pause",
		"action.seekAria": "Playback position",
		"action.recordStart": "Start recording",
		"action.recordStartBig": "Start recording",
		"action.recordStop": "Stop recording",
		"action.stop": "Stop",
		"action.next": "Next Script",
		"action.send": "Send",
		"action.sending": "Sending…",
		"action.sendOK": "Sent",
		"action.sendFail": "Send failed",

		"upload.title": "Drop an audio file here",
		"upload.or": "or",
		"upload.hint": "MP3 · WAV · OGG · M4A · FLAC — up to {mb} MB / {min} min",
		"upload.privacy":
			"Audio and results are never kept on the server. History stays in your browser and can be cleared any time.",
		"upload.audioUnavailable": "Original audio is no longer available (lost after reload)",

		"action.cancel": "Cancel",

		"import.button": "Import analysis result",
		"import.successFmt": "Imported {name}",
		"import.successMultiFmt": "Imported {n} session(s) into history",
		"import.errParse": "Could not parse the file as JSON.",
		"import.errSchemaFmt": "Export schema version mismatch (file {version}, current 1).",
		"import.errMalformed": "Exported file is missing required fields.",
		"import.errTooLarge": "File too large ({mb} MB, limit {limit} MB).",
		"import.errTooManySessions": "File contains {n} sessions, over the limit of {limit}.",
		"export.button": "Export",
		"export.confirm": "Export",
		"export.dialogTitle": "Export analysis result",
		"export.scopeLabel": "Scope",
		"export.scopeCurrent": "Current result",
		"export.scopeAll": "All history",
		"export.scopeAllCountFmt": "({n} sessions)",
		"export.contentLabel": "Content",
		"export.includeAudio": "Include original audio",
		"export.includeEngineC": "Include Engine C phone-level data",
		"export.alsoAudio": "Also download audio file(s)",
		"export.alsoAudioHintMulti": "({n} files)",
		"export.audioSizeFmt": "~{size}",
		"export.audioSizeMultiFmt": "~{n} clips, {size}",
		"export.audioSizeNone": "(no audio)",
		"export.successFmt": "Exported {name} ({size})",
		"export.audioDownloadedFmt": "Saved {n} audio file(s)",
		"export.audioSkippedFmt": "{n} session(s) missing audio, skipped",
		"export.errNoData": "No analysis result available to export.",
		"export.errEmptyHistory": "History is empty.",

		"input.tabsAria": "Choose input method",
		"input.tabUpload": "Upload file",
		"input.tabRecord": "Record from mic",

		"record.modeLabel": "Analysis mode",
		"record.modeAria": "Analysis mode",
		"record.modeScript": "Read a script",
		"record.modeFree": "Free speech",
		"record.scriptTip": "Read the script below — skips ASR, alignment is faster and steadier.",
		"record.freeTip": "Speak freely, transcribed automatically (slower, more CPU).",
		"record.hint": "Read the text above. We feed your script straight to the aligner — no speech-to-text step.",
		"record.scriptPickerLabel": "Script",
		"record.scriptPickerAria": "Pick a script to read",
		"record.scriptCustom": "Custom script",
		"record.scriptCustomPlaceholder": "Type the script you want to read aloud…",
		"record.customHint":
			"We feed this text straight to the aligner — make sure it matches the analysis language or it won't line up.",
		"record.scriptCustomEmpty": "Type some text in the custom script first.",

		"stats.title": "Distribution",
		"stats.subtitle": "Within voiced speech only — music / silence excluded",
		"stats.modeAria": "Classification basis",
		"stats.modeA": "Neural net",
		"stats.modePitch": "Pitch",
		"stats.modeResonance": "Resonance",
		"stats.modeATip": "Labels from the inaSpeechSegmenter neural classifier.",
		"stats.modePitchTip": "Per-phone F0 — masc < 145 Hz, neutral 145–185 Hz, fem > 185 Hz.",
		"stats.modeResonanceTip":
			"Per-phone resonance — split by the current language's cis-distribution p25 / p75 into masc / neutral / fem.",
		"stats.lockedTip": "No Engine C phone data for this file (Engine C off or failed).",
		"label.male": "Masc",
		"label.neutral": "Neutral",
		"label.female": "Fem",
		"label.other": "Other",
		"label.music": "Music",
		"label.noise": "Noise",
		"label.silence": "Silent",

		"dashboard.addBlock": "Add block",
		"dashboard.hideBlock": "Hide block",
		"dashboard.resetLayout": "Reset layout",
		"dashboard.toggleCollapse": "Collapse / expand",
		"dashboard.editHint": "Drag ⋮⋮ to move · drag bottom-right to resize",
		"dashboard.empty.segment": "Click a segment to populate",
		"dashboard.empty.analysis": "Upload audio first",
		"dashboard.popoverEmpty": "All blocks visible",
		"dashboard.block.pitch": "Pitch range",
		"dashboard.block.formants": "Formants",
		"dashboard.block.resonance": "Resonance",
		"dashboard.block.nn": "NN estimate",
		"dashboard.block.stats": "Distribution",

		"metrics.emptyClick": "Click a segment<br/>to see its acoustic detail",
		"metrics.emptyUpload": "Upload and analyze audio<br/>to see the whole-file averages",
		"metrics.noEngineC": "Engine C is off<br/>no whole-file averages to show",
		"metrics.alignWarning": "Alignment quality is low — treat the numbers as indicative only.",
		"metrics.alignHintScript": "Script may have been skipped or misread — a fresh take usually helps.",
		"metrics.alignHintFree": "Noise or pacing may have weakened the alignment.",
		"metrics.alignPhoneRatio": "phones/chars {ratio}",
		"metrics.alignCoverage": "coverage {pct}%",
		"metrics.cardPitch": "Pitch (F0)",
		"metrics.cardResonance": "Resonance",
		"metrics.pitchRangeTitle": "Pitch range",
		"metrics.zoneMale": "Masculine-typical 80–145 Hz",
		"metrics.zoneOverlap": "Overlap zone 145–185 Hz",
		"metrics.zoneFemale": "Feminine-typical 185–255 Hz",
		"metrics.legendMale": "Masc 80–145 Hz",
		"metrics.legendNeutral": "Mixed 145–185 Hz",
		"metrics.legendFemale": "Fem 185–255 Hz",
		"metrics.formantsTitle": "Formants",
		"metrics.nnTitle": "Neural network estimate",
		"metrics.nnDisclaimer":
			"This estimate comes from inaSpeechSegmenter, an open-source classifier trained primarily on French broadcast audio. It reflects how one specific classifier, trained on one specific dataset, labelled this sample. Not your identity, not whether you 'pass'.",
		"metrics.nnSegmentNote":
			"* Duration-weighted average for the whole file. Alternating masculine/feminine labels in the segment list below are normal. The classifier is noisy near the boundary, not tracking multiple speakers.",
		"metrics.headerOverall": "Whole file",
		"metrics.headerOverallSpeech": "Whole file · speech {dur}",
		"metrics.disclaimer.prefix": "Built on two open-source projects: the neural classifier is ",
		"metrics.disclaimer.mid": ". The phone-level formant z-score pipeline is a ",
		"metrics.disclaimer.forkLabel": "fork",

		// Abbreviated as band-side column headers so the label gutter stays
		// narrow and the heatmap content keeps its honest width; the readout
		// row above spells out "Pitch" / "Resonance" in full for clarity.
		"timeline.pitch": "P.",
		"timeline.resonance": "R.",
		"timeline.prevAria": "Previous line",
		"timeline.nextAria": "Next line",
		"timeline.pagerAria": "Line pagination",
		"timeline.readoutPitch": "Pitch",
		"timeline.readoutResonance": "Resonance",
		"timeline.pitchTitle": "{char} {phone} · pitch {raw}",
		"timeline.pitchTitleInterp": "{char} {phone} · pitch {raw} (char-level {interp} Hz)",
		"timeline.resonanceTitle": "{char} {phone} · resonance {res}",
		"timeline.ariaPitch": "Pitch heatmap; color per character (unvoiced consonants inherit the vowel color).",
		"timeline.ariaPitchDesc": "Pitch heatmap for the current page",
		"timeline.ariaResonance": "Resonance heatmap; each cell is one phone's resonance value, 0–1.",
		"timeline.ariaResonanceDesc": "Resonance heatmap for the current page. 0.5 = female reference mean.",
		"timeline.announceReady": "Analysis complete, {n} characters shown",
		"timeline.returnToCurrent": "Jump to now",
		"timeline.barModePhone": "Phones",
		"timeline.barModeWord": "Word avg",
		"timeline.barModeAria": "Bar granularity: one rect per phone / one rect per word (duration-weighted average)",
		"timeline.wordAvgLabel": "word avg",

		"fallback.noTimelineTitle": "Couldn't build the phone-level timeline",
		"fallback.noTimelineLead": "We received the audio but couldn't finish phone-level alignment.",
		"fallback.commonReasons": "Common causes",
		"fallback.reasonTooShort": "Recording is too short (aim for 5+ seconds)",
		"fallback.reasonWrongLang":
			"Language mismatch — switch the language in the top bar to match your audio, then retry",
		"fallback.reasonNoise": "Too much background noise",
		"fallback.reasonNoSpeech": "No clear speech in the recording",
		"fallback.tips": "Suggestions",
		"fallback.tipQuiet": "Record again in a quiet room",
		"fallback.tipRead": "Read a passage of about 10–30 seconds",
		"fallback.tipMicDist": "Keep the mic 15–25 cm (6–10 in) from your mouth",
		"fallback.stillVisible": "The waveform and the neural estimate below are still available.",
		"fallback.lowPhone":
			"Only {n} phones detected — statistics may be unstable. Record at least 10 seconds of continuous speech for more reliable numbers.",
		"fallback.noSpeechTitle": "No speech detected",
		"fallback.noSpeechLead": "Nothing in the audio looks analyzable. Is it music or ambient noise?",
		"fallback.noSpeechHint": "Record a clip with clear speech and try again.",

		"legend.azimuthAria": "Resonance color key",
		"legend.scienceAria": "How the palette was calibrated",
		"legend.male": "Masculine-leaning",
		"legend.neutral": "Androgynous",
		"legend.female": "Feminine-leaning",
		"legend.infoAria": "Palette info",
		"legend.sci1":
			"<strong>Resonance 0.5</strong> is the <strong>female reference mean</strong>, not the male/female midline. Empirical medians: male ≈ 0.35–0.49, female ≈ 0.65–0.81 (language-dependent).",
		"legend.sci2":
			"Calibration uses the acousticgender.space English voice-training corpus; per-phone F₂/F₃/F₄ z-scores are combined with weights brute-forced on labeled speakers.",
		"legend.sci3":
			"<strong>Pitch reference:</strong> {neutral} Hz is the typical masculine-upper / feminine-lower boundary; {fem} Hz is a common perceptual threshold used in voice training.",
		"legend.sci4":
			"Pitch ranges come from cisgender English-speaking reference populations — they aren't training goals. Many cis women speak below 175 Hz and are read as women without issue. Resonance matters as much as pitch.",
		"legend.sciNote": "Colors are directional guidance, not a gender verdict.",

		"tone.leans_feminine": "Leans feminine",
		"tone.leans_masculine": "Leans masculine",
		"tone.weakly_feminine": "Slightly feminine",
		"tone.weakly_masculine": "Slightly masculine",
		"tone.not_clearly_leaning": "Not clearly leaning",

		"advice.resonance.title": "Resonance",
		"advice.resonance.summary.clearly_below_female": "Cis-male range",
		"advice.resonance.summary.leans_male": "Leans cis-male",
		"advice.resonance.summary.mid_neutral": "Androgynous range",
		"advice.resonance.summary.leans_female": "Cis-female range",
		"advice.resonance.summary.at_ceiling": "Cis-female range",
		"advice.resonance.caveat.score_clamp":
			"Resonance score caps at 1.0; some vowels may already be saturated. Per-vowel z is more diagnostic.",
		"advice.resonance.caveat.low_alignment": "Alignment quality is low — treat results as approximate.",
		"advice.resonance.section_title_all": "Vowels",
		"advice.resonance.consonants.toggle_vowels_only": "Vowels only",
		"advice.resonance.consonants.toggle_all_phones": "Include consonants",
		"advice.resonance.consonants.tooltip":
			"Consonants (nasals /m n ŋ/, glides /j w/, …) carry vocal-tract resonance information too, but training targets are typically vowels. Enable this to see the full per-phone diagnostic distribution.",
		"advice.resonance.consonants.aria_label": "Include consonants in the resonance panel",
		"advice.resonance.history.compare_with": "Compared with same-script recording {when}",
		"advice.resonance.history.improved": "Improved",
		"advice.resonance.history.regressed": "Slipped",
		"advice.resonance.history.no_prior": "No same-script prior recording yet",
		"advice.resonance.history.pitch_compensation":
			"⚠ Your NN score went up, but most vowels' resonance details slipped — you likely raised pitch (jaw/larynx tightening) instead of reshaping resonance. Try keeping the jaw relaxed, lift the soft palate, and focus on /a/ and /o/.",

		"disclosure.title": "Before you start",
		"disclosure.intro":
			"This tool measures a few acoustic features of your voice as a training reference. It isn't a diagnosis, a score, or a substitute for a teacher.",
		"disclosure.point.measurement":
			"You're seeing measurements, not instructions — what you do with them is up to you.",
		"disclosure.point.model_judgment":
			"The numbers are model output and don't always match what a human ear hears. The model gets some voices wrong.",
		"disclosure.point.not_teacher":
			"Not a replacement for a voice teacher or SLP — they can read technique details these numbers can't.",
		"disclosure.point.dysphoria":
			"If you're in a rough headspace, the readout may make it worse. It's fine to close this and come back when you're feeling steadier.",
		"disclosure.resources.heading": "Recommended resources",
		"disclosure.resources.transvoice_note":
			"— Zheanna Erose's channel, the most-recommended starting point in the TVT community.",
		"disclosure.resources.sumian_note": "— Sumian's channel, covering resonance / pitch / weight technique work.",
		"disclosure.acknowledge": "I understand — let's go",
		"disclosure.close": "Close",

		"duck.msg1": "Listening to the voiceprint…",
		"duck.msg2": "Quacking hard at the data…",
		"duck.msg3": "Duck is perking up its ears…",
		"duck.msg4": "Measuring pitch contours…",
		"duck.msg5": "Computing formants…",
		"duck.msg6": "Almost there…",
		"duck.done": "Analysis complete 🎉",
		"duck.running": "Analyzing…",

		"toast.cancelled": "Analysis timed out — try a shorter clip.",
		"toast.failedFmt": "Analysis failed: {msg}",
		"toast.batchFmt": "Batch done: {ok} / {total} succeeded",
		"toast.batchItemFmt": "{name} failed: {msg}",
		"toast.confirmClear": "Clear all saved sessions?",
		"toast.processing": "Processing…",
		"toast.hideFeedback": "Feedback button hidden (append ?feedback=1 to the URL to restore).",

		"progress.queued": "Queued, waiting for a worker…",
		"progress.queuedNext": "Almost your turn…",
		"progress.queuedCount": "Queued — {n} ahead of you",
		"progress.processing": "Preparing the audio…",
		"progress.listening": "Listening to the voiceprint… (this step is slow)",
		"progress.organizing": "Done listening — organizing notes…",
		"progress.loadAudio": "Loading audio…",
		"progress.analyseSegment": "Analyzing segment {i} of {total}…",
		"progress.engineCScript": "Aligning the script word-by-word…",
		"progress.engineCFree": "Running advanced phone-level analysis…",
		"progress.almostDone": "Almost done…",

		"recorder.noPermission": "Please grant microphone access and try again.",
		"recorder.noDevice": "No microphone found.",
		"recorder.noAccess": "Couldn't access the microphone.",
		"recorder.recordError": "Recording error: {msg}",
		"recorder.empty": "Nothing was recorded — please try again.",
		"recorder.filenamePrefix": "recording",
		"recorder.idleHint": "Up to 3 minutes; analysis starts as soon as you stop.",

		"upload.errEmpty": "The file is empty — please pick another.",
		"upload.errUnsupported": "Unsupported format: {fmt}. Please upload an audio file.",
		"upload.errUnknown": "unknown",
		"upload.errTooLarge": "File too large ({mb} MB). Current limit is {limit} MB.",
		"upload.errNoFile": "No file selected",
		"analyzer.noTaskId": "The backend did not return a task_id.",
		"analyzer.needOnProgress": "analyzeAudio requires an onProgress callback to subscribe to the progress stream.",
		"analyzer.submitFailed": "Request failed ({status})",
		"analyzer.streamFailed": "Could not subscribe to progress ({status})",
		"analyzer.backendError": "Backend analysis error",
		"analyzer.noResult": "No result received",

		"audioGate.clipping": "Audio is clipped ({pct}% of samples saturated). Lower the recording volume and try again.",
		"audioGate.tooQuiet": "Volume too low (RMS {db} dBFS). Move closer to the mic or raise the input gain.",
		"audioGate.silence": "The clip is nearly silent — check that your mic isn't muted.",
		"audioGate.insufficientVoicing":
			"Not enough speech detected ({pct}%). Please record a clip with continuous speaking.",

		"feedback.title": "Feedback",
		"feedback.email": "Your email (optional)",
		"feedback.placeholder": "Tell us what you think…",
		"feedback.btnAria": "Feedback (long-press to hide)",
		"feedback.btnTitle": "Long-press to hide this button",
		"feedback.close": "Close",

		"help.title": "🦆 Voiceduck · How to use",
		"help.what.h": "What is this?",
		"help.what.p":
			"Upload or record a Chinese / English / French clip and we analyze its gendered acoustic features. The center timeline shows per-phone pitch and resonance; the right side gives whole-file medians. Reference for voice training, not a verdict.",
		"help.what.engineA.h": "Engine A · Tonal reference",
		"help.what.engineA.desc": "inaSpeechSegmenter K-3 fork · CNN classifier; outputs the whole-file femininity score.",
		"help.what.engineC.h": "Engine C · Primary · phone-level",
		"help.what.engineC.desc": "ASR + Montreal Forced Aligner + Praat formants — pitch / resonance per phone.",
		"help.what.beta": "beta · iterating",
		"help.flow.h": "Pipeline",
		"help.flow.s1.h": "Upload / record",
		"help.flow.s1.note": "Drop a file, pick one, or use the mic (≤ {mb} MB, < {min} min; zh-CN / en-US / fr-FR).",
		"help.flow.s2.h": "VAD segmentation",
		"help.flow.s2.note": "Engine A · inaSpeechSegmenter K-3 splits speech / music / silence.",
		"help.flow.s3.h": "Text alignment",
		"help.flow.s3.note":
			"Engine C · free mode runs ASR (FunASR / faster-whisper); script mode uses your pasted text. Montreal Forced Aligner aligns to phones.",
		"help.flow.s4.h": "Formants + z-score",
		"help.flow.s4.note":
			"Praat extracts F1 / F2 / F3 → z-score normalizes into the resonance value; whole-file aggregation uses median-of-per-vowel-medians.",
		"help.flow.s5.h": "Three-panel render",
		"help.flow.s5.note": "Waveform · center sandwich timeline · right-side whole-file averages.",
		"help.how.h": "How to use",
		"help.how.1": "Drag a file, pick one, or record (≤ {mb} MB, < {min} min).",
		"help.how.2": "Press Analyze and wait for the duck progress bar.",
		"help.how.3": "The three panels fill in automatically, no extra clicks needed.",
		"help.heatmap.h": "Terminology",
		"help.heatmap.resonanceDT": "Resonance",
		"help.heatmap.resonanceDD":
			"Resonance within each phone, computed only on vowels, as a z-score-normalized weighted blend of F1 / F2 / F3. Baseline is a cis-voice reference distribution (table below).",
		"help.heatmap.resonance.credit": "Algorithm from",
		"help.heatmap.pitchDT": "Pitch",
		"help.heatmap.pitchDD":
			"F0 within each phone (pyin, 60–250 Hz). The most audible cue, but not the only one — F0 going up while resonance stays low usually sounds strained. Reading the two heatmaps side-by-side beats reading F0 alone.",
		"help.baseline.h": "Reference distributions",
		"help.baseline.note":
			"Distributions overlap heavily — which side a number leans on is not a verdict. calibration_v1, ~90 cis recordings per language.",
		"help.baseline.col.lang": "Language",
		"help.baseline.col.male": "Male median (p25–p75)",
		"help.baseline.col.female": "Female median (p25–p75)",
		"help.overall.h": "Whole-file analysis",
		"help.overall.note":
			"The timeline is phone-level measurement; the right side is whole-file aggregation. Aggregation methods below:",
		"help.aggregate.h": "Aggregation",
		"help.aggregate.f0.h": "F0",
		"help.aggregate.f0.body": "pyin median + p25 / p75",
		"help.aggregate.resonance.h": "Resonance",
		"help.aggregate.resonance.body":
			"Median of per-vowel medians (each vowel weighted equally, so high-frequency phones don't drag the global value).",
		"help.aggregate.formant.h": "F1 / F2 / F3",
		"help.aggregate.formant.body": "Mean across voiced frames",
		"help.qa.h": "FAQ",
		"help.qa.q1": "Where should I look first?",
		"help.qa.a1":
			"Look at the resonance and pitch heatmaps in the center timeline. The Neural Net percentage on the right has been downgraded to a tonal reference — it isn't accurate, don't train against it. Resonance / pitch are direct phone-level measurements; that's what can actually guide practice.",
		"help.qa.q2": "Two engines disagree?",
		"help.qa.a2":
			"Trust resonance and pitch (Engine C). It's normal for them to disagree with the NN (Engine A) — they aren't measuring the same thing. A more useful question is: do resonance and pitch agree with each other? If pitch has gone up but resonance is still low, that means vocal pitch went up but the resonant cavity hasn't changed yet — that's your next direction.",
		"help.qa.q3": 'What is "Other"?',
		"help.qa.a3": "Pauses, breath sounds, or segments the engine couldn't classify.",
		"help.qa.q4": "I get read as a woman in everyday life, but the tool says I'm masc — what's going on?",
		"help.qa.a4": "The tool is wrong; you're fine.",
		"help.qa.q5": "So what is this tool actually useful for?",
		"help.qa.a5":
			"Watching how each vowel's resonance and pitch change across the timeline. \"This 'a' sounds bright; that 'a' collapses.\" Your ear rarely catches that detail, but the heatmap makes it visible.",
		"help.qa.q6": "Audio limits?",
		"help.qa.a6": "≤ 5 MB, < 3 minutes. Best results: 30+ seconds, quiet room, single speaker.",
		"help.qa.q7": "How do I switch language?",
		"help.qa.a7": "Use the toggle in the top-right corner to cycle between zh-CN, en-US, and fr-FR.",
		"help.qa.q8": "Is my data kept?",
		"help.qa.a8": "The server saves nothing.",
		"help.qa.q9": "Does it work on mobile?",
		"help.qa.a9": "Yes, but landscape orientation is recommended for the timeline.",
		"help.links.h": "Links",
		"help.links.projGroup": "This project",
		"help.links.creditsGroup": "Tech credits",
		"help.links.repo": "GitHub repository",
		"help.links.issues": "Report an issue",
		"help.links.ina": "inaSpeechSegmenter (K-3 fork)",
		"help.links.gvv": "gender-voice-visualization",
		"help.links.mfa": "Montreal Forced Aligner",
		"help.links.praat": "Praat",
		"help.links.funasr": "FunASR",
		"help.links.whisper": "faster-whisper",
	},

	"fr-FR": {
		"app.title": "Voiceduck — analyse vocale pour le travail de la voix",
		"app.logoAria": "Dépôt GitHub de Voiceduck",
		"app.name": "Voiceduck",
		"header.help": "Aide",
		"header.disclosure": "À lire avant de commencer",
		"header.theme": "Changer de thème",
		"header.lang": "Changer de langue / Switch language / 切换语言",
		"header.langShort.zh": "中",
		"header.langShort.en": "EN",
		"header.langShort.fr": "FR",
		"header.langShort.ko": "한",
		"header.langName.zh": "中文",
		"header.langName.en": "English",
		"header.langName.fr": "Français",
		"header.langName.ko": "한국어",

		"panel.history": "Sessions précédentes",
		"panel.metrics": "Récapitulatif acoustique",

		"scatter.modeAria": "Disposition de l'historique",
		"scatter.mode.score": "Tendance",
		"scatter.mode.time": "Temps",
		"scatter.mode.scoreTip": "Disposer par tendance vocale (par défaut)",
		"scatter.mode.timeTip": "Disposer par date (les plus récentes en haut)",
		"scatter.tick.justNow": "Maintenant",
		"scatter.tick.minutesAgoFmt": "{n} min",
		"scatter.tick.hoursAgoFmt": "{n} h",
		"scatter.tick.dayAgo": "1 j",
		"scatter.tick.daysAgoFmt": "{n} j",
		"scatter.tick.weekAgo": "1 sem.",
		"scatter.tick.monthAgo": "1 mois",

		"action.delete": "Supprimer cette session",
		"action.clear": "Vider l'historique",
		"action.changeFile": "Choisir un autre fichier",
		"action.browse": "parcourir un fichier",
		"action.analyze": "Analyser",
		"action.analyzing": "Analyse en cours…",
		"action.analyzed": "Analysé",
		"action.play": "Lecture",
		"action.pause": "Pause",
		"action.seekAria": "Position de lecture",
		"action.recordStart": "Démarrer l'enregistrement",
		"action.recordStartBig": "Démarrer l'enregistrement",
		"action.recordStop": "Arrêter l'enregistrement",
		"action.stop": "Arrêter",
		"action.next": "Texte suivant",
		"action.send": "Envoyer",
		"action.sending": "Envoi…",
		"action.sendOK": "Envoyé",
		"action.sendFail": "Échec de l'envoi",

		"upload.title": "Déposez un fichier audio ici",
		"upload.or": "ou",
		"upload.hint": "MP3 · WAV · OGG · M4A · FLAC — jusqu'à {mb} Mo / {min} min",
		"upload.privacy":
			"Aucun audio ni résultat n'est conservé sur le serveur. L'historique reste dans votre navigateur et peut être vidé à tout moment.",
		"upload.audioUnavailable": "L'audio d'origine n'est plus disponible (perdu après actualisation)",

		"action.cancel": "Annuler",

		"import.button": "Importer un résultat d'analyse",
		"import.successFmt": "{name} importé",
		"import.successMultiFmt": "{n} session(s) importée(s) dans l'historique",
		"import.errParse": "Impossible d'analyser le fichier en JSON.",
		"import.errSchemaFmt": "Version d'export incompatible (fichier {version}, courante 1).",
		"import.errMalformed": "Le fichier exporté manque de champs obligatoires.",
		"import.errTooLarge": "Fichier trop volumineux ({mb} Mo, limite {limit} Mo).",
		"import.errTooManySessions": "Le fichier contient {n} sessions, au-delà de la limite de {limit}.",
		"export.button": "Exporter",
		"export.confirm": "Exporter",
		"export.dialogTitle": "Exporter le résultat d'analyse",
		"export.scopeLabel": "Portée",
		"export.scopeCurrent": "Résultat courant",
		"export.scopeAll": "Tout l'historique",
		"export.scopeAllCountFmt": "({n} sessions)",
		"export.contentLabel": "Contenu",
		"export.includeAudio": "Inclure l'audio d'origine",
		"export.includeEngineC": "Inclure les données phone-level d'Engine C",
		"export.alsoAudio": "Télécharger aussi le(s) fichier(s) audio",
		"export.alsoAudioHintMulti": "({n} fichiers)",
		"export.audioSizeFmt": "~{size}",
		"export.audioSizeMultiFmt": "~{n} extraits, {size}",
		"export.audioSizeNone": "(aucun audio)",
		"export.successFmt": "{name} exporté ({size})",
		"export.audioDownloadedFmt": "{n} fichier(s) audio enregistré(s)",
		"export.audioSkippedFmt": "{n} session(s) sans audio, ignorée(s)",
		"export.errNoData": "Aucun résultat disponible à exporter.",
		"export.errEmptyHistory": "L'historique est vide.",

		"input.tabsAria": "Choisir la source",
		"input.tabUpload": "Téléverser un fichier",
		"input.tabRecord": "Enregistrer au micro",

		"record.modeLabel": "Mode d'analyse",
		"record.modeAria": "Mode d'analyse",
		"record.modeScript": "Lire un texte",
		"record.modeFree": "Parole libre",
		"record.scriptTip":
			"Lisez le texte ci-dessous — pas de reconnaissance vocale, alignement plus rapide et plus stable.",
		"record.freeTip": "Parlez librement, transcription automatique (plus lent, plus de ressources).",
		"record.hint":
			"Lisez le texte ci-dessus. Nous le transmettons directement à l'aligneur — pas d'étape de reconnaissance vocale.",
		"record.scriptPickerLabel": "Texte",
		"record.scriptPickerAria": "Choisir un texte à lire",
		"record.scriptCustom": "Texte personnalisé",
		"record.scriptCustomPlaceholder": "Saisissez le texte que vous souhaitez lire à voix haute…",
		"record.customHint":
			"Ce texte est transmis tel quel à l'aligneur — assurez-vous qu'il correspond à la langue d'analyse, sinon l'alignement échouera.",
		"record.scriptCustomEmpty": "Saisissez d'abord du texte dans le champ personnalisé.",

		"stats.title": "Répartition",
		"stats.subtitle": "Uniquement segments parlés — musique / silence exclus",
		"stats.modeAria": "Critère de classification",
		"stats.modeA": "Réseau de neurones",
		"stats.modePitch": "Hauteur",
		"stats.modeResonance": "Résonance",
		"stats.modeATip": "Étiquettes du classificateur neuronal inaSpeechSegmenter.",
		"stats.modePitchTip": "F0 par phonème — masc < 145 Hz, neutre 145–185 Hz, fém > 185 Hz.",
		"stats.modeResonanceTip":
			"Résonance par phonème — répartition selon p25 / p75 de la distribution cis de la langue courante (masc / neutre / fém).",
		"stats.lockedTip": "Aucune donnée Engine C pour ce fichier (Engine C désactivé ou en échec).",
		"label.male": "Masc",
		"label.neutral": "Neutre",
		"label.female": "Fém",
		"label.other": "Autre",
		"label.music": "Musique",
		"label.noise": "Bruit",
		"label.silence": "Silence",

		"dashboard.addBlock": "Ajouter un bloc",
		"dashboard.hideBlock": "Masquer",
		"dashboard.resetLayout": "Réinitialiser",
		"dashboard.toggleCollapse": "Réduire / développer",
		"dashboard.editHint": "Glisser ⋮⋮ pour déplacer · coin inférieur droit pour redimensionner",
		"dashboard.empty.segment": "Cliquez un segment",
		"dashboard.empty.analysis": "Téléversez un audio d'abord",
		"dashboard.popoverEmpty": "Tous les blocs sont visibles",
		"dashboard.block.pitch": "Hauteur",
		"dashboard.block.formants": "Formants",
		"dashboard.block.resonance": "Résonance",
		"dashboard.block.nn": "Estimation NN",
		"dashboard.block.stats": "Répartition",

		"metrics.emptyClick": "Cliquez un segment<br/>pour voir son détail acoustique",
		"metrics.emptyUpload": "Téléversez et analysez un audio<br/>pour voir les moyennes globales",
		"metrics.noEngineC": "Engine C est désactivé<br/>aucune moyenne globale à afficher",
		"metrics.alignWarning": "La qualité d'alignement est faible — résultats à titre indicatif seulement.",
		"metrics.alignHintScript": "Texte peut-être sauté ou mal lu — refaire une prise aide souvent.",
		"metrics.alignHintFree": "Bruit ou rythme ont pu affaiblir l'alignement.",
		"metrics.alignPhoneRatio": "phonèmes/caractères {ratio}",
		"metrics.alignCoverage": "couverture {pct} %",
		"metrics.cardPitch": "Hauteur (F0)",
		"metrics.cardResonance": "Résonance",
		"metrics.pitchRangeTitle": "Plage de hauteur",
		"metrics.zoneMale": "Masculin typique 80–145 Hz",
		"metrics.zoneOverlap": "Zone de chevauchement 145–185 Hz",
		"metrics.zoneFemale": "Féminin typique 185–255 Hz",
		"metrics.legendMale": "Masc 80–145 Hz",
		"metrics.legendNeutral": "Mixte 145–185 Hz",
		"metrics.legendFemale": "Fém 185–255 Hz",
		"metrics.formantsTitle": "Formants",
		"metrics.nnTitle": "Estimation par réseau de neurones",
		"metrics.nnDisclaimer":
			"Cette estimation provient d'inaSpeechSegmenter, un classificateur open-source entraîné principalement sur de l'audio de radiodiffusion français. Elle reflète comment ce classificateur, entraîné sur ce jeu de données précis, étiquette cet échantillon. Pas votre identité, pas une note de « passing ».",
		"metrics.nnSegmentNote":
			"* Moyenne pondérée par durée sur tout le fichier. L'alternance masculin/féminin dans la liste des segments est normale : le classificateur est bruité près de la frontière, il ne suit pas plusieurs locuteur·ices.",
		"metrics.headerOverall": "Fichier complet",
		"metrics.headerOverallSpeech": "Fichier complet · parole {dur}",
		"metrics.disclaimer.prefix": "Construit sur deux projets open-source : le classificateur neuronal vient d'",
		"metrics.disclaimer.mid": ". Le pipeline de z-score formant phonème par phonème est un ",
		"metrics.disclaimer.forkLabel": "fork",

		// Abrégés en en-tête de colonne pour garder la gouttière étroite ; la
		// ligne de readout au-dessus écrit « Hauteur » / « Résonance » en entier.
		"timeline.pitch": "H.",
		"timeline.resonance": "R.",
		"timeline.prevAria": "Ligne précédente",
		"timeline.nextAria": "Ligne suivante",
		"timeline.pagerAria": "Pagination des lignes",
		"timeline.readoutPitch": "Hauteur",
		"timeline.readoutResonance": "Résonance",
		"timeline.pitchTitle": "{char} {phone} · hauteur {raw}",
		"timeline.pitchTitleInterp": "{char} {phone} · hauteur {raw} (mot {interp} Hz)",
		"timeline.resonanceTitle": "{char} {phone} · résonance {res}",
		"timeline.ariaPitch":
			"Carte thermique de la hauteur ; couleur par caractère (les consonnes non voisées héritent de la couleur de la voyelle).",
		"timeline.ariaPitchDesc": "Carte thermique de hauteur pour la page courante",
		"timeline.ariaResonance": "Carte thermique de résonance ; chaque cellule = un phonème, valeur 0–1.",
		"timeline.ariaResonanceDesc":
			"Carte thermique de résonance pour la page courante. 0,5 = moyenne référence féminine.",
		"timeline.announceReady": "Analyse terminée, {n} caractères affichés",
		"timeline.returnToCurrent": "Revenir au moment présent",
		"timeline.barModePhone": "Phonèmes",
		"timeline.barModeWord": "Moyenne mot",
		"timeline.barModeAria":
			"Granularité des barres : un rect par phonème / un rect par mot (moyenne pondérée par durée)",
		"timeline.wordAvgLabel": "moy. mot",

		"fallback.noTimelineTitle": "Impossible de construire la timeline phonème par phonème",
		"fallback.noTimelineLead": "L'audio a été reçu mais l'alignement phonème n'a pas pu aboutir.",
		"fallback.commonReasons": "Causes fréquentes",
		"fallback.reasonTooShort": "Enregistrement trop court (visez 5 s ou plus)",
		"fallback.reasonWrongLang":
			"Langue incorrecte — changez la langue dans la barre du haut pour qu'elle corresponde à l'audio, puis réessayez",
		"fallback.reasonNoise": "Trop de bruit de fond",
		"fallback.reasonNoSpeech": "Pas de parole claire dans l'enregistrement",
		"fallback.tips": "Conseils",
		"fallback.tipQuiet": "Réenregistrez dans une pièce calme",
		"fallback.tipRead": "Lisez un passage d'environ 10 à 30 secondes",
		"fallback.tipMicDist": "Gardez le micro à 15–25 cm (6–10 in) de la bouche",
		"fallback.stillVisible": "La forme d'onde et l'estimation neuronale ci-dessous restent disponibles.",
		"fallback.lowPhone":
			"Seuls {n} phonèmes détectés — les statistiques peuvent être instables. Enregistrez au moins 10 s de parole continue pour des chiffres plus fiables.",
		"fallback.noSpeechTitle": "Aucune parole détectée",
		"fallback.noSpeechLead": "Rien d'analysable dans l'audio. Est-ce de la musique ou un bruit ambiant ?",
		"fallback.noSpeechHint": "Enregistrez un extrait avec parole claire et réessayez.",

		"legend.azimuthAria": "Légende de couleur de résonance",
		"legend.scienceAria": "Comment la palette a été calibrée",
		"legend.male": "Tendance masculine",
		"legend.neutral": "Androgyne",
		"legend.female": "Tendance féminine",
		"legend.infoAria": "Info palette",
		"legend.sci1":
			"<strong>La résonance 0,5</strong> est la <strong>moyenne du référentiel féminin</strong>, pas la médiane masculin/féminin. Médianes empiriques : masculine ≈ 0,35–0,49, féminine ≈ 0,65–0,81 (selon la langue).",
		"legend.sci2":
			"Le calibrage utilise le corpus d'entraînement vocal acousticgender.space en anglais ; les z-scores phonème par phonème de F₂/F₃/F₄ sont combinés avec des poids déterminés par recherche exhaustive sur des locuteur·ices étiqueté·es.",
		"legend.sci3":
			"<strong>Référence de hauteur :</strong> {neutral} Hz est la frontière typique masculin-haut / féminin-bas ; {fem} Hz est un seuil perceptuel commun en travail de la voix.",
		"legend.sci4":
			"Les plages de hauteur viennent de populations cisgenres anglophones de référence — ce ne sont pas des objectifs d'entraînement. Beaucoup de femmes cis parlent sous 175 Hz et sont perçues comme femmes sans souci. La résonance compte autant que la hauteur.",
		"legend.sciNote": "Les couleurs sont une indication directionnelle, pas un verdict de genre.",

		"tone.leans_feminine": "Tendance féminine",
		"tone.leans_masculine": "Tendance masculine",
		"tone.weakly_feminine": "Légèrement féminine",
		"tone.weakly_masculine": "Légèrement masculine",
		"tone.not_clearly_leaning": "Tendance peu marquée",

		// TODO(fr): native review of resonance copy
		"advice.resonance.title": "Résonance",
		"advice.resonance.summary.clearly_below_female": "Plage cis-masculine",
		"advice.resonance.summary.leans_male": "Tendance cis-masculine",
		"advice.resonance.summary.mid_neutral": "Plage androgyne",
		"advice.resonance.summary.leans_female": "Plage cis-féminine",
		"advice.resonance.summary.at_ceiling": "Plage cis-féminine",
		"advice.resonance.caveat.score_clamp":
			"Le score de résonance plafonne à 1,0 ; certaines voyelles peuvent être saturées. Le z par voyelle est plus diagnostique.",
		"advice.resonance.caveat.low_alignment": "Qualité d'alignement faible — résultats à titre indicatif.",
		"advice.resonance.section_title_all": "Voyelles",
		"advice.resonance.consonants.toggle_vowels_only": "Voyelles seules",
		"advice.resonance.consonants.toggle_all_phones": "Avec consonnes",
		"advice.resonance.consonants.tooltip":
			"Les consonnes (nasales /m n ŋ/, semi-voyelles /j w/, …) reflètent aussi la résonance du conduit vocal, mais l'entraînement cible généralement les voyelles. Activez pour voir la distribution diagnostique de tous les phonèmes.",
		"advice.resonance.consonants.aria_label": "Inclure les consonnes dans le panneau de résonance",
		"advice.resonance.history.compare_with": "Comparé à l'enregistrement du même texte {when}",
		"advice.resonance.history.improved": "Progression",
		"advice.resonance.history.regressed": "Régression",
		"advice.resonance.history.no_prior": "Aucun enregistrement antérieur du même texte",
		"advice.resonance.history.pitch_compensation":
			"⚠ Votre score NN a augmenté, mais le détail des résonances voyelle par voyelle a régressé — vous avez sans doute monté le ton (mâchoire/larynx serrés) au lieu de remodeler la résonance. Détendez la mâchoire, soulevez le voile du palais, travaillez /a/ et /o/.",

		// TODO(fr): native review of disclosure copy
		"disclosure.title": "À lire avant de commencer",
		"disclosure.intro":
			"Cet outil mesure quelques caractéristiques acoustiques de votre voix, à titre de référence pour le travail vocal. Ce n'est ni un diagnostic, ni un score, ni un substitut à un·e enseignant·e.",
		"disclosure.point.measurement":
			"Vous voyez des mesures, pas des instructions — ce que vous en faites vous appartient.",
		"disclosure.point.model_judgment":
			"Les chiffres sont des sorties de modèle et ne correspondent pas toujours à ce que l'oreille humaine entend. Le modèle se trompe sur certaines voix.",
		"disclosure.point.not_teacher":
			"Ne remplace pas un·e enseignant·e vocal·e ou un·e orthophoniste — iels lisent des détails techniques que ces chiffres ne montrent pas.",
		"disclosure.point.dysphoria":
			"Si vous êtes dans une mauvaise passe émotionnelle, ces résultats peuvent vous faire du mal. Il est tout à fait correct de fermer et de revenir quand vous serez plus posé·e.",
		"disclosure.resources.heading": "Ressources recommandées",
		"disclosure.resources.transvoice_note":
			"— La chaîne de Zheanna Erose, la référence d'entrée la plus recommandée dans la communauté TVT.",
		"disclosure.resources.sumian_note":
			"— La chaîne de Sumian, qui couvre résonance / hauteur / weight et autres techniques.",
		"disclosure.acknowledge": "J'ai compris, on y va",
		"disclosure.close": "Fermer",

		"duck.msg1": "Le canard écoute la voix…",
		"duck.msg2": "Le canard travaille fort…",
		"duck.msg3": "Le canard tend l'oreille…",
		"duck.msg4": "Mesure des contours de hauteur…",
		"duck.msg5": "Calcul des formants…",
		"duck.msg6": "Presque fini…",
		"duck.done": "Analyse terminée 🎉",
		"duck.running": "Analyse en cours…",

		"toast.cancelled": "Délai d'analyse dépassé — essayez un extrait plus court.",
		"toast.failedFmt": "Échec de l'analyse : {msg}",
		"toast.batchFmt": "Lot terminé : {ok} / {total} réussis",
		"toast.batchItemFmt": "{name} a échoué : {msg}",
		"toast.confirmClear": "Effacer toutes les sessions enregistrées ?",
		"toast.processing": "Traitement…",
		"toast.hideFeedback": "Bouton de retour masqué (ajoutez ?feedback=1 à l'URL pour le restaurer).",

		"progress.queued": "En file d'attente, en attente d'un worker…",
		"progress.queuedNext": "Bientôt votre tour…",
		"progress.queuedCount": "En file d'attente — {n} devant vous",
		"progress.processing": "Préparation de l'audio…",
		"progress.listening": "Écoute de la voix… (étape lente)",
		"progress.organizing": "Écoute terminée — organisation des notes…",
		"progress.loadAudio": "Chargement de l'audio…",
		"progress.analyseSegment": "Analyse du segment {i} sur {total}…",
		"progress.engineCScript": "Alignement du texte mot par mot…",
		"progress.engineCFree": "Analyse phonème par phonème en cours…",
		"progress.almostDone": "Presque terminé…",

		"recorder.noPermission": "Veuillez autoriser l'accès au micro et réessayer.",
		"recorder.noDevice": "Aucun micro détecté.",
		"recorder.noAccess": "Accès au micro impossible.",
		"recorder.recordError": "Erreur d'enregistrement : {msg}",
		"recorder.empty": "Rien n'a été enregistré — réessayez.",
		"recorder.filenamePrefix": "enregistrement",
		"recorder.idleHint": "Jusqu'à 3 minutes ; l'analyse démarre dès l'arrêt.",

		"upload.errEmpty": "Le fichier est vide — choisissez-en un autre.",
		"upload.errUnsupported": "Format non pris en charge : {fmt}. Téléversez un fichier audio.",
		"upload.errUnknown": "inconnu",
		"upload.errTooLarge": "Fichier trop volumineux ({mb} Mo). Limite actuelle : {limit} Mo.",
		"upload.errNoFile": "Aucun fichier sélectionné",
		"analyzer.noTaskId": "Le backend n'a pas renvoyé de task_id.",
		"analyzer.needOnProgress": "analyzeAudio nécessite un callback onProgress pour s'abonner au flux de progression.",
		"analyzer.submitFailed": "Échec de la requête ({status})",
		"analyzer.streamFailed": "Impossible de s'abonner à la progression ({status})",
		"analyzer.backendError": "Erreur d'analyse côté backend",
		"analyzer.noResult": "Aucun résultat reçu",

		"audioGate.clipping":
			"Audio écrêté ({pct} % d'échantillons saturés). Baissez le volume d'enregistrement et réessayez.",
		"audioGate.tooQuiet": "Volume trop bas (RMS {db} dBFS). Rapprochez-vous du micro ou augmentez le gain d'entrée.",
		"audioGate.silence": "Le clip est presque silencieux — vérifiez que votre micro n'est pas coupé.",
		"audioGate.insufficientVoicing":
			"Pas assez de parole détectée ({pct} %). Enregistrez un extrait avec parole continue.",

		"feedback.title": "Retour",
		"feedback.email": "Votre e-mail (facultatif)",
		"feedback.placeholder": "Dites-nous ce que vous en pensez…",
		"feedback.btnAria": "Retour (appui long pour masquer)",
		"feedback.btnTitle": "Appui long pour masquer ce bouton",
		"feedback.close": "Fermer",

		"help.title": "🦆 Voiceduck · Mode d'emploi",
		"help.what.h": "C'est quoi ?",
		"help.what.p":
			"Téléversez ou enregistrez un audio chinois / anglais / français pour analyser ses caractéristiques acoustiques liées au genre. La timeline centrale montre la hauteur et la résonance par phonème ; le panneau de droite donne les médianes globales. Référence pour le travail de voix, pas un verdict.",
		"help.what.engineA.h": "Moteur A · Référence tonale",
		"help.what.engineA.desc": "inaSpeechSegmenter K-3 fork · classificateur CNN ; produit le score global de féminité.",
		"help.what.engineC.h": "Moteur C · Principal · niveau phonème",
		"help.what.engineC.desc": "ASR + Montreal Forced Aligner + formants Praat — pitch / résonance par phonème.",
		"help.what.beta": "bêta · en cours",
		"help.flow.h": "Pipeline",
		"help.flow.s1.h": "Téléverser / enregistrer",
		"help.flow.s1.note":
			"Déposez un fichier, choisissez-en un, ou utilisez le micro (≤ {mb} Mo, < {min} min ; zh-CN / en-US / fr-FR).",
		"help.flow.s2.h": "Segmentation VAD",
		"help.flow.s2.note": "Engine A · inaSpeechSegmenter K-3 sépare parole / musique / silence.",
		"help.flow.s3.h": "Alignement texte",
		"help.flow.s3.note":
			"Engine C · le mode libre lance une ASR (FunASR / faster-whisper) ; le mode lecture utilise votre texte tel quel. Montreal Forced Aligner aligne au phonème.",
		"help.flow.s4.h": "Formants + z-score",
		"help.flow.s4.note":
			"Praat extrait F1 / F2 / F3 → z-score normalisé en valeur de résonance ; agrégation globale par médiane des médianes par voyelle.",
		"help.flow.s5.h": "Rendu trois panneaux",
		"help.flow.s5.note": "Forme d'onde · timeline sandwich centrale · moyennes globales à droite.",
		"help.how.h": "Comment l'utiliser",
		"help.how.1": "Glissez un fichier, choisissez-en un, ou enregistrez (≤ {mb} Mo, < {min} min).",
		"help.how.2": "Cliquez Analyser et attendez la barre de progression du canard.",
		"help.how.3": "Les trois panneaux se remplissent automatiquement, sans clic supplémentaire.",
		"help.heatmap.h": "Terminologie",
		"help.heatmap.resonanceDT": "Résonance",
		"help.heatmap.resonanceDD":
			"Résonance par phonème, calculée sur les voyelles uniquement, à partir d'une combinaison pondérée et z-scorée de F1 / F2 / F3. La ligne de base provient d'un corpus de voix cis (cf. tableau ci-dessous).",
		"help.heatmap.resonance.credit": "Algorithme issu de",
		"help.heatmap.pitchDT": "Hauteur",
		"help.heatmap.pitchDD":
			"F0 par phonème (pyin, 60–250 Hz). C'est l'indice le plus audible, mais pas le seul — F0 qui monte sans que la résonance suive sonne souvent forcé. Mieux vaut lire les deux cartes thermiques côte à côte que la hauteur seule.",
		"help.baseline.h": "Distributions de référence",
		"help.baseline.note":
			"Les distributions se chevauchent fortement — un chiffre qui penche d'un côté n'est pas un verdict. calibration_v1, ~90 enregistrements cis par langue.",
		"help.baseline.col.lang": "Langue",
		"help.baseline.col.male": "Médiane masc. (p25–p75)",
		"help.baseline.col.female": "Médiane fém. (p25–p75)",
		"help.overall.h": "Analyse globale",
		"help.overall.note":
			"La timeline est une mesure au phonème ; le panneau de droite est une agrégation globale. Méthodes ci-dessous :",
		"help.aggregate.h": "Agrégation",
		"help.aggregate.f0.h": "F0",
		"help.aggregate.f0.body": "médiane pyin + p25 / p75",
		"help.aggregate.resonance.h": "Résonance",
		"help.aggregate.resonance.body":
			"Médiane des médianes par voyelle (chaque voyelle équipondérée, pour qu'une voyelle fréquente ne tire pas la valeur globale).",
		"help.aggregate.formant.h": "F1 / F2 / F3",
		"help.aggregate.formant.body": "Moyenne sur trames voisées",
		"help.qa.h": "FAQ",
		"help.qa.q1": "Où regarder en premier ?",
		"help.qa.a1":
			"Regardez les cartes thermiques de résonance et de hauteur sur la timeline centrale. Le pourcentage NN à droite a été rétrogradé en référence tonale — il n'est pas précis, ne vous entraînez pas dessus. Résonance / hauteur sont des mesures directes au phonème ; c'est ça qui peut guider la pratique.",
		"help.qa.q2": "Les deux moteurs ne sont pas d'accord ?",
		"help.qa.a2":
			"Faites confiance à la résonance et à la hauteur (Moteur C). C'est normal qu'elles divergent du NN (Moteur A) — elles ne mesurent pas la même chose. Question plus utile : la résonance et la hauteur sont-elles d'accord entre elles ? Si la hauteur est montée mais la résonance reste basse, c'est que la hauteur vocale est montée mais la cavité résonante n'a pas encore changé — voilà la prochaine direction.",
		"help.qa.q3": "C'est quoi « Other » ?",
		"help.qa.a3": "Pauses, sons de respiration, ou segments que le moteur n'a pas pu classer.",
		"help.qa.q4":
			"Je suis perçu·e comme femme dans la vie, mais l'outil dit que je suis masc — qu'est-ce qui se passe ?",
		"help.qa.a4": "L'outil se trompe ; tout va bien.",
		"help.qa.q5": "Alors à quoi sert vraiment cet outil ?",
		"help.qa.a5":
			"À observer comment la résonance et la hauteur de chaque voyelle évoluent dans le temps. « Ce ‹a› sonne lumineux ; cet autre ‹a› s'effondre. » L'oreille capte rarement ce détail, mais la carte thermique le rend visible.",
		"help.qa.q6": "Limites audio ?",
		"help.qa.a6": "≤ 5 Mo, < 3 minutes. Meilleurs résultats : 30 s+, pièce calme, un·e seul·e locuteur·ice.",
		"help.qa.q7": "Comment changer de langue ?",
		"help.qa.a7": "Utilisez le bouton en haut à droite pour passer entre zh-CN, en-US et fr-FR.",
		"help.qa.q8": "Mes données sont-elles conservées ?",
		"help.qa.a8": "Le serveur ne garde rien.",
		"help.qa.q9": "Ça marche sur mobile ?",
		"help.qa.a9": "Oui, mais l'orientation paysage est recommandée pour la timeline.",
		"help.links.h": "Liens",
		"help.links.projGroup": "Ce projet",
		"help.links.creditsGroup": "Crédits techniques",
		"help.links.repo": "Dépôt GitHub",
		"help.links.issues": "Signaler un problème",
		"help.links.ina": "inaSpeechSegmenter (fork K-3)",
		"help.links.gvv": "gender-voice-visualization",
		"help.links.mfa": "Montreal Forced Aligner",
		"help.links.praat": "Praat",
		"help.links.funasr": "FunASR",
		"help.links.whisper": "faster-whisper",
	},

	"ko-KR": {
		"app.title": "Voiceduck — 젠더 어퍼밍 음성 훈련을 위한 음향 분석",
		"app.logoAria": "Voiceduck GitHub 저장소",
		"app.name": "Voiceduck",
		"header.help": "도움말",
		"header.disclosure": "시작 전 안내",
		"header.theme": "테마 전환",
		"header.lang": "언어 전환 / Switch language / 切换语言",
		"header.langShort.zh": "中",
		"header.langShort.en": "EN",
		"header.langShort.fr": "FR",
		"header.langShort.ko": "한",
		"header.langName.zh": "中文",
		"header.langName.en": "English",
		"header.langName.fr": "Français",
		"header.langName.ko": "한국어",

		"panel.history": "이전 세션",
		"panel.metrics": "종합 음향 특성",

		"scatter.modeAria": "기록 배치",
		"scatter.mode.score": "성향",
		"scatter.mode.time": "시간",
		"scatter.mode.scoreTip": "음성 성향순으로 배치 (기본)",
		"scatter.mode.timeTip": "생성 시간순으로 배치 (최신이 위)",
		"scatter.tick.justNow": "방금",
		"scatter.tick.minutesAgoFmt": "{n}분",
		"scatter.tick.hoursAgoFmt": "{n}시간",
		"scatter.tick.dayAgo": "1일",
		"scatter.tick.daysAgoFmt": "{n}일",
		"scatter.tick.weekAgo": "1주",
		"scatter.tick.monthAgo": "1개월",

		"action.delete": "이 기록 삭제",
		"action.clear": "기록 모두 지우기",
		"action.changeFile": "다른 파일 선택",
		"action.browse": "파일 찾아보기",
		"action.analyze": "분석 시작",
		"action.analyzing": "분석 중…",
		"action.analyzed": "분석 완료",
		"action.play": "재생",
		"action.pause": "일시정지",
		"action.seekAria": "재생 위치",
		"action.recordStart": "녹음 시작",
		"action.recordStartBig": "녹음 시작",
		"action.recordStop": "녹음 정지",
		"action.stop": "정지",
		"action.next": "다른 텍스트",
		"action.send": "보내기",
		"action.sending": "전송 중…",
		"action.sendOK": "전송 완료",
		"action.sendFail": "전송 실패",

		"upload.title": "오디오 파일을 여기로 끌어다 놓으세요",
		"upload.or": "또는",
		"upload.hint": "MP3 · WAV · OGG · M4A · FLAC · 최대 {mb} MB / {min} 분",
		"upload.privacy": "서버에 오디오나 분석 결과를 저장하지 않습니다. 기록은 브라우저에만 보관되며 언제든 지울 수 있습니다.",
		"upload.audioUnavailable": "원본 오디오를 사용할 수 없습니다 (페이지 새로고침으로 사라짐)",

		"action.cancel": "취소",

		"import.button": "분석 결과 가져오기",
		"import.successFmt": "{name} 가져옴",
		"import.successMultiFmt": "기록 {n}건을 가져왔습니다",
		"import.errParse": "파일을 JSON으로 파싱할 수 없습니다",
		"import.errSchemaFmt": "내보내기 형식 버전이 맞지 않습니다 (파일 {version}, 현재 1)",
		"import.errMalformed": "내보내기 파일에 필수 필드가 없습니다",
		"import.errTooLarge": "파일이 너무 큽니다 ({mb} MB, 상한 {limit} MB)",
		"import.errTooManySessions": "파일에 {n}건이 들어 있어 상한 {limit}을 초과합니다",
		"export.button": "내보내기",
		"export.confirm": "내보내기",
		"export.dialogTitle": "분석 결과 내보내기",
		"export.scopeLabel": "범위",
		"export.scopeCurrent": "현재 결과",
		"export.scopeAll": "전체 기록",
		"export.scopeAllCountFmt": "({n}건)",
		"export.contentLabel": "내용",
		"export.includeAudio": "원본 오디오 포함",
		"export.includeEngineC": "Engine C 음소 데이터 포함",
		"export.alsoAudio": "원본 오디오를 별도로 내보내기",
		"export.alsoAudioHintMulti": "({n}개 파일)",
		"export.audioSizeFmt": "약 {size}",
		"export.audioSizeMultiFmt": "약 {n}개 클립, 총 {size}",
		"export.audioSizeNone": "(오디오 없음)",
		"export.successFmt": "{name} 내보냄 ({size})",
		"export.audioDownloadedFmt": "원본 오디오 {n}개를 별도 저장했습니다",
		"export.audioSkippedFmt": "{n}건의 기록에 원본 오디오가 없어 건너뜀",
		"export.errNoData": "내보낼 분석 결과가 없습니다",
		"export.errEmptyHistory": "기록이 비어 있습니다",

		"input.tabsAria": "입력 방식 선택",
		"input.tabUpload": "파일 업로드",
		"input.tabRecord": "마이크 녹음",

		"record.modeLabel": "분석 모드",
		"record.modeAria": "분석 모드",
		"record.modeScript": "원고 따라 읽기",
		"record.modeFree": "자유 발화",
		"record.scriptTip": "아래 원고를 따라 읽으세요 — 음성 인식을 건너뛰어 더 빠르고 안정적입니다",
		"record.freeTip": "자유롭게 말하면 AI가 자동 전사합니다 (느리고 자원 소모 큼)",
		"record.hint": "위 원고를 따라 읽으세요. 오리가 이 원고로 바로 정렬하므로 음성 인식 단계를 건너뜁니다.",
		"record.scriptPickerLabel": "원고 선택",
		"record.scriptPickerAria": "따라 읽을 원고 선택",
		"record.scriptCustom": "사용자 지정 원고",
		"record.scriptCustomPlaceholder": "소리 내어 읽을 텍스트를 여기에 입력하세요…",
		"record.customHint": "이 텍스트는 정렬기로 그대로 전달됩니다 — 「분석 언어」와 일치해야 정렬이 성공합니다.",
		"record.scriptCustomEmpty": "사용자 지정 원고 칸에 먼저 텍스트를 입력하세요.",

		"stats.title": "음성 비율",
		"stats.subtitle": "발화 구간만 (음악 / 무음 제외)",
		"stats.modeAria": "비율 기준",
		"stats.modeA": "신경망",
		"stats.modePitch": "음높이",
		"stats.modeResonance": "공명",
		"stats.modeATip": "inaSpeechSegmenter 신경망 라벨 기준",
		"stats.modePitchTip": "음소별 F0 (145 Hz 이하 남성 / 145–185 Hz 중성 / 185 Hz 이상 여성)",
		"stats.modeResonanceTip": "음소별 공명 (현재 언어의 시스 분포 p25/p75 기준 남성 / 중성 / 여성)",
		"stats.lockedTip": "이 파일에 Engine C 음소 데이터가 없습니다 (Engine C가 꺼져 있거나 실패)",
		"label.male": "남성",
		"label.neutral": "중성",
		"label.female": "여성",
		"label.other": "기타",
		"label.music": "음악",
		"label.noise": "잡음",
		"label.silence": "무음",

		"dashboard.addBlock": "블록 추가",
		"dashboard.hideBlock": "숨기기",
		"dashboard.resetLayout": "레이아웃 초기화",
		"dashboard.toggleCollapse": "접기 / 펼치기",
		"dashboard.editHint": "⋮⋮ 드래그로 위치 이동 · 우하단 드래그로 크기 조절",
		"dashboard.empty.segment": "구간을 클릭하면 표시",
		"dashboard.empty.analysis": "오디오 업로드 후 표시",
		"dashboard.popoverEmpty": "모두 표시되어 있음",
		"dashboard.block.pitch": "음높이 범위",
		"dashboard.block.formants": "포먼트",
		"dashboard.block.resonance": "모음 공명",
		"dashboard.block.nn": "신경망 추정",
		"dashboard.block.stats": "비율 분포",

		"metrics.emptyClick": "구간을 클릭하면<br/>음향 세부 정보가 표시됩니다",
		"metrics.emptyUpload": "오디오를 업로드 / 분석하면<br/>전체 구간 평균이 나타납니다",
		"metrics.noEngineC": "Engine C가 꺼져 있어<br/>전체 평균을 표시할 수 없습니다",
		"metrics.alignWarning": "정렬 품질이 낮습니다 — 결과는 참고용으로만 보세요.",
		"metrics.alignHintScript": "원고를 건너뛰거나 잘못 읽은 듯합니다 — 다시 녹음하면 보통 개선됩니다.",
		"metrics.alignHintFree": "잡음이나 빠른 속도로 정렬이 약해졌을 수 있습니다.",
		"metrics.alignPhoneRatio": "음소/글자 비 {ratio}",
		"metrics.alignCoverage": "범위 {pct}%",
		"metrics.cardPitch": "기본 주파수 PITCH",
		"metrics.cardResonance": "공명 RESONANCE",
		"metrics.pitchRangeTitle": "음높이 범위",
		"metrics.zoneMale": "남성 80~145 Hz",
		"metrics.zoneOverlap": "중간 145~185 Hz",
		"metrics.zoneFemale": "여성 185~255 Hz",
		"metrics.legendMale": "♂ 80~145 Hz",
		"metrics.legendNeutral": "♂♀ 145~185 Hz",
		"metrics.legendFemale": "♀ 185~255 Hz",
		"metrics.formantsTitle": "포먼트",
		"metrics.nnTitle": "신경망 추정",
		"metrics.nnDisclaimer":
			"이 추정은 대규모 음성 데이터로 학습된 분류기에서 나옵니다. 「전형적인 청자에게 당신의 음성이 어떻게 들릴 수 있는지」를 반영할 뿐, 당신의 정체성을 나타내지 않습니다.",
		"metrics.nnSegmentNote":
			"↑ 파일 전체에서 지속 시간 가중 평균. 구간 목록에서 남/여가 번갈아 나오는 것은 중성 경계에서 AI가 민감하게 반응하는 정상 현상입니다 — 다중 화자를 의미하지 않습니다.",
		"metrics.headerOverall": "전체",
		"metrics.headerOverallSpeech": "전체 · 발화 {dur}",
		"metrics.disclaimer.prefix": "두 오픈소스 프로젝트에 진심으로 감사드립니다: 신경망 분류기는 ",
		"metrics.disclaimer.mid": " 음소별 포먼트 z-score 파이프라인은 ",
		"metrics.disclaimer.forkLabel": "포크",

		"timeline.pitch": "음높이",
		"timeline.resonance": "공명",
		"timeline.prevAria": "이전 줄",
		"timeline.nextAria": "다음 줄",
		"timeline.pagerAria": "줄 페이지",
		"timeline.readoutPitch": "음높이",
		"timeline.readoutResonance": "공명",
		"timeline.pitchTitle": "{char} {phone} · 음높이 {raw}",
		"timeline.pitchTitleInterp": "{char} {phone} · 음높이 {raw} (글자 보간 {interp} Hz)",
		"timeline.resonanceTitle": "{char} {phone} · 공명 {res}",
		"timeline.ariaPitch": "음높이 히트맵 (무성 자음은 같은 단위 안의 모음 색을 상속)",
		"timeline.ariaPitchDesc": "현재 페이지의 음높이 히트맵",
		"timeline.ariaResonance": "공명 히트맵 (각 셀 = 음소 1개, 값 0–1)",
		"timeline.ariaResonanceDesc": "현재 페이지의 공명 히트맵. 0.5 = 여성 기준 중앙값, 여성 임계값 = 0.587",
		"timeline.announceReady": "분석 완료, 총 {n}자",
		"timeline.returnToCurrent": "현재로 돌아가기",
		"timeline.barModePhone": "음소",
		"timeline.barModeWord": "어절 평균",
		"timeline.barModeAria": "막대 표시 단위 전환: 음소별 / 어절 지속시간 가중 평균",
		"timeline.wordAvgLabel": "어절 평균",

		"fallback.noTimelineTitle": "음소별 타임라인을 만들 수 없습니다",
		"fallback.noTimelineLead": "오디오는 인식되었지만 음소 정렬에 실패했습니다.",
		"fallback.commonReasons": "흔한 원인",
		"fallback.reasonTooShort": "녹음이 너무 짧음 (5초 이상 권장)",
		"fallback.reasonWrongLang": "녹음 언어와 현재 파이프라인이 일치하지 않음 (상단에서 언어를 바꾼 뒤 다시 시도)",
		"fallback.reasonNoise": "배경 잡음이 너무 큼",
		"fallback.reasonNoSpeech": "녹음에 또렷한 음성이 없음",
		"fallback.tips": "팁",
		"fallback.tipQuiet": "조용한 환경에서 다시 녹음하세요",
		"fallback.tipRead": "10~30초 분량의 단락을 읽으세요",
		"fallback.tipMicDist": "마이크와 입 사이 거리를 15~25 cm로 유지하세요",
		"fallback.stillVisible": "아래의 파형과 신경망 추정은 그대로 확인할 수 있습니다.",
		"fallback.lowPhone": "음소 {n}개만 검출됨 — 통계가 불안정할 수 있습니다. 더 안정적인 수치를 보려면 10초 이상 연속 발화로 녹음하세요.",
		"fallback.noSpeechTitle": "음성 미검출",
		"fallback.noSpeechLead": "오디오에서 분석할 만한 음성을 찾지 못했습니다. 순수 배경음이나 악기음이 아닐까요?",
		"fallback.noSpeechHint": "말소리가 담긴 클립으로 다시 녹음해 주세요.",

		"legend.azimuthAria": "공명 색상 범례",
		"legend.scienceAria": "팔레트 보정 방법",
		"legend.male": "남성 방향",
		"legend.neutral": "중성",
		"legend.female": "여성 방향",
		"legend.infoAria": "팔레트 정보",
		"legend.sci1":
			"<strong>공명 팔레트</strong>의 0.5는 <strong>여성 기준 중앙값</strong>입니다 (남녀의 중간선이 아닙니다 — 실측에서 남성 median ≈ 0.35–0.49, 여성 median ≈ 0.65–0.81로 언어에 따라 다릅니다). 여성 임계값 = <strong>{res}</strong>.",
		"legend.sci2": "이 임계값은 AISHELL-3 코퍼스 (134 남 + 134 여)에서 10-fold 교차검증한 결과이며, 정확도는 <strong>0.900</strong>입니다.",
		"legend.sci3":
			"<strong>음높이 기준:</strong> {neutral} Hz는 남성 상한 / 여성 하한 경계, {fem} Hz는 음성 작업에서 흔히 쓰이는 여성 지각 임계값입니다.",
		"legend.sci4":
			"음높이 구간은 영어권 시스 화자 기준 분포에서 가져온 값이며, 학습 목표가 아닙니다. 많은 시스 여성이 평소 F0가 175 Hz 아래입니다 — 공명의 중요성이 음높이만큼 큽니다.",
		"legend.sciNote": "색상은 방향 지표일 뿐 성별 판정이 아닙니다.",

		// Segment-level lean tag (waveform tooltip + NN block), keyed off
		// inaSpeechSegmenter confidence margins.
		"tone.leans_feminine": "여성 쪽 성향",
		"tone.leans_masculine": "남성 쪽 성향",
		"tone.weakly_feminine": "약하게 여성 쪽",
		"tone.weakly_masculine": "약하게 남성 쪽",
		"tone.not_clearly_leaning": "성향이 뚜렷하지 않음",

		"advice.resonance.title": "공명 표현",
		"advice.resonance.summary.clearly_below_female": "시스 남성 구간",
		"advice.resonance.summary.leans_male": "시스 남성 쪽 성향",
		"advice.resonance.summary.mid_neutral": "무성별 구간",
		"advice.resonance.summary.leans_female": "시스 여성 구간",
		"advice.resonance.summary.at_ceiling": "시스 여성 구간",
		"advice.resonance.caveat.score_clamp":
			"공명 점수의 상한은 1.0이며 일부 모음이 이미 천장에 닿았을 수 있습니다 — 각 모음의 z값을 함께 보는 것이 더 정확합니다.",
		"advice.resonance.caveat.low_alignment": "정렬 품질이 낮습니다 — 이번 결과는 참고용입니다.",
		"advice.resonance.section_title_all": "모음별",
		"advice.resonance.consonants.toggle_vowels_only": "모음만",
		"advice.resonance.consonants.toggle_all_phones": "자음 포함",
		"advice.resonance.consonants.tooltip":
			"자음 (비음 /m n ŋ/, 반모음 /j w/ 등)의 포먼트도 성도 공명 상태를 반영하지만, 음성 훈련 목표는 보통 모음에 집중됩니다. 이 옵션을 켜면 모든 음소의 진단 분포를 확인할 수 있습니다.",
		"advice.resonance.consonants.aria_label": "공명 패널에 자음 포함 여부",
		"advice.resonance.history.compare_with": "{when}의 같은 원고 녹음과 비교",
		"advice.resonance.history.improved": "개선됨",
		"advice.resonance.history.regressed": "후퇴함",
		"advice.resonance.history.no_prior": "비교할 동일 원고 기록이 없습니다",
		"advice.resonance.history.pitch_compensation":
			"⚠ NN 점수는 올라갔지만 다수 모음의 공명 디테일이 떨어졌습니다 — 음높이만 올려 공명 조정을 대체했을 수 있습니다. 권장: 턱을 풀고 연구개를 들어 올리며 /a/ /o/ 위주로 연습.",

		"disclosure.title": "시작하기 전에",
		"disclosure.intro": "이 도구는 음성의 음향 지표 몇 가지를 측정해 연습 참고로 제공합니다. 진단도, 평가도, 전문 교사의 대체도 아닙니다.",
		"disclosure.point.measurement": "표시되는 것은 측정값이지 지시 사항이 아닙니다 — 어떻게 연습할지는 본인에게 달려 있습니다.",
		"disclosure.point.model_judgment": "수치는 모델의 판단이며 사람의 청감과 항상 일치하지는 않습니다. 어떤 목소리에서는 모델이 틀리기도 합니다.",
		"disclosure.point.not_teacher": "voice teacher / SLP를 대체하지 않습니다 — 이 수치만으로는 기술의 세부를 읽어낼 수 없지만 선생님은 가능합니다.",
		"disclosure.point.dysphoria": "지금 감정이 불안정하다면, 결과가 더 불편하게 느껴질 수 있습니다. 잠시 닫아두고 상태가 좋아진 뒤 돌아와도 괜찮습니다.",
		"disclosure.resources.heading": "추천 자료",
		"disclosure.resources.transvoice_note": "— Zheanna Erose 채널, TVT 커뮤니티에서 가장 자주 추천하는 입문 강좌.",
		"disclosure.resources.sumian_note": "— Sumian 채널, resonance / pitch / weight 등 기술을 폭넓게 다룸.",
		"disclosure.acknowledge": "확인했어요, 시작합니다",
		"disclosure.close": "닫기",

		"duck.msg1": "오리가 음성을 듣는 중…",
		"duck.msg2": "오리가 열심히 일하는 중…",
		"duck.msg3": "오리가 귀를 쫑긋 세웠어요…",
		"duck.msg4": "오리가 음높이를 분석하는 중…",
		"duck.msg5": "오리가 포먼트를 계산하는 중…",
		"duck.msg6": "오리가 거의 다 끝냈어요…",
		"duck.done": "분석 완료 🎉",
		"duck.running": "분석 중…",

		"toast.cancelled": "분석 시간이 초과되었습니다. 더 짧은 오디오로 시도해 보세요.",
		"toast.failedFmt": "분석 실패: {msg}",
		"toast.batchFmt": "배치 분석 완료: {ok} / {total} 성공",
		"toast.batchItemFmt": "{name} 실패: {msg}",
		"toast.confirmClear": "저장된 모든 분석 기록을 지울까요?",
		"toast.processing": "처리 중…",
		"toast.hideFeedback": "피드백 버튼을 숨겼습니다 (URL에 ?feedback=1 을 붙이면 복원됨)",

		"progress.queued": "대기열에 있습니다",
		"progress.queuedNext": "곧 차례입니다…",
		"progress.queuedCount": "대기열 — 앞에 {n}명",
		"progress.processing": "오리가 오디오를 처리하는 중…",
		"progress.listening": "오리가 음성을 듣는 중… (이 단계는 시간이 좀 걸립니다)",
		"progress.organizing": "오리가 다 듣고 메모를 정리하는 중…",
		"progress.loadAudio": "오리가 오디오를 불러오는 중…",
		"progress.analyseSegment": "오리가 {i}/{total} 구간을 분석하는 중…",
		"progress.engineCScript": "오리가 원고를 한 글자씩 정렬하는 중…",
		"progress.engineCFree": "오리가 진짜 진심으로 분석 중…",
		"progress.almostDone": "오리가 거의 다 끝냈어요…",

		"recorder.noPermission": "마이크 권한을 허용한 뒤 다시 시도하세요",
		"recorder.noDevice": "마이크를 찾을 수 없습니다",
		"recorder.noAccess": "마이크에 접근할 수 없습니다",
		"recorder.recordError": "녹음 오류: {msg}",
		"recorder.empty": "녹음된 내용이 없습니다. 다시 시도하세요.",
		"recorder.filenamePrefix": "녹음",
		"recorder.idleHint": "최대 3분까지 녹음 가능합니다. 끝나면 분석 버튼으로 자동 이동합니다.",

		"upload.errEmpty": "파일이 비어 있습니다. 다시 선택해 주세요.",
		"upload.errUnsupported": "지원하지 않는 형식: {fmt}. 오디오 파일을 업로드해 주세요.",
		"upload.errUnknown": "알 수 없음",
		"upload.errTooLarge": "파일이 너무 큽니다 ({mb} MB). 현재 모드의 상한은 {limit} MB입니다.",
		"upload.errNoFile": "선택된 파일이 없습니다",
		"analyzer.noTaskId": "백엔드가 task_id를 반환하지 않았습니다",
		"analyzer.needOnProgress": "analyzeAudio는 진행 스트림 구독을 위해 onProgress 콜백이 필요합니다",
		"analyzer.submitFailed": "요청 실패 ({status})",
		"analyzer.streamFailed": "진행 상황 구독 실패 ({status})",
		"analyzer.backendError": "백엔드 분석 오류",
		"analyzer.noResult": "분석 결과를 받지 못했습니다",

		"audioGate.clipping": "클리핑이 심합니다 ({pct}% 샘플이 포화). 녹음 음량을 낮추고 다시 시도하세요.",
		"audioGate.tooQuiet": "음량이 너무 낮습니다 (RMS {db} dBFS). 마이크에 가까이 가거나 입력 게인을 올리세요.",
		"audioGate.silence": "오디오가 거의 무음입니다 — 마이크가 음소거 상태가 아닌지 확인하세요.",
		"audioGate.insufficientVoicing": "유효 발화 비율이 너무 낮습니다 ({pct}%). 연속해서 말하는 클립을 녹음해 주세요.",

		"feedback.title": "피드백",
		"feedback.email": "이메일 (선택)",
		"feedback.placeholder": "어떻게 생각하시는지 알려주세요…",
		"feedback.btnAria": "피드백 (길게 누르면 숨김)",
		"feedback.btnTitle": "길게 누르면 이 버튼을 숨깁니다",
		"feedback.close": "닫기",

		"help.title": "🦆 Voiceduck · 사용 안내",
		"help.what.h": "이게 뭔가요?",
		"help.what.p":
			"한국어 / 중국어 / 영어 / 프랑스어 오디오를 업로드하거나 녹음해 음성의 성별 음향 특성을 분석합니다. 가운데 타임라인이 음소별 음높이와 공명을 보여주고, 오른쪽은 전체 중앙값을 표시합니다. 음성 훈련 참고용일 뿐 판정이 아닙니다.",
		"help.what.engineA.h": "Engine A · 음색 참고",
		"help.what.engineA.desc": "inaSpeechSegmenter K-3 fork · CNN 분류기로 전체 여성도 점수를 출력",
		"help.what.engineC.h": "Engine C · 메인 · 음소 단위",
		"help.what.engineC.desc": "ASR + Montreal Forced Aligner + Praat 포먼트로 음소별 pitch / resonance 산출",
		"help.what.beta": "beta · 개선 중",
		"help.flow.h": "분석 흐름",
		"help.flow.s1.h": "업로드 / 녹음",
		"help.flow.s1.note":
			"오디오를 끌어다 놓거나 선택, 또는 마이크 녹음 (≤ {mb} MB, < {min}분; zh-CN / en-US / fr-FR / ko-KR)",
		"help.flow.s2.h": "VAD 분할",
		"help.flow.s2.note": "Engine A · inaSpeechSegmenter K-3 신경망이 발화 / 음악 / 무음을 분리",
		"help.flow.s3.h": "텍스트 정렬",
		"help.flow.s3.note":
			"Engine C · 자유 모드는 ASR (FunASR / faster-whisper)을 돌리고 따라 읽기 모드는 원고를 그대로 사용; Montreal Forced Aligner가 음소 단위로 정렬",
		"help.flow.s4.h": "포먼트 + z-score",
		"help.flow.s4.note": "Praat이 F1 / F2 / F3 추출 → z-score를 결합해 공명 값으로; 전체 집계는 「모음별 median 후 다시 중앙값」",
		"help.flow.s5.h": "3패널 렌더링",
		"help.flow.s5.note": "파형 · 가운데 샌드위치 타임라인 · 오른쪽 전체 평균",
		"help.how.h": "사용 방법",
		"help.how.1": "오디오를 끌어다 놓거나 / 클릭으로 선택 / 녹음 (≤ {mb} MB, < {min}분)",
		"help.how.2": "「분석 시작」을 누르고 오리의 진행바를 기다리세요",
		"help.how.3": "세 패널이 자동으로 채워지며 추가 클릭은 필요 없습니다",
		"help.heatmap.h": "용어",
		"help.heatmap.resonanceDT": "공명",
		"help.heatmap.resonanceDD":
			"음소 내 공명. 모음에서만 계산되며 F1 / F2 / F3의 가중 + z-score 정규화로 산출. 기준선은 시스 녹음 분포 참고값 (아래 표 참조).",
		"help.heatmap.resonance.credit": "알고리즘 출처:",
		"help.heatmap.pitchDT": "음높이",
		"help.heatmap.pitchDD":
			"음소 내 F0 (pyin, 60–250 Hz). 청감상 가장 알아채기 쉽지만 유일한 단서는 아닙니다 — F0만 올리고 공명이 따라 올라오지 않으면 보통 「쥐어짠 소리」로 들립니다. 두 히트맵을 함께 보는 것이 F0만 보는 것보다 유용합니다.",
		"help.baseline.h": "기준 분포",
		"help.baseline.note": "남녀 분포는 크게 겹칩니다 — 수치가 어느 쪽에 가깝다고 곧 판정이 되지는 않습니다. calibration_v1, 각 언어 ~90개 시스 녹음 기준.",
		"help.baseline.col.lang": "언어",
		"help.baseline.col.male": "남성 중앙값 (p25–p75)",
		"help.baseline.col.female": "여성 중앙값 (p25–p75)",
		"help.overall.h": "전체 분석",
		"help.overall.note": "타임라인은 음소 단위 측정값이고 오른쪽은 전체 집계입니다. 집계 방식은 아래와 같습니다:",
		"help.aggregate.h": "집계 방식",
		"help.aggregate.f0.h": "F0",
		"help.aggregate.f0.body": "pyin 중앙값 + p25 / p75",
		"help.aggregate.resonance.h": "공명",
		"help.aggregate.resonance.body": "모음별 median 후 다시 중앙값 (모음 등가중치로 빈번한 모음이 전체를 지배하지 않도록)",
		"help.aggregate.formant.h": "F1 / F2 / F3",
		"help.aggregate.formant.body": "유효 프레임 평균",
		"help.qa.h": "FAQ",
		"help.qa.q1": "먼저 어디를 봐야 하나요?",
		"help.qa.a1":
			"가운데 타임라인의 resonance와 pitch 히트맵을 보세요. 오른쪽 NN 퍼센트는 「음색 참고」로 격하 중입니다 — 정확하지 않으니 그걸 보며 연습하지 마세요. Resonance / pitch는 음소 단위 직접 측정값이며, 연습을 안내해 줄 수 있는 것이 바로 이것입니다.",
		"help.qa.q2": "두 엔진이 다를 때는?",
		"help.qa.a2":
			"resonance와 pitch (Engine C)를 믿으세요. NN (Engine A)과 다른 게 정상입니다 — 같은 걸 재는 게 아닙니다. 더 유용한 질문: 「resonance와 pitch가 서로 일치하나요?」 pitch는 올랐는데 resonance가 낮으면 음높이만 올리고 공명강은 아직 안 바꿨다는 뜻 — 다음 연습 방향입니다.",
		"help.qa.q3": '"Other"가 뭔가요?',
		"help.qa.a3": "휴지, 호흡음, 또는 엔진이 분류하지 못한 구간입니다.",
		"help.qa.q4": "실생활에서 pass 하는데 도구는 masc라고 — 무슨 일인가요?",
		"help.qa.a4": "도구가 틀린 겁니다. 당신은 문제가 없어요.",
		"help.qa.q5": "그럼 이 도구는 도대체 어디에 쓰나요?",
		"help.qa.a5":
			"각 모음의 resonance와 pitch가 시간에 따라 어떻게 변하는지 관찰하는 데. 「이 ‹아›는 밝게 들리는데 저 ‹아›는 무너졌네.」 귀로는 잘 잡히지 않는 디테일이지만 히트맵에서는 보입니다.",
		"help.qa.q6": "오디오 제한은?",
		"help.qa.a6": "≤ 5 MB, < 3분. 30초 이상, 조용한 환경, 단일 화자 녹음이 가장 좋습니다.",
		"help.qa.q7": "언어를 어떻게 바꾸나요?",
		"help.qa.a7": "오른쪽 위에서 zh-CN / en-US / fr-FR / ko-KR을 차례로 전환할 수 있습니다.",
		"help.qa.q8": "데이터는 저장되나요?",
		"help.qa.a8": "서버에는 아무것도 저장하지 않습니다.",
		"help.qa.q9": "모바일에서 작동하나요?",
		"help.qa.a9": "네, 다만 타임라인은 가로 모드로 보는 것을 권장합니다.",
		"help.links.h": "관련 링크",
		"help.links.projGroup": "프로젝트 자체",
		"help.links.creditsGroup": "기술 크레딧",
		"help.links.repo": "GitHub 저장소",
		"help.links.issues": "피드백 / 이슈 제출",
		"help.links.ina": "inaSpeechSegmenter (K-3 fork)",
		"help.links.gvv": "gender-voice-visualization",
		"help.links.mfa": "Montreal Forced Aligner",
		"help.links.praat": "Praat",
		"help.links.funasr": "FunASR",
		"help.links.whisper": "faster-whisper",
	},
};

// ─── Runtime state ───────────────────────────────────────────

let _lang = (() => {
	try {
		const stored = localStorage.getItem(LS_KEY);
		if (stored && SUPPORTED.includes(stored)) return stored;
	} catch (_) {}
	const nav = typeof navigator !== "undefined" ? navigator.language || "" : "";
	const lc = nav.toLowerCase();
	if (lc.startsWith("zh")) return "zh-CN";
	if (lc.startsWith("fr")) return "fr-FR";
	return "en-US";
})();

const _listeners = new Set();

// ─── Public API ──────────────────────────────────────────────

export function getLang() {
	return _lang;
}

export function setLang(code) {
	if (!SUPPORTED.includes(code) || code === _lang) return;
	_lang = code;
	try {
		localStorage.setItem(LS_KEY, code);
	} catch (_) {}
	document.documentElement.setAttribute("lang", code);
	applyStaticDom();
	for (const cb of _listeners) {
		try {
			cb(code);
		} catch (err) {
			// eslint-disable-next-line no-console
			console.error("[i18n] listener failed", err);
		}
	}
}

export function onLangChange(cb) {
	_listeners.add(cb);
	return () => _listeners.delete(cb);
}

export function t(key, params) {
	const table = DICT[_lang] || DICT["en-US"];
	const raw = table[key] ?? DICT["en-US"][key] ?? key;
	if (!params) return raw;
	return raw.replace(/\{(\w+)\}/g, (_, k) => (params[k] != null ? String(params[k]) : `{${k}}`));
}

/**
 * Apply translations to all elements with `data-i18n*` attributes inside `root`.
 * Attributes supported:
 *   data-i18n           → element.textContent
 *   data-i18n-html      → element.innerHTML (use sparingly)
 *   data-i18n-title     → element.title
 *   data-i18n-aria-label→ element.setAttribute("aria-label", ...)
 *   data-i18n-placeholder→ element.placeholder
 *   data-i18n-value     → element.value (inputs/buttons)
 * Optional `data-i18n-params='{"mb":5}'` passes template parameters.
 * The special key `__document_title__` mapped via `data-i18n="app.title"` on
 * `<html>` also updates document.title.
 */
export function applyStaticDom(root) {
	const scope = root || document;

	const pickParams = (el) => {
		const raw = el.getAttribute("data-i18n-params");
		if (!raw) return undefined;
		try {
			return JSON.parse(raw);
		} catch (_) {
			return undefined;
		}
	};

	scope.querySelectorAll("[data-i18n]").forEach((el) => {
		const key = el.getAttribute("data-i18n");
		el.textContent = t(key, pickParams(el));
	});
	scope.querySelectorAll("[data-i18n-html]").forEach((el) => {
		const key = el.getAttribute("data-i18n-html");
		el.innerHTML = t(key, pickParams(el));
	});
	scope.querySelectorAll("[data-i18n-title]").forEach((el) => {
		const key = el.getAttribute("data-i18n-title");
		el.title = t(key, pickParams(el));
	});
	scope.querySelectorAll("[data-i18n-aria-label]").forEach((el) => {
		const key = el.getAttribute("data-i18n-aria-label");
		el.setAttribute("aria-label", t(key, pickParams(el)));
	});
	scope.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
		const key = el.getAttribute("data-i18n-placeholder");
		el.placeholder = t(key, pickParams(el));
	});
	scope.querySelectorAll("[data-i18n-value]").forEach((el) => {
		const key = el.getAttribute("data-i18n-value");
		el.value = t(key, pickParams(el));
	});

	const titleNode = document.querySelector("title[data-i18n]");
	if (titleNode) document.title = titleNode.textContent;
}

// ─── Dev-only drift guard ────────────────────────────────────
// Fires the moment a developer reloads the page after editing DICT — earlier
// than any CI test would catch it. Tree-shaken in `vite build` (NODE_ENV=production
// makes import.meta.env.DEV a literal `false`, the whole block becomes dead code).
// Equality, not just superset: an extra key in fr-FR that en-US lacks would make
// English users fall back to French — a reverse bug.
if (import.meta.env?.DEV) {
	const canon = "en-US";
	const canonKeys = Object.keys(DICT[canon]);
	for (const lang of SUPPORTED) {
		if (lang === canon) continue;
		const langSet = new Set(Object.keys(DICT[lang]));
		const canonSet = new Set(canonKeys);
		const missing = canonKeys.filter((k) => !langSet.has(k));
		const extra = [...langSet].filter((k) => !canonSet.has(k));
		if (missing.length || extra.length) {
			throw new Error(
				`[i18n] DICT drift in ${lang}: missing=${JSON.stringify(missing)} extra=${JSON.stringify(extra)}`,
			);
		}
	}
}

// Boot once: ensure <html lang="..."> matches the chosen language even before
// the first setLang call.  applyStaticDom is invoked explicitly from main.js
// after scripts/data-i18n attributes are present — don't race the parser here.
if (typeof document !== "undefined") {
	document.documentElement.setAttribute("lang", _lang);
}
