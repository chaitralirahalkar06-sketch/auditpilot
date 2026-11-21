#!/usr/bin/env bash
set -Eeuo pipefail

dnf install -y docker awscli curl
systemctl enable --now docker

TOKEN="$(curl -fsS -X PUT \
    -H 'X-aws-ec2-metadata-token-ttl-seconds: 21600' \
    http://169.254.169.254/latest/api/token)"
REGION="$(curl -fsS \
    -H "X-aws-ec2-metadata-token: $TOKEN" \
    http://169.254.169.254/latest/meta-data/placement/region)"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"

install -d -m 0750 /opt/auditpilot /etc/auditpilot
install -d -o 10001 -g 10001 -m 0750 \
    /var/lib/auditpilot/audit /var/lib/auditpilot/docs
printf '%s\n' "$REGION" > /etc/auditpilot/region
printf '%s\n' "$ACCOUNT_ID" > /etc/auditpilot/account_id
chmod 0640 /etc/auditpilot/region /etc/auditpilot/account_id

cat > /opt/auditpilot/deploy.sh <<'DEPLOY'
#!/usr/bin/env bash
set -Eeuo pipefail
set +x

REGION="$(</etc/auditpilot/region)"
ACCOUNT_ID="$(</etc/auditpilot/account_id)"
TAG="${1:-latest}"
if [[ ! "$TAG" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "Image tag contains unsupported characters" >&2
    exit 2
fi

REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
IMAGE="${REGISTRY}/auditpilot:${TAG}"

aws ecr get-login-password --region "$REGION" |
    docker login --username AWS --password-stdin "$REGISTRY"
docker pull "$IMAGE"

umask 077
ENV_FILE="$(mktemp /run/auditpilot-env.XXXXXX)"
KEY=""
OLD_CONTAINER=0
NEW_CONTAINER=0
DEPLOY_OK=0

restore_on_failure() {
    local status=$?
    trap - EXIT
    if (( DEPLOY_OK == 0 )); then
        if (( NEW_CONTAINER == 1 )); then
            docker rm -f auditpilot >/dev/null 2>&1 || true
        fi
        if (( OLD_CONTAINER == 1 )); then
            docker rename auditpilot_previous auditpilot
            docker start auditpilot >/dev/null
            echo "Previous container restored after failed deployment" >&2
        fi
    fi
    rm -f "$ENV_FILE"
    unset KEY
    exit "$status"
}
trap restore_on_failure EXIT

KEY="$(aws secretsmanager get-secret-value \
    --region "$REGION" \
    --secret-id auditpilot/google_api_key \
    --query SecretString \
    --output text)"
if [[ -z "$KEY" || "$KEY" == "None" || "$KEY" == *$'\n'* ]]; then
    echo "The Gemini API key secret is empty or malformed" >&2
    exit 1
fi
printf 'GOOGLE_API_KEY=%s\nGOOGLE_GENAI_USE_VERTEXAI=FALSE\nAUDIT_TRAIL_PATH=/app/audit_storage/audit_trail.jsonl\n' \
    "$KEY" > "$ENV_FILE"

if docker inspect auditpilot >/dev/null 2>&1; then
    docker stop auditpilot >/dev/null
    docker rename auditpilot auditpilot_previous
    OLD_CONTAINER=1
fi

docker run -d \
    --name auditpilot \
    --restart unless-stopped \
    --publish 80:8080 \
    --env-file "$ENV_FILE" \
    --mount type=bind,source=/var/lib/auditpilot/audit,target=/app/audit_storage \
    --mount type=bind,source=/var/lib/auditpilot/docs,target=/app/docs \
    --log-driver awslogs \
    --log-opt "awslogs-region=${REGION}" \
    --log-opt awslogs-group=auditpilot \
    --log-opt awslogs-create-group=true \
    "$IMAGE"
NEW_CONTAINER=1

for _ in $(seq 1 20); do
    if curl -fsS --max-time 2 http://127.0.0.1/health >/dev/null; then
        if (( OLD_CONTAINER == 1 )); then
            docker rm -f auditpilot_previous >/dev/null
            OLD_CONTAINER=0
        fi
        DEPLOY_OK=1
        echo "Deployment of ${IMAGE} passed the health check"
        exit 0
    fi
    sleep 3
done

echo "Health check failed for ${IMAGE}" >&2
exit 1
DEPLOY

chmod 0750 /opt/auditpilot/deploy.sh
