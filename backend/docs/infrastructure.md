# Pillioo Infrastructure & Deployment Documentation

This document contains the backend infrastructure architecture and network configuration for the deployed system. 
To ensure security and smooth testing, please strictly adhere to the guidelines below.

---

## 1. EC2 Instance Information
- **Server Name:** `pillioo-server` (t3.micro / Ubuntu)
- **Public IP:** `Dynamic IP` (*Note: Elastic IP is not attached. The IP address changes upon instance reboot. Please check the output of `deploy.sh` or the team channel for the current IP.*)
- **SSH User:** `ubuntu`
- **Access Key:** `pillioo-key.pem`

---

## 2. Security Group Inbound Rules
Currently, ports are controlled using a whitelist policy to enhance security. If your IP address changes and you cannot connect, please contact Ji-hee.

| Protocol / Port | Purpose | Allowed Source | Remarks |
| :--- | :--- | :--- | :--- |
| **TCP / 22 (SSH)** | Remote Server Access & Management | `Developer's Public IP/32` | 0.0.0.0/0 Blocked (Restricted Access) |
| **TCP / 8000** | FastAPI Swagger UI & API | `Developer's Public IP/32` | Temporarily allowed for development |

---

## 3. Docker Compose Container Configuration (`--profile rag`)
The backend architecture is managed within an isolated network via Docker Compose.

- **FastAPI (`pillioo_fastapi`):** Port `8000` (Exposed externally)
- **PostgreSQL (`pillioo_postgres`):** Port `5432` (Internal network only)
- **Milvus (`pillioo_milvus`):** Port `19530` (Internal network only, Vector DB)
- **Minio / Etcd:** RAG Pipeline Infrastructure Components

---

## 4. Environment Variables (`.env`) Structural Rules
When configuring the `.env` file, the database credentials must be identical across fields to prevent authentication errors (`FATAL: password authentication`).

```env
DB_HOST=postgres
DB_PORT=5432
DB_NAME=pillioo_db
DB_USER=user
DB_PASSWORD=password

# IMPORTANT: The password in DATABASE_URL must perfectly match the DB_PASSWORD above!
DATABASE_URL=postgresql://user:password@postgres:5432/pillioo_db

# RAG & External Integrations
OPENAI_API_KEY=sk-proj-...
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIM=1536
EMBEDDING_BATCH_SIZE=64
MILVUS_URI=http://localhost:19530
MILVUS_COLLECTION=evidence_chunks