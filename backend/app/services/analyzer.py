from __future__ import annotations

from collections import Counter

import jieba

from app.core.config import settings
from app.models.schemas import AnalysisSection, TopicStat
from app.utils.text import split_sentences, truncate_text, unique_preserve_order


STOPWORDS = {
    "我们",
    "你们",
    "他们",
    "这个",
    "那个",
    "一个",
    "一些",
    "已经",
    "还是",
    "觉得",
    "微博",
    "真的",
    "可以",
    "需要",
    "进行",
    "今天",
    "现在",
    "因为",
    "所以",
    "没有",
    "不是",
    "就是",
    "非常",
    "大家",
    "自己",
    "看到",
    "支持",
    "关注",
    "一下",
    "什么",
    "还有",
}

POSITIVE_WORDS = {
    "支持",
    "认可",
    "喜欢",
    "不错",
    "优秀",
    "赞同",
    "感谢",
    "期待",
    "开心",
    "放心",
    "看好",
    "满意",
    "成功",
    "进步",
}

NEGATIVE_WORDS = {
    "反对",
    "失望",
    "生气",
    "糟糕",
    "离谱",
    "批评",
    "担心",
    "质疑",
    "难过",
    "愤怒",
    "不好",
    "差劲",
    "失败",
    "问题",
    "压力",
}


class ContentAnalyzer:
    def analyze(self, texts: list[str], label: str) -> AnalysisSection:
        cleaned = [item.strip() for item in texts if item and item.strip()]
        if not cleaned:
            return AnalysisSection(
                summary=f"{label}暂无可分析内容。",
                topics=[],
                topic_stats=[],
                viewpoints=[],
                sentiment="中性",
                positive_count=0,
                negative_count=0,
                neutral_count=0,
            )

        topic_counter: Counter[str] = Counter()
        all_sentences: list[str] = []
        positive_count = 0
        negative_count = 0
        neutral_count = 0

        for text in cleaned:
            topic_counter.update(self._tokenize(text))
            sentences = split_sentences(text)
            all_sentences.extend(sentences)
            score = self._sentiment_score(text)
            if score > 0:
                positive_count += 1
            elif score < 0:
                negative_count += 1
            else:
                neutral_count += 1

        topics = [word for word, _ in topic_counter.most_common(settings.analysis_top_k)]
        topic_stats = [
            TopicStat(topic=word, count=count)
            for word, count in topic_counter.most_common(settings.analysis_top_k)
        ]
        sentiment = self._label_sentiment(positive_count, negative_count, neutral_count)
        viewpoints = self._select_viewpoints(all_sentences, topics)
        summary = self._build_summary(
            label=label,
            topics=topics,
            viewpoints=viewpoints,
            sentiment=sentiment,
            positive_count=positive_count,
            negative_count=negative_count,
            neutral_count=neutral_count,
        )

        return AnalysisSection(
            summary=summary,
            topics=topics,
            topic_stats=topic_stats,
            viewpoints=viewpoints,
            sentiment=sentiment,
            positive_count=positive_count,
            negative_count=negative_count,
            neutral_count=neutral_count,
        )

    def _tokenize(self, text: str) -> list[str]:
        tokens = []
        for token in jieba.cut(text, cut_all=False):
            value = token.strip()
            if len(value) <= 1:
                continue
            if value.isdigit():
                continue
            if value.lower().startswith("http"):
                continue
            if value in STOPWORDS:
                continue
            tokens.append(value)
        return tokens

    def _sentiment_score(self, text: str) -> int:
        positive_hits = sum(1 for word in POSITIVE_WORDS if word in text)
        negative_hits = sum(1 for word in NEGATIVE_WORDS if word in text)
        return positive_hits - negative_hits

    def _label_sentiment(self, positive_count: int, negative_count: int, neutral_count: int) -> str:
        if positive_count == negative_count == 0:
            return "中性"
        if positive_count >= negative_count * 1.5 and positive_count > 0:
            return "正面"
        if negative_count >= positive_count * 1.5 and negative_count > 0:
            return "负面"
        if positive_count == 0 and neutral_count > 0 and negative_count == 0:
            return "中性"
        return "分化"

    def _select_viewpoints(self, sentences: list[str], topics: list[str]) -> list[str]:
        ranked: list[tuple[int, int, str]] = []
        topic_set = set(topics[:4])
        for sentence in sentences:
            score = sum(1 for topic in topic_set if topic and topic in sentence)
            if score == 0 and len(ranked) > settings.analysis_viewpoint_count * 3:
                continue
            sentiment_bonus = abs(self._sentiment_score(sentence))
            ranked.append((score, sentiment_bonus, truncate_text(sentence, 80)))

        ranked.sort(key=lambda item: (item[0], item[1], len(item[2])), reverse=True)
        picked = unique_preserve_order([item[2] for item in ranked])
        return picked[: settings.analysis_viewpoint_count]

    def _build_summary(
        self,
        label: str,
        topics: list[str],
        viewpoints: list[str],
        sentiment: str,
        positive_count: int,
        negative_count: int,
        neutral_count: int,
    ) -> str:
        topic_text = "、".join(topics[:5]) if topics else "暂无明显高频主题"
        viewpoint_text = "；".join(viewpoints[:3]) if viewpoints else "暂无稳定观点样本"
        return (
            f"{label}高频话题集中在{topic_text}。"
            f"整体态度倾向为{sentiment}，正面 {positive_count} 条、负面 {negative_count} 条、"
            f"中性 {neutral_count} 条。代表性观点包括：{viewpoint_text}。"
        )
