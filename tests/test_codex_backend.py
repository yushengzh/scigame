import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from experiments.codex_structured_backend import (
    CodexStructuredBackend, ISOLATION_CONFIG, _AppServerSession, validate_fresh_thread,
)
from role_benchmark import GenerationConfig, GenerationRequest, Message


def request(text='benchmark user input', **config):
    return GenerationRequest(
        messages=(Message('system', 'benchmark system instructions'), Message('user', text)),
        response_schema={'type': 'object', 'properties': {}, 'additionalProperties': False},
        config=GenerationConfig(**config), metadata={'purpose': 'test'},
    )


class FakeSession:
    instances = []
    resolved_model = 'gpt-5.5'
    final_text = '{}'
    extra_events = []
    token_usage = {'total': {'inputTokens': 23, 'outputTokens': 11,
                            'reasoningOutputTokens': 5, 'cachedInputTokens': 3}}
    account_type = 'chatgpt'
    turn_status = 'completed'
    fail_with = None

    def __init__(self, command, workspace, audit_dir, timeout_s):
        self.command = command
        self.workspace = workspace
        self.audit_dir = audit_dir
        self.timeout_s = timeout_s
        self.calls = []
        self.closed = False
        self.thread_id = 'thread-' + str(len(self.instances))
        self.events = []
        self.instances.append(self)
        assert not list(workspace.iterdir())

    def notify(self, method, params=None):
        self.calls.append((method, params))

    def rpc(self, method, params):
        self.calls.append((method, params))
        if method == 'initialize':
            return {'userAgent': 'fixture'}
        if method == 'account/read':
            return {'account': {'type': self.account_type}}
        if method == 'thread/start':
            return {'model': self.resolved_model, 'instructionSources': [],
                    'thread': {'id': self.thread_id, 'ephemeral': True, 'turns': [],
                               'cwd': str(self.workspace), 'forkedFromId': None,
                               'parentThreadId': None}}
        if method == 'turn/start':
            item = {'type': 'agentMessage', 'id': 'message-1', 'phase': 'final_answer',
                    'text': self.final_text}
            self.events = copy.deepcopy(self.extra_events) + [
                {'method': 'item/completed', 'params': {'threadId': self.thread_id,
                    'turnId': 'turn-1', 'item': item}},
                {'method': 'thread/tokenUsage/updated', 'params': {
                    'threadId': self.thread_id, 'turnId': 'turn-1', 'tokenUsage': self.token_usage}},
                {'method': 'turn/completed', 'params': {'threadId': self.thread_id,
                    'turn': {'id': 'turn-1', 'status': self.turn_status, 'items': [item]}}},
            ]
            return {'turn': {'id': 'turn-1'}}
        raise AssertionError('Unexpected RPC: ' + method)

    def next_event(self):
        if self.fail_with:
            raise self.fail_with
        return self.events.pop(0)

    def close(self):
        self.closed = True


class CodexBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.audit = Path(self.temp.name) / 'audit'
        FakeSession.instances = []
        FakeSession.resolved_model = 'gpt-5.5'
        FakeSession.final_text = '{}'
        FakeSession.extra_events = []
        FakeSession.token_usage = {'total': {'inputTokens': 23, 'outputTokens': 11,
            'reasoningOutputTokens': 5, 'cachedInputTokens': 3}}
        FakeSession.account_type = 'chatgpt'
        FakeSession.turn_status = 'completed'
        FakeSession.fail_with = None
        self.session_patch = patch('experiments.codex_structured_backend._AppServerSession', FakeSession)
        self.session_patch.start()
        self.addCleanup(self.session_patch.stop)
        executable = patch('experiments.codex_structured_backend.shutil.which', return_value='/test/codex')
        executable.start()
        self.addCleanup(executable.stop)

    def backend(self, **kwargs):
        return CodexStructuredBackend(audit_dir=self.audit, role='player', **kwargs)

    def test_native_schema_and_exact_messages_are_audited(self):
        req = request(max_output_tokens=8000, temperature=0.5, top_p=0.7)
        response = self.backend().generate(req)
        instance = FakeSession.instances[0]
        self.assertTrue(instance.closed)
        self.assertFalse(instance.workspace.exists())
        self.assertEqual([method for method, _ in instance.calls],
            ['initialize', 'initialized', 'account/read', 'thread/start', 'turn/start'])
        thread = dict(instance.calls)['thread/start']
        turn = dict(instance.calls)['turn/start']
        self.assertEqual(thread['baseInstructions'], req.messages[0].content)
        self.assertEqual(thread['developerInstructions'], '')
        self.assertEqual(turn['input'], [{'type': 'text', 'text': req.messages[1].content}])
        self.assertEqual(turn['outputSchema'], req.response_schema)
        self.assertFalse(thread['allowProviderModelFallback'])
        for key in ('environments', 'dynamicTools', 'selectedCapabilityRoots', 'runtimeWorkspaceRoots'):
            self.assertEqual(thread[key], [])
        for key, value in ISOLATION_CONFIG.items():
            self.assertEqual(thread['config'][key], value)
            self.assertIn(key + '=' + json.dumps(value), instance.command)
        self.assertEqual(response.model, 'gpt-5.5')
        self.assertEqual(response.provider, 'codex')
        self.assertEqual(response.usage.input_tokens, 23)
        self.assertEqual(response.usage.output_tokens, 11)
        self.assertEqual(response.metadata['reasoning_tokens'], 5)
        self.assertFalse(response.metadata['max_output_tokens_enforced'])
        self.assertFalse(response.metadata['temperature_enforced'])
        audit = Path(response.metadata['audit_dir'])
        self.assertEqual(json.loads((audit / 'response.json').read_text())['text'], '{}')
        self.assertEqual(json.loads((audit / 'request.json').read_text())['messages'],
            [{'role': 'system', 'content': req.messages[0].content},
             {'role': 'user', 'content': req.messages[1].content}])

    def test_each_call_gets_new_process_workspace_and_thread(self):
        backend = self.backend()
        first, second = backend.generate(request()), backend.generate(request())
        self.assertNotEqual(first.metadata['thread_id'], second.metadata['thread_id'])
        self.assertNotEqual(first.metadata['audit_dir'], second.metadata['audit_dir'])
        self.assertNotEqual(FakeSession.instances[0].workspace, FakeSession.instances[1].workspace)

    def test_supported_models_are_requested_and_audited_exactly(self):
        for model in ('gpt-5.5', 'gpt-5.6-sol', 'gpt-6-astra'):
            with self.subTest(model=model):
                FakeSession.resolved_model = model
                response = self.backend(model=model, reasoning_effort='high').generate(request())
                instance = FakeSession.instances[-1]
                calls = dict(instance.calls)
                self.assertEqual(calls['thread/start']['model'], model)
                self.assertFalse(calls['thread/start']['allowProviderModelFallback'])
                self.assertEqual(calls['turn/start']['model'], model)
                self.assertEqual(calls['turn/start']['effort'], 'high')
                self.assertEqual(response.model, model)
                self.assertEqual(response.metadata['requested_model'], model)
                self.assertEqual(response.metadata['returned_model'], model)
                audit = Path(response.metadata['audit_dir'])
                self.assertEqual(json.loads((audit / 'request.json').read_text())['model'], model)
                self.assertEqual(json.loads((audit / 'thread_start_receipt.json').read_text())['model'], model)
                self.assertTrue(instance.closed)
                self.assertFalse(instance.workspace.exists())

    def test_malformed_model_answer_is_preserved_without_repair(self):
        FakeSession.final_text = '{"partial":'
        self.assertEqual(self.backend().generate(request()).text, FakeSession.final_text)
        self.assertEqual(len(FakeSession.instances), 1)
        self.assertEqual(sum(method == 'turn/start' for method, _ in FakeSession.instances[0].calls), 1)

    def test_unavailable_token_counts_remain_unknown(self):
        FakeSession.token_usage = {}
        response = self.backend().generate(request())
        self.assertIsNone(response.usage.input_tokens)
        self.assertIsNone(response.usage.output_tokens)

    def test_wrong_model_is_rejected_before_turn(self):
        for model in ('gpt-5.5', 'gpt-5.6-sol', 'gpt-6-astra'):
            for resolved in ('gpt-5.5', 'gpt-5.6-sol', 'gpt-6-astra', 'gpt-5.6', None):
                if resolved == model:
                    continue
                with self.subTest(requested=model, resolved=resolved):
                    FakeSession.resolved_model = resolved
                    count = len(FakeSession.instances)
                    with self.assertRaisesRegex(RuntimeError, 'different model') as caught:
                        self.backend(model=model).generate(request())
                    self.assertIn(repr(model), str(caught.exception))
                    self.assertIn(repr(resolved), str(caught.exception))
                    self.assertEqual(len(FakeSession.instances), count + 1)
                    instance = FakeSession.instances[-1]
                    self.assertNotIn('turn/start', dict(instance.calls))
                    self.assertTrue(instance.closed)
                    failure = json.loads((instance.audit_dir / 'failure.json').read_text())
                    self.assertEqual(failure['error'], str(caught.exception))

    def test_api_key_auth_is_rejected(self):
        FakeSession.account_type = 'apiKey'
        with self.assertRaisesRegex(RuntimeError, 'ChatGPT login'):
            self.backend().generate(request())
        self.assertNotIn('thread/start', dict(FakeSession.instances[0].calls))

    def test_tools_and_memory_are_rejected(self):
        for item in ({'type': 'commandExecution', 'id': 'tool'},
                     {'type': 'agentMessage', 'id': 'message', 'text': '{}', 'memoryCitation': {}},
                     {'type': 'hookPrompt', 'id': 'hook'}):
            with self.subTest(item=item):
                FakeSession.extra_events = [{'method': 'item/started', 'params': {'item': item}}]
                with self.assertRaises(RuntimeError):
                    self.backend().generate(request())
                self.assertTrue(FakeSession.instances[-1].closed)

    def test_timeout_and_failed_turn_are_audited_without_retry(self):
        FakeSession.fail_with = TimeoutError('fixture timeout')
        with self.assertRaises(TimeoutError):
            self.backend().generate(request())
        self.assertEqual(len(FakeSession.instances), 1)
        self.assertTrue(FakeSession.instances[0].closed)
        failures = list(self.audit.glob('*/failure.json'))
        self.assertEqual(json.loads(failures[0].read_text())['error_type'], 'TimeoutError')
        FakeSession.fail_with = None
        FakeSession.turn_status = 'failed'
        with self.assertRaisesRegex(RuntimeError, 'did not complete: failed'):
            self.backend().generate(request())

    def test_wrong_thread_or_turn_event_is_rejected(self):
        for identity in ({'threadId': 'other'}, {'turnId': 'other'}):
            FakeSession.extra_events = [{'method': 'irrelevant', 'params': identity}]
            with self.assertRaisesRegex(RuntimeError, 'another (thread|turn)'):
                self.backend().generate(request())

    def test_unsupported_request_rejected_before_process_creation(self):
        for req in (request(seed=1), GenerationRequest(
            messages=(Message('user', 'user only'),), response_schema={'type': 'object'},
            config=GenerationConfig())):
            with self.assertRaises(ValueError):
                self.backend().generate(req)
        for model in ('gpt-5.6', 'gpt-6', 'gpt-5.6-sol-latest', '', 'GPT-6-ASTRA'):
            with self.subTest(model=model), self.assertRaisesRegex(ValueError, 'benchmark model'):
                self.backend(model=model)
        for model in ('gpt-5.5', 'gpt-5.6-sol', 'gpt-6-astra'):
            with self.subTest(model=model), self.assertRaisesRegex(ValueError, 'reasoning effort'):
                self.backend(model=model, reasoning_effort='none')
        self.assertEqual(FakeSession.instances, [])

    def test_fresh_thread_guard_rejects_missing_instruction_receipt(self):
        workspace = Path('/tmp/example')
        receipt = {'instructionSources': [], 'thread': {'ephemeral': True, 'turns': [],
            'cwd': str(workspace), 'forkedFromId': None, 'parentThreadId': None}}
        validate_fresh_thread(receipt, workspace)
        for value in (None, ['AGENTS.md']):
            receipt['instructionSources'] = value
            with self.assertRaises(RuntimeError):
                validate_fresh_thread(receipt, workspace)


class StdioTransportTests(unittest.TestCase):
    def test_real_subprocess_jsonl_handshake_and_notification_buffering(self):
        script = """
import json, sys
for line in sys.stdin:
    request = json.loads(line)
    if 'id' in request:
        print(json.dumps({'method': 'fixture/event', 'params': {}}), flush=True)
        print(json.dumps({'id': request['id'], 'result': {'ok': True}}), flush=True)
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session = _AppServerSession([sys.executable, '-u', '-c', script], path, path, 5)
            try:
                self.assertEqual(session.rpc('initialize', {}), {'ok': True})
                self.assertEqual(session.next_event()['method'], 'fixture/event')
            finally:
                session.close()
            events = [json.loads(line) for line in (path / 'events.jsonl').read_text().splitlines()]
            self.assertEqual([event['direction'] for event in events], ['send', 'receive', 'receive'])
            self.assertIsNotNone(session._process.poll())

    def test_silent_subprocess_times_out_and_is_terminated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session = _AppServerSession([sys.executable, '-c', 'import time; time.sleep(10)'], path, path, 0.1)
            try:
                with self.assertRaises(TimeoutError):
                    session.rpc('initialize', {})
            finally:
                session.close()
            self.assertIsNotNone(session._process.poll())

    def test_server_tool_request_is_refused(self):
        script = """
import json, sys
sys.stdin.readline()
print(json.dumps({'id': 10, 'method': 'item/tool/call', 'params': {}}), flush=True)
sys.stdin.readline()
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session = _AppServerSession([sys.executable, '-u', '-c', script], path, path, 5)
            try:
                with self.assertRaisesRegex(RuntimeError, 'client request or tool call'):
                    session.rpc('initialize', {})
            finally:
                session.close()
            events = [json.loads(line) for line in (path / 'events.jsonl').read_text().splitlines()]
            self.assertEqual(events[-1]['message']['error']['code'], -32601)


if __name__ == '__main__':
    unittest.main()
