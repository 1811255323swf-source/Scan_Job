from __future__ import annotations

from models import Job, ScoreResult


def _contains_any(text: str, keywords: list[str]) -> list[str]:
    text_casefold = text.casefold()
    return [keyword for keyword in keywords if keyword.casefold() in text_casefold]


def _level(score: int) -> str:
    if score >= 90:
        return "重点推荐"
    if score >= 70:
        return "建议关注"
    if score >= 50:
        return "备选"
    return "过滤"


def score_job(job: Job, config: dict) -> ScoreResult:
    text = job.search_text
    position_text = job.position
    keywords = config.get("keywords", {})
    scoring = config.get("scoring", {})
    profile = config.get("user_profile", {})

    positive_keywords = keywords.get("positive", [])
    negative_keywords = keywords.get("negative", [])
    matched_positive = _contains_any(text, positive_keywords)
    negative_in_position = _contains_any(position_text, negative_keywords)
    negative_in_text = _contains_any(text, negative_keywords)

    score = 0
    matched_rules: list[str] = []
    penalties: list[str] = []

    for rule in scoring.get("rules", []):
        rule_keywords = rule.get("keywords", [])
        matched = _contains_any(text, rule_keywords)
        if matched:
            value = int(rule.get("score", 0))
            score += value
            matched_rules.append(f"{rule.get('name', '/'.join(matched))} +{value}")

    target_locations = profile.get("target_locations", [])
    location_matches = _contains_any(job.location or text, target_locations)
    if location_matches:
        value = int(scoring.get("location_score", 0))
        score += value
        matched_rules.append(f"目标地点({','.join(location_matches)}) +{value}")

    graduation_year = str(profile.get("graduation_year", "")).strip()
    graduation_text = f"{job.graduation_year} {text}"
    if graduation_year and (
        graduation_year in graduation_text
        or "不限" in graduation_text
        or "在校" in graduation_text
        or "本科" in graduation_text
    ):
        value = int(scoring.get("graduation_score", 0))
        score += value
        matched_rules.append(f"{graduation_year}届可投 +{value}")

    if not matched_positive:
        value = int(scoring.get("non_target_penalty", -30))
        score += value
        penalties.append(f"缺少目标方向关键词 {value}")

    if negative_in_text:
        value = int(scoring.get("negative_keyword_penalty", -30))
        score += value
        penalties.append(f"包含排除关键词({','.join(negative_in_text)}) {value}")

    conflict_terms = ["全职", "一年以上", "12个月", "每周5天", "立即到岗长期"]
    if _contains_any(text, conflict_terms):
        value = int(scoring.get("internship_conflict_penalty", -10))
        score += value
        penalties.append(f"实习周期可能冲突 {value}")

    excluded = bool(negative_in_position) or not matched_positive
    score = max(0, min(100, score))
    return ScoreResult(
        score=score,
        level=_level(score),
        matched_rules=matched_rules,
        penalties=penalties,
        excluded=excluded,
    )

