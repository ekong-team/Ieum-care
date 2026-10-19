"""Optional Anthropic Messages adapter; disabled until explicitly configured.

Official API reference: https://platform.claude.com/docs/en/api/messages/create
No SDK dependency, endpoint override, tools, hidden retries or implicit API calls.
"""
import json
import os
import urllib.request


class AnthropicRevisionProvider:
    kind = 'external_llm'
    def __init__(self, model, *, max_tokens=2000, timeout=30, max_calls=2):
        if not model or type(max_tokens) is not int or not 1 <= max_tokens <= 4000:
            raise ValueError('model and bounded output tokens required')
        if not 1 <= timeout <= 60 or type(max_calls) is not int or not 1 <= max_calls <= 5:
            raise ValueError('invalid provider limits')
        self.model, self.max_tokens, self.timeout, self.max_calls = model, max_tokens, timeout, max_calls
        self.calls = 0
        self.identity = f'anthropic:{model}:{max_tokens}:{timeout}:{max_calls}'

    def __call__(self, system, payload):
        key = os.environ.get('ANTHROPIC_API_KEY')
        if not key:
            raise RuntimeError('provider_not_configured')
        if self.calls >= self.max_calls:
            raise RuntimeError('provider_call_limit')
        user = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        if len(user.encode('utf-8')) > 80000:
            raise ValueError('input_size_limit')
        self.calls += 1
        data = json.dumps(dict(model=self.model, max_tokens=self.max_tokens, system=system,
                               messages=[dict(role='user', content=user)]), ensure_ascii=False).encode('utf-8')
        request = urllib.request.Request('https://api.anthropic.com/v1/messages', data=data,
            headers={'x-api-key': key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            result = json.loads(response.read(1000000))
        output = ''.join(b['text'] for b in result.get('content', []) if b.get('type') == 'text')
        # Even a malformed/truncated response may be billed. Preserve receipt/usage,
        # while returning no usable proposal and never silently repairing it.
        proposal = None
        output_status = 'incomplete'
        if result.get('stop_reason') == 'end_turn':
            try:
                proposal = json.loads(output)
                output_status = 'json_received'
            except ValueError:
                output_status = 'invalid_json'
        return dict(proposal=proposal, provenance=dict(kind='external_llm', provider='anthropic',
                    model=result.get('model'), response_id=result.get('id'), usage=result.get('usage', {}),
                    output_status=output_status, stop_reason=result.get('stop_reason'), cost_krw=None, cost_status='not_computed'))
