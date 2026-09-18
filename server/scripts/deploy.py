"""Generate a minimal remote environment from root .env and deploy the API stack."""
import io
import secrets
import tarfile

from dotenv import dotenv_values, set_key
from vps import ROOT, connect


def main():
    env_path = ROOT / ".env"
    values = dotenv_values(env_path)
    if not values.get("API_DOMAIN"):
        raise ValueError("Set API_DOMAIN in root .env to the VPS HTTPS hostname")
    generated = {"DB_ROOT_PASSWORD": secrets.token_hex(32),
                 "PRODUCTION_API_ORIGIN": values["PRODUCTION_WEB_ORIGIN"]}
    for key, value in generated.items():
        if not values.get(key):
            set_key(env_path, key, value)
    env_path.chmod(0o600)
    values = dotenv_values(env_path)
    selected = {k: v for k, v in values.items() if k in {
        "PRODUCTION_WEB_ORIGIN", "PRODUCTION_API_ORIGIN", "API_DOMAIN", "DB_PASSWORD", "DB_ROOT_PASSWORD", "SESSION_SECRET",
        "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "OPENROUTER_API_KEY", "MODEL_ALLOWLIST", "ADMIN_USERNAME", "ADMIN_PASSWORD",
        "ZENMUX_API_KEY", "OPENAI_API_KEY", "UPSTAGE_API_KEY",
        "TOOL_MODEL_ALLOWLIST", "INPUT_PRICE_CAP_USD_PER_M", "OUTPUT_PRICE_CAP_USD_PER_M",
        "USER_DAILY_BUDGET_USD", "USER_DAILY_REQUEST_LIMIT", "GUEST_DAILY_REQUEST_LIMIT",
        "MAX_INPUT_TOKENS", "MAX_OUTPUT_TOKENS"}}
    payload = "".join(f"{key}='{value}'\n" for key, value in selected.items())
    if any("'" in value or "\n" in value for value in selected.values()):
        raise ValueError("Environment values require safe dotenv serialization")
    server = ROOT / "server"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name in ("backend", "pyproject.toml", "uv.lock", "Dockerfile", ".dockerignore", "alembic.ini", "compose.yaml", "infra"):
            archive.add(server / name, arcname=name,
                        filter=lambda member: None if "__pycache__" in member.name else member)
    client, _ = connect()
    try:
        sftp = client.open_sftp()
        with sftp.open("/opt/modurouter/source.tar.gz", "wb") as target:
            target.write(buffer.getvalue())
        with sftp.open("/opt/modurouter/.env", "w") as target:
            target.write(payload)
        sftp.chmod("/opt/modurouter/.env", 0o600)
        sftp.close()
        command = "cd /opt/modurouter && tar -xzf source.tar.gz && rm source.tar.gz && rm -f backend/migrations/versions/0006_routing_choice.py backend/migrations/versions/0007_runtime_settings.py && (docker image tag modurouter-api:local modurouter-api:previous 2>/dev/null || true) && docker compose build api && docker compose up -d mariadb && docker compose run --rm api alembic upgrade head && docker compose up -d && docker compose exec -T proxy caddy reload --config /etc/caddy/Caddyfile && docker compose ps"
        _, stdout, stderr = client.exec_command(command, timeout=1800)
        # Read both channels together so Docker build progress cannot fill stderr's window.
        channel = stdout.channel
        channel.set_combine_stderr(True)
        result = stdout.read().decode(errors="replace")
        for key, value in values.items():
            if value and any(w in key for w in ("PASSWORD", "SECRET", "KEY", "IP_ADDRESS", "API_DOMAIN")):
                result = result.replace(value, "[REDACTED]")
        log = ROOT / "server/.runtime/deploy.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(result)
        print(result[-5000:])
        if channel.recv_exit_status():
            raise RuntimeError("Deployment failed; see server/.runtime/deploy.log")
    finally:
        client.close()


if __name__ == "__main__":
    main()
