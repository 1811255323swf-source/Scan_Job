from models import Job
from analyzer.scorer import score_job


def base_config():
    return {
        "keywords": {
            "positive": ["C++", "Linux", "Socket", "后端", "网络", "epoll"],
            "negative": ["前端", "测试", "销售"],
        },
        "user_profile": {"target_locations": ["武汉"], "graduation_year": "2028"},
        "scoring": {
            "rules": [
                {"name": "C++", "keywords": ["C++"], "score": 20},
                {"name": "Linux", "keywords": ["Linux"], "score": 20},
                {"name": "Socket/网络编程", "keywords": ["Socket", "网络编程"], "score": 20},
                {"name": "epoll/高并发", "keywords": ["epoll"], "score": 10},
                {"name": "后端/服务端", "keywords": ["后端", "服务端"], "score": 15},
            ],
            "location_score": 15,
            "graduation_score": 10,
            "non_target_penalty": -30,
            "negative_keyword_penalty": -30,
            "internship_conflict_penalty": -10,
        },
    }


def test_cpp_linux_wuhan_job_scores_high():
    job = Job(
        source="test",
        company="Example",
        position="C++ Linux 后端开发实习生",
        location="武汉",
        graduation_year="2028届",
        requirements="熟悉 Socket、epoll、多线程网络编程",
        url="https://example.com/job/1",
    )

    result = score_job(job, base_config())

    assert result.score >= 90
    assert result.level == "重点推荐"
    assert not result.excluded


def test_frontend_position_is_excluded():
    job = Job(
        source="test",
        company="Example",
        position="前端开发实习生",
        location="武汉",
        requirements="Vue React",
        url="https://example.com/job/2",
    )

    result = score_job(job, base_config())

    assert result.excluded
    assert result.level == "过滤"



def test_generic_java_backend_is_excluded_when_cpp_direction_is_required():
    config = base_config()
    config["keywords"]["required"] = ["C++", "Linux", "Socket", "服务端"]
    job = Job(
        source="test",
        company="Example",
        position="Java后端实习生",
        location="北京",
        requirements="Spring Boot",
        url="https://example.com/job/java",
    )

    result = score_job(job, config)

    assert result.excluded
