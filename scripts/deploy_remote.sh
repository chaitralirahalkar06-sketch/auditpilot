#!/usr/bin/env bash
set -Eeuo pipefail

: "${AWS_REGION:?AWS_REGION must be set}"
: "${BUILD_NUMBER:?BUILD_NUMBER must be set}"

if [[ ! "$BUILD_NUMBER" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "BUILD_NUMBER contains unsupported characters" >&2
    exit 2
fi

mapfile -t APP_INSTANCE_IDS < <(
    aws ec2 describe-instances \
        --region "$AWS_REGION" \
        --filters \
            Name=tag:Name,Values=auditpilot_app \
            Name=instance-state-name,Values=running \
        --query 'Reservations[].Instances[].InstanceId' \
        --output text |
        tr '\t' '\n' |
        sed '/^$/d'
)

if [[ "${#APP_INSTANCE_IDS[@]}" -ne 1 || "${APP_INSTANCE_IDS[0]}" == "None" ]]; then
    echo "Expected exactly one running EC2 instance tagged Name=auditpilot_app" >&2
    exit 1
fi

INSTANCE_ID="${APP_INSTANCE_IDS[0]}"
COMMAND_ID="$(
    aws ssm send-command \
        --region "$AWS_REGION" \
        --instance-ids "$INSTANCE_ID" \
        --document-name AWS-RunShellScript \
        --parameters "commands=/opt/auditpilot/deploy.sh $BUILD_NUMBER" \
        --query 'Command.CommandId' \
        --output text
)"

for _ in $(seq 1 60); do
    STATUS="$(
        aws ssm get-command-invocation \
            --region "$AWS_REGION" \
            --command-id "$COMMAND_ID" \
            --instance-id "$INSTANCE_ID" \
            --query 'Status' \
            --output text 2>/dev/null || true
    )"
    echo "SSM deployment status: ${STATUS:-Pending}"

    case "$STATUS" in
        Success)
            exit 0
            ;;
        Failed|Cancelled|TimedOut|Cancelling)
            break
            ;;
    esac
    sleep 5
done

aws ssm get-command-invocation \
    --region "$AWS_REGION" \
    --command-id "$COMMAND_ID" \
    --instance-id "$INSTANCE_ID" \
    --query '{Status:Status,StandardError:StandardErrorContent,StandardOutput:StandardOutputContent}' \
    --output json >&2 || true
exit 1
