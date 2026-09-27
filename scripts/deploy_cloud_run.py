from __future__ import annotations

import getpass
import secrets
import subprocess
import sys


def run(command: list[str], *, input_text: str | None = None) -> None:
    result = subprocess.run(command, input=input_text, text=True, check=False)
    if result.returncode:
        raise SystemExit(result.returncode)


def main() -> None:
    try:
        subprocess.run(["gcloud", "--version"], check=True, stdout=subprocess.DEVNULL)
    except (FileNotFoundError, subprocess.CalledProcessError):
        raise SystemExit("Install and authenticate the Google Cloud CLI first.")

    project = input("Google Cloud project ID: ").strip()
    region = input("Cloud Run region [us-central1]: ").strip() or "us-central1"
    if not project:
        raise SystemExit("A Google Cloud project ID is required.")
    password = getpass.getpass("Set a private demo password (12+ characters): ")
    if len(password) < 12:
        raise SystemExit("Choose a password with at least 12 characters.")
    confirmation = getpass.getpass("Confirm demo password: ")
    if not secrets.compare_digest(password, confirmation):
        raise SystemExit("Passwords did not match.")

    service = "trustmesh-ai"
    secret = "trustmesh-demo-password"
    run(["gcloud", "config", "set", "project", project])
    run(["gcloud", "services", "enable", "run.googleapis.com", "cloudbuild.googleapis.com",
         "artifactregistry.googleapis.com", "secretmanager.googleapis.com", "--project", project])
    secret_exists = subprocess.run(
        ["gcloud", "secrets", "describe", secret, "--project", project],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    ).returncode == 0
    if secret_exists:
        run(["gcloud", "secrets", "versions", "add", secret, "--project", project, "--data-file=-"],
            input_text=password)
    else:
        run(["gcloud", "secrets", "create", secret, "--project", project, "--replication-policy=automatic"])
        run(["gcloud", "secrets", "versions", "add", secret, "--project", project, "--data-file=-"],
            input_text=password)

    account = "trustmesh-runtime"
    service_account = f"{account}@{project}.iam.gserviceaccount.com"
    account_exists = subprocess.run(
        ["gcloud", "iam", "service-accounts", "describe", service_account, "--project", project],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    ).returncode == 0
    if not account_exists:
        run([
            "gcloud", "iam", "service-accounts", "create", account,
            "--project", project, "--display-name=TrustMesh Cloud Run runtime",
        ])
    run([
        "gcloud", "projects", "add-iam-policy-binding", project,
        f"--member=serviceAccount:{service_account}",
        "--role=roles/secretmanager.secretAccessor",
    ])
    deploy = [
        "gcloud", "run", "deploy", service,
        "--source", ".", "--project", project, "--region", region,
        "--allow-unauthenticated", "--port", "8080", "--memory", "1Gi", "--cpu", "1",
        "--max", "1", "--min", "0", "--timeout", "300",
        "--service-account", service_account,
        "--set-env-vars",
        "APP_ENV=development,TRUSTMESH_PUBLIC_MODE=true,DATABASE_PATH=/tmp/trustmesh/trustmesh.sqlite3,MAX_UPLOAD_BYTES=10485760,MAX_UPLOAD_MB=10",
        "--set-secrets", f"TRUSTMESH_DEMO_PASSWORD={secret}:latest",
    ]
    run(deploy)
    print("\nDeployment finished. Open the service URL printed by gcloud.")
    print("Container storage is ephemeral: user uploads, feedback, and investigations may be lost on restart.")
    print("Secret Manager and any usage beyond Cloud Run's free tier may incur charges.")


if __name__ == "__main__":
    main()
