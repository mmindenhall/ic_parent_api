"""Infinite Campus API Client."""
import logging

from urllib.parse import urljoin

import aiohttp

from .errors import InfiniteCampusError
from .models.base import StudentResponse, CourseResponse, \
    AssignmentResponse, TermResponse, ScheduleDayResponse, GradeEnrollmentResponse

_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel(logging.INFO)


def _enable_debug_logging():
    _LOGGER.setLevel(logging.DEBUG)


class InfiniteCampusApiClient():
    """Infinite Campus Parent API Client."""
    def __init__(
        self,
        base_url,
        username,
        secret,
        district,
        path: str = None,
        debug=False,
        cookies: dict = None,
    ):
        if debug:
            _enable_debug_logging()

        self._base_url = base_url

        _LOGGER.debug(f"generated base url: {self._base_url}")

        self._username = username
        self._secret = secret
        self._district = district
        # Pre-authenticated session cookies (e.g. from an SSO browser login).
        # When set, verify.jsp login is skipped.
        self._cookies = cookies
        self._headers = {"Accept": "application/json"}

    async def authenticate(self, session):
        """Test if we can authenticate with the district."""
        try:
            request_url = urljoin(
                self._base_url, (f"/campus/verify.jsp?nonBrowser=true"
                                 f"&username={self._username}"
                                 f"&password={self._secret}"
                                 f"&appName={self._district}"
                                 "&portalLoginPage=parents")
            )
            async with session.post(request_url) as authresponse:
                response = authresponse
                responsetext = await response.text()
                if "samlLoginThruCampus" in responsetext:
                    raise InfiniteCampusError(
                        400, "District requires SSO login; pass session cookies via cookies=")
                if response.status == 200 and "password-error" not in responsetext:
                    return True
                raise InfiniteCampusError(400, "Bad Credentials")
        except Exception as error:
            raise InfiniteCampusError(400, error)

    async def _get_request(self, end_url: str):
        """Perform GET request to API endpoint."""
        request_url = urljoin(self._base_url, end_url)
        async with aiohttp.ClientSession(cookies=self._cookies) as session:
            authenticated = True if self._cookies else await self.authenticate(session)
            if authenticated:
                async with session.get(f"{request_url}", headers=self._headers) as resp:
                    response = resp
                    responsetext = await resp.text()
                    response_json = await resp.json()
                    if response.status >= 400:
                        raise InfiniteCampusError(response.status, responsetext)
                    return response_json
            raise InfiniteCampusError(400, "Bad Credentials")

    async def get_students(self) -> list[StudentResponse]:
        """Get Infinite Campus Students."""
        parsed_response = await self._get_request("/campus/api/portal/students")
        scheduledayslist: list[ScheduleDayResponse] = []
        if parsed_response:
            studentresp: list[StudentResponse] = [StudentResponse(**resp) for resp in parsed_response]
            for student in studentresp:
                for enrollment in student.enrollments:
                    scheduledays = await self.get_scheduledays(enrollment.calendarID)
                    scheduledayslist.extend(scheduledays)
                student.scheduleDays = scheduledayslist
            return studentresp
        return []

    async def get_courses(self, student_id: int) -> list[CourseResponse]:
        """Get Infinite Campus Courses."""
        parsed_response = await self._get_request(f"/campus/resources/portal/roster?&personID={student_id}")
        if parsed_response:
            return [CourseResponse(**resp) for resp in parsed_response]
        return []

    async def get_assignments(self, student_id: int) -> list[AssignmentResponse]:
        """Get Infinite Campus Courses."""
        parsed_response = await self._get_request(
            f"/campus/api/portal/assignment/listView?&personID={student_id}"
        )
        if parsed_response:
            return [AssignmentResponse(**resp) for resp in parsed_response]
        return []

    async def get_terms(self, structure_id: int = 1210) -> list[TermResponse]:
        """Get Infinite Campus Terms for a schedule structure."""
        parsed_response = await self._get_request(f"/campus/resources/term?structureID={structure_id}")
        if parsed_response:
            return [TermResponse(**resp) for resp in parsed_response]
        return []

    async def get_scheduledays(self, calendar_id: int) -> list[ScheduleDayResponse]:
        """Get Infinite Campus Courses."""
        parsed_response = await self._get_request(
            f"/campus/resources/calendar/instructionalDay?calendarID={calendar_id}"
        )
        if parsed_response:
            return [ScheduleDayResponse(**resp) for resp in parsed_response]
        return []

    async def get_grades(self, student_id: int) -> list[GradeEnrollmentResponse]:
        """Get Infinite Campus grades (per enrollment, term, course and grading task)."""
        parsed_response = await self._get_request(f"/campus/resources/portal/grades?personID={student_id}")
        if parsed_response:
            return [GradeEnrollmentResponse(**resp) for resp in parsed_response]
        return []
