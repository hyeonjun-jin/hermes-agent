"""Conservative mechanical checks, never a replacement for semantic verification."""
import re


def review(text, evidence):
    ids={item['source_id'] for item in evidence}
    cited=set(re.findall(r'\[([^\]\n]+)\]',text))
    source=' '.join(span['text'] for item in evidence for span in item['spans'])
    numbers=set(re.findall(r'(?<![\w-])[+-]?\d+(?:\.\d+)?%?',text))
    supported=set(re.findall(r'(?<![\w-])[+-]?\d+(?:\.\d+)?%?',source))
    return {'unknown_citations':sorted(cited-ids),'unmatched_numeric_tokens':sorted(numbers-supported),
            'human_review_required':True,'note':'숫자 토큰 일치도 기간·단위·인과관계의 타당성을 보장하지 않습니다.'}
