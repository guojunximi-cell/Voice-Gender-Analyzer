/**
 * i18n.js — UI 语言 + 分析管线语言。
 *
 * 一个简单的键值字典：zh-CN 是原版 UI，en-US 的表述遵循
 * `notes/english-localization.md` 术语表（masculine/feminine、perceived、
 * gender-affirming、避免 pass/passing）。
 *
 * 对外：
 *   t(key, params?) — 取当前语言下的字符串；`{name}` 占位由 params 注入。
 *   getLang() / setLang(code) — "zh-CN" | "en-US"
 *   onLangChange(cb) — 订阅变化（cb 收到新语言）
 *   applyStaticDom(root?) — 按 data-i18n* 属性刷新 root 下的文本；不传则整页。
 *
 * 语言写进 localStorage("vga.lang")；同一个语言同时决定：
 *   1. 界面文案（本文件 DICT）
 *   2. 示例稿件库（scripts.js 按语言取）
 *   3. POST /api/analyze-voice 的 `language` 表单字段（analyzer.js 读）
 */

const LS_KEY = "vga.lang";
export const SUPPORTED = ["zh-CN", "en-US"];

const DICT = {
	"zh-CN": {
		"app.title": "声音分析鸭 — 声音性别分析",
		"app.logoAria": "声音分析鸭 GitHub 仓库",
		"app.name": "声音分析鸭",
		"header.help": "使用帮助",
		"header.theme": "切换主题",
		"header.lang": "切换语言 / Language",
		"header.langShort.zh": "中",
		"header.langShort.en": "EN",

		"panel.history": "历史分析",
		"panel.metrics": "综合声学特征",

		"action.upload": "上传新文件",
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

		"stats.title": "声音占比",
		"stats.modeAria": "占比依据",
		"stats.modeA": "神经网络",
		"stats.modePitch": "音高",
		"stats.modeResonance": "共鸣",
		"stats.modeATip": "依 inaSpeechSegmenter 神经网络标签",
		"stats.modePitchTip": "依每个音素的基频（165 Hz 为中性线）",
		"stats.modeResonanceTip": "依每个音素的共鸣值（0.5 为中性线）",
		"stats.lockedTip": "该文件无 Engine C 音素数据（可能 Engine C 未启用或失败）",
		"label.male": "男声",
		"label.female": "女声",
		"label.other": "其他",
		"label.music": "音乐",
		"label.noise": "噪音",
		"label.silence": "静音",

		"segments.title": "分段详情",
		"segments.countSuffix": "段",
		"segments.acousticDot": "含声学分析",
		"segments.confTitle": "置信度 {pct}%",

		"mobile.tabSegments": "分段详情",
		"mobile.tabMetrics": "声学特征",

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
		"metrics.pitchRangeTitle": "音高范围 (80~320 Hz)",
		"metrics.zoneMale": "男性 85~155 Hz",
		"metrics.zoneOverlap": "中间 145~185 Hz",
		"metrics.zoneFemale": "女性 175~255 Hz",
		"metrics.legendMale": "♂ 85~155 Hz",
		"metrics.legendNeutral": "♂♀ 145~185 Hz",
		"metrics.legendFemale": "♀ 175~255 Hz",
		"metrics.formantsTitle": "共振峰",
		"metrics.nnTitle": "神经网络估计",
		"metrics.nnDisclaimer":
			"此估计来自一个在大规模语音数据上训练的分类器。它反映的是「典型听者可能如何感知你的声音」，不代表你的身份。",
		"metrics.spectrumMale": "♂ 男性化",
		"metrics.spectrumNeutral": "中性",
		"metrics.spectrumFemale": "♀ 女性化",
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
		"timeline.ariaResonanceDesc": "当前页的共鸣热力带；女声阈值 = 0.587",
		"timeline.announceReady": "分析完成，共 {n} 个字",
		"timeline.returnToCurrent": "回到当前",

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
		"legend.sci1": "<strong>共鸣色条</strong>的中性点为 0.5（参考语料库均值），女声阈值 = <strong>{res}</strong>。",
		"legend.sci2": "该阈值基于 AISHELL-3 语料库（134 男 + 134 女）的 10-fold 交叉验证，精度 <strong>0.900</strong>。",
		"legend.sci3":
			"<strong>音高参考</strong>：{neutral} Hz 为男声上限 / 女声下限交界，{fem} Hz 为声音训练常用的女声感知阈值。",
		"legend.sciNote": "色值仅作方向参考，不是性别判定。",

		"scatter.male": "♂ 男",
		"scatter.neutral": "中性",
		"scatter.female": "♀ 女",
		"scatter.yaxis": "综合性别表达",

		"certainty.low": "低置信度",
		"certainty.boundary": "临界区间",
		"certainty.femaleStrong": "明确女声",
		"certainty.femaleClear": "较明显女声",
		"certainty.maleStrong": "明确男声",
		"certainty.maleClear": "较明显男声",
		"certainty.femaleLean": "偏女性化",
		"certainty.female": "女性化",
		"certainty.maleLean": "偏男性化",
		"certainty.male": "男性化",

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
			"上传或录制一段普通话或英文音频，分析声音的性别声学特征。输出整段均值 + 逐字音高/共鸣色彩，作声音训练的参考工具——并非判定。",
		"help.flow.h": "分析流程",
		"help.flow.s1.h": "上传 / 录音",
		"help.flow.s1.note": "拖拽音频、选择文件，或调用麦克风（≤ {mb} MB，< {min} 分钟，中文 zh-CN 或英文 en-US）",
		"help.flow.s2.h": "VAD 分段",
		"help.flow.s2.note": "Engine A · inaSpeechSegmenter K-3 神经网络分出语音 / 音乐 / 静音",
		"help.flow.s3.h": "文本对齐",
		"help.flow.s3.note":
			"Engine C · 自由模式跑 ASR（FunASR / faster-whisper），跟稿模式直接用您的稿子；Montreal Forced Aligner 对齐到音素",
		"help.flow.s4.h": "共振峰 + z-score",
		"help.flow.s4.note": "Praat 提 F1 / F2 / F3 → z-score 合成共鸣值",
		"help.flow.s5.h": "三面板渲染",
		"help.flow.s5.note": "波形 · 中央三明治时间轴 · 右侧整段均值",
		"help.how.h": "如何使用？",
		"help.how.1": "拖拽音频 / 点击上传 / 录音（≤ {mb} MB，< {min} 分钟）",
		"help.how.2": "点击「开始分析」，等待鸭子跑完进度条",
		"help.how.3": "三块面板自动填充，无需额外点击",
		"help.tour.h": "界面导览",
		"help.tour.waveDT": "上方波形",
		"help.tour.waveDD": "时间轴；拖动跳转播放，分段着色代表 AI 识别的语音 / 音乐 / 静音。",
		"help.tour.timelineDT": "中央时间轴",
		"help.tour.timelineDD":
			"音高色带 → 字形 → 共鸣色带的三明治：三行按时间严格同轴，每字一格槽位；字内多个音素按时长细分。点击色块或字形跳转播放；← N/M → 翻页浏览全文。",
		"help.tour.rightDT": "右侧面板",
		"help.tour.rightDD": "整段音频的均值：基频、共鸣、F1/F2/F3 与音高范围参考条，底部为 AI 分类器的加权置信度。",
		"help.color.h": "色彩与区间",
		"help.color.dirDT": "色彩方向",
		"help.color.dirDD":
			"<strong>蓝色</strong> = 男声方向（低音高 / 宽声道共鸣）；<strong>粉色</strong> = 女声方向（高音高 / 窄声道共鸣）。",
		"help.color.f0DT": "基频 F0",
		"help.color.f0DD": "< 155 Hz 典型男声，155~185 Hz 中性区，> 185 Hz 偏女声。",
		"help.color.f2DT": "共振峰 F2",
		"help.color.f2DD": "< 1400 Hz 偏男，1600~1900 Hz 中性，> 2200 Hz 偏女。",
		"help.color.resDT": "共鸣（0~100%）",
		"help.color.resDD": "基于 F1/F2/F3 z-score 的合成分，越高越偏女声方向。",
		"help.qa.h": "常见问题",
		"help.qa.q1": "音频有什么限制？",
		"help.qa.a1": "≤ {mb} MB、< {min} 分钟，常见格式（mp3 / wav / m4a / webm 等）。建议 ≥ 30 秒、安静环境单人朗读。",
		"help.qa.q2": "中英怎么切换？",
		"help.qa.a2": "上传前在右上角语言切换里选 zh-CN 或 en-US。语言决定示例稿件、ASR 模型、MFA 资源路径。",
		"help.qa.q3": "「自由模式」和「跟稿模式」有什么区别？",
		"help.qa.a3":
			"自由模式跑 ASR 自动出文本；跟稿模式直接用您粘贴的稿子，更快、对齐更稳定。短音频或方言/嘈杂环境推荐跟稿。",
		"help.qa.q4": "为什么有些字没显示？",
		"help.qa.a4": "MFA 对齐到那个字时置信度过低就会跳过；可以改用跟稿模式贴入完整稿子改善。",
		"help.qa.q5": "进度卡住或断开怎么办？",
		"help.qa.a5": "SSE 走 Redis Stream 流式回放，刷新页面可以重新接收，结果不会丢失。",
		"help.qa.q6": "数据会保留吗？",
		"help.qa.a6": "服务端不持久化音频与转写结果；浏览器会话结束即清空。",
		"help.qa.q7": "结果靠谱吗？",
		"help.qa.a7": "参考工具，非医学/法律/身份判定。模型有偏差，请结合主观感受与训练目标使用。",
		"help.qa.q8": "移动端能用吗？",
		"help.qa.a8": "支持触屏与录音；建议横屏查看时间轴；viewport 已锁，不会被双指缩放。",
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
		"app.title": "Voiceya — voice analysis for gender-affirming training",
		"app.logoAria": "Voiceya GitHub repository",
		"app.name": "Voiceya",
		"header.help": "Help",
		"header.theme": "Toggle theme",
		"header.lang": "Switch language / 切换语言",
		"header.langShort.zh": "中",
		"header.langShort.en": "EN",

		"panel.history": "Past sessions",
		"panel.metrics": "Acoustic summary",

		"action.upload": "Upload new file",
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

		"stats.title": "Distribution",
		"stats.modeAria": "Classification basis",
		"stats.modeA": "Neural net",
		"stats.modePitch": "Pitch",
		"stats.modeResonance": "Resonance",
		"stats.modeATip": "Labels from the inaSpeechSegmenter neural classifier.",
		"stats.modePitchTip": "Per-phone F0 — 165 Hz is the neutral midline.",
		"stats.modeResonanceTip": "Per-phone resonance index — 0.5 is the neutral midline.",
		"stats.lockedTip": "No Engine C phone data for this file (Engine C off or failed).",
		"label.male": "Masc",
		"label.female": "Fem",
		"label.other": "Other",
		"label.music": "Music",
		"label.noise": "Noise",
		"label.silence": "Silent",

		"segments.title": "Segments",
		"segments.countSuffix": "segs",
		"segments.acousticDot": "Includes acoustic analysis",
		"segments.confTitle": "Classifier confidence {pct}%",

		"mobile.tabSegments": "Segments",
		"mobile.tabMetrics": "Acoustics",

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
		"metrics.pitchRangeTitle": "Pitch range (80–320 Hz)",
		"metrics.zoneMale": "♂ 85–155 Hz",
		"metrics.zoneOverlap": "♂♀ 145–185 Hz",
		"metrics.zoneFemale": "♀ 175–255 Hz",
		"metrics.legendMale": "♂ 85–155 Hz",
		"metrics.legendNeutral": "♂♀ 145–185 Hz",
		"metrics.legendFemale": "♀ 175–255 Hz",
		"metrics.formantsTitle": "Formants",
		"metrics.nnTitle": "Neural network estimate",
		"metrics.nnDisclaimer":
			"This estimate comes from inaSpeechSegmenter, an open-source classifier trained primarily on French broadcast audio. It reflects how one specific classifier, trained on one specific dataset, labelled this sample. Not your identity, not whether you 'pass'.",
		"metrics.spectrumMale": "Masculine",
		"metrics.spectrumNeutral": "Androgynous",
		"metrics.spectrumFemale": "Feminine",
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
		"timeline.ariaResonanceDesc": "Resonance heatmap for the current page. Palette midline = 0.5.",
		"timeline.announceReady": "Analysis complete, {n} characters shown",
		"timeline.returnToCurrent": "Jump to now",

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
			"<strong>Resonance palette</strong> centers on 0.5 by construction — the reference-corpus midline between masculine-cool and feminine-warm.",
		"legend.sci2":
			"Calibration uses the acousticgender.space English voice-training corpus; per-phone F₂/F₃/F₄ z-scores are combined with weights brute-forced on labeled speakers.",
		"legend.sci3":
			"<strong>Pitch reference:</strong> {neutral} Hz is the typical masculine-upper / feminine-lower boundary; {fem} Hz is a common perceptual threshold used in voice training.",
		"legend.sciNote": "Colors are directional guidance, not a gender verdict.",

		"scatter.male": "M",
		"scatter.neutral": "Neutral",
		"scatter.female": "F",
		"scatter.yaxis": "Perceived gender expression",

		"certainty.low": "Low confidence",
		"certainty.boundary": "Boundary zone",
		"certainty.femaleStrong": "Clearly feminine",
		"certainty.femaleClear": "Fairly feminine",
		"certainty.maleStrong": "Clearly masculine",
		"certainty.maleClear": "Fairly masculine",
		"certainty.femaleLean": "Leans feminine",
		"certainty.female": "Feminine-leaning",
		"certainty.maleLean": "Leans masculine",
		"certainty.male": "Masculine-leaning",

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
		"audioGate.insufficientVoicing": "Not enough speech detected ({pct}%). Please record a clip with continuous speaking.",

		"feedback.title": "Feedback",
		"feedback.email": "Your email (optional)",
		"feedback.placeholder": "Tell us what you think…",
		"feedback.btnAria": "Feedback (long-press to hide)",
		"feedback.btnTitle": "Long-press to hide this button",
		"feedback.close": "Close",

		"help.title": "🦆 Voiceya · How to use",
		"help.what.h": "What is this?",
		"help.what.p":
			"Upload or record a short clip of speech (English or Mandarin Chinese). The tool returns whole-file acoustic averages and phone-level pitch / resonance colors — a reference for voice training, not a verdict.",
		"help.flow.h": "Pipeline",
		"help.flow.s1.h": "Upload / record",
		"help.flow.s1.note": "Drop a file, pick one, or use the mic (≤ {mb} MB, < {min} min, zh-CN or en-US).",
		"help.flow.s2.h": "VAD segmentation",
		"help.flow.s2.note": "Engine A · inaSpeechSegmenter K-3 splits speech / music / silence.",
		"help.flow.s3.h": "Text alignment",
		"help.flow.s3.note":
			"Engine C · free mode runs ASR (FunASR / faster-whisper); script mode uses your pasted text. Montreal Forced Aligner aligns to phones.",
		"help.flow.s4.h": "Formants + z-score",
		"help.flow.s4.note": "Praat extracts F1 / F2 / F3 → z-score blends into the resonance value.",
		"help.flow.s5.h": "Three-panel render",
		"help.flow.s5.note": "Waveform · center sandwich timeline · right-side whole-file averages.",
		"help.how.h": "How to use",
		"help.how.1": "Drag a file, pick one, or record (≤ {mb} MB, < {min} min).",
		"help.how.2": "Press Analyze and wait for the duck progress bar.",
		"help.how.3": "The three panels fill in automatically — no extra clicks.",
		"help.tour.h": "Interface tour",
		"help.tour.waveDT": "Waveform (top)",
		"help.tour.waveDD":
			"Timeline — drag to seek. Segment colors mark what the classifier heard: speech / music / silence.",
		"help.tour.timelineDT": "Center timeline",
		"help.tour.timelineDD":
			"Pitch strip → characters → resonance strip, all time-aligned. Click a cell or character to seek; ← N/M → to page through the transcript.",
		"help.tour.rightDT": "Right panel",
		"help.tour.rightDD":
			"Whole-file averages: F0, resonance, F1/F2/F3, pitch-range reference bar, and the classifier's duration-weighted confidence at the bottom.",
		"help.color.h": "Colors & ranges",
		"help.color.dirDT": "Color direction",
		"help.color.dirDD":
			"<strong>Blue</strong> = masculine-leaning (lower pitch / wider vocal tract). <strong>Pink</strong> = feminine-leaning (higher pitch / narrower vocal tract).",
		"help.color.f0DT": "F0 (pitch)",
		"help.color.f0DD": "< 155 Hz typical masculine, 155–185 Hz androgynous, > 185 Hz feminine-leaning.",
		"help.color.f2DT": "Formant F2",
		"help.color.f2DD": "< 1400 Hz masculine-leaning, 1600–1900 Hz androgynous, > 2200 Hz feminine-leaning.",
		"help.color.resDT": "Resonance (0–100%)",
		"help.color.resDD": "A composite from F1/F2/F3 z-scores. Higher values lean feminine.",
		"help.qa.h": "FAQ",
		"help.qa.q1": "What are the audio limits?",
		"help.qa.a1":
			"≤ {mb} MB, < {min} min, common formats (mp3 / wav / m4a / webm…). 30+ seconds in a quiet, single-speaker setting works best.",
		"help.qa.q2": "How do I switch language?",
		"help.qa.a2":
			"Pick zh-CN or en-US in the top-right language toggle before uploading. Language drives the script library, ASR model, and MFA resources.",
		"help.qa.q3": "Free vs script mode?",
		"help.qa.a3":
			"Free mode runs ASR to transcribe automatically; script mode uses the text you paste — faster and more stable for short clips, accents, or noisy audio.",
		"help.qa.q4": "Why are some characters missing?",
		"help.qa.a4":
			"MFA skipped them because alignment confidence was too low. Switching to script mode with a full transcript usually helps.",
		"help.qa.q5": "Progress stuck or disconnected — what now?",
		"help.qa.a5": "SSE replays from a Redis Stream, so refreshing reconnects and resumes; the result is not lost.",
		"help.qa.q6": "Is my data kept?",
		"help.qa.a6": "The server does not persist audio or transcripts; everything clears when your browser session ends.",
		"help.qa.q7": "How reliable are the results?",
		"help.qa.a7":
			"A reference tool — not a medical, legal, or identity verdict. The models have bias; combine with your own ear and training goals.",
		"help.qa.q8": "Does it work on mobile?",
		"help.qa.a8":
			"Touch and recording are supported; landscape is best for the timeline. The viewport is locked so pinch-zoom won't break the layout.",
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
};

// ─── Runtime state ───────────────────────────────────────────

let _lang = (() => {
	try {
		const stored = localStorage.getItem(LS_KEY);
		if (stored && SUPPORTED.includes(stored)) return stored;
	} catch (_) {}
	const nav = typeof navigator !== "undefined" ? navigator.language || "" : "";
	return nav.toLowerCase().startsWith("zh") ? "zh-CN" : "en-US";
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

// Boot once: ensure <html lang="..."> matches the chosen language even before
// the first setLang call.  applyStaticDom is invoked explicitly from main.js
// after scripts/data-i18n attributes are present — don't race the parser here.
if (typeof document !== "undefined") {
	document.documentElement.setAttribute("lang", _lang);
}
