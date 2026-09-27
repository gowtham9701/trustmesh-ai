# Personal deployment guide

## Recommended layout

Deploy one container that runs Streamlit as the public ingress and FastAPI on
loopback only. This avoids exposing an unauthenticated second API, works with
Streamlit's WebSocket session, and fits Cloud Run and Render better than
deploying the UI to a static host.

The root [Dockerfile](Dockerfile) and
[`backend/app/combined_server.py`](backend/app/combined_server.py) implement
this layout. The API listens only at `127.0.0.1:8000`; the platform routes
public traffic to the Streamlit process on `$PORT`. Public mode requires the
owner-configured `TRUSTMESH_DEMO_PASSWORD`, at least 12 characters long. This
is a shared-password demo gate, not full user authentication or brute-force
protection. Use only synthetic/non-sensitive evidence; use an identity-aware
access proxy and managed storage before handling private or production data.

## Hosting comparison

| Platform | Fit | Personal/free-tier caveat |
| --- | --- | --- |
| **Google Cloud Run** | Recommended container platform; scale-to-zero, configurable max instances, one public Streamlit ingress | Free tier is quota-based, not a guarantee of a zero bill. Requires billing-enabled Google Cloud project. Container filesystem is ephemeral; this deployment stores SQLite under `/tmp`, so user data can disappear after an instance stops/restarts. Secret Manager and builds may have separate charges. |
| **Render Web Service** | Easiest Git-connected Docker deploy; `render.yaml` is a Blueprint | Free services sleep after inactivity and lose local files on restart/redeploy. Persistent disks are paid-only. Good for a temporary demo; do not use it for durable uploaded evidence on Free. |
| **Vercel** | Can host frontend/framework functions or a separately adapted stateless API | Not the target for this combined Streamlit/WebSocket + SQLite container. Would require replacing the UI and moving state to external managed services. |
| **Netlify** | Static websites and supported function patterns | Not suitable for running the Streamlit server plus private FastAPI process as one persistent app. Would require a frontend/API redesign. |

This project purposely does not deploy an LLM on the free web instance. The
default is deterministic local retrieval. Model weights can be large and may
exceed free memory, startup, storage, and egress budgets.

## Cloud Run (recommended demo)

Prerequisites: a Google Cloud account, billing-enabled project, `gcloud`
installed and authenticated (`gcloud auth login`), and permission to enable APIs,
create a service account/secret, and deploy Cloud Run.

From the project root:

```bash
python3 scripts/deploy_cloud_run.py
```

The script asks for a project, region and private demo password. It places the
password in Secret Manager (not in the container image or source), grants the
runtime service account access to that secret, deploys the root Dockerfile with
1 vCPU, 1 GiB memory, scale-to-zero, and a one-instance cap, then prints the
Cloud Run URL.

Review the script before running it: the deploy command enables Google APIs,
creates/updates a Secret Manager secret, creates a runtime service account,
changes IAM policy, and creates/updates a publicly reachable Cloud Run service.
The web app itself then prompts for the demo password. Use Cloud Run's maximum
instance cap and Google Cloud budgets/alerts; neither prevents all possible
charges. Check current [Cloud Run pricing](https://cloud.google.com/run/pricing)
for your region and account before deployment. Cloud Build, IAM changes, API
enablement, and deploy permissions must be available to the authenticated
account.

### Cloud Run storage and privacy

The deploy script stores SQLite under `/tmp`, not in the image. Cloud Run
container filesystems are instance-local and temporary. Documents, investigation
history, feedback and approvals can be lost when an instance stops, is replaced,
or scales to another instance. The app caps instances at one, but this is not
durability. Use only synthetic/non-sensitive evidence on this profile.

For persistent personal use, use a paid persistent-disk host such as a single
Render Web Service with its disk mounted at `/var/data` and set:

```text
DATABASE_PATH=/var/data/trustmesh.sqlite3
```

Keep one application instance for SQLite and back up the disk. For scalable,
durable production, migrate the store to a managed database and use object
storage/KMS; that architecture is not included in the zero-cost profile.

## Render Blueprint

1. Push this project to a Git provider and connect the repository in Render.
2. Create a Blueprint using [`render.yaml`](render.yaml).
3. Set `TRUSTMESH_DEMO_PASSWORD` as a secret environment variable in Render.
4. Deploy the Free web service for a non-sensitive demo.

Free Render instances sleep after 15 minutes idle and have ephemeral filesystems;
the demo password remains configured but SQLite user data may reset. For
persistence, upgrade the web service and attach a persistent disk mounted at
`/var/data`, then change `DATABASE_PATH` to `/var/data/trustmesh.sqlite3`.

See Render's [free instance limitations](https://render.com/docs/free) and
[persistent disk documentation](https://render.com/docs/disks).

## Git publishing

This directory may be separate from a Git checkout. First initialize the
project as a repository or clone your empty remote into a location and copy
these project files. Ensure `.env`, SQLite/WAL files, model/vector caches, and
other private state remain ignored. Do not include real incident records,
tokens, encryption keys, or demo passwords in Git.

```bash
cd "/Users/gautam/personal projects/opspilot"
git init
git add .
git status --short
git commit -m "Build TrustMesh personal deployment"
git remote add origin <your-repository-url>
git push -u origin HEAD
```

Set `TRUSTMESH_DEMO_PASSWORD` in the hosting provider, not in the repository.

## Official references

- [Cloud Run pricing/free tier](https://cloud.google.com/run/pricing)
- [Cloud Run container contract and `$PORT`](https://cloud.google.com/run/docs/container-contract)
- [Cloud Run memory configuration](https://cloud.google.com/run/docs/configuring/services/memory-limits)
- [Render free instances](https://render.com/docs/free)
- [Render persistent disks](https://render.com/docs/disks)
- [Vercel function limits](https://vercel.com/docs/functions/limitations)
