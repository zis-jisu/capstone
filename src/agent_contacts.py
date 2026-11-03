"""Contact suggestions are presentation data, never access grants."""
import re
from pydantic import BaseModel, Field


class ContactPerson(BaseModel):
    person_id: str = Field(default='', max_length=120)
    name: str = Field(min_length=1, max_length=150)
    role: str = Field(default='RELATED', max_length=40)


class ContactContext(BaseModel):
    current_person_id: str = Field(default='', max_length=120)
    current_person_name: str = Field(default='', max_length=150)
    absence_known: bool = False
    absent_people: list[ContactPerson] = Field(default_factory=list, max_length=100)
    candidates: list[ContactPerson] = Field(default_factory=list, max_length=100)


def contact_question(question):
    return bool(re.search(r'연락|문의|물어|물으면|물어볼|누구한테|누구에게|누구.*(?:확인|요청)|(?:확인|요청).*누구', question))


def contact_answer(question, context):
    if not context or not context.absence_known or not (context.current_person_id or context.current_person_name):
        return '현재 사용자 또는 해당 업무의 공백자 정보가 확인되지 않아 연락 대상을 안전하게 추천할 수 없습니다.'
    excluded_ids = {p.person_id for p in context.absent_people if p.person_id}
    excluded_names = {p.name.strip() for p in context.absent_people}
    if context.current_person_id:
        excluded_ids.add(context.current_person_id)
    if context.current_person_name.strip():
        excluded_names.add(context.current_person_name.strip())
    roles = {'OWNER': '담당자', 'APPROVER': '승인자', 'REVIEWER': '검토자',
             'COLLABORATOR': '협업자', 'ASSIGNEE': '담당자', 'RELATED': '관련자'}
    preferred = 'APPROVER' if '승인' in question else 'REVIEWER' if '검토' in question else 'OWNER'
    order = [preferred] + [r for r in roles if r != preferred]
    people, seen = [], set()
    for p in sorted(context.candidates, key=lambda p: order.index(p.role) if p.role in order else 99):
        name = p.name.strip()
        if (not name or p.role not in roles or p.person_id in excluded_ids or name in excluded_names
                or name in seen or (p.person_id and p.person_id in seen)):
            continue
        people.append(f'{name} ({roles[p.role]})')
        seen.add(name)
        if p.person_id:
            seen.add(p.person_id)
    if not people:
        return '현재 사용자와 해당 업무의 공백자를 제외하면, 업무 관계 정보에서 연락 가능한 대체 담당자를 확인할 수 없습니다.'
    return ('현재 사용자와 해당 업무의 공백자를 제외한 업무 관계 기준 연락 후보입니다.\n'
            + '\n'.join('- ' + p for p in people[:5])
            + '\n연결 역할을 기준으로 정리했으며, 현재 응답 가능 여부나 대체 담당 지정 여부는 별도 확인이 필요합니다.')

