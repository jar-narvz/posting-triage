import pytest

from posting_triage.parameters import read_parameters


class FakeSSM:
    """Stand-in for boto3's SSM client: get_parameters over a dict, recording each call.
    Like AWS, the reply leaves InvalidParameters out when nothing is missing."""

    def __init__(self, values):
        self.values, self.calls = values, []

    def get_parameters(self, Names, WithDecryption):
        self.calls.append((Names, WithDecryption))
        reply = {"Parameters": [{"Name": n, "Value": self.values[n]} for n in Names if n in self.values]}
        missing = [n for n in Names if n not in self.values]
        if missing:
            reply["InvalidParameters"] = missing
        return reply


STORED = {
    "/posting-triage/anthropic-api-key": "sk-test",
    "/posting-triage/api-token": "tok",
    "/posting-triage/profile": "degree: bachelors\n",
}


@pytest.mark.parametrize("prefix", ["/posting-triage", "/posting-triage/"])
def test_reads_all_three_decrypted_in_one_request(prefix):
    ssm = FakeSSM(STORED)
    assert read_parameters(prefix, ssm) == {
        "anthropic-api-key": "sk-test", "api-token": "tok", "profile": "degree: bachelors\n",
    }
    assert ssm.calls == [(list(STORED), True)]


def test_a_missing_parameter_stops_startup_and_is_named():
    values = {k: v for k, v in STORED.items() if not k.endswith("/profile")}
    with pytest.raises(RuntimeError, match="/posting-triage/profile"):
        read_parameters("/posting-triage", FakeSSM(values))
