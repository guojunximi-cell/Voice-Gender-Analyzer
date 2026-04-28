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
		"export.audioSizeFmt": "约 {size}",
		"export.audioSizeMultiFmt": "约 {n} 段共 {size}",
		"export.audioSizeNone": "（无音频）",
		"export.successFmt": "已导出 {name}（{size}）",
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
		"legend.sci4":
			"音高区间基于 cis 英语母语者的参考分布，不代表训练目标。很多 cis 女性 F0 长期低于 175 Hz——共鸣的重要性不亚于音高。",
		"legend.sciNote": "色值仅作方向参考，不是性别判定。",

		// Advice v2 — see docs/plans/v2_redesign_measurement.md
		"advice.tone.leans_feminine": "倾向偏女",
		"advice.tone.leans_masculine": "倾向偏男",
		"advice.tone.not_clearly_leaning": "倾向不明显",
		"advice.zone.low": "低基频",
		"advice.zone.mid_lower": "中低基频",
		"advice.zone.mid_neutral": "声学中性区间",
		"advice.zone.mid_upper": "中高基频",
		"advice.zone.high": "高基频",
		"advice.warning.short_recording_minimal": "录音少于 10 秒，仅显示原始测量值。tonal 倾向需 10 秒以上录音。",
		"advice.warning.short_recording_standard":
			"录音较短（{duration} 秒），结果稳定性有限。建议录制 30 秒以上以获得稳定结果。",
		"advice.warning.dismiss": "关闭提示",
		"advice.summary.low_leans_feminine": "F0 中位数 {f0} Hz，位于低基频区间。声学倾向偏女。",
		"advice.summary.low_leans_masculine": "F0 中位数 {f0} Hz，位于低基频区间。声学倾向偏男。",
		"advice.summary.low_not_clearly_leaning": "F0 中位数 {f0} Hz，位于低基频区间。倾向不明显。",
		"advice.summary.mid_lower_leans_feminine": "F0 中位数 {f0} Hz，位于中低基频区间。声学倾向偏女。",
		"advice.summary.mid_lower_leans_masculine": "F0 中位数 {f0} Hz，位于中低基频区间。声学倾向偏男。",
		"advice.summary.mid_lower_not_clearly_leaning": "F0 中位数 {f0} Hz，位于中低基频区间。倾向不明显。",
		"advice.summary.mid_neutral_leans_feminine": "F0 中位数 {f0} Hz，处于声学中性区间。声学倾向偏女。",
		"advice.summary.mid_neutral_leans_masculine": "F0 中位数 {f0} Hz，处于声学中性区间。声学倾向偏男。",
		"advice.summary.mid_neutral_not_clearly_leaning": "F0 中位数 {f0} Hz，处于声学中性区间。倾向不明显。",
		"advice.summary.mid_upper_leans_feminine": "F0 中位数 {f0} Hz，位于中高基频区间。声学倾向偏女。",
		"advice.summary.mid_upper_leans_masculine": "F0 中位数 {f0} Hz，位于中高基频区间。声学倾向偏男。",
		"advice.summary.mid_upper_not_clearly_leaning": "F0 中位数 {f0} Hz，位于中高基频区间。倾向不明显。",
		"advice.summary.high_leans_feminine": "F0 中位数 {f0} Hz，位于高基频区间。声学倾向偏女。",
		"advice.summary.high_leans_masculine": "F0 中位数 {f0} Hz，位于高基频区间。声学倾向偏男。",
		"advice.summary.high_not_clearly_leaning": "F0 中位数 {f0} Hz，位于高基频区间。倾向不明显。",

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
			"这是一个双引擎互相参考的，对声音刻板影响性别的评估网站。它分为音素级分析和整段分析。主要由上游项目 gender-voice-visualization 和 inaSpeechSegmenter（K-3 fork）驱动。它处于 beta 版本，在迭代中。作者希望它能辅助练声过程。",
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
		"help.heatmap.h": "热力图中",
		"help.heatmap.resonanceDT": "共鸣",
		"help.heatmap.resonanceDD":
			"音素内的共鸣。只识别元音。由 F1 F2 F3 加权后得出。Baseline 基于 cis 分布参考。大于 50% 即意味着女性化。",
		"help.heatmap.pitchDT": "音高",
		"help.heatmap.pitchDD": "音素内的 F0。被认为是男女性化声音的主要边界。",
		"help.overall.h": "整段分析",
		"help.overall.note": "基频，共鸣和共振峰采用有效数据的平均值。",
		"help.overall.nnDT": "NN / Engine A",
		"help.overall.nnDD":
			"来自 inaSpeechSegmenter 的 CNN 分类器，数据源以法语为主。输出性别标签，设计目的是区分 cis 人群在语音中的分布。仅作为 tone 参考。",
		"help.qa.h": "常见问题",
		"help.qa.q1": "先看哪里？",
		"help.qa.a1":
			"看 resonance 和 pitch 的热力图，不要看 Neural Net 那个百分比。Neural Net 不准。我正在把它降级成「音色参考」。Resonance 和 pitch 是直接测量出来的，时间分辨率细到每个音素，这才是能指导练习的东西。",
		"help.qa.q2": "三个引擎分歧？",
		"help.qa.a2":
			"信 resonance 和 pitch。它们对不上 NN 是正常的。它们测的不是同一个东西。更有用的问法是「resonance 和 pitch 自己之间对得上吗」。如果 pitch 已经上去了但 resonance 还偏低，说明抬了音高但共鸣腔还没改，这就是下一步的方向。",
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
		"help.qa.a7": "右上角切 zh-CN / en-US。",
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
		"export.audioSizeFmt": "~{size}",
		"export.audioSizeMultiFmt": "~{n} clips, {size}",
		"export.audioSizeNone": "(no audio)",
		"export.successFmt": "Exported {name} ({size})",
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
		"record.customHint": "We feed this text straight to the aligner — make sure it matches the analysis language or it won't line up.",
		"record.scriptCustomEmpty": "Type some text in the custom script first.",

		"stats.title": "Distribution",
		"stats.subtitle": "Within voiced speech only — music / silence excluded",
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
		"metrics.zoneMale": "Masculine-typical 85–155 Hz",
		"metrics.zoneOverlap": "Overlap zone 145–185 Hz",
		"metrics.zoneFemale": "Feminine-typical 175–255 Hz",
		"metrics.legendMale": "Masc 85–155 Hz",
		"metrics.legendNeutral": "Mixed 145–185 Hz",
		"metrics.legendFemale": "Fem 175–255 Hz",
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
		"legend.sci4":
			"Pitch ranges come from cisgender English-speaking reference populations — they aren't training goals. Many cis women speak below 175 Hz and are read as women without issue. Resonance matters as much as pitch.",
		"legend.sciNote": "Colors are directional guidance, not a gender verdict.",

		// Advice v2 — see docs/plans/v2_redesign_measurement.md
		"advice.tone.leans_feminine": "Leans feminine",
		"advice.tone.leans_masculine": "Leans masculine",
		"advice.tone.not_clearly_leaning": "Not clearly leaning",
		"advice.zone.low": "Low",
		"advice.zone.mid_lower": "Mid-low",
		"advice.zone.mid_neutral": "Acoustically neutral",
		"advice.zone.mid_upper": "Mid-high",
		"advice.zone.high": "High",
		"advice.warning.short_recording_minimal":
			"Recording is under 10 seconds; only raw measurements are shown. Tonal tendency requires 10 s+.",
		"advice.warning.short_recording_standard":
			"Recording is short ({duration} s); result stability is limited. 30 s+ recommended for stable output.",
		"advice.warning.dismiss": "Dismiss notice",
		"advice.summary.low_leans_feminine": "F0 median {f0} Hz, low range. Leans feminine.",
		"advice.summary.low_leans_masculine": "F0 median {f0} Hz, low range. Leans masculine.",
		"advice.summary.low_not_clearly_leaning": "F0 median {f0} Hz, low range. Not clearly leaning.",
		"advice.summary.mid_lower_leans_feminine": "F0 median {f0} Hz, mid-low range. Leans feminine.",
		"advice.summary.mid_lower_leans_masculine": "F0 median {f0} Hz, mid-low range. Leans masculine.",
		"advice.summary.mid_lower_not_clearly_leaning": "F0 median {f0} Hz, mid-low range. Not clearly leaning.",
		"advice.summary.mid_neutral_leans_feminine": "F0 median {f0} Hz, acoustically neutral range. Leans feminine.",
		"advice.summary.mid_neutral_leans_masculine": "F0 median {f0} Hz, acoustically neutral range. Leans masculine.",
		"advice.summary.mid_neutral_not_clearly_leaning":
			"F0 median {f0} Hz, acoustically neutral range. Not clearly leaning.",
		"advice.summary.mid_upper_leans_feminine": "F0 median {f0} Hz, mid-high range. Leans feminine.",
		"advice.summary.mid_upper_leans_masculine": "F0 median {f0} Hz, mid-high range. Leans masculine.",
		"advice.summary.mid_upper_not_clearly_leaning": "F0 median {f0} Hz, mid-high range. Not clearly leaning.",
		"advice.summary.high_leans_feminine": "F0 median {f0} Hz, high range. Leans feminine.",
		"advice.summary.high_leans_masculine": "F0 median {f0} Hz, high range. Leans masculine.",
		"advice.summary.high_not_clearly_leaning": "F0 median {f0} Hz, high range. Not clearly leaning.",

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

		"help.title": "🦆 Voiceya · How to use",
		"help.what.h": "What is this?",
		"help.what.p":
			"A dual-engine cross-referencing site for evaluating how acoustic stereotypes shape perceived gender. It covers phone-level analysis and whole-file analysis. Powered primarily by upstream projects gender-voice-visualization and inaSpeechSegmenter (K-3 fork). It's in beta and iterating. The author hopes it can assist with voice training.",
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
		"help.how.3": "The three panels fill in automatically, no extra clicks needed.",
		"help.heatmap.h": "In the heatmap",
		"help.heatmap.resonanceDT": "Resonance",
		"help.heatmap.resonanceDD":
			"Resonance within each phone. Vowels only. Derived from a weighted blend of F1, F2, and F3. Baseline calibrated against a cis-voice reference corpus. Values above 50% indicate feminine-leaning.",
		"help.heatmap.pitchDT": "Pitch",
		"help.heatmap.pitchDD":
			"F0 within each phone. Considered the primary acoustic boundary between masculine and feminine voice perception.",
		"help.overall.h": "Whole-file analysis",
		"help.overall.note": "F0, resonance, and formants are averages over voiced segments.",
		"help.overall.nnDT": "NN / Engine A",
		"help.overall.nnDD":
			"A CNN classifier from inaSpeechSegmenter, trained primarily on French broadcast audio. Outputs a gender label designed to distinguish cis-voice distributions in speech segments. Treat as a rough tonal reference only.",
		"help.qa.h": "FAQ",
		"help.qa.q1": "Where should I look first?",
		"help.qa.a1":
			"Look at the resonance and pitch heatmaps, not the Neural Net percentage. Neural Net isn't accurate. I'm downgrading it to a \"tonal reference\". Resonance and pitch are direct measurements with phone-level time resolution, and that's what can actually guide practice.",
		"help.qa.q2": "Three engines disagree?",
		"help.qa.a2":
			"Trust resonance and pitch. It's normal for them to disagree with the NN. They aren't measuring the same thing. A more useful question is: do resonance and pitch agree with each other? If pitch has gone up but resonance is still low, that means vocal pitch went up but the resonant cavity hasn't changed yet, and that's your next direction.",
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
		"help.qa.a7": "Use the toggle in the top-right corner to switch between zh-CN and en-US.",
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
