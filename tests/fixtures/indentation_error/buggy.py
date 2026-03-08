def categorise(score):
    """Return grade category based on numeric score (0-100)."""
    if score >= 90:
        grade = "A"
    elif score >= 80:
        grade = "B"
    elif score >= 70:
            grade = "C"   # over-indented — IndentationError at parse time
    elif score >= 60:
        grade = "D"
    else:
        grade = "F"
    return grade
