from __future__ import annotations

import os
from textwrap import dedent

from models import Job, ScoreResult
from settings import as_bool


class AIAnalyzer:
    def __init__(self, config: dict) -> None:
        self.config = config
        ai_config = config.get("ai", {})
        self.provider = str(ai_config.get("provider", "openai")).strip().lower()
        self.model = os.getenv("OPENAI_MODEL") or str(ai_config.get("model", "gpt-5"))
        self.base_url = os.getenv("OPENAI_BASE_URL") or str(ai_config.get("base_url", "") or "")
        self.max_output_tokens = int(ai_config.get("max_output_tokens", 700))

    def enabled(self) -> bool:
        if self.provider in {"", "disabled", "none", "false"}:
            return False
        if self.provider == "openai":
            return bool(os.getenv("OPENAI_API_KEY"))
        if self.provider == "openai_compatible":
            return bool(os.getenv("OPENAI_API_KEY") or os.getenv("DEEPSEEK_API_KEY"))
        return False

    def analyze(self, job: Job, score_result: ScoreResult) -> str:
        if not self.enabled():
            return self.fallback(job, score_result)

        prompt = self._build_prompt(job, score_result)
        try:
            if self.provider == "openai":
                return self._analyze_with_openai_responses(prompt)
            return self._analyze_with_chat_completions(prompt)
        except Exception as exc:  # noqa: BLE001 - report safe error class only
            return f"AI分析暂不可用：{exc.__class__.__name__}。已保留规则评分结果。"

    def fallback(self, job: Job, score_result: ScoreResult) -> str:
        advantages = "、".join(score_result.matched_rules) or "岗位信息中暂未发现明显匹配项"
        penalties = "、".join(score_result.penalties) or "暂无明显短板"
        suggestion = "优先投递" if score_result.score >= 90 else "建议关注" if score_result.score >= 70 else "可作为备选"
        return dedent(
            f"""
            匹配程度：{score_result.level}（规则评分 {score_result.score}）

            优势：
            1. {advantages}

            不足：
            1. {penalties}

            建议：
            {suggestion}
            """
        ).strip()

    def _build_prompt(self, job: Job, score_result: ScoreResult) -> str:
        profile = self.config.get("user_profile", {})
        skills = "、".join(profile.get("skills", []))
        learning = "、".join(profile.get("learning", []))
        return dedent(
            f"""
            你是计算机本科生求职顾问。请用简洁中文分析这个实习岗位是否适合用户。

            用户背景：
            - 学校：{profile.get("school", "")}
            - 专业：{profile.get("major", "")}
            - 毕业年份：{profile.get("graduation_year", "")}
            - 已掌握：{skills}
            - 正在学习：{learning}

            岗位信息：
            - 公司：{job.company}
            - 岗位：{job.position}
            - 地点：{job.location}
            - 发布时间：{job.published_at}
            - 学历要求：{job.education}
            - 毕业年份要求：{job.graduation_year}
            - 实习周期：{job.internship_period}
            - 岗位描述：{job.description}
            - 技术要求：{job.requirements}
            - 规则评分：{score_result.score}
            - 命中规则：{"；".join(score_result.matched_rules)}
            - 扣分项：{"；".join(score_result.penalties)}

            请严格按下面格式输出：
            匹配程度：

            优势：
            1.
            2.

            不足：
            1.
            2.

            建议：
            """
        ).strip()

    def _analyze_with_openai_responses(self, prompt: str) -> str:
        from openai import OpenAI

        client = OpenAI()
        response = client.responses.create(
            model=self.model,
            input=prompt,
            max_output_tokens=self.max_output_tokens,
        )
        return response.output_text.strip()

    def _analyze_with_chat_completions(self, prompt: str) -> str:
        from openai import OpenAI

        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
        client_kwargs = {"api_key": api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        client = OpenAI(**client_kwargs)
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "你是严谨、务实的计算机实习求职顾问。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=self.max_output_tokens,
            temperature=0.2,
        )
        return (response.choices[0].message.content or "").strip()


def ai_enabled_from_config(config: dict) -> bool:
    ai_config = config.get("ai", {})
    return as_bool(ai_config.get("enabled", True))

