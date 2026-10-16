"""Base Infinite Campus Class."""
import logging

from .models.student import Student
from .models.course import Course
from .models.assignment import Assignment
from .models.term import Term
from .ic_api_client import InfiniteCampusApiClient
from .models.base import GradeEnrollmentResponse

_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel(logging.INFO)


class InfiniteCampus():
    """Define InfiniteCampus Class."""
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
        self._api_client = InfiniteCampusApiClient(
            base_url, username, secret, district, path, debug, cookies)

        if debug:
            _LOGGER.setLevel(logging.DEBUG)

    async def authenticate(self, session) -> bool:
        """Authenticate with Infinite Campus."""
        authresp = await self._api_client.authenticate(session)
        return authresp

    async def students(self) -> list[Student]:
        """Get Students."""
        studentsresp = await self._api_client.get_students()
        students = [Student(response) for response in studentsresp]
        return students

    async def courses(self, student_id) -> list[Course]:
        """Get Courses: must supply student id."""
        coursesresp = await self._api_client.get_courses(student_id)
        courses = [Course(response) for response in coursesresp]
        return courses

    async def assignments(self, student_id) -> list[Assignment]:
        """Get Assignments: must supply student id."""
        assignmentsresp = await self._api_client.get_assignments(student_id)
        assignments = [Assignment(response) for response in assignmentsresp]
        return assignments

    async def terms(self, structure_id: int = 1210) -> list[Term]:
        """Get Terms for a schedule structure (a student's enrollment/assignments carry structureID)."""
        termsresp = await self._api_client.get_terms(structure_id)
        terms = [Term(response) for response in termsresp]
        return terms

    async def grades(self, student_id) -> list[GradeEnrollmentResponse]:
        """Get Grades: must supply student id. Returns the response models (enrollment > term > course > task)."""
        return await self._api_client.get_grades(student_id)
