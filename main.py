from fastapi import FastAPI, UploadFile, File, HTTPException
from bs4 import BeautifulSoup
import re

app = FastAPI(title="Course Catalog API")

# In-memory course catalog.
courses = {}


def course_codes(text: str) -> list[str]:
    """Extract course codes such as COSC 3506 or COSC3506."""
    if not text:
        return []

    matches = re.findall(r"\b[A-Za-z]{2,6}\s*-?\s*\d{4}\b", text)
    result = []

    for match in matches:
        code = re.sub(r"\s+", " ", match.strip().replace("-", " ")).upper()
        if code not in result:
            result.append(code)

    return result


def clean_text(value: str) -> str:
    return " ".join(value.split()).strip()


def parse_catalog(html: bytes) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    table = soup.find("table")
    if table is None:
        raise ValueError("No course catalog table found")

    rows = table.find_all("tr")
    if not rows:
        raise ValueError("No rows found in catalog")

    # Read column names from the header so parsing is based on structure,
    # not on specific course codes or titles.
    headers = [
        clean_text(cell.get_text(" ", strip=True)).lower()
        for cell in rows[0].find_all(["th", "td"])
    ]

    required = {
        "course code": "course_code",
        "title": "title",
        "credits": "credits",
        "prerequisites": "prerequisites",
        "cross-listed": "cross_listed",
    }

    indexes = {}
    for header, field in required.items():
        if header in headers:
            indexes[field] = headers.index(header)

    missing = [field for field in required.values() if field not in indexes]
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")

    parsed = {}

    for row in rows[1:]:
        cells = row.find_all("td")
        if not cells:
            continue

        values = [clean_text(cell.get_text(" ", strip=True)) for cell in cells]

        # Ignore malformed rows instead of crashing the entire import.
        if len(values) <= max(indexes.values()):
            continue

        code = values[indexes["course_code"]].upper()
        if not code:
            continue

        title = values[indexes["title"]]
        credits_text = values[indexes["credits"]]

        try:
            credits = int(float(credits_text))
        except ValueError:
            credits = credits_text

        prereq_text = values[indexes["prerequisites"]]
        cross_text = values[indexes["cross_listed"]]

        parsed[code] = {
            "course_code": code,
            "title": title,
            "credits": credits,
            "prerequisites": course_codes(prereq_text),
            "cross_listed": course_codes(cross_text),
        }

    return parsed


@app.post("/api/v1/admin/catalog/import")
async def import_catalog(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    content = await file.read()

    try:
        imported = parse_catalog(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    courses.clear()
    courses.update(imported)

    return {
        "message": "Catalog imported successfully",
        "courses_imported": len(courses),
    }


@app.get("/api/v1/catalog/courses/{course_code}")
async def get_course(course_code: str):
    # Accept both COSC 3506 and COSC3506.
    normalized = re.sub(r"\s+", " ", course_code.strip().upper())

    if normalized not in courses:
        compact = normalized.replace(" ", "")
        for code in courses:
            if code.replace(" ", "") == compact:
                normalized = code
                break
        else:
            raise HTTPException(status_code=404, detail="Course not found")

    return courses[normalized]
