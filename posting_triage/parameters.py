"""Settings kept in AWS Systems Manager Parameter Store, for the deployed API.

On AWS the Anthropic key, the API token, and the profile live as SecureString parameters
under one prefix (e.g. /posting-triage/api-token), never in the image or the function's
settings. The API reads them once at startup. Locally nothing here runs: .env and
profile.yaml work as before.
"""

NAMES = ("anthropic-api-key", "api-token", "profile")


def read_parameters(prefix, client=None):
    """{name: value} for every name in NAMES under `prefix`, decrypted, in one request.
    RuntimeError names any that are missing, so the app fails closed. `client` is
    swappable for tests; by default it's boto3's SSM client for the function's region."""
    if client is None:
        import boto3  # only the deployed API needs it: the `aws` extra

        client = boto3.client("ssm")
    full = {f"{prefix.rstrip('/')}/{name}": name for name in NAMES}
    reply = client.get_parameters(Names=list(full), WithDecryption=True)
    missing = reply.get("InvalidParameters") or []
    if missing:
        raise RuntimeError(f"missing from Parameter Store: {', '.join(sorted(missing))}")
    return {full[p["Name"]]: p["Value"] for p in reply["Parameters"]}
