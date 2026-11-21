pipeline {
    agent any

    options {
        timestamps()
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    environment {
        AWS_REGION = 'ap-south-1'
        ECR_REPOSITORY = 'auditpilot'
    }

    stages {
        stage('Checkout') {
            steps {
                sh 'git log -1 --oneline'
            }
        }

        stage('Resolve image') {
            steps {
                script {
                    env.AWS_ACCOUNT_ID = sh(
                        script: 'aws sts get-caller-identity --query Account --output text',
                        returnStdout: true
                    ).trim()
                    env.ECR_REGISTRY = "${env.AWS_ACCOUNT_ID}.dkr.ecr.${env.AWS_REGION}.amazonaws.com"
                    env.IMAGE = "${env.ECR_REGISTRY}/${env.ECR_REPOSITORY}"
                }
            }
        }

        stage('Build test image') {
            steps {
                sh 'docker build --pull --target test -t auditpilot-test:${BUILD_NUMBER} .'
            }
        }

        stage('Run tests') {
            steps {
                sh 'docker run --rm auditpilot-test:${BUILD_NUMBER}'
            }
        }

        stage('Build runtime image') {
            when {
                branch 'main'
            }
            steps {
                sh 'docker build --pull --target runtime -t "$IMAGE:$BUILD_NUMBER" -t "$IMAGE:latest" .'
            }
        }

        stage('Push to ECR') {
            when {
                branch 'main'
            }
            steps {
                sh '''
                    aws ecr get-login-password --region "$AWS_REGION" |
                      docker login --username AWS --password-stdin "$ECR_REGISTRY"
                    docker push "$IMAGE:$BUILD_NUMBER"
                    docker push "$IMAGE:latest"
                '''
            }
        }

        stage('Deploy') {
            when {
                branch 'main'
            }
            steps {
                sh 'bash scripts/deploy_remote.sh'
            }
        }
    }

    post {
        always {
            sh 'docker image prune -f'
        }
    }
}
