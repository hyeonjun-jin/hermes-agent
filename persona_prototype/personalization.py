"""Small explicit bilingual vocabulary and lossless output-shape fallback."""
import re

from .output_format import _BREAK, format_matches, readable_table, table_rows

TAGS = ("delivery", "risk", "onboarding")
ALIASES = {"project": ("project", "프로젝트"), "plan": ("plan", "계획", "일정"),
           "delivery": ("delivery", "deployment", "배포"), "risk": ("risk", "위험", "검증"),
           "onboarding": ("onboarding", "beginner", "초보", "온보딩")}


def terms(text):
    words = re.findall(r"\w+", text.lower())
    return {next((canonical for canonical, aliases in ALIASES.items()
                  if any(w.startswith(a) for a in aliases)), w) for w in words}

def format_answer(text, style):
    valid = style == 'explanation' or format_matches(text, style)
    rows = table_rows(text) if style == 'table' else None
    improve_table = style == 'table' and (bool(_BREAK.search(text)) or (rows is not None and len(rows[0]) == 1))
    if (valid and not improve_table) or not text.strip():
        return text, {'requested': style, 'raw_valid': valid, 'fallback_applied': False}
    if style == 'bullets':
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        result = '\n'.join(line if re.match(r'^[-*] ', line) else '- ' + line for line in lines)
    else:
        result = readable_table(text)
    return result, {'requested': style, 'raw_valid': valid, 'fallback_applied': True,
                    'reason': 'readable_table' if improve_table else 'shape_mismatch',
                    'method': 'local_text_only; no model call or content summarization'}
