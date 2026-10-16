from ic_tracker.model import ClassGrade


def test_letter_grades_show_percent_like_the_portal():
    assert ClassGrade("AP English", "D", 62.5).display == "D (62.5%)"
    assert ClassGrade("Pre-Calc", "D", 61.75).display == "D (61.75%)"
    assert ClassGrade("Pre-Calc", "F", 50.0).display == "F (50%)"
    assert ClassGrade("Seminar", "A", 100.0).display == "A (100%)"
    assert ClassGrade("History", "B+", 88.4).display == "B+ (88.4%)"


def test_rubric_levels_and_pass_marks_are_not_percentages():
    assert ClassGrade("Science", "3", 3.12).display == "3 (3.12)"
    assert ClassGrade("Advisement", "P", 3.0).display == "P (3)"


def test_partial_and_empty_grades():
    assert ClassGrade("x", "B", None).display == "B"
    assert ClassGrade("x", None, 71.5).display == "71.5%"
    assert ClassGrade("x", None, None).display == "-"
