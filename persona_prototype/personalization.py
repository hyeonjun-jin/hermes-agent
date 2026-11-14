"""Small explicit bilingual vocabulary and lossless output-shape fallback."""
import re

TAGS = ("delivery", "risk", "onboarding")
ALIASES = {"project": ("project", "프로젝트"), "plan": ("plan", "계획", "일정"),
           "delivery": ("delivery", "deployment", "배포"), "risk": ("risk", "위험", "검증"),
           "onboarding": ("onboarding", "beginner", "초보", "온보딩")}


def terms(text):
    words = re.findall(r"\w+", text.lower())
    return {next((canonical for canonical, aliases in ALIASES.items()
                  if any(w.startswith(a) for a in aliases)), w) for w in words}


def format_answer(text, style):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    valid = (style == "explanation" or
             (style == "bullets" and bool(lines) and all(re.match(r"^[-*] ", line) for line in lines)) or
             (style == "table" and len(lines) >= 2 and lines[0].startswith("|")
              and bool(re.match(r"^\|[ :|-]+\|$", lines[1]))))
    if valid or not text.strip():
        return text, {"requested": style, "raw_valid": valid, "fallback_applied": False}
    if style == "bullets":
        result = "\n".join(line if re.match(r"^[-*] ", line) else "- " + line for line in lines)
    else:
        cell = text.replace("|", "\\|").replace("\n", "<br>")
        result = "| 내용 |\n|---|\n| " + cell + " |"
    return result, {"requested": style, "raw_valid": False, "fallback_applied": True}
