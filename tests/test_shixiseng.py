from crawler.shixiseng import ShixisengCrawler


def test_shixiseng_parser_extracts_real_company_and_job_fields():
    crawler = ShixisengCrawler({"name": "shixiseng"}, {"app": {}})
    html = """
    <div data-intern-id="job-1">
      <div class="intern-detail__job">
        <p><a class="title" href="/intern/job-1">C++实习生</a></p>
        <p class="tip"><span class="city">武汉</span><span>5天/周</span><span>3个月</span></p>
      </div>
      <div class="intern-detail__company"><a class="title">示例科技</a></div>
      <span class="intern-label">可转正</span>
    </div>
    """

    jobs = crawler._parse_html(html, "https://www.shixiseng.com/interns")

    assert len(jobs) == 1
    assert jobs[0].position == "C++实习生"
    assert jobs[0].company == "示例科技"
    assert jobs[0].location == "武汉"
    assert jobs[0].url == "https://www.shixiseng.com/intern/job-1"
    assert "可转正" in jobs[0].description
