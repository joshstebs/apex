import json
from unittest.mock import MagicMock, patch

from app import build_conversation_history
from voice_engine import VoiceEngine


def run():
    engine = VoiceEngine(hf_token="offline-test-token")
    tools = [{"name": "save_message", "parameters": {"caller_name": "string"}}]
    upstream = MagicMock(status=200)
    cases = [
        ('{"tool":"save_message","args":{"caller_name":"Sam","extra":"ignore"}}',
         {"tool": "save_message", "parameters": {"caller_name": "Sam"}}),
        ('{"tool":"save_message","parameters":{"caller_name":"Sam"}}',
         {"tool": "save_message", "parameters": {"caller_name": "Sam"}}),
        ('{"tool":"book_appointment","parameters":{"caller_name":"Sam"}}', None),
        ('{"tool":"save_message","parameters":[]}', None),
        ('{"tool":"save_message", broken}', None),
    ]
    for block, expected in cases:
        upstream.read.return_value = json.dumps({
            "choices": [{"message": {"content": "Thanks!\n```json\n" + block + "\n```"}}],
        }).encode()
        with patch("voice_engine.urllib.request.urlopen") as mock_open:
            mock_open.return_value.__enter__.return_value = upstream
            result = engine.generate_chat_response("Receptionist", [], "Hello", tools=tools)
        assert result["text"] == "Thanks!", result
        assert result["tool_call"] == expected, result
        request = json.loads(mock_open.call_args.args[0].data)
        assert '"caller_name": "string"' in request["messages"][0]["content"]

    assert build_conversation_history([
        {"speaker": "assistant", "message": "How may I help?"},
        {"speaker": "tool", "message": "Internal message capture"},
        {"speaker": "human", "message": "I need a callback."},
    ]) == [
        {"role": "assistant", "content": "How may I help?"},
        {"role": "user", "content": "I need a callback."},
    ]

    long_history = [{"speaker": "human", "message": str(turn)} for turn in range(20)]
    recent = build_conversation_history(long_history)
    assert [entry["content"] for entry in recent] == [str(turn) for turn in range(4, 20)]


if __name__ == "__main__":
    run()
    print("PASS: message capture and conversation history")
