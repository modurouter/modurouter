import os
import subprocess

from dotenv import dotenv_values
from vps import ROOT


def main():
    values = dotenv_values(ROOT / ".env")
    token = values["VERCEL_DEPLOY_KEY"]
    web_origin = values["PRODUCTION_WEB_ORIGIN"].rstrip("/")
    api_origin = (values.get("PRODUCTION_API_ORIGIN") or web_origin).rstrip("/")
    if not api_origin.startswith("https://"):
        raise ValueError("Production API origin must use HTTPS")
    command = ["npx", "--yes", "vercel@latest", "deploy", "--prod", "--yes", "--name", "modurouter",
               "--build-env", "API_UPSTREAM_URL=https://" + values["API_DOMAIN"],
               "--build-env", "NEXT_PUBLIC_API_ORIGIN=" + (api_origin if api_origin != web_origin else "")]
    process = subprocess.run(command, cwd=ROOT / "client", env={**os.environ, "CI": "1", "VERCEL_TOKEN": token},
                             text=True, capture_output=True)
    output = (process.stdout + process.stderr).replace(token, "[REDACTED]")
    log = ROOT / "server/.runtime/vercel-deploy.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(output)
    print(output[-6000:])
    raise SystemExit(process.returncode)


if __name__ == "__main__":
    main()
