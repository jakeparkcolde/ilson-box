"""질문의 복잡도에 따른 출력 예산. 근거와 모델은 바꾸지 않는 비교 실험이다."""
import re


def answer_budget(question, mode, experiment):
    if experiment not in ('concise_answer_v1', 'evidence_concise_v1'):
        return None
    complex_question = bool(re.search(
        r'비교|차이|\bvs\b|장단점|전략|계획|분석|보고서|코드|구현|예제|절차|방법|사용법|혜택|조건|추천|저렴',
        question, re.I))
    if mode == 'deep':
        return dict(kind='deep', max_claims=10, max_claim_characters=1800,
                    max_table_rows=8, first_claim_characters=240)
    return dict(kind='complex' if complex_question else 'simple',
                max_claims=6 if complex_question else 3,
                max_claim_characters=700 if complex_question else 450,
                max_table_rows=5 if complex_question else 3,
                first_claim_characters=200)


def budget_instructions(budget):
    if budget is None:
        return ''
    return (f'\n출력 예산: 주장은 최대 {budget["max_claims"]}개이며 개수를 채우려고 내용을 늘리지 않는다. '
            f'첫 claim은 출처가 연결된 직접적인 결론 1~2문장, {budget["first_claim_characters"]}자 이내로 먼저 완성한다. '
            '근거가 부족하면 첫 문단에 확인되지 않은 범위를 분명히 말한다. '
            '나머지 문단에는 새로운 근거·조건만 넣고 결론을 반복하지 않는다. '
            '짧게 쓰더라도 질문에 요청된 항목, 지역·기준일·단위·편도/왕복, 예외·불확실성을 삭제하지 않는다. '
            '질문에 비교 의도가 없으면 comparison은 null이다. 후속 질문은 2개만 작성한다.')
