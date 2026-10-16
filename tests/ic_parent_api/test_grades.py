import asyncio

from ic_parent_api.ic_api_client import InfiniteCampusApiClient

RAW = [{
    "enrollmentID": 1, "extra": "ignored",
    "terms": [{
        "termID": 10, "termName": "S1", "startDate": "2026-08-19", "endDate": "2026-12-18", "termSeq": 1,
        "courses": [{
            "sectionID": 5, "courseName": "AP English", "dropped": False, "teacherDisplay": "x",
            "gradingTasks": [
                {"taskID": 230, "taskName": "1st 6 Weeks", "termID": 10, "sectionID": 5, "score": "D",
                 "percent": 62.5, "modifiedDate": "2026-09-24 13:12:00"},
                {"taskID": 1, "taskName": "Term Final", "termID": 10, "sectionID": 5, "progressScore": "B",
                 "progressPercent": 85.94, "progressPointsEarned": 241.5, "progressTotalPoints": 281.0},
                {"taskID": 2, "taskName": "Weekly Eligibility"},
            ]}]}]}]


def make_client(payload):
    client = InfiniteCampusApiClient("https://x", "u", "p", "d", cookies={"a": "b"})

    async def fake_get(url):
        fake_get.url = url
        return payload

    client._get_request = fake_get
    return client, fake_get


def test_get_grades_parses_terms_courses_and_tasks():
    client, fake = make_client(RAW)
    enrollments = asyncio.run(client.get_grades(1428303))
    assert fake.url == "/campus/resources/portal/grades?personID=1428303"
    course = enrollments[0].terms[0].courses[0]
    assert (enrollments[0].terms[0].termID, course.courseName, course.dropped) == (10, "AP English", False)
    first, final, bare = course.gradingTasks
    assert (first.score, first.percent, first.progressScore) == ("D", 62.5, None)
    assert (final.progressScore, final.progressPercent, final.progressPointsEarned) == ("B", 85.94, 241.5)
    assert (bare.score, bare.progressScore, bare.percent) == (None, None, None)


def test_get_grades_empty_response_is_empty_list():
    client, _ = make_client([])
    assert asyncio.run(client.get_grades(1)) == []
