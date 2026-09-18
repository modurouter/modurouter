"""SSH operations using only root .env; redact credentials from command output.

Usage: uv run python scripts/vps.py inspect
       uv run python scripts/vps.py run path/to/reviewed-script.sh
"""
import argparse
import sys
from pathlib import Path

import paramiko
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]


def connect():
    values = dotenv_values(ROOT / ".env")
    client = paramiko.SSHClient()
    known = values.get("VPS_KNOWN_HOSTS", "")
    if not known.strip():
        raise RuntimeError("Pin the VPS host key in root .env as VPS_KNOWN_HOSTS before connecting")
    for line in known.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        entry = paramiko.hostkeys.HostKeyEntry.from_line(line)
        if entry is None or entry.key is None:
            raise RuntimeError("Invalid VPS_KNOWN_HOSTS entry in root .env")
        for hostname in entry.hostnames:
            client.get_host_keys().add(hostname, entry.key.get_name(), entry.key)
    client.connect(values["CONTABO_VPS_IP_ADDRESS"],
        username=values["CONTABO_VPS_DEFAULT_USER"], password=values.get("CONTABO_VPS_PASSWORD"),
        key_filename=values.get("CONTABO_VPS_SSH_KEY_PATH"), look_for_keys=False, allow_agent=False, timeout=20)
    return client, values


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["inspect", "run"])
    parser.add_argument("script", nargs="?")
    args = parser.parse_args()
    client, values = connect()
    try:
        if args.action == "inspect":
            command = "id; cat /etc/os-release; free -m; df -h /; systemctl list-units --type=service --state=running --no-pager; docker ps -a --format '{{.Names}} {{.Image}} {{.Status}}' 2>/dev/null; ls -la /opt /srv /var/www /root; ss -lntp"
            stdin, stdout, stderr = client.exec_command(command)
        else:
            if not args.script:
                parser.error("run requires a reviewed script path")
            stdin, stdout, stderr = client.exec_command("bash -se", timeout=1800)
            stdin.write(Path(args.script).read_text())
            stdin.channel.shutdown_write()
        # Drain one combined channel so a full stderr buffer cannot block stdout.
        stdout.channel.set_combine_stderr(True)
        output = stdout.read().decode(errors="replace")
        for key, value in values.items():
            if value and any(word in key for word in ("PASSWORD", "SECRET", "KEY", "IP_ADDRESS")):
                output = output.replace(value, "[REDACTED]")
        print(output)
        return stdout.channel.recv_exit_status()
    finally:
        client.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except paramiko.AuthenticationException:
        print("SSH authentication rejected. Check the VPS key or password configuration.")
        sys.exit(1)
