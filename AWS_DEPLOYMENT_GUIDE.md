# GlassEntials HRMS - AWS Deployment Guide

> Complete step-by-step guide for deploying the GlassEntials Premium HRMS application on Amazon Web Services (AWS)

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Prerequisites](#prerequisites)
3. [AWS Services Setup](#aws-services-setup)
4. [Database Configuration](#database-configuration)
5. [Application Deployment](#application-deployment)
6. [Load Balancing & SSL](#load-balancing--ssl)
7. [Monitoring & Logging](#monitoring--logging)
8. [Scaling & Performance](#scaling--performance)
9. [Backup & Disaster Recovery](#backup--disaster-recovery)
10. [Security Best Practices](#security-best-practices)
11. [Troubleshooting](#troubleshooting)
12. [Cost Optimization](#cost-optimization)

---

## Architecture Overview

### Recommended AWS Architecture for GlassEntials

```
┌─────────────────────────────────────────────────┐
│         CloudFront (CDN)                         │
│  - Static asset distribution                     │
│  - DDoS protection                               │
└──────────────────┬──────────────────────────────┘
                   │
        ┌──────────▼──────────┐
        │  Application Load   │
        │   Balancer (ALB)    │
        │  - HTTPS termination│
        └──────────┬──────────┘
                   │
    ┌──────────────┼──────────────┐
    │              │              │
 ┌──▼──┐       ┌──▼──┐       ┌──▼──┐
 │ EC2 │       │ EC2 │       │ EC2 │  (Auto Scaling Group)
 │ App │       │ App │       │ App │  - Django instances
 │ #1  │       │ #2  │       │ #3  │  - Gunicorn/uWSGI
 └─────┘       └─────┘       └─────┘
    │              │              │
    └──────────────┼──────────────┘
                   │
        ┌──────────▼──────────┐
        │   RDS PostgreSQL    │
        │  - Multi-AZ setup   │
        │  - Automated backups│
        └─────────────────────┘
```

---

## Prerequisites

### Required AWS Account Setup

- ✅ AWS Account with billing enabled
- ✅ IAM user with appropriate permissions (EC2, RDS, S3, CloudFront, ALB)
- ✅ AWS CLI installed and configured (`pip install awscli`)
- ✅ SSH key pair created in AWS
- ✅ Domain name (optional but recommended)

### Local Requirements

```bash
# Python & Dependencies
python 3.11+
pip
virtualenv

# Django Project Dependencies
Django 5.x
PostgreSQL client tools
Git

# AWS Tools
aws-cli >= 2.0
```

### Application Baseline

Before deployment, ensure your Django app is production-ready:

```bash
# Verify settings
python manage.py check

# Collect static files locally
python manage.py collectstatic --dry-run

# Run tests
pytest  # or: python manage.py test
```

---

## AWS Services Setup

### 1. VPC Configuration

**Create a Virtual Private Cloud (VPC)** for isolated network infrastructure:

```bash
# Create VPC with CIDR block 10.0.0.0/16
aws ec2 create-vpc --cidr-block 10.0.0.0/16 --tag-specifications 'ResourceType=vpc,Tags=[{Key=Name,Value=glassentials-vpc}]'

# Note the VPC ID from response
export VPC_ID="vpc-xxxxx"
```

**Create Subnets** (2 public + 2 private across 2 AZs):

```bash
# Public Subnets (for ALB)
aws ec2 create-subnet --vpc-id $VPC_ID --cidr-block 10.0.1.0/24 --availability-zone us-east-1a --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=public-subnet-1a}]'

aws ec2 create-subnet --vpc-id $VPC_ID --cidr-block 10.0.2.0/24 --availability-zone us-east-1b --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=public-subnet-1b}]'

# Private Subnets (for EC2 & RDS)
aws ec2 create-subnet --vpc-id $VPC_ID --cidr-block 10.0.11.0/24 --availability-zone us-east-1a --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=private-subnet-1a}]'

aws ec2 create-subnet --vpc-id $VPC_ID --cidr-block 10.0.12.0/24 --availability-zone us-east-1b --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=private-subnet-1b}]'
```

**Internet Gateway Setup**:

```bash
# Create Internet Gateway
aws ec2 create-internet-gateway --tag-specifications 'ResourceType=internet-gateway,Tags=[{Key=Name,Value=glassentials-igw}]'

# Note IGW ID
export IGW_ID="igw-xxxxx"

# Attach to VPC
aws ec2 attach-internet-gateway --internet-gateway-id $IGW_ID --vpc-id $VPC_ID
```

**Route Tables**:

```bash
# Create public route table
aws ec2 create-route-table --vpc-id $VPC_ID --tag-specifications 'ResourceType=route-table,Tags=[{Key=Name,Value=public-rt}]'

export PUBLIC_RT_ID="rtb-xxxxx"

# Add route to Internet Gateway
aws ec2 create-route --route-table-id $PUBLIC_RT_ID --destination-cidr-block 0.0.0.0/0 --gateway-id $IGW_ID

# Associate public subnets with public route table
aws ec2 associate-route-table --subnet-id $PUBLIC_SUBNET_1A --route-table-id $PUBLIC_RT_ID
aws ec2 associate-route-table --subnet-id $PUBLIC_SUBNET_1B --route-table-id $PUBLIC_RT_ID
```

### 2. Security Groups

**Application Security Group** (for EC2 instances):

```bash
aws ec2 create-security-group \
  --group-name glassentials-app-sg \
  --description "Security group for GlassEntials Django app" \
  --vpc-id $VPC_ID

export APP_SG_ID="sg-xxxxx"

# Allow HTTP from ALB
aws ec2 authorize-security-group-ingress \
  --group-id $APP_SG_ID \
  --protocol tcp \
  --port 8000 \
  --source-security-group-id $APP_SG_ID  # from ALB SG

# Allow SSH (restrict to your IP)
aws ec2 authorize-security-group-ingress \
  --group-id $APP_SG_ID \
  --protocol tcp \
  --port 22 \
  --cidr 0.0.0.0/0  # ⚠️ Restrict to your IP in production
```

**ALB Security Group**:

```bash
aws ec2 create-security-group \
  --group-name glassentials-alb-sg \
  --description "Security group for ALB" \
  --vpc-id $VPC_ID

export ALB_SG_ID="sg-xxxxx"

# Allow HTTP
aws ec2 authorize-security-group-ingress \
  --group-id $ALB_SG_ID \
  --protocol tcp \
  --port 80 \
  --cidr 0.0.0.0/0

# Allow HTTPS
aws ec2 authorize-security-group-ingress \
  --group-id $ALB_SG_ID \
  --protocol tcp \
  --port 443 \
  --cidr 0.0.0.0/0
```

**RDS Security Group**:

```bash
aws ec2 create-security-group \
  --group-name glassentials-rds-sg \
  --description "Security group for RDS PostgreSQL" \
  --vpc-id $VPC_ID

export RDS_SG_ID="sg-xxxxx"

# Allow PostgreSQL from app servers
aws ec2 authorize-security-group-ingress \
  --group-id $RDS_SG_ID \
  --protocol tcp \
  --port 5432 \
  --source-security-group-id $APP_SG_ID
```

### 3. S3 for Static & Media Files

```bash
# Create S3 bucket for static files
aws s3 mb s3://glassentials-static-${AWS_ACCOUNT_ID} --region us-east-1

# Create S3 bucket for media uploads
aws s3 mb s3://glassentials-media-${AWS_ACCOUNT_ID} --region us-east-1

# Block public access (media files)
aws s3api put-public-access-block \
  --bucket glassentials-media-${AWS_ACCOUNT_ID} \
  --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

# Enable versioning for backups
aws s3api put-bucket-versioning \
  --bucket glassentials-static-${AWS_ACCOUNT_ID} \
  --versioning-configuration Status=Enabled
```

---

## Database Configuration

### 1. RDS PostgreSQL Setup

**Create DB Subnet Group**:

```bash
aws rds create-db-subnet-group \
  --db-subnet-group-name glassentials-db-subnet \
  --db-subnet-group-description "Subnet group for GlassEntials RDS" \
  --subnet-ids subnet-1a subnet-1b
```

**Launch RDS PostgreSQL Instance**:

```bash
aws rds create-db-instance \
  --db-instance-identifier glassentials-db \
  --db-instance-class db.t3.small \
  --engine postgres \
  --engine-version 15.4 \
  --master-username glassadmin \
  --master-user-password 'YourSecurePassword123!' \
  --allocated-storage 100 \
  --storage-type gp3 \
  --db-subnet-group-name glassentials-db-subnet \
  --vpc-security-group-ids $RDS_SG_ID \
  --multi-az \
  --backup-retention-period 30 \
  --preferred-backup-window "03:00-04:00" \
  --preferred-maintenance-window "sun:04:00-sun:05:00" \
  --enable-cloudwatch-logs-exports '["postgresql"]' \
  --tags Key=Name,Value=glassentials-db
```

**Alternative: Using AWS Secrets Manager for password**:

```bash
# Store DB password securely
aws secretsmanager create-secret \
  --name glassentials/db/password \
  --secret-string '{"username":"glassadmin","password":"YourSecurePassword123!"}'
```

### 2. Database Initialization

**Connect to RDS and create application database**:

```bash
# Get RDS endpoint
export RDS_ENDPOINT=$(aws rds describe-db-instances \
  --db-instance-identifier glassentials-db \
  --query 'DBInstances[0].Endpoint.Address' \
  --output text)

# Connect via psql
psql -h $RDS_ENDPOINT -U glassadmin -d postgres

# Inside psql:
CREATE DATABASE glassentials_prod;
CREATE USER glassentials_user WITH PASSWORD 'AppUserPassword123!';
GRANT ALL PRIVILEGES ON DATABASE glassentials_prod TO glassentials_user;
ALTER USER glassentials_user CREATEDB;
\q
```

### 3. Django Settings for RDS

Update your `HRMS_Glassentials/settings.py`:

```python
import os
from pathlib import Path

# Database Configuration for Production
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME', 'glassentials_prod'),
        'USER': os.getenv('DB_USER', 'glassentials_user'),
        'PASSWORD': os.getenv('DB_PASSWORD'),
        'HOST': os.getenv('DB_HOST'),  # RDS Endpoint
        'PORT': os.getenv('DB_PORT', '5432'),
        'ATOMIC_REQUESTS': True,
        'CONN_MAX_AGE': 600,
        'OPTIONS': {
            'sslmode': 'require',  # SSL connection to RDS
        }
    }
}

# Static Files (S3)
AWS_STORAGE_BUCKET_NAME = 'glassentials-static-{account-id}'
AWS_S3_REGION_NAME = 'us-east-1'
AWS_S3_CUSTOM_DOMAIN = f'{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com'
STATIC_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/static/'
STATICFILES_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'

# Media Files (S3)
AWS_MEDIA_BUCKET_NAME = 'glassentials-media-{account-id}'
MEDIA_URL = f'https://{AWS_MEDIA_BUCKET_NAME}.s3.amazonaws.com/media/'
DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'

# Security Headers
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Allowed Hosts
ALLOWED_HOSTS = [
    'your-domain.com',
    'www.your-domain.com',
    'alb-dns-name.us-east-1.elb.amazonaws.com',
]

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}
```

---

## Application Deployment

### 1. Prepare Application Code

**Create requirements file** (if not exists):

```bash
pip freeze > requirements.txt
```

**Add production dependencies**:

```bash
# Add to requirements.txt:
gunicorn==21.2.0
psycopg2-binary==2.9.9
boto3==1.28.70
django-storages==1.14.2
python-dotenv==1.0.0
whitenoise==6.6.0
```

**Install locally first**:

```bash
pip install -r requirements.txt
python manage.py collectstatic --noinput
```

### 2. Create EC2 AMI (Amazon Machine Image)

**Launch base Ubuntu instance**:

```bash
# Get latest Ubuntu 22.04 LTS AMI ID
export AMI_ID="ami-0c55b159cbfafe1f0"

aws ec2 run-instances \
  --image-id $AMI_ID \
  --instance-type t3.medium \
  --key-name your-key-pair \
  --security-group-ids $APP_SG_ID \
  --subnet-id $PRIVATE_SUBNET_1A \
  --iam-instance-profile Name=glassentials-ec2-role \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=glassentials-app-base}]'
```

**SSH into instance and install dependencies**:

```bash
#!/bin/bash
# On EC2 instance:

# Update system
sudo apt-get update && sudo apt-get upgrade -y

# Install Python & dependencies
sudo apt-get install -y python3.11 python3-pip python3-venv
sudo apt-get install -y postgresql-client libpq-dev
sudo apt-get install -y git curl wget

# Create app user
sudo useradd -m -s /bin/bash glassentials

# Create application directory
sudo mkdir -p /var/www/glassentials
sudo chown -R glassentials:glassentials /var/www/glassentials
```

**Setup application**:

```bash
# As glassentials user:
cd /var/www/glassentials

# Clone repository
git clone https://your-repo-url.git .

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt
```

**Create environment file**:

```bash
# /var/www/glassentials/.env (set proper permissions)
DB_HOST=your-rds-endpoint.us-east-1.rds.amazonaws.com
DB_PORT=5432
DB_NAME=glassentials_prod
DB_USER=glassentials_user
DB_PASSWORD=your-secure-password

AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
AWS_STORAGE_BUCKET_NAME=glassentials-static-xxxxx
AWS_MEDIA_BUCKET_NAME=glassentials-media-xxxxx

SECRET_KEY=your-django-secret-key
DEBUG=False
ALLOWED_HOSTS=your-domain.com,www.your-domain.com
```

**Create Gunicorn systemd service**:

```bash
# /etc/systemd/system/glassentials.service
[Unit]
Description=GlassEntials Django Application
After=network.target

[Service]
User=glassentials
WorkingDirectory=/var/www/glassentials
Environment="PATH=/var/www/glassentials/venv/bin"
EnvironmentFile=/var/www/glassentials/.env
ExecStart=/var/www/glassentials/venv/bin/gunicorn \
    --workers 4 \
    --worker-class sync \
    --bind 0.0.0.0:8000 \
    --timeout 60 \
    --access-logfile - \
    --error-logfile - \
    HRMS_Glassentials.wsgi:application

Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Enable and start service**:

```bash
sudo systemctl daemon-reload
sudo systemctl enable glassentials
sudo systemctl start glassentials
```

### 3. Create Custom AMI

```bash
# Get instance ID
export INSTANCE_ID="i-xxxxx"

# Create AMI from instance
aws ec2 create-image \
  --instance-id $INSTANCE_ID \
  --name "glassentials-django-app" \
  --description "GlassEntials Django application ready for production"

# Note the AMI ID
export CUSTOM_AMI_ID="ami-xxxxx"
```

### 4. Auto Scaling Configuration

**Create Launch Template**:

```bash
aws ec2 create-launch-template \
  --launch-template-name glassentials-lt \
  --version-description "GlassEntials production template" \
  --launch-template-data '{
    "ImageId":"'$CUSTOM_AMI_ID'",
    "InstanceType":"t3.medium",
    "KeyName":"your-key-pair",
    "SecurityGroupIds":["'$APP_SG_ID'"],
    "IamInstanceProfile":{"Arn":"arn:aws:iam::ACCOUNT_ID:instance-profile/glassentials-ec2-role"},
    "TagSpecifications":[{
      "ResourceType":"instance",
      "Tags":[{"Key":"Name","Value":"glassentials-app-asg"}]
    }]
  }'
```

**Create Auto Scaling Group**:

```bash
aws autoscaling create-auto-scaling-group \
  --auto-scaling-group-name glassentials-asg \
  --launch-template LaunchTemplateName=glassentials-lt \
  --min-size 2 \
  --max-size 6 \
  --desired-capacity 2 \
  --default-cooldown 300 \
  --health-check-type ELB \
  --health-check-grace-period 300 \
  --vpc-zone-identifier "subnet-1a,subnet-1b" \
  --target-group-arns arn:aws:elasticloadbalancing:us-east-1:ACCOUNT_ID:targetgroup/glassentials-tg/xxxxx
```

**Scaling Policies**:

```bash
# Create scaling policy for CPU
aws autoscaling put-scaling-policy \
  --auto-scaling-group-name glassentials-asg \
  --policy-name scale-up-cpu \
  --policy-type TargetTrackingScaling \
  --target-tracking-configuration '{
    "TargetValue":70.0,
    "PredefinedMetricSpecification":{"PredefinedMetricType":"ASGAverageCPUUtilization"},
    "ScaleOutCooldown":60,
    "ScaleInCooldown":300
  }'
```

---

## Load Balancing & SSL

### 1. Application Load Balancer

**Create Load Balancer**:

```bash
aws elbv2 create-load-balancer \
  --name glassentials-alb \
  --subnets $PUBLIC_SUBNET_1A $PUBLIC_SUBNET_1B \
  --security-groups $ALB_SG_ID \
  --scheme internet-facing \
  --type application \
  --tags Key=Name,Value=glassentials-alb

export ALB_ARN="arn:aws:elasticloadbalancing:us-east-1:ACCOUNT_ID:loadbalancer/app/glassentials-alb/xxxxx"
```

**Create Target Group**:

```bash
aws elbv2 create-target-group \
  --name glassentials-tg \
  --protocol HTTP \
  --port 8000 \
  --vpc-id $VPC_ID \
  --health-check-enabled \
  --health-check-protocol HTTP \
  --health-check-path /health/ \
  --health-check-interval-seconds 30 \
  --health-check-timeout-seconds 5 \
  --healthy-threshold-count 2 \
  --unhealthy-threshold-count 3

export TARGET_GROUP_ARN="arn:aws:elasticloadbalancing:us-east-1:ACCOUNT_ID:targetgroup/glassentials-tg/xxxxx"
```

**Create Listeners**:

```bash
# HTTP listener (redirect to HTTPS)
aws elbv2 create-listener \
  --load-balancer-arn $ALB_ARN \
  --protocol HTTP \
  --port 80 \
  --default-actions Type=redirect,RedirectConfig='{Protocol=HTTPS,Port=443,StatusCode=HTTP_301}'

# HTTPS listener (requires SSL certificate)
aws elbv2 create-listener \
  --load-balancer-arn $ALB_ARN \
  --protocol HTTPS \
  --port 443 \
  --certificates CertificateArn=arn:aws:acm:us-east-1:ACCOUNT_ID:certificate/xxxxx \
  --default-actions Type=forward,TargetGroupArn=$TARGET_GROUP_ARN
```

### 2. SSL/TLS Certificate (AWS Certificate Manager)

**Request SSL Certificate**:

```bash
aws acm request-certificate \
  --domain-name your-domain.com \
  --subject-alternative-names www.your-domain.com \
  --validation-method DNS

# Note the Certificate ARN
export CERT_ARN="arn:aws:acm:us-east-1:ACCOUNT_ID:certificate/xxxxx"
```

**Validate Certificate via DNS**:

```bash
# Get validation details
aws acm describe-certificate --certificate-arn $CERT_ARN

# Add CNAME record to your DNS provider based on validation details
```

### 3. CloudFront CDN Distribution (Optional)

```bash
# Create CloudFront distribution for static assets
aws cloudfront create-distribution \
  --distribution-config '{
    "CallerReference":"glassentials-'$(date +%s)'",
    "Enabled":true,
    "Origins":{
      "Quantity":1,
      "Items":[{
        "Id":"S3-glassentials-static",
        "DomainName":"glassentials-static-xxxxx.s3.amazonaws.com",
        "S3OriginConfig":{"OriginAccessIdentity":""}
      }]
    },
    "DefaultCacheBehavior":{
      "TargetOriginId":"S3-glassentials-static",
      "ViewerProtocolPolicy":"redirect-to-https",
      "AllowedMethods":["GET","HEAD"],
      "CachePolicyId":"658327ea-f89d-4fab-a63d-7e88639e58f6"
    }
  }'
```

---

## Monitoring & Logging

### 1. CloudWatch Setup

**Enable Application Logging**:

```python
# In settings.py
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{levelname}] {asctime} {name} - {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': True,
        },
    },
}
```

**Create CloudWatch Log Groups**:

```bash
# Application logs
aws logs create-log-group --log-group-name /aws/glassentials/app

# ALB logs
aws logs create-log-group --log-group-name /aws/glassentials/alb

# RDS logs (already enabled during creation)
```

### 2. CloudWatch Alarms

```bash
# High CPU utilization alarm
aws cloudwatch put-metric-alarm \
  --alarm-name glassentials-high-cpu \
  --alarm-description "Alert when CPU exceeds 80%" \
  --metric-name CPUUtilization \
  --namespace AWS/EC2 \
  --statistic Average \
  --period 300 \
  --threshold 80 \
  --comparison-operator GreaterThanThreshold \
  --alarm-actions arn:aws:sns:us-east-1:ACCOUNT_ID:glassentials-alerts

# RDS database connections alarm
aws cloudwatch put-metric-alarm \
  --alarm-name glassentials-db-connections \
  --alarm-description "Alert on high database connections" \
  --metric-name DatabaseConnections \
  --namespace AWS/RDS \
  --statistic Average \
  --period 300 \
  --threshold 80 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=DBInstanceIdentifier,Value=glassentials-db
```

### 3. SNS Notifications

```bash
# Create SNS topic for alerts
aws sns create-topic --name glassentials-alerts

export SNS_TOPIC_ARN="arn:aws:sns:us-east-1:ACCOUNT_ID:glassentials-alerts"

# Subscribe email
aws sns subscribe \
  --topic-arn $SNS_TOPIC_ARN \
  --protocol email \
  --notification-endpoint your-email@example.com
```

---

## Scaling & Performance

### 1. Database Query Optimization

```python
# In Django models
class Employee(models.Model):
    # ... fields ...
    
    class Meta:
        indexes = [
            models.Index(fields=['department', 'is_active']),
            models.Index(fields=['created_at']),
        ]

# Use select_related and prefetch_related
employees = Employee.objects.select_related('department', 'designation').prefetch_related('leaves_set')
```

### 2. Caching Strategy

```python
# settings.py - Redis caching
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://elasticache-endpoint:6379/1',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        }
    }
}

# Use caching
from django.views.decorators.cache import cache_page

@cache_page(60 * 5)  # Cache for 5 minutes
def employee_list(request):
    return render(request, 'employees.html', {'employees': Employee.objects.all()})
```

### 3. ElastiCache (Redis) for Caching

```bash
# Create Redis cluster
aws elasticache create-cache-cluster \
  --cache-cluster-id glassentials-redis \
  --cache-node-type cache.t3.micro \
  --engine redis \
  --engine-version 7.0 \
  --num-cache-nodes 1 \
  --security-group-ids $CACHE_SG_ID
```

---

## Backup & Disaster Recovery

### 1. RDS Automated Backups

Already configured during RDS creation:
- **Retention**: 30 days
- **Backup Window**: 03:00-04:00 UTC
- **Multi-AZ**: Enabled

### 2. Manual Snapshots

```bash
# Create manual snapshot
aws rds create-db-snapshot \
  --db-instance-identifier glassentials-db \
  --db-snapshot-identifier glassentials-db-snapshot-$(date +%Y%m%d)

# List snapshots
aws rds describe-db-snapshots \
  --db-instance-identifier glassentials-db

# Copy snapshot to another region (disaster recovery)
aws rds copy-db-snapshot \
  --source-db-snapshot-identifier arn:aws:rds:us-east-1:ACCOUNT_ID:snapshot:glassentials-db-snapshot-xxxxx \
  --target-db-snapshot-identifier glassentials-db-snapshot-dr \
  --source-region us-east-1 \
  --destination-region us-west-2
```

### 3. S3 Backup Strategy

```bash
# Enable versioning (already done)
# Create lifecycle policy to archive old versions

aws s3api put-bucket-lifecycle-configuration \
  --bucket glassentials-static-xxxxx \
  --lifecycle-configuration '{
    "Rules":[{
      "Id":"archive-old-versions",
      "Status":"Enabled",
      "NoncurrentVersionTransitions":[{
        "NoncurrentDays":30,
        "StorageClass":"GLACIER"
      }],
      "NoncurrentVersionExpiration":{"NoncurrentDays":90}
    }]
  }'
```

### 4. Disaster Recovery Plan

| Component | Recovery Method | RTO | RPO |
|-----------|-----------------|-----|-----|
| **RDS Database** | Multi-AZ failover + snapshots | 2-5 min | < 1 min |
| **Static Files (S3)** | Cross-region replication | 1 hour | Real-time |
| **Application Code** | ASG with new AMI | 5-10 min | Current commit |
| **Media Files** | S3 versioning + Glacier backup | 24 hours | Daily |

---

## Security Best Practices

### 1. IAM Roles & Policies

**Create EC2 Instance Role**:

```json
// /tmp/ec2-trust-policy.json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "ec2.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}

// /tmp/ec2-policy.json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject"
      ],
      "Resource": [
        "arn:aws:s3:::glassentials-static-*/*",
        "arn:aws:s3:::glassentials-media-*/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue"
      ],
      "Resource": "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:glassentials/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:us-east-1:ACCOUNT_ID:log-group:/aws/glassentials/*"
    }
  ]
}
```

```bash
aws iam create-role --role-name glassentials-ec2-role --assume-role-policy-document file:///tmp/ec2-trust-policy.json

aws iam put-role-policy --role-name glassentials-ec2-role --policy-name glassentials-policy --policy-document file:///tmp/ec2-policy.json

aws iam create-instance-profile --instance-profile-name glassentials-ec2-role

aws iam add-role-to-instance-profile --instance-profile-name glassentials-ec2-role --role-name glassentials-ec2-role
```

### 2. Secrets Management

```bash
# Store secrets in AWS Secrets Manager
aws secretsmanager create-secret \
  --name glassentials/django/secret-key \
  --secret-string 'your-django-secret-key'

# Retrieve in Django
import boto3

client = boto3.client('secretsmanager')
response = client.get_secret_value(SecretId='glassentials/django/secret-key')
SECRET_KEY = response['SecretString']
```

### 3. VPC Endpoint for S3

```bash
# Create VPC endpoint for S3 (private access)
aws ec2 create-vpc-endpoint \
  --vpc-id $VPC_ID \
  --service-name com.amazonaws.us-east-1.s3 \
  --route-table-ids rtb-xxxxx
```

### 4. WAF (Web Application Firewall)

```bash
# Create WAF WebACL
aws wafv2 create-web-acl \
  --name glassentials-waf \
  --region us-east-1 \
  --scope REGIONAL \
  --default-action Block={} \
  --rules file:///tmp/waf-rules.json \
  --visibility-config SampledRequestsEnabled=true,CloudWatchMetricsEnabled=true,MetricName=GlassentalsWAF

# Associate with ALB
aws wafv2 associate-web-acl \
  --web-acl-arn arn:aws:wafv2:us-east-1:ACCOUNT_ID:regional/webacl/glassentials-waf/xxxxx \
  --resource-arn $ALB_ARN
```

### 5. Security Group Hardening

```bash
# Restrict SSH to specific IP only
aws ec2 revoke-security-group-ingress \
  --group-id $APP_SG_ID \
  --protocol tcp \
  --port 22 \
  --cidr 0.0.0.0/0

aws ec2 authorize-security-group-ingress \
  --group-id $APP_SG_ID \
  --protocol tcp \
  --port 22 \
  --cidr YOUR_IP/32
```

---

## Troubleshooting

### Common Issues & Solutions

#### 1. Application Instances Unhealthy

```bash
# Check health
aws elbv2 describe-target-health \
  --target-group-arn $TARGET_GROUP_ARN

# SSH into instance and check logs
systemctl status glassentials
journalctl -u glassentials -n 50

# Check application logs
tail -f /var/log/syslog | grep glassentials
```

#### 2. Database Connection Errors

```bash
# Test connectivity from EC2
psql -h $RDS_ENDPOINT -U glassentials_user -d glassentials_prod

# Check RDS security group
aws ec2 describe-security-groups --group-ids $RDS_SG_ID

# Verify parameter group settings
aws rds describe-db-instances --db-instance-identifier glassentials-db
```

#### 3. Static Files Not Loading

```bash
# Verify S3 bucket permissions
aws s3api get-bucket-acl --bucket glassentials-static-xxxxx

# Check CloudFront cache
aws cloudfront get-distribution --id XXXXX

# Manually sync static files to S3
python manage.py collectstatic --noinput
aws s3 sync ./static s3://glassentials-static-xxxxx/static/
```

#### 4. High Memory Usage

```bash
# Check Gunicorn workers
ps aux | grep gunicorn

# Reduce workers if needed
# Edit /etc/systemd/system/glassentials.service
# --workers 2 (instead of 4)
```

### Diagnostic Commands

```bash
# Get ALB DNS name
aws elbv2 describe-load-balancers --names glassentials-alb --query 'LoadBalancers[0].DNSName'

# Check Auto Scaling Group status
aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names glassentials-asg

# View recent CloudWatch logs
aws logs tail /aws/glassentials/app --follow

# Get RDS endpoint
aws rds describe-db-instances --db-instance-identifier glassentials-db --query 'DBInstances[0].Endpoint.Address'
```

---

## Cost Optimization

### 1. Reserved Instances

```bash
# Purchase 1-year reserved instances for consistent usage
aws ec2 purchase-reserved-instances \
  --instance-count 2 \
  --instance-type t3.medium \
  --offering-class standard \
  --purchase-type one-year \
  --instance-tenancy default
```

### 2. RDS Optimization

- Use `db.t3.small` for development, `db.r6i.large` for production
- Enable automated minor version upgrades
- Use read replicas for reporting workloads
- Archive old data to S3

### 3. S3 Storage Optimization

- Use S3 Intelligent-Tiering for variable access patterns
- Enable S3 Lifecycle policies
- Use CloudFront to reduce data transfer costs

### 4. ALB Optimization

- Combine multiple applications on single ALB
- Use target groups efficiently
- Enable access logging only in production

### 5. Cost Monitoring

```bash
# Create a budget
aws budgets create-budget \
  --account-id ACCOUNT_ID \
  --budget file:///tmp/budget.json

# View cost anomalies
aws ce list-cost-allocation-tags --status Inactive
```

---

## Maintenance & Updates

### 1. Regular Updates

```bash
# Update security patches on EC2 instances (automated via Systems Manager)
aws ssm create-document \
  --content file:///tmp/patch-manager-document.json \
  --name glassentials-patch-policy \
  --document-type Command

# Update Django dependencies
pip install -U -r requirements.txt
python manage.py migrate
```

### 2. Blue-Green Deployments

```bash
# Create new ASG with updated AMI
# Update ALB to point to new ASG
# Monitor for errors
# Switch back if needed
```

### 3. Database Maintenance

```bash
# Perform maintenance window tasks
aws rds modify-db-instance \
  --db-instance-identifier glassentials-db \
  --preferred-maintenance-window sun:04:00-sun:05:00 \
  --apply-immediately
```

---

## Checklist for Production Deployment

- [ ] VPC and subnets configured
- [ ] Security groups with minimal permissions
- [ ] RDS PostgreSQL configured with Multi-AZ
- [ ] Database initialized with migrations
- [ ] S3 buckets created and versioning enabled
- [ ] Django settings configured for production
- [ ] Gunicorn service file created
- [ ] Custom AMI built and tested
- [ ] ALB and target groups configured
- [ ] SSL certificate installed and verified
- [ ] Auto Scaling Group configured
- [ ] CloudWatch alarms and monitoring enabled
- [ ] SNS topic for alerts configured
- [ ] Backups and disaster recovery plan tested
- [ ] WAF rules deployed
- [ ] IAM roles with least privilege
- [ ] Secrets stored in Secrets Manager
- [ ] Load balancing and health checks verified
- [ ] Performance testing completed
- [ ] Documentation updated

---

## Support & Further Resources

- [AWS Documentation](https://docs.aws.amazon.com/)
- [Django Deployment Guide](https://docs.djangoproject.com/en/stable/howto/deployment/)
- [AWS Well-Architected Framework](https://aws.amazon.com/architecture/well-architected/)
- [GlassEntials Internal Wiki](https://wiki.glassentials.internal)

---

<div align="center">
  <p><strong>GlassEntials Premium HRMS - AWS Deployment Guide</strong></p>
  <p><em>© 2026 GlassEntials Platform. Internal Enterprise Documentation.</em></p>
  <p><em>Last Updated: May 2026</em></p>
</div>
