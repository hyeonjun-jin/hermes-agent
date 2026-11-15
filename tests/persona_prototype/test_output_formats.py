"""Formatting must retain evidence and render usable Markdown without HTML breaks."""
import re

import pytest

from persona_prototype.personalization import format_answer
from persona_prototype.output_format import format_matches


@pytest.mark.parametrize('raw', [
    '현재 단계: prototype\n수율: 98.2%\n기준일: 2026-11-15\n근거: [doc-1], [doc-42]\n일정: 미확정 | 추가 확인 필요',
    '| 내용 |\n|---|\n| 수율 98.2%<br>2026-11-15 [doc-42]<br/>일정 미확정 |',
    '| 내용 |\n|---|\n| 수율: 98.2%<br>기준일: 2026-11-15 [doc-42]<br>일정: 미확정 |',
    '| 항목 | 내용 |\n|---|---|\n| 수율 | 98.2%<BR />2026-11-15 [doc-42] |\n| 일정 | 미확정 |',
])
def test_table_repair_keeps_values_and_uncertainty_in_multiple_columns(raw):
    table, audit = format_answer(raw, 'table')
    assert '<br' not in table.lower()
    assert len(re.findall(r'(?<!\\)\|', table.splitlines()[0])) >= 3
    for token in ('98.2%', '2026-11-15', '[doc-42]', '미확정'):
        assert token in table
    assert format_matches(table, 'table')
    assert audit['fallback_applied']
    assert format_answer(table, 'table')[0] == table


def test_labeled_rows_and_pipes_do_not_turn_into_extra_columns():
    raw = '프로젝트: atlas\n제약: A | B, 최소 2개\n시각: 12:30\n비고: 문서에서 미발견, 실제 부재는 미확인'
    table, _ = format_answer(raw, 'table')
    assert '| 항목 | 내용 |' in table
    assert '| 프로젝트 | atlas |' in table
    assert 'A \\| B, 최소 2개' in table and '12:30' in table
    assert '문서에서 미발견, 실제 부재는 미확인' in table
    assert not format_matches('| 내용 |\n|---|\n설명만 존재', 'table')


def test_existing_valid_formats_and_explanation_are_unchanged():
    table = '| 항목 | 내용 |\n|---|---|\n| 일정 | 미확인 [doc-3] |'
    assert format_answer(table, 'table') == (table, {'requested': 'table', 'raw_valid': True, 'fallback_applied': False})
    assert format_answer('- 일정 미확인 [doc-3]', 'bullets')[0] == '- 일정 미확인 [doc-3]'
    text = '일정 미확인.\n\n[doc-3] 2026-11-15'
    assert format_answer(text, 'explanation')[0] == text
