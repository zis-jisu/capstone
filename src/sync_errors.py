"""Safe, stage-specific diagnostics for the Slack -> ML streaming operation."""
import re
from fastapi import HTTPException

STAGES = {'database': '업무 DB 조회', 'collect': 'Slack MCP 수집',
          'extract': '변경 확인·업무 추출·저장', 'graph': 'ML 그래프 검증', 'training': 'ML 학습'}
SLACK_CODES = {'invalid_auth', 'not_authed', 'token_revoked', 'token_expired',
               'account_inactive', 'missing_scope', 'not_allowed_token_type',
               'channel_not_found', 'not_in_channel', 'thread_not_found',
               'ratelimited', 'restricted_action', 'access_denied', 'is_archived'}


def exception_leaves(error):
    if isinstance(error, BaseExceptionGroup):
        return [leaf for child in error.exceptions for leaf in exception_leaves(child)]
    return [error]


def sync_error_detail(error, stage):
    """Never return arbitrary third-party bodies, credentials, or Slack messages."""
    leaves = exception_leaves(error)
    for exc in leaves:
        text = str(exc)
        if isinstance(exc, HTTPException):
            text = str(exc.detail)
        for code in sorted(SLACK_CODES):
            if re.search(r'(?<![a-z_])' + code + r'(?![a-z_])', text):
                hints = {
                    'missing_scope': 'SLACK_TOKEN의 채널 대화·스레드 읽기 및 users:read 권한을 확인하세요.',
                    'invalid_auth': 'Railway SLACK_TOKEN이 유효한 Slack 토큰인지 확인하세요.',
                    'not_authed': 'Railway SLACK_TOKEN 값을 확인하세요.',
                    'not_allowed_token_type': '채널 스레드를 읽을 수 있는 User OAuth Token을 사용하세요.',
                    'not_in_channel': '토큰 계정을 해당 업무 채널에 참여시키세요.',
                    'channel_not_found': '토큰 계정의 채널 접근 권한과 Slack 워크스페이스를 확인하세요.',
                    'ratelimited': 'Slack 요청 한도에 도달했습니다. 잠시 후 다시 실행하세요.',
                }
                return f'Slack API 오류: {code}. ' + hints.get(code, 'Slack 토큰의 상태와 채널 접근 권한을 확인하세요.')
        http = re.search(r'Slack HTTP error (\d{3})', text)
        if http:
            return 'Slack HTTP 오류 ' + http[1] + (' · 요청 한도에 도달했습니다. 잠시 후 다시 실행하세요.' if http[1] == '429' else '')
        db = re.search(r'Supabase ([a-z_]+) (GET|POST|DELETE) failed: HTTP (\d{3})', text)
        if db:
            return f'Supabase {db[1]} {db[2]} 오류 (HTTP {db[3]}). 테이블·키·접근 권한을 확인하세요.'
        openai = re.search(r'OpenAI API error (\d{3})', text)
        if openai:
            codes = [c for c in ['model_not_found', 'invalid_api_key', 'insufficient_quota', 'rate_limit_exceeded'] if c in text]
            return f'업무 추출 API 오류 (HTTP {openai[1]})' + (' · ' + ', '.join(codes) if codes else '')
        ml = re.search(r'ML API returned HTTP (\d{3})', text)
        if ml:
            return 'ML API 오류 (HTTP ' + ml[1] + '). MODEL_API_URL과 MODEL_API_KEY를 확인하세요.'
        if isinstance(exc, (TimeoutError, ConnectionError)):
            return STAGES.get(stage, stage) + ' 연결 시간이 초과되거나 연결이 끊겼습니다.'
        if isinstance(exc, HTTPException):
            # Only allow messages authored by this app, never arbitrary HTTP bodies.
            known = ['MCP collection failed', 'Unexpected MCP response', 'ML API is unavailable',
                     'MODEL_API_KEY is not configured on LINK-ing Railway',
                     'MODEL_API_URL must use HTTPS', 'SLACK_TOKEN is not configured on Railway']
            if text in known:
                return text
        # Internal validation messages contain no remote response body. Restrict to
        # fixed prefixes; evidence-validation messages can include Slack text.
        safe_prefixes = ('WORK-00020 ', 'No WORK-00020 ', 'MCP returned messages outside ',
                         'OPENAI_API_KEY is required ', 'Previously stored Slack messages are missing;',
                         'Extraction did not preserve ', 'Extraction attempted to update ',
                         'Slack names conflict ', 'DB changed during extraction;',
                         'An unfinished sync plan exists;', 'A Task is shared ', 'An Event is shared ',
                         'Raw-message schema not confirmed.', 'DB sync verification failed:',
                         'Slack raw message verification failed', 'Graph RPC failed:',
                         'ML training failed', 'ML training did not confirm completion')
        if text.startswith(safe_prefixes):
            return text.split('\n')[0][:240]
    names = ', '.join(sorted({type(exc).__name__ for exc in leaves}))
    return STAGES.get(stage, stage) + ' 처리 오류 (' + names + '). 서버의 WORK20_SYNC 로그를 확인하세요.'
