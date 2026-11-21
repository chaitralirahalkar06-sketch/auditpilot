#!/usr/bin/env bash
set -Eeuo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl fontconfig openjdk-21-jre docker.io unzip

install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://pkg.jenkins.io/debian-stable/jenkins.io-2026.key \
    -o /etc/apt/keyrings/jenkins-keyring.asc
echo "deb [signed-by=/etc/apt/keyrings/jenkins-keyring.asc] https://pkg.jenkins.io/debian-stable binary/" \
    > /etc/apt/sources.list.d/jenkins.list

apt-get update
apt-get install -y jenkins

curl -fsSL https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip \
    -o /tmp/awscli.zip
unzip -q /tmp/awscli.zip -d /tmp
/tmp/aws/install
rm -rf /tmp/aws /tmp/awscli.zip

usermod -aG docker jenkins
systemctl enable --now docker
systemctl enable --now jenkins
